"""
excel_importer.py
Importa datos desde Excel y hace matching con personas en PostgreSQL
"""

import sys
sys.path.insert(0, '/app/airflow')

import os
import pandas as pd
from typing import Dict, List, Optional, Tuple
from sqlalchemy import create_engine, text
import logging
from datetime import datetime
from pathlib import Path
import uuid

from plugins.utils.name_matcher import NameMatcher

logger = logging.getLogger(__name__)


class ExcelImporter:
    """
    Importa datos de investigadores desde Excel y hace matching con BD
    """
    
    def __init__(self, connection_string: str):
        """
        Args:
            connection_string: String de conexión PostgreSQL
        """
        self.connection_string = connection_string
        self.engine = None
        self.name_matcher = NameMatcher(threshold=0.85)
        
        # Mapeo de columnas esperadas en Excel
        self.column_mapping = {
            'nombre_completo': ['nombre_completo', 'nombre', 'full_name', 'investigador'],
            'dni': ['dni', 'documento', 'doc_identidad'],
            'link_cti_vitae': ['link_cti_vitae', 'cti_vitae', 'link_cti'],
            'orcid': ['orcid', 'orcid_id'],
            'scopus_author_id': ['scopus_author_id', 'scopus_id', 'scopus'],
            'researcher_id': ['researcher_id', 'wos_id', 'web_of_science_id'],
            'gender': ['genero', 'gender', 'sexo'],
        }
        
        self.stats = {
            'total_rows': 0,
            'matched_exact_dni': 0,
            'matched_exact_name': 0,
            'matched_fuzzy': 0,
            'no_match': 0,
            'needs_review': 0,
            'updated': 0,
            'errors': []
        }
    
    def connect(self) -> bool:
        """Establece conexión con PostgreSQL"""
        try:
            self.engine = create_engine(self.connection_string, pool_pre_ping=True)
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("✅ Conectado a PostgreSQL")
            return True
        except Exception as e:
            logger.error(f"❌ Error conectando a PostgreSQL: {e}")
            return False
    
    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Normaliza nombres de columnas del Excel a formato estándar
        
        Args:
            df: DataFrame original
            
        Returns:
            DataFrame con columnas normalizadas
        """
        df_normalized = df.copy()
        
        # Convertir columnas a minúsculas y quitar espacios
        df_normalized.columns = df_normalized.columns.str.lower().str.strip()
        
        # Mapear a nombres estándar
        rename_dict = {}
        for standard_col, possible_names in self.column_mapping.items():
            for col in df_normalized.columns:
                if col in possible_names:
                    rename_dict[col] = standard_col
                    break
        
        df_normalized = df_normalized.rename(columns=rename_dict)
        
        # Log columnas reconocidas
        recognized = [col for col in self.column_mapping.keys() if col in df_normalized.columns]
        logger.info(f"📋 Columnas reconocidas: {recognized}")
        
        return df_normalized
    
    def read_excel(self, file_path: str) -> Optional[pd.DataFrame]:
        """
        Lee archivo Excel y normaliza columnas
        
        Args:
            file_path: Ruta al archivo Excel
            
        Returns:
            DataFrame normalizado o None si hay error
        """
        try:
            if not Path(file_path).exists():
                logger.error(f"❌ Archivo no encontrado: {file_path}")
                return None
            
            logger.info(f"📖 Leyendo Excel: {file_path}")
            
            # Intentar leer con diferentes engines
            try:
                df = pd.read_excel(file_path, engine='openpyxl')
            except:
                df = pd.read_excel(file_path, engine='xlrd')
            
            logger.info(f"   ✅ {len(df)} filas leídas")
            
            # Normalizar columnas
            df = self._normalize_columns(df)
            
            # Verificar columnas obligatorias
            if 'nombre_completo' not in df.columns:
                logger.error("❌ Columna 'nombre_completo' es obligatoria")
                return None
            
            # Limpiar valores nulos en nombre
            df = df[df['nombre_completo'].notna()].copy()
            
            self.stats['total_rows'] = len(df)
            
            return df
            
        except Exception as e:
            logger.error(f"❌ Error leyendo Excel: {e}")
            self.stats['errors'].append(f"Error leyendo Excel: {e}")
            return None
    
    def _fetch_all_persons_from_db(self) -> pd.DataFrame:
        """
        Obtiene todas las personas de la BD para matching
        
        Returns:
            DataFrame con id, full_name, dni de todas las personas
        """
        try:
            query = text("""
                SELECT 
                    id,
                    full_name,
                    dni,
                    orcid,
                    scopus_author_id,
                    researcher_id,
                    excel_enriched
                FROM public.persons
                WHERE validation_status != 'invalid'
            """)
            
            with self.engine.connect() as conn:
                df = pd.read_sql(query, conn)
            
            logger.info(f"   📊 {len(df)} personas cargadas de BD")
            return df
            
        except Exception as e:
            logger.error(f"❌ Error obteniendo personas de BD: {e}")
            return pd.DataFrame()
    
    def match_person(
        self, 
        excel_row: pd.Series,
        db_persons: pd.DataFrame
    ) -> Tuple[Optional[str], str, float]:
        """
        Encuentra match de una persona del Excel en la BD
        
        Estrategias (en orden):
        1. Match exacto por DNI
        2. Match exacto por nombre normalizado
        3. Match fuzzy por nombre (threshold > 0.85)
        
        Args:
            excel_row: Fila del Excel
            db_persons: DataFrame con todas las personas de BD
            
        Returns:
            (person_id, match_type, similarity_score)
        """
        excel_name = excel_row.get('nombre_completo', '')
        excel_dni = excel_row.get('dni', None)
        
        # Estrategia 1: Match por DNI
        if pd.notna(excel_dni):
            excel_dni_str = str(excel_dni).strip()
            dni_match = db_persons[db_persons['dni'] == excel_dni_str]
            
            if len(dni_match) == 1:
                logger.debug(f"   ✅ Match exacto por DNI: {excel_dni_str}")
                self.stats['matched_exact_dni'] += 1
                return (dni_match.iloc[0]['id'], 'exact_dni', 1.0)
            elif len(dni_match) > 1:
                logger.warning(f"   ⚠️ DNI duplicado en BD: {excel_dni_str}")
        
        # Estrategia 2: Match exacto por nombre normalizado
        excel_name_norm = self.name_matcher.normalize_name(excel_name)
        
        for _, person in db_persons.iterrows():
            db_name_norm = self.name_matcher.normalize_name(person['full_name'])
            if excel_name_norm == db_name_norm:
                logger.debug(f"   ✅ Match exacto por nombre: {excel_name}")
                self.stats['matched_exact_name'] += 1
                return (person['id'], 'exact_name', 1.0)
        
        # Estrategia 3: Match fuzzy
        candidates = [(row['full_name'], row['id']) for _, row in db_persons.iterrows()]
        result = self.name_matcher.find_best_match(excel_name, candidates)
        
        if result:
            person_id, score, match_type = result
            logger.debug(f"   ✅ Match fuzzy: {excel_name} (score={score:.3f})")
            self.stats['matched_fuzzy'] += 1
            return (person_id, f'fuzzy_{match_type}', score)
        
        # No match
        logger.debug(f"   ⚠️ Sin match: {excel_name}")
        self.stats['no_match'] += 1
        return (None, 'no_match', 0.0)
    
    def _save_match_candidate(
        self,
        excel_row: pd.Series,
        row_number: int,
        person_id: Optional[str],
        match_type: str,
        similarity_score: float
    ):
        """Guarda candidato de match en BD para revisión"""
        try:
            insert_query = text("""
                INSERT INTO public.person_match_candidates 
                (excel_name, excel_dni, excel_row_number, person_id, 
                 match_type, similarity_score, match_status)
                VALUES 
                (:name, :dni, :row_num, :person_id, :match_type, :score, :status)
            """)
            
            # Determinar status
            if match_type in ['exact_dni', 'exact_name']:
                status = 'confirmed'
            elif similarity_score >= 0.95:
                status = 'confirmed'
            elif similarity_score >= 0.85:
                status = 'pending'
            else:
                status = 'needs_review'
            
            with self.engine.begin() as conn:
                conn.execute(insert_query, {
                    'name': excel_row.get('nombre_completo', ''),
                    'dni': str(excel_row.get('dni', '')) if pd.notna(excel_row.get('dni')) else None,
                    'row_num': row_number,
                    'person_id': person_id,
                    'match_type': match_type,
                    'score': float(similarity_score),
                    'status': status
                })
            
            if status == 'needs_review':
                self.stats['needs_review'] += 1
                
        except Exception as e:
            logger.error(f"❌ Error guardando match candidate: {e}")
    
    def _update_person_from_excel(
        self,
        person_id: str,
        excel_row: pd.Series
    ) -> bool:
        """
        Actualiza campos de una persona con datos del Excel
        
        Args:
            person_id: UUID de la persona en BD
            excel_row: Fila del Excel con datos
            
        Returns:
            True si se actualizó correctamente
        """
        try:
            # Construir UPDATE dinámico solo con campos presentes
            updates = []
            params = {'person_id': person_id}
            
            field_mapping = {
                'orcid': 'orcid',
                'scopus_author_id': 'scopus_author_id',
                'researcher_id': 'researcher_id',
                'link_cti_vitae': 'link_cti_vitae',
                'gender': 'gender'
            }
            
            for excel_col, db_col in field_mapping.items():
                if excel_col in excel_row and pd.notna(excel_row[excel_col]):
                    value = str(excel_row[excel_col]).strip()
                    if value:  # Solo actualizar si no está vacío
                        updates.append(f"{db_col} = :{db_col}")
                        params[db_col] = value
                        
                        # Agregar source tracking
                        updates.append(f"{db_col}_source = 'excel'")
            
            if not updates:
                logger.debug(f"   ℹ️ No hay campos para actualizar en {person_id}")
                return True
            
            # Agregar flags de enriquecimiento
            updates.append("excel_enriched = TRUE")
            updates.append("excel_enriched_at = CURRENT_TIMESTAMP")
            updates.append("updated_at = CURRENT_TIMESTAMP")
            
            update_query = text(f"""
                UPDATE public.persons
                SET {', '.join(updates)}
                WHERE id = :person_id
            """)
            
            with self.engine.begin() as conn:
                result = conn.execute(update_query, params)
                
                if result.rowcount > 0:
                    self.stats['updated'] += 1
                    logger.debug(f"   ✅ Actualizado: {person_id}")
                    return True
                    
        except Exception as e:
            logger.error(f"❌ Error actualizando persona {person_id}: {e}")
            self.stats['errors'].append(f"Error actualizando {person_id}: {e}")
            return False
        
        return False
    
    def process_excel_file(
        self,
        file_path: str,
        auto_update: bool = True,
        save_candidates: bool = True
    ) -> Dict[str, any]:
        """
        Procesa archivo Excel completo
        
        Args:
            file_path: Ruta al Excel
            auto_update: Si True, actualiza automáticamente matches con score > 0.95
            save_candidates: Si True, guarda todos los matches en person_match_candidates
            
        Returns:
            Diccionario con estadísticas del proceso
        """
        logger.info("=" * 70)
        logger.info("🚀 INICIANDO IMPORTACIÓN DESDE EXCEL")
        logger.info("=" * 70)
        
        if not self.engine and not self.connect():
            return {'error': 'No se pudo conectar a PostgreSQL'}
        
        # Leer Excel
        df_excel = self.read_excel(file_path)
        if df_excel is None:
            return {'error': 'No se pudo leer el Excel'}
        
        # Obtener todas las personas de BD
        logger.info("\n📊 Cargando personas de BD...")
        db_persons = self._fetch_all_persons_from_db()
        
        if db_persons.empty:
            logger.error("❌ No hay personas en BD para hacer matching")
            return {'error': 'BD vacía'}
        
        # Procesar cada fila
        logger.info(f"\n🔄 Procesando {len(df_excel)} filas del Excel...\n")
        
        for idx, row in df_excel.iterrows():
            row_num = idx + 2  # +2 porque Excel empieza en 1 y tiene header
            
            try:
                # Encontrar match
                person_id, match_type, score = self.match_person(row, db_persons)
                
                # Guardar candidato si se solicita
                if save_candidates:
                    self._save_match_candidate(row, row_num, person_id, match_type, score)
                
                # Actualizar si hay match y score alto
                if person_id and auto_update and score >= 0.95:
                    self._update_person_from_excel(person_id, row)
                
            except Exception as e:
                logger.error(f"❌ Error procesando fila {row_num}: {e}")
                self.stats['errors'].append(f"Fila {row_num}: {e}")
        
        # Resumen
        self._log_summary()
        
        return self.stats
    
    def _log_summary(self):
        """Log del resumen de importación"""
        logger.info("\n" + "=" * 70)
        logger.info("📊 RESUMEN DE IMPORTACIÓN")
        logger.info("=" * 70)
        logger.info(f"Total filas procesadas: {self.stats['total_rows']}")
        logger.info(f"  ✅ Match exacto por DNI: {self.stats['matched_exact_dni']}")
        logger.info(f"  ✅ Match exacto por nombre: {self.stats['matched_exact_name']}")
        logger.info(f"  ✅ Match fuzzy: {self.stats['matched_fuzzy']}")
        logger.info(f"  ⚠️ Sin match: {self.stats['no_match']}")
        logger.info(f"  🔍 Requieren revisión: {self.stats['needs_review']}")
        logger.info(f"  📝 Actualizados: {self.stats['updated']}")
        
        if self.stats['errors']:
            logger.info(f"  ❌ Errores: {len(self.stats['errors'])}")
        
        logger.info("=" * 70)


def test_excel_importer():
    """Test del importer"""
    import os
    from dotenv import load_dotenv
    
    load_dotenv('/app/airflow/.env')
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Construir connection string
    host = os.getenv('POSTGRES_HOST', 'localhost')
    port = os.getenv('POSTGRES_PORT', '5432')
    db = os.getenv('POSTGRES_DB', 'cris_data')
    user = os.getenv('POSTGRES_USER', 'postgres')
    password = os.getenv('POSTGRES_PASSWORD')
    
    connection_string = f"postgresql://{user}:{password}@{host}:{port}/{db}"
    
    # Crear importer
    importer = ExcelImporter(connection_string)
    
    # Procesar archivo (ajusta la ruta)
    excel_path = "/app/airflow/data/raw/investigadores.xlsx"
    
    if not Path(excel_path).exists():
        print(f"❌ Archivo de prueba no encontrado: {excel_path}")
        return
    
    results = importer.process_excel_file(
        excel_path,
        auto_update=True,
        save_candidates=True
    )
    
    print("\n✅ Proceso completado")
    print(f"Estadísticas: {results}")


if __name__ == "__main__":
    test_excel_importer()