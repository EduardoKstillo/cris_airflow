-- ============================================================================
-- FASE 2: EXTENSIONES PARA ENRIQUECIMIENTO DE PERSONAS
-- Script de extensión para agregar campos y tablas necesarias para el 
-- enriquecimiento de datos desde Excel, CTI Vitae y Renacyt
-- ============================================================================
-- Autor: Sistema CRIS - UNSA
-- Fecha: 2025-10-20
-- Dependencias: Requiere 01_raw_tables.sql ejecutado previamente
-- ============================================================================

-- ============================================================================
-- 1. EXTENSIONES A LA TABLA PERSONS
-- ============================================================================

-- Campos de enlaces externos
ALTER TABLE public.persons 
ADD COLUMN IF NOT EXISTS link_cti_vitae VARCHAR(500),
ADD COLUMN IF NOT EXISTS link_renacyt VARCHAR(500),
ADD COLUMN IF NOT EXISTS foto_url VARCHAR(500);

-- Campos institucionales de Renacyt
ALTER TABLE public.persons
ADD COLUMN IF NOT EXISTS institucion_laboral_principal VARCHAR(500),
ADD COLUMN IF NOT EXISTS institucion_laboral_actual VARCHAR(500);

-- Campos de contacto de Renacyt
ALTER TABLE public.persons
ADD COLUMN IF NOT EXISTS telefono_fijo VARCHAR(50),
ADD COLUMN IF NOT EXISTS telefono_celular VARCHAR(50);

-- Campos de ubicación de Renacyt
ALTER TABLE public.persons
ADD COLUMN IF NOT EXISTS direccion TEXT,
ADD COLUMN IF NOT EXISTS departamento VARCHAR(100),
ADD COLUMN IF NOT EXISTS provincia VARCHAR(100),
ADD COLUMN IF NOT EXISTS distrito VARCHAR(100);

-- Campos básicos de Renacyt
ALTER TABLE public.persons
ADD COLUMN IF NOT EXISTS nivel_renacyt VARCHAR(50),
ADD COLUMN IF NOT EXISTS condicion_renacyt VARCHAR(50),
ADD COLUMN IF NOT EXISTS formacion_academica JSONB;

-- Campos de tracking de enriquecimiento por fuente
ALTER TABLE public.persons
ADD COLUMN IF NOT EXISTS excel_enriched BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS excel_enriched_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS cti_vitae_enriched BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS cti_vitae_enriched_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS renacyt_enriched BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS renacyt_enriched_at TIMESTAMP;

-- Estado general de enriquecimiento
ALTER TABLE public.persons
ADD COLUMN IF NOT EXISTS enrichment_status VARCHAR(20) DEFAULT 'pending',
ADD COLUMN IF NOT EXISTS enrichment_errors TEXT,
ADD COLUMN IF NOT EXISTS last_enrichment_attempt TIMESTAMP,
ADD COLUMN IF NOT EXISTS enrichment_attempts INTEGER DEFAULT 0;

-- Campos para rastrear fuente de datos (opcional pero recomendado)
ALTER TABLE public.persons
ADD COLUMN IF NOT EXISTS orcid_source VARCHAR(20),
ADD COLUMN IF NOT EXISTS scopus_author_id_source VARCHAR(20),
ADD COLUMN IF NOT EXISTS researcher_id_source VARCHAR(20),
ADD COLUMN IF NOT EXISTS link_cti_vitae_source VARCHAR(20),
ADD COLUMN IF NOT EXISTS gender_source VARCHAR(20);

-- Campos de validación
ALTER TABLE public.persons
ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS needs_revalidation BOOLEAN DEFAULT FALSE;

-- ============================================================================
-- 2. ÍNDICES PARA OPTIMIZAR BÚSQUEDAS DE FASE 2
-- ============================================================================

-- Índices para estado de enriquecimiento
CREATE INDEX IF NOT EXISTS idx_person_enrichment_status 
    ON public.persons(enrichment_status);

CREATE INDEX IF NOT EXISTS idx_person_excel_enriched 
    ON public.persons(excel_enriched) 
    WHERE excel_enriched = FALSE;

