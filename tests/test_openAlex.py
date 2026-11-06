"""
Explorador Avanzado de OpenAlex API (Fase de Pruebas ETL)
Extracción completa: ROR, Abstracts invertidos, Conceptos, y Métricas cruzadas.
"""
import requests
import json
import logging
from typing import Dict, List

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class OpenAlexAdvancedTester:
    def __init__(self, email: str):
        # Header obligatorio para acceder al Polite Pool (mayor velocidad)
        self.headers = {'User-Agent': f'mailto:{email}'}
        self.base_url = "https://api.openalex.org"

    def reconstruct_abstract(self, inverted_index: dict) -> str:
        """
        OpenAlex devuelve el abstract en formato 'inverted_index' por temas de copyright.
        Ej: {"The": [0, 5], "study": [1], ...}
        Esta función lo reconstruye a texto legible.
        """
        if not inverted_index:
            return "No abstract available"
            
        try:
            # Encontrar la posición máxima para dimensionar el arreglo
            max_pos = max([pos for positions in inverted_index.values() for pos in positions])
            palabras = [""] * (max_pos + 1)
            
            for palabra, posiciones in inverted_index.items():
                for pos in posiciones:
                    palabras[pos] = palabra
                    
            return " ".join(palabras).strip()
        except Exception as e:
            logger.warning(f"Error reconstruyendo abstract: {e}")
            return "Error reconstructing abstract"

    def get_works_by_orcid(self, orcid: str) -> List[Dict]:
        orcid_clean = orcid.replace('https://orcid.org/', '').strip()
        url = f"{self.base_url}/works?filter=author.orcid:https://orcid.org/{orcid_clean}"
        
        logger.info(f"Buscando publicaciones para ORCID: {orcid_clean}")
        
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            resultados = data.get('results', [])
            logger.info(f"✅ Se encontraron {len(resultados)} publicaciones.")
            return resultados
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error consultando OpenAlex: {e}")
            return []

    def analyze_publication(self, work_data: Dict):
        """Desglosa la información completa útil para cris_data"""
        print("\n" + "="*80)
        
        # 1. METADATOS CORE
        print("📄 METADATOS PRINCIPALES:")
        print(f"   Título: {work_data.get('title')}")
        print(f"   DOI: {work_data.get('doi')}")
        print(f"   Año: {work_data.get('publication_year')}")
        print(f"   Tipo: {work_data.get('type')} (Acceso Abierto: {work_data.get('open_access', {}).get('is_oa', False)})")
        
        revista = work_data.get('primary_location', {}).get('source', {})
        if revista:
            print(f"   Revista: {revista.get('display_name')} (ISSN: {revista.get('issn_l')})")

        # 2. IDENTIFICADORES CRUZADOS (Para cruzar con Scopus/WoS en el futuro)
        print("\n🔗 IDENTIFICADORES EXTERNOS:")
        ids = work_data.get('ids', {})
        for id_name, id_value in ids.items():
            if id_name != 'openalex':
                print(f"   - {id_name.upper()}: {id_value}")

        # 3. IMPACTO (Altmetrics base)
        print("\n📈 MÉTRICAS DE IMPACTO:")
        print(f"   Citas recibidas: {work_data.get('cited_by_count', 0)}")

        # 4. CONCEPTOS TEMÁTICOS (Clasificación automática que reemplaza NLP propio)
        print("\n🧠 CONCEPTOS (Top 5):")
        conceptos = work_data.get('concepts', [])
        # Ordenamos por score de relevancia
        conceptos_ordenados = sorted(conceptos, key=lambda x: x.get('score', 0), reverse=True)[:5]
        for c in conceptos_ordenados:
            print(f"   - {c.get('display_name')} (Relevancia: {round(c.get('score', 0) * 100, 1)}%)")

        # 5. ABSTRACT RECONSTRUIDO
        print("\n📝 RESUMEN (Abstract):")
        abstract = self.reconstruct_abstract(work_data.get('abstract_inverted_index'))
        # Mostramos solo los primeros 250 caracteres para no inundar la consola
        print(f"   {abstract[:250]}..." if len(abstract) > 250 else f"   {abstract}")

        # 6. EQUIPO DE AUTORES Y ROR INSTITUCIONAL
        print("\n👥 EQUIPO DE AUTORES (Identity & ROR):")
        for authorship in work_data.get('authorships', []):
            author = authorship.get('author', {})
            institutions = authorship.get('institutions', [])
            
            print(f"   🔹 {author.get('display_name')}")
            print(f"      Rol: {authorship.get('author_position')} | Corresponding: {authorship.get('is_corresponding')}")
            print(f"      ORCID: {author.get('orcid')}")
            
            if institutions:
                for inst in institutions:
                    # EL ROR ES LA LLAVE MAESTRA PARA SABER SI ES DE LA UNSA
                    ror = inst.get('ror', 'SIN ROR')
                    print(f"      🏢 Afiliación: {inst.get('display_name')} [ROR: {ror}]")
            else:
                print("      🏢 Afiliación: Ninguna registrada en este paper")
            print("      ---")
            
        print("="*80)

if __name__ == "__main__":
    # ⚠️ IMPORTANTE: Usa tu correo real, OpenAlex bloquea peticiones anónimas masivas
    tester = OpenAlexAdvancedTester(email="tu_correo@unsa.edu.pe")
    
    # ORCIDs de prueba que me proporcionaste
    orcids_prueba = ["0000-0002-9767-4946", "0000-0002-7902-1650"]
    
    for orcid in orcids_prueba:
        publicaciones = tester.get_works_by_orcid(orcid)
        if publicaciones:
            # Analizamos solo la publicación más reciente (la primera) de cada autor
            tester.analyze_publication(publicaciones[0])