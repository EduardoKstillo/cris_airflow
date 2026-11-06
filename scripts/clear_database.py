"""
Script para limpiar la base de datos antes de ejecutar tests
Ejecutar: python clear_database.py
"""
import os
import sys
from pathlib import Path
import logging
from sqlalchemy import text

# Resolución dinámica de la raíz del proyecto (Compatible con Docker y entornos locales)
BASE_DIR = Path(os.getenv('AIRFLOW_HOME', Path(__file__).resolve().parent.parent))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from plugins.loaders.postgres_loader import PostgresLoader

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def clear_all_tables():
    """Limpia todas las tablas de la base de datos respetando dependencias."""
    loader = PostgresLoader()

    if not loader.connect():
        logger.error("❌ No se pudo conectar a PostgreSQL")
        return False

    tables_to_clear = [
        'research_areas',
        'project_researchers',
        'projects',
        'funding_grants',
        'funding_calls',
        'funding_sources',
        'person_organization_affiliations',
        'persons',
        'organizations'
    ]

    try:
        logger.info("🗑️ Limpiando base de datos...")

        # begin() maneja automáticamente COMMIT / ROLLBACK
        with loader.engine.begin() as conn:
            for table in tables_to_clear:
                # Verificar si la tabla existe
                exists = conn.execute(
                    text("""
                        SELECT EXISTS (
                            SELECT 1
                            FROM information_schema.tables
                            WHERE table_schema = 'public'
                            AND table_name = :table
                        )
                    """),
                    {"table": table}
                ).scalar()

                if not exists:
                    logger.warning(f"   ⚠️ {table}: no existe, se omite")
                    continue

                # TRUNCATE con CASCADE respeta y limpia las dependencias de FK
                conn.execute(text(f'TRUNCATE TABLE public."{table}" CASCADE'))
                logger.info(f"   ✅ {table} limpiada")

        logger.info("✅ Base de datos limpiada correctamente")
        return True

    except Exception as e:
        logger.error(f"❌ Error limpiando base de datos: {e}")
        return False
    
    finally:
        # Aseguramos que la conexión siempre se cierre pase lo que pase
        loader.close()


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("⚠️ ADVERTENCIA: Esto eliminará TODOS los datos de las tablas")
    print("=" * 70)

    confirm = input("\n¿Continuar? (escribir 'SI' en mayúsculas): ")

    if confirm == 'SI':
        success = clear_all_tables()
        sys.exit(0 if success else 1)
    else:
        print("❌ Operación cancelada")
        sys.exit(1)