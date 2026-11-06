"""
Test Completo de FASE 2: SMART SYNC
Compatible con ejecuciones interactivas o automáticas (CLI/Docker).
"""
import os
import sys
import logging
import traceback
from datetime import datetime
from pathlib import Path
import pandas as pd

BASE_DIR = Path(os.getenv('AIRFLOW_HOME', Path(__file__).resolve().parent.parent))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from plugins.extractors.sismo_extractor import SISMOExtractor
from plugins.extractors.siri_extractor import SIRIExtractor
from plugins.transformers.entity_separator import EntitySeparator
from plugins.transformers.organization_builder import OrganizationBuilder
from plugins.transformers.siri_enricher import SIRIEnricher
from plugins.loaders.postgres_loader import PostgresLoader
from plugins.validators.validator import DataValidator

SIRI_ACTIVE_SEMESTER_ID = os.getenv('SIRI_ACTIVE_SEMESTER_ID', '1215433')

LOGS_DIR = BASE_DIR / 'logs' / 'custom'
LOGS_DIR.mkdir(parents=True, exist_ok=True)
log_filename = LOGS_DIR / f"phase2_sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_filename, mode='w', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


class Phase2Tester:
    def __init__(self):
        self.start_time = datetime.now()
        self.results = {
            'sismo_extraction': {'success': False, 'projects': 0, 'team': 0, 'duration': 0},
            'entity_separation': {'success': False, 'entities': 0, 'duration': 0, 'duplicates_removed': 0},
            'organization_building': {'success': False, 'orgs': 0, 'duration': 0},
            'siri_affiliations': {'success': False, 'affiliations': 0, 'duration': 0},
            'validation': {'success': False, 'errors': 0, 'warnings': 0, 'duration': 0},
            'postgres_load': {'success': False, 'tables': 0, 'total_records': 0, 'duration': 0, 'duplicates_skipped': 0}
        }
        self.raw_data = None
        self.entities = None
        
    def run_all_tests(self, include_db_load: bool = True, verify_schema: bool = True):
        try:
            logger.info("="*70)
            logger.info("🧪 TEST COMPLETO FASE 2: SMART SYNC")
            logger.info("="*70)
            
            if verify_schema and include_db_load:
                if not self._verify_postgres_schema(): return False
            if not self._test_sismo_extraction(): return False
            if not self._test_entity_separation(): return False
            if not self._test_siri_affiliations(): return False
            if not self._test_validation(): logger.warning("⚠️ Validación completada con advertencias")
            
            if include_db_load:
                if not self._test_postgres_load(): return False
            else:
                logger.info("\n[PASO 6] Carga a PostgreSQL omitida (Modo Dry Run)")
            
            self._print_summary()
            return True
            
        except Exception as e:
            logger.error(f"\n💥 ERROR FATAL: {str(e)}")
            logger.error(traceback.format_exc())
            return False
    
    def _verify_postgres_schema(self) -> bool:
        logger.info("\n" + "="*70 + "\n[PASO 0/6] Verificación de Esquema\n" + "="*70)
        try:
            loader = PostgresLoader()
            if not loader.connect(): return False
            required = ['organizations', 'persons', 'funding_sources', 'funding_calls', 'projects', 'project_researchers', 'person_organization_affiliations']
            missing = [t for t in required if not loader._table_exists(t, schema='public')]
            loader.close()
            if missing:
                logger.error(f"❌ Tablas faltantes: {missing}")
                return False
            logger.info("✅ Esquema PostgreSQL verificado")
            return True
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            return False
    
    def _test_sismo_extraction(self):
        logger.info("\n" + "="*70 + "\n[PASO 1/6] Extracción de Orígenes\n" + "="*70)
        step_start = datetime.now()
        try:
            sismo = SISMOExtractor()
            siri = SIRIExtractor()
            loader = PostgresLoader()
            
            if not sismo.connect() or not siri.connect() or not loader.connect(): return False
            
            df_projects = sismo.extract_projects_and_grants()
            df_team = sismo.extract_team_members()
            df_siri_master = siri.get_master_personnel_data(semestre_id=SIRI_ACTIVE_SEMESTER_ID)
            
            logger.info("🏛️ Obteniendo Golden Record desde PostgreSQL...")
            df_pg_persons = pd.read_sql_query("SELECT id as pg_id, dni, full_name FROM public.persons WHERE full_name IS NOT NULL", loader.engine)
            
            sismo.close()
            siri.close()
            loader.close()
            
            self.raw_data = {
                'projects': df_projects, 
                'team': df_team, 
                'siri_personnel': df_siri_master,
                'existing_persons': df_pg_persons
            }
            duration = (datetime.now() - step_start).total_seconds()
            logger.info(f"✅ Extracción combinada completada en {duration:.2f}s")
            self.results['sismo_extraction'] = {'success': True, 'projects': len(df_projects), 'team': len(df_team), 'duration': duration}
            return True
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            logger.error(traceback.format_exc())
            return False
    
    def _test_entity_separation(self):
        logger.info("\n" + "="*70 + "\n[PASO 2/6] Separación de Entidades\n" + "="*70)
        step_start = datetime.now()
        try:
            self.separator = EntitySeparator() 
            self.entities = self.separator.separate_all(self.raw_data)
            duration = (datetime.now() - step_start).total_seconds()
            logger.info(f"✅ {len(self.entities)} entidades procesadas en {duration:.2f}s")
            self.results['entity_separation'] = {'success': True, 'entities': len(self.entities), 'duration': duration, 'duplicates_removed': 0}
            return True
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            logger.error(traceback.format_exc())
            return False
    
    def _test_siri_affiliations(self):
        logger.info("\n" + "="*70 + "\n[PASO 4/6] Afiliaciones (Memoria)\n" + "="*70)
        step_start = datetime.now()
        try:
            df_all_researchers = self.entities['researchers']
            if df_all_researchers.empty:
                affiliations = pd.DataFrame(columns=['sismo_researcher_id', 'org_code'])
            else:
                siri_master_df = self.raw_data['siri_personnel']
                affiliations = SIRIEnricher().build_affiliations(df_all_researchers, siri_master_df)
                
            self.entities['person_organization_affiliations'] = affiliations
            duration = (datetime.now() - step_start).total_seconds()
            logger.info(f"✅ {len(affiliations)} afiliaciones procesadas en {duration:.2f}s")
            self.results['siri_affiliations'] = {'success': True, 'affiliations': len(affiliations), 'duration': duration}
            return True
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            logger.error(traceback.format_exc())
            return False
    
    def _test_validation(self):
        logger.info("\n" + "="*70 + "\n[PASO 5/6] Validación de Datos\n" + "="*70)
        step_start = datetime.now()
        try:
            self.validation_results = DataValidator().validate_all_entities(self.entities)
            duration = (datetime.now() - step_start).total_seconds()
            s = self.validation_results['summary']
            logger.info(f"✅ Pasados: {s['passed']} | Warnings: {s['warnings']} | Errores: {s['errors']}")
            self.results['validation'] = {'success': True, 'errors': s['errors'], 'warnings': s['warnings'], 'duration': duration}
            return True
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            return True
    
    def _test_postgres_load(self):
        logger.info("\n" + "="*70 + "\n[PASO 6/6] Carga a PostgreSQL\n" + "="*70)
        step_start = datetime.now()
        try:
            loader = PostgresLoader() 
            loader.connect()
            load_results = loader.load_all_entities(self.entities, schema="public")
            loader.export_sync_audit(str(LOGS_DIR))
            loader.close()
            
            duration = (datetime.now() - step_start).total_seconds()
            self.results['postgres_load'] = {
                'success': True, 
                'tables': sum(1 for c in load_results.values() if c > 0), 
                'total_records': sum(load_results.values()), 
                'duration': duration, 
                'duplicates_skipped': 0
            }
            return True
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            logger.error(traceback.format_exc())
            return False
    
    def _print_summary(self):
        logger.info("\n" + "="*70 + "\n📋 RESUMEN FINAL - FASE 2\n" + "="*70)
        logger.info(f"✅ Extracción: {self.results['sismo_extraction']['duration']:.1f}s")
        logger.info(f"✅ Separación: {self.results['entity_separation']['duration']:.1f}s")
        logger.info(f"✅ Afiliación: {self.results['siri_affiliations']['duration']:.1f}s")
        logger.info(f"✅ Carga BD: {self.results['postgres_load']['total_records']} registros en {self.results['postgres_load']['duration']:.1f}s")
        logger.info("="*70)


if __name__ == "__main__":
    choice = sys.argv[1] if len(sys.argv) > 1 else '1'
    if choice == '4':
        sys.exit(0)
    elif choice == '3':
        sys.exit(0 if Phase2Tester()._verify_postgres_schema() else 1)
    elif choice in ['1', '2']:
        success = Phase2Tester().run_all_tests(include_db_load=(choice == '1'), verify_schema=(choice == '1'))
        sys.exit(0 if success else 1)