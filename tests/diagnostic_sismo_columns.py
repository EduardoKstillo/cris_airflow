"""
Script de diagnóstico para verificar columnas reales en SISMO
"""
import sys
sys.path.insert(0, '/app/airflow')

from plugins.extractors.sismo_extractor import SISMOExtractor
from dotenv import load_dotenv
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def diagnose_sismo():
    """Extrae datos de SISMO y muestra todas las columnas"""
    
    print("\n" + "="*80)
    print("DIAGNÓSTICO: Columnas Reales en SISMO")
    print("="*80 + "\n")
    
    try:
        load_dotenv('/app/airflow/.env')
        
        extractor = SISMOExtractor()
        
        if not extractor.connect():
            print("❌ No se pudo conectar a SISMO")
            return False
        
        print("Extrayendo datos de SISMO...")
        df = extractor.extract_master_query()
        
        print(f"\n✅ Se extrajeron {len(df)} registros\n")
        
        # Mostrar todas las columnas
        print("COLUMNAS REALES EN SISMO:")
        print("-" * 80)
        for i, col in enumerate(df.columns, 1):
            print(f"{i:2d}. {col}")
        
        print("\n" + "-" * 80)
        print(f"Total de columnas: {len(df.columns)}\n")
        
        # Mostrar tipos de datos
        print("TIPOS DE DATOS:")
        print("-" * 80)
        print(df.dtypes)
        
        # Buscar columnas relacionadas a fuente
        print("\n" + "-" * 80)
        print("BÚSQUEDA DE COLUMNAS RELACIONADAS:")
        print("-" * 80)
        
        search_terms = ['fuente', 'organi', 'id_', 'codigo_', 'descripcion_', 'moneda']
        
        for term in search_terms:
            matches = [col for col in df.columns if term.lower() in col.lower()]
            if matches:
                print(f"\n📌 Columnas con '{term}':")
                for col in matches:
                    print(f"   - {col}")
        
        # Mostrar primeras filas
        print("\n" + "-" * 80)
        print("PRIMERAS 3 FILAS (muestra):")
        print("-" * 80)
        print(df.head(3).to_string())
        
        # Verificar columnas críticas
        print("\n" + "-" * 80)
        print("VALIDACIÓN DE COLUMNAS CRÍTICAS:")
        print("-" * 80)
        
        critical_columns = {
            'Proyectos': ['id_proyecto', 'codigo_proyecto', 'nombre_proyecto', 'tipo_proyecto'],
            'Investigadores': ['id_persona', 'nombre_completo_investigador', 'numero_documento', 'documento', 'genero'],
            'Organización': ['id_fuente', 'descripcion_fuente', 'abreviatura_fuente', 'estado_fuente'],
            'Financiamiento': ['id_contrato', 'numero_contrato', 'moneda', 'monto_contrato'],
            'Convocatorias': ['id_convocatoria', 'codigo_convocatoria', 'nombre_convocatoria']
        }
        
        for category, cols in critical_columns.items():
            print(f"\n{category}:")
            for col in cols:
                exists = col in df.columns
                status = "✓" if exists else "✗"
                print(f"  {status} {col}")
        
        # Guardar lista de columnas en archivo
        with open('/app/airflow/logs/custom/sismo_columns_diagnostic.txt', 'w') as f:
            f.write("COLUMNAS REALES EN SISMO\n")
            f.write("="*80 + "\n\n")
            for i, col in enumerate(df.columns, 1):
                f.write(f"{i:2d}. {col}\n")
            f.write(f"\nTotal: {len(df.columns)} columnas\n")
        
        print("\n" + "="*80)
        print("✅ Diagnóstico guardado en: /app/airflow/logs/custom/sismo_columns_diagnostic.txt")
        print("="*80 + "\n")
        
        extractor.close()
        return True
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = diagnose_sismo()
    sys.exit(0 if success else 1)