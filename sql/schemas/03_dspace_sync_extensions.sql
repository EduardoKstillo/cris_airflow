-- ============================================================================
-- FASE 3: EXTENSIONES PARA SINCRONIZACIÓN CON DSPACE-CRIS 7
-- Objetivo: Preparar el esquema para el "Golden Record" y habilitar Upserts
-- ============================================================================

-- 1. PREPARACIÓN DE LLAVES DE NEGOCIO (BUSINESS KEYS) PARA UPSERT
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.persons'::regclass AND conname = 'uq_persons_dni') THEN
        ALTER TABLE public.persons ADD CONSTRAINT uq_persons_dni UNIQUE (dni);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.funding_grants'::regclass AND conname = 'uq_funding_grants_contract') THEN
        ALTER TABLE public.funding_grants ADD CONSTRAINT uq_funding_grants_contract UNIQUE (contract_number);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.funding_calls'::regclass AND conname = 'uq_funding_calls_code') THEN
        ALTER TABLE public.funding_calls ADD CONSTRAINT uq_funding_calls_code UNIQUE (call_code);
    END IF;
END $$;

-- 2. DOMINIOS DE ESTADO DE SINCRONIZACIÓN
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'sync_state_enum') THEN
        CREATE TYPE sync_state_enum AS ENUM ('synced', 'pending_create', 'pending_update', 'error');
    END IF;
END $$;

-- 3. ADICIÓN DE COLUMNAS DE SINCRONIZACIÓN
-- Organizaciones
ALTER TABLE public.organizations
    ADD COLUMN IF NOT EXISTS dspace_uuid UUID UNIQUE,
    ADD COLUMN IF NOT EXISTS dspace_handle VARCHAR(100) UNIQUE,
    ADD COLUMN IF NOT EXISTS sync_status sync_state_enum DEFAULT 'pending_create',
    ADD COLUMN IF NOT EXISTS last_sync_date TIMESTAMP,
    ADD COLUMN IF NOT EXISTS sync_errors TEXT;

-- Personas
ALTER TABLE public.persons
    ADD COLUMN IF NOT EXISTS dspace_uuid UUID UNIQUE,
    ADD COLUMN IF NOT EXISTS dspace_handle VARCHAR(100) UNIQUE,
    ADD COLUMN IF NOT EXISTS sync_status sync_state_enum DEFAULT 'pending_create',
    ADD COLUMN IF NOT EXISTS last_sync_date TIMESTAMP,
    ADD COLUMN IF NOT EXISTS sync_errors TEXT;

-- Proyectos
ALTER TABLE public.projects
    ADD COLUMN IF NOT EXISTS dspace_uuid UUID UNIQUE,
    ADD COLUMN IF NOT EXISTS dspace_handle VARCHAR(100) UNIQUE,
    ADD COLUMN IF NOT EXISTS sync_status sync_state_enum DEFAULT 'pending_create',
    ADD COLUMN IF NOT EXISTS last_sync_date TIMESTAMP,
    ADD COLUMN IF NOT EXISTS sync_errors TEXT;

-- Financiamientos (Grants)
ALTER TABLE public.funding_grants
    ADD COLUMN IF NOT EXISTS dspace_uuid UUID UNIQUE,
    ADD COLUMN IF NOT EXISTS dspace_handle VARCHAR(100) UNIQUE,
    ADD COLUMN IF NOT EXISTS sync_status sync_state_enum DEFAULT 'pending_create',
    ADD COLUMN IF NOT EXISTS last_sync_date TIMESTAMP,
    ADD COLUMN IF NOT EXISTS sync_errors TEXT;

-- Fuentes de Financiamiento (Sources)
ALTER TABLE public.funding_sources
    ADD COLUMN IF NOT EXISTS dspace_uuid UUID UNIQUE,
    ADD COLUMN IF NOT EXISTS dspace_handle VARCHAR(100) UNIQUE,
    ADD COLUMN IF NOT EXISTS sync_status sync_state_enum DEFAULT 'pending_create',
    ADD COLUMN IF NOT EXISTS last_sync_date TIMESTAMP,
    ADD COLUMN IF NOT EXISTS sync_errors TEXT;

-- Convocatorias (Calls)
ALTER TABLE public.funding_calls
    ADD COLUMN IF NOT EXISTS dspace_uuid UUID UNIQUE,
    ADD COLUMN IF NOT EXISTS dspace_handle VARCHAR(100) UNIQUE,
    ADD COLUMN IF NOT EXISTS sync_status sync_state_enum DEFAULT 'pending_create',
    ADD COLUMN IF NOT EXISTS last_sync_date TIMESTAMP,
    ADD COLUMN IF NOT EXISTS sync_errors TEXT;

-- 4. ÍNDICES DE OPTIMIZACIÓN
CREATE INDEX IF NOT EXISTS idx_persons_sync_status ON public.persons(sync_status) WHERE sync_status != 'synced';
CREATE INDEX IF NOT EXISTS idx_projects_sync_status ON public.projects(sync_status) WHERE sync_status != 'synced';
CREATE INDEX IF NOT EXISTS idx_orgs_sync_status ON public.organizations(sync_status) WHERE sync_status != 'synced';

CREATE INDEX IF NOT EXISTS idx_persons_dspace_uuid ON public.persons(dspace_uuid);
CREATE INDEX IF NOT EXISTS idx_projects_dspace_uuid ON public.projects(dspace_uuid);
CREATE INDEX IF NOT EXISTS idx_orgs_dspace_uuid ON public.organizations(dspace_uuid);

-- FIN DEL SCRIPT