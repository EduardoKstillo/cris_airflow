import sys
from pathlib import Path
import os

# Añadir raíz al path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from plugins.extractors.siri_extractor import SIRIExtractor

def test_siri():
    print("🚀 Iniciando prueba de conexión a SIRI...")
    extractor = SIRIExtractor()
    
    if extractor.connect():
        print("✅ Conexión establecida con éxito.")
        
        # Probar extracción de facultades
        df_faculties = extractor.get_faculties()
        print(f"🏛️ Facultades encontradas: {len(df_faculties)}")
        print(df_faculties.head(3))
        
        # Probar extracción de personal con el semestre activo del .env
        semestre_id = os.getenv('SIRI_ACTIVE_SEMESTER_ID', '1215433')
        df_personnel = extractor.get_master_personnel_data(semestre_id)
        print(f"👥 Registros de personal para el semestre {semestre_id}: {len(df_personnel)}")
        print(df_personnel.head(3))
        
        extractor.close()
    else:
        print("❌ Falló la conexión a SIRI.")

if __name__ == "__main__":
    test_siri()