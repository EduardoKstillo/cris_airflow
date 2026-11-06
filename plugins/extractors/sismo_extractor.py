"""
Extractor de datos desde SISMO (PostgreSQL)
VERSIÓN INTEGRADA CON CORE - Golden Record de Personas y Contacto.
✅ SANACIÓN DE IDs: Corrige automáticamente IDs fantasmas buscando por Nombre.
✅ Usa `contrato.id_persona` como fuente de la verdad para el PI.
✅ Extrae contacto (Email/Teléfono) usando Regex desde `persona_contacto`.
✅ SEGURIDAD: Conexión cifrada sin exponer credenciales en Logs (URL.create).
"""
import os
import sys
import logging
from typing import Dict, Any, Optional
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Resolución dinámica de la raíz del proyecto (Igual que en DSpace)
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
log_filename = LOGS_DIR / f"sismo_extraction_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_filename, mode='w', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

class SISMOExtractor:
    """Extractor de datos desde la base de datos SISMO (PostgreSQL)"""
    
    def __init__(self, connection_string: Optional[str] = None):
        if connection_string:
            self.connection_string = connection_string
        else:
            host = os.getenv('SISMO_HOST')
            port = os.getenv('SISMO_PORT', '5431')
            db = os.getenv('SISMO_DB')
            user = os.getenv('SISMO_USER')
            password = os.getenv('SISMO_PASSWORD')
            
            if not all([host, db, user, password]):
                raise ValueError(
                    f"Faltan credenciales de SISMO en variables de entorno. "
                    f"(HOST: {host}, PORT: {port}, DB: {db}, USER: {user})"
                )
            
            # URL.create evita que la contraseña se filtre en los stack traces de errores
            self.connection_string = URL.create(
                drivername="postgresql",
                username=user,
                password=password,
                host=host,
                port=port,
                database=db
            )
        
        self.engine = None
        
    def connect(self) -> bool:
        try:
            self.engine = create_engine(
                self.connection_string,
                pool_pre_ping=True,
                pool_recycle=3600,
                echo=False
            )
            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT version()"))
                version = result.fetchone()[0]
                logger.info("✅ Conexión exitosa a SISMO PostgreSQL (Con Integración Core y Sanación)")
            return True
        except Exception as e:
            logger.error(f"❌ Error conectando a SISMO (Verifique credenciales y red): {e}")
            return False
    
    def extract_data(self, sql_query: str, params: Optional[Dict] = None) -> pd.DataFrame:
        if not self.engine:
            if not self.connect():
                raise ConnectionError("No se pudo conectar a SISMO")
        
        try:
            start_time = datetime.now()
            with self.engine.connect() as connection:
                df = pd.read_sql_query(text(sql_query), connection, params=params)
            
            execution_time = (datetime.now() - start_time).total_seconds()
            logger.info(f"✅ Extraídos {len(df)} registros en {execution_time:.2f}s")
            return df
            
        except Exception as e:
            logger.error(f"❌ Error extrayendo datos: {str(e)}")
            raise
    
    def extract_projects_and_grants(self) -> pd.DataFrame:
        projects_sql = """
        SELECT DISTINCT
            p.id_proyecto,
            p.nomb_proy as nombre_proyecto, 
            c.numero_cont as codigo_proyecto, 
            p.tipo_proy as tipo_proyecto, 
            p.resumen_ejecutivo as resumen_proyecto,
            p.just_proy as justificacion_proyecto,
            p.hipo_proy as hipotesis_proyecto,
            p.resul_espe_proy as resultado_esperado_proyecto,
            p.impacto_proy as impacto_proyecto,    
            p.obj_general_proy as objetivo_general_proyecto,
            p.est_proy,
            COALESCE(
                CASE p.est_proy
                    WHEN 'R' THEN 'Registrado'
                    WHEN 'V' THEN 'Enviado para revisión al monitor'
                    WHEN 'T' THEN 'Enviado al coordinador de esquema'
                    WHEN 'E' THEN 'En Ejecución'
                    WHEN 'C' THEN 'Cerrado'
                    WHEN 'O' THEN 'Observado'
                    WHEN 'X' THEN 'Anulado'
                    WHEN 'A' THEN 'Cancelado'
                    WHEN 'D' THEN 'En proceso de cierre'
                    ELSE '--'
                END, '--'
            ) AS descripcion_estado,   
            p.claves_proy as keywords, 
            p.fech_ini_proy as fecha_inicial_proyecto,
            p.durac_proy as duracion_proyecto_meses,      
            
            c.id_contrato,
            c.numero_cont AS numero_contrato,
            c.desc_cont AS nombre_contrato,
            c.id_persona AS id_investigador_principal,
            
            lis.cod_lista as moneda, 
            c.monto_cont as monto_contrato, 
            
            tipo_subvencion.desc_lista as tipo_subvencion,
            c.id_monitor,   
            CONCAT(TRIM(per2.ape_pat_per), ' ', TRIM(per2.ape_mat_per), ', ', TRIM(per2.nomb_per)) AS nombre_monitor, 
            c.id_coordinador,
            CONCAT(TRIM(per3.ape_pat_per), ' ', TRIM(per3.ape_mat_per), ', ', TRIM(per3.nomb_per)) AS nombre_coordinador, 
            
            f.id_fuente,
            f.desc_fuente as descripcion_fuente,
            f.abre_fuente AS abreviatura_fuente,
            f.esta_fuente AS estado_fuente,
            
            con.id_convocatoria,
            con.codigo_conv as codigo_convocatoria,
            con.nomb_conv as nombre_convocatoria, 
            con.id_esquema_finan,        
            ap1.type_areapri AS type_area_prioritaria, 
            ap1.nomb_areapri AS nombre_area_prioritaria,
            ap2.type_areapri AS type_area_investigacion, 
            ap2.nomb_areapri AS nombre_area_investigacion,
            ap3.type_areapri AS type_linea_investigacion, 
            ap3.nomb_areapri AS nombre_linea_investigacion    
        FROM 
            bytsscom_bytsig.proyecto p
            JOIN bytsscom_bytsig.contrato c ON p.id_proyecto = c.id_contrato
            JOIN bytsscom_bytsig.convocatoria con ON c.id_convocatoria = con.id_convocatoria
            JOIN bytsscom_bytsig.esquema_finan ef ON con.id_esquema_finan = ef.id_esquema_finan
            JOIN bytsscom_bytcore.fuente f ON c.id_fuente = f.id_fuente
            
            LEFT JOIN bytsscom_bytcore.persona per2 ON c.id_monitor = per2.id_persona
            LEFT JOIN bytsscom_bytcore.persona per3 ON c.id_coordinador = per3.id_persona
            
            JOIN bytsscom_bytcore.lista lis ON c.id_moneda = lis.id_lista 
            LEFT JOIN bytsscom_bytcore.lista tipo_subvencion ON p.id_tiposubvencionado = tipo_subvencion.id_lista 
            LEFT JOIN bytsscom_bytsig.area_prioritaria ap1 ON p.id_area_prioritaria = ap1.id_area_prioritaria
            LEFT JOIN bytsscom_bytsig.area_prioritaria ap2 ON p.id_area_investigacion = ap2.id_area_prioritaria
            LEFT JOIN bytsscom_bytsig.area_prioritaria ap3 ON p.id_linea_investigacion = ap3.id_area_prioritaria    
        WHERE 
            p.tipo_proy IN (
                'E041 - Proyectos de Investigación Básica y Aplicada - UNSA',
                'E044 - Equipamiento Científico para la investigación - UNSA',
                'E056 - Proyectos de Tesis - UNSA',
                'Proyectos de Investigación en Recursos Genéticos de Planta Nativas y Banco de Germoplasma',
                'PROYECTOS UNSA CON FINANCIAMIENTO EXTERNO'
            ) 
            AND p.codigo_proy IS NOT NULL
            AND TRIM(p.codigo_proy) <> ''
            AND c.numero_cont IS NOT NULL
            AND TRIM(c.numero_cont) <> ''
            AND p.id_proyecto <> 6023
        ORDER BY p.id_proyecto
        """
        logger.info("📊 Ejecutando SQL de Proyectos y Contratos...")
        return self.extract_data(projects_sql)

    def extract_team_members(self) -> pd.DataFrame:
        team_sql = """
        WITH EquipoCrudo AS (
            SELECT 
                pe.id_proyecto, pe.cargo_equipo, pe.tiene_rel_contrac, pe.full_name_per,
                c.id_persona as id_contrato_pi, pe.id_persona as id_original_pe
            FROM bytsscom_bytsig.proyecto_equipo pe
            LEFT JOIN bytsscom_bytsig.contrato c ON pe.id_proyecto = c.id_contrato
            UNION
            SELECT 
                c.id_contrato as id_proyecto, 'Investigador Principal' as cargo_equipo,
                '1' as tiene_rel_contrac, NULL as full_name_per,
                c.id_persona as id_contrato_pi, c.id_persona as id_original_pe
            FROM bytsscom_bytsig.contrato c
            WHERE c.id_persona IS NOT NULL
        ),
        EquipoSanado AS (
            SELECT 
                ec.id_proyecto, ec.cargo_equipo, ec.tiene_rel_contrac, ec.full_name_per,
                COALESCE(
                    CASE WHEN ec.cargo_equipo ILIKE '%Investigador Principal%' AND ec.id_contrato_pi IS NOT NULL THEN ec.id_contrato_pi ELSE NULL END,
                    (SELECT id_persona FROM bytsscom_bytcore.persona WHERE id_persona = ec.id_original_pe LIMIT 1),
                    (SELECT id_persona FROM bytsscom_bytcore.persona 
                     WHERE ec.full_name_per IS NOT NULL 
                     AND UPPER(CONCAT(TRIM(ape_pat_per), ' ', TRIM(ape_mat_per), ', ', TRIM(nomb_per))) = UPPER(TRIM(ec.full_name_per)) 
                     LIMIT 1),
                    ec.id_original_pe
                ) as id_persona_real
            FROM EquipoCrudo ec
        ),
        Contactos AS (
            SELECT 
                pc.id_persona,
                json_agg(
                    json_build_object(
                        'type', COALESCE(l.cod_lista, 'OTRO'),
                        'value', TRIM(pc.data_contacto)
                    )
                )::text as contactos_json
            FROM bytsscom_bytcore.persona_contacto pc
            LEFT JOIN bytsscom_bytcore.lista l ON pc.id_tipo_contacto = l.id_lista
            WHERE pc.data_contacto IS NOT NULL AND TRIM(pc.data_contacto) <> ''
            GROUP BY pc.id_persona
        )
        SELECT DISTINCT
            es.id_proyecto,
            es.id_persona_real as id_persona,
            es.cargo_equipo as cargo_original_sismo,
            es.tiene_rel_contrac,
            per.nro_doc_per as numero_documento,
            lis2.cod_lista as documento,
            per.sex_per as genero,
            COALESCE(
                CONCAT(TRIM(per.ape_pat_per), ' ', TRIM(per.ape_mat_per), ', ', TRIM(per.nomb_per)), 
                es.full_name_per
            ) AS nombre_completo_investigador,
            con.contactos_json as contactos
        FROM 
            EquipoSanado es
            JOIN bytsscom_bytsig.proyecto p ON es.id_proyecto = p.id_proyecto
            LEFT JOIN bytsscom_bytcore.persona per ON es.id_persona_real = per.id_persona
            LEFT JOIN bytsscom_bytcore.lista lis2 ON per.tipo_doc_per = lis2.id_lista
            LEFT JOIN Contactos con ON es.id_persona_real = con.id_persona
        WHERE 
            p.tipo_proy IN (
                'E041 - Proyectos de Investigación Básica y Aplicada - UNSA',
                'E044 - Equipamiento Científico para la investigación - UNSA',
                'E056 - Proyectos de Tesis - UNSA',
                'Proyectos de Investigación en Recursos Genéticos de Planta Nativas y Banco de Germoplasma',
                'PROYECTOS UNSA CON FINANCIAMIENTO EXTERNO'
            ) 
            AND p.codigo_proy IS NOT NULL 
            AND TRIM(p.codigo_proy) <> ''
            AND es.id_persona_real IS NOT NULL
            AND p.id_proyecto <> 6023
        """
        logger.info("👥 Ejecutando SQL del Equipo del Proyecto (Extracción Semántica de Contactos)...")
        return self.extract_data(team_sql)
    
    def close(self):
        if self.engine:
            self.engine.dispose()
            logger.info("🔌 Conexión a SISMO cerrada")

def main():
    extractor = SISMOExtractor()

    if not extractor.connect():
        return

    try:
        df_projects = extractor.extract_projects_and_grants()

        print("Filas extraídas:", len(df_projects))
        print("Proyectos únicos:", df_projects["id_proyecto"].nunique())
        print("Duplicados:", df_projects["id_proyecto"].duplicated().sum())

        df_team = extractor.extract_team_members()
        print(f"- Proyectos únicos: {df_projects['id_proyecto'].nunique()}")
        print(f"- Miembros de equipo encontrados: {len(df_team)}")
        print("\n✅ Extracción completada exitosamente!")
    except Exception as e:
        print(f"❌ Error al extraer los datos: {e}")
    finally:
        extractor.close()

if __name__ == "__main__":
    main()