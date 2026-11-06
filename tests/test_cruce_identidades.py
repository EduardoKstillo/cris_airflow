import sys
import pandas as pd
sys.path.insert(0, '/app/airflow')

from plugins.extractors.sismo_extractor import SISMOExtractor
from plugins.extractors.siri_extractor import SIRIExtractor
from plugins.utils.name_matcher import NameMatcher

def debug_cruce_identidades():
    print("="*60)
    print("🔍 DEBUGGING: CRUCE DE IDENTIDADES SISMO -> SIRI")
    print("="*60)

    # 1. Extraer Equipo de SISMO
    sismo = SISMOExtractor()
    sismo_team = sismo.extract_team_members()
    sismo_nombres_unicos = sismo_team['nombre_completo_investigador'].dropna().unique()
    print(f"✅ SISMO: {len(sismo_nombres_unicos)} nombres únicos encontrados.")

    # 2. Extraer Personal de SIRI
    siri = SIRIExtractor()
    siri_personnel = siri.get_all_active_personnel()
    print(f"✅ SIRI: {len(siri_personnel)} personas activas encontradas.")

    # 3. Preparar el Matcher
    matcher = NameMatcher(threshold=0.85)
    
    # Crear lista de candidatos de SIRI: [(Nombre Completo, DNI), ...]
    candidatos_siri = list(zip(siri_personnel['nombre_completo_siri'], siri_personnel['dni']))
    
    # 4. Proceso de Cruce
    print("\n🔄 Iniciando cruce inteligente de nombres (Esto puede tomar un minuto)...")
    
    match_exitoso = 0
    match_fallido = []

    for nombre_sismo in sismo_nombres_unicos:
        # Usar la función de tu NameMatcher
        resultado = matcher.find_best_match(nombre_sismo, candidatos_siri)
        
        if resultado:
            match_exitoso += 1
        else:
            match_fallido.append(nombre_sismo)

    # 5. Resultados del Debugging
    tasa_exito = (match_exitoso / len(sismo_nombres_unicos)) * 100
    print("\n" + "="*60)
    print(f"📊 RESULTADOS DEL CRUCE")
    print("="*60)
    print(f"✔️ Matches exitosos (DNI Encontrado): {match_exitoso}")
    print(f"❌ Matches fallidos (DNI No Encontrado): {len(match_fallido)}")
    print(f"📈 Tasa de éxito: {tasa_exito:.2f}%")

    if match_fallido:
        print("\n⚠️ Muestra de nombres no encontrados en SIRI (Primeros 10):")
        for n in match_fallido[:10]:
            print(f"   - {n}")

if __name__ == "__main__":
    debug_cruce_identidades()