CREATE INDEX IF NOT EXISTS idx_person_cti_enriched 
    ON public.persons(cti_vitae_enriched) 
    WHERE cti_vitae_enriched = FALSE;

CREATE INDEX IF NOT EXISTS idx_person_renacyt_enriched 
    ON public.persons(renacyt_enriched) 
    WHERE renacyt_enriched = FALSE;

-- Índices para enlaces
CREATE INDEX IF NOT EXISTS idx_person_link_cti 
    ON public.persons(link_cti_vitae) 
    WHERE link_cti_vitae IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_person_link_renacyt 
    ON public.persons(link_renacyt) 
    WHERE link_renacyt IS NOT NULL;

-- Índice para búsquedas por nombre normalizado
CREATE INDEX IF NOT EXISTS idx_person_full_name_lower 
    ON public.persons(LOWER(full_name));

-- Índice compuesto para matching
CREATE INDEX IF NOT EXISTS idx_person_matching 
    ON public.persons(dni, full_name);

-- Índice para institución laboral
CREATE INDEX IF NOT EXISTS idx_person_institucion_principal 
    ON public.persons(institucion_laboral_principal);

-- ============================================================================
-- 3. TABLA DE LOG DE ENRIQUECIMIENTO
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.person_enrichment_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID NOT NULL REFERENCES public.persons(id) ON DELETE CASCADE,
    enrichment_source VARCHAR(50) NOT NULL,
    enrichment_type VARCHAR(50),
    fields_updated TEXT[],
    status VARCHAR(20) NOT NULL,
    error_message TEXT,
    error_type VARCHAR(50),
    raw_data JSONB,
    execution_time_seconds DECIMAL(8,2),
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT check_enrichment_source CHECK (
        enrichment_source IN ('excel', 'cti_vitae', 'cti_vitae_search', 'renacyt', 'manual')
    ),
    CONSTRAINT check_enrichment_status CHECK (
        status IN ('success', 'partial', 'failed', 'skipped', 'pending')
    )
);

-- Índices para el log
CREATE INDEX IF NOT EXISTS idx_enrich_log_person 
    ON public.person_enrichment_log(person_id);

CREATE INDEX IF NOT EXISTS idx_enrich_log_source 
    ON public.person_enrichment_log(enrichment_source);

CREATE INDEX IF NOT EXISTS idx_enrich_log_status 
    ON public.person_enrichment_log(status);

CREATE INDEX IF NOT EXISTS idx_enrich_log_created 
    ON public.person_enrichment_log(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_enrich_log_person_source 
    ON public.person_enrichment_log(person_id, enrichment_source);

-- ============================================================================
-- 4. TABLA PARA GESTIÓN DE SESIONES DE SCRAPING
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.scraping_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    service VARCHAR(50) NOT NULL,
    session_name VARCHAR(100),
    cookies JSONB,
    headers JSONB,
    user_agent TEXT,
    proxy_config JSONB,
    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_valid BOOLEAN DEFAULT TRUE,
    expires_at TIMESTAMP,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    last_error TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT check_scraping_service CHECK (
        service IN ('cti_vitae', 'cti_vitae_search', 'renacyt', 'scopus', 'wos')
    )
);

-- Índices para sesiones
CREATE INDEX IF NOT EXISTS idx_scraping_service 
    ON public.scraping_sessions(service);

CREATE INDEX IF NOT EXISTS idx_scraping_valid 
    ON public.scraping_sessions(is_valid) 
    WHERE is_valid = TRUE;

CREATE INDEX IF NOT EXISTS idx_scraping_last_used 
    ON public.scraping_sessions(last_used DESC);

-- ============================================================================
-- 5. TABLA PARA CACHÉ DE BÚSQUEDAS CTI VITAE
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.cti_vitae_search_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    search_query VARCHAR(500) NOT NULL,
    normalized_query VARCHAR(500),
    results JSONB,
    result_count INTEGER,
    search_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_valid BOOLEAN DEFAULT TRUE,
    expires_at TIMESTAMP,
    
    CONSTRAINT unique_search_query UNIQUE (normalized_query)
);

CREATE INDEX IF NOT EXISTS idx_cti_cache_query 
    ON public.cti_vitae_search_cache(normalized_query);

