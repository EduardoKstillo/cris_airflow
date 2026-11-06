"""
Separador Inteligente de Entidades (MDM)
✅ Respeta Carnés de Extranjería (CE) y Pasaportes.
✅ Bloquea y reporta Homónimos.
✅ MDM Semántico: Fusión de múltiples contactos en estructura JSONB limpia.
✅ Trazabilidad de Fuentes: Combina SISMO y SIRI sin pérdida de datos.
"""
import pandas as pd
from typing import Dict, Tuple, Optional, Any
from datetime import datetime
import logging
import re
import json

logger = logging.getLogger(__name__)

class EntitySeparator:
    
    def __init__(self):
        self.stats = {
            'researchers': 0, 'projects': 0, 'funding_sources': 0,
            'calls': 0, 'funding_grants': 0, 'project_researchers': 0, 'research_areas': 0,
            'identity_resolution': {
                'total_members': 0, 'valid_dni_native': 0, 'valid_foreign_ce_pas': 0,
                'recovered_from_pg': 0, 'recovered_from_siri': 0, 'homonyms_blocked': 0, 'orphans_assigned_temp': 0
            },
            'data_quality_issues': {
                'missing_document': 0, 'invalid_dni_format': 0, 'missing_gender': 0, 'missing_dates': 0
            }
        }
        self.homonyms_log = set()
    
    def _normalize_name(self, name: str) -> Optional[str]:
        if pd.isna(name) or not isinstance(name, str): return None
        name = name.strip()
        if not name: return None
        parts = name.split(',')
        normalized_parts = []
        for part in parts:
            words = part.strip().split()
            normalized_words = [w[0].upper() + w[1:].lower() for w in words if w]
            normalized_parts.append(' '.join(normalized_words))
        return ', '.join(normalized_parts)
    
    def _normalize_gender(self, gender: str) -> Optional[str]:
        if pd.isna(gender) or not isinstance(gender, str):
            self.stats['data_quality_issues']['missing_gender'] += 1
            return None
        gender = gender.strip().lower()
        if gender in ['m', 'f']: return gender
        self.stats['data_quality_issues']['missing_gender'] += 1
        return None
    
    def _validate_dni(self, dni: str) -> Tuple[bool, Optional[str]]:
        if pd.isna(dni): return False, None
        dni_str = str(dni).strip()
        if not dni_str: return False, None
        dni_clean = re.sub(r'\D', '', dni_str)
        if len(dni_clean) == 8: return True, dni_clean
        return False, dni_str
    
    def _calculate_end_date(self, start_date, duration_months) -> Optional[datetime]:
        if pd.isna(start_date) or pd.isna(duration_months):
            self.stats['data_quality_issues']['missing_dates'] += 1
            return None
        try: return start_date + pd.DateOffset(months=int(duration_months))
        except: return None
    
    def _deduplicate_projects(self, projects_df: pd.DataFrame) -> pd.DataFrame:
        original_count = len(projects_df)
        duplicates_mask = projects_df.duplicated(subset=['project_code'], keep='first')
        
        self.project_id_mapping = {}
        if duplicates_mask.any():
            all_dups = projects_df[projects_df.duplicated(subset=['project_code'], keep=False)]
            for code, group in all_dups.groupby('project_code'):
                survivor_id = group.iloc[0]['sismo_project_id']
                for dropped_id in group.iloc[1:]['sismo_project_id']:
                    self.project_id_mapping[dropped_id] = survivor_id
                    logger.warning(f"⚠️ PROYECTO DUPLICADO: Código '{code}'. Sobrevive ID SISMO {survivor_id}. Se elimina ID SISMO {dropped_id}.")

        cleaned_df = projects_df.drop_duplicates(subset=['project_code'], keep='first')
        removed_count = original_count - len(cleaned_df)
        if removed_count > 0:
            logger.info(f"✅ Proyectos limpios: {len(cleaned_df)}. (Se remapearán las relaciones de los {removed_count} eliminados).")
        return cleaned_df
    
    def separate_all(self, raw_data: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        logger.info("🔀 Iniciando separación de entidades y resolución de identidad...")
        df_projects = raw_data.get('projects')
        df_team = raw_data.get('team')
        df_siri = raw_data.get('siri_personnel', pd.DataFrame())
        df_pg = raw_data.get('existing_persons', pd.DataFrame())
        
        if df_projects is None or df_team is None:
            raise ValueError("Faltan dataframes 'projects' o 'team' en raw_data.")

        entities = {}
        entities['funding_sources'] = self._extract_funding_sources(df_projects)
        entities['calls'] = self._extract_calls(df_projects)
        entities['funding_grants'] = self._extract_funding_grants(df_projects)
        
        entities['projects'] = self._extract_projects(df_projects)
        entities['research_areas'] = self._extract_research_areas(df_projects)

        researchers, project_researchers = self._extract_team_and_resolve_identity(df_team, df_siri, df_pg)
        
        if hasattr(self, 'project_id_mapping') and self.project_id_mapping:
            project_researchers['sismo_project_id'] = project_researchers['sismo_project_id'].apply(lambda x: self.project_id_mapping.get(x, x))
            entities['research_areas']['sismo_project_id'] = entities['research_areas']['sismo_project_id'].apply(lambda x: self.project_id_mapping.get(x, x))

        proyectos_validos = set(entities['projects']['sismo_project_id'])
        huerfanos = project_researchers[~project_researchers['sismo_project_id'].isin(proyectos_validos)]
        
        if not huerfanos.empty:
            logger.warning(f"🧹 PURGA: Se detectaron {len(huerfanos)} relaciones apuntando a IDs de proyectos inexistentes.")
        
        project_researchers = project_researchers[project_researchers['sismo_project_id'].isin(proyectos_validos)]
        
        entities['researchers'] = researchers
        entities['project_researchers'] = project_researchers
        
        self._log_data_quality()
        return entities

    def _extract_team_and_resolve_identity(self, df_team: pd.DataFrame, df_siri: pd.DataFrame, df_pg: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
        logger.info("\n🔍 Procesando Miembros del Equipo (MDM Semántico de Contactos)...")
        
        personas_unicas = df_team.drop_duplicates(subset=['id_persona'])
        self.stats['identity_resolution']['total_members'] = len(personas_unicas)

        pg_exact_dict = {}
        if not df_pg.empty:
            for _, row in df_pg.iterrows():
                if pd.notna(row['full_name']) and pd.notna(row['dni']):
                    nombre_norm = self._normalize_name(row['full_name'])
                    if nombre_norm: pg_exact_dict.setdefault(nombre_norm, set()).add(str(row['dni']).strip())

        siri_exact_dict = {}
        siri_names_by_dni = {}
        siri_emails_by_dni = {}
        
        if not df_siri.empty:
            df_siri_clean = df_siri.dropna(subset=['dni'])
            for _, row in df_siri_clean.iterrows():
                dni_str = str(row['dni']).strip().lstrip('0').zfill(8)
                if pd.notna(row.get('nombre_completo_siri')):
                    raw_siri_name = str(row['nombre_completo_siri']).strip()
                    siri_names_by_dni[dni_str] = raw_siri_name
                    nombre_norm = self._normalize_name(raw_siri_name)
                    if nombre_norm: siri_exact_dict.setdefault(nombre_norm, set()).add(dni_str)
                
                if pd.notna(row.get('email_siri')):
                    siri_emails_by_dni[dni_str] = str(row['email_siri']).strip().lower()

        resolved_researchers = []
        invalid_strings = ['nan', 'none', 'null', '']
        
        for _, per in personas_unicas.iterrows():
            nombre_original_sismo = str(per.get('nombre_completo_investigador', ''))
            nombre_final = nombre_original_sismo
            sismo_id = per['id_persona']
            
            doc_original = str(per.get('numero_documento', '')).strip()
            doc_type_sismo = str(per.get('documento', 'DNI')).strip().upper()
            
            dni_valido = False
            dni_limpio = None
            doc_final_type = 'OTHER'

            if doc_type_sismo == 'DNI':
                dni_valido, dni_limpio = self._validate_dni(doc_original)
                if dni_valido: doc_final_type = 'DNI'
                else: self.stats['data_quality_issues']['invalid_dni_format'] += 1
            elif doc_type_sismo in ['CE', 'PAS', 'PASAPORTE', 'C.E.'] and doc_original:
                dni_valido = True
                dni_limpio = doc_original
                doc_final_type = 'CE_PAS'
            elif not doc_original:
                self.stats['data_quality_issues']['missing_document'] += 1

            dni_asignado = dni_limpio if dni_valido else None
            is_recovered = False

            if doc_final_type == 'DNI' and dni_limpio in siri_names_by_dni:
                nombre_final = siri_names_by_dni[dni_limpio]
                
            nombre_norm = self._normalize_name(nombre_final)

            if not dni_valido and nombre_norm:
                pg_dnis = pg_exact_dict.get(nombre_norm, set())
                siri_dnis = siri_exact_dict.get(nombre_norm, set())
                all_dnis = pg_dnis.union(siri_dnis)

                if len(all_dnis) > 1:
                    self.homonyms_log.add(f"{nombre_norm} (Conflictos: {', '.join(all_dnis)})")
                    self.stats['identity_resolution']['homonyms_blocked'] += 1
                    dni_asignado = f"TMP-SISMO-{sismo_id}"
                elif len(all_dnis) == 1:
                    dni_asignado = list(all_dnis)[0]
                    dni_valido = True
                    doc_final_type = 'DNI_RECOVERED'
                    is_recovered = True
                    if dni_asignado in siri_names_by_dni:
                        nombre_final = siri_names_by_dni[dni_asignado]
                        nombre_norm = self._normalize_name(nombre_final)
                    
                    if len(pg_dnis) == 1: self.stats['identity_resolution']['recovered_from_pg'] += 1
                    else: self.stats['identity_resolution']['recovered_from_siri'] += 1
                else:
                    dni_asignado = f"TMP-SISMO-{sismo_id}"
                    self.stats['identity_resolution']['orphans_assigned_temp'] += 1
            elif not dni_valido:
                dni_asignado = f"TMP-SISMO-{sismo_id}"
                self.stats['identity_resolution']['orphans_assigned_temp'] += 1

            # --- CONSOLIDACIÓN SEMÁNTICA Y TRAZABILIDAD DE CONTACTOS ---
            contactos_map = {} 
            
            # 1. Procesar Contactos etiquetados de SISMO
            sismo_contacts_raw = per.get('contactos')
            if pd.notna(sismo_contacts_raw) and str(sismo_contacts_raw).strip() not in invalid_strings:
                try:
                    # El sql nos da un string "[{\"type\": \"CEL\", \"value\": \"999\"}]"
                    sismo_list = json.loads(sismo_contacts_raw) if isinstance(sismo_contacts_raw, str) else sismo_contacts_raw
                    
                    if isinstance(sismo_list, list):
                        for c in sismo_list:
                            # Filtro para ignorar nulos de la BD ej. [null]
                            if not isinstance(c, dict): continue
                                
                            val = str(c.get('value', '')).strip().lower()
                            c_type = str(c.get('type', 'OTRO')).strip().upper()
                            
                            if val and val not in invalid_strings:
                                contactos_map[val] = {'type': c_type, 'value': val, 'source': 'SISMO'}
                except Exception as e:
                    logger.warning(f"Error parseando contactos JSON de SISMO para ID {sismo_id}: {e} (Valor: {sismo_contacts_raw[:50]})")

            # 2. Correo Institucional de SIRI
            if doc_final_type in ['DNI', 'DNI_RECOVERED'] and dni_asignado in siri_emails_by_dni:
                siri_email = str(siri_emails_by_dni[dni_asignado]).strip().lower()
                if siri_email and siri_email not in invalid_strings:
                    if siri_email in contactos_map:
                        # Si ya existía, preservamos trazabilidad
                        c_type = contactos_map[siri_email]['type']
                        if 'EMAIL_INSTITUCIONAL' not in c_type:
                            contactos_map[siri_email]['type'] = f"{c_type} / EMAIL_INSTITUCIONAL"
                        contactos_map[siri_email]['source'] = "SISMO, SIRI"
                    else:
                        contactos_map[siri_email] = {'type': 'EMAIL_INSTITUCIONAL', 'value': siri_email, 'source': 'SIRI'}

            final_contacts = list(contactos_map.values())

            if doc_final_type == 'DNI': self.stats['identity_resolution']['valid_dni_native'] += 1
            elif doc_final_type == 'CE_PAS': self.stats['identity_resolution']['valid_foreign_ce_pas'] += 1

            resolved_researchers.append({
                'sismo_id': sismo_id,
                'full_name': nombre_norm, 
                'dni': dni_asignado,
                'document_type': doc_final_type,
                'gender': self._normalize_gender(str(per.get('genero', ''))),
                'contacts': final_contacts, 
                'dni_valid': dni_valido,
                'siri_enriched': is_recovered,
                'source_system': 'SISMO',
                'validation_status': 'pending' if dni_valido else 'missing_dni',
                'created_at': datetime.now()
            })

        df_researchers = pd.DataFrame(resolved_researchers)
        self.stats['researchers'] = len(df_researchers)

        df_team_roles = df_team.copy()
        def assign_role_priority(cargo_texto):
            cargo_limpio = str(cargo_texto).strip().title()
            if 'Investigador Principal' in cargo_limpio: return 1, 'Investigador Principal'
            elif 'Co' in cargo_limpio or 'Co-investigador' in cargo_limpio: return 2, 'Co-investigador'
            elif 'Tesis' in cargo_limpio: return 3, 'Tesista'
            elif 'Asesor' in cargo_limpio: return 4, 'Asesor'
            else: return 5, 'Miembro del Equipo'

        df_team_roles[['priority', 'role_mapped']] = df_team_roles.apply(lambda row: pd.Series(assign_role_priority(row.get('cargo_original_sismo', ''))), axis=1)
        df_team_dedup = df_team_roles.sort_values(['id_proyecto', 'id_persona', 'priority']).drop_duplicates(subset=['id_proyecto', 'id_persona'], keep='first')

        pr_list = []
        for _, row in df_team_dedup.iterrows():
            role_mapped = row['role_mapped']
            pr_list.append({
                'sismo_project_id': row['id_proyecto'], 'sismo_researcher_id': row['id_persona'],
                'sismo_contract_id': None, 'role': role_mapped,
                'participation_percentage': 100.0 if role_mapped == 'Investigador Principal' else 0.0,
                'created_at': datetime.now()
            })
            
        df_project_researchers = pd.DataFrame(pr_list)
        self.stats['project_researchers'] = len(df_project_researchers)
        
        return df_researchers, df_project_researchers
    
    def _extract_projects(self, df: pd.DataFrame) -> pd.DataFrame:
        project_columns = ['id_proyecto', 'codigo_proyecto', 'nombre_proyecto', 'id_contrato']
        optional_cols = [
            'tipo_proyecto', 'resumen_proyecto', 'just_proy', 'hipo_proy',
            'resul_espe_proy', 'impacto_proyecto', 'obj_general_proy',
            'est_proy', 'descripcion_estado', 'keywords',
            'fecha_inicial_proyecto', 'duracion_proyecto_meses'
        ]
        
        for col in optional_cols:
            if col in df.columns: project_columns.append(col)
                
        projects = df[project_columns].drop_duplicates(subset=['id_proyecto']).copy()
        projects = projects.reset_index(drop=True)
        
        column_mapping = {
            'id_proyecto': 'sismo_project_id', 'id_contrato': 'sismo_contract_id',
            'codigo_proyecto': 'project_code', 'nombre_proyecto': 'title',
            'tipo_proyecto': 'project_type', 'resumen_proyecto': 'abstract',
            'just_proy': 'justification', 'hipo_proy': 'hypothesis',
            'resul_espe_proy': 'expected_results', 'impacto_proyecto': 'impact',
            'obj_general_proy': 'general_objective', 'est_proy': 'status_code',
            'descripcion_estado': 'status_description', 'keywords': 'keywords',
            'fecha_inicial_proyecto': 'planned_start_date', 'duracion_proyecto_meses': 'duration_months'
        }
        
        projects = projects.rename(columns=column_mapping)
        projects = self._deduplicate_projects(projects)
        
        if 'planned_start_date' in projects.columns:
            projects['planned_start_date'] = pd.to_datetime(projects['planned_start_date'], errors='coerce')
            if 'duration_months' in projects.columns:
                projects['duration_months'] = pd.to_numeric(projects['duration_months'], errors='coerce')
                projects['estimated_end_date'] = projects.apply(
                    lambda row: self._calculate_end_date(row.get('planned_start_date'), row.get('duration_months')), axis=1
                )
        
        projects['ocde_classification'] = None
        projects['ocde_confidence_score'] = None
        projects['source_system'] = 'SISMO'
        projects['validation_status'] = 'pending'
        projects['created_at'] = datetime.now()
        projects['updated_at'] = datetime.now()
        
        self.stats['projects'] = len(projects)
        return projects
    
    def _extract_funding_sources(self, df: pd.DataFrame) -> pd.DataFrame:
        sources = df[['id_fuente', 'descripcion_fuente', 'abreviatura_fuente']].drop_duplicates(subset=['id_fuente']).copy()
        sources = sources.rename(columns={'id_fuente': 'sismo_funding_source_id', 'descripcion_fuente': 'name', 'abreviatura_fuente': 'abbreviation'})
        sources['name'] = sources['name'].apply(lambda x: x.strip() if isinstance(x, str) else x)
        sources['abbreviation'] = sources['abbreviation'].apply(lambda x: x.strip() if isinstance(x, str) else x)
        sources['source_type'] = 'external'
        sources['country'] = 'Peru'
        sources['website'] = None
        sources['organization_id'] = None
        sources['source_system'] = 'SISMO'
        sources['created_at'] = datetime.now()
        sources['updated_at'] = datetime.now()
        self.stats['funding_sources'] = len(sources)
        return sources
    
    def _extract_calls(self, df: pd.DataFrame) -> pd.DataFrame:
        calls = df[['id_convocatoria', 'codigo_convocatoria', 'nombre_convocatoria', 'id_fuente']].drop_duplicates(subset=['id_convocatoria']).copy()
        calls = calls.rename(columns={'id_convocatoria': 'sismo_call_id', 'codigo_convocatoria': 'call_code', 'nombre_convocatoria': 'call_name', 'id_fuente': 'sismo_funding_source_id'})
        calls['created_at'] = datetime.now()
        self.stats['calls'] = len(calls)
        return calls
    
    def _extract_funding_grants(self, df: pd.DataFrame) -> pd.DataFrame:
        funding_grants = df[['id_contrato', 'numero_contrato', 'nombre_contrato', 'id_convocatoria', 'moneda', 'monto_contrato']].drop_duplicates(subset=['id_contrato']).copy()
        funding_grants = funding_grants.rename(columns={'id_contrato': 'sismo_contract_id', 'numero_contrato': 'contract_number', 'nombre_contrato': 'contract_description', 'id_convocatoria': 'sismo_funding_call_id', 'moneda': 'currency', 'monto_contrato': 'amount'})
        funding_grants['amount'] = pd.to_numeric(funding_grants['amount'], errors='coerce')
        funding_grants['grant_code'] = None
        funding_grants['organization_id'] = None
        funding_grants['start_date'] = None
        funding_grants['end_date'] = None
        funding_grants['created_at'] = datetime.now()
        funding_grants['updated_at'] = datetime.now()
        self.stats['funding_grants'] = len(funding_grants)
        return funding_grants
    
    def _extract_research_areas(self, df: pd.DataFrame) -> pd.DataFrame:
        areas_list = []
        if 'type_area_prioritaria' in df.columns and 'nombre_area_prioritaria' in df.columns:
            priority_areas = df[df['type_area_prioritaria'].notna()][['id_proyecto', 'type_area_prioritaria', 'nombre_area_prioritaria']].drop_duplicates()
            for _, row in priority_areas.iterrows(): areas_list.append({'sismo_project_id': row['id_proyecto'], 'area_type': 'priority_area', 'area_code': row['type_area_prioritaria'], 'area_name': row['nombre_area_prioritaria']})
        if 'type_area_investigacion' in df.columns and 'nombre_area_investigacion' in df.columns:
            research_areas = df[df['type_area_investigacion'].notna()][['id_proyecto', 'type_area_investigacion', 'nombre_area_investigacion']].drop_duplicates()
            for _, row in research_areas.iterrows(): areas_list.append({'sismo_project_id': row['id_proyecto'], 'area_type': 'research_area', 'area_code': row['type_area_investigacion'], 'area_name': row['nombre_area_investigacion']})
        if 'type_linea_investigacion' in df.columns and 'nombre_linea_investigacion' in df.columns:
            research_lines = df[df['type_linea_investigacion'].notna()][['id_proyecto', 'type_linea_investigacion', 'nombre_linea_investigacion']].drop_duplicates()
            for _, row in research_lines.iterrows(): areas_list.append({'sismo_project_id': row['id_proyecto'], 'area_type': 'research_line', 'area_code': row['type_linea_investigacion'], 'area_name': row['nombre_linea_investigacion']})
        
        if areas_list:
            areas_df = pd.DataFrame(areas_list).drop_duplicates()
            areas_df['created_at'] = datetime.now()
        else:
            areas_df = pd.DataFrame(columns=['sismo_project_id', 'area_type', 'area_code', 'area_name', 'created_at'])
            
        self.stats['research_areas'] = len(areas_df)
        return areas_df
    
    def _log_data_quality(self):
        logger.info("\n📊 REPORTE DE RESOLUCIÓN DE IDENTIDAD (MDM):")
        logger.info(f"   - DNIs Nativos SISMO (Válidos): {self.stats['identity_resolution']['valid_dni_native']}")
        logger.info(f"   - Extranjeros (CE/PAS) Aceptados: {self.stats['identity_resolution']['valid_foreign_ce_pas']}")
        logger.info(f"   - Rescatados desde Base de Datos (PG): {self.stats['identity_resolution']['recovered_from_pg']}")
        logger.info(f"   - Rescatados desde Planillas (SIRI): {self.stats['identity_resolution']['recovered_from_siri']}")
        
        if self.stats['identity_resolution']['homonyms_blocked'] > 0:
            logger.warning(f"   ⚠️ HOMÓNIMOS BLOQUEADOS: {self.stats['identity_resolution']['homonyms_blocked']} (Se asignó ID Temporal)")
            for h in self.homonyms_log: logger.warning(f"       -> {h}")
        else:
            logger.info("   ✅ Cero homónimos detectados.")
            
        logger.info(f"   - Huérfanos/Sin datos (DNI Temporal): {self.stats['identity_resolution']['orphans_assigned_temp']}")
        
    def get_stats(self) -> Dict[str, Any]: return self.stats