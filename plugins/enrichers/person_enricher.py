"""
person_enricher.py
Orquestador principal del proceso de enriquecimiento de personas
Coordina Excel, CTI Vitae y Renacyt API (solo datos básicos)
"""

import sys
sys.path.insert(0, '/app/airflow')

import os
from typing import Dict, Optional, List
from sqlalchemy import create_engine, text
import logging
from datetime import datetime
import json

from plugins.enrichers.excel_importer import ExcelImporter
from plugins.enrichers.cti_vitae_scraper import CTIVitaeScraper
from plugins.enrichers.cti_vitae_searcher import CTIVitaeSearcher
from plugins.enrichers.renacyt_api_client import RenacytAPIClient
from plugins.utils.name_matcher import NameMatcher

logger = logging.getLogger(__name__)


class PersonEnricher:
    """
    Orquestador del enriquecimiento de personas
    Ejecuta pipeline completo: Excel → CTI Vitae → Renacyt API
    """
    
    def __init__(self, connection_string: str):
        """
        Args:
            connection_string: String de conexión PostgreSQL
        """
        self.connection_string = connection_string
        self.engine = None
        
        # Inicializar componentes
        self.excel_importer = ExcelImporter(connection_string)
        self.cti_scraper = CTIVitaeScraper()
        self.renacyt_client = RenacytAPIClient()
        self.name_matcher = NameMatcher()
        
        # Estadísticas globales
        self.stats = {
            'total_persons': 0,
            'enriched_from_excel': 0,
            'enriched_from_cti': 0,
            'enriched_from_renacyt': 0,
            'errors': []
        }
    
    def connect(self) -> bool:
        """Establece conexión con PostgreSQL"""
        try:
            self.engine = create_engine(self.connection_string, pool_pre_ping=True)
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("✅ PersonEnricher conectado a PostgreSQL")
            return True
        except Exception as e:
            logger.error(f"❌ Error conectando: {e}")
            return False
    
    def enrich_from_excel(
        self, 
        excel_path: str,
        auto_update: bool = True
    ) -> Dict:
        """
        Fase 1: Enriquecimiento desde Excel
        
        Args:
            excel_path: Ruta al archivo Excel
            auto_update: Si True, actualiza automáticamente
            
        Returns:
            Estadísticas del proceso
        """
        logger.info("\n" + "="*70)
        logger.info("📊 FASE 1: ENRIQUECIMIENTO DESDE EXCEL")
        logger.info("="*70)
        
        results = self.excel_importer.process_excel_file(
            excel_path,
            auto_update=auto_update,
            save_candidates=True
        )
        
        self.stats['enriched_from_excel'] = results.get('updated', 0)
        
        return results
    
    def get_persons_needing_cti_enrichment(self, limit: int = None) -> List[Dict]:
        """
        Obtiene personas que necesitan enriquecimiento desde CTI Vitae
        
        Args:
            limit: Límite de registros a retornar
            
        Returns:
            Lista de dicts con id, full_name, link_cti_vitae
        """
        if not self.engine and not self.connect():
            return []
        
        try:
            query = text("""
                SELECT id, full_name, dni, link_cti_vitae
                FROM public.persons
                WHERE cti_vitae_enriched = FALSE
                AND enrichment_status != 'failed'
                AND (enrichment_attempts IS NULL OR enrichment_attempts < 3)
                ORDER BY 
                    link_cti_vitae IS NOT NULL DESC,
                    last_enrichment_attempt ASC NULLS FIRST
                LIMIT :limit
            """)
            
            with self.engine.connect() as conn:
                result = conn.execute(query, {'limit': limit or 1000})
                persons = [dict(row._mapping) for row in result]
            
            logger.info(f"📋 {len(persons)} personas necesitan enriquecimiento CTI")
            return persons
            
        except Exception as e:
            logger.error(f"❌ Error obteniendo personas: {e}")
            return []
    
    def enrich_person_from_cti(self, person: Dict) -> bool:
        """
        Enriquece una persona desde CTI Vitae
        
        Args:
            person: Dict con datos de la persona
            
        Returns:
            True si se enriqueció exitosamente
        """
        person_id = person['id']
        full_name = person['full_name']
        link_cti = person.get('link_cti_vitae')
        
        start_time = datetime.now()
        
        try:
            # Caso 1: Ya tiene link_cti_vitae
            if link_cti:
                logger.info(f"🔍 Enriqueciendo (con link): {full_name}")
                cti_data = self.cti_scraper.scrape_researcher(link_cti)
                
            # Caso 2: Necesita buscar primero
            else:
                logger.info(f"🔍 Buscando en CTI Vitae: {full_name}")
                
                # Marcar como "needs manual search"
                self._log_enrichment_attempt(
                    person_id,
                    'cti_vitae_search',
                    'skipped',
                    error_message="Requiere búsqueda manual (no tiene link)",
                    execution_time=(datetime.now() - start_time).total_seconds()
                )
                return False
            
            # Actualizar BD con datos obtenidos
            if cti_data:
                success = self._update_person_with_cti_data(person_id, cti_data)
                
                if success:
                    execution_time = (datetime.now() - start_time).total_seconds()
                    self._log_enrichment_attempt(
                        person_id,
                        'cti_vitae',
                        'success',
                        fields_updated=list(cti_data.keys()),
                        raw_data=cti_data,
                        execution_time=execution_time
                    )
                    self.stats['enriched_from_cti'] += 1
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ Error enriqueciendo {full_name}: {e}")
            self._log_enrichment_attempt(
                person_id,
                'cti_vitae',
                'failed',
                error_message=str(e),
                execution_time=(datetime.now() - start_time).total_seconds()
            )
            return False
    
    def _update_person_with_cti_data(self, person_id: str, cti_data: Dict) -> bool:
        """Actualiza persona con datos de CTI Vitae"""
        try:
            updates = []
            params = {'person_id': person_id}
            
            # Mapear campos
            field_mapping = {
                'orcid': 'orcid',
                'scopus_author_id': 'scopus_author_id',
                'researcher_id': 'researcher_id',
                'link_cti_vitae': 'link_cti_vitae',
                'link_renacyt': 'link_renacyt',
                'foto_url': 'foto_url',
                'descripcion': 'description'
            }
            
            for cti_field, db_field in field_mapping.items():
                if cti_field in cti_data and cti_data[cti_field]:
                    updates.append(f"{db_field} = :{db_field}")
                    params[db_field] = cti_data[cti_field]
                    
                    # Source tracking
                    if db_field in ['orcid', 'scopus_author_id', 'researcher_id']:
                        updates.append(f"{db_field}_source = 'cti_vitae'")
            
            if not updates:
                return False
            
            # Agregar flags
            updates.append("cti_vitae_enriched = TRUE")
            updates.append("cti_vitae_enriched_at = CURRENT_TIMESTAMP")
            updates.append("enrichment_attempts = COALESCE(enrichment_attempts, 0) + 1")
            updates.append("last_enrichment_attempt = CURRENT_TIMESTAMP")
            updates.append("updated_at = CURRENT_TIMESTAMP")
            
            update_query = text(f"""
                UPDATE public.persons
                SET {', '.join(updates)}
                WHERE id = :person_id
            """)
            
            with self.engine.begin() as conn:
                result = conn.execute(update_query, params)
                return result.rowcount > 0
                
        except Exception as e:
            logger.error(f"❌ Error actualizando persona: {e}")
            return False
    
    def enrich_person_from_renacyt(self, person: Dict) -> bool:
        """
        Enriquece una persona desde Renacyt API (solo datos básicos)
        
        Datos extraídos:
        - Nivel Renacyt
        - Condición (Vigente/Vencido)
        - Institución laboral principal y actual
        - Contacto (teléfonos)
        - Ubicación (departamento, provincia, distrito, dirección)
        - Formación académica
        
        Args:
            person: Dict con datos de la persona
            
        Returns:
            True si se enriqueció exitosamente
        """
        person_id = person['id']
        link_renacyt = person.get('link_renacyt')
        
        if not link_renacyt:
            logger.debug(f"   ⏭️ Sin link Renacyt: {person['full_name']}")
            return False
        
        start_time = datetime.now()
        
        try:
            logger.info(f"🔍 Enriqueciendo desde Renacyt API: {person['full_name']}")
            
            # Obtener perfil completo de Renacyt
            renacyt_data = self.renacyt_client.get_complete_profile_from_url(link_renacyt)
            
            if renacyt_data:
                success = self._update_person_with_renacyt_data(person_id, renacyt_data)
                
                if success:
                    execution_time = (datetime.now() - start_time).total_seconds()
                    
                    # Lista de campos actualizados
                    fields_updated = [
                        'nivel_renacyt', 'condicion_renacyt',
                        'institucion_laboral_principal', 'institucion_laboral_actual',
                        'telefono_fijo', 'telefono_celular',
                        'departamento', 'provincia', 'distrito', 'direccion',
                        'formacion_academica'
                    ]
                    
                    self._log_enrichment_attempt(
                        person_id,
                        'renacyt',
                        'success',
                        fields_updated=fields_updated,
                        raw_data=renacyt_data,
                        execution_time=execution_time
                    )
                    self.stats['enriched_from_renacyt'] += 1
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ Error enriqueciendo desde Renacyt: {e}")
            self._log_enrichment_attempt(
                person_id,
                'renacyt',
                'failed',
                error_message=str(e),
                execution_time=(datetime.now() - start_time).total_seconds()
            )
            return False
    
    def _update_person_with_renacyt_data(self, person_id: str, renacyt_data: Dict) -> bool:
        """
        Actualiza persona con datos básicos de Renacyt API
        
        SOLO se guardan:
        - nivel_renacyt
        - condicion_renacyt
        - institucion_laboral_principal
        - institucion_laboral_actual
        - telefono_fijo, telefono_celular
        - departamento, provincia, distrito, direccion
        - formacion_academica (JSON)
        
        Los demás campos (DNI, ORCID, etc.) se usan solo para VALIDACIÓN
        """
        try:
            updates = []
            params = {'person_id': person_id}
            
            # Mapeo de campos BÁSICOS (sin datos de validación)
            field_mapping = {
                # Renacyt básico
                'nivel': 'nivel_renacyt',
                'condicion': 'condicion_renacyt',
                
                # Institucional
                'institucion_laboral_principal': 'institucion_laboral_principal',
                'institucion_laboral_actual': 'institucion_laboral_actual',
                
                # Contacto
                'telefono_fijo': 'telefono_fijo',
                'telefono_celular': 'telefono_celular',
                
                # Ubicación
                'direccion': 'direccion',
                'departamento': 'departamento',
                'provincia': 'provincia',
                'distrito': 'distrito',
            }
            
            for renacyt_field, db_field in field_mapping.items():
                if renacyt_field in renacyt_data and renacyt_data[renacyt_field]:
                    value = renacyt_data[renacyt_field]
                    
                    # Limpiar strings vacíos
                    if isinstance(value, str):
                        value = value.strip()
                        if not value:
                            continue
                    
                    updates.append(f"{db_field} = :{db_field}")
                    params[db_field] = value
            
            # Formación académica (JSON)
            if renacyt_data.get('formacion_academica'):
                updates.append("formacion_academica = :formacion_academica")
                params['formacion_academica'] = json.dumps(
                    renacyt_data['formacion_academica'],
                    ensure_ascii=False
                )
            
            if not updates:
                logger.warning(f"⚠️ No hay datos básicos para actualizar desde Renacyt para {person_id}")
                return False
            
            # Flags de enriquecimiento
            updates.append("renacyt_enriched = TRUE")
            updates.append("renacyt_enriched_at = CURRENT_TIMESTAMP")
            updates.append("updated_at = CURRENT_TIMESTAMP")
            
            update_query = text(f"""
                UPDATE public.persons
                SET {', '.join(updates)}
                WHERE id = :person_id
            """)
            
            with self.engine.begin() as conn:
                result = conn.execute(update_query, params)
                
                if result.rowcount > 0:
                    logger.info(f"   ✅ {len(updates)} campos actualizados desde Renacyt")
                    return True
                
                return False
                
        except Exception as e:
            logger.error(f"❌ Error actualizando con datos Renacyt: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return False
    
    def _log_enrichment_attempt(
        self,
        person_id: str,
        source: str,
        status: str,
        fields_updated: List[str] = None,
        error_message: str = None,
        raw_data: Dict = None,
        execution_time: float = None
    ):
        """Registra intento de enriquecimiento en log"""
        try:
            insert_query = text("""
                INSERT INTO public.person_enrichment_log
                (person_id, enrichment_source, status, fields_updated, 
                 error_message, raw_data, execution_time_seconds)
                VALUES
                (:person_id, :source, :status, :fields, :error, :raw_data, :exec_time)
            """)
            
            with self.engine.begin() as conn:
                conn.execute(insert_query, {
                    'person_id': person_id,
                    'source': source,
                    'status': status,
                    'fields': fields_updated,
                    'error': error_message,
                    'raw_data': json.dumps(raw_data, ensure_ascii=False) if raw_data else None,
                    'exec_time': execution_time
                })
                
        except Exception as e:
            logger.error(f"❌ Error guardando log: {e}")
    
    def run_full_enrichment_pipeline(
        self,
        excel_path: Optional[str] = None,
        enrich_cti: bool = True,
        enrich_renacyt: bool = True,
        batch_size: int = 50
    ) -> Dict:
        """
        Ejecuta pipeline completo de enriquecimiento
        
        Args:
            excel_path: Ruta al Excel (opcional)
            enrich_cti: Si True, enriquece desde CTI Vitae
            enrich_renacyt: Si True, enriquece desde Renacyt
            batch_size: Tamaño de lote para procesamiento
            
        Returns:
            Estadísticas del proceso completo
        """
        logger.info("\n" + "="*70)
        logger.info("🚀 INICIANDO PIPELINE COMPLETO DE ENRIQUECIMIENTO")
        logger.info("="*70)
        
        # Fase 1: Excel
        if excel_path:
            self.enrich_from_excel(excel_path, auto_update=True)
        
        # Fase 2: CTI Vitae
        if enrich_cti:
            logger.info("\n" + "="*70)
            logger.info("📚 FASE 2: ENRIQUECIMIENTO DESDE CTI VITAE")
            logger.info("="*70)
            
            persons = self.get_persons_needing_cti_enrichment(limit=batch_size)
            self.stats['total_persons'] = len(persons)
            
            for idx, person in enumerate(persons, 1):
                logger.info(f"\n[{idx}/{len(persons)}] Procesando...")
                self.enrich_person_from_cti(person)
        
        # Fase 3: Renacyt API
        if enrich_renacyt:
            logger.info("\n" + "="*70)
            logger.info("🎓 FASE 3: ENRIQUECIMIENTO DESDE RENACYT API")
            logger.info("="*70)
            
            persons_with_renacyt = self._get_persons_with_renacyt_link(batch_size)
            
            for idx, person in enumerate(persons_with_renacyt, 1):
                logger.info(f"\n[{idx}/{len(persons_with_renacyt)}] Procesando...")
                self.enrich_person_from_renacyt(person)
        
        # Resumen final
        self._log_final_summary()
        
        return self.stats
    
    def _get_persons_with_renacyt_link(self, limit: int) -> List[Dict]:
        """Obtiene personas con link Renacyt pendientes de enriquecimiento"""
        try:
            query = text("""
                SELECT id, full_name, link_renacyt
                FROM public.persons
                WHERE link_renacyt IS NOT NULL
                AND renacyt_enriched = FALSE
                AND enrichment_status != 'failed'
                LIMIT :limit
            """)
            
            with self.engine.connect() as conn:
                result = conn.execute(query, {'limit': limit})
                return [dict(row._mapping) for row in result]
                
        except Exception as e:
            logger.error(f"❌ Error obteniendo personas con Renacyt: {e}")
            return []
    
    def _log_final_summary(self):
        """Log del resumen final"""
        logger.info("\n" + "="*70)
        logger.info("📊 RESUMEN FINAL DE ENRIQUECIMIENTO")
        logger.info("="*70)
        logger.info(f"Total personas procesadas: {self.stats['total_persons']}")
        logger.info(f"  ✅ Enriquecidas desde Excel: {self.stats['enriched_from_excel']}")
        logger.info(f"  ✅ Enriquecidas desde CTI Vitae: {self.stats['enriched_from_cti']}")
        logger.info(f"  ✅ Enriquecidas desde Renacyt API: {self.stats['enriched_from_renacyt']}")
        
        if self.stats['errors']:
            logger.info(f"  ❌ Errores: {len(self.stats['errors'])}")
        
        logger.info("="*70)


def test_person_enricher():
    """Test del enricher"""
    import os
    from dotenv import load_dotenv
    
    load_dotenv('/app/airflow/.env')
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Connection string
    host = os.getenv('POSTGRES_HOST', 'localhost')
    port = os.getenv('POSTGRES_PORT', '5432')
    db = os.getenv('POSTGRES_DB', 'cris_data')
    user = os.getenv('POSTGRES_USER', 'postgres')
    password = os.getenv('POSTGRES_PASSWORD')
    
    connection_string = f"postgresql://{user}:{password}@{host}:{port}/{db}"
    
    # Crear enricher
    enricher = PersonEnricher(connection_string)
    
    # Ejecutar pipeline
    excel_path = "/app/airflow/data/raw/investigadores.xlsx"
    
    results = enricher.run_full_enrichment_pipeline(
        excel_path=excel_path if os.path.exists(excel_path) else None,
        enrich_cti=True,
        enrich_renacyt=True,
        batch_size=10
    )
    
    print("\n✅ Pipeline completado")
    print(f"Estadísticas: {results}")


if __name__ == "__main__":
    test_person_enricher()