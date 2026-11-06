"""
Enriquecedor Asíncrono OCDE - Google Gemini
Arquitectura Desacoplada: Lee de PostgreSQL, enriquece, y actualiza PostgreSQL.
VERSIÓN DE PRODUCCIÓN: SDK google-genai, manejo de cuotas, retries, truncamiento y Chain of Thought.
"""

import os
import json
import time
import random
import logging
from typing import Dict, Any, List

# NUEVO SDK OFICIAL DE GOOGLE
from google import genai
from google.genai import types

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

class GeminiOCDEClassifier:
    def __init__(self):
        load_dotenv('/app/airflow/.env')
        api_key = os.getenv('GEMINI_API_KEY')
        
        if not api_key:
            raise ValueError("No se encontró GEMINI_API_KEY en las variables de entorno.")
            
        # Inicialización con el nuevo SDK
        self.client = genai.Client(api_key=api_key)
        self.model_name = 'gemini-3.6-flash'
        
        # Conexión a la BD
        host = os.getenv('POSTGRES_HOST', 'localhost')
        port = os.getenv('POSTGRES_PORT', '5432')
        db = os.getenv('POSTGRES_DB', 'cris_data')
        user = os.getenv('POSTGRES_USER', 'postgres')
        password = os.getenv('POSTGRES_PASSWORD')
        self.engine = create_engine(f"postgresql://{user}:{password}@{host}:{port}/{db}")
        
        vocab_path = os.path.join('/app/airflow/config', 'ocde_vocabularies.json')
        with open(vocab_path, 'r', encoding='utf-8') as f:
            self.vocabularies = json.load(f)
            
        self.purl_base_ford = "https://purl.org/pe-repo/ocde/ford#"
        self.purl_base_activity = "https://purl.org/pe-repo/ocde/tipoProyecto#"

    def _clean_text(self, text: str, max_chars: int = 3000) -> str:
        if not text: return ""
        clean = " ".join(str(text).split())
        return clean[:max_chars]
    
    def _build_prompt(self, title: str, abstract: str, keywords: str, project_type: str) -> str:
        tipos_validos = json.dumps(self.vocabularies['tipo_proyecto'], ensure_ascii=False)
        ford_validos = json.dumps(self.vocabularies['ford'], ensure_ascii=False)

        return f"""
        Actúa como un experto del CONCYTEC (Perú). Tu tarea es clasificar un proyecto científico.
        
        DATOS DEL PROYECTO:
        - TÍTULO: {title}
        - RESUMEN: {abstract}
        - PALABRAS CLAVE: {keywords}
        - TIPO: {project_type}

        DICCIONARIO DE TIPOS DE ACTIVIDAD PERMITIDOS:
        {tipos_validos}
        
        DICCIONARIO DE CLASIFICACIÓN FORD PERMITIDOS (6 dígitos):
        {ford_validos}

        INSTRUCCIONES:
        1. Analiza el proyecto y justifica brevemente tu elección.
        2. Selecciona entre 1 y 3 claves exactas de "Tipos de Actividad".
        3. Selecciona entre 1 y 3 claves exactas de "FORD" que mejor describan la rama específica.
        4. Asigna un score de confianza de 1 a 100.
        
        FORMATO DE SALIDA ESTRICTO (JSON):
        {{
            "justificacion": "Tu razonamiento corto aquí...",
            "confidence_score": 95,
            "actividades_keys": ["clave1", "clave2"],
            "ford_keys": ["codigo1", "codigo2"]
        }}
        """

    def classify_single_project(self, title: str, abstract: str, keywords: str, project_type: str, max_retries=5) -> Dict[str, Any]:
        prompt = self._build_prompt(title, abstract, keywords, project_type)
        
        for attempt in range(max_retries):
            try:
                # Sintaxis del NUEVO SDK
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )
                )
                result = json.loads(response.text)
                
                actividades_urls = [f"{self.purl_base_activity}{k}" for k in result.get("actividades_keys", []) if k in self.vocabularies['tipo_proyecto']]
                ford_urls = [f"{self.purl_base_ford}{k}" for k in result.get("ford_keys", []) if k in self.vocabularies['ford']]
                
                return {
                    "ocde_activity_type": ", ".join(actividades_urls) if actividades_urls else None,
                    "ocde_classification": ", ".join(ford_urls) if ford_urls else None,
                    "ocde_confidence_score": result.get("confidence_score", 0),
                    "justification": result.get("justificacion", "")
                }
            except Exception as e:
                error_msg = str(e).lower()
                # Tratamos los errores 503 (Unavailable) y 429 (Rate Limit) con el mismo backoff
                if "429" in error_msg or "quota" in error_msg or "exhausted" in error_msg or "503" in error_msg or "unavailable" in error_msg:
                    sleep_time = (2 ** attempt) * 6 + random.uniform(2, 5)
                    logger.warning(f"⚠️ API Ocupada o Límite Alcanzado. Reintento en {sleep_time:.1f}s (Intento {attempt+1}/{max_retries})")
                    time.sleep(sleep_time)
                else:
                    logger.error(f"❌ Error API Inesperado: {e}")
                    break
        return {"ocde_activity_type": None, "ocde_classification": None, "ocde_confidence_score": 0, "justification": ""}

    def process_pending_projects(self):
        logger.info("🔍 Buscando proyectos sin clasificación OCDE en la base de datos...")
        
        try:
            with self.engine.begin() as conn:
                query = text("""
                    SELECT id, title, abstract, keywords, project_type 
                    FROM public.projects 
                    WHERE (ocde_classification IS NULL OR ocde_classification = '')
                      AND title IS NOT NULL
                    LIMIT 3
                """)
                projects = conn.execute(query).fetchall()
                
                if not projects:
                    logger.info("✅ Todos los proyectos están clasificados.")
                    return
                
                logger.info(f"⏳ Procesando {len(projects)} proyectos con Inteligencia Artificial...")
                
                for count, row in enumerate(projects, 1):
                    res = self.classify_single_project(
                        title=row.title, 
                        abstract=self._clean_text(row.abstract), 
                        keywords=self._clean_text(row.keywords),
                        project_type=row.project_type or ""
                    )

                    logger.info("=" * 80)
                    logger.info(f"📋 PROYECTO PROCESADO")
                    logger.info(f"   ID: {row.id}")
                    logger.info(f"   TÍTULO: {row.title}")
                    logger.info(f"   ACTIVIDAD: {res['ocde_activity_type']}")
                    logger.info(f"   FORD: {res['ocde_classification']}")
                    logger.info(f"   CONFIANZA: {res['ocde_confidence_score']}")
                    logger.info("=" * 80)
                    
                    if res["ocde_classification"]:
                        first_ford_code = res["ocde_classification"].split(', ')[0].split('#')[-1]
                        knowledge_base = f"{first_ford_code[0]}.00.00" if len(first_ford_code) >= 1 else ""
                        knowledge_field = f"{self.purl_base_ford}{knowledge_base}" if knowledge_base else None
                        
                        update_query = text("""
                            UPDATE public.projects 
                            SET ocde_activity_type = :act, 
                                ocde_classification = :cls, 
                                ocde_knowledge_field = :kf,
                                ocde_confidence_score = :score,
                                sync_status = 'pending_update'::sync_state_enum,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = :id
                        """)
                        conn.execute(update_query, {
                            "act": res["ocde_activity_type"],
                            "cls": res["ocde_classification"],
                            "kf": knowledge_field,
                            "score": res["ocde_confidence_score"],
                            "id": row.id
                        })
                        logger.info(f"✅ Proyecto {row.id} clasificado | FORD: {first_ford_code} | Confianza: {res['ocde_confidence_score']}")
                    else:
                        logger.warning(f"⚠️ Proyecto {row.id} quedó sin clasificar tras agotar reintentos.")
                        
                    if count % 5 == 0:
                        logger.info(f"   📊 Progreso: {count}/{len(projects)} proyectos procesados...")
                    
                    # Rate limiting estricto de 6 segundos (máximo 10 requests por minuto)
                    time.sleep(6.0)
                    
            logger.info("✅ Proceso de enriquecimiento con IA completado.")
                    
        except Exception as e:
            logger.error(f"❌ Error en el proceso de enriquecimiento: {e}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    classifier = GeminiOCDEClassifier()
    classifier.process_pending_projects()