CREATE INDEX IF NOT EXISTS idx_cti_cache_valid 
    ON public.cti_vitae_search_cache(is_valid) 
    WHERE is_valid = TRUE;

-- ============================================================================
-- 6. TABLA PARA MATCHING DE NOMBRES (Excel vs BD)
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.person_match_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    excel_name VARCHAR(255) NOT NULL,
    excel_dni VARCHAR(20),
    excel_row_number INTEGER,
    person_id UUID REFERENCES public.persons(id) ON DELETE CASCADE,
    match_type VARCHAR(50),
    similarity_score DECIMAL(5,2),
    match_status VARCHAR(20) DEFAULT 'pending',
    reviewed_by VARCHAR(100),
    reviewed_at TIMESTAMP,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT check_match_type CHECK (
        match_type IN ('exact_dni', 'exact_name', 'fuzzy_name', 'manual', 'no_match')
    ),
    CONSTRAINT check_match_status CHECK (
        match_status IN ('pending', 'confirmed', 'rejected', 'needs_review')
    )
);

CREATE INDEX IF NOT EXISTS idx_match_excel_dni 
    ON public.person_match_candidates(excel_dni);

CREATE INDEX IF NOT EXISTS idx_match_person 
    ON public.person_match_candidates(person_id);

CREATE INDEX IF NOT EXISTS idx_match_status 
    ON public.person_match_candidates(match_status);

-- ============================================================================
-- 7. VISTA PARA ESTADÍSTICAS DE ENRIQUECIMIENTO
-- ============================================================================

-- ============================================================================
-- 1. EXTENSIONES A LA TABLA PERSONS (SOLO DATOS BÁSICOS DE RENACYT)
-- ============================================================================

-- Campos de enlaces externos
ALTER TABLE public.persons 
ADD COLUMN IF NOT EXISTS link_cti_vitae VARCHAR(500),
ADD COLUMN IF NOT EXISTS link_renacyt VARCHAR(500),
ADD COLUMN IF NOT EXISTS foto_url VARCHAR(500);

-- Campos básicos de Renacyt
ALTER TABLE public.persons
ADD COLUMN IF NOT EXISTS nivel_renacyt VARCHAR(50),
ADD COLUMN IF NOT EXISTS condicion_renacyt VARCHAR(50),
ADD COLUMN IF NOT EXISTS formacion_academica JSONB;

-- Campos institucionales de Renacyt
ALTER TABLE public.persons
ADD COLUMN IF NOT EXISTS institucion_laboral_principal VARCHAR(500),
ADD COLUMN IF NOT EXISTS institucion_laboral_actual VARCHAR(500);

-- Campos de contacto de Renacyt
ALTER TABLE public.persons
ADD COLUMN IF NOT EXISTS telefono_fijo VARCHAR(50),
ADD COLUMN IF NOT EXISTS telefono_celular VARCHAR(50);

-- Campos de ubicación de Renacyt
ALTER TABLE public.persons
ADD COLUMN IF NOT EXISTS direccion TEXT,
ADD COLUMN IF NOT EXISTS departamento VARCHAR(100),
ADD COLUMN IF NOT EXISTS provincia VARCHAR(100),
ADD COLUMN IF NOT EXISTS distrito VARCHAR(100);

-- Campos de tracking de enriquecimiento por fuente
ALTER TABLE public.persons
ADD COLUMN IF NOT EXISTS excel_enriched BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS excel_enriched_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS cti_vitae_enriched BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS cti_vitae_enriched_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS renacyt_enriched BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS renacyt_enriched_at TIMESTAMP;

-- Estado general de enriquecimiento
ALTER TABLE public.persons
ADD COLUMN IF NOT EXISTS enrichment_status VARCHAR(20) DEFAULT 'pending',
ADD COLUMN IF NOT EXISTS enrichment_errors TEXT,
ADD COLUMN IF NOT EXISTS last_enrichment_attempt TIMESTAMP,
ADD COLUMN IF NOT EXISTS enrichment_attempts INTEGER DEFAULT 0;

