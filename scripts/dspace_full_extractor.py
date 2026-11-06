"""
Extracción Total DSpace-CRIS 7 -> PostgreSQL (Golden Record)
Soporte dinámico multiplataforma (Windows / Ubuntu / Docker).
"""
import os
import sys
import logging
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Resolución dinámica de la raíz del proyecto
BASE_DIR = Path(os.getenv('AIRFLOW_HOME', Path(__file__).resolve().parent.parent))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Carga de variables de entorno y logs
ENV_FILE = BASE_DIR / '.env'
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)

LOGS_DIR = BASE_DIR / 'logs' / 'custom'
LOGS_DIR.mkdir(parents=True, exist_ok=True)
log_filename = LOGS_DIR / f"dspace_full_extraction_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_filename, mode='w', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


class DSpaceFullExtractor:
    def __init__(self):
        self.api_url = os.getenv('DSPACE_API_URL', 'https://cris.unsa.edu.pe/server/api').rstrip('/')
        self.email = os.getenv('DSPACE_API_EMAIL')
        self.password = os.getenv('DSPACE_API_PASSWORD')
        self.session = requests.Session()
        
        host = os.getenv('POSTGRES_HOST', 'postgres')
        port = os.getenv('POSTGRES_PORT', '5432')
        db = os.getenv('POSTGRES_DB', 'airflow')
        user = os.getenv('POSTGRES_USER', 'airflow')
        password = os.getenv('POSTGRES_PASSWORD', 'airflow')
        self.engine = create_engine(f"postgresql://{user}:{password}@{host}:{port}/{db}", pool_pre_ping=True)
        
        self.stats = {
            'orgs_inserted': 0, 'persons_inserted': 0, 'projects_inserted': 0, 
            'calls_inserted': 0, 'grants_inserted': 0, 'sources_inserted': 0, 
            'affiliations_inserted': 0, 'errors': 0, 'skipped_fundings': 0
        }

    def authenticate(self) -> bool:
        logger.info(f"🔐 Autenticando en DSpace API: {self.api_url}")
        try:
            auth_url = f"{self.api_url}/authn/login"
            response = self.session.post(auth_url, data={'user': self.email, 'password': self.password})
            
            if response.status_code == 200 and 'Authorization' in response.headers:
                self.session.headers.update({'Authorization': response.headers['Authorization']})
                logger.info("✅ Autenticación exitosa")
                return True
            else:
                logger.error(f"❌ Falló autenticación: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"❌ Error de red al autenticar: {e}")
            return False

    def get_meta(self, metadata_dict, key, default=None):
        try:
            if key in metadata_dict and metadata_dict[key]:
                val = metadata_dict[key][0].get('value')
                return val if val is not None else default
            return default
        except Exception:
            return default

    def get_meta_authority(self, metadata_dict, key):
        try:
            if key in metadata_dict and metadata_dict[key]:
                return metadata_dict[key][0].get('authority')
            return None
        except Exception:
            return None

    def get_meta_list(self, metadata_dict, key, separator=", "):
        try:
            if key in metadata_dict and metadata_dict[key]:
                values = [str(item.get('value')) for item in metadata_dict[key] if item.get('value')]
                return separator.join(values) if values else None
            return None
        except Exception:
            return None

    def extract_handle(self, metadata_dict):
        uri = self.get_meta(metadata_dict, 'dc.identifier.uri')
        if uri and 'handle/' in uri:
            return uri.split('handle/')[-1]
        return None

    # def get_cti_vitae_link(self, metadata_dict):
    #     try:
    #         urls = metadata_dict.get('oairecerif.identifier.url', [])
    #         titles = metadata_dict.get('crisrp.site.title', [])
    #         title_map = {t.get('place', i): t.get('value') for i, t in enumerate(titles)}
            
    #         for i, u in enumerate(urls):
    #             place = u.get('place', i)
    #             title = title_map.get(place, '')
    #             if title == 'Perfil de CTI Vitae':
    #                 return u.get('value')
    #         return None
    #     except Exception:
    #         return None

    # Extrae directamente la primera URL disponible en oairecerif.
    def get_cti_vitae_link(self, metadata_dict):
        try:
            return self.get_meta(metadata_dict, 'oairecerif.identifier.url')
        except Exception:
            return None

    def extract_organizations(self):
        logger.info("\n" + "="*50 + "\n🏛️ EXTRACCIÓN DE ORGANIZACIONES\n" + "="*50)
        url = f"{self.api_url}/discover/search/objects?query=search.entitytype:OrgUnit&size=100"
        org_parents = []

        query = text("""
            INSERT INTO public.organizations (
                dspace_uuid, dspace_handle, code, name, acronym, organization_type, 
                description, dependency_type, ruc, scopus_affid, isni, 
                website_url, email, country, address, ocde_classification, ubigeo, sync_status
            )
            VALUES (
                :uuid, :handle, :code, :name, :acronym, :org_type, 
                :description, :dep_type, :ruc, :scopus, :isni, 
                :url, :email, :country, :address, :ocde, :ubigeo, 'synced'
            )
            ON CONFLICT (code) DO UPDATE SET 
                dspace_uuid = EXCLUDED.dspace_uuid,
                dspace_handle = EXCLUDED.dspace_handle,
                name = EXCLUDED.name,
                acronym = EXCLUDED.acronym,
                organization_type = EXCLUDED.organization_type,
                description = EXCLUDED.description,
                dependency_type = EXCLUDED.dependency_type,
                ruc = EXCLUDED.ruc,
                scopus_affid = EXCLUDED.scopus_affid,
                isni = EXCLUDED.isni,
                website_url = EXCLUDED.website_url,
                email = EXCLUDED.email,
                country = EXCLUDED.country,
                address = EXCLUDED.address,
                ocde_classification = EXCLUDED.ocde_classification,
                ubigeo = EXCLUDED.ubigeo,
                sync_status = 'synced'
        """)

        while url:
            try:
                res = self.session.get(url).json()
                objects = res.get('_embedded', {}).get('searchResult', {}).get('_embedded', {}).get('objects', [])
                
                with self.engine.connect() as conn:
                    for obj in objects:
                        with conn.begin():
                            item = obj.get('_embedded', {}).get('indexableObject', {})
                            uuid = item.get('uuid')
                            meta = item.get('metadata', {})
                            
                            try:
                                name = self.get_meta(meta, 'dc.title', 'Sin Nombre')
                                acronym = self.get_meta(meta, 'oairecerif.acronym')
                                org_type = self.get_meta(meta, 'perucris.type.orgunit', 'OTRO') 
                                dep_type = self.get_meta(meta, 'dc.type') 
                                description = self.get_meta(meta, 'dc.description.abstract')
                                ruc = self.get_meta(meta, 'organization.identifier.ruc')
                                scopus_affid = self.get_meta(meta, 'organization.identifier.scopusaffid')
                                isni = self.get_meta(meta, 'organization.identifier.isni')
                                website_url = self.get_meta(meta, 'oairecerif.identifier.url')
                                email = self.get_meta(meta, 'orgunit.email')
                                country = self.get_meta(meta, 'organization.address.addressCountry')
                                address = self.get_meta(meta, 'perucris.address.streetAddress')
                                ubigeo = self.get_meta(meta, 'perucris.ubigeo')
                                ocde_classification = self.get_meta(meta, 'perucris.subject.ocde')
                                handle = self.extract_handle(meta)
                                
                                parent_uuid = self.get_meta_authority(meta, 'organization.parentOrganization')
                                if parent_uuid:
                                    org_parents.append({'child_uuid': uuid, 'parent_uuid': parent_uuid})
                                
                                conn.execute(query, {
                                    'uuid': uuid, 'handle': handle, 'code': acronym or uuid[:8], 
                                    'name': name, 'acronym': acronym, 'org_type': org_type,
                                    'description': description, 'dep_type': dep_type, 'ruc': ruc,
                                    'scopus': scopus_affid, 'isni': isni, 'url': website_url,
                                    'email': email, 'country': country, 'address': address,
                                    'ocde': ocde_classification, 'ubigeo': ubigeo
                                })
                                self.stats['orgs_inserted'] += 1
                            except Exception as e:
                                logger.error(f"❌ Error insertando Organización [UUID: {uuid}]: {e}")
                                self.stats['errors'] += 1
                            
                url = res.get('_embedded', {}).get('searchResult', {}).get('_links', {}).get('next', {}).get('href')
            except Exception as e:
                logger.error(f"❌ Error paginando API Organizaciones: {e}")
                break

        if org_parents:
            logger.info("🔄 Resolviendo jerarquías organizacionales...")
            with self.engine.begin() as conn:
                update_parent_query = text("""
                    UPDATE public.organizations child
                    SET parent_organization_id = parent.id
                    FROM public.organizations parent
                    WHERE child.dspace_uuid = :child_uuid AND parent.dspace_uuid = :parent_uuid
                """)
                conn.execute(update_parent_query, org_parents)

    def extract_persons(self):
        logger.info("\n" + "="*50 + "\n🧑 EXTRACCIÓN DE PERSONAS Y AFILIACIONES\n" + "="*50)
        url = f"{self.api_url}/discover/search/objects?query=search.entitytype:Person&size=100"
        
        query_person = text("""
            INSERT INTO public.persons (
                dspace_uuid, dspace_handle, dni, full_name, gender, orcid, 
                email, phone, scopus_author_id, researcher_id, link_cti_vitae, sync_status
            )
            VALUES (
                :uuid, :handle, :dni, :name, :gender, :orcid, 
                :email, :phone, :scopus_author_id, :researcher_id, :link_cti_vitae, 'synced'
            )
            ON CONFLICT (dni) DO UPDATE SET 
                dspace_uuid = EXCLUDED.dspace_uuid, 
                dspace_handle = EXCLUDED.dspace_handle,
                gender = EXCLUDED.gender, 
                orcid = EXCLUDED.orcid, 
                email = EXCLUDED.email,
                phone = EXCLUDED.phone,
                scopus_author_id = EXCLUDED.scopus_author_id, 
                researcher_id = EXCLUDED.researcher_id, 
                link_cti_vitae = EXCLUDED.link_cti_vitae, 
                sync_status = 'synced'
        """)
        
        query_affil = text("""
            INSERT INTO public.person_organization_affiliations 
            (person_id, organization_id, role, is_active)
            SELECT p.id, o.id, 'Investigador', true
            FROM public.persons p, public.organizations o
            WHERE p.dspace_uuid = :person_uuid AND o.dspace_uuid = :org_uuid
            ON CONFLICT DO NOTHING
        """)

        while url:
            try:
                res = self.session.get(url).json()
                objects = res.get('_embedded', {}).get('searchResult', {}).get('_embedded', {}).get('objects', [])
                
                with self.engine.begin() as conn:
                    for obj in objects:
                        item = obj.get('_embedded', {}).get('indexableObject', {})
                        uuid = item.get('uuid')
                        meta = item.get('metadata', {})
                        
                        try:
                            dni = self.get_meta(meta, 'perucris.identifier.dni')
                            if not dni:
                                continue
                                
                            full_name = self.get_meta(meta, 'dc.title', '')
                            gender = self.get_meta(meta, 'oairecerif.person.gender')
                            orcid = self.get_meta(meta, 'person.identifier.orcid')
                            email = self.get_meta(meta, 'person.email')
                            phone = self.get_meta(meta, 'perucris.phone')
                            scopus_author_id = self.get_meta(meta, 'person.identifier.scopus-author-id')
                            researcher_id = self.get_meta(meta, 'person.identifier.rid')
                            link_cti_vitae = self.get_cti_vitae_link(meta)
                            handle = self.extract_handle(meta)
                            
                            conn.execute(query_person, {
                                'uuid': uuid, 'handle': handle, 'dni': dni, 'name': full_name, 
                                'gender': gender, 'orcid': orcid, 'email': email, 'phone': phone,
                                'scopus_author_id': scopus_author_id, 'researcher_id': researcher_id, 
                                'link_cti_vitae': link_cti_vitae
                            })
                            self.stats['persons_inserted'] += 1

                            if 'oairecerif.person.affiliation' in meta:
                                for affil in meta['oairecerif.person.affiliation']:
                                    org_uuid = affil.get('authority')
                                    if org_uuid:
                                        res_affil = conn.execute(query_affil, {'person_uuid': uuid, 'org_uuid': org_uuid})
                                        if res_affil.rowcount > 0:
                                            self.stats['affiliations_inserted'] += 1

                        except Exception as e:
                            logger.error(f"❌ Error insertando Persona [UUID: {uuid}, DNI: {dni}]: {e}")
                            self.stats['errors'] += 1
                            
                url = res.get('_embedded', {}).get('searchResult', {}).get('_links', {}).get('next', {}).get('href')
            except Exception as e:
                logger.error(f"❌ Error paginando API Personas: {e}")
                break

    def extract_projects(self):
        logger.info("\n" + "="*50 + "\n🚀 EXTRACCIÓN DE PROYECTOS Y EQUIPO\n" + "="*50)
        url = f"{self.api_url}/discover/search/objects?query=search.entitytype:Project&size=100"
        
        query_project = text("""
            INSERT INTO public.projects (
                dspace_uuid, dspace_handle, project_code, title, acronym, 
                abstract, keywords, planned_start_date, estimated_end_date, 
                url, ocde_activity_type, ocde_classification, sync_status
            )
            VALUES (
                :uuid, :handle, :code, :title, :acronym, 
                :abstract, :keywords, :start_date, :end_date, 
                :url, :ocde_type, :ocde_class, 'synced'
            )
            ON CONFLICT (project_code) DO UPDATE SET 
                dspace_uuid = EXCLUDED.dspace_uuid, 
                dspace_handle = EXCLUDED.dspace_handle,
                title = EXCLUDED.title, 
                acronym = EXCLUDED.acronym,
                abstract = EXCLUDED.abstract, 
                keywords = EXCLUDED.keywords,
                planned_start_date = EXCLUDED.planned_start_date,
                estimated_end_date = EXCLUDED.estimated_end_date,
                url = EXCLUDED.url,
                ocde_activity_type = EXCLUDED.ocde_activity_type,
                ocde_classification = EXCLUDED.ocde_classification,
                sync_status = 'synced'
        """)

        query_pi = text("""
            INSERT INTO public.project_researchers (project_id, researcher_id, role, order_in_project)
            SELECT p.id, per.id, 'Investigador Principal', 1
            FROM public.projects p, public.persons per
            WHERE p.dspace_uuid = :proj_uuid AND per.dspace_uuid = :person_uuid
              AND NOT EXISTS (
                  SELECT 1 FROM public.project_researchers pr2 
                  WHERE pr2.project_id = p.id AND pr2.researcher_id = per.id AND pr2.role = 'Investigador Principal'
              )
        """)

        query_coinv = text("""
            INSERT INTO public.project_researchers (project_id, researcher_id, role, order_in_project)
            SELECT p.id, per.id, 'Co-investigador', :order_idx
            FROM public.projects p, public.persons per
            WHERE p.dspace_uuid = :proj_uuid AND per.dspace_uuid = :person_uuid
              AND NOT EXISTS (
                  SELECT 1 FROM public.project_researchers pr2 
                  WHERE pr2.project_id = p.id AND pr2.researcher_id = per.id AND pr2.role = 'Co-investigador'
              )
        """)

        while url:
            try:
                res = self.session.get(url).json()
                objects = res.get('_embedded', {}).get('searchResult', {}).get('_embedded', {}).get('objects', [])
                
                with self.engine.begin() as conn:
                    for obj in objects:
                        item = obj.get('_embedded', {}).get('indexableObject', {})
                        uuid = item.get('uuid')
                        meta = item.get('metadata', {})
                        
                        try:
                            code = self.get_meta(meta, 'oairecerif.internalid')
                            if not code:
                                continue
                                
                            acronym = self.get_meta(meta, 'oairecerif.acronym')
                            title = self.get_meta(meta, 'dc.title', '')
                            abstract_text = self.get_meta(meta, 'dc.description.abstract')
                            keywords = self.get_meta_list(meta, 'dc.subject')
                            
                            start_date = self.get_meta(meta, 'oairecerif.project.startDate')
                            end_date = self.get_meta(meta, 'oairecerif.project.endDate')
                            project_url = self.get_meta(meta, 'oairecerif.identifier.url')

                            ocde_activity_type = self.get_meta_list(meta, 'perucris.project.typeOcde')
                            ocde_classification = self.get_meta_list(meta, 'perucris.subject.ocde')
                            handle = self.extract_handle(meta)
                            
                            # status_url = self.get_meta(meta, 'oairecerif.project.status', '')
                            # status_map = {
                            #     'activo': 'E', 'enejecucion': 'E', 'concluido': 'C', 
                            #     'registrado': 'R', 'anulado': 'X', 'observado': 'O', 'enprocesocierre': 'D'
                            # }
                            # status_code = next((v for k, v in status_map.items() if k in status_url.lower()), 'R')
                            
                            conn.execute(query_project, {
                                'uuid': uuid, 'handle': handle, 'code': code, 'title': title[:500], 'acronym': acronym,
                                'abstract': abstract_text, 'keywords': keywords,
                                'start_date': start_date[:10] if start_date else None, 
                                'end_date': end_date[:10] if end_date else None,
                                'url': project_url, 'ocde_type': ocde_activity_type, 'ocde_class': ocde_classification
                            })
                            
                            pi_uuid = self.get_meta_authority(meta, 'crispj.investigator')
                            if pi_uuid:
                                conn.execute(query_pi, {'proj_uuid': uuid, 'person_uuid': pi_uuid})

                            if 'crispj.coinvestigators' in meta:
                                for i, coinv in enumerate(meta['crispj.coinvestigators']):
                                    coinv_uuid = coinv.get('authority')
                                    if coinv_uuid:
                                        conn.execute(query_coinv, {'proj_uuid': uuid, 'person_uuid': coinv_uuid, 'order_idx': i + 2})
                                        
                            self.stats['projects_inserted'] += 1
                        except Exception as e:
                            logger.error(f"❌ Error insertando Proyecto [UUID: {uuid}, Code: {code}]: {e}")
                            self.stats['errors'] += 1
                            
                url = res.get('_embedded', {}).get('searchResult', {}).get('_links', {}).get('next', {}).get('href')
            except Exception as e:
                logger.error(f"❌ Error paginando API Proyectos: {e}")
                break

    def extract_fundings(self):
        logger.info("\n" + "="*50 + "\n💰 EXTRACCIÓN TOPOLÓGICA DE FINANCIAMIENTOS\n" + "="*50)
        
        sources_data, calls_data, grants_data = [], [], []
        url = f"{self.api_url}/discover/search/objects?query=search.entitytype:Funding&size=100"
        
        while url:
            try:
                res = self.session.get(url).json()
                objects = res.get('_embedded', {}).get('searchResult', {}).get('_embedded', {}).get('objects', [])
                
                for obj in objects:
                    item = obj.get('_embedded', {}).get('indexableObject', {})
                    uuid = item.get('uuid')
                    meta = item.get('metadata', {})
                    
                    try:
                        code = self.get_meta(meta, 'oairecerif.internalid') or self.get_meta(meta, 'oairecerif.acronym') or f"NO-CODE-{uuid[:8]}"
                        title = self.get_meta(meta, 'dc.title', 'Sin Título')
                        acronym = self.get_meta(meta, 'oairecerif.acronym')
                        description = self.get_meta(meta, 'dc.description')
                        dc_type = self.get_meta(meta, 'dc.type', '').lower()
                        parent_uuid = self.get_meta_authority(meta, 'oairecerif.fundingParent')
                        handle = self.extract_handle(meta)
                        
                        payload = {'uuid': uuid, 'handle': handle, 'code': code, 'title': title[:255], 'acronym': acronym, 'description': description, 'parent_uuid': parent_uuid, 'meta': meta}
                        
                        if any(t in dc_type for t in ['gift', 'fundingprogramme', 'internalfunding']):
                            sources_data.append(payload)
                        elif 'call' in dc_type:
                            calls_data.append(payload)
                        elif any(t in dc_type for t in ['contract', 'grant', 'award', 'tender']):
                            # amount_str = self.get_meta(meta, 'oairecerif.amount')
                            # try:
                            #     payload['amount'] = float(amount_str) if amount_str else None
                            # except ValueError:
                            #     payload['amount'] = None
                            # payload['currency'] = self.get_meta(meta, 'oairecerif.amount.currency')
                            
                            # start_date = self.get_meta(meta, 'oairecerif.funding.startDate')
                            # end_date = self.get_meta(meta, 'oairecerif.funding.endDate')
                            # payload['start_date'] = start_date[:10] if start_date else None
                            # payload['end_date'] = end_date[:10] if end_date else None
                            payload['project_uuid'] = self.get_meta_authority(meta, 'dc.relation.project')
                            grants_data.append(payload)
                        else:
                            self.stats['skipped_fundings'] += 1

                    except Exception as e:
                        logger.error(f"❌ Error procesando Funding en Memoria [UUID: {uuid}]: {e}")
                        self.stats['errors'] += 1
                        
                url = res.get('_embedded', {}).get('searchResult', {}).get('_links', {}).get('next', {}).get('href')
            except Exception as e:
                logger.error(f"❌ Error paginando API Fundings: {e}")
                break
                
        source_pg_ids, call_pg_ids = {}, {}

        with self.engine.begin() as conn:
            for src in sources_data:
                try:
                    query = text("""
                        INSERT INTO public.funding_sources (dspace_uuid, dspace_handle, abbreviation, name, description, sync_status)
                        VALUES (:uuid, :handle, :acronym, :name, :description, 'synced')
                        ON CONFLICT (abbreviation) DO UPDATE 
                        SET dspace_uuid = EXCLUDED.dspace_uuid, dspace_handle = EXCLUDED.dspace_handle, name = EXCLUDED.name, description = EXCLUDED.description, sync_status = 'synced'
                        RETURNING id
                    """)
                    result = conn.execute(query, {'uuid': src['uuid'], 'handle': src['handle'], 'acronym': src['code'], 'name': src['title'], 'description': src['description']})
                    source_pg_ids[src['uuid']] = result.scalar()
                    self.stats['sources_inserted'] += 1
                except Exception:
                    self.stats['errors'] += 1

            for call in calls_data:
                pg_source_id = source_pg_ids.get(call['parent_uuid'])
                if not pg_source_id:
                    self.stats['skipped_fundings'] += 1
                    continue
                    
                try:
                    query = text("""
                        INSERT INTO public.funding_calls (dspace_uuid, dspace_handle, call_code, call_name, description, funding_source_id, sync_status)
                        VALUES (:uuid, :handle, :code, :name, :description, :source_id, 'synced')
                        ON CONFLICT (call_code) DO UPDATE 
                        SET dspace_uuid = EXCLUDED.dspace_uuid, dspace_handle = EXCLUDED.dspace_handle, call_name = EXCLUDED.call_name, 
                            description = EXCLUDED.description, funding_source_id = EXCLUDED.funding_source_id, sync_status = 'synced'
                        RETURNING id
                    """)
                    result = conn.execute(query, {
                        'uuid': call['uuid'], 'handle': call['handle'], 'code': call['code'], 'name': call['title'], 'description': call['description'], 'source_id': pg_source_id
                    })
                    call_pg_ids[call['uuid']] = result.scalar()
                    self.stats['calls_inserted'] += 1
                except Exception:
                    self.stats['errors'] += 1

            for grant in grants_data:
                pg_call_id = call_pg_ids.get(grant['parent_uuid'])
                if not pg_call_id:
                    self.stats['skipped_fundings'] += 1
                    continue
                    
                try:
                    query = text("""
                        INSERT INTO public.funding_grants (
                            dspace_uuid, dspace_handle, contract_number, contract_description, 
                            funding_call_id, sync_status
                        )
                        VALUES (:uuid, :handle, :code, :name, :call_id, 'synced')
                        ON CONFLICT (contract_number) DO UPDATE 
                        SET dspace_uuid = EXCLUDED.dspace_uuid, dspace_handle = EXCLUDED.dspace_handle, contract_description = EXCLUDED.contract_description, 
                            funding_call_id = EXCLUDED.funding_call_id, sync_status = 'synced'
                        RETURNING id
                    """)
                    result = conn.execute(query, {
                        'uuid': grant['uuid'], 'handle': grant['handle'], 'code': grant['code'], 'name': grant['title'], 
                        #'amount': grant['amount'], 'currency': grant['currency'], 
                        #'start_date': grant['start_date'], 'end_date': grant['end_date'],
                        'call_id': pg_call_id
                    })
                    grant_pg_id = result.scalar()
                    self.stats['grants_inserted'] += 1
                    
                    if grant.get('project_uuid') and grant_pg_id:
                        query_link = text("""
                            UPDATE public.projects 
                            SET funding_grant_id = :grant_id 
                            WHERE dspace_uuid = :project_uuid
                        """)
                        conn.execute(query_link, {'grant_id': grant_pg_id, 'project_uuid': grant['project_uuid']})
                        
                except Exception:
                    self.stats['errors'] += 1

    def run(self):
        start = datetime.now()
        if not self.authenticate():
            return
            
        self.extract_organizations()
        self.extract_persons()
        self.extract_projects()
        self.extract_fundings()
        
        duration = (datetime.now() - start).total_seconds()
        logger.info("\n" + "="*50)
        logger.info(f"✅ EXTRACCIÓN TOTAL FINALIZADA EN {duration:.2f}s")
        logger.info(f"   🏛️ Organizaciones: {self.stats['orgs_inserted']}")
        logger.info(f"   🧑 Personas: {self.stats['persons_inserted']}")
        logger.info(f"   🤝 Afiliaciones Person-Org: {self.stats['affiliations_inserted']}")
        logger.info(f"   🚀 Proyectos: {self.stats['projects_inserted']}")
        logger.info(f"   🏦 Fuentes: {self.stats['sources_inserted']}")
        logger.info(f"   📢 Convocatorias (Calls): {self.stats['calls_inserted']}")
        logger.info(f"   📝 Contratos (Grants): {self.stats['grants_inserted']}")
        logger.info(f"   ⚠️ Financiamientos Saltados: {self.stats['skipped_fundings']}")
        logger.info(f"   ❌ Errores Críticos: {self.stats['errors']}")
        logger.info("="*50)


if __name__ == "__main__":
    extractor = DSpaceFullExtractor()
    extractor.run()