-- PostgreSQL baseline for the future production adapter.
-- This migration is NOT automatically applied by the current SQLite application.
BEGIN;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE IF NOT EXISTS companies (
  id UUID PRIMARY KEY, name VARCHAR(120) NOT NULL, username VARCHAR(60) UNIQUE NOT NULL,
  password_hash TEXT NOT NULL, activation_code_hash TEXT, activation_expires_at TIMESTAMPTZ,
  activation_used_at TIMESTAMPTZ, status VARCHAR(16) NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','active','blocked')),
  province VARCHAR(80) NOT NULL DEFAULT '', district VARCHAR(80) NOT NULL DEFAULT '',
  business_sector VARCHAR(100) NOT NULL DEFAULT '', registration_number VARCHAR(100) NOT NULL DEFAULT '',
  tax_number VARCHAR(100) NOT NULL DEFAULT '', company_size VARCHAR(16) NOT NULL DEFAULT 'micro',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_companies_status_created ON companies(status,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_companies_geo ON companies(province,district);
CREATE TABLE IF NOT EXISTS platform_admins (
  id UUID PRIMARY KEY, username VARCHAR(80) UNIQUE NOT NULL, password_hash TEXT NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE, mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS departments (
  id UUID PRIMARY KEY, company_id UUID NOT NULL REFERENCES companies(id), name VARCHAR(100) NOT NULL,
  description VARCHAR(500) NOT NULL DEFAULT '', created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(company_id,name), UNIQUE(company_id,id)
);
CREATE TABLE IF NOT EXISTS employees (
  id UUID PRIMARY KEY, company_id UUID NOT NULL REFERENCES companies(id), department_id UUID,
  full_name VARCHAR(160) NOT NULL, email VARCHAR(254) NOT NULL, role VARCHAR(32) NOT NULL,
  password_hash TEXT NOT NULL, active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(company_id,email),
  FOREIGN KEY(company_id,department_id) REFERENCES departments(company_id,id)
);
CREATE INDEX IF NOT EXISTS idx_employees_company_role ON employees(company_id,role,active);
CREATE TABLE IF NOT EXISTS role_permissions (
  id UUID PRIMARY KEY, company_id UUID NOT NULL REFERENCES companies(id), role VARCHAR(32) NOT NULL,
  permission VARCHAR(80) NOT NULL, granted BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(company_id,role,permission)
);
CREATE TABLE IF NOT EXISTS company_branches (
  id UUID PRIMARY KEY, company_id UUID NOT NULL REFERENCES companies(id), name VARCHAR(120) NOT NULL,
  province VARCHAR(80) NOT NULL DEFAULT '', district VARCHAR(80) NOT NULL DEFAULT '',
  address VARCHAR(240) NOT NULL DEFAULT '', active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), UNIQUE(company_id,name), UNIQUE(company_id,id)
);
CREATE TABLE IF NOT EXISTS transactions (
  id UUID NOT NULL, company_id UUID NOT NULL REFERENCES companies(id), kind VARCHAR(16) NOT NULL
    CHECK(kind IN ('receita','despesa')), category VARCHAR(80) NOT NULL, description VARCHAR(240) NOT NULL,
  amount_cents BIGINT NOT NULL CHECK(amount_cents > 0), occurred_at TIMESTAMPTZ NOT NULL,
  source VARCHAR(20) NOT NULL DEFAULT 'online', synced BOOLEAN NOT NULL DEFAULT TRUE,
  created_by VARCHAR(160), device_id VARCHAR(128), PRIMARY KEY(company_id,id)
);
CREATE INDEX IF NOT EXISTS idx_transactions_tenant_date ON transactions(company_id,occurred_at DESC);
CREATE TABLE IF NOT EXISTS activation_devices (
  device_id VARCHAR(128) PRIMARY KEY, company_id UUID NOT NULL REFERENCES companies(id),
  token_hash CHAR(64) NOT NULL, activated_at TIMESTAMPTZ NOT NULL DEFAULT now(), revoked_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_devices_company_active ON activation_devices(company_id,revoked_at);
CREATE TABLE IF NOT EXISTS audit_log (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, company_id UUID NOT NULL REFERENCES companies(id),
  actor VARCHAR(160) NOT NULL, action VARCHAR(100) NOT NULL, object_id VARCHAR(128),
  detail VARCHAR(500) NOT NULL DEFAULT '', created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_tenant_created ON audit_log(company_id,created_at DESC);
COMMIT;
