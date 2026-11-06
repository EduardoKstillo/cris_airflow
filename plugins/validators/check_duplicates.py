"""
Script para investigar proyectos duplicados
Ejecutar desde: /app/airflow/
"""
import sys
sys.path.insert(0, '/app/airflow')

from plugins.extractors.sismo_extractor import SISMOExtractor
from plugins.transformers.entity_separator import EntitySeparator
import pandas as pd

pd.set_option('display.max_columns', None)
pd.set_option('display.width', None)
pd.set_option('display.max_colwidth', 50)

print("="*80)
print("🔍 INVESTIGACIÓN DE PROYECTOS DUPLICADOS")
print("="*80)

# 1. Extraer datos de SISMO
print("\n1️⃣ Extrayendo datos de SISMO...")
extractor = SISMOExtractor()
if not extractor.connect():
    print("❌ Error conectando a SISMO")
    sys.exit(1)

raw_data = extractor.extract_master_query()
extractor.close()
print(f"   ✅ Extraídos {len(raw_data)} registros")

# 2. Separar entidades
print("\n2️⃣ Separando entidades...")
separator = EntitySeparator()
entities = separator.separate_all(raw_data)
projects = entities['projects']
print(f"   ✅ {len(projects)} proyectos únicos")

# 3. Buscar duplicados
print("\n3️⃣ Buscando duplicados en project_code...")
duplicated_mask = projects['project_code'].duplicated(keep=False)
duplicates_count = duplicated_mask.sum()

if duplicates_count == 0:
    print("   ✅ No hay duplicados")
    sys.exit(0)

print(f"   ⚠️ Encontrados {duplicates_count} registros con códigos duplicados")

# 4. Mostrar detalles
print("\n4️⃣ DETALLES DE DUPLICADOS:")
print("="*80)

dup_codes = projects[duplicated_mask]['project_code'].unique()

for i, code in enumerate(dup_codes, 1):
    print(f"\n🔸 DUPLICADO #{i}: Código '{code}'")
    print("-"*80)
    
    dup_rows = projects[projects['project_code'] == code].sort_values('sismo_project_id')
    
    # Mostrar información relevante
    cols_to_show = ['sismo_project_id', 'project_code', 'title', 'project_type', 
                    'status_code', 'status_description']
    cols_available = [c for c in cols_to_show if c in dup_rows.columns]
    
    print(dup_rows[cols_available].to_string(index=False))
    
    # Análisis
    print(f"\n📊 Análisis:")
    print(f"   - Cantidad de ocurrencias: {len(dup_rows)}")
    print(f"   - IDs SISMO: {dup_rows['sismo_project_id'].tolist()}")
    
    if 'title' in dup_rows.columns:
        unique_titles = dup_rows['title'].nunique()
        if unique_titles == 1:
            print(f"   - Mismo título: ✅ (probablemente mismo proyecto)")
        else:
            print(f"   - Títulos diferentes: ⚠️ ({unique_titles} títulos distintos)")
    
    if 'status_code' in dup_rows.columns:
        unique_status = dup_rows['status_code'].nunique()
        if unique_status > 1:
            print(f"   - Estados diferentes: {dup_rows['status_code'].unique().tolist()}")

print("\n" + "="*80)
print("💡 RECOMENDACIONES:")
print("="*80)
print("""
Si son el MISMO proyecto con IDs diferentes:
  → Esto es normal en SISMO (duplicación por estados o versiones)
  → El loader manejará esto usando UPSERT o ignorando duplicados

Si son proyectos DIFERENTES con el mismo código:
  → Error en los datos de SISMO
  → Contactar al administrador de SISMO para corregir
  
Para continuar la carga ignorando este error:
  → Modifica el test para que no bloquee por duplicados
  → O limpia los duplicados antes de cargar
""")

# 5. Verificar en datos crudos de SISMO
print("\n5️⃣ Verificando en datos crudos de SISMO...")
print("="*80)

for code in dup_codes:
    print(f"\n🔍 Código: {code}")
    raw_matches = raw_data[raw_data['codigo_proyecto'] == code]
    print(f"   - Aparece en {len(raw_matches)} registros del query master")
    print(f"   - IDs de proyecto únicos: {raw_matches['id_proyecto'].nunique()}")
    print(f"   - IDs de proyecto: {raw_matches['id_proyecto'].unique().tolist()}")
    
    if 'nombre_proyecto' in raw_matches.columns:
        unique_names = raw_matches['nombre_proyecto'].nunique()
        print(f"   - Nombres únicos: {unique_names}")
        if unique_names > 1:
            print("   - Nombres diferentes:")
            for name in raw_matches['nombre_proyecto'].unique():
                print(f"     * {name}")

print("\n" + "="*80)