-- Campos para rastrear fuente de datos
ALTER TABLE public.persons
ADD COLUMN IF NOT EXISTS orcid_source VARCHAR(20),
ADD COLUMN IF NOT EXISTS scopus_author_id_source VARCHAR(20),
ADD COLUMN IF NOT EXISTS researcher_id_source VARCHAR(20),
ADD COLUMN IF NOT EXISTS link_cti_vitae_source VARCHAR(20),
ADD COLUMN IF NOT EXISTS gender_source VARCHAR(20);

-- Campos de validación
ALTER TABLE public.persons
ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMP,
ADD COLUMN IF NOT EXISTS needs_revalidation BOOLEAN DEFAULT FALSE;

-- ============================================================================
-- 2. ÍNDICES PARA OPTIMIZAR BÚSQUEDAS DE FASE 2
-- ============================================================================

-- Índices para estado de enriquecimiento
CREATE INDEX IF NOT EXISTS idx_person_enrichment_status 
    ON public.persons(enrichment_status);

CREATE INDEX IF NOT EXISTS idx_person_excel_enriched 
    ON public.persons(excel_enriched) 
    WHERE excel_enriched = FALSE;

CREATE INDEX IF NOT EXISTS idx_person_cti_enriched 
    ON public.persons(cti_vitae_enriched) 
    WHERE cti_vitae_enriched = FALSE;

CREATE INDEX IF NOT EXISTS idx_person_renacyt_enriched 
    ON public.persons(renacyt_enriched) 
    WHERE renacyt_enriched = FALSE;

-- Índices para enlaces
CREATE INDEX IF NOT EXISTS idx_person_link_cti 
    ON public.persons(link_cti_vitae) 
    WHERE link_cti_vitae IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_person_link_renacyt 
    ON public.persons(link_renacyt) 
    WHERE link_renacyt IS NOT NULL;

-- Índice para búsquedas por nombre normalizado
CREATE INDEX IF NOT EXISTS idx_person_full_name_lower 
    ON public.persons(LOWER(full_name));

-- Índice compuesto para matching
CREATE INDEX IF NOT EXISTS idx_person_matching 
    ON public.persons(dni, full_name);

-- Índice para institución laboral
CREATE INDEX IF NOT EXISTS idx_person_institucion_principal 
    ON public.persons(institucion_laboral_principal);

-- ============================================================================
-- 11. COMENTARIOS PARA DOCUMENTACIÓN (ACTUALIZADOS)
-- ============================================================================

COMMENT ON COLUMN public.persons.link_cti_vitae IS 
    'URL completa de la ficha CTI Vitae del investigador en CONCYTEC';

COMMENT ON COLUMN public.persons.link_renacyt IS 
    'URL completa de la ficha Renacyt del investigador';

COMMENT ON COLUMN public.persons.nivel_renacyt IS 
    'Nivel del investigador en Renacyt (Carlos I, II, III, IV, V, María Rostworowski I, II, III)';

COMMENT ON COLUMN public.persons.condicion_renacyt IS 
    'Condición actual en Renacyt (Vigente, Vencido, etc.)';

COMMENT ON COLUMN public.persons.formacion_academica IS 
    'JSON con formación académica completa: [{grado, titulo, centro_estudios, fecha_inicio, fecha_fin, puntaje_obtenido}]';

COMMENT ON COLUMN public.persons.institucion_laboral_principal IS 
    'Institución laboral principal declarada en Renacyt';

COMMENT ON COLUMN public.persons.institucion_laboral_actual IS 
    'Institución laboral actual del investigador';

COMMENT ON COLUMN public.persons.telefono_fijo IS 
    'Teléfono fijo del investigador desde Renacyt';

COMMENT ON COLUMN public.persons.telefono_celular IS 
    'Teléfono celular del investigador desde Renacyt';

COMMENT ON COLUMN public.persons.direccion IS 
    'Dirección completa del investigador';

COMMENT ON COLUMN public.persons.departamento IS 
    'Departamento de residencia del investigador';

COMMENT ON COLUMN public.persons.provincia IS 
    'Provincia de residencia del investigador';

COMMENT ON COLUMN public.persons.distrito IS 
    'Distrito de residencia del investigador';

COMMENT ON COLUMN public.persons.foto_url IS 
    'URL de la foto de perfil del investigador desde CTI Vitae';

