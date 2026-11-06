"""
renacyt_api_client.py
Cliente para obtener datos de investigadores desde la API de Renacyt
Flujo: URL Ficha Renacyt -> ID CTI Vitae -> Datos completos del investigador
"""

import requests
import logging
from typing import Dict, Optional, List
import time
import re
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)


class RenacytAPIClient:
    """
    Cliente para interactuar con la API de Renacyt
    
    Flujo de obtención de datos:
    1. URL de ficha Renacyt -> Extraer idInvestigador
    2. idInvestigador -> Obtener datos básicos del acto registral
    3. solicitudId -> Obtener datos de contacto y ubicación
    4. solicitudId -> Obtener formación académica
    """
    
    BASE_URL = "https://renacyt.concytec.gob.pe/renacyt-backend"
    FICHA_BASE_URL = "https://servicio-renacyt.concytec.gob.pe/ficha-renacyt/"
    
    def __init__(self, timeout: int = 30):
        """
        Args:
            timeout: Timeout para las peticiones HTTP (segundos)
        """
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def extract_id_from_url(self, ficha_url: str) -> Optional[str]:
        """
        Extrae el idInvestigador desde la URL de la ficha Renacyt
        
        Args:
            ficha_url: URL completa o solo el ID
                      Ej: "https://servicio-renacyt.concytec.gob.pe/ficha-renacyt/?idInvestigador=1557"
                      O simplemente: "1557"
        
        Returns:
            ID del investigador como string o None si no se puede extraer
        """
        try:
            # Si ya es solo un número, retornarlo
            if ficha_url.strip().isdigit():
                return ficha_url.strip()
            
            # Intentar parsear como URL
            parsed = urlparse(ficha_url)
            query_params = parse_qs(parsed.query)
            
            if 'idInvestigador' in query_params:
                id_investigador = query_params['idInvestigador'][0]
                logger.debug(f"✓ ID extraído de URL: {id_investigador}")
                return id_investigador
            
            # Intentar extraer con regex como fallback
            match = re.search(r'idInvestigador[=:](\d+)', ficha_url)
            if match:
                id_investigador = match.group(1)
                logger.debug(f"✓ ID extraído con regex: {id_investigador}")
                return id_investigador
            
            logger.error(f"❌ No se pudo extraer ID de: {ficha_url}")
            return None
            
        except Exception as e:
            logger.error(f"❌ Error extrayendo ID: {e}")
            return None
    
    def get_investigador_data(self, cti_vitae_id: str) -> Optional[Dict]:
        """
        Obtiene datos del investigador desde el acto registral usando el ID de CTI Vitae
        
        Args:
            cti_vitae_id: ID del investigador (extraído de la URL)
            
        Returns:
            Dict con datos del investigador o None si falla
        """
        url = f"{self.BASE_URL}/actoRegistral/obtenerCalificacionInvestigadorFichaRenacyt"
        
        try:
            logger.info(f"🔍 Obteniendo datos del investigador ID: {cti_vitae_id}")
            
            payload = {
                "data": {
                    "ctiVitae": cti_vitae_id
                }
            }
            
            response = self.session.post(url, json=payload, timeout=self.timeout)
            
            if response.status_code != 200:
                logger.error(f"❌ HTTP {response.status_code}: {url}")
                return None
            
            data = response.json()
            
            if data.get('responseCode') != '1':
                logger.error(f"❌ Error en respuesta: {data.get('messageErrors', 'Unknown')}")
                return None
            
            investigador_data = data.get('data', {})
            
            # Extraer datos relevantes
            extracted = self._extract_investigador_data(investigador_data)
            
            logger.info(f"   ✅ Datos obtenidos: {extracted.get('nombre_completo', 'N/A')}")
            
            time.sleep(0.5)  # Pausa cortés
            
            return extracted
            
        except requests.exceptions.Timeout:
            logger.error(f"⏱️ Timeout obteniendo investigador ID: {cti_vitae_id}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error de request: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Error inesperado: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None
    
    def get_solicitud_data(self, solicitud_id: int) -> Optional[Dict]:
        """
        Obtiene datos de la solicitud del investigador (contacto y ubicación)
        
        Args:
            solicitud_id: ID de la solicitud
            
        Returns:
            Dict con datos de la solicitud o None si falla
        """
        url = f"{self.BASE_URL}/solicitud/obtenerSolicitud"
        
        try:
            logger.info(f"📄 Obteniendo solicitud ID: {solicitud_id}")
            
            payload = {"data": {"id": solicitud_id}}
            
            response = self.session.post(url, json=payload, timeout=self.timeout)
            
            if response.status_code != 200:
                logger.error(f"❌ HTTP {response.status_code}: {url}")
                return None
            
            data = response.json()
            
            if data.get('responseCode') != '1':
                logger.error(f"❌ Error en respuesta: {data.get('messageErrors', 'Unknown')}")
                return None
            
            solicitud_data = data.get('data', {})
            
            # Extraer datos relevantes
            extracted = self._extract_solicitud_data(solicitud_data)
            
            logger.info(f"   ✅ Datos de solicitud obtenidos")
            
            time.sleep(0.5)
            
            return extracted
            
        except requests.exceptions.Timeout:
            logger.error(f"⏱️ Timeout obteniendo solicitud: {solicitud_id}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error de request: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Error inesperado: {e}")
            return None
    
    def get_formacion_academica(self, solicitud_id: int) -> Optional[List[Dict]]:
        """
        Obtiene información de formación académica del investigador
        
        Args:
            solicitud_id: ID de la solicitud
            
        Returns:
            Lista de formaciones académicas o None si falla
        """
        url = f"{self.BASE_URL}/usuario/obtenerInformacionCriteriosFiltroCc/{solicitud_id}"
        
        try:
            logger.info(f"🎓 Obteniendo formación académica (solicitud ID: {solicitud_id})")
            
            response = self.session.get(url, timeout=self.timeout)
            
            if response.status_code != 200:
                logger.error(f"❌ HTTP {response.status_code}: {url}")
                return []
            
            data = response.json()
            
            # Este endpoint retorna los datos directamente, sin wrapper de responseCode
            logger.debug(f"   📦 Keys principales del response: {list(data.keys())[:5]}")
            
            # Verificar si tiene la estructura esperada (criterioARequest)
            if 'criterioARequest' not in data:
                logger.warning(f"⚠️ No se encontró 'criterioARequest' en la respuesta")
                logger.debug(f"   Keys disponibles: {list(data.keys())}")
                return []
            
            # Extraer formaciones académicas (pasamos el objeto completo con estructura: {'criterioARequest': ...})
            # No hay que acceder a data['data'] porque no existe ese wrapper
            formaciones = self._extract_formacion_academica({'data': data})
            
            logger.info(f"   ✅ {len(formaciones)} formaciones académicas obtenidas")
            
            time.sleep(0.5)
            
            return formaciones
            
        except requests.exceptions.Timeout:
            logger.error(f"⏱️ Timeout obteniendo formación académica: {solicitud_id}")
            return []
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error de request: {e}")
            return []
        except Exception as e:
            logger.error(f"❌ Error inesperado: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return []
    
    def get_complete_profile_from_url(self, ficha_url: str) -> Optional[Dict]:
        """
        Obtiene el perfil completo del investigador desde la URL de su ficha Renacyt
        
        FLUJO COMPLETO:
        1. Extrae idInvestigador de la URL
        2. Obtiene datos básicos (nombre, nivel, institución, etc.)
        3. Si tiene solicitudId, obtiene contacto y ubicación
        4. Si tiene solicitudId, obtiene formación académica
        
        Args:
            ficha_url: URL completa de la ficha Renacyt o solo el ID
                      Ej: "https://servicio-renacyt.concytec.gob.pe/ficha-renacyt/?idInvestigador=1557"
                      O: "1557"
        
        Returns:
            Dict con todos los datos combinados o None si falla
        """
        logger.info(f"📊 Iniciando obtención de perfil completo")
        logger.info(f"   URL/ID: {ficha_url}")
        
        # 1. Extraer ID de la URL
        cti_vitae_id = self.extract_id_from_url(ficha_url)
        
        if not cti_vitae_id:
            logger.error("❌ No se pudo extraer ID del investigador")
            return None
        
        # 2. Obtener datos básicos del investigador
        investigador = self.get_investigador_data(cti_vitae_id)
        
        if not investigador:
            logger.error(f"❌ No se pudieron obtener datos básicos del ID: {cti_vitae_id}")
            return None
        
        # 3. Obtener datos adicionales si existe solicitud_id
        solicitud_id = investigador.get('solicitud_id')
        
        if solicitud_id:
            # Datos de solicitud (contacto, ubicación)
            solicitud = self.get_solicitud_data(solicitud_id)
            if solicitud:
                investigador.update(solicitud)
            
            # Formación académica
            formacion = self.get_formacion_academica(solicitud_id)
            if formacion:
                investigador['formacion_academica'] = formacion
        else:
            logger.warning(f"⚠️ No hay solicitud_id para el investigador {cti_vitae_id}")
            investigador['formacion_academica'] = []
        
        # Agregar URL original
        investigador['ficha_renacyt_url'] = f"{self.FICHA_BASE_URL}?idInvestigador={cti_vitae_id}"
        
        logger.info(f"✅ Perfil completo obtenido para ID: {cti_vitae_id}")
        
        return investigador
    
    def _extract_investigador_data(self, data: Dict) -> Dict:
        """
        Extrae y estructura los datos relevantes del investigador
        
        Args:
            data: Dict con respuesta del endpoint de acto registral
            
        Returns:
            Dict con datos estructurados
        """
        return {
            # Identificación
            'codigo_registro': data.get('codigoRegistro'),
            'tipo_documento': data.get('tipoDocumento'),
            'numero_documento': data.get('numeroDocumento'),
            
            # Datos personales
            'apellido_paterno': data.get('apellidoPaterno'),
            'apellido_materno': data.get('apellidoMaterno'),
            'nombres': data.get('nombres'),
            'nombre_completo': f"{data.get('apellidoPaterno', '')} {data.get('apellidoMaterno', '')} {data.get('nombres', '')}".strip(),
            'genero': data.get('genero'),
            
            # Contacto
            'email': data.get('emailNotificar'),
            
            # Información académica/profesional
            'orcid': data.get('orcid'),
            'cti_vitae': data.get('ctiVitae'),
            
            # Renacyt
            'grupo': data.get('grupo'),
            'nivel': data.get('nivel'),
            'condicion': data.get('condicion'),
            'fecha_inicio_vigencia': data.get('fechaInicioVigencia'),
            'fecha_fin_vigencia': data.get('fechaFinVigencia'),
            'fecha_registro_activo': data.get('fechaRegistroActivo'),
            
            # Institucional
            'institucion_laboral_principal': data.get('institucionLaboralPrincipal'),
            'institucion_laboral_actual': data.get('institucionLaboralActual'),
            
            # Áreas
            'areas_ocde': data.get('areasOcde'),
            
            # IDs para consultas adicionales
            'solicitud_id': data.get('solicitudId'),
            'convocatoria_id': data.get('convocatoriaId'),
            
            # Documentos
            'hoja_ruta': data.get('hojaRuta'),
            'ruta_documento': data.get('rutaDocumento'),
            'ruta_constancia_activo': data.get('rutaConstanciaActivo'),
            
            # Estado
            'anulado': data.get('anulado', False),
            'fecha_anulacion': data.get('fechaAnulacion'),
        }
    
    def _extract_solicitud_data(self, data: Dict) -> Dict:
        """
        Extrae datos relevantes de la solicitud (contacto y ubicación)
        
        Args:
            data: Dict con respuesta del endpoint de solicitud
            
        Returns:
            Dict con datos de contacto y ubicación
        """
        postulante = data.get('postulante', {})
        
        return {
            # Contacto
            'telefono_fijo': postulante.get('telefonoFijo', '').strip(),
            'telefono_celular': postulante.get('telefonoCelular', '').strip(),
            
            # Ubicación
            'direccion': postulante.get('direccion'),
            'departamento': postulante.get('descDepartamento'),
            'provincia': postulante.get('descProvincia'),
            'distrito': postulante.get('descDistrito'),
            
            # Datos adicionales del postulante
            'pais_nacimiento': postulante.get('paisNacimiento'),
            'fecha_nacimiento': postulante.get('fechaNacimiento'),
            'id_investigador': postulante.get('idInvestigador'),
            
            # Datos de solicitud
            'tipo_solicitud': data.get('tipoSolicitud'),
            'nivel_simulado': data.get('nivelSimulado'),
            'puntaje_simulado': data.get('puntajeSimulado'),
            'fecha_notificacion': data.get('fechaNotificacion'),
        }
    
    def _extract_formacion_academica(self, data: Dict) -> List[Dict]:
        """
        Extrae formaciones académicas del criterio A
        
        Args:
            data: Dict con respuesta del endpoint de criterios
            
        Returns:
            Lista de formaciones académicas
        """
        formaciones = []
        
        try:
            logger.debug("🔍 DEBUG: Estructura completa del JSON de formación:")
            logger.debug(f"   Keys principales: {list(data.keys())}")
            
            # Intentar diferentes estructuras posibles
            data_content = data.get('data', {})
            logger.debug(f"   Keys en 'data': {list(data_content.keys())}")
            
            criterio_a = data_content.get('criterioARequest', {})
            logger.debug(f"   Keys en 'criterioARequest': {list(criterio_a.keys())}")
            
            formaciones_raw = criterio_a.get('formacionesAcademicas', [])
            logger.debug(f"   Total formaciones encontradas: {len(formaciones_raw)}")
            
            if not formaciones_raw:
                logger.warning("⚠️ No se encontraron formaciones académicas en la respuesta")
                logger.debug(f"   Contenido completo de criterio_a: {criterio_a}")
                return []
            
            for idx, item in enumerate(formaciones_raw):
                logger.debug(f"\n   --- Procesando formación {idx + 1} ---")
                logger.debug(f"   Keys del item: {list(item.keys())}")
                
                formacion_pojo = item.get('formacionAcademicaPOJO', {})
                logger.debug(f"   Keys del POJO: {list(formacion_pojo.keys())}")
                
                considerado_cc = item.get('consideradoParaCC', False)
                logger.debug(f"   consideradoParaCC: {considerado_cc}")
                logger.debug(f"   Grado: {formacion_pojo.get('descGradoAcademico')}")
                logger.debug(f"   Título: {formacion_pojo.get('titulo')}")
                
                # Solo agregar si está considerada para calificación
                if considerado_cc:
                    formacion_extraida = {
                        'id': formacion_pojo.get('id'),
                        'grado': formacion_pojo.get('descGradoAcademico'),
                        'titulo': formacion_pojo.get('titulo'),
                        'centro_estudios': formacion_pojo.get('descCentroEstudios'),
                        'fecha_inicio': formacion_pojo.get('fechaInicio'),
                        'fecha_fin': formacion_pojo.get('fechaFin'),
                        'puntaje_obtenido': formacion_pojo.get('puntajeObtenido'),
                        'puntaje_renacyt': formacion_pojo.get('puntajeRenacyt'),
                        'importado': formacion_pojo.get('indicadorImportado', False),
                        'calificado': item.get('esCalificado', False),
                    }
                    formaciones.append(formacion_extraida)
                    logger.debug(f"   ✅ Formación agregada: {formacion_extraida['grado']}")
                else:
                    logger.debug(f"   ⏭️ Formación omitida (no considerada para CC)")
            
            logger.info(f"   ✅ Total formaciones extraídas: {len(formaciones)}")
            
            # Ordenar por nivel de grado (Doctorado > Maestría > Licenciatura > Bachiller)
            orden_grados = {
                'Doctorado': 1,
                'Magister': 2,
                'Licenciado / Título': 3,
                'Bachiller': 4
            }
            
            formaciones.sort(key=lambda x: orden_grados.get(x.get('grado', ''), 99))
            
        except Exception as e:
            logger.error(f"❌ Error extrayendo formación académica: {e}")
            import traceback
            logger.debug(traceback.format_exc())
        
        return formaciones


def test_renacyt_api_client():
    """Test del cliente API de Renacyt"""
    logging.basicConfig(
        level=logging.DEBUG,  # ← Cambiado a DEBUG para ver todo el detalle
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    client = RenacytAPIClient()
    
    # URLs de prueba
    test_urls = [
        "https://servicio-renacyt.concytec.gob.pe/ficha-renacyt/?idInvestigador=1557",
        "1557",  # Solo el ID también funciona
    ]
    
    print("\n" + "="*70)
    print("🧪 TEST: Renacyt API Client")
    print("="*70 + "\n")
    
    for test_url in test_urls:
        print(f"\n{'='*70}")
        print(f"Testing con: {test_url}")
        print('='*70)
        
        # Obtener perfil completo
        perfil = client.get_complete_profile_from_url(test_url)
        
        if perfil:
            print("\n✅ PERFIL COMPLETO OBTENIDO\n")
            
            # Datos básicos
            print("📋 DATOS BÁSICOS")
            print("-" * 70)
            print(f"Nombre: {perfil.get('nombre_completo')}")
            print(f"Código: {perfil.get('codigo_registro')}")
            print(f"Documento: {perfil.get('tipo_documento')} {perfil.get('numero_documento')}")
            print(f"Email: {perfil.get('email')}")
            print(f"ORCID: {perfil.get('orcid')}")
            print(f"CTI Vitae: {perfil.get('cti_vitae')}")
            
            # Renacyt
            print(f"\n🎖️ RENACYT")
            print("-" * 70)
            print(f"Nivel: {perfil.get('nivel')} (Grupo {perfil.get('grupo')})")
            print(f"Condición: {perfil.get('condicion')}")
            print(f"Vigencia: {perfil.get('fecha_inicio_vigencia')} - {perfil.get('fecha_fin_vigencia')}")
            
            # Institucional
            print(f"\n🏢 INSTITUCIONAL")
            print("-" * 70)
            print(f"Principal: {perfil.get('institucion_laboral_principal')}")
            print(f"Actual: {perfil.get('institucion_laboral_actual')}")
            print(f"Áreas OCDE: {perfil.get('areas_ocde')}")
            
            # Contacto
            print(f"\n📞 CONTACTO")
            print("-" * 70)
            print(f"Teléfono fijo: {perfil.get('telefono_fijo') or 'N/A'}")
            print(f"Teléfono celular: {perfil.get('telefono_celular') or 'N/A'}")
            
            # Ubicación
            print(f"\n📍 UBICACIÓN")
            print("-" * 70)
            print(f"Dirección: {perfil.get('direccion')}")
            print(f"Distrito: {perfil.get('distrito')}")
            print(f"Provincia: {perfil.get('provincia')}")
            print(f"Departamento: {perfil.get('departamento')}")
            
            # Formación académica
            formacion = perfil.get('formacion_academica', [])
            if formacion:
                print(f"\n🎓 FORMACIÓN ACADÉMICA ({len(formacion)} registros)")
                print("-" * 70)
                for idx, f in enumerate(formacion, 1):
                    print(f"\n{idx}. {f.get('grado')}")
                    print(f"   Título: {f.get('titulo')}")
                    print(f"   Centro: {f.get('centro_estudios')}")
                    print(f"   Puntaje: {f.get('puntaje_obtenido')} pts")
            
            print("\n" + "="*70)
            
            # Solo probar con la primera URL
            break
        else:
            print("\n❌ NO SE PUDO OBTENER EL PERFIL\n")
            print("Posibles causas:")
            print("- ID de investigador inválido")
            print("- Problemas de conectividad")
            print("- API no disponible")


if __name__ == "__main__":
    test_renacyt_api_client()