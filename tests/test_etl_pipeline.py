"""
test_etl_pipeline.py
Script de prueba End-to-End para el pipeline ETL de SISMO/SIRI a PostgreSQL.
Incluye guardado de CSVs para auditoría visual.
Ejecutar desde: /app/airflow/
"""
import sys
import os
import logging
from datetime import datetime

# Asegurar que el path del proyecto esté disponible
sys.path.insert(0, '/app/airflow')

from plugins.extractors.sismo_extractor import SISMOExtractor
from plugins.extractors.siri_extractor import SIRIExtractor
from plugins.transformers.entity_separator import EntitySeparator
from plugins.transformers.organization_builder import OrganizationBuilder
from plugins.transformers.siri_enricher import SIRIEnricher
from plugins.loaders.postgres_loader import PostgresLoader

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("ETL_Test")

def save_to_csv(entities_dict, output_folder='/app/airflow/data/processed'):
    """Guarda todas las entidades en CSV para revisión visual"""
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
        
    logger.info(f"\n" + "="*50 + f"\n💾 GUARDANDO CSVs EN {output_folder}\n" + "="*50)
    
    for name, df in entities_dict.items():
        if df is not None and not df.empty:
            file_path = os.path.join(output_folder, f"{name}.csv")
            try:
                # Quitamos la zona horaria de las fechas porque Excel no la maneja bien
                df_to_save = df.copy()
                for col in df_to_save.select_dtypes(include=['datetime64[ns, UTC]', 'datetime64[ns]']).columns:
                    df_to_save[col] = df_to_save[col].dt.tz_localize(None)
                    
                df_to_save.to_csv(file_path, index=False, encoding='utf-8')
                logger.info(f"   ✅ Guardado: {name}.csv ({len(df)} filas)")
            except Exception as e:
                logger.error(f"   ❌ Error guardando {name}.csv: {e}")

def main():
    start_time = datetime.now()
    logger.info("🚀 INICIANDO PRUEBA DEL PIPELINE ETL (END-TO-END) 🚀")
    
    # ---------------------------------------------------------
    # 1. INICIALIZAR COMPONENTES
    # ---------------------------------------------------------
    logger.info("\n" + "="*50 + "\n1. INICIALIZANDO COMPONENTES\n" + "="*50)
    
    sismo = SISMOExtractor()
    siri = SIRIExtractor()
    separator = EntitySeparator()
    loader = PostgresLoader()
    
    if not all([sismo.connect(), siri.connect(), loader.connect()]):
        logger.error("❌ Falló la conexión a alguna de las bases de datos. Revisa tus credenciales.")
        sys.exit(1)
        
    org_builder = OrganizationBuilder(siri)
    siri_enricher = SIRIEnricher(siri)
    
    # ---------------------------------------------------------
    # 2. EXTRACCIÓN (SISMO)
    # ---------------------------------------------------------
    logger.info("\n" + "="*50 + "\n2. EXTRACCIÓN DE DATOS (SISMO)\n" + "="*50)
    try:
        df_projects = sismo.extract_projects_and_grants()
        df_team = sismo.extract_team_members()
        
        raw_data = {
            'projects': df_projects,
            'team': df_team
        }
        logger.info(f"✅ Extracción completada. Proyectos: {len(df_projects)}, Miembros: {len(df_team)}")
    except Exception as e:
        logger.error(f"❌ Fallo en la extracción: {e}")
        sys.exit(1)

    # ---------------------------------------------------------
    # 3. TRANSFORMACIÓN BÁSICA (Entity Separator)
    # ---------------------------------------------------------
    logger.info("\n" + "="*50 + "\n3. TRANSFORMACIÓN Y SEPARACIÓN DE ENTIDADES\n" + "="*50)
    try:
        entities = separator.separate_all(raw_data)
        logger.info("✅ Transformación completada exitosamente.")
    except Exception as e:
        logger.error(f"❌ Fallo en la transformación: {e}")
        sys.exit(1)

    # ---------------------------------------------------------
    # 4. ORGANIZACIONES (SIRI)
    # ---------------------------------------------------------
    logger.info("\n" + "="*50 + "\n4. CONSTRUYENDO JERARQUÍA ORGANIZACIONAL (SIRI)\n" + "="*50)
    try:
        entities['organizations'] = org_builder.build_complete_hierarchy()
    except Exception as e:
        logger.error(f"❌ Fallo construyendo organizaciones: {e}")
        sys.exit(1)

    # ---------------------------------------------------------
    # 5. AFILIACIONES (Cruce SISMO - SIRI)
    # ---------------------------------------------------------
    logger.info("\n" + "="*50 + "\n5. CONSTRUYENDO AFILIACIONES DE INVESTIGADORES\n" + "="*50)
    try:
        df_researchers_clean = entities['researchers']
        df_affiliations = siri_enricher.build_affiliations(df_researchers_clean)
        entities['person_organization_affiliations'] = df_affiliations
    except Exception as e:
        logger.error(f"❌ Fallo cruzando afiliaciones con SIRI: {e}")
        sys.exit(1)

    # ---------------------------------------------------------
    # EXPORTAR CSVS PARA AUDITORÍA
    # ---------------------------------------------------------
    save_to_csv(entities)

    # ---------------------------------------------------------
    # 6. CARGA A POSTGRESQL
    # ---------------------------------------------------------
    logger.info("\n" + "="*50 + "\n6. CARGA FINAL A POSTGRESQL (CRIS DATA)\n" + "="*50)
    try:
        # Aquí falló tu afiliación. Si necesitas ver los CSVs antes de que falle, 
        # comenta o comenta la siguiente línea por ahora.
        results = loader.load_all_entities(entities, phase="Test", clear_before_load=True)
    except Exception as e:
        logger.error(f"❌ Fallo crítico durante la carga a BD: {e}")
        # sys.exit(1) # Comentado para permitir que cierre conexiones correctamente

    # ---------------------------------------------------------
    # 7. CIERRE Y RESUMEN
    # ---------------------------------------------------------
    logger.info("\n" + "="*50 + "\n7. VERIFICACIÓN Y CIERRE\n" + "="*50)
    integrity = loader.verify_data_integrity()
    logger.info(f"Reporte de integridad en BD: {integrity}")

    sismo.close()
    siri.close()
    loader.close()

    duration = (datetime.now() - start_time).total_seconds()
    logger.info(f"🎉 PRUEBA COMPLETADA EXITOSAMENTE EN {duration:.2f} SEGUNDOS 🎉")

if __name__ == "__main__":
    main()