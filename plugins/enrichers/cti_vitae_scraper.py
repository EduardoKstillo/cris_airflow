"""
cti_vitae_scraper.py
Extrae datos de fichas individuales de CTI Vitae (cuando ya se tiene el link)
"""

import sys
sys.path.insert(0, '/app/airflow')

import requests
from bs4 import BeautifulSoup
import re
from typing import Dict, Optional
import logging
import time
from urllib.parse import urljoin

from plugins.utils.cookie_manager import CookieManager

logger = logging.getLogger(__name__)


class CTIVitaeScraper:
    """
    Scraper para fichas individuales de CTI Vitae
    Extrae: nombre, descripción, ORCID, Scopus, WOS, Renacyt, foto
    """
    
    BASE_URL = "https://ctivitae.concytec.gob.pe/appDirectorioCTI/"
    
    def __init__(self, cookie_manager: Optional[CookieManager] = None):
        """
        Args:
            cookie_manager: Gestor de cookies opcional
        """
        self.cookie_manager = cookie_manager
        self.session = requests.Session()
        
        # Configurar headers por defecto
        if cookie_manager:
            self.session.headers.update(
                cookie_manager.get_default_headers('cti_vitae')
            )
        else:
            self.session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
    
    def load_session_cookies(self) -> bool:
        """Carga cookies de una sesión válida"""
        if not self.cookie_manager:
            return False
        
        session_data = self.cookie_manager.load_session('cti_vitae')
        if session_data:
            # Aplicar cookies
            for key, value in session_data['cookies'].items():
                self.session.cookies.set(key, value)
            
            # Aplicar headers
            self.session.headers.update(session_data['headers'])
            
            logger.info("✅ Sesión cargada en scraper")
            return True
        
        return False
    
    def extract_researcher_data(self, html_content: str) -> Dict:
        """
        Extrae datos de la ficha de investigador desde HTML
        
        Args:
            html_content: HTML de la página
            
        Returns:
            Dict con los datos extraídos
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        
        data = {
            'nombre_completo': None,
            'descripcion': None,
            'orcid': None,
            'scopus_author_id': None,
            'researcher_id': None,
            'link_renacyt': None,
            'foto_url': None
        }
        
        try:
            # Nombre completo
            nombre_elem = soup.find('div', class_='tituloNombreFicha2')
            if nombre_elem:
                nombre_span = nombre_elem.find('span')
                if nombre_span:
                    data['nombre_completo'] = nombre_span.get_text(strip=True)
            
            # Descripción
            desc_elem = soup.find('p', class_='descPersonalFicha2')
            if desc_elem:
                data['descripcion'] = desc_elem.get_text(strip=True)
            
            # ORCID
            orcid_span = soup.find('span', id='link_orcid')
            if orcid_span:
                orcid_link = orcid_span.find('a', href=re.compile(r'orcid\.org'))
                if orcid_link:
                    orcid_url = orcid_link.get('href', '')
                    # Extraer ID: https://orcid.org/0000-0002-1234-5678
                    orcid_match = re.search(r'orcid\.org/([0-9X-]+)', orcid_url)
                    if orcid_match:
                        data['orcid'] = orcid_match.group(1)
            
            # Buscar TODOS los spans con id='link_scopus' (mal uso del id por parte de CTI Vitae)
            all_scopus_spans = soup.find_all('span', id='link_scopus')
            
            for span in all_scopus_spans:
                span_text = span.get_text()
                
                # Scopus Author ID
                if 'Scopus Author Identifier' in span_text:
                    scopus_link = span.find('a', href=re.compile(r'scopus\.com'))
                    if scopus_link:
                        scopus_url = scopus_link.get('href', '')
                        # Extraer ID de la URL
                        scopus_match = re.search(r'authorId=(\d+)', scopus_url)
                        if scopus_match:
                            data['scopus_author_id'] = scopus_match.group(1)
                            logger.debug(f"   ✅ Scopus ID encontrado: {data['scopus_author_id']}")
                
                # Web of Science ResearcherID
                elif 'Web of Science ResearcherID' in span_text or 'ResearcherID' in span_text:
                    # Buscar el span interno que contiene el ID
                    inner_spans = span.find_all('span')
                    for inner_span in inner_spans:
                        inner_text = inner_span.get_text(strip=True)
                        # El ResearcherID tiene formato: ABC-1234-2023
                        if re.match(r'^[A-Z]{3}-\d{4}-\d{4}$', inner_text):
                            data['researcher_id'] = inner_text
                            logger.debug(f"   ✅ ResearcherID encontrado: {data['researcher_id']}")
                            break
                    
                    # Si no se encontró en spans internos, buscar directamente en el link (si existe)
                    if not data['researcher_id']:
                        wos_link = span.find('a')
                        if wos_link:
                            wos_text = wos_link.get_text(strip=True)
                            if re.match(r'^[A-Z]{3}-\d{4}-\d{4}$', wos_text):
                                data['researcher_id'] = wos_text
                                logger.debug(f"   ✅ ResearcherID encontrado en link: {data['researcher_id']}")
                
                # Link Renacyt
                elif 'Ficha Renacyt' in span_text or 'Ver:' in span_text:
                    renacyt_link = span.find('a', href=re.compile(r'ficha-renacyt/\?idInvestigador='))
                    if renacyt_link:
                        data['link_renacyt'] = renacyt_link.get('href', '')
                        # Asegurar URL completa
                        if not data['link_renacyt'].startswith('http'):
                            data['link_renacyt'] = urljoin(
                                'https://servicio-renacyt.concytec.gob.pe/',
                                data['link_renacyt']
                            )
                        logger.debug(f"   ✅ Link Renacyt encontrado: {data['link_renacyt']}")
        
            # Foto de perfil
            foto_img = soup.find('img', class_='foto_investigador')
            if foto_img:
                foto_src = foto_img.get('src', '')
                if foto_src:
                    data['foto_url'] = urljoin(self.BASE_URL, foto_src)
            
            logger.debug(f"✅ Datos extraídos: {data['nombre_completo']}")
            
        except Exception as e:
            logger.error(f"❌ Error extrayendo datos: {e}")
        
        return data
    
    def scrape_researcher(self, cti_link: str) -> Optional[Dict]:
        """
        Hace scraping de una ficha de investigador
        
        Args:
            cti_link: URL completa de la ficha CTI Vitae
            
        Returns:
            Dict con datos extraídos o None si falla
        """
        try:
            logger.info(f"🔍 Scrapeando: {cti_link}")
            
            # Hacer request
            response = self.session.get(cti_link, timeout=30)
            
            if response.status_code != 200:
                logger.error(f"❌ HTTP {response.status_code}: {cti_link}")
                return None
            
            # Verificar si es HTML válido
            if 'text/html' not in response.headers.get('Content-Type', ''):
                logger.error("❌ Respuesta no es HTML")
                return None
            
            # Extraer datos
            data = self.extract_researcher_data(response.text)
            data['link_cti_vitae'] = cti_link
            
            # Pequeña pausa para no saturar
            time.sleep(1)
            
            return data
            
        except requests.exceptions.Timeout:
            logger.error(f"⏱️ Timeout: {cti_link}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error de request: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Error inesperado: {e}")
            return None
    
    def scrape_batch(
        self, 
        cti_links: list, 
        delay_between_requests: float = 2.0
    ) -> list:
        """
        Scrapea múltiples fichas con delay entre requests
        
        Args:
            cti_links: Lista de URLs
            delay_between_requests: Segundos entre cada request
            
        Returns:
            Lista de dicts con datos extraídos
        """
        results = []
        
        logger.info(f"🚀 Scraping batch de {len(cti_links)} investigadores")
        
        for idx, link in enumerate(cti_links, 1):
            logger.info(f"   [{idx}/{len(cti_links)}] Procesando...")
            
            data = self.scrape_researcher(link)
            if data:
                results.append(data)
            
            # Delay entre requests
            if idx < len(cti_links):
                time.sleep(delay_between_requests)
        
        logger.info(f"✅ Batch completado: {len(results)}/{len(cti_links)} exitosos")
        
        return results


def test_cti_vitae_scraper():
    """Test del scraper"""
    logging.basicConfig(level=logging.INFO)
    
    scraper = CTIVitaeScraper()
    
    # URL de prueba (ajustar a un investigador real)
    test_url = "https://ctivitae.concytec.gob.pe/appDirectorioCTI/VerDatosInvestigador.do?id_investigador=1557"
    
    print(f"\n🧪 Testing scraper con URL: {test_url}\n")
    
    data = scraper.scrape_researcher(test_url)
    
    if data:
        print("✅ Datos extraídos:")
        for key, value in data.items():
            if value:
                print(f"   {key}: {value}")
    else:
        print("❌ No se pudieron extraer datos")


if __name__ == "__main__":
    test_cti_vitae_scraper()