COMMENT ON COLUMN public.persons.enrichment_status IS 
    'Estado del enriquecimiento: pending, partial, complete, failed';

COMMENT ON COLUMN public.persons.enrichment_errors IS 
    'Mensajes de error acumulados durante los intentos de enriquecimiento';

COMMENT ON COLUMN public.persons.orcid_source IS 
    'Fuente del ORCID: excel, cti_vitae, manual';

-- ============================================================================
-- 7. VISTA PARA ESTADÍSTICAS DE ENRIQUECIMIENTO (ACTUALIZADA)
-- ============================================================================

CREATE OR REPLACE VIEW public.v_enrichment_stats AS
SELECT 
    COUNT(*) as total_persons,
    COUNT(*) FILTER (WHERE excel_enriched = TRUE) as excel_enriched_count,
    COUNT(*) FILTER (WHERE cti_vitae_enriched = TRUE) as cti_enriched_count,
    COUNT(*) FILTER (WHERE renacyt_enriched = TRUE) as renacyt_enriched_count,
    COUNT(*) FILTER (WHERE enrichment_status = 'complete') as fully_enriched,
    COUNT(*) FILTER (WHERE enrichment_status = 'pending') as pending_enrichment,
    COUNT(*) FILTER (WHERE enrichment_status = 'failed') as failed_enrichment,
    COUNT(*) FILTER (WHERE link_cti_vitae IS NOT NULL) as with_cti_link,
    COUNT(*) FILTER (WHERE link_renacyt IS NOT NULL) as with_renacyt_link,
    COUNT(*) FILTER (WHERE orcid IS NOT NULL) as with_orcid,
    COUNT(*) FILTER (WHERE scopus_author_id IS NOT NULL) as with_scopus,
    COUNT(*) FILTER (WHERE researcher_id IS NOT NULL) as with_wos,
    COUNT(*) FILTER (WHERE nivel_renacyt IS NOT NULL) as with_nivel_renacyt,
    COUNT(*) FILTER (WHERE formacion_academica IS NOT NULL) as with_formacion_academica,
    COUNT(*) FILTER (WHERE institucion_laboral_principal IS NOT NULL) as with_institucion,
    ROUND(AVG(enrichment_attempts), 2) as avg_enrichment_attempts
FROM public.persons;

-- ============================================================================
-- 8. VISTA PARA PERSONAS PENDIENTES DE ENRIQUECIMIENTO
-- ============================================================================

CREATE OR REPLACE VIEW public.v_persons_pending_enrichment AS
SELECT 
    p.id,
    p.full_name,
    p.dni,
    p.enrichment_status,
    p.excel_enriched,
    p.cti_vitae_enriched,
    p.renacyt_enriched,
    p.link_cti_vitae,
    p.link_renacyt,
    p.enrichment_attempts,
    p.last_enrichment_attempt,
    p.enrichment_errors
FROM public.persons p
WHERE 
    p.enrichment_status IN ('pending', 'failed')
    OR p.excel_enriched = FALSE
    OR p.cti_vitae_enriched = FALSE
    OR (p.link_renacyt IS NOT NULL AND p.renacyt_enriched = FALSE)
ORDER BY 
    p.enrichment_attempts ASC,
    p.last_enrichment_attempt ASC NULLS FIRST;

-- ============================================================================
-- 9. FUNCIÓN PARA ACTUALIZAR TIMESTAMP DE updated_at
-- ============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Aplicar trigger a scraping_sessions
DROP TRIGGER IF EXISTS update_scraping_sessions_updated_at ON public.scraping_sessions;
CREATE TRIGGER update_scraping_sessions_updated_at
    BEFORE UPDATE ON public.scraping_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- 10. FUNCIÓN PARA NORMALIZAR NOMBRES (útil para matching)
-- ============================================================================

CREATE OR REPLACE FUNCTION normalize_name(name TEXT)
RETURNS TEXT AS $$
BEGIN
    RETURN LOWER(
        TRIM(
            REGEXP_REPLACE(
                -- Remover acentos
                TRANSLATE(name, 
                    'áéíóúàèìòùäëïöüâêîôûãõñÁÉÍÓÚÀÈÌÒÙÄËÏÖÜÂÊÎÔÛÃÕÑ',
                    'aeiouaeiouaeiouaeiouaonAEIOUAEIOUAEIOUAEIOUAON'
                ),
                -- Remover caracteres especiales excepto espacios
                '[^a-z0-9 ]', '', 'g'
            )
        )
    );
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- ============================================================================
-- 11. COMENTARIOS PARA DOCUMENTACIÓN
-- ============================================================================

