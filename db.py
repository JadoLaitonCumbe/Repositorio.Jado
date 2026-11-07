import os
import sqlite3
from pathlib import Path

DB_PATH = os.getenv("DATABASE_PATH", "./business_hybrid.db")


def connect():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS companies (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, activation_code_hash TEXT,
            activation_expires_at TEXT, activation_used_at TEXT,
            status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id TEXT NOT NULL, company_id TEXT NOT NULL, kind TEXT NOT NULL,
            category TEXT NOT NULL, description TEXT NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
            occurred_at TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'online',
            synced INTEGER NOT NULL DEFAULT 1, created_by TEXT, device_id TEXT,
            PRIMARY KEY(company_id, id), FOREIGN KEY(company_id) REFERENCES companies(id)
        );
        CREATE INDEX IF NOT EXISTS idx_transactions_company_date ON transactions(company_id, occurred_at);
        CREATE TABLE IF NOT EXISTS activation_devices (
            device_id TEXT PRIMARY KEY, company_id TEXT NOT NULL, token_hash TEXT NOT NULL,
            activated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, revoked_at TEXT,
            FOREIGN KEY(company_id) REFERENCES companies(id)
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, company_id TEXT NOT NULL, actor TEXT NOT NULL,
            action TEXT NOT NULL, object_id TEXT, detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, FOREIGN KEY(company_id) REFERENCES companies(id)
        );
        CREATE TABLE IF NOT EXISTS auth_attempts (
            key TEXT PRIMARY KEY, attempts INTEGER NOT NULL, window_start REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS platform_admins (
            id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS departments (
            id TEXT PRIMARY KEY, company_id TEXT NOT NULL, name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(company_id,name), FOREIGN KEY(company_id) REFERENCES companies(id)
        );
        CREATE TABLE IF NOT EXISTS employees (
            id TEXT PRIMARY KEY, company_id TEXT NOT NULL, department_id TEXT,
            full_name TEXT NOT NULL, email TEXT NOT NULL, role TEXT NOT NULL,
            password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(company_id,email), FOREIGN KEY(company_id) REFERENCES companies(id),
            FOREIGN KEY(department_id) REFERENCES departments(id)
        );
        CREATE TABLE IF NOT EXISTS strategic_plans (
            id TEXT PRIMARY KEY, company_id TEXT NOT NULL, title TEXT NOT NULL,
            mission TEXT NOT NULL DEFAULT '', vision TEXT NOT NULL DEFAULT '',
            objective TEXT NOT NULL, metric TEXT NOT NULL DEFAULT '', target_value REAL,
            horizon TEXT NOT NULL, due_date TEXT, status TEXT NOT NULL DEFAULT 'planned',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(company_id) REFERENCES companies(id)
        );
        CREATE TABLE IF NOT EXISTS finance_accounts (
            id TEXT PRIMARY KEY, company_id TEXT NOT NULL, name TEXT NOT NULL,
            account_type TEXT NOT NULL, opening_balance_cents INTEGER NOT NULL DEFAULT 0,
            UNIQUE(company_id,name), FOREIGN KEY(company_id) REFERENCES companies(id)
        );
        CREATE TABLE IF NOT EXISTS cash_sessions (
            id TEXT PRIMARY KEY, company_id TEXT NOT NULL, opened_by TEXT NOT NULL,
            opening_cents INTEGER NOT NULL DEFAULT 0, closing_cents INTEGER,
            opened_at TEXT NOT NULL, closed_at TEXT, status TEXT NOT NULL DEFAULT 'open',
            FOREIGN KEY(company_id) REFERENCES companies(id)
        );
        CREATE TABLE IF NOT EXISTS finance_documents (
            id TEXT PRIMARY KEY, company_id TEXT NOT NULL, doc_type TEXT NOT NULL,
            counterparty TEXT NOT NULL, description TEXT NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
            due_date TEXT, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL,
            FOREIGN KEY(company_id) REFERENCES companies(id)
        );
        CREATE TABLE IF NOT EXISTS customers (
            id TEXT PRIMARY KEY, company_id TEXT NOT NULL, name TEXT NOT NULL,
            email TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(company_id) REFERENCES companies(id)
        );
        CREATE TABLE IF NOT EXISTS suppliers (
            id TEXT PRIMARY KEY, company_id TEXT NOT NULL, name TEXT NOT NULL,
            email TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(company_id) REFERENCES companies(id)
        );
        CREATE TABLE IF NOT EXISTS products (
            id TEXT PRIMARY KEY, company_id TEXT NOT NULL, sku TEXT NOT NULL,
            name TEXT NOT NULL, unit TEXT NOT NULL DEFAULT 'un', quantity REAL NOT NULL DEFAULT 0,
            min_quantity REAL NOT NULL DEFAULT 0, cost_cents INTEGER NOT NULL DEFAULT 0,
            price_cents INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1,
            UNIQUE(company_id,sku), FOREIGN KEY(company_id) REFERENCES companies(id)
        );
        CREATE TABLE IF NOT EXISTS stock_movements (
            id TEXT PRIMARY KEY, company_id TEXT NOT NULL, product_id TEXT NOT NULL,
            movement_type TEXT NOT NULL, quantity REAL NOT NULL, reason TEXT NOT NULL,
            created_at TEXT NOT NULL, created_by TEXT NOT NULL,
            FOREIGN KEY(company_id) REFERENCES companies(id), FOREIGN KEY(product_id) REFERENCES products(id)
        );
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY, company_id TEXT NOT NULL, title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '', owner TEXT NOT NULL DEFAULT '',
            due_date TEXT, status TEXT NOT NULL DEFAULT 'planned',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(company_id) REFERENCES companies(id)
        );
        CREATE TABLE IF NOT EXISTS sync_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, company_id TEXT NOT NULL,
            entity TEXT NOT NULL, entity_id TEXT NOT NULL, operation TEXT NOT NULL,
            payload TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY(company_id) REFERENCES companies(id)
        );
        CREATE INDEX IF NOT EXISTS idx_sync_changes_company_id ON sync_changes(company_id,id);
        CREATE TABLE IF NOT EXISTS role_permissions (
            id TEXT PRIMARY KEY, company_id TEXT NOT NULL, role TEXT NOT NULL,
            permission TEXT NOT NULL, granted INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(company_id, role, permission), FOREIGN KEY(company_id) REFERENCES companies(id)
        );
        CREATE TABLE IF NOT EXISTS company_branches (
            id TEXT PRIMARY KEY, company_id TEXT NOT NULL, name TEXT NOT NULL,
            province TEXT NOT NULL DEFAULT '', district TEXT NOT NULL DEFAULT '',
            address TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(company_id) REFERENCES companies(id), UNIQUE(company_id,name)
        );
        CREATE TABLE IF NOT EXISTS platform_admin_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id TEXT NOT NULL,
            action TEXT NOT NULL, target_type TEXT NOT NULL, target_id TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_companies_status_created ON companies(status,created_at);
        CREATE INDEX IF NOT EXISTS idx_employees_company_role ON employees(company_id,role,active);
        CREATE INDEX IF NOT EXISTS idx_audit_company_created ON audit_log(company_id,created_at);
        """)
        # Backward-compatible national directory metadata for companies.
        company_cols = {r["name"] for r in db.execute("PRAGMA table_info(companies)").fetchall()}
        for col, ddl in {
            "province": "TEXT NOT NULL DEFAULT ''",
            "district": "TEXT NOT NULL DEFAULT ''",
            "business_sector": "TEXT NOT NULL DEFAULT ''",
            "registration_number": "TEXT NOT NULL DEFAULT ''",
            "tax_number": "TEXT NOT NULL DEFAULT ''",
            "company_size": "TEXT NOT NULL DEFAULT 'micro'",
        }.items():
            if col not in company_cols:
                db.execute(f"ALTER TABLE companies ADD COLUMN {col} {ddl}")
        # Migrate databases created by the previous MVP version.
        company_cols = {r["name"] for r in db.execute("PRAGMA table_info(companies)").fetchall()}
        if "status" not in company_cols:
            db.execute("ALTER TABLE companies ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
        if "activation_code" in company_cols and "activation_code_hash" not in company_cols:
            db.execute("ALTER TABLE companies ADD COLUMN activation_code_hash TEXT")
            db.execute("ALTER TABLE companies ADD COLUMN activation_expires_at TEXT")
            db.execute("ALTER TABLE companies ADD COLUMN activation_used_at TEXT")
            # Legacy plaintext codes are intentionally invalidated; keep only a non-secret tombstone
            # because old schemas declared activation_code NOT NULL.
            db.execute("UPDATE companies SET activation_code='INVALIDATED-' || id, activation_code_hash=NULL, activation_expires_at=NULL, activation_used_at=NULL")
        elif "activation_code" in company_cols:
            # Finish migration safely if a previous deployment added the hash columns but retained plaintext codes.
            db.execute("UPDATE companies SET activation_code='INVALIDATED-' || id WHERE activation_code_hash IS NULL OR activation_code_hash=''")
        tx_cols = {r["name"] for r in db.execute("PRAGMA table_info(transactions)").fetchall()}
        pk_cols = [r["name"] for r in db.execute("PRAGMA table_info(transactions)").fetchall() if r["pk"]]
        if pk_cols == ["id"]:
            db.execute("ALTER TABLE transactions RENAME TO transactions_legacy")
            db.executescript("""
            CREATE TABLE transactions (
                id TEXT NOT NULL, company_id TEXT NOT NULL, kind TEXT NOT NULL,
                category TEXT NOT NULL, description TEXT NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
                occurred_at TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'online', synced INTEGER NOT NULL DEFAULT 1,
                created_by TEXT, device_id TEXT, PRIMARY KEY(company_id,id), FOREIGN KEY(company_id) REFERENCES companies(id)
            );
            INSERT OR IGNORE INTO transactions(id,company_id,kind,category,description,amount_cents,occurred_at,source,synced)
              SELECT id,company_id,kind,category,description,amount_cents,occurred_at,source,synced FROM transactions_legacy;
            DROP TABLE transactions_legacy;
            CREATE INDEX IF NOT EXISTS idx_transactions_company_date ON transactions(company_id, occurred_at);
            """)
        device_cols = {r["name"] for r in db.execute("PRAGMA table_info(activation_devices)").fetchall()}
        if "token_hash" not in device_cols:
            db.execute("ALTER TABLE activation_devices ADD COLUMN token_hash TEXT NOT NULL DEFAULT ''")
            db.execute("ALTER TABLE activation_devices ADD COLUMN revoked_at TEXT")
            db.execute("UPDATE activation_devices SET revoked_at=CURRENT_TIMESTAMP WHERE token_hash='' ")
