"""
test_batch_search.py
Prueba de búsquedas en lote manteniendo el navegador abierto
Resuelves el CAPTCHA UNA sola vez para múltiples búsquedas
"""
import sys
sys.path.insert(0, '/app/airflow')

import logging
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from plugins.enrichers.cti_vitae_searcher import CTIVitaeSearcher

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def batch_search_with_single_captcha(nombres_a_buscar: list):
    """
    Busca múltiples investigadores resolviendo CAPTCHA solo una vez
    
    Args:
        nombres_a_buscar: Lista de nombres a buscar
    """
    
    print("\n" + "="*70)
    print("🔍 BÚSQUEDA EN LOTE CON UN SOLO CAPTCHA")
    print("="*70)
    print(f"Total de búsquedas a realizar: {len(nombres_a_buscar)}\n")
    
    # Crear searcher
    searcher = CTIVitaeSearcher(headless=False)
    
    # Inicializar driver
    searcher._init_driver()
    
    all_results = {}
    
    try:
        # 1. Navegar a la página de búsqueda
        print("1️⃣ Navegando a CTI Vitae...")
        searcher.driver.get(searcher.SEARCH_URL)
        time.sleep(3)
        
        # 2. Resolver CAPTCHA UNA SOLA VEZ
        print("\n" + "="*70)
        print("⚠️  ACCIÓN REQUERIDA:")
        print("="*70)
        print("1. Verás el navegador Chrome abierto")
        print("2. Resuelve el reCAPTCHA (marca 'No soy un robot')")
        print("3. NO hagas la búsqueda todavía")
        print("4. Vuelve aquí y presiona ENTER para continuar")
        print("="*70)
        
        input("\n▶️  Presiona ENTER después de resolver el CAPTCHA...\n")
        
        print("✅ Continuando con las búsquedas...\n")
        
        # 3. Hacer búsquedas en bucle
        for idx, nombre in enumerate(nombres_a_buscar, 1):
            print(f"\n[{idx}/{len(nombres_a_buscar)}] Buscando: {nombre}")
            print("-" * 60)
            
            try:
                # Llenar campo de búsqueda
                search_input = WebDriverWait(searcher.driver, 10).until(
                    EC.presence_of_element_located((By.NAME, "investigadorTituloPublicacion"))
                )
                search_input.clear()
                search_input.send_keys(nombre)
                print("   ✓ Campo de búsqueda completado")
                
                # Click en buscar
                search_button = searcher.driver.find_element(By.ID, "btnBuscarInvestigador")
                search_button.click()
                print("   ✓ Botón 'Buscar' presionado")
                
                time.sleep(3)
                
                # Verificar si hay alerta de CAPTCHA (no debería aparecer)
                try:
                    alert = searcher.driver.switch_to.alert
                    alert_text = alert.text
                    print(f"   ⚠️ Alerta: {alert_text}")
                    alert.accept()
                    print("   ❌ El CAPTCHA expiró o no se resolvió correctamente")
                    print("   → Saltando esta búsqueda")
                    continue
                except:
                    # No hay alerta, todo bien
                    pass
                
                # Esperar resultados
                try:
                    WebDriverWait(searcher.driver, 10).until(
                        EC.presence_of_element_located((By.ID, "resultado_consulta"))
                    )
                    print("   ✓ Tabla de resultados cargada")
                except TimeoutException:
                    print("   ⚠️ No aparecieron resultados (posiblemente sin coincidencias)")
                    all_results[nombre] = []
                    
                    # Volver a página de búsqueda para siguiente iteración
                    searcher.driver.get(searcher.SEARCH_URL)
                    time.sleep(2)
                    continue
                
                # Extraer resultados
                results = searcher._extract_search_results()
                all_results[nombre] = results
                
                if results:
                    print(f"   ✅ {len(results)} resultados encontrados")
                    for r_idx, result in enumerate(results[:3], 1):  # Mostrar solo primeros 3
                        print(f"      {r_idx}. {result['nombre']}")
                    if len(results) > 3:
                        print(f"      ... y {len(results) - 3} más")
                else:
                    print("   ℹ️ Sin resultados")
                
                # Volver a la página de búsqueda para la siguiente iteración
                print("   ⟲ Recargando página de búsqueda...")
                searcher.driver.get(searcher.SEARCH_URL)
                time.sleep(2)
                
            except Exception as e:
                print(f"   ❌ Error en búsqueda: {e}")
                all_results[nombre] = []
                # Intentar volver a página de búsqueda
                try:
                    searcher.driver.get(searcher.SEARCH_URL)
                    time.sleep(2)
                except:
                    pass
        
        # 4. Resumen final
        print("\n" + "="*70)
        print("📊 RESUMEN DE BÚSQUEDAS")
        print("="*70)
        
        total_exitosas = sum(1 for results in all_results.values() if results)
        total_sin_resultados = sum(1 for results in all_results.values() if not results)
        total_resultados = sum(len(results) for results in all_results.values())
        
        print(f"\nTotal búsquedas realizadas: {len(all_results)}")
        print(f"  ✅ Con resultados: {total_exitosas}")
        print(f"  ⚠️ Sin resultados: {total_sin_resultados}")
        print(f"  📈 Total de investigadores encontrados: {total_resultados}")
        
        print("\nDetalle por búsqueda:")
        for nombre, results in all_results.items():
            if results:
                print(f"  • {nombre}: {len(results)} resultado(s)")
            else:
                print(f"  • {nombre}: sin resultados")
        
        print("\n" + "="*70)
        
        return all_results
        
    finally:
        # Preguntar antes de cerrar
        print("\n⏸️  El navegador permanecerá abierto para que revises los resultados")
        input("Presiona ENTER para cerrar el navegador...\n")
        searcher.close()
        print("✅ Proceso completado")


if __name__ == "__main__":
    # Lista de nombres a buscar
    nombres_prueba = [
        "GARCIA LOPEZ JUAN",
        "PEREZ SANCHEZ MARIA",
        "RODRIGUEZ TORRES CARLOS",
        "MENDOZA FLORES ANA",
        "SILVA RAMIREZ PEDRO"
    ]
    
    print("\n" + "="*70)
    print("🧪 TEST: BÚSQUEDA EN LOTE")
    print("="*70)
    print("\nEste test buscará los siguientes investigadores:")
    for idx, nombre in enumerate(nombres_prueba, 1):
        print(f"  {idx}. {nombre}")
    
    print("\n⚠️  IMPORTANTE:")
    print("- Solo resolverás el CAPTCHA UNA vez")
    print("- Luego se harán todas las búsquedas automáticamente")
    print("- El navegador permanecerá abierto todo el tiempo")
    
    continuar = input("\n¿Deseas continuar? (s/n): ").strip().lower()
    
    if continuar == 's':
        results = batch_search_with_single_captcha(nombres_prueba)
    else:
        print("❌ Prueba cancelada")