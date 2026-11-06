"""
test_cookie_integration.py
Prueba de integración entre CTIVitaeSearcher y CookieManager
"""
import sys
sys.path.insert(0, '/app/airflow')

import logging
import os
import time
from dotenv import load_dotenv

from plugins.enrichers.cti_vitae_searcher import CTIVitaeSearcher
from plugins.utils.cookie_manager import CookieManager

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def test_primera_busqueda_con_guardado():
    """Primera búsqueda: resuelve CAPTCHA y guarda cookies"""
    
    print("\n" + "="*70)
    print("🧪 TEST 1: PRIMERA BÚSQUEDA (con CAPTCHA + guardar cookies)")
    print("="*70 + "\n")
    
    # Configurar conexión a BD
    load_dotenv('/app/airflow/.env')
    
    host = os.getenv('POSTGRES_HOST', 'localhost')
    port = os.getenv('POSTGRES_PORT', '5432')
    db = os.getenv('POSTGRES_DB', 'cris_data')
    user = os.getenv('POSTGRES_USER', 'postgres')
    password = os.getenv('POSTGRES_PASSWORD')
    
    connection_string = f"postgresql://{user}:{password}@{host}:{port}/{db}"
    
    # Crear cookie manager
    cookie_manager = CookieManager(connection_string)
    
    # Crear searcher CON cookie_manager
    searcher = CTIVitaeSearcher(headless=False, cookie_manager=cookie_manager)
    
    try:
        # Primera búsqueda (necesitarás resolver CAPTCHA)
        nombre1 = "GARCIA LOPEZ JUAN"
        
        print(f"📝 Buscando: {nombre1}")
        print("⚠️ TENDRÁS QUE RESOLVER EL CAPTCHA MANUALMENTE\n")
        
        results = searcher.search_researcher(nombre1, captcha_method='enter')
        
        if results:
            print(f"\n✅ Encontrados {len(results)} resultados")
            for idx, r in enumerate(results, 1):
                print(f"   {idx}. {r['nombre']}")
        
        # GUARDAR LAS COOKIES
        print("\n💾 Guardando cookies de la sesión...")
        if searcher.save_current_session('test_session'):
            print("✅ Cookies guardadas exitosamente")
            print("   Ahora puedes hacer más búsquedas sin resolver CAPTCHA\n")
        else:
            print("❌ Error guardando cookies\n")
        
    finally:
        searcher.close()


def test_segunda_busqueda_con_cookies():
    """Segunda búsqueda: usa cookies guardadas (sin CAPTCHA)"""
    
    print("\n" + "="*70)
    print("🧪 TEST 2: SEGUNDA BÚSQUEDA (usando cookies guardadas)")
    print("="*70 + "\n")
    
    # Configurar conexión a BD
    load_dotenv('/app/airflow/.env')
    
    host = os.getenv('POSTGRES_HOST', 'localhost')
    port = os.getenv('POSTGRES_PORT', '5432')
    db = os.getenv('POSTGRES_DB', 'cris_data')
    user = os.getenv('POSTGRES_USER', 'postgres')
    password = os.getenv('POSTGRES_PASSWORD')
    
    connection_string = f"postgresql://{user}:{password}@{host}:{port}/{db}"
    
    # Crear cookie manager
    cookie_manager = CookieManager(connection_string)
    
    # Crear searcher CON cookie_manager
    searcher = CTIVitaeSearcher(headless=False, cookie_manager=cookie_manager)
    
    try:
        # Inicializar driver primero
        searcher._init_driver()
        
        # CARGAR COOKIES GUARDADAS
        print("📂 Cargando cookies guardadas...")
        if searcher.load_saved_session('test_session'):
            print("✅ Cookies cargadas en el navegador\n")
            
            # Ahora buscar SIN resolver CAPTCHA
            nombre2 = "PEREZ SANCHEZ MARIA"
            
            print(f"📝 Buscando: {nombre2}")
            print("⚠️ Si las cookies son válidas, NO deberías ver CAPTCHA\n")
            
            # Navegar a búsqueda (ya con cookies)
            searcher.driver.get(searcher.SEARCH_URL)
            time.sleep(3)
            
            # Verificar si aparece CAPTCHA
            print("👀 Verifica en el navegador:")
            print("   - ¿Aparece el CAPTCHA?")
            print("   - Si NO aparece → ✅ Las cookies funcionan")
            print("   - Si SÍ aparece → ❌ Las cookies expiraron\n")
            
            input("Presiona ENTER para continuar con la búsqueda...")
            
            # Hacer búsqueda normal
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            
            search_input = WebDriverWait(searcher.driver, 10).until(
                EC.presence_of_element_located((By.NAME, "investigadorTituloPublicacion"))
            )
            search_input.clear()
            search_input.send_keys(nombre2)
            
            search_button = searcher.driver.find_element(By.ID, "btnBuscarInvestigador")
            search_button.click()
            
            time.sleep(3)
            
            # Extraer resultados
            results = searcher._extract_search_results()
            
            if results:
                print(f"\n✅ Encontrados {len(results)} resultados SIN resolver CAPTCHA")
                for idx, r in enumerate(results, 1):
                    print(f"   {idx}. {r['nombre']}")
            else:
                print("\n⚠️ No se encontraron resultados o las cookies no funcionaron")
        else:
            print("❌ No se pudieron cargar las cookies")
            print("   Ejecuta primero test_primera_busqueda_con_guardado()\n")
        
    finally:
        searcher.close()


if __name__ == "__main__":
    import sys
    
    print("\n" + "="*70)
    print("🔬 TEST DE INTEGRACIÓN: Cookie Manager + CTI Vitae Searcher")
    print("="*70)
    
    print("\nElige qué test ejecutar:")
    print("1. Primera búsqueda (resolver CAPTCHA y guardar cookies)")
    print("2. Segunda búsqueda (usar cookies guardadas - sin CAPTCHA)")
    print("3. Ejecutar ambos tests secuencialmente")
    
    opcion = input("\nOpción (1/2/3): ").strip()
    
    if opcion == "1":
        test_primera_busqueda_con_guardado()
    elif opcion == "2":
        test_segunda_busqueda_con_cookies()
    elif opcion == "3":
        test_primera_busqueda_con_guardado()
        input("\n⏸️ Presiona ENTER para continuar con el segundo test...")
        test_segunda_busqueda_con_cookies()
    else:
        print("❌ Opción inválida")