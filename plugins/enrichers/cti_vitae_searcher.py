"""
cti_vitae_searcher.py
Búsqueda de investigadores en CTI Vitae con manejo de reCAPTCHA
VERSIÓN ACTUALIZADA: CAPTCHA aparece ANTES de la búsqueda
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import time
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class CTIVitaeSearcher:
    """
    Buscador de investigadores en CTI Vitae
    Usa Selenium para resolver reCAPTCHA manualmente ANTES de buscar
    """
    
    SEARCH_URL = "https://ctivitae.concytec.gob.pe/appDirectorioCTI/BuscarInvestigadores.do"
    BASE_URL = "https://ctivitae.concytec.gob.pe/appDirectorioCTI/"
    
    def __init__(self, headless: bool = False, cookie_manager=None):
        """
        Args:
            headless: Si True, ejecuta navegador sin interfaz gráfica
                     (NO RECOMENDADO: necesitas ver el CAPTCHA)
        """
        self.headless = headless
        self.driver = None
        self.cookie_manager = cookie_manager
    
    def _init_driver(self):
        """Inicializa el driver de Selenium"""
        try:
            options = webdriver.ChromeOptions()
            
            if self.headless:
                options.add_argument('--headless')
                logger.warning("⚠️ Modo headless activado - no podrás resolver CAPTCHA manualmente")
            
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            
            # Usar webdriver-manager (recomendado)
            try:
                from webdriver_manager.chrome import ChromeDriverManager
                from selenium.webdriver.chrome.service import Service
                
                service = Service(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=options)
                logger.info("✅ Driver de Selenium inicializado (con webdriver-manager)")
                
            except ImportError:
                # Fallback: usar ChromeDriver del PATH
                self.driver = webdriver.Chrome(options=options)
                logger.info("✅ Driver de Selenium inicializado (ChromeDriver del sistema)")
            
        except Exception as e:
            logger.error(f"❌ Error inicializando driver: {e}")
            logger.error("   Asegúrate de tener Chrome instalado y ChromeDriver disponible")
            raise
    
    def _wait_for_captcha_resolution(self, method: str = "enter") -> bool:
        """
        Espera a que el usuario resuelva el CAPTCHA
        
        Args:
            method: "enter" (espera tecla ENTER) o "auto" (detección automática)
            
        Returns:
            True si se puede continuar
        """
        if method == "enter":
            return self._wait_with_enter_key()
        else:
            return self._wait_with_auto_detection()
    
    def _wait_with_enter_key(self) -> bool:
        """
        Método simple: espera que el usuario presione ENTER
        después de resolver el CAPTCHA
        """
        logger.info("⏳ ACCIÓN REQUERIDA:")
        logger.info("   1. Resuelve el reCAPTCHA en el navegador")
        logger.info("   2. Presiona ENTER aquí en la consola para continuar...")
        
        try:
            input()
            logger.info("✅ Continuando con la búsqueda...")
            return True
        except KeyboardInterrupt:
            logger.error("❌ Operación cancelada por el usuario")
            return False
    
    def _wait_with_auto_detection(self, timeout: int = 120) -> bool:
        """
        Método avanzado: detecta automáticamente cuando se resuelve el CAPTCHA
        Verifica el estado del checkbox del reCAPTCHA
        """
        logger.info("⏳ Esperando resolución de reCAPTCHA...")
        logger.info("   (Marca la casilla 'No soy un robot')")
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                # Buscar el iframe del reCAPTCHA
                recaptcha_frames = self.driver.find_elements(
                    By.CSS_SELECTOR, 
                    "iframe[src*='recaptcha']"
                )
                
                for frame in recaptcha_frames:
                    try:
                        # Cambiar al iframe
                        self.driver.switch_to.frame(frame)
                        
                        # Verificar si el checkbox está marcado
                        checkbox = self.driver.find_element(By.CLASS_NAME, "recaptcha-checkbox")
                        aria_checked = checkbox.get_attribute("aria-checked")
                        
                        # Volver al contenido principal
                        self.driver.switch_to.default_content()
                        
                        if aria_checked == "true":
                            logger.info("✅ reCAPTCHA resuelto correctamente")
                            return True
                        
                    except NoSuchElementException:
                        self.driver.switch_to.default_content()
                        continue
                
            except Exception as e:
                logger.debug(f"Verificando CAPTCHA: {e}")
                self.driver.switch_to.default_content()
            
            time.sleep(2)
        
        logger.error("⏱️ Timeout esperando resolución de CAPTCHA")
        return False
    
    def save_current_session(self, session_name: str = 'default') -> bool:
        """
        Guarda la sesión actual (cookies) en la BD
        
        Args:
            session_name: Nombre de la sesión
            
        Returns:
            True si se guardó correctamente
        """
        if not self.cookie_manager:
            logger.warning("⚠️ No hay cookie_manager configurado")
            return False
        
        cookies = self.extract_session_cookies()
        if not cookies:
            logger.warning("⚠️ No hay cookies para guardar")
            return False
        
        # Guardar en BD
        success = self.cookie_manager.save_session(
            service='cti_vitae_search',
            cookies=cookies,
            session_name=session_name,
            expires_in_hours=24
        )
        
        if success:
            logger.info(f"✅ Sesión guardada: {session_name}")
        
        return success

    def load_saved_session(self, session_name: str = 'default') -> bool:
        """
        Carga una sesión guardada y la aplica al navegador
        
        Args:
            session_name: Nombre de la sesión
            
        Returns:
            True si se cargó correctamente
        """
        if not self.cookie_manager:
            logger.warning("⚠️ No hay cookie_manager configurado")
            return False
        
        if not self.driver:
            logger.warning("⚠️ Debes inicializar el driver primero")
            return False
        
        # Cargar sesión de BD
        session_data = self.cookie_manager.load_session('cti_vitae_search', session_name)
        
        if not session_data:
            logger.warning(f"⚠️ No hay sesión válida guardada: {session_name}")
            return False
        
        # Primero navegar al dominio (necesario para set cookies)
        try:
            self.driver.get(self.SEARCH_URL)
            time.sleep(2)
            
            # Aplicar cookies al navegador
            for name, value in session_data['cookies'].items():
                self.driver.add_cookie({
                    'name': name,
                    'value': value,
                    'domain': '.concytec.gob.pe'  # Dominio de CTI Vitae
                })
            
            logger.info(f"✅ Sesión cargada en el navegador: {session_name}")
            
            # Refrescar página para aplicar cookies
            self.driver.refresh()
            time.sleep(2)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error cargando sesión en navegador: {e}")
            return False
    
    def search_researcher(
        self, 
        nombre_completo: str,
        captcha_method: str = "enter"
    ) -> List[Dict]:
        """
        Busca un investigador por nombre completo
        
        Args:
            nombre_completo: Nombre completo del investigador
            captcha_method: "enter" (presionar ENTER) o "auto" (detección automática)
            
        Returns:
            Lista de resultados encontrados con 'nombre' y 'link'
        """
        if not self.driver:
            self._init_driver()
        
        try:
            logger.info(f"🔍 Buscando: {nombre_completo}")
            
            # Navegar a la página de búsqueda
            self.driver.get(self.SEARCH_URL)
            time.sleep(3)  # Esperar a que cargue completamente
            
            # Llenar campo de búsqueda
            try:
                search_input = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.NAME, "investigadorTituloPublicacion"))
                )
                search_input.clear()
                search_input.send_keys(nombre_completo)
                logger.info("   ✅ Campo de búsqueda completado")
                
            except TimeoutException:
                logger.error("❌ No se encontró el campo de búsqueda")
                logger.error("   Verifica que la página haya cargado correctamente")
                return []
            
            # ⭐ ESPERAR RESOLUCIÓN DE CAPTCHA ANTES DE BUSCAR
            if not self._wait_for_captcha_resolution(method=captcha_method):
                logger.error("❌ No se pudo resolver el CAPTCHA")
                return []
            
            # Hacer clic en buscar (DESPUÉS de resolver CAPTCHA)
            try:
                search_button = self.driver.find_element(By.ID, "btnBuscarInvestigador")
                search_button.click()
                logger.info("   🔎 Botón 'Buscar' presionado")
                time.sleep(3)
                
            except NoSuchElementException:
                logger.error("❌ No se encontró el botón de búsqueda")
                logger.error("   ID esperado: 'btnBuscarInvestigador'")
                return []
            
            # Verificar si hay alerta de CAPTCHA no resuelto
            try:
                alert = self.driver.switch_to.alert
                alert_text = alert.text
                logger.warning(f"⚠️ Alerta detectada: {alert_text}")
                alert.accept()
                logger.error("❌ El CAPTCHA no se resolvió correctamente")
                return []
            except:
                # No hay alerta, continuar normalmente
                pass
            
            # Esperar que carguen los resultados
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.ID, "resultado_consulta"))
                )
                logger.info("   ✅ Tabla de resultados cargada")
                
            except TimeoutException:
                logger.warning("⚠️ No aparecieron resultados")
                logger.warning("   Posibles causas:")
                logger.warning("   - No hay coincidencias para la búsqueda")
                logger.warning("   - El CAPTCHA no se resolvió correctamente")
                logger.warning("   - Error en la página")
                return []
            
            # Extraer resultados
            results = self._extract_search_results()
            
            logger.info(f"   ✅ {len(results)} resultados encontrados")
            return results
            
        except Exception as e:
            logger.error(f"❌ Error en búsqueda: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return []
    
    def _extract_search_results(self) -> List[Dict]:
        """Extrae resultados de la tabla de búsqueda"""
        results = []
        
        try:
            # Encontrar tabla de resultados
            table = self.driver.find_element(By.ID, "resultado_consulta")
            
            # Encontrar el tbody
            tbody = table.find_element(By.TAG_NAME, "tbody")
            
            # Encontrar todas las filas
            rows = tbody.find_elements(By.TAG_NAME, "tr")
            
            logger.info(f"   📊 Procesando {len(rows)} filas de resultados...")
            
            for idx, row in enumerate(rows, 1):
                try:
                    # Encontrar todas las celdas de la fila
                    cells = row.find_elements(By.TAG_NAME, "td")
                    
                    if len(cells) < 3:
                        logger.debug(f"      Fila {idx}: estructura inválida, omitiendo")
                        continue
                    
                    # La tercera columna (index 2) contiene el nombre y link
                    user_cell = cells[2]
                    
                    # Buscar el enlace con target="_blank" que contiene el nombre
                    links = user_cell.find_elements(By.CSS_SELECTOR, 'a[target="_blank"]')
                    
                    for link in links:
                        # El nombre está dentro de <b> tags
                        nombre_elem = link.find_element(By.TAG_NAME, "b")
                        nombre = nombre_elem.text.strip()
                        href = link.get_attribute("href")
                        
                        # Construir URL completa si es necesario
                        if href and not href.startswith("http"):
                            href = self.BASE_URL + href
                        
                        if nombre and href:
                            results.append({
                                'nombre': nombre,
                                'link': href
                            })
                            logger.debug(f"      {idx}. {nombre}")
                            break  # Solo tomar el primer enlace válido
                        
                except NoSuchElementException:
                    logger.debug(f"      Fila {idx}: sin enlace válido, omitiendo")
                    continue
                except Exception as e:
                    logger.debug(f"      Fila {idx}: error procesando - {e}")
                    continue
            
        except NoSuchElementException:
            logger.warning("⚠️ No se encontró tabla de resultados (ID: resultado_consulta)")
        except Exception as e:
            logger.error(f"❌ Error extrayendo resultados: {e}")
        
        return results
    
    def close(self):
        """Cierra el navegador"""
        if self.driver:
            self.driver.quit()
            self.driver = None
            logger.info("🔌 Driver de Selenium cerrado")
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def extract_session_cookies(self) -> Dict:
        """Extrae las cookies actuales del navegador Selenium"""
        if not self.driver:
            logger.warning("No hay driver activo")
            return {}
        
        cookies = {}
        try:
            for cookie in self.driver.get_cookies():
                cookies[cookie['name']] = cookie['value']
            logger.info(f"✅ {len(cookies)} cookies extraídas del navegador")
        except Exception as e:
            logger.error(f"❌ Error extrayendo cookies: {e}")
        
        return cookies
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()


def test_cti_vitae_searcher():
    """Test del searcher con diferentes métodos de CAPTCHA"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Configuración
    test_name = "GARCIA LOPEZ JUAN"
    captcha_method = "enter"  # Cambiar a "auto" para detección automática
    
    print("\n" + "="*60)
    print("🧪 TEST: CTI Vitae Searcher")
    print("="*60)
    print(f"Nombre a buscar: {test_name}")
    print(f"Método CAPTCHA: {captcha_method}")
    print("="*60 + "\n")
    
    # Usar context manager
    with CTIVitaeSearcher(headless=False) as searcher:
        results = searcher.search_researcher(
            test_name, 
            captcha_method=captcha_method
        )
        
        if results:
            print("\n" + "="*60)
            print(f"✅ {len(results)} RESULTADOS ENCONTRADOS")
            print("="*60 + "\n")
            
            for idx, result in enumerate(results, 1):
                print(f"{idx}. {result['nombre']}")
                print(f"   🔗 {result['link']}\n")
        else:
            print("\n" + "="*60)
            print("❌ NO SE ENCONTRARON RESULTADOS")
            print("="*60 + "\n")
            print("Posibles causas:")
            print("- El nombre no existe en la base de datos")
            print("- El CAPTCHA no se resolvió correctamente")
            print("- Error de conexión o timeout")


if __name__ == "__main__":
    test_cti_vitae_searcher()