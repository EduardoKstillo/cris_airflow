"""
Cargador de Datos a PostgreSQL - SMART UPSERT FASE 2
Soporte multiplataforma con resolución dinámica de entorno.
"""
import os
import sys
import re
import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
import pandas as pd
from sqlalchemy import create_engine, text, inspect
from dotenv import load_dotenv

BASE_DIR = Path(os.getenv('AIRFLOW_HOME', Path(__file__).resolve().parent.parent.parent))
ENV_FILE = BASE_DIR / '.env'
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)

logger = logging.getLogger(__name__)


class PostgresLoader:
    def __init__(self, connection_string: Optional[str] = None):
        if connection_string:
            self.connection_string = connection_string
        else:
            host = os.getenv('POSTGRES_HOST', 'postgres')
            port = os.getenv('POSTGRES_PORT', '5432')
            db = os.getenv('POSTGRES_DB', 'airflow')
            user = os.getenv('POSTGRES_USER', 'airflow')
            password = os.getenv('POSTGRES_PASSWORD', 'airflow')

            if not all([host, db, user, password]):
                raise ValueError("Faltan credenciales de PostgreSQL en entorno")

            self.connection_string = f"postgresql://{user}:{password}@{host}:{port}/{db}"

        self.engine = None
        self.schema = 'public'
        self.stats = {'tables_created': 0, 'records_inserted': {}, 'skipped_duplicates': {}, 'errors': []}
        
        self.uuid_cache = {
            'organizations': {}, 'persons': {}, 'projects': {}, 
            'funding_sources': {}, 'funding_calls': {}, 'funding_grants': {}
        }
        self.audit_trail = []

        self.BUSINESS_RULES = {
            'organizations': {
                'action': 'upsert',
                'conflict_key': 'code',
                'protected_cols': ['id', 'code', 'dspace_uuid', 'dspace_handle', 'created_at', 'updated_at', 'sync_status']
            },
            'projects': {
                'action': 'upsert',
                'conflict_key': 'project_code',
                'fuzzy_match': True,  
                'protected_cols': ['id', 'project_code', 'dspace_uuid', 'dspace_handle', 'ocde_classification', 'ocde_knowledge_field', 'ocde_activity_type', 'created_at', 'updated_at', 'sync_status']
            },
            'persons': {
                'action': 'upsert',
                'conflict_key': 'dni',
                'protected_cols': ['id', 'dni', 'orcid', 'scopus_author_id', 'researcher_id', 'link_cti_vitae', 'dspace_uuid', 'dspace_handle', 'created_at', 'updated_at', 'sync_status']
            },
            'funding_sources': {
                'action': 'upsert',
                'conflict_key': 'abbreviation',
                'protected_cols': ['id', 'abbreviation', 'dspace_uuid', 'dspace_handle', 'created_at', 'updated_at', 'sync_status']
            },
            'funding_calls': {
                'action': 'upsert',
                'conflict_key': 'call_code',
                'protected_cols': ['id', 'call_code', 'dspace_uuid', 'dspace_handle', 'created_at', 'updated_at', 'sync_status']
            },
            'funding_grants': {
                'action': 'upsert',
                'conflict_key': 'contract_number',
                'fuzzy_match': True,
                'protected_cols': ['id', 'contract_number', 'dspace_uuid', 'dspace_handle', 'created_at', 'updated_at', 'sync_status']
            },
            'project_researchers': {
                'action': 'sync_exact',
                'check_keys': ['project_id', 'researcher_id'] 
            },
            'research_areas': {
                'action': 'sync_exact',
                'check_keys': ['project_id', 'area_code']
            },
            'person_organization_affiliations': {
                'action': 'ignore_if_exists',
                'check_keys': ['person_id', 'organization_id']
            }
        }

    def connect(self) -> bool:
        try:
            self.engine = create_engine(self.connection_string, pool_pre_ping=True, pool_recycle=3600, echo=False)
            with self.engine.connect() as conn:
                version = conn.execute(text("SELECT version()")).fetchone()[0]
                logger.info(f"✅ Conectado a PostgreSQL ({version[:40]}...)")
            return True
        except Exception as e:
            logger.error(f"❌ Error conectando a PostgreSQL: {e}")
            return False

    def truncate_all_tables(self, schema: str = None) -> bool:
        if schema is None: schema = self.schema
        logger.warning(f"⚠️ Iniciando TRUNCATE en esquema '{schema}'...")
        if not self.engine and not self.connect(): return False
        
        tables_to_clear = ['research_areas', 'project_researchers', 'projects', 'funding_grants', 'funding_calls', 'funding_sources', 'person_organization_affiliations', 'persons', 'organizations']
        
        try:
            with self.engine.begin() as conn:
                conn.execute(text("SET CONSTRAINTS ALL DEFERRED"))
                for table in tables_to_clear:
                    if self._table_exists(table, schema):
                        try:
                            conn.execute(text(f"TRUNCATE TABLE {schema}.{table} RESTART IDENTITY CASCADE"))
                            logger.info(f"   ✅ {table} limpiada")
                        except Exception as e:
                            logger.warning(f"   ⚠️ {table}: {str(e)}")
            return True
        except Exception as e:
            logger.error(f"❌ Error limpiando tablas: {e}")
            return False

    def _clean_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        df_clean = df.copy()
        cleaned_columns = {}
        for col in df_clean.columns:
            clean_col = re.sub(r'_[mxy]\d+$', '', col)
            clean_col = re.sub(r'_[xy]$', '', clean_col)
            cleaned_columns[col] = clean_col
        
        clean_col_values = list(cleaned_columns.values())
        if len(clean_col_values) != len(set(clean_col_values)):
            seen = set()
            final_columns = {}
            cols_to_drop = []
            for orig_col, clean_col in cleaned_columns.items():
                if clean_col not in seen:
                    final_columns[orig_col] = clean_col
                    seen.add(clean_col)
                else: cols_to_drop.append(orig_col)
            if cols_to_drop: df_clean = df_clean.drop(columns=cols_to_drop)
            cleaned_columns = final_columns
        
        df_clean = df_clean.rename(columns=cleaned_columns)
        df_clean = df_clean.where(pd.notna(df_clean), None)
        
        for col in df_clean.select_dtypes(include=['object']).columns:
            df_clean[col] = df_clean[col].apply(lambda x: x.strip() if isinstance(x, str) else x)
        return df_clean
    
    def _table_exists(self, table_name: str, schema: str = None) -> bool:
        if schema is None: schema = self.schema
        if not self.engine and not self.connect(): raise ConnectionError("No connection")
        return table_name in inspect(self.engine).get_table_names(schema=schema)

    def _get_table_columns(self, table_name: str, schema: str = None) -> List[str]:
        if schema is None: schema = self.schema
        return [col['name'] for col in inspect(self.engine).get_columns(table_name, schema=schema)]

    def _safe_str(self, val) -> Optional[str]:
        if pd.isna(val): return None
        v = str(val).strip()
        if v == '': return None
        if v.endswith('.0'): return v[:-2]
        return v

    def _build_uuid_cache(self, schema: str = 'public'):
        for key in self.uuid_cache: self.uuid_cache[key].clear()
        
        try:
            with self.engine.connect() as conn:
                for row in conn.execute(text(f"SELECT id, code FROM {schema}.organizations WHERE code IS NOT NULL")):
                    self.uuid_cache['organizations'][str(row.code)] = str(row.id)

                for row in conn.execute(text(f"SELECT id, sismo_id FROM {schema}.persons WHERE sismo_id IS NOT NULL")):
                    self.uuid_cache['persons'][str(row.sismo_id)] = str(row.id)
                
                for row in conn.execute(text(f"SELECT id, sismo_project_id FROM {schema}.projects WHERE sismo_project_id IS NOT NULL")):
                    self.uuid_cache['projects'][str(row.sismo_project_id)] = str(row.id)
                
                for row in conn.execute(text(f"SELECT id, sismo_funding_source_id FROM {schema}.funding_sources WHERE sismo_funding_source_id IS NOT NULL")):
                    self.uuid_cache['funding_sources'][str(row.sismo_funding_source_id)] = str(row.id)
                
                for row in conn.execute(text(f"SELECT id, sismo_call_id FROM {schema}.funding_calls WHERE sismo_call_id IS NOT NULL")):
                    self.uuid_cache['funding_calls'][str(row.sismo_call_id)] = str(row.id)
                
                for row in conn.execute(text(f"SELECT id, sismo_contract_id FROM {schema}.funding_grants WHERE sismo_contract_id IS NOT NULL")):
                    self.uuid_cache['funding_grants'][str(row.sismo_contract_id)] = str(row.id)
                
        except Exception as e:
            logger.error(f"❌ Error construyendo caché: {e}")

    def _normalize_text(self, text: str) -> str:
        if not text or pd.isna(text): return ""
        t = str(text).lower()
        accents = {'á':'a', 'é':'e', 'í':'i', 'ó':'o', 'ú':'u', 'ü':'u', 'ñ':'n'}
        for k, v in accents.items(): t = t.replace(k, v)
        t = re.sub(r'[^a-z0-9]', '', t)
        return t

    def _find_matching_db_record(self, sismo_text: str, db_records: List[Tuple]) -> Optional[Tuple]:
        norm_sismo = self._normalize_text(sismo_text)
        if len(norm_sismo) < 15: return None
        
        for db_id, db_code, db_text in db_records:
            norm_db = self._normalize_text(db_text)
            if norm_sismo == norm_db: return db_id, db_code
            
        for db_id, db_code, db_text in db_records:
            norm_db = self._normalize_text(db_text)
            if len(norm_db) >= 15:
                if norm_sismo in norm_db or norm_db in norm_sismo:
                    return db_id, db_code
        return None

    def _align_business_keys(self, df: pd.DataFrame, entity_name: str, schema: str) -> pd.DataFrame:
        rule = self.BUSINESS_RULES.get(entity_name)
        if df.empty or not rule or not rule.get('fuzzy_match'): return df
            
        df_aligned = df.copy()
        try:
            with self.engine.begin() as conn:
                if entity_name == 'projects':
                    res = conn.execute(text(f"SELECT id, project_code, title FROM {schema}.projects"))
                    db_records = [(row.id, str(row.project_code).strip(), row.title) for row in res if row.title]
                    existing_codes = {r[1] for r in db_records}
                    
                    for idx, row in df_aligned.iterrows():
                        sismo_code = str(row.get('project_code', '')).strip()
                        sismo_title = str(row.get('title', '')).strip()
                        
                        if not sismo_code or not sismo_title: continue
                        if sismo_code in existing_codes: continue
                        
                        match = self._find_matching_db_record(sismo_title, db_records)
                        if match:
                            db_id, db_code = match
                            if sismo_code != db_code:
                                logger.info(f"   🔄 Alineando Proyecto: '{sismo_title[:45]}...' -> de '{db_code}' a '{sismo_code}'")
                                try:
                                    conn.execute(text(f"UPDATE {schema}.projects SET project_code = :new_code WHERE id = :id"), {"new_code": sismo_code, "id": db_id})
                                    existing_codes.add(sismo_code)
                                except Exception: pass

                elif entity_name == 'funding_grants':
                    res = conn.execute(text(f"SELECT id, contract_number, contract_description FROM {schema}.funding_grants"))
                    db_records = [(row.id, str(row.contract_number).strip(), row.contract_description) for row in res if row.contract_description]
                    existing_codes = {r[1] for r in db_records}
                    
                    for idx, row in df_aligned.iterrows():
                        sismo_code = str(row.get('contract_number', '')).strip()
                        sismo_title = str(row.get('contract_description', '')).strip()
                        
                        if not sismo_code or not sismo_title: continue
                        if sismo_code in existing_codes: continue
                        
                        match = self._find_matching_db_record(sismo_title, db_records)
                        if match:
                            db_id, db_code = match
                            if sismo_code != db_code:
                                logger.info(f"   🔄 Alineando Contrato: '{sismo_title[:45]}...' -> de '{db_code}' a '{sismo_code}'")
                                try:
                                    conn.execute(text(f"UPDATE {schema}.funding_grants SET contract_number = :new_code WHERE id = :id"), {"new_code": sismo_code, "id": db_id})
                                    existing_codes.add(sismo_code)
                                except Exception: pass

        except Exception as e:
            logger.warning(f"⚠️ Fallo general en alineación de llaves para {entity_name}: {e}")
            
        return df_aligned

    def _resolve_foreign_keys(self, df: pd.DataFrame, entity: str) -> pd.DataFrame:
        df_res = df.copy()
        unsa_id = self.uuid_cache['organizations'].get('UNSA')
        
        if entity == 'funding_sources':
            if unsa_id: df_res['organization_id'] = unsa_id

        elif entity == 'calls':
            if 'sismo_funding_source_id' in df_res.columns:
                df_res['funding_source_id'] = df_res['sismo_funding_source_id'].apply(lambda x: self.uuid_cache['funding_sources'].get(self._safe_str(x)))
                df_res = df_res.drop(columns=['sismo_funding_source_id']).dropna(subset=['funding_source_id'])
            if unsa_id: df_res['organization_id'] = unsa_id
        
        elif entity == 'funding_grants':
            if 'sismo_funding_call_id' in df_res.columns:
                df_res['funding_call_id'] = df_res['sismo_funding_call_id'].apply(lambda x: self.uuid_cache['funding_calls'].get(self._safe_str(x)))
                df_res = df_res.drop(columns=['sismo_funding_call_id']).dropna(subset=['funding_call_id'])
            if unsa_id: df_res['organization_id'] = unsa_id
        
        elif entity == 'project_researchers':
            if 'sismo_project_id' in df_res.columns:
                df_res['project_id'] = df_res['sismo_project_id'].apply(lambda x: self.uuid_cache['projects'].get(self._safe_str(x)))
                df_res = df_res.drop(columns=['sismo_project_id'])
            if 'sismo_researcher_id' in df_res.columns:
                df_res['researcher_id'] = df_res['sismo_researcher_id'].apply(lambda x: self.uuid_cache['persons'].get(self._safe_str(x)))
                df_res = df_res.drop(columns=['sismo_researcher_id'])
            if 'sismo_contract_id' in df_res.columns:
                df_res['contract_id'] = df_res['sismo_contract_id'].apply(lambda x: self.uuid_cache['funding_grants'].get(self._safe_str(x)))
                df_res = df_res.drop(columns=['sismo_contract_id'])
            df_res = df_res.dropna(subset=['project_id', 'researcher_id'])

        elif entity == 'projects':
            if 'sismo_contract_id' in df_res.columns:
                df_res['funding_grant_id'] = df_res['sismo_contract_id'].apply(lambda x: self.uuid_cache['funding_grants'].get(self._safe_str(x)))
                df_res = df_res.drop(columns=['sismo_contract_id'])
        
        elif entity == 'research_areas':
            if 'sismo_project_id' in df_res.columns:
                df_res['project_id'] = df_res['sismo_project_id'].apply(lambda x: self.uuid_cache['projects'].get(self._safe_str(x)))
                df_res = df_res.drop(columns=['sismo_project_id']).dropna(subset=['project_id'])

        elif entity == 'person_organization_affiliations':
            df_res['person_id'] = df_res['sismo_researcher_id'].apply(lambda x: self.uuid_cache['persons'].get(self._safe_str(x))) if 'sismo_researcher_id' in df_res.columns else None
            df_res['organization_id'] = df_res['org_code'].apply(lambda x: self.uuid_cache['organizations'].get(str(x).strip())) if 'org_code' in df_res.columns else None
            df_res = df_res.dropna(subset=['person_id', 'organization_id'])
            df_res['person_id'] = df_res['person_id'].astype(str)
            df_res['organization_id'] = df_res['organization_id'].astype(str)
            cols_to_drop = [c for c in ['sismo_researcher_id', 'org_code'] if c in df_res.columns]
            df_res = df_res.drop(columns=cols_to_drop)
        
        return df_res

    def _fetch_existing_records(self, table_name: str, schema: str, conflict_key: str) -> Dict[str, dict]:
        existing_data = {}
        try:
            with self.engine.connect() as conn:
                res = conn.execute(text(f"SELECT * FROM {schema}.{table_name}"))
                for row in res:
                    mapping = dict(row._mapping)
                    key_val = mapping.get(conflict_key)
                    if key_val is not None:
                        existing_data[str(key_val)] = mapping
        except Exception:
            pass
        return existing_data

    def load_dataframe(self, df: pd.DataFrame, table_name: str, schema: str = None, entity_name: str = None) -> int:
        if df.empty: return 0
        schema = schema or self.schema
        if not self.engine and not self.connect(): raise ConnectionError("No DB")
        if not self._table_exists(table_name, schema): raise RuntimeError(f"Tabla {schema}.{table_name} no existe.")

        if entity_name:
            df = self._align_business_keys(df, entity_name, schema)

        if entity_name in ['funding_sources', 'calls', 'funding_grants', 'project_researchers', 'research_areas', 'person_organization_affiliations', 'projects']:
            df = self._resolve_foreign_keys(df, entity_name)
            if df.empty: return 0

        table_columns = self._get_table_columns(table_name, schema)
        df_columns = [col for col in df.columns if col in table_columns]
        if not df_columns: return 0
        
        df_clean = self._clean_dataframe(df[df_columns].copy())
        full_table = f"{schema}.{table_name}"
        
        try:
            logger.info(f"📤 Procesando {len(df_clean)} registros para {full_table} ...")
            start = datetime.now()
            inserted_count = 0
            
            rule = self.BUSINESS_RULES.get(table_name)
            existing_data = {}
            if rule and rule['action'] == 'upsert':
                existing_data = self._fetch_existing_records(table_name, schema, rule['conflict_key'])

            with self.engine.begin() as conn:
                if rule and rule['action'] == 'sync_exact':
                    conn.execute(text(f"TRUNCATE TABLE {full_table} CASCADE"))
                    logger.info(f"🧹 Sincronización Espejo: Tabla {full_table} limpiada.")

                for record in df_clean.to_dict(orient='records'):
                    clean_record = {}
                    for k, v in record.items():
                        if isinstance(v, (list, dict)):
                            clean_record[k] = json.dumps(v, ensure_ascii=False)
                        else:
                            try:
                                if pd.notna(v):
                                    clean_record[k] = v
                            except ValueError:
                                clean_record[k] = v
                    
                    if not clean_record: continue
                    
                    try:
                        if rule and rule['action'] == 'upsert':
                            conflict_key = rule['conflict_key']
                            protected = rule['protected_cols']
                            record_id = str(clean_record.get(conflict_key, 'Desconocido'))

                            diff_str = "Nuevo Registro"
                            action_type = "INSERT"
                            
                            if record_id in existing_data:
                                old_row = existing_data[record_id]
                                changes = []
                                for k, v in clean_record.items():
                                    if k not in protected and k in old_row:
                                        old_v = old_row[k]
                                        if isinstance(old_v, (list, dict)):
                                            old_v = json.dumps(old_v, ensure_ascii=False)

                                        try:
                                            both_null = pd.isna(old_v) and pd.isna(v)
                                        except ValueError:
                                            both_null = False
                                            
                                        if str(old_v) != str(v) and not both_null:
                                            changes.append(f"{k}")
                                
                                if not changes:
                                    continue
                                
                                diff_str = "Actualizado: " + ", ".join(changes)
                                action_type = "UPDATE"

                            update_keys = [k for k in clean_record.keys() if k not in protected and k not in ['sync_status', 'updated_at']]
                            columns = ', '.join(clean_record.keys())
                            placeholders = ', '.join([f":{k}" for k in clean_record.keys()])
                            
                            upd = [f"{k} = EXCLUDED.{k}" for k in update_keys]
                            upd_stmt = ', '.join(upd) + ", sync_status = 'pending_update'::sync_state_enum, updated_at = CURRENT_TIMESTAMP" if upd else "sync_status = 'pending_update'::sync_state_enum, updated_at = CURRENT_TIMESTAMP"
                            
                            sql = text(f"INSERT INTO {full_table} ({columns}) VALUES ({placeholders}) ON CONFLICT ({conflict_key}) DO UPDATE SET {upd_stmt}")
                            conn.execute(sql, clean_record)
                            self.audit_trail.append([table_name, action_type, record_id, diff_str, datetime.now().strftime("%Y-%m-%d %H:%M:%S")])

                        elif rule and rule['action'] == 'ignore_if_exists':
                            missing_keys = [k for k in rule['check_keys'] if k not in clean_record]
                            if missing_keys:
                                logger.warning(f"⚠️ Faltan llaves {missing_keys} en registro relacional para {full_table}. Omitiendo.")
                                continue

                            conditions = " AND ".join([f"{k} = :{k}" for k in rule['check_keys']])
                            check_sql = text(f"SELECT 1 FROM {full_table} WHERE {conditions}")
                            if conn.execute(check_sql, clean_record).fetchone(): 
                                continue 
                            
                            columns = ', '.join(clean_record.keys())
                            placeholders = ', '.join([f":{k}" for k in clean_record.keys()])
                            sql = text(f"INSERT INTO {full_table} ({columns}) VALUES ({placeholders})")
                            conn.execute(sql, clean_record)

                        else:
                            columns = ', '.join(clean_record.keys())
                            placeholders = ', '.join([f":{k}" for k in clean_record.keys()])
                            sql = text(f"INSERT INTO {full_table} ({columns}) VALUES ({placeholders})")
                            conn.execute(sql, clean_record)
                        
                        inserted_count += 1
                        
                    except Exception as sql_e:
                        logger.error(f"❌ Error SQL en {table_name}: {str(sql_e)}")
                        raise sql_e

            duration = (datetime.now() - start).total_seconds()
            logger.info(f"   ✅ {inserted_count} filas procesadas exitosamente en {duration:.2f}s → {full_table}")
            self.stats['records_inserted'][full_table] = inserted_count
            return inserted_count

        except Exception as e:
            logger.error(f"❌ Error crítico procesando DataFrame para {schema}.{table_name}: {str(e)}")
            raise

    def load_all_entities(self, entities: Dict[str, pd.DataFrame], schema: str = None) -> Dict[str, int]:
        schema = schema or self.schema
        logger.info(f"🚀 Iniciando sincronización SMART UPSERT en '{schema}'")

        tm = {
            'organizations': 'organizations', 'researchers': 'persons', 'funding_sources': 'funding_sources',
            'calls': 'funding_calls', 'funding_grants': 'funding_grants', 'projects': 'projects',
            'project_researchers': 'project_researchers', 'research_areas': 'research_areas',
            'person_organization_affiliations': 'person_organization_affiliations'
        }

        results = {}
        logger.info("\n" + "="*70 + "\n📦 FASE 1: Entidades Base\n" + "="*70)
        for e in ['organizations', 'researchers', 'funding_sources']:
            if e in entities and not entities[e].empty: results[e] = self.load_dataframe(entities[e], tm[e], schema, e)
        
        self._build_uuid_cache(schema)
        
        logger.info("\n" + "="*70 + "\n📦 FASE 2: Convocatorias\n" + "="*70)
        if 'calls' in entities and not entities['calls'].empty: results['calls'] = self.load_dataframe(entities['calls'], tm['calls'], schema, 'calls')
        
        self._build_uuid_cache(schema)
        
        logger.info("\n" + "="*70 + "\n📦 FASE 3: Proyectos y Relaciones\n" + "="*70)
        if 'funding_grants' in entities and not entities['funding_grants'].empty: results['funding_grants'] = self.load_dataframe(entities['funding_grants'], tm['funding_grants'], schema, 'funding_grants')
        self._build_uuid_cache(schema)
            
        if 'projects' in entities and not entities['projects'].empty: results['projects'] = self.load_dataframe(entities['projects'], tm['projects'], schema, 'projects')
        self._build_uuid_cache(schema)
        
        for e in ['project_researchers', 'research_areas', 'person_organization_affiliations']:
            if e in entities and not entities[e].empty: results[e] = self.load_dataframe(entities[e], tm[e], schema, e)

        self._log_load_summary(results, schema)
        return results

    def export_sync_audit(self, output_dir: str):
        if not self.audit_trail:
            logger.info("\n   ℹ️ No se detectaron datos nuevos o modificados en la BD en esta ejecución.")
            return

        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        filename = out_path / f"audit_sync_bd_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        try:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['TABLA', 'ACCION', 'CLAVE_IDENTIFICADORA', 'DETALLE_DE_CAMBIOS', 'FECHA_HORA'])
                for record in self.audit_trail:
                    writer.writerow(record)

            logger.info(f"\n   📄 Reporte de auditoría generado ({len(self.audit_trail)} registros): {filename}")
                
        except Exception as e:
            logger.error(f"❌ Error guardando archivo de auditoría: {e}")

    def verify_data_integrity(self, schema: str = None) -> Dict[str, Any]:
        return {}

    def _log_load_summary(self, results: Dict[str, int], schema: str):
        logger.info(f"\n📊 Resumen UPSERT en {schema}:")
        total = sum(results.values())
        for e, c in results.items(): 
            if c > 0:
                logger.info(f"   ✅ {e}: {c} filas impactadas/procesadas") 
            else:
                logger.info(f"   ⚠️ {e}: 0 filas")
        logger.info(f"\n   📈 TOTAL: {total} registros ingresados/actualizados.")

    def get_stats(self) -> Dict[str, Any]: return self.stats
    
    def close(self):
        if self.engine: self.engine.dispose()