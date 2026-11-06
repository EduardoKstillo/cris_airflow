"""
Extractor de datos desde SIRI (MySQL)
Obtiene información organizacional: facultades, departamentos, afiliaciones
✅ OPTIMIZADO: Consulta Maestra Única (Evita múltiples viajes a la BD).
✅ LEFT JOIN: Protege correos de personas sin facultad asignada.
"""
import os
import sys
import logging
from typing import Dict, Any, Optional, List
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Resolución dinámica de la raíz del proyecto (Igual que en SISMO y DSpace)
BASE_DIR = Path(os.getenv('AIRFLOW_HOME', Path(__file__).resolve().parent.parent))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Carga de variables de entorno y configuración de logs
ENV_FILE = BASE_DIR / '.env'
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)
else:
    load_dotenv()  # Fallback a búsqueda estándar

LOGS_DIR = BASE_DIR / 'logs' / 'custom'
LOGS_DIR.mkdir(parents=True, exist_ok=True)
log_filename = LOGS_DIR / f"siri_extraction_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_filename, mode='w', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

class SIRIExtractor:
    def __init__(self, connection_string: Optional[str] = None):
        if connection_string:
            self.connection_string = connection_string
        else:
            host = os.getenv('SIRI_HOST')
            port = os.getenv('SIRI_PORT', '3306')
            db = os.getenv('SIRI_DB')
            user = os.getenv('SIRI_USER')
            password = os.getenv('SIRI_PASSWORD')
            
            if not all([host, db, user, password]):
                raise ValueError(
                    f"Faltan credenciales de SIRI en variables de entorno. "
                    f"(HOST: {host}, PORT: {port}, DB: {db}, USER: {user})"
                )
            
            self.connection_string = URL.create(
                drivername="mysql+pymysql",
                username=user,
                password=password,
                host=host,
                port=int(port),
                database=db,
                query={"charset": "utf8mb4"}
            )
        
        self.engine = None
        
    def connect(self) -> bool:
        try:
            self.engine = create_engine(self.connection_string, pool_pre_ping=True, pool_recycle=3600, echo=False)
            with self.engine.connect() as conn:
                version = conn.execute(text("SELECT VERSION()")).fetchone()[0]
                logger.info(f"✅ Conexión segura exitosa a SIRI MySQL ({version})")
            return True
        except Exception as e:
            logger.error(f"❌ Error conectando a SIRI: {str(e)}")
            return False
    
    def extract_data(self, sql_query: str, params: Optional[Dict] = None) -> pd.DataFrame:
        if not self.engine and not self.connect():
            raise ConnectionError("No se pudo conectar a SIRI")
        try:
            start_time = datetime.now()
            with self.engine.connect() as conn:
                df = pd.read_sql_query(text(sql_query), conn, params=params)
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"✅ Extraídos {len(df)} registros en {elapsed:.2f}s")
            return df
        except Exception as e:
            logger.error(f"❌ Error extrayendo datos: {str(e)}")
            raise
            
    def get_master_personnel_data(self, semestre_id: str) -> pd.DataFrame:
        """
        Extracción ÚNICA: Trae toda la data (Personal, Correos y Organizaciones).
        Usa LEFT JOIN para no perder personas que aún no tienen facultad asignada.
        ✅ CORREGIDO: El cruce de la facultad se hace a través del departamento 
        (sd.id_facultad = sf.id_facultad) para garantizar que nunca venga nulo.
        """
        query = """
        SELECT DISTINCT
            spd.libele AS dni,
            p.email AS email_siri,
            REPLACE(spd.apn, '/', ' ') AS nombre_completo_siri,
            sf.denominacion AS facultad,
            sf.codigo AS facultad_codigo,
            sd.denominacion AS departamento,
            sd.codigo AS departamento_codigo
        FROM siri_persona2departamento spd
        LEFT JOIN persona p ON spd.id_persona = p.idpersona
        LEFT JOIN siri_departamentos sd ON spd.dep = sd.codigo
        LEFT JOIN siri_facultades sf ON sd.id_facultad = sf.id_facultad
        WHERE spd.id_semestre = :semestre
        """
        logger.info(f"👥 Descargando Data Maestra de SIRI (Semestre ID: {semestre_id})...")
        return self.extract_data(query, params={'semestre': semestre_id})

    def get_faculties(self) -> pd.DataFrame:
        query = "SELECT DISTINCT id_facultad, denominacion, codigo, estado FROM siri_facultades WHERE estado = 'A' ORDER BY denominacion"
        return self.extract_data(query)
    
    def get_departments(self, facultad_id: Optional[int] = None) -> pd.DataFrame:
        query = "SELECT id_departamento, id_facultad, denominacion, codigo, estado FROM siri_departamentos WHERE estado = 'A'"
        if facultad_id: query += f" AND id_facultad = {facultad_id}"
        query += " ORDER BY denominacion"
        return self.extract_data(query)
    
    def close(self):
        if self.engine:
            self.engine.dispose()
            logger.info("🔌 Conexión a SIRI cerrada")