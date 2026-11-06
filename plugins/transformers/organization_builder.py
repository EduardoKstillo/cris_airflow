"""
Constructor de Jerarquía Organizacional
"""
import pandas as pd
from typing import Dict, List, Optional
import logging
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)

class OrganizationBuilder:
    
    def __init__(self, siri_extractor):
        self.siri_extractor = siri_extractor
        self.stats = {
            'total_organizations': 0,
            'main_institution': 0,
            'faculties': 0,
            'departments': 0,
            'groups': 0,
            'research_lines': 0,
            'hierarchy_levels': 0
        }
    
    def build_complete_hierarchy(self) -> pd.DataFrame:
        logger.info("🏛️ Construyendo jerarquía organizacional...")
        
        organizations = []
        
        main_org = self._create_main_institution()
        organizations.append(main_org)
        main_org_id = main_org['id']
        
        faculties_df = self.siri_extractor.get_faculties()
        logger.info(f"   📚 Extraídas {len(faculties_df)} facultades")
        
        faculty_map = {}
        
        for _, faculty_row in faculties_df.iterrows():
            faculty_org = self._create_faculty_organization(faculty_row, main_org_id)
            organizations.append(faculty_org)
            faculty_map[str(faculty_row['id_facultad'])] = faculty_org['id']
        
        self.stats['faculties'] = len(faculties_df)
        
        departments_df = self.siri_extractor.get_departments()
        logger.info(f"   🏢 Extraídos {len(departments_df)} departamentos")
        
        for _, dept_row in departments_df.iterrows():
            parent_faculty_id = faculty_map.get(str(dept_row['id_facultad']))
            if parent_faculty_id:
                dept_org = self._create_department_organization(dept_row, parent_faculty_id)
                organizations.append(dept_org)
            else:
                logger.warning(f"   ⚠️ Departamento {dept_row['denominacion']} sin facultad padre")
        
        self.stats['departments'] = len(departments_df)
        
        orgs_df = pd.DataFrame(organizations)
        
        self.stats['total_organizations'] = len(orgs_df)
        self.stats['hierarchy_levels'] = self._calculate_hierarchy_depth(orgs_df)
        
        logger.info(f"✅ Jerarquía construida: {len(orgs_df)} organizaciones")
        self._log_hierarchy_summary()
        
        return orgs_df
    
    def _create_main_institution(self) -> Dict:
        return {
            'id': str(uuid.uuid4()),
            'code': 'UNSA-001',
            'name': 'Universidad Nacional de San Agustín de Arequipa',
            'acronym': 'UNSA',
            'organization_type': 'PRINCIPAL',
            'parent_organization_id': None,
            'dependency_type': None,
            'ruc': '20175589230',
            'scopus_affid': None,
            'isni': None,
            'website_url': 'https://www.unsa.edu.pe',
            'email': 'informes@unsa.edu.pe',
            'country': 'Peru',
            'address': 'Av. Independencia s/n, Arequipa, Perú',
            'source_system': 'MANUAL',
            'external_id': None,
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        }
    
    def _create_faculty_organization(self, faculty_row: pd.Series, parent_id: str) -> Dict:
        return {
            'id': str(uuid.uuid4()),
            'code': f"FAC-{faculty_row['codigo']}",
            'name': faculty_row['denominacion'].strip(),
            'acronym': self._generate_acronym(faculty_row['denominacion']),
            'organization_type': 'FACULTAD',
            'parent_organization_id': parent_id,
            'dependency_type': 'ACADEMICA',
            'ruc': None,
            'scopus_affid': None,
            'isni': None,
            'website_url': None,
            'email': None,
            'country': 'Peru',
            'address': None,
            'source_system': 'SIRI',
            'external_id': str(faculty_row['id_facultad']),
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        }
    
    def _create_department_organization(self, dept_row: pd.Series, parent_id: str) -> Dict:
        return {
            'id': str(uuid.uuid4()),
            'code': f"DEPT-{dept_row['codigo']}",
            'name': dept_row['denominacion'].strip(),
            'acronym': self._generate_acronym(dept_row['denominacion']),
            'organization_type': 'DEPARTAMENTO',
            'parent_organization_id': parent_id,
            'dependency_type': 'ACADEMICA',
            'ruc': None,
            'scopus_affid': None,
            'isni': None,
            'website_url': None,
            'email': None,
            'country': 'Peru',
            'address': None,
            'source_system': 'SIRI',
            'external_id': str(dept_row['id_departamento']),
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        }
    
    def _generate_acronym(self, name: str) -> str:
        if not name:
            return None
        
        words = name.upper().split()
        significant_words = [w for w in words if len(w) > 3 and w not in ['FACULTAD', 'DE', 'LA', 'DEL', 'LOS', 'LAS']]
        
        if significant_words:
            acronym = ''.join([w[0] for w in significant_words[:4]])
            return acronym
        
        return words[0][:4] if words else None
    
    def _calculate_hierarchy_depth(self, orgs_df: pd.DataFrame) -> int:
        max_depth = 0
        
        def get_depth(org_id, current_depth=0):
            children = orgs_df[orgs_df['parent_organization_id'] == org_id]
            if children.empty:
                return current_depth
            return max([get_depth(child_id, current_depth + 1) 
                       for child_id in children['id']])
        
        root_orgs = orgs_df[orgs_df['parent_organization_id'].isna()]
        for root_id in root_orgs['id']:
            depth = get_depth(root_id)
            max_depth = max(max_depth, depth)
        
        return max_depth + 1
    
    def _log_hierarchy_summary(self):
        logger.info("\n🏛️ Resumen de Jerarquía Organizacional:")
        logger.info(f"   - Institución Principal: 1")
        logger.info(f"   - Facultades: {self.stats['faculties']}")
        logger.info(f"   - Departamentos: {self.stats['departments']}")
        logger.info(f"   - Niveles jerárquicos: {self.stats['hierarchy_levels']}")
        logger.info(f"   - Total organizaciones: {self.stats['total_organizations']}")
    
    def get_stats(self) -> Dict:
        return self.stats