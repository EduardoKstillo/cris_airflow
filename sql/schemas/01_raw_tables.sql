-- ============================================================================
-- FASE 1: SCHEMA POSTGRESQL - VERSIÓN CON DEPENDENCIAS CORREGIDAS
-- Soluciona: dependencias circulares y orden de creación
-- ============================================================================

-- CREAR ESQUEMAS
CREATE SCHEMA IF NOT EXISTS public;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS raw;

-- ============================================================================
-- 1. TABLA RAW
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.raw_sismo_data (
    id SERIAL PRIMARY KEY,
    extraction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source_system VARCHAR(50) DEFAULT 'SISMO',
    raw_data JSONB NOT NULL,
    processed BOOLEAN DEFAULT FALSE,
    processing_errors TEXT,
    validation_status VARCHAR(20) DEFAULT 'PENDING',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_raw_sismo_extraction_date ON public.raw_sismo_data(extraction_date);
CREATE INDEX IF NOT EXISTS idx_raw_sismo_validation_status ON public.raw_sismo_data(validation_status);

-- ============================================================================
-- 2. ORGANIZATIONS (sin dependencias)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    acronym VARCHAR(50),
    organization_type VARCHAR(100) NOT NULL,
    parent_organization_id UUID REFERENCES public.organizations(id) ON DELETE SET NULL,
    dependency_type VARCHAR(100),
    ruc VARCHAR(20),
    scopus_affid VARCHAR(50),
    isni VARCHAR(50),
    website_url VARCHAR(255),
    email VARCHAR(255),
    country VARCHAR(100),
    address TEXT,
    source_system VARCHAR(50),
    external_id VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_org_code ON public.organizations(code);
CREATE INDEX IF NOT EXISTS idx_org_parent ON public.organizations(parent_organization_id);
CREATE INDEX IF NOT EXISTS idx_org_type ON public.organizations(organization_type);
CREATE INDEX IF NOT EXISTS idx_org_name ON public.organizations(name);

-- ============================================================================
-- 3. PERSONS (sin dependencias)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.persons (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sismo_id INTEGER,
    full_name VARCHAR(255) NOT NULL,
    dni VARCHAR(20),
    document_type VARCHAR(50),
    orcid VARCHAR(50),
    scopus_author_id VARCHAR(50),
    researcher_id VARCHAR(50),
    gender VARCHAR(20),
    email VARCHAR(255),
    phone VARCHAR(20),
    personal_website VARCHAR(255),
    description TEXT,
    funding_info TEXT,
    dni_valid BOOLEAN DEFAULT FALSE,
    source_system VARCHAR(50),
    validation_status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_person_dni ON public.persons(dni);
CREATE INDEX IF NOT EXISTS idx_person_sismo_id ON public.persons(sismo_id);
CREATE INDEX IF NOT EXISTS idx_person_orcid ON public.persons(orcid);
CREATE INDEX IF NOT EXISTS idx_person_name ON public.persons(full_name);

-- ============================================================================
-- 4. PERSON-ORGANIZATION AFFILIATIONS
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.person_organization_affiliations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID NOT NULL REFERENCES public.persons(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    position_title VARCHAR(255),
    role VARCHAR(100),
    start_date DATE,
    end_date DATE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_aff_person ON public.person_organization_affiliations(person_id);
CREATE INDEX IF NOT EXISTS idx_aff_organization ON public.person_organization_affiliations(organization_id);
CREATE INDEX IF NOT EXISTS idx_aff_active ON public.person_organization_affiliations(is_active);

-- ============================================================================
-- 5. FUNDING SOURCES
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.funding_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sismo_funding_source_id INTEGER,
    name VARCHAR(255) NOT NULL,
    abbreviation VARCHAR(50),
    description TEXT,
    source_type VARCHAR(100),
    country VARCHAR(100),
    website VARCHAR(255),
    organization_id UUID REFERENCES public.organizations(id) ON DELETE SET NULL,
    source_system VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_funding_sources_abbreviation UNIQUE (abbreviation)
);

CREATE INDEX IF NOT EXISTS idx_funding_source_sismo_id ON public.funding_sources(sismo_funding_source_id);
CREATE INDEX IF NOT EXISTS idx_funding_source_org ON public.funding_sources(organization_id);
CREATE INDEX IF NOT EXISTS idx_funding_source_name ON public.funding_sources(name);

-- ============================================================================
-- 6. FUNDING CALLS
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.funding_calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sismo_call_id INTEGER,
    funding_source_id UUID NOT NULL REFERENCES public.funding_sources(id) ON DELETE CASCADE,
    call_code VARCHAR(100) NOT NULL,
    call_name VARCHAR(255) NOT NULL,
    description TEXT,
    call_year SMALLINT,
    start_date DATE,
    end_date DATE,
    total_budget DECIMAL(18,2),
    currency VARCHAR(10),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_funding_call_sismo_id ON public.funding_calls(sismo_call_id);
CREATE INDEX IF NOT EXISTS idx_funding_call_source ON public.funding_calls(funding_source_id);
CREATE INDEX IF NOT EXISTS idx_funding_call_code ON public.funding_calls(call_code);

-- ============================================================================
-- 7. RESEARCH LINES
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.research_lines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    organization_id UUID REFERENCES public.organizations(id) ON DELETE SET NULL,
    ocde_field VARCHAR(100),
    ocde_discipline VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_research_line_org ON public.research_lines(organization_id);
CREATE INDEX IF NOT EXISTS idx_research_line_code ON public.research_lines(code);

-- ============================================================================
-- 8. FUNDING GRANTS (antes de projects para evitar circular dependency)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.funding_grants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sismo_contract_id INTEGER,
    funding_call_id UUID NOT NULL REFERENCES public.funding_calls(id) ON DELETE CASCADE,
    organization_id UUID REFERENCES public.organizations(id) ON DELETE SET NULL,
    contract_number VARCHAR(100),
    contract_description TEXT,
    grant_code VARCHAR(100),
    amount DECIMAL(15, 2),
    currency VARCHAR(10),
    start_date DATE,
    end_date DATE,
    lead_researcher_id UUID REFERENCES public.persons(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_funding_grant_sismo_id ON public.funding_grants(sismo_contract_id);
CREATE INDEX IF NOT EXISTS idx_funding_grant_call ON public.funding_grants(funding_call_id);
CREATE INDEX IF NOT EXISTS idx_funding_grant_org ON public.funding_grants(organization_id);
CREATE INDEX IF NOT EXISTS idx_funding_grant_lead ON public.funding_grants(lead_researcher_id);

-- ============================================================================
-- 9. PROJECTS (ahora funding_grants ya existe)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sismo_project_id INTEGER,
    project_code VARCHAR(100) UNIQUE NOT NULL,
    title VARCHAR(500) NOT NULL,
    acronym VARCHAR(50),
    project_type VARCHAR(100),
    status_code VARCHAR(10),
    status_description VARCHAR(100),
    
    planned_start_date DATE,
    estimated_end_date DATE,
    duration_months INTEGER,
    
    abstract TEXT,
    justification TEXT,
    hypothesis TEXT,
    expected_results TEXT,
    impact TEXT,
    general_objective TEXT,
    
    url VARCHAR(255),
    keywords TEXT,
    
    research_line_id UUID REFERENCES public.research_lines(id) ON DELETE SET NULL,
    funding_grant_id UUID REFERENCES public.funding_grants(id) ON DELETE SET NULL,
    
    ocde_activity_type VARCHAR(100),
    ocde_knowledge_field VARCHAR(100),
    ocde_classification VARCHAR(255),
    ocde_confidence_score DECIMAL(5,2),
    
    source_system VARCHAR(50),
    external_id VARCHAR(100),
    validation_status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_project_sismo_id ON public.projects(sismo_project_id);
CREATE INDEX IF NOT EXISTS idx_project_code ON public.projects(project_code);
CREATE INDEX IF NOT EXISTS idx_project_status ON public.projects(status_code);
CREATE INDEX IF NOT EXISTS idx_project_research_line ON public.projects(research_line_id);
CREATE INDEX IF NOT EXISTS idx_project_funding_grant ON public.projects(funding_grant_id);

-- ============================================================================
-- 10. PROJECT-RESEARCHERS
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.project_researchers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    researcher_id UUID NOT NULL REFERENCES public.persons(id) ON DELETE CASCADE,
    contract_id UUID REFERENCES public.funding_grants(id) ON DELETE SET NULL,
    role VARCHAR(100) NOT NULL,
    participation_percentage DECIMAL(5,2),
    order_in_project INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_proj_research_project ON public.project_researchers(project_id);
CREATE INDEX IF NOT EXISTS idx_proj_research_person ON public.project_researchers(researcher_id);

-- ============================================================================
-- 12. RESEARCH AREAS (áreas prioritarias, investigación, líneas)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.research_areas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    area_type VARCHAR(100) NOT NULL,
    area_code VARCHAR(100),
    area_name VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_research_area_project ON public.research_areas(project_id);
CREATE INDEX IF NOT EXISTS idx_research_area_type ON public.research_areas(area_type);

-- ============================================================================
-- 13. PUBLICATIONS
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.publications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(500) NOT NULL,
    doi VARCHAR(100) UNIQUE,
    scopus_id VARCHAR(50) UNIQUE,
    wos_id VARCHAR(50) UNIQUE,
    publication_year SMALLINT,
    publication_date DATE,
    abstract TEXT,
    keywords TEXT,
    journal_name VARCHAR(255),
    volume VARCHAR(20),
    issue VARCHAR(20),
    pages VARCHAR(50),
    publication_type VARCHAR(100),
    url VARCHAR(500),
    project_id UUID REFERENCES public.projects(id) ON DELETE SET NULL,
    source_system VARCHAR(50),
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pub_doi ON public.publications(doi);
CREATE INDEX IF NOT EXISTS idx_pub_year ON public.publications(publication_year);
CREATE INDEX IF NOT EXISTS idx_pub_project ON public.publications(project_id);

-- ============================================================================
-- 14. PUBLICATION-AUTHORS
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.publication_authors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    publication_id UUID NOT NULL REFERENCES public.publications(id) ON DELETE CASCADE,
    person_id UUID NOT NULL REFERENCES public.persons(id) ON DELETE CASCADE,
    author_order INT NOT NULL,
    author_name VARCHAR(255),
    author_affiliation VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pub_author_publication ON public.publication_authors(publication_id);
CREATE INDEX IF NOT EXISTS idx_pub_author_person ON public.publication_authors(person_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pub_author_unique ON public.publication_authors(publication_id, author_order);

-- ============================================================================
-- 15. PATENTS
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.patents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(500) NOT NULL,
    patent_number VARCHAR(100) UNIQUE NOT NULL,
    patent_type VARCHAR(100),
    cip_classification VARCHAR(100),
    granting_entity VARCHAR(255),
    granting_country VARCHAR(100),
    original_filing_date DATE,
    grant_date DATE,
    abstract TEXT,
    url VARCHAR(500),
    language VARCHAR(20),
    ocde_knowledge_field VARCHAR(100),
    keywords TEXT,
    project_id UUID REFERENCES public.projects(id) ON DELETE SET NULL,
    funding_grant_id UUID REFERENCES public.funding_grants(id) ON DELETE SET NULL,
    predecessor_patent_id UUID REFERENCES public.patents(id) ON DELETE SET NULL,
    source_system VARCHAR(50),
    external_id VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_patent_number ON public.patents(patent_number);
CREATE INDEX IF NOT EXISTS idx_patent_project ON public.patents(project_id);

-- ============================================================================
-- 16. PATENT HOLDERS
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.patent_holders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patent_id UUID NOT NULL REFERENCES public.patents(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    holder_type VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_patent_holder_patent ON public.patent_holders(patent_id);
CREATE INDEX IF NOT EXISTS idx_patent_holder_org ON public.patent_holders(organization_id);

-- ============================================================================
-- 17. PATENT INVENTORS
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.patent_inventors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patent_id UUID NOT NULL REFERENCES public.patents(id) ON DELETE CASCADE,
    person_id UUID NOT NULL REFERENCES public.persons(id) ON DELETE CASCADE,
    inventor_order INT,
    inventor_name VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_patent_inventor_patent ON public.patent_inventors(patent_id);
CREATE INDEX IF NOT EXISTS idx_patent_inventor_person ON public.patent_inventors(person_id);

-- ============================================================================
-- 18. DATA VALIDATION LOG
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.data_validation_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type VARCHAR(100),
    entity_id UUID,
    validation_rule VARCHAR(255),
    status VARCHAR(20),
    message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_validation_entity ON public.data_validation_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_validation_status ON public.data_validation_log(status);

-- ============================================================================
-- 19. ETL EXECUTION LOG
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.etl_execution_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_name VARCHAR(100),
    phase VARCHAR(50),
    status VARCHAR(20),
    rows_processed INT,
    rows_succeeded INT,
    rows_failed INT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    duration_seconds INT,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_etl_pipeline ON public.etl_execution_log(pipeline_name);
CREATE INDEX IF NOT EXISTS idx_etl_status ON public.etl_execution_log(status);

-- ============================================================================
-- COMENTARIOS
-- ============================================================================
COMMENT ON TABLE public.organizations IS 'Jerarquía organizacional: Universidad -> Facultades -> Departamentos';
COMMENT ON TABLE public.persons IS 'Investigadores con datos enriquecidos de SIRI y fuentes externas';
COMMENT ON TABLE public.projects IS 'Proyectos de investigación de SISMO';
COMMENT ON TABLE public.funding_grants IS 'Financiamientos otorgados vinculados a convocatorias';
COMMENT ON TABLE public.project_researchers IS 'Relación N:M entre proyectos e investigadores con rol';
COMMENT ON TABLE public.research_areas IS 'Áreas prioritarias y líneas de investigación por proyecto';

-- Fin del script