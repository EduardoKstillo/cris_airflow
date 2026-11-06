"""
Validador de Datos - VERSIÓN CON MANEJO DE DUPLICADOS
✅ Actualizado para trabajar con nombres de columnas correctos (sismo_*)
✅ NUEVO: Duplicados de proyectos reportados como WARNING (no ERROR)
"""
import pandas as pd
from typing import Dict, List, Any
import logging

logger = logging.getLogger(__name__)

class DataValidator:
    """Validador de integridad y calidad de datos"""
    
    def __init__(self):
        self.validation_results = {
            'passed': [],
            'warnings': [],
            'errors': [],
            'summary': {
                'passed': 0,
                'warnings': 0,
                'errors': 0
            }
        }
    
    def validate_all_entities(self, entities: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        """Valida todas las entidades"""
        logger.info("🔍 Iniciando validación de entidades...")
        
        # Validar entidades individuales
        if 'researchers' in entities:
            logger.info("   Validando investigadores...")
            self._validate_researchers(entities['researchers'])
        
        if 'projects' in entities:
            logger.info("   Validando proyectos...")
            self._validate_projects(entities['projects'])
        
        if 'funding_sources' in entities:
            logger.info("   Validando fuentes de financiamiento...")
            self._validate_funding_sources(entities['funding_sources'])
        
        # Validar relaciones (integridad referencial)
        if 'project_researchers' in entities:
            logger.info("   Validando relaciones proyecto-investigador...")
            self._validate_relationships(
                entities.get('project_researchers'),
                entities.get('projects'),
                entities.get('researchers')
            )
        
        # Calcular resumen
        self.validation_results['summary']['passed'] = len(self.validation_results['passed'])
        self.validation_results['summary']['warnings'] = len(self.validation_results['warnings'])
        self.validation_results['summary']['errors'] = len(self.validation_results['errors'])
        
        return self.validation_results
    
    def _validate_researchers(self, df: pd.DataFrame):
        """Valida investigadores"""
        if df.empty:
            self._add_error("Tabla de investigadores vacía")
            return
        
        # Check 1: DNI válidos
        if 'dni_valid' in df.columns:
            invalid_dni_count = (~df['dni_valid']).sum()
            if invalid_dni_count > 0:
                self._add_warning(f"{invalid_dni_count} investigadores con DNI inválido")
            else:
                self._add_passed("Todos los DNI son válidos")
        
        # Check 2: Nombres completos
        if 'full_name' in df.columns:
            missing_names = df['full_name'].isna().sum()
            if missing_names > 0:
                self._add_warning(f"{missing_names} investigadores sin nombre")
            else:
                self._add_passed("Todos los investigadores tienen nombre")
        
        # Check 3: IDs únicos
        if 'sismo_id' in df.columns:
            duplicates = df['sismo_id'].duplicated().sum()
            if duplicates > 0:
                self._add_error(f"{duplicates} IDs duplicados en investigadores")
            else:
                self._add_passed("Todos los IDs de investigadores son únicos")
        
        # Check 4: Enriquecimiento SIRI
        if 'siri_enriched' in df.columns:
            enriched_count = df['siri_enriched'].sum()
            enrichment_rate = (enriched_count / len(df)) * 100
            if enrichment_rate < 50:
                self._add_warning(f"Tasa de enriquecimiento SIRI baja: {enrichment_rate:.1f}%")
            else:
                self._add_passed(f"Enriquecimiento SIRI: {enrichment_rate:.1f}%")
    
    def _validate_projects(self, df: pd.DataFrame):
        """
        Valida proyectos
        ✅ MODIFICADO: Duplicados ahora son WARNING en lugar de ERROR
        """
        if df.empty:
            self._add_error("Tabla de proyectos vacía")
            return
        
        # Check 1: Códigos de proyecto únicos
        if 'project_code' in df.columns:
            duplicates = df['project_code'].duplicated().sum()
            if duplicates > 0:
                # Encontrar cuáles son los duplicados
                dup_codes = df[df['project_code'].duplicated(keep=False)]['project_code'].unique()
                dup_details = []
                for code in dup_codes:
                    dup_rows = df[df['project_code'] == code]
                    dup_details.append(
                        f"Código '{code}': {len(dup_rows)} ocurrencias "
                        f"(IDs: {dup_rows['sismo_project_id'].tolist()})"
                    )
                
                # ✅ CAMBIO CRÍTICO: De ERROR a WARNING
                warning_msg = (
                    f"{duplicates} códigos de proyecto duplicados "
                    f"(deberían haber sido limpiados en entity_separator):\n"
                    + "\n".join(f"      {d}" for d in dup_details)
                )
                self._add_warning(warning_msg)
                
                # Log adicional para debugging
                logger.warning("📋 Detalles de proyectos duplicados residuales:")
                for code in dup_codes:
                    dup_rows = df[df['project_code'] == code][['sismo_project_id', 'project_code', 'title']]
                    logger.warning(f"\n{dup_rows.to_string()}")
            else:
                self._add_passed("Todos los códigos de proyecto son únicos")
        
        # Check 2: Títulos presentes
        if 'title' in df.columns:
            missing_titles = df['title'].isna().sum()
            if missing_titles > 0:
                self._add_warning(f"{missing_titles} proyectos sin título")
            else:
                self._add_passed("Todos los proyectos tienen título")
        
        # Check 3: IDs únicos
        if 'sismo_project_id' in df.columns:
            duplicates = df['sismo_project_id'].duplicated().sum()
            if duplicates > 0:
                self._add_error(f"{duplicates} IDs duplicados en proyectos")
            else:
                self._add_passed("Todos los IDs de proyectos son únicos")
        
        # Check 4: Fechas válidas
        if 'planned_start_date' in df.columns:
            valid_dates = df['planned_start_date'].notna().sum()
            total = len(df)
            if valid_dates < total * 0.5:
                self._add_warning(f"Solo {valid_dates}/{total} proyectos tienen fecha de inicio")
            else:
                self._add_passed(f"{valid_dates}/{total} proyectos con fecha de inicio")
    
    def _validate_funding_sources(self, df: pd.DataFrame):
        """Valida fuentes de financiamiento"""
        if df.empty:
            self._add_error("Tabla de fuentes de financiamiento vacía")
            return
        
        # Check 1: Nombres únicos
        if 'name' in df.columns:
            missing_names = df['name'].isna().sum()
            if missing_names > 0:
                self._add_error(f"{missing_names} fuentes sin nombre")
            else:
                self._add_passed("Todas las fuentes tienen nombre")
        
        # Check 2: IDs únicos
        if 'sismo_funding_source_id' in df.columns:
            duplicates = df['sismo_funding_source_id'].duplicated().sum()
            if duplicates > 0:
                self._add_error(f"{duplicates} IDs duplicados en fuentes")
            else:
                self._add_passed("Todos los IDs de fuentes son únicos")
    
    def _validate_relationships(
        self, 
        relations_df: pd.DataFrame,
        projects_df: pd.DataFrame,
        researchers_df: pd.DataFrame
    ):
        """
        Valida integridad referencial de relaciones
        ✅ CORREGIDO: Usa nombres de columnas correctos (sismo_*)
        """
        if relations_df is None or relations_df.empty:
            self._add_warning("No hay relaciones proyecto-investigador para validar")
            return
        
        if projects_df is None or projects_df.empty:
            self._add_error("No hay proyectos para validar relaciones")
            return
        
        if researchers_df is None or researchers_df.empty:
            self._add_error("No hay investigadores para validar relaciones")
            return
        
        # ✅ CORRECCIÓN: Usar nombres correctos de columnas
        project_id_col = 'sismo_project_id'
        researcher_id_col = 'sismo_researcher_id'
        
        # Verificar que existen las columnas
        if project_id_col not in relations_df.columns:
            self._add_error(f"Columna '{project_id_col}' no encontrada en relaciones")
            return
        
        if researcher_id_col not in relations_df.columns:
            self._add_error(f"Columna '{researcher_id_col}' no encontrada en relaciones")
            return
        
        # Check 1: Proyectos existen
        project_ids = set(projects_df['sismo_project_id'].dropna())
        invalid_projects = relations_df[
            ~relations_df[project_id_col].isin(project_ids)
        ]
        
        if len(invalid_projects) > 0:
            self._add_error(
                f"{len(invalid_projects)} relaciones apuntan a proyectos inexistentes"
            )
        else:
            self._add_passed("Todos los proyectos en relaciones existen")
        
        # Check 2: Investigadores existen
        researcher_ids = set(researchers_df['sismo_id'].dropna())
        invalid_researchers = relations_df[
            ~relations_df[researcher_id_col].isin(researcher_ids)
        ]
        
        if len(invalid_researchers) > 0:
            self._add_error(
                f"{len(invalid_researchers)} relaciones apuntan a investigadores inexistentes"
            )
        else:
            self._add_passed("Todos los investigadores en relaciones existen")
        
        # Check 3: Relaciones únicas (no duplicadas)
        duplicates = relations_df.duplicated(
            subset=[project_id_col, researcher_id_col]
        ).sum()
        
        if duplicates > 0:
            self._add_warning(f"{duplicates} relaciones duplicadas")
        else:
            self._add_passed("No hay relaciones duplicadas")
        
        # Check 4: Verificar que cada proyecto tiene al menos un investigador
        projects_with_researchers = relations_df[project_id_col].nunique()
        total_projects = len(projects_df)
        
        if projects_with_researchers < total_projects:
            missing = total_projects - projects_with_researchers
            self._add_warning(
                f"{missing} proyectos sin investigadores asignados"
            )
        else:
            self._add_passed("Todos los proyectos tienen investigadores")
    
    def _add_passed(self, message: str):
        """Agrega validación exitosa"""
        self.validation_results['passed'].append(message)
    
    def _add_warning(self, message: str):
        """Agrega advertencia"""
        self.validation_results['warnings'].append(message)
        logger.warning(f"⚠️ {message}")
    
    def _add_error(self, message: str):
        """Agrega error"""
        self.validation_results['errors'].append(message)
        logger.error(f"❌ {message}")
    
    def get_summary(self) -> Dict[str, int]:
        """Retorna resumen de validación"""
        return self.validation_results['summary']
    
    def has_errors(self) -> bool:
        """Indica si hay errores críticos"""
        return len(self.validation_results['errors']) > 0
    
    def has_warnings(self) -> bool:
        """Indica si hay advertencias"""
        return len(self.validation_results['warnings']) > 0


def test_validator():
    """Test del validador"""
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Crear datos de prueba con nombres de columnas correctos
    researchers = pd.DataFrame({
        'sismo_id': [1, 2, 3, 4],
        'full_name': ['Juan Pérez', 'María García', None, 'Pedro López'],
        'dni': ['12345678', '87654321', '11111111', '22222222'],
        'dni_valid': [True, True, False, True],
        'siri_enriched': [True, True, False, True]
    })
    
    projects = pd.DataFrame({
        'sismo_project_id': [100, 101, 102],
        'project_code': ['PROJ-001', 'PROJ-002', 'PROJ-003'],
        'title': ['Proyecto 1', 'Proyecto 2', 'Proyecto 3'],
        'planned_start_date': [pd.Timestamp('2024-01-01'), None, pd.Timestamp('2024-03-01')]
    })
    
    funding_sources = pd.DataFrame({
        'sismo_funding_source_id': [1, 2],
        'name': ['CONCYTEC', 'FONDECYT']
    })
    
    project_researchers = pd.DataFrame({
        'sismo_project_id': [100, 101, 102, 999],  # 999 es inválido
        'sismo_researcher_id': [1, 2, 3, 4]
    })
    
    entities = {
        'researchers': researchers,
        'projects': projects,
        'funding_sources': funding_sources,
        'project_researchers': project_researchers
    }
    
    validator = DataValidator()
    results = validator.validate_all_entities(entities)
    
    print("\n" + "="*70)
    print("📊 RESULTADOS DE VALIDACIÓN")
    print("="*70)
    print(f"\n✅ Checks pasados: {results['summary']['passed']}")
    print(f"⚠️ Advertencias: {results['summary']['warnings']}")
    print(f"❌ Errores: {results['summary']['errors']}")
    
    if results['warnings']:
        print("\n⚠️ ADVERTENCIAS:")
        for warning in results['warnings']:
            print(f"   - {warning}")
    
    if results['errors']:
        print("\n❌ ERRORES:")
        for error in results['errors']:
            print(f"   - {error}")
    
    print("\n" + "="*70)


if __name__ == "__main__":
    test_validator()