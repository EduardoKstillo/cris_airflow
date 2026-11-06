import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime

import requests
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

BASE_DIR = Path("/app/airflow")
CONFIG_DIR = BASE_DIR / "config"
LOG_DIR = BASE_DIR / "logs" / "custom"

LOG_DIR.mkdir(parents=True, exist_ok=True)

log_filename = LOG_DIR / f"dspace_publisher_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_filename, mode="w", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)

sys.path.insert(0, str(BASE_DIR))

class DSpaceUniversalPublisher:

    def __init__(self):
        load_dotenv(BASE_DIR / ".env")
        
        self.api_url = os.getenv("DSPACE_API_URL", "https://cris.unsa.edu.pe/server/api").rstrip("/")
        self.email = os.getenv("DSPACE_API_EMAIL")
        self.password = os.getenv("DSPACE_API_PASSWORD")

        self.collections = {
            "organizations": os.getenv("DSPACE_ORGS_COLLECTION_UUID"),
            "persons": os.getenv("DSPACE_PERSONS_COLLECTION_UUID"),
            "projects": os.getenv("DSPACE_PROJECTS_COLLECTION_UUID"),
            "funding_sources": os.getenv("DSPACE_FUNDINGS_COLLECTION_UUID"),
            "funding_calls": os.getenv("DSPACE_FUNDINGS_COLLECTION_UUID"),
            "funding_grants": os.getenv("DSPACE_FUNDINGS_COLLECTION_UUID")
        }

        self.session = requests.Session()
        self.csrf_token = None

        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5432")
        db = os.getenv("POSTGRES_DB", "cris_data")
        user = os.getenv("POSTGRES_USER", "postgres")
        password = os.getenv("POSTGRES_PASSWORD")

        self.engine = create_engine(f"postgresql://{user}:{password}@{host}:{port}/{db}")

        mapping_path = CONFIG_DIR / "dspace_mapping.json"
        if not mapping_path.exists():
            raise FileNotFoundError(f"No se encontró el archivo de mapping: {mapping_path}")

        with open(mapping_path, "r", encoding="utf-8") as f:
            self.mapping = json.load(f)

        self.stats = {}

    def _update_csrf_from_response(self, response: requests.Response):
        new_token = response.headers.get("DSPACE-XSRF-TOKEN")
        if new_token:
            if new_token != self.csrf_token:
                logger.debug("🔄 DSpace devolvió un nuevo CSRF token.")
            self.csrf_token = new_token

    def _make_request(self, method: str, url: str, json_payload: dict = None, data_payload: dict = None) -> requests.Response:
        headers = {"Accept": "application/json"}
        if json_payload is not None:
            headers["Content-Type"] = "application/json"

        authorization = self.session.headers.get("Authorization")
        if authorization:
            headers["Authorization"] = authorization

        modifying_methods = {"POST", "PUT", "PATCH", "DELETE"}
        if method.upper() in modifying_methods:
            if not self.csrf_token:
                logger.warning(f"⚠️ No existe CSRF token antes de {method.upper()} {url}")
            else:
                headers["X-XSRF-TOKEN"] = self.csrf_token

        logger.info(f"   📡 [{method.upper()}] {url}")
        
        response = self.session.request(
            method=method, url=url, headers=headers, json=json_payload, data=data_payload
        )
        self._update_csrf_from_response(response)
        return response

    def _initialize_csrf(self) -> bool:
        csrf_url = f"{self.api_url}/security/csrf"
        logger.info(f"🔐 Obteniendo CSRF token: {csrf_url}")
        
        try:
            response = self.session.get(csrf_url)
            self._update_csrf_from_response(response)
            
            if response.status_code != 204:
                logger.error("❌ No se pudo obtener el CSRF token.")
                return False
                
            if not self.csrf_token:
                logger.error("❌ DSpace no devolvió DSPACE-XSRF-TOKEN.")
                return False
                
            logger.info("✅ CSRF token inicial obtenido.")
            return True
        except requests.RequestException as e:
            logger.error(f"❌ Error de red obteniendo CSRF: {e}")
            return False

    def authenticate(self) -> bool:
        logger.info(f"🔐 Autenticando en DSpace API: {self.api_url}")
        try:
            if not self._initialize_csrf(): return False

            auth_url = f"{self.api_url}/authn/login"
            headers = {"X-XSRF-TOKEN": self.csrf_token, "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
            
            response = self.session.post(auth_url, data={"user": self.email, "password": self.password}, headers=headers)
            self._update_csrf_from_response(response)

            if response.status_code == 200 and "Authorization" in response.headers:
                self.session.headers.update({"Authorization": response.headers["Authorization"]})
                logger.info("✅ Autenticación exitosa")
                return True
                
            logger.error(f"❌ Falló autenticación: HTTP {response.status_code}")
            return False
            
        except Exception as e:
            logger.exception(f"❌ Error inesperado durante autenticación: {e}")
            return False

    def _build_metadata_block(self, row: pd.Series, entity_config: dict, entity_id: str) -> tuple:
        metadata = {}
        missing_fields = []

        # 1. Campos
        for col_name, rules in entity_config.get("fields", {}).items():
            value = row.get(col_name)
            is_empty = pd.isna(value) or value is None or (isinstance(value, str) and str(value).strip() == "")
            
            if rules.get("type") == "fixed":
                value = rules.get("value")
                is_empty = False
                
            elif rules.get("type") == "replace_separator" and not is_empty:
                value = [p.strip() for p in str(value).split(',') if p.strip()]
                is_empty = len(value) == 0

            elif rules.get("type") == "conditional_vocabulary":
                base_column = rules.get("based_on")
                base_value = str(row.get(base_column, "")).strip()
                translation_dict = rules.get("translation", {})
                
                if base_value in translation_dict:
                    value = translation_dict[base_value]
                else:
                    value = translation_dict.get("default", "")
                is_empty = False if value else True

            elif rules.get("type") == "uri" and not is_empty:
                base_domain = self.api_url.replace("/server/api", "")
                value = f"{base_domain}/handle/{value}"
                
            elif is_empty and "default" in rules.get("translation", {}):
                value = rules["translation"]["default"]
                is_empty = False
                
            if is_empty:
                if rules.get("required"): missing_fields.append(col_name)
                continue

            dspace_field = rules["dspace_field"]
            lang = rules.get("language")

            if rules.get("type") == "vocabulary":
                original_value = str(value).strip()
                value = rules.get("translation", {}).get(original_value, original_value)

            if dspace_field not in metadata: metadata[dspace_field] = []
            
            if isinstance(value, list):
                for val in value:
                    meta_obj = {"value": str(val).strip()}
                    if lang: meta_obj["language"] = lang
                    metadata[dspace_field].append(meta_obj)
            else:
                meta_obj = {"value": str(value).strip()}
                if lang: meta_obj["language"] = lang
                metadata[dspace_field].append(meta_obj)

        metadata["dspace.entity.type"] = [{"value": entity_config["dspace_entity_type"]}]

        # 2. Authorities
        if "authorities" in entity_config:
            with self.engine.connect() as conn:
                for auth_name, auth_rules in entity_config["authorities"].items():
                    dspace_field = auth_rules["dspace_field"]
                    try:
                        result = conn.execute(text(auth_rules["sql_query"]), {"entity_id": entity_id}).fetchall()
                    except Exception as e:
                        logger.error(f"❌ Error obteniendo authority {auth_name}: {e}")
                        missing_fields.append(auth_name)
                        continue

                    if not result and auth_rules.get("required"):
                        missing_fields.append(auth_name)
                        continue

                    for auth_row in result:
                        if dspace_field not in metadata: metadata[dspace_field] = []
                        
                        authority_value = getattr(auth_row, "authority", None)
                        display_value = getattr(auth_row, "value", None)
                        
                        if pd.isna(display_value) or display_value is None: continue
                        
                        meta_obj = {"value": str(display_value)}
                        if authority_value:
                            meta_obj["authority"] = str(authority_value)
                            meta_obj["confidence"] = 600
                            
                        metadata[dspace_field].append(meta_obj)

        return metadata, missing_fields

    def update_db_status(self, table: str, record_id: str, status: str, dspace_uuid: str = None, dspace_handle: str = None, error: str = None):
        try:
            with self.engine.begin() as conn:
                if dspace_uuid and dspace_handle:
                    conn.execute(
                        text(f"UPDATE public.{table} SET sync_status = :status, dspace_uuid = :uuid, dspace_handle = :handle, sync_errors = :error, last_sync_date = CURRENT_TIMESTAMP WHERE id = :id"),
                        {"status": status, "uuid": dspace_uuid, "handle": dspace_handle, "error": error, "id": record_id}
                    )
                elif dspace_uuid:
                    conn.execute(
                        text(f"UPDATE public.{table} SET sync_status = :status, dspace_uuid = :uuid, sync_errors = :error, last_sync_date = CURRENT_TIMESTAMP WHERE id = :id"),
                        {"status": status, "uuid": dspace_uuid, "error": error, "id": record_id}
                    )
                else:
                    conn.execute(
                        text(f"UPDATE public.{table} SET sync_status = :status, sync_errors = :error, last_sync_date = CURRENT_TIMESTAMP WHERE id = :id"),
                        {"status": status, "error": error, "id": record_id}
                    )
        except Exception as e:
            logger.error(f"❌ Error actualizando BD {table}/{record_id}: {e}")

    def get_item(self, dspace_uuid: str):
        url = f"{self.api_url}/core/items/{dspace_uuid}"
        response = self._make_request("GET", url)
        if response.status_code != 200: return None
        try: return response.json()
        except ValueError: return None

    def publish_entity(self, entity_key: str, collection_uuid: str):
        if not collection_uuid:
            logger.warning(f"⚠️ Colección no configurada para '{entity_key}'. Saltando...")
            return

        config = self.mapping["entities"][entity_key]
        table = config["table_name"]
        
        logger.info(f"\n🚀 PROCESANDO COLECCIÓN: {entity_key.upper()}")
        self.stats[entity_key] = {"created": 0, "updated": 0, "failed": 0, "skipped": 0}

        try:
            if table == "persons":
                query = f"""
                SELECT p.*,
                       (SELECT c->>'value' 
                        FROM jsonb_array_elements(COALESCE(p.contacts, '[]'::jsonb)) c 
                        WHERE c->>'type' LIKE '%EMAIL_INSTITUCIONAL%' LIMIT 1) AS correo_institucional
                FROM public.persons p
                WHERE p.sync_status IN ('pending_create', 'pending_update')
                AND (
                    EXISTS (SELECT 1 FROM public.person_organization_affiliations poa WHERE poa.person_id = p.id)
                    OR EXISTS (SELECT 1 FROM public.project_researchers pr WHERE pr.researcher_id = p.id AND pr.role = 'Investigador Principal')
                )
                """
            elif table == "projects":
                # Filtra los proyectos con financiamiento externo para que no suban a DSpace
                query = f"""
                SELECT * FROM public.projects 
                WHERE sync_status IN ('pending_create', 'pending_update') 
                AND (project_type IS NULL OR project_type <> 'PROYECTOS UNSA CON FINANCIAMIENTO EXTERNO')
                """
            else:
                order_clause = "ORDER BY parent_organization_id NULLS FIRST" if table == "organizations" else ""
                query = f"SELECT * FROM public.{table} WHERE sync_status IN ('pending_create', 'pending_update') {order_clause}"

            df = pd.read_sql_query(query, self.engine)
        except Exception as e:
            logger.error(f"❌ Error leyendo {table}: {e}")
            return

        if df.empty:
            logger.info("   ✅ No hay registros pendientes.")
            return

        for _, row in df.iterrows():
            record_id = str(row["id"])
            status = row["sync_status"]
            dspace_uuid = str(row["dspace_uuid"]) if pd.notna(row["dspace_uuid"]) else None
            identifier = str(row.get("code", row.get("name", row.get("title", row.get("call_code", row.get("contract_number", "Item"))))))

            try:
                metadata, missing_fields = self._build_metadata_block(row, config, record_id)
            except Exception as e:
                self.update_db_status(table, record_id, "error", error=str(e)[:300])
                self.stats[entity_key]["failed"] += 1
                continue

            if missing_fields:
                error_msg = f"Faltan datos obligatorios ({', '.join(missing_fields)})"
                self.update_db_status(table, record_id, "error", error=error_msg)
                self.stats[entity_key]["skipped"] += 1
                continue

            if status == "pending_create":
                payload = {"name": identifier[:250], "inArchive": True, "discoverable": True, "withdrawn": False, "type": "item", "metadata": metadata}
                url = f"{self.api_url}/core/items?owningCollection={collection_uuid}"
                res = self._make_request("POST", url, json_payload=payload)

                if res.status_code in [200, 201]:
                    new_uuid = res.json().get("uuid")
                    new_handle = res.json().get("handle")
                    
                    if new_uuid:
                        self.update_db_status(table, record_id, "synced", dspace_uuid=new_uuid, dspace_handle=new_handle, error=None)
                        self.stats[entity_key]["created"] += 1
                    else:
                        self.update_db_status(table, record_id, "error", error="DSpace no devolvió UUID.")
                        self.stats[entity_key]["failed"] += 1
                else:
                    self.update_db_status(table, record_id, "error", error=res.text[:300])
                    self.stats[entity_key]["failed"] += 1

            elif status == "pending_update" and dspace_uuid:
                existing_item = self.get_item(dspace_uuid)
                if not existing_item:
                    self.update_db_status(table, record_id, "error", error="No se pudo obtener el Item desde DSpace.")
                    self.stats[entity_key]["failed"] += 1
                    continue

                payload = {
                    "uuid": existing_item.get("uuid", dspace_uuid),
                    "handle": existing_item.get("handle"),
                    "type": existing_item.get("type", "item"),
                    "metadata": metadata
                }
                
                for prop in ["inArchive", "discoverable", "withdrawn"]:
                    if prop in existing_item: payload[prop] = existing_item[prop]

                url = f"{self.api_url}/core/items/{dspace_uuid}"
                res = self._make_request("PUT", url, json_payload=payload)

                if res.status_code in [200, 201, 204]:
                    self.update_db_status(table, record_id, "synced", error=None)
                    self.stats[entity_key]["updated"] += 1
                else:
                    self.update_db_status(table, record_id, "error", error=res.text[:300])
                    self.stats[entity_key]["failed"] += 1

    def run(self):
        start = datetime.now()
        if not self.authenticate(): return
            
        self.publish_entity("organizations", self.collections.get("organizations"))
        self.publish_entity("persons", self.collections.get("persons"))
        self.publish_entity("funding_sources", self.collections.get("funding_sources"))
        self.publish_entity("funding_calls", self.collections.get("funding_calls"))
        self.publish_entity("funding_grants", self.collections.get("funding_grants"))
        self.publish_entity("projects", self.collections.get("projects"))

        duration = (datetime.now() - start).total_seconds()
        logger.info("\n" + "=" * 70)
        logger.info(f"🏁 PUBLICACIÓN FINALIZADA EN {duration:.2f}s")
        for k, v in self.stats.items():
            logger.info(f"   [{k.upper()}] Creados: {v['created']} | Actualizados: {v['updated']} | Rechazados: {v['skipped']} | Errores: {v['failed']}")
        logger.info("=" * 70)

if __name__ == "__main__":
    try:
        publisher = DSpaceUniversalPublisher()
        publisher.run()
    except KeyboardInterrupt:
        logger.warning("⚠️ Ejecución cancelada por el usuario.")
    except Exception as e:
        logger.exception(f"❌ Error fatal del publicador: {e}")
