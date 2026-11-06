"""
Extractor de la API REST de SISMO
Filtra por esquemas financieros específicos y realiza guardado progresivo.
"""
import os
import sys
import json
import logging
import requests
import time
from datetime import datetime
from dotenv import load_dotenv

sys.path.insert(0, '/app/airflow')
os.makedirs("/app/airflow/logs/custom", exist_ok=True)
os.makedirs("/app/airflow/data/raw", exist_ok=True)

log_filename = f"/app/airflow/logs/custom/sismo_api_extraction_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_filename, mode='w', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

class SismoApiExtractor:
    def __init__(self):
        load_dotenv('/app/airflow/.env')
        self.session = requests.Session()
        self.url = 'https://sismo.unsa.edu.pe/bytsig/proyecto/seguimiento'
        
        self.cookie = os.getenv('SISMO_COOKIE')
        if not self.cookie:
            raise ValueError("SISMO_COOKIE no encontrada en .env")
            
        self.session.headers.update({
            'Cookie': self.cookie,
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
            'Content-Type': 'application/json;charset=UTF-8',
            'Origin': 'https://sismo.unsa.edu.pe',
            'Referer': 'https://sismo.unsa.edu.pe/bytsig/',
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36'
        })
        
        self.output_file = "/app/airflow/data/raw/sismo_raw.json"
        
        # Esquemas financieros objetivo
        self.target_schemas = [91, 23, 113, 109, 105]

    def _save_to_disk(self, data):
        """Guarda progresivamente en disco para no perder datos si se cancela"""
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def fetch_data(self):
        logger.info("\n" + "="*60 + "\n🌐 INICIANDO EXTRACCIÓN FILTRADA API SISMO\n" + "="*60)
        
        project_ids = set() # Usamos set para evitar duplicados si un proyecto estuviera en 2 esquemas
        
        # 1. Obtener la lista de proyectos por cada esquema financiero
        for schema_id in self.target_schemas:
            logger.info(f"📡 Buscando proyectos del esquema financiero: {schema_id}...")
            search_payload = {
                "C": "PROYECTO",
                "S": "FULL-SEARCH",
                "tipousuario": "view",
                "limit": 1000, 
                "page": 1,
                "idesquemafinan": str(schema_id)
            }
            
            try:
                res_search = self.session.post(self.url, json=search_payload, timeout=30)
                res_search.raise_for_status()
                search_data = res_search.json()
                
                projects_list = search_data.get('data', search_data)
                if isinstance(projects_list, list):
                    found_ids = [str(p.get('idproyecto', p.get('IDPROYECTO'))) for p in projects_list if p.get('idproyecto') or p.get('IDPROYECTO')]
                    project_ids.update(found_ids)
                    logger.info(f"   ✅ Se encontraron {len(found_ids)} proyectos para el esquema {schema_id}.")
                else:
                    logger.warning(f"   ⚠️ No se pudo extraer la lista para el esquema {schema_id}.")
                    
                time.sleep(0.5) # Pausa entre búsquedas
                
            except Exception as e:
                logger.error(f"   ❌ Error al buscar esquema {schema_id}: {e}")

        project_ids = list(project_ids)
        logger.info(f"\n🎯 Total de proyectos únicos a descargar: {len(project_ids)}")
        
        if not project_ids:
            logger.error("No se encontraron proyectos para descargar.")
            return False

        # 2. Obtener el JSON rico para cada ID
        rich_projects = []
        logger.info("\n📡 Descargando detalles profundos de cada proyecto (GETBYID)...")
        
        for idx, pid in enumerate(project_ids, 1):
            if idx % 10 == 0 or idx == 1:
                logger.info(f"   Descargando {idx}/{len(project_ids)}...")
                
            detail_payload = {
                "C": "PROYECTO",
                "S": "GETBYID",
                "idproyecto": pid
            }
            
            try:
                res_detail = self.session.post(self.url, json=detail_payload, timeout=15)
                if res_detail.status_code == 200:
                    try:
                        project_data = res_detail.json()
                        rich_projects.append(project_data)
                    except json.JSONDecodeError:
                        logger.warning(f"⚠️ El proyecto {pid} no devolvió un JSON válido.")
                
                # Guardado progresivo cada 10 proyectos
                if idx % 10 == 0:
                    self._save_to_disk(rich_projects)
                    
            except Exception as e:
                logger.error(f"   ❌ Error descargando proyecto {pid}: {e}")
            
            time.sleep(0.2) # Pausa para no saturar

        # 3. Guardado Final
        self._save_to_disk(rich_projects)
            
        file_size_mb = os.path.getsize(self.output_file) / (1024 * 1024)
        logger.info("\n" + "="*60)
        logger.info(f"✅ EXTRACCIÓN COMPLETADA EXITOSAMENTE")
        logger.info(f"📥 {len(rich_projects)} proyectos ricos descargados y guardados.")
        logger.info(f"💾 Archivo final: {self.output_file} ({file_size_mb:.2f} MB)")
        logger.info("="*60)
        return True

if __name__ == "__main__":
    extractor = SismoApiExtractor()
    extractor.fetch_data()