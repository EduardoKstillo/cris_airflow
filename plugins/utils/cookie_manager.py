"""
cookie_manager.py
Gestión de cookies y sesiones HTTP para web scraping
"""

import json
import uuid
from typing import Dict, Optional, List
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
import logging

logger = logging.getLogger(__name__)


class CookieManager:
    """
    Gestiona cookies y headers de sesiones HTTP
    Las persiste en PostgreSQL para reutilización
    """
    
    def __init__(self, connection_string: str):
        """
        Args:
            connection_string: String de conexión PostgreSQL
        """
        self.connection_string = connection_string
        self.engine = None
        
        # Headers por defecto para cada servicio
        self.default_headers = {
            'cti_vitae': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            },
            'renacyt': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'es-PE,es;q=0.9,en;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive'
            }
        }
    
    def connect(self) -> bool:
        """Establece conexión con PostgreSQL"""
        try:
            self.engine = create_engine(self.connection_string, pool_pre_ping=True)
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("✅ CookieManager conectado a PostgreSQL")
            return True
        except Exception as e:
            logger.error(f"❌ Error conectando a PostgreSQL: {e}")
            return False
    
    def save_session(
        self,
        service: str,
        cookies: Dict,
        headers: Optional[Dict] = None,
        session_name: str = 'default',
        expires_in_hours: int = 24
    ) -> bool:
        """
        Guarda una sesión en la BD
        
        Args:
            service: Nombre del servicio ('cti_vitae', 'renacyt', etc.)
            cookies: Diccionario de cookies
            headers: Headers HTTP opcionales
            session_name: Nombre de la sesión
            expires_in_hours: Horas hasta expiración
            
        Returns:
            True si se guardó correctamente
        """
        if not self.engine and not self.connect():
            return False
        
        try:
            # Invalidar sesiones anteriores del mismo servicio+nombre
            self._invalidate_previous_sessions(service, session_name)
            
            # Calcular expiración
            expires_at = datetime.now() + timedelta(hours=expires_in_hours)
            
            # Usar headers por defecto si no se proporcionan
            if headers is None:
                headers = self.default_headers.get(service, {})
            
            insert_query = text("""
                INSERT INTO public.scraping_sessions 
                (service, session_name, cookies, headers, expires_at, is_valid)
                VALUES 
                (:service, :session_name, :cookies, :headers, :expires_at, TRUE)
            """)
            
            with self.engine.begin() as conn:
                conn.execute(insert_query, {
                    'service': service,
                    'session_name': session_name,
                    'cookies': json.dumps(cookies),
                    'headers': json.dumps(headers),
                    'expires_at': expires_at
                })
            
            logger.info(f"✅ Sesión guardada: {service}/{session_name}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error guardando sesión: {e}")
            return False
    
    def _invalidate_previous_sessions(self, service: str, session_name: str):
        """Marca como inválidas las sesiones anteriores"""
        try:
            update_query = text("""
                UPDATE public.scraping_sessions
                SET is_valid = FALSE
                WHERE service = :service 
                AND session_name = :session_name 
                AND is_valid = TRUE
            """)
            
            with self.engine.begin() as conn:
                conn.execute(update_query, {
                    'service': service,
                    'session_name': session_name
                })
                
        except Exception as e:
            logger.warning(f"⚠️ Error invalidando sesiones previas: {e}")
    
    def load_session(
        self,
        service: str,
        session_name: str = 'default'
    ) -> Optional[Dict]:
        """
        Carga una sesión válida de la BD
        
        Args:
            service: Nombre del servicio
            session_name: Nombre de la sesión
            
        Returns:
            Dict con 'cookies', 'headers', 'session_id' o None si no hay válida
        """
        if not self.engine and not self.connect():
            return None
        
        try:
            query = text("""
                SELECT id, cookies, headers, expires_at
                FROM public.scraping_sessions
                WHERE service = :service
                AND session_name = :session_name
                AND is_valid = TRUE
                AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
                ORDER BY created_at DESC
                LIMIT 1
            """)
            
            with self.engine.connect() as conn:
                result = conn.execute(query, {
                    'service': service,
                    'session_name': session_name
                }).fetchone()
            
            if result:
                logger.info(f"✅ Sesión cargada: {service}/{session_name}")
                
                # Actualizar last_used
                self._update_last_used(result.id)
                
                # PostgreSQL JSONB ya retorna dict, no necesita json.loads()
                cookies = result.cookies if isinstance(result.cookies, dict) else json.loads(result.cookies)
                headers = result.headers if isinstance(result.headers, dict) else json.loads(result.headers)
                
                return {
                    'session_id': str(result.id),
                    'cookies': cookies,
                    'headers': headers
                }
            else:
                logger.info(f"ℹ️ No hay sesión válida para {service}/{session_name}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error cargando sesión: {e}")
            return None
    
    def _update_last_used(self, session_id: str):
        """Actualiza el timestamp last_used de una sesión"""
        try:
            update_query = text("""
                UPDATE public.scraping_sessions
                SET last_used = CURRENT_TIMESTAMP
                WHERE id = :session_id
            """)
            
            with self.engine.begin() as conn:
                conn.execute(update_query, {'session_id': session_id})
                
        except Exception as e:
            logger.debug(f"⚠️ Error actualizando last_used: {e}")
    
    def mark_session_invalid(self, session_id: str, error_message: Optional[str] = None):
        """
        Marca una sesión como inválida (ej: cuando falla)
        
        Args:
            session_id: UUID de la sesión
            error_message: Mensaje de error opcional
        """
        if not self.engine and not self.connect():
            return
        
        try:
            update_query = text("""
                UPDATE public.scraping_sessions
                SET is_valid = FALSE,
                    last_error = :error,
                    failure_count = failure_count + 1
                WHERE id = :session_id
            """)
            
            with self.engine.begin() as conn:
                conn.execute(update_query, {
                    'session_id': session_id,
                    'error': error_message
                })
            
            logger.info(f"⚠️ Sesión marcada como inválida: {session_id}")
            
        except Exception as e:
            logger.error(f"❌ Error marcando sesión inválida: {e}")
    
    def mark_session_success(self, session_id: str):
        """Incrementa contador de éxitos de una sesión"""
        if not self.engine and not self.connect():
            return
        
        try:
            update_query = text("""
                UPDATE public.scraping_sessions
                SET success_count = success_count + 1,
                    last_used = CURRENT_TIMESTAMP
                WHERE id = :session_id
            """)
            
            with self.engine.begin() as conn:
                conn.execute(update_query, {'session_id': session_id})
                
        except Exception as e:
            logger.debug(f"⚠️ Error actualizando success_count: {e}")
    
    def get_default_headers(self, service: str) -> Dict:
        """Retorna headers por defecto para un servicio"""
        return self.default_headers.get(service, {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def cleanup_expired_sessions(self) -> int:
        """
        Elimina sesiones expiradas de la BD
        
        Returns:
            Número de sesiones eliminadas
        """
        if not self.engine and not self.connect():
            return 0
        
        try:
            delete_query = text("""
                DELETE FROM public.scraping_sessions
                WHERE expires_at < CURRENT_TIMESTAMP
                OR (is_valid = FALSE AND created_at < CURRENT_TIMESTAMP - INTERVAL '7 days')
            """)
            
            with self.engine.begin() as conn:
                result = conn.execute(delete_query)
                deleted = result.rowcount
            
            if deleted > 0:
                logger.info(f"🗑️ {deleted} sesiones expiradas eliminadas")
            
            return deleted
            
        except Exception as e:
            logger.error(f"❌ Error limpiando sesiones: {e}")
            return 0


def test_cookie_manager():
    """Test del cookie manager"""
    import os
    from dotenv import load_dotenv
    
    load_dotenv('/app/airflow/.env')
    
    logging.basicConfig(level=logging.INFO)
    
    # Connection string
    host = os.getenv('POSTGRES_HOST', 'localhost')
    port = os.getenv('POSTGRES_PORT', '5432')
    db = os.getenv('POSTGRES_DB', 'cris_data')
    user = os.getenv('POSTGRES_USER', 'postgres')
    password = os.getenv('POSTGRES_PASSWORD')
    
    connection_string = f"postgresql://{user}:{password}@{host}:{port}/{db}"
    
    manager = CookieManager(connection_string)
    
    # Test 1: Guardar sesión
    print("\n=== Test 1: Guardar sesión ===")
    test_cookies = {
        'JSESSIONID': 'ABC123XYZ',
        'session_token': 'token_value'
    }
    
    success = manager.save_session(
        service='cti_vitae',
        cookies=test_cookies,
        session_name='test_session',
        expires_in_hours=1
    )
    print(f"Guardar sesión: {'✅' if success else '❌'}")
    
    # Test 2: Cargar sesión
    print("\n=== Test 2: Cargar sesión ===")
    loaded = manager.load_session('cti_vitae', 'test_session')
    if loaded:
        print(f"✅ Sesión cargada: {loaded['session_id']}")
        print(f"   Cookies: {loaded['cookies']}")
    else:
        print("❌ No se pudo cargar sesión")
    
    # Test 3: Limpiar sesiones expiradas
    print("\n=== Test 3: Limpiar expiradas ===")
    deleted = manager.cleanup_expired_sessions()
    print(f"Sesiones eliminadas: {deleted}")


if __name__ == "__main__":
    test_cookie_manager()