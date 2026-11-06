"""
name_matcher.py
Algoritmos de matching y normalización de nombres para identificar personas
"""

import re
import unicodedata
from typing import Tuple, List, Dict, Optional
from difflib import SequenceMatcher
import logging

logger = logging.getLogger(__name__)


class NameMatcher:
    """
    Clase para matching inteligente de nombres de personas
    Soporta normalización, comparación fuzzy y scoring
    """
    
    def __init__(self, threshold: float = 0.85):
        """
        Args:
            threshold: Umbral mínimo de similitud (0.0-1.0) para considerar un match válido
        """
        self.threshold = threshold
        
        # Palabras comunes que no aportan al matching
        self.stopwords = {
            'de', 'del', 'la', 'las', 'los', 'el',
            'y', 'e', 'o', 'u', 'dr', 'dra', 'mg', 'phd'
        }
    
    def normalize_name(self, name: str) -> str:
        """
        Normaliza un nombre para comparación
        
        Proceso:
        1. Convertir a minúsculas
        2. Remover acentos y diacríticos
        3. Remover caracteres especiales
        4. Remover stopwords
        5. Normalizar espacios
        
        Args:
            name: Nombre original
            
        Returns:
            Nombre normalizado
        """
        if not name or not isinstance(name, str):
            return ""
        
        # Minúsculas
        normalized = name.lower().strip()
        
        # Remover acentos
        normalized = ''.join(
            c for c in unicodedata.normalize('NFD', normalized)
            if unicodedata.category(c) != 'Mn'
        )
        
        # Remover caracteres especiales, mantener solo letras, números y espacios
        normalized = re.sub(r'[^a-z0-9\s]', ' ', normalized)
        
        # Remover stopwords
        words = normalized.split()
        words = [w for w in words if w not in self.stopwords and len(w) > 1]
        
        # Normalizar espacios múltiples
        normalized = ' '.join(words)
        
        return normalized
    
    def extract_name_parts(self, name: str) -> Dict[str, str]:
        """
        Intenta extraer partes del nombre (nombres, apellidos)
        
        Asume formato típico peruano:
        - Apellido1 Apellido2 Nombre1 Nombre2
        - o variaciones
        
        Args:
            name: Nombre completo
            
        Returns:
            Dict con 'first_names' y 'last_names'
        """
        normalized = self.normalize_name(name)
        words = normalized.split()
        
        if len(words) == 0:
            return {'first_names': '', 'last_names': ''}
        
        # Heurística simple: primeros 2 son apellidos, resto son nombres
        # (esto puede fallar, pero es un punto de partida)
        if len(words) <= 2:
            return {
                'first_names': words[-1] if words else '',
                'last_names': words[0] if len(words) > 1 else ''
            }
        
        return {
            'last_names': ' '.join(words[:2]),
            'first_names': ' '.join(words[2:])
        }
    
    def similarity_score(self, name1: str, name2: str) -> float:
        """
        Calcula score de similitud entre dos nombres (0.0-1.0)
        Usa SequenceMatcher de Python (algoritmo Gestalt Pattern Matching)
        
        Args:
            name1: Primer nombre
            name2: Segundo nombre
            
        Returns:
            Score de similitud (0.0 = totalmente diferentes, 1.0 = idénticos)
        """
        norm1 = self.normalize_name(name1)
        norm2 = self.normalize_name(name2)
        
        if not norm1 or not norm2:
            return 0.0
        
        return SequenceMatcher(None, norm1, norm2).ratio()
    
    def advanced_similarity(self, name1: str, name2: str) -> Tuple[float, str]:
        """
        Similitud avanzada con múltiples estrategias
        
        Estrategias:
        1. Match exacto normalizado -> 1.0
        2. Match de apellidos + iniciales de nombres -> 0.95
        3. Similitud secuencial alta -> ratio directo
        4. Match por partes (apellidos vs apellidos, nombres vs nombres) -> promedio ponderado
        
        Args:
            name1: Primer nombre
            name2: Segundo nombre
            
        Returns:
            (score, match_type) donde match_type indica la estrategia que funcionó
        """
        norm1 = self.normalize_name(name1)
        norm2 = self.normalize_name(name2)
        
        # Estrategia 1: Match exacto
        if norm1 == norm2:
            return (1.0, 'exact')
        
        # Estrategia 2: Match de apellidos + iniciales
        parts1 = self.extract_name_parts(name1)
        parts2 = self.extract_name_parts(name2)
        
        last_names_match = self.similarity_score(
            parts1['last_names'], 
            parts2['last_names']
        )
        
        # Si apellidos son muy similares (>0.9), verificar iniciales de nombres
        if last_names_match > 0.9:
            first1 = parts1['first_names'].split()
            first2 = parts2['first_names'].split()
            
            if first1 and first2:
                # Comparar primeras letras
                initials_match = first1[0][0] == first2[0][0] if first1[0] and first2[0] else False
                if initials_match:
                    return (0.95, 'last_names_initials')
        
        # Estrategia 3: Similitud secuencial directa
        seq_score = SequenceMatcher(None, norm1, norm2).ratio()
        
        # Estrategia 4: Match por partes con peso
        first_names_match = self.similarity_score(
            parts1['first_names'],
            parts2['first_names']
        )
        
        # Peso: apellidos 60%, nombres 40%
        weighted_score = (last_names_match * 0.6) + (first_names_match * 0.4)
        
        # Tomar el mejor score
        best_score = max(seq_score, weighted_score)
        match_type = 'sequential' if seq_score > weighted_score else 'parts_weighted'
        
        return (best_score, match_type)
    
    def find_best_match(
        self, 
        target_name: str, 
        candidate_names: List[Tuple[str, any]]
    ) -> Optional[Tuple[any, float, str]]:
        """
        Encuentra el mejor match de un nombre en una lista de candidatos
        
        Args:
            target_name: Nombre a buscar
            candidate_names: Lista de tuplas (nombre, identificador)
            
        Returns:
            (identificador, score, match_type) del mejor match, o None si ninguno supera threshold
        """
        if not candidate_names:
            return None
        
        best_match = None
        best_score = 0.0
        best_type = ''
        best_id = None
        
        for candidate_name, candidate_id in candidate_names:
            score, match_type = self.advanced_similarity(target_name, candidate_name)
            
            if score > best_score:
                best_score = score
                best_type = match_type
                best_id = candidate_id
                best_match = candidate_name
        
        # Verificar si supera threshold
        if best_score >= self.threshold:
            logger.debug(
                f"Match encontrado: '{target_name}' -> '{best_match}' "
                f"(score={best_score:.3f}, type={best_type})"
            )
            return (best_id, best_score, best_type)
        
        return None
    
    def categorize_match_quality(self, score: float) -> str:
        """
        Categoriza la calidad del match basado en el score
        
        Args:
            score: Score de similitud (0.0-1.0)
            
        Returns:
            Categoría: 'exact', 'high', 'medium', 'low', 'no_match'
        """
        if score >= 0.98:
            return 'exact'
        elif score >= 0.90:
            return 'high'
        elif score >= 0.80:
            return 'medium'
        elif score >= 0.70:
            return 'low'
        else:
            return 'no_match'


