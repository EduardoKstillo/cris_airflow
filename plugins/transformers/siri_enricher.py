"""
Enriquecedor de Datos con SIRI
"""
import pandas as pd
from typing import Dict, List, Optional
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class SIRIEnricher:
    def __init__(self):
        self.stats = {
            'total_researchers': 0, 'enriched_count': 0, 'not_found_count': 0,
            'invalid_dni_count': 0, 'enrichment_rate': 0.0, 'errors': []
        }
    
    def build_affiliations(self, researchers_df: pd.DataFrame, siri_master_df: pd.DataFrame) -> pd.DataFrame:
        logger.info("🔄 Construyendo afiliaciones organizacionales (En Memoria)...")
        
        if researchers_df.empty or siri_master_df.empty:
            logger.warning("⚠️ DataFrames de entrada vacíos.")
            return pd.DataFrame()

        df_clean = researchers_df.copy()
        df_clean['dni'] = df_clean['dni'].astype(str).str.strip().str.lstrip('0').str.zfill(8)
        
        valid_dnis = df_clean[df_clean.get('dni_valid', True) == True]['dni'].unique().tolist()
        if not valid_dnis:
            logger.warning("⚠️ No hay DNIs válidos para cruzar con SIRI")
            return pd.DataFrame()
            
        siri_data = siri_master_df.copy()
        siri_data['dni'] = siri_data['dni'].astype(str).str.strip().str.lstrip('0').str.zfill(8)
        
        merged = pd.merge(df_clean[['sismo_id', 'dni']], siri_data, on='dni', how='inner')
        
        affiliations = []
        for _, row in merged.iterrows():
            sismo_id = row['sismo_id']
            
            fac_val = row.get('facultad_codigo')
            if pd.notna(fac_val) and str(fac_val).strip() != "":
                fac_code = str(fac_val).strip().upper()
                affiliations.append({
                    'sismo_researcher_id': sismo_id,
                    'org_code': fac_code,
                    'position_title': None, 'role': 'Investigador',
                    'start_date': None, 'end_date': None, 'is_active': True
                })
                
            dep_val = row.get('departamento_codigo')
            if pd.notna(dep_val) and str(dep_val).strip() != "":
                dep_code = str(dep_val).strip().upper()
                affiliations.append({
                    'sismo_researcher_id': sismo_id,
                    'org_code': dep_code,
                    'position_title': None, 'role': 'Docente/Investigador',
                    'start_date': None, 'end_date': None, 'is_active': True
                })
                
        affiliations_df = pd.DataFrame(affiliations)
        
        if not affiliations_df.empty:
            affiliations_df = affiliations_df.drop_duplicates()
            affiliations_df['created_at'] = datetime.now()
            
        logger.info(f"✅ Construidas {len(affiliations_df)} afiliaciones para {merged['sismo_id'].nunique()} investigadores")
        return affiliations_df