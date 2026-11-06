import sys
sys.path.insert(0, '/app/airflow')

from plugins.extractors.sismo_extractor import SISMOExtractor
from plugins.transformers.entity_separator import EntitySeparator


extractor = SISMOExtractor()

try:
    print("🔌 Conectando a SISMO...")

    if not extractor.connect():
        raise Exception("No se pudo conectar")

    print("📥 Extrayendo datos...")
    raw_df = extractor.extract_master_query()

    print(f"✅ Raw: {len(raw_df)} registros")

    print("🔀 Separando entidades...")
    separator = EntitySeparator()

    entities = separator.separate_all(raw_df)

    print("\n===== RESULTADOS =====")

    for name, df in entities.items():
        print(f"{name}: {len(df)} registros")

    print("\n===== ESTADÍSTICAS =====")
    print(separator.get_stats())

    print("\n✅ TEST COMPLETADO")

finally:
    extractor.close()