COMMENT ON COLUMN public.persons.link_cti_vitae IS 
    'URL completa de la ficha CTI Vitae del investigador en CONCYTEC';

COMMENT ON COLUMN public.persons.link_renacyt IS 
    'URL completa de la ficha Renacyt del investigador';

COMMENT ON COLUMN public.persons.nivel_renacyt IS 
    'Nivel del investigador en Renacyt (Carlos I, II, III, IV, V, María Rostworowski I, II, III)';

COMMENT ON COLUMN public.persons.condicion_renacyt IS 
    'Condición actual en Renacyt (Vigente, Vencido, etc.)';

COMMENT ON COLUMN public.persons.formacion_academica IS 
    'JSON con formación académica completa: [{grado, titulo, centro_estudios, fecha_inicio, fecha_fin, puntaje_obtenido}]';

COMMENT ON COLUMN public.persons.institucion_laboral_principal IS 
    'Institución laboral principal declarada en Renacyt';

COMMENT ON COLUMN public.persons.institucion_laboral_actual IS 
    'Institución laboral actual del investigador';

COMMENT ON COLUMN public.persons.telefono_fijo IS 
    'Teléfono fijo del investigador desde Renacyt';

COMMENT ON COLUMN public.persons.telefono_celular IS 
    'Teléfono celular del investigador desde Renacyt';

COMMENT ON COLUMN public.persons.direccion IS 
    'Dirección completa del investigador';

COMMENT ON COLUMN public.persons.departamento IS 
    'Departamento de residencia del investigador';

COMMENT ON COLUMN public.persons.provincia IS 
    'Provincia de residencia del investigador';

COMMENT ON COLUMN public.persons.distrito IS 
    'Distrito de residencia del investigador';

COMMENT ON COLUMN public.persons.foto_url IS 
    'URL de la foto de perfil del investigador desde CTI Vitae';

COMMENT ON COLUMN public.persons.enrichment_status IS 
    'Estado del enriquecimiento: pending, partial, complete, failed';

COMMENT ON COLUMN public.persons.enrichment_errors IS 
    'Mensajes de error acumulados durante los intentos de enriquecimiento';

COMMENT ON COLUMN public.persons.orcid_source IS 
    'Fuente del ORCID: excel, cti_vitae, manual';

-- ============================================================================
-- 12. VERIFICACIÓN FINAL
-- ============================================================================

DO $$
DECLARE
    table_count INTEGER;
    view_count INTEGER;
BEGIN
    -- Contar tablas nuevas
    SELECT COUNT(*) INTO table_count
    FROM information_schema.tables
    WHERE table_schema = 'public'
    AND table_name IN (
        'person_enrichment_log',
        'scraping_sessions',
        'cti_vitae_search_cache',
        'person_match_candidates'
    );
    
    -- Contar vistas nuevas
    SELECT COUNT(*) INTO view_count
    FROM information_schema.views
    WHERE table_schema = 'public'
    AND table_name IN (
        'v_enrichment_stats',
        'v_persons_pending_enrichment'
    );
    
    RAISE NOTICE '============================================';
    RAISE NOTICE 'Fase 2 Extensions - Resumen de instalación:';
    RAISE NOTICE '============================================';
    RAISE NOTICE 'Tablas creadas: %', table_count;
    RAISE NOTICE 'Vistas creadas: %', view_count;
    RAISE NOTICE 'Columnas agregadas a persons: 20+';
    RAISE NOTICE 'Índices creados: 20+';
    RAISE NOTICE 'Funciones creadas: 2';
    RAISE NOTICE '============================================';
    
    IF table_count = 4 AND view_count = 2 THEN
        RAISE NOTICE '✅ Fase 2 Extensions instalada correctamente';
    ELSE
        RAISE WARNING '⚠️ Algunas tablas o vistas pueden no haberse creado';
    END IF;
END $$;