def test_name_matcher():
    """Test básico del matcher"""
    logging.basicConfig(level=logging.DEBUG)
    
    matcher = NameMatcher(threshold=0.85)
    
    # Test 1: Normalización
    print("=== Test 1: Normalización ===")
    test_names = [
        "PÉREZ GARCÍA, Juan Carlos",
        "Pérez García Juan Carlos",
        "Dr. Juan C. Pérez-García",
    ]
    for name in test_names:
        print(f"{name} -> {matcher.normalize_name(name)}")
    
    # Test 2: Similitud
    print("\n=== Test 2: Similitud ===")
    pairs = [
        ("Juan Pérez García", "PEREZ GARCIA JUAN"),
        ("María Rodriguez López", "Rodriguez Lopez Maria Isabel"),
        ("Carlos Mendoza", "Juan Pérez"),
    ]
    for name1, name2 in pairs:
        score, match_type = matcher.advanced_similarity(name1, name2)
        quality = matcher.categorize_match_quality(score)
        print(f"{name1} vs {name2}: {score:.3f} ({match_type}, {quality})")
    
    # Test 3: Best match
    print("\n=== Test 3: Best Match ===")
    target = "GARCIA LOPEZ MARIA"
    candidates = [
        ("María García López", 1),
        ("María García Pérez", 2),
        ("Juan García López", 3),
        ("María Isabel García López", 4),
    ]
    result = matcher.find_best_match(target, candidates)
    if result:
        print(f"Mejor match: ID={result[0]}, score={result[1]:.3f}, type={result[2]}")
    else:
        print("No se encontró match")


if __name__ == "__main__":
    test_name_matcher()