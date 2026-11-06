"""
Actualizador de Perfiles VRI (Modo Auditoría y Prioridad VRI)
Extrae JSON incrustado (historicaData), detecta duplicados en origen, permite forzar la prioridad 
de los datos del VRI sobre la BD y genera un log CSV detallado de cada decisión tomada.
"""

import os
import re
import json
import csv
import requests
import logging
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from dotenv import load_dotenv

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configuración de Logs en Consola
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)

class VRIJsonUpdater:
    def __init__(self):
        load_dotenv('/app/airflow/.env')
        
        # ==========================================================
        # ⚙️ CONFIGURACIÓN DE PRIORIDAD
        # True = VRI sobrescribe a la BD en caso de conflicto.
        # False = BD se protege, solo se rellenan espacios vacíos.
        # ==========================================================
        self.PRIORITIZE_VRI = True 
        
        self.vri_url = "https://proyectos-vri.unsa.edu.pe/informacion-investigacion/index.php/Perfiles"
        
        host = os.getenv('POSTGRES_HOST', 'localhost')
        port = os.getenv('POSTGRES_PORT', '5432')
        db = os.getenv('POSTGRES_DB', 'cris_data')
        user = os.getenv('POSTGRES_USER', 'postgres')
        password = os.getenv('POSTGRES_PASSWORD')
        
        if not all([host, db, user, password]):
            raise ValueError("Faltan credenciales de PostgreSQL en el archivo .env")
            
        self.engine = create_engine(URL.create(
            drivername="postgresql", username=user, password=password,
            host=host, port=port, database=db
        ))
        
        self.stats = {
            'vri_duplicates_found': 0,
            'profiles_extracted': 0,
            'matched_in_db': 0,
            'profiles_updated': 0,
            'fields_added_new': 0,
            'fields_overwritten': 0,
            'conflicts_protected': 0,
            'skipped_identical': 0
        }
        
        # Memoria para el CSV de auditoría
        self.audit_log = []

    def _clean_cti_url(self, raw_val: str) -> str:
        if not raw_val: return None
        raw_val = str(raw_val).strip()
        if raw_val.isdigit():
            return f"https://ctivitae.concytec.gob.pe/appDirectorioCTI/VerDatosInvestigador.do?id_investigador={raw_val}"
        return raw_val

    def fetch_vri_data(self) -> dict:
        logger.info(f"🌐 Extrayendo historicaData desde: {self.vri_url}")
        master_profiles = {}
        
        try:
            response = requests.get(self.vri_url, verify=False, timeout=30)
            response.raise_for_status()
            
            # Solo extraemos historicaData para evitar duplicación masiva
            match_hist = re.search(r'var\s+historicaData\s*=\s*(\[.*?\]);', response.text, re.DOTALL)
            
            raw_profiles = []
            if match_hist: 
                raw_profiles.extend(json.loads(match_hist.group(1)))
            else:
                logger.error("❌ No se encontró la variable historicaData en el HTML.")
                return {}
            
            for p in raw_profiles:
                dni_raw = p.get('nro_documento')
                if not dni_raw: continue
                
                dni_clean = str(dni_raw).strip().lstrip('0').zfill(8)
                if len(dni_clean) != 8 or not dni_clean.isdigit(): continue
                
                # DETECCIÓN DE DUPLICADOS EN VRI
                if dni_clean in master_profiles:
                    self.stats['vri_duplicates_found'] += 1
                    logger.warning(f"⚠️ Duplicado en origen VRI: DNI {dni_clean} ({p.get('_full_name')}). Se fusionarán sus datos.")
                
                # Fusión si ya existe, creación si es nuevo
                if dni_clean not in master_profiles:
                    master_profiles[dni_clean] = {'name': p.get('_full_name', 'Desconocido')}
                
                prof = master_profiles[dni_clean]
                if p.get('orcid_id'): prof['orcid'] = p.get('orcid_id')
                if p.get('id_scopus'): prof['scopus'] = p.get('id_scopus')
                if p.get('id_wos'): prof['wos'] = p.get('id_wos')
                
                cti_val = p.get('id_cti_vitae') or p.get('_cti_url')
                if cti_val: prof['cti'] = self._clean_cti_url(cti_val)
                
                if p.get('foto_perfil'): prof['foto'] = p.get('foto_perfil')
                
            self.stats['profiles_extracted'] = len(master_profiles)
            logger.info(f"✅ Se consolidaron {len(master_profiles)} perfiles únicos desde historicaData.")
            return master_profiles
            
        except Exception as e:
            logger.error(f"❌ Error descargando o parseando JSON del VRI: {e}")
            return {}

    def load_db_persons(self) -> dict:
        logger.info("📦 Mapeando investigadores desde PostgreSQL...")
        db_persons = {}
        try:
            with self.engine.connect() as conn:
                query = text("""
                    SELECT id, dni, full_name, orcid, scopus_author_id, researcher_id, link_cti_vitae, foto_url 
                    FROM public.persons 
                    WHERE dni IS NOT NULL
                """)
                result = conn.execute(query)
                for row in result:
                    mapping = dict(row._mapping)
                    dni_clean = str(mapping['dni']).strip().lstrip('0').zfill(8)
                    db_persons[dni_clean] = mapping
            return db_persons
        except Exception as e:
            logger.error(f"❌ Error leyendo la base de datos: {e}")
            return {}

    def export_audit_csv(self):
        if not self.audit_log: return
        
        output_dir = '/app/airflow/logs/custom'
        os.makedirs(output_dir, exist_ok=True)
        filename = os.path.join(output_dir, f"audit_vri_enrichment_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['DNI', 'INVESTIGADOR', 'CAMPO', 'ACCION', 'VALOR_ANTERIOR (BD)', 'VALOR_NUEVO (VRI)'])
                for row in self.audit_log:
                    writer.writerow(row)
            logger.info(f"\n📄 REPORTE DE AUDITORÍA GENERADO: {filename}")
        except Exception as e:
            logger.error(f"❌ Error guardando CSV de auditoría: {e}")

    def run(self):
        vri_profiles = self.fetch_vri_data()
        if not vri_profiles: return
        
        db_persons = self.load_db_persons()
        if not db_persons: return

        updates_to_execute = []
        logger.info(f"🔍 Iniciando Cruce (Prioridad VRI = {self.PRIORITIZE_VRI})...")

        for dni, vri in vri_profiles.items():
            if dni not in db_persons:
                continue
                
            self.stats['matched_in_db'] += 1
            db_row = db_persons[dni]
            
            # Mapeo de campos a comparar (ClaveBD : ClaveVRI)
            comparisons = {
                'orcid': ('orcid', vri.get('orcid')),
                'scopus_author_id': ('scopus', vri.get('scopus')),
                'researcher_id': ('wos', vri.get('wos')),
                'link_cti_vitae': ('cti', vri.get('cti')),
                'foto_url': ('foto', vri.get('foto'))
            }

            fields_to_update = {}
            field_logs = []

            for db_col, (vri_key, vri_val) in comparisons.items():
                vri_val = str(vri_val or '').strip()
                if not vri_val: continue # Si VRI no tiene nada, pasamos al siguiente campo
                
                db_val = str(db_row.get(db_col) or '').strip()

                # Ignorar si son idénticos o si la diferencia es solo el ID del CTI Vitae en la URL
                if db_val == vri_val: continue
                if db_col == 'link_cti_vitae' and vri_val.split('=')[-1] in db_val: continue
                
                # Caso 1: BD está vacía -> Siempre se llena
                if not db_val:
                    fields_to_update[db_col] = vri_val
                    field_logs.append(f"{db_col.upper()}: [NUEVO] {vri_val}")
                    self.audit_log.append([dni, vri['name'], db_col.upper(), 'NUEVO', 'Vacío', vri_val])
                    self.stats['fields_added_new'] += 1
                
                # Caso 2: Conflicto de datos (Ambos tienen valores distintos)
                else:
                    if self.PRIORITIZE_VRI:
                        fields_to_update[db_col] = vri_val
                        field_logs.append(f"{db_col.upper()}: [SOBRESCRITO] '{db_val}' -> '{vri_val}'")
                        self.audit_log.append([dni, vri['name'], db_col.upper(), 'SOBRESCRITO (VRI MANDA)', db_val, vri_val])
                        self.stats['fields_overwritten'] += 1
                    else:
                        field_logs.append(f"{db_col.upper()}: [PROTEGIDO] BD conservó '{db_val}' frente a '{vri_val}'")
                        self.audit_log.append([dni, vri['name'], db_col.upper(), 'IGNORADO (BD PROTEGIDA)', db_val, vri_val])
                        self.stats['conflicts_protected'] += 1

            if fields_to_update:
                update_query = "UPDATE public.persons SET "
                set_clauses = [f"{col} = :{col}" for col in fields_to_update.keys()]
                set_clauses.extend(["sync_status = 'pending_update'", "updated_at = CURRENT_TIMESTAMP"])
                
                update_query += ", ".join(set_clauses) + " WHERE id = :id"
                fields_to_update['id'] = db_row['id']
                
                updates_to_execute.append({
                    "query": text(update_query), 
                    "params": fields_to_update, 
                    "name": vri['name'],
                    "dni": dni, # Pasamos el DNI para un log seguro
                    "logs": field_logs
                })
            else:
                self.stats['skipped_identical'] += 1

        if updates_to_execute:
            logger.info(f"\n💾 Guardando {len(updates_to_execute)} perfiles en PostgreSQL...")
            try:
                with self.engine.begin() as conn:
                    for up in updates_to_execute:
                        conn.execute(up["query"], up["params"])
                        # Imprimir historial detallado por investigador usando el DNI
                        logger.info(f"👤 {up['name']} (DNI: {up['dni']})")
                        for log_msg in up['logs']:
                            logger.info(f"   ↳ {log_msg}")
                        self.stats['profiles_updated'] += 1
            except Exception as e:
                logger.error(f"❌ Error Fatal al escribir en BD: {e}")

        self._print_summary()
        self.export_audit_csv()

    def _print_summary(self):
        logger.info("\n" + "="*60)
        logger.info(f"📋 RESUMEN DE ENRIQUECIMIENTO (PRIORIDAD VRI = {self.PRIORITIZE_VRI})")
        logger.info("="*60)
        logger.info(f"🔹 Perfiles extraídos (VRI)  : {self.stats['profiles_extracted']}")
        logger.info(f"⚠️  Duplicados en origen VRI : {self.stats['vri_duplicates_found']}")
        logger.info(f"🔗 Cruzados exactos por DNI  : {self.stats['matched_in_db']}")
        logger.info("------------------------------------------------------------")
        logger.info(f"✅ PERFILES ACTUALIZADOS     : {self.stats['profiles_updated']}")
        logger.info(f"➕ Campos Nuevos Añadidos    : {self.stats['fields_added_new']}")
        logger.info(f"🔄 Campos Sobrescritos       : {self.stats['fields_overwritten']}")
        logger.info(f"🛡️  Conflictos Protegidos    : {self.stats['conflicts_protected']}")
        logger.info(f"⏭️  Omitidos (Ya idénticos)  : {self.stats['skipped_identical']}")
        logger.info("="*60)

if __name__ == "__main__":
    VRIJsonUpdater().run()