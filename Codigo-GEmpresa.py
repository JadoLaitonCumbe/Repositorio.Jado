#GEmpresa-JLC
#CÓDIGO-FONTE — VERSÃO 1.0.0
#JLC-tech
 
gempresa_jlc/requirements.txt
gempresa_jlc/deploy/docker-compose.infrastructure.yml
gempresa_jlc/run_gempresa_jlc.bat
gempresa_jlc/tests/test_smoke.py
gempresa_jlc/scripts/backup_sqlite_encrypted.py
gempresa_jlc/scripts/restore_sqlite_encrypted.py
gempresa_jlc/scripts/backup_sqlite.py
gempresa_jlc/scripts/load_test.py
gempresa_jlc/run_gempresa_jlc.sh
gempresa_jlc/migrations/postgresql/001_core.sql
gempresa_jlc/desktop_client.py
gempresa_jlc/requirements-r2.txt
gempresa_jlc/.env.example
gempresa_jlc/app/__init__.py
gempresa_jlc/app/main.py
gempresa_jlc/app/templates/permissions.html
gempresa_jlc/app/templates/login.html
gempresa_jlc/app/templates/base.html
gempresa_jlc/app/templates/register.html
gempresa_jlc/app/templates/activation.html
gempresa_jlc/app/templates/platform_admin.html
gempresa_jlc/app/templates/dashboard.html
gempresa_jlc/app/security.py
gempresa_jlc/app/db.py
gempresa_jlc/app/static/style.css
gempresa_jlc/app/product.py
 
fastapi>=0.115,<1.0
uvicorn[standard]>=0.30,<1.0
jinja2>=3.1,<4.0
python-multipart>=0.0.9
itsdangerous>=2.2
pytest>=8.0
httpx>=0.27
keyring>=25.0,<26.0
openpyxl>=3.1,<4.0
reportlab>=4.2,<5.0
 
 
# Infrastructure reference only. The current FastAPI app still uses SQLite and
# must be migrated to the PostgreSQL adapter before connecting it to this stack.
services:
  postgres:
    image: postgres:16
    restart: unless-stopped
    environment:
      POSTGRES_DB: gempresa_jlc
      POSTGRES_USER: gempresa_jlc
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set a strong password in .env}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U gempresa_jlc -d gempresa_jlc"]
      interval: 10s
      timeout: 5s
      retries: 10
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: ["redis-server", "--appendonly", "yes", "--requirepass", "${REDIS_PASSWORD:?set a strong password in .env}"]
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 10s
      timeout: 5s
      retries: 10
volumes:
  postgres_data:
  redis_data:
 
import os
import tempfile
import re
import json
import uuid
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from datetime import datetime, timezone
from fastapi.testclient import TestClient
 
_fd, _db_path = tempfile.mkstemp(suffix=".db")
os.environ["DATABASE_PATH"] = _db_path
os.environ["APP_SECRET_KEY"] = "test-secret-key-for-tests-only-123456789-abcdef"
os.environ["APP_MODE"] = "development"
os.environ["ADMIN_USERNAME"] = "platform_admin"
os.environ["ADMIN_PASSWORD"] = "PlatformAdmin-Test-Password-2026!"
from app.main import app, _RATE
 
 
def csrf(html):
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "CSRF token not present in form"
    return match.group(1)
 
 
def register_company(client, name="Empresa Teste", username=None):
    _RATE.clear()  # isolate test cases; rate-limit behavior is not under test here
    username = username or ("empresa_" + uuid.uuid4().hex[:10])
    page = client.get("/registo")
    response = client.post("/registo", data={
        "csrf_token": csrf(page.text), "company_name": name, "username": username,
        "password": "SenhaMuitoForte123!"
    })
    assert response.status_code == 200, response.text
    code_match = re.search(r"ATJ-[A-F0-9]+-[A-F0-9]+", response.text)
    assert code_match, response.text
    # Company accounts remain pending until the platform administrator approves them.
    admin_login = client.post("/api/admin/login", json={"username":"platform_admin", "password":"PlatformAdmin-Test-Password-2026!"})
    assert admin_login.status_code == 200, admin_login.text
    companies = client.get("/api/admin/companies").json()["companies"]
    company = next(item for item in companies if item["username"] == username)
    approved = client.post(f"/api/admin/companies/{company['id']}/status", json={"status":"active"})
    assert approved.status_code == 200, approved.text
    page = client.get("/")
    logged = client.post("/login", data={"csrf_token":csrf(page.text), "username":username, "password":"SenhaMuitoForte123!"})
    assert logged.status_code in (200, 303) and "Olá," in logged.text, logged.text
    return code_match.group(0)
 
 
def test_home_and_health():
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/").status_code == 200
        assert client.get("/health").json()["status"] == "ok"
        assert client.get("/").headers["x-frame-options"] == "DENY"
 
 
def test_company_registration_and_dashboard_and_csrf():
    with TestClient(app, base_url="http://localhost") as client:
        register_company(client)
        dashboard = client.get("/dashboard")
        assert dashboard.status_code == 200
        assert "Empresa Teste" in dashboard.text
        # Missing CSRF token must be rejected.
        bad = client.post("/financeiro/movimento", data={"kind":"receita","category":"Vendas","description":"Venda","amount":"10,00"})
        assert bad.status_code == 422 or bad.status_code == 403
 
 
def test_activation_is_one_time_and_sync_requires_bearer_token():
    with TestClient(app, base_url="http://localhost") as client:
        code = register_company(client)
        device_id = str(uuid.uuid4())
        activated = client.post("/api/device/activate", json={"activation_code": code, "device_id": device_id})
        assert activated.status_code == 200, activated.text
        data = activated.json()
        assert data["device_token"]
        second_device = client.post("/api/device/activate", json={"activation_code": code, "device_id": str(uuid.uuid4())})
        assert second_device.status_code == 403
        event = {"event_id": str(uuid.uuid4()), "kind":"receita", "category":"Vendas", "description":"Venda offline", "amount_cents": 12550, "occurred_at": datetime.now(timezone.utc).isoformat()}
        denied = client.post("/api/sync/push", json={"device_id":device_id,"events":[event]})
        assert denied.status_code == 401
        result = client.post("/api/sync/push", headers={"Authorization":"Bearer "+data["device_token"]}, json={"device_id":device_id,"events":[event]})
        assert result.status_code == 200, result.text
        assert result.json()["created"] == [event["event_id"]]
        again = client.post("/api/sync/push", headers={"Authorization":"Bearer "+data["device_token"]}, json={"device_id":device_id,"events":[event]})
        assert again.json()["duplicate"] == [event["event_id"]]
        conflict_event = dict(event, amount_cents=99999)
        conflict = client.post("/api/sync/push", headers={"Authorization":"Bearer "+data["device_token"]}, json={"device_id":device_id,"events":[conflict_event]})
        assert conflict.json()["conflicts"][0]["event_id"] == event["event_id"]
 
 
def test_sync_rejects_non_finite_amount_without_rolling_back_other_events():
    with TestClient(app, base_url="http://localhost") as client:
        code = register_company(client, "Empresa Finita", "empresa_finita")
        device_id = str(uuid.uuid4())
        activated = client.post("/api/device/activate", json={"activation_code":code,"device_id":device_id}).json()
        good = {"event_id":str(uuid.uuid4()),"kind":"despesa","category":"Renda","description":"Aluguer","amount_cents":12000,"occurred_at":datetime.now(timezone.utc).isoformat()}
        bad = {"event_id":str(uuid.uuid4()),"kind":"receita","category":"Vendas","description":"Infinito","amount_cents":float("inf"),"occurred_at":datetime.now(timezone.utc).isoformat()}
        response = client.post("/api/sync/push", headers={"Authorization":"Bearer "+activated["device_token"], "Content-Type":"application/json"}, content=json.dumps({"device_id":device_id,"events":[bad,good]}, allow_nan=True))
        assert response.status_code == 200, response.text
        assert len(response.json()["created"]) == 1
        assert len(response.json()["rejected"]) == 1
 
 
def test_money_validation_and_tenant_isolation():
    from app.main import validate_amount
    assert validate_amount("1.005") == 101
    assert validate_amount("0,285") == 29
    for value in ("inf", "Infinity", "1e400", "1.234,56"):
        try:
            validate_amount(value)
            assert False, f"should reject {value}"
        except ValueError:
            pass
    with TestClient(app, base_url="http://localhost") as client_a, TestClient(app, base_url="http://localhost") as client_b:
        # Tenant isolation: company B cannot see company A's dashboard without its own session.
        register_company(client_a, "Empresa A", "empresa_a")
        assert client_b.get("/dashboard").status_code == 401
 
 
def test_device_cannot_be_reassigned_to_another_company():
    with TestClient(app, base_url="http://localhost") as client:
        code_a = register_company(client, "Empresa A", "empresa_a_reassign")
        device_id = str(uuid.uuid4())
        first = client.post("/api/device/activate", json={"activation_code":code_a,"device_id":device_id})
        assert first.status_code == 200
        code_b = register_company(client, "Empresa B", "empresa_b_reassign")
        attempt = client.post("/api/device/activate", json={"activation_code":code_b,"device_id":device_id})
        assert attempt.status_code == 409
 
 
def test_sync_idempotency_is_scoped_to_company():
    with TestClient(app, base_url="http://localhost") as client:
        code_a = register_company(client, "Tenant A", "tenant_a_scope")
        dev_a = str(uuid.uuid4())
        token_a = client.post("/api/device/activate", json={"activation_code":code_a,"device_id":dev_a}).json()["device_token"]
        code_b = register_company(client, "Tenant B", "tenant_b_scope")
        dev_b = str(uuid.uuid4())
        token_b = client.post("/api/device/activate", json={"activation_code":code_b,"device_id":dev_b}).json()["device_token"]
        shared_event_id = str(uuid.uuid4())
        event_a = {"event_id":shared_event_id,"kind":"receita","category":"Vendas","description":"A","amount_cents":100,"occurred_at":datetime.now(timezone.utc).isoformat()}
        event_b = dict(event_a, description="B", amount_cents=200)
        res_a = client.post("/api/sync/push", headers={"Authorization":"Bearer "+token_a}, json={"device_id":dev_a,"events":[event_a]})
        res_b = client.post("/api/sync/push", headers={"Authorization":"Bearer "+token_b}, json={"device_id":dev_b,"events":[event_b]})
        assert res_a.json()["created"] == [shared_event_id]
        assert res_b.json()["created"] == [shared_event_id]
 
 
def test_device_revocation_blocks_sync_and_company_isolation_for_devices():
    with TestClient(app, base_url="http://localhost") as client:
        code = register_company(client, "Empresa Revogação", "empresa_revogacao")
        device_id = str(uuid.uuid4())
        activation = client.post("/api/device/activate", json={"activation_code":code,"device_id":device_id}).json()
        listed = client.get("/api/devices")
        assert listed.status_code == 200 and any(d["device_id"] == device_id for d in listed.json()["devices"])
        revoked = client.post(f"/api/devices/{device_id}/revoke")
        assert revoked.status_code == 200
        denied = client.get(f"/api/sync/pull?device_id={device_id}", headers={"Authorization":"Bearer "+activation["device_token"]})
        assert denied.status_code == 403
 
 
def test_admin_can_block_company_and_login_is_denied():
    with TestClient(app, base_url="http://localhost") as client:
        page = client.get("/registo")
        username = "empresa_bloqueada"
        response = client.post("/registo", data={"csrf_token":csrf(page.text),"company_name":"Empresa Bloqueada","username":username,"password":"SenhaMuitoForte123!"})
        assert response.status_code == 200
        client.post("/api/admin/login", json={"username":"platform_admin","password":"PlatformAdmin-Test-Password-2026!"})
        company = next(c for c in client.get("/api/admin/companies").json()["companies"] if c["username"] == username)
        assert client.post(f"/api/admin/companies/{company['id']}/status", json={"status":"blocked"}).status_code == 200
        page = client.get("/")
        denied = client.post("/login", data={"csrf_token":csrf(page.text),"username":username,"password":"SenhaMuitoForte123!"})
        assert denied.status_code == 403
 
 
def test_company_erp_foundations_and_finance_exports():
    with TestClient(app, base_url="http://localhost") as client:
        register_company(client, "Empresa ERP", "empresa_erp")
        dep = client.post("/api/departments", json={"name":"Financeiro"})
        assert dep.status_code == 200, dep.text
        employee = client.post("/api/employees", json={"full_name":"Ana Financeira","email":"ana@erp.test","role":"finance","password":"SenhaFinanceira123!","department_id":dep.json()["id"]})
        assert employee.status_code == 200, employee.text
        plan = client.post("/api/strategy/plans", json={"title":"Plano anual","objective":"Aumentar vendas","horizon":"medium","metric":"Receita","target_value":100000})
        assert plan.status_code == 200
        doc = client.post("/api/finance/documents", json={"doc_type":"payable","counterparty":"Fornecedor A","description":"Compra de mercadoria","amount_cents":50000})
        assert doc.status_code == 200
        customer = client.post("/api/customers", json={"name":"Cliente A"})
        assert customer.status_code == 200
        product = client.post("/api/products", json={"sku":"SKU-1","name":"Produto 1","quantity":10,"min_quantity":2,"cost_cents":1000,"price_cents":1500})
        assert product.status_code == 200
        project = client.post("/api/projects", json={"title":"Expansão"})
        assert project.status_code == 200
        assert client.get("/reports/finance.xlsx").status_code == 200
        assert client.get("/reports/finance.pdf").status_code == 200
 
 
def test_employee_role_restriction_on_strategy_and_finance():
    with TestClient(app, base_url="http://localhost") as client:
        register_company(client, "Empresa Perfis", "empresa_perfis")
        employee = client.post("/api/employees", json={"full_name":"Vendedor","email":"vendedor@perfil.test","role":"sales","password":"SenhaVendedor123!"})
        assert employee.status_code == 200
        login = client.post("/api/employee/login", json={"email":"vendedor@perfil.test","password":"SenhaVendedor123!","company_username":"empresa_perfis"})
        assert login.status_code == 200
        denied = client.post("/api/strategy/plans", json={"title":"Plano","objective":"Meta","horizon":"short"})
        assert denied.status_code == 403
 
 
def test_activation_code_is_consumed_atomically_under_concurrency():
    from concurrent.futures import ThreadPoolExecutor
    with TestClient(app, base_url="http://localhost") as owner:
        code = register_company(owner, "Empresa Concorrência", "empresa_concorrencia")
    def attempt(_):
        with TestClient(app, base_url="http://localhost") as client:
            return client.post("/api/device/activate", json={"activation_code":code,"device_id":str(uuid.uuid4())}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(attempt, range(2)))
    assert sorted(statuses) == [200, 403]
 
 
def test_sync_pull_delivers_online_financial_changes():
    with TestClient(app, base_url="http://localhost") as client:
        code = register_company(client, "Empresa Pull", "empresa_pull")
        device = str(uuid.uuid4())
        activated = client.post("/api/device/activate", json={"activation_code":code,"device_id":device}).json()
        page = client.get("/dashboard")
        token = csrf(page.text)
        posted = client.post("/financeiro/movimento", data={"csrf_token":token,"kind":"receita","category":"Vendas","description":"Venda online","amount":"50,00"})
        assert posted.status_code in (200,303)
        pulled = client.get(f"/api/sync/pull?device_id={device}&after_id=0", headers={"Authorization":"Bearer "+activated["device_token"]})
        assert pulled.status_code == 200
        assert any(change["entity"] == "transaction" and "Venda online" in change["payload"] for change in pulled.json()["changes"])
 
 
def test_revoked_device_can_be_reactivated_by_same_company_with_new_code():
    with TestClient(app, base_url="http://localhost") as client:
        code = register_company(client, "Empresa Reativação", "empresa_reativacao")
        device_id = str(uuid.uuid4())
        first = client.post("/api/device/activate", json={"activation_code":code,"device_id":device_id})
        assert first.status_code == 200
        assert client.post(f"/api/devices/{device_id}/revoke").status_code == 200
        page = client.get("/dashboard")
        renewed = client.post("/ativacao/novo", data={"csrf_token":csrf(page.text)})
        new_code_match = re.search(r"ATJ-[A-F0-9]+-[A-F0-9]+", renewed.text)
        assert new_code_match
        second = client.post("/api/device/activate", json={"activation_code":new_code_match.group(0),"device_id":device_id})
        assert second.status_code == 200, second.text
        assert second.json()["device_token"] != first.json()["device_token"]
 
 
def test_blocked_company_existing_session_is_denied_and_tenant_records_are_isolated():
    with TestClient(app, base_url="http://localhost") as company_a, TestClient(app, base_url="http://localhost") as company_b, TestClient(app, base_url="http://localhost") as admin:
        register_company(company_a, "Empresa Isolada A", "empresa_isolada_a")
        register_company(company_b, "Empresa Isolada B", "empresa_isolada_b")
        company_a.post("/api/departments", json={"name":"Apenas A"})
        assert company_b.get("/api/departments").json()["departments"] == []
        admin.post("/api/admin/login", json={"username":"platform_admin","password":"PlatformAdmin-Test-Password-2026!"})
        companies = admin.get("/api/admin/companies").json()["companies"]
        a = next(c for c in companies if c["username"] == "empresa_isolada_a")
        admin.post(f"/api/admin/companies/{a['id']}/status", json={"status":"blocked"})
        assert company_a.get("/api/departments").status_code == 403
 
 
def test_platform_admin_dashboard_overview_and_company_directory_filters():
    with TestClient(app, base_url="http://localhost") as client:
        page = client.get("/admin")
        assert page.status_code == 200 and "Administrador Geral" in page.text
        login = client.post("/api/admin/login", json={"username":"platform_admin", "password":"PlatformAdmin-Test-Password-2026!"})
        assert login.status_code == 200
        overview = client.get("/api/admin/overview")
        assert overview.status_code == 200
        assert "companies" in overview.json() and "companies_by_province" in overview.json()
        directory = client.get("/api/admin/companies?page=1&page_size=10")
        assert directory.status_code == 200 and directory.json()["page_size"] == 10
 
 
def test_company_registration_stores_national_location_metadata():
    with TestClient(app, base_url="http://localhost") as client:
        page = client.get("/registo")
        response = client.post("/registo", data={
            "csrf_token": csrf(page.text), "company_name":"Empresa Nacional", "username":"empresa_nacional",
            "password":"SenhaMuitoForte123!", "province":"Sofala", "district":"Beira",
            "business_sector":"Comércio", "company_size":"small"
        })
        assert response.status_code == 200
        client.post("/api/admin/login", json={"username":"platform_admin", "password":"PlatformAdmin-Test-Password-2026!"})
        company = next(x for x in client.get("/api/admin/companies?q=empresa_nacional").json()["companies"] if x["username"] == "empresa_nacional")
        assert company["province"] == "Sofala" and company["district"] == "Beira"
 
 
def test_company_role_permission_override_is_enforced():
    with TestClient(app, base_url="http://localhost") as owner, TestClient(app, base_url="http://localhost") as employee:
        register_company(owner, "Empresa RBAC", "empresa_rbac")
        created = owner.post("/api/employees", json={"full_name":"Vendedor RBAC", "email":"rbac@empresa.test", "role":"sales", "password":"SenhaVendedor123!"})
        assert created.status_code == 200
        permissions_page = owner.get("/empresa/permissoes")
        assert permissions_page.status_code == 200 and "Perfis e permissões" in permissions_page.text
        csrf_token = csrf(owner.get("/dashboard").text)
        denied_override = owner.post("/api/permissions/roles", headers={"X-CSRF-Token":csrf_token}, json={"role":"sales", "permission":"crm.manage", "granted":False})
        assert denied_override.status_code == 200
        login = employee.post("/api/employee/login", json={"email":"rbac@empresa.test", "password":"SenhaVendedor123!", "company_username":"empresa_rbac"})
        assert login.status_code == 200
        # CRM write is denied after the owner explicitly removes this permission.
        assert employee.post("/api/customers", json={"name":"Cliente sem permissão"}).status_code == 403
        assert employee.get("/api/permissions/roles").status_code == 403
 
 
def test_national_branch_records_are_company_scoped():
    with TestClient(app, base_url="http://localhost") as a, TestClient(app, base_url="http://localhost") as b:
        register_company(a, "Empresa com Filiais", "empresa_filiais")
        created = a.post("/api/branches", json={"name":"Filial Beira", "province":"Sofala", "district":"Beira"})
        assert created.status_code == 200
        assert len(a.get("/api/branches").json()["branches"]) == 1
        assert b.get("/api/branches").status_code == 401
 
 
def test_readiness_probe_and_admin_login_form():
    with TestClient(app, base_url="http://localhost") as client:
        ready = client.get("/ready")
        assert ready.status_code == 200 and ready.json()["ready"] is True
        page = client.get("/admin")
        login = client.post("/admin/login", data={"csrf_token":csrf(page.text), "username":"platform_admin", "password":"PlatformAdmin-Test-Password-2026!"})
        assert login.status_code == 200 and "Centro de Administração Geral" in login.text
        panel = client.get("/admin")
        assert panel.status_code == 200 and "Centro de Administração Geral" in panel.text
 
 
def test_platform_admin_audit_records_company_state_changes():
    with TestClient(app, base_url="http://localhost") as client:
        register_company(client, "Empresa Auditoria Admin", "empresa_audit_admin")
        client.post("/api/admin/login", json={"username":"platform_admin", "password":"PlatformAdmin-Test-Password-2026!"})
        companies = client.get("/api/admin/companies?q=empresa_audit_admin").json()["companies"]
        company = companies[0]
        changed = client.post(f"/api/admin/companies/{company['id']}/status", json={"status":"blocked"})
        assert changed.status_code == 200
        events = client.get("/api/admin/audit").json()["events"]
        assert any(x["action"] == "company.status_changed" and x["target_id"] == company["id"] for x in events)
 
 
def test_production_rate_limit_requires_redis(monkeypatch):
    from fastapi import HTTPException
    from app.main import rate_limit
    monkeypatch.setenv("APP_MODE", "production")
    monkeypatch.delenv("REDIS_URL", raising=False)
    try:
        rate_limit("production-no-redis", 5, 60)
        assert False, "production must fail closed without Redis"
    except HTTPException as exc:
        assert exc.status_code == 503
    finally:
        monkeypatch.setenv("APP_MODE", "development")
 
 
def test_product_identity():
    with TestClient(app, base_url="http://localhost") as client:
        product = client.get("/api/product")
        assert product.status_code == 200
        data = product.json()
        assert data["name"] == "GEmpresa-JLC"
        assert data["brand"] == "JLC-tech"
        assert data["version"] == app.version
 
 
"""Create an encrypted, consistent SQLite backup. Set BACKUP_ENCRYPTION_KEY to a Fernet key."""
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from cryptography.fernet import Fernet
 
source = Path(os.getenv("DATABASE_PATH", "./business_hybrid.db")).resolve()
key = os.getenv("BACKUP_ENCRYPTION_KEY", "").strip().encode("ascii")
if not key:
    raise SystemExit("Defina BACKUP_ENCRYPTION_KEY com uma chave Fernet gerada por Fernet.generate_key().")
try:
    cipher = Fernet(key)
except Exception as exc:
    raise SystemExit("BACKUP_ENCRYPTION_KEY inválida.") from exc
if not source.is_file():
    raise SystemExit(f"Base de dados não encontrada: {source}")
 
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
target = Path(sys.argv[1] if len(sys.argv) > 1 else f"backup-{stamp}.sqlite3.fernet").resolve()
tmp = target.with_suffix(target.suffix + ".tmp")
plain = target.with_suffix(target.suffix + ".plain.tmp")
try:
    with sqlite3.connect(source) as src, sqlite3.connect(plain) as dst:
        src.backup(dst)
    encrypted = cipher.encrypt(plain.read_bytes())
    tmp.write_bytes(encrypted)
    os.chmod(tmp, 0o600)
    tmp.replace(target)
    print(f"Backup cifrado criado: {target}")
finally:
    plain.unlink(missing_ok=True)
    tmp.unlink(missing_ok=True)
 
 
"""Restore an encrypted SQLite backup to a new file (never overwrites an existing database)."""
import os
import sqlite3
import sys
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
 
if len(sys.argv) != 3:
    raise SystemExit("Uso: python scripts/restore_sqlite_encrypted.py BACKUP.sqlite3.fernet NOVA_BASE.sqlite3")
backup, target = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
if target.exists():
    raise SystemExit("Destino já existe. Escolha um caminho novo para evitar sobrescrever dados.")
key = os.getenv("BACKUP_ENCRYPTION_KEY", "").strip().encode("ascii")
if not key:
    raise SystemExit("Defina BACKUP_ENCRYPTION_KEY.")
try:
    plain = Fernet(key).decrypt(backup.read_bytes())
except (InvalidToken, ValueError) as exc:
    raise SystemExit("Backup inválido ou chave de cifragem incorreta.") from exc
try:
    target.write_bytes(plain)
    with sqlite3.connect(target) as db:
        result = db.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            target.unlink(missing_ok=True)
            raise SystemExit("A verificação de integridade falhou; ficheiro restaurado removido.")
    os.chmod(target, 0o600)
    print(f"Base restaurada e validada: {target}")
except Exception:
    target.unlink(missing_ok=True)
    raise
 
 
"""Create a consistent SQLite backup. Not encrypted; protect destination storage."""
import argparse
import hashlib
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
 
 
def main():
    parser = argparse.ArgumentParser(description="Backup consistente da base SQLite GEmpresa-JLC")
    parser.add_argument("--source", default=os.getenv("DATABASE_PATH", "./business_hybrid.db"))
    parser.add_argument("--dest", default="./backups")
    args = parser.parse_args()
    source = Path(args.source).resolve()
    if not source.exists():
        raise SystemExit(f"Base de dados não encontrada: {source}")
    dest_dir = Path(args.dest).resolve(); dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = dest_dir / f"business_hybrid_{stamp}.sqlite3"
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
        check = dst.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            target.unlink(missing_ok=True)
            raise SystemExit(f"Backup inválido: {check}")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (target.with_suffix(target.suffix + ".sha256")).write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    print(f"Backup criado: {target}")
    print(f"SHA-256: {digest}")
    print("AVISO: este script não cifra o backup; guarde-o num destino protegido e externo ao servidor.")
 
if __name__ == "__main__": main()
 
 
"""Basic concurrent health-endpoint smoke test; not a full business/load certification."""
import argparse
import concurrent.futures
import time
import urllib.error
import urllib.request
 
 
def check(url, timeout):
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read()
            return response.status, time.perf_counter() - start, len(body)
    except Exception:
        return 0, time.perf_counter() - start, 0
 
 
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000/health")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=5)
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1: raise SystemExit("requests e concurrency devem ser positivos")
    start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(lambda _: check(args.url, args.timeout), range(args.requests)))
    elapsed = time.perf_counter() - start
    ok = [r for r in results if r[0] == 200]
    latencies = sorted(r[1] for r in results)
    p95 = latencies[min(len(latencies)-1, int(len(latencies)*0.95))]
    print(f"Pedidos: {args.requests}; concorrência: {args.concurrency}; HTTP 200: {len(ok)}; erros: {len(results)-len(ok)}")
    print(f"Duração: {elapsed:.2f}s; throughput: {len(results)/elapsed:.2f} req/s; latência p95: {p95*1000:.1f} ms")
    if len(ok) != len(results): raise SystemExit(1)
    print("NOTA: teste limitado ao endpoint /health; não substitui testes de carga de login, sincronização, BD e fluxos financeiros.")
 
if __name__ == "__main__": main()
 
 
#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
fi
export APP_MODE="${APP_MODE:-development}"
export APP_SECRET_KEY="${APP_SECRET_KEY:-CHANGE_ME_BEFORE_PRODUCTION}"
exec .venv/bin/python -m uvicorn app.main:app --reload
 
 
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
 
 
"""Cliente offline demonstrativo para Windows/Linux/macOS (Python + Tkinter + SQLite)."""
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlparse
import sqlite3
import urllib.request
import urllib.error
import uuid
import tkinter as tk
import keyring
from tkinter import ttk, messagebox
from pathlib import Path
from datetime import datetime, timezone
 
DB = Path.home() / ".gempresa_jlc_business.db"
 
def db_connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS outbox (event_id TEXT PRIMARY KEY, kind TEXT NOT NULL, category TEXT NOT NULL, description TEXT NOT NULL, amount_cents INTEGER NOT NULL, occurred_at TEXT NOT NULL, synced INTEGER NOT NULL DEFAULT 0)")
    conn.commit()
    return conn
 
def setting(key, value=None):
    with db_connect() as db:
        if value is not None:
            db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None
 
def post_json(url, payload, token=None):
    headers = {"Content-Type": "application/json"}
    if token: headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=json.dumps(payload, allow_nan=False).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=12) as response:
        return json.loads(response.read().decode())
 
def get_json(url, token=None):
    headers = {}
    if token: headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=12) as response:
        return json.loads(response.read().decode())
 
class OfflineApp:
    def __init__(self, root):
        self.root = root
        root.title("GEmpresa-JLC | Cliente Offline")
        root.geometry("760x600")
        root.configure(bg="#f3f8f5")
        style = ttk.Style()
        style.configure("TButton", padding=8)
        tk.Label(root, text="◆ GEmpresa-JLC", bg="#f3f8f5", fg="#087f5b", font=("Segoe UI", 18, "bold")).pack(anchor="w", padx=22, pady=(18, 0))
        tk.Label(root, text="GESTÃO EMPRESARIAL • MODO OFFLINE", bg="#f3f8f5", fg="#70857d", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=24, pady=(0, 14))
        config = ttk.LabelFrame(root, text="Ligação e ativação", padding=10); config.pack(fill="x", padx=20)
        self.url = tk.StringVar(value=setting("server_url") or "http://127.0.0.1:8000")
        self.code = tk.StringVar(value="")
        ttk.Label(config, text="URL do servidor").grid(row=0,column=0,sticky="w")
        ttk.Entry(config,textvariable=self.url,width=38).grid(row=0,column=1,padx=8,sticky="ew")
        ttk.Label(config, text="Código de ativação").grid(row=1,column=0,sticky="w",pady=6)
        ttk.Entry(config,textvariable=self.code,width=38).grid(row=1,column=1,padx=8,sticky="ew")
        ttk.Button(config,text="Ativar / testar ligação",command=self.activate).grid(row=0,column=2,rowspan=2,padx=8)
        config.columnconfigure(1,weight=1)
        form = ttk.LabelFrame(root,text="Novo movimento (funciona offline)",padding=10); form.pack(fill="x",padx=20,pady=14)
        self.kind=tk.StringVar(value="receita"); self.category=tk.StringVar(value="Vendas"); self.description=tk.StringVar(); self.amount=tk.StringVar()
        ttk.Label(form,text="Tipo").grid(row=0,column=0,sticky="w"); ttk.Combobox(form,textvariable=self.kind,values=("receita","despesa"),state="readonly",width=12).grid(row=1,column=0,padx=(0,8),sticky="ew")
        ttk.Label(form,text="Categoria").grid(row=0,column=1,sticky="w"); ttk.Combobox(form,textvariable=self.category,values=("Vendas","Serviços","Salários","Renda","Transporte","Stock","Impostos","Outros"),width=16).grid(row=1,column=1,padx=8,sticky="ew")
        ttk.Label(form,text="Descrição").grid(row=0,column=2,sticky="w"); ttk.Entry(form,textvariable=self.description,width=25).grid(row=1,column=2,padx=8,sticky="ew")
        ttk.Label(form,text="Valor MZN").grid(row=0,column=3,sticky="w"); ttk.Entry(form,textvariable=self.amount,width=12).grid(row=1,column=3,padx=8,sticky="ew")
        ttk.Button(form,text="Guardar",command=self.save).grid(row=1,column=4,padx=8)
        listing=ttk.LabelFrame(root,text="Movimentos locais",padding=10); listing.pack(fill="both",expand=True,padx=20,pady=(0,10))
        self.tree=ttk.Treeview(listing,columns=("type","desc","value","status"),show="headings",height=8)
        for col,title,width in (("type","Tipo",85),("desc","Descrição",330),("value","Valor (MZN)",120),("status","Estado",100)):
            self.tree.heading(col,text=title); self.tree.column(col,width=width)
        self.tree.pack(fill="both",expand=True)
        bottom=ttk.Frame(root); bottom.pack(fill="x",padx=20,pady=(0,16))
        self.status=tk.StringVar(value="Os movimentos ficam guardados neste PC mesmo sem internet.")
        ttk.Label(bottom,textvariable=self.status).pack(side="left",fill="x",expand=True)
        ttk.Button(bottom,text="Sincronizar agora",command=self.sync).pack(side="right")
        self.refresh()
 
    def activate(self):
        base=self.url.get().strip().rstrip("/"); code=self.code.get().strip()
        if not base or not code: messagebox.showwarning("Dados em falta","Indique URL e código de ativação."); return
        parsed=urlparse(base)
        if not (parsed.scheme == "https" and parsed.hostname or parsed.scheme == "http" and parsed.hostname in {"localhost","127.0.0.1","::1"}):
            messagebox.showerror("URL insegura","Use HTTPS. HTTP só é permitido para localhost em testes."); return
        device=setting("device_id") or str(uuid.uuid4())
        try:
            result=post_json(base.rstrip("/")+"/api/device/activate",{"activation_code":code,"device_id":device})
            # Save settings only after successful validation/activation; never persist the one-time code.
            setting("server_url",base.rstrip("/")); setting("device_id",device)
            keyring.set_password("GEmpresa-JLC", device, result["device_token"])
            setting("company_id",result["company_id"]); setting("company_name",result["company_name"])
            self.code.set("")
            self.status.set("Ativado: "+result["company_name"]); messagebox.showinfo("Ativação concluída","Este dispositivo foi associado à empresa "+result["company_name"])
        except urllib.error.HTTPError as exc:
            detail=exc.read().decode("utf-8",errors="replace")[:500]
            messagebox.showerror(f"Erro HTTP {exc.code}", detail or str(exc))
        except Exception as exc: messagebox.showerror("Não foi possível ativar",f"Confirme a URL e a ligação.\n\n{exc}")
 
    def save(self):
        try:
            raw=self.amount.get().strip().replace(" ","")
            if "," in raw and "." in raw: raise ValueError("Use apenas um separador decimal.")
            value=Decimal(raw.replace(",","."))
            if not value.is_finite(): raise ValueError("O valor deve ser finito.")
            cents=int((value*100).quantize(Decimal("1"),rounding=ROUND_HALF_UP))
        except (ValueError, InvalidOperation): messagebox.showerror("Valor inválido","Introduza um valor decimal válido, por exemplo 1250,50."); return
        if cents<=0 or not self.description.get().strip(): messagebox.showerror("Dados inválidos","Descrição e valor positivo são obrigatórios."); return
        with db_connect() as db:
            db.execute("INSERT INTO outbox(event_id,kind,category,description,amount_cents,occurred_at,synced) VALUES(?,?,?,?,?,?,0)",(str(uuid.uuid4()),self.kind.get(),self.category.get(),self.description.get().strip()[:240],cents,datetime.now(timezone.utc).isoformat()))
        self.description.set(""); self.amount.set(""); self.refresh(); self.status.set("Movimento guardado localmente. Pode sincronizar quando houver internet.")
 
    def refresh(self):
        for item in self.tree.get_children(): self.tree.delete(item)
        with db_connect() as db:
            rows=db.execute("SELECT * FROM outbox ORDER BY occurred_at DESC LIMIT 100").fetchall()
            pending=db.execute("SELECT COUNT(*) FROM outbox WHERE synced=0").fetchone()[0]
        for row in rows: self.tree.insert("","end",values=(row["kind"],row["description"],f'{row["amount_cents"]/100:.2f}',"Sincronizado" if row["synced"] else "Pendente"))
        self.status.set(f"{pending} movimento(s) pendente(s) • Dados guardados neste PC")
 
    def sync(self):
        base=setting("server_url"); device=setting("device_id")
        try: token=keyring.get_password("GEmpresa-JLC", device) if device else None
        except Exception: token=None
        if not base or not device or not token: messagebox.showwarning("Ativação necessária","Ative primeiro este dispositivo com o código da empresa."); return
        with db_connect() as db: rows=db.execute("SELECT * FROM outbox WHERE synced=0 ORDER BY occurred_at LIMIT 500").fetchall()
        if not rows: self.status.set("Tudo sincronizado."); return
        payload={"device_id":device,"events":[{"event_id":r["event_id"],"kind":r["kind"],"category":r["category"],"description":r["description"],"amount_cents":r["amount_cents"],"occurred_at":r["occurred_at"]} for r in rows]}
        try:
            result=post_json(base.rstrip("/")+"/api/sync/push",payload,token=token)
            accepted=set(result.get("created",[])) | set(result.get("duplicate",[]))
            with db_connect() as db:
                for event_id in accepted: db.execute("UPDATE outbox SET synced=1 WHERE event_id=?",(event_id,))
            # Pull online changes after pushing local changes. Cursor makes retries safe.
            cursor = int(setting("sync_cursor") or "0")
            pulled_count = 0
            while True:
                pulled = get_json(base.rstrip("/")+f"/api/sync/pull?device_id={device}&after_id={cursor}", token=token)
                with db_connect() as db:
                    for change in pulled.get("changes", []):
                        if change.get("entity") == "transaction" and change.get("operation") == "upsert":
                            item = json.loads(change["payload"])
                            db.execute("INSERT OR IGNORE INTO outbox(event_id,kind,category,description,amount_cents,occurred_at,synced) VALUES(?,?,?,?,?,?,1)", (item["id"],item["kind"],item["category"],item["description"],item["amount_cents"],item["occurred_at"]))
                pulled_count += len(pulled.get("changes", [])); cursor = int(pulled.get("next_cursor", cursor)); setting("sync_cursor", str(cursor))
                if not pulled.get("has_more") or not pulled.get("changes"): break
            self.refresh(); self.status.set(f"Sincronização bidirecional: {len(accepted)} enviados; {pulled_count} alterações recebidas; {len(result.get('rejected',[]))} rejeitado(s).")
        except urllib.error.HTTPError as exc:
            detail=exc.read().decode("utf-8",errors="replace")[:500]
            messagebox.showerror(f"Sincronização rejeitada (HTTP {exc.code})",detail or str(exc))
            self.status.set("Há eventos pendentes. Consulte o erro e corrija antes de repetir.")
        except urllib.error.URLError:
            messagebox.showwarning("Sem ligação","Os dados continuam guardados localmente. Tente novamente quando houver internet."); self.status.set("Offline: operações preservadas no PC.")
        except Exception as exc: messagebox.showerror("Erro de sincronização",str(exc))
 
if __name__ == "__main__":
    root=tk.Tk(); OfflineApp(root); root.mainloop()
 
 
psycopg[binary]>=3.2,<4.0
redis>=5.0,<7.0
celery>=5.4,<6.0
cryptography>=43.0,<46.0
 
cryptography>=43.0,<46.0
 
 
# Copie para .env e substitua por um segredo aleatório com pelo menos 32 caracteres.
APP_SECRET_KEY=REPLACE_WITH_A_RANDOM_SECRET_AT_LEAST_32_CHARS
DATABASE_PATH=./business_hybrid.db
APP_MODE=development
# Em produção: APP_MODE=production e URL pública HTTPS com proxy TLS configurado.
 
# Primeiro administrador geral: criado apenas quando ainda não existe nenhum administrador.
ADMIN_USERNAME=
ADMIN_PASSWORD=
# Produção/R2: configure Redis com password forte e rede privada.
REDIS_URL=
# PostgreSQL é o alvo da migração; a aplicação ainda usa SQLite neste pacote.
# DATABASE_URL=postgresql://gempresa_jlc:CHANGE_ME@127.0.0.1:5432/gempresa_jlc
 
# GEmpresa-JLC / JLC-tech
PRODUCT_NAME=GEmpresa-JLC
PRODUCT_BRAND=JLC-tech
PRODUCT_VERSION=1.0.0
 
 

 
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path
from uuid import UUID, uuid4
import hashlib
import hmac
import json
import os
import secrets
import time
 
# Load .env explicitly without overriding real environment variables.
ROOT_DIR = Path(__file__).resolve().parent.parent
_env_file = ROOT_DIR / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))
 
from fastapi import FastAPI, Form, Request, HTTPException, Header
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
 
from .db import connect, init_db
from .security import hash_password, verify_password, make_activation_code, secret_key, hash_secret, csrf_token, normalize_timestamp, utc_now_iso
from .product import PRODUCT_NAME, PRODUCT_BRAND, PRODUCT_FULL_NAME, PRODUCT_TAGLINE, PRODUCT_VERSION, product_payload
 
BASE_DIR = Path(__file__).resolve().parent
 
def _is_production():
    return os.getenv("APP_MODE", "development").lower() == "production"
 
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Force secret validation at startup, not after serving requests.
    secret_key()
    init_db()
    # Optional first-run platform administrator. Credentials are supplied only through environment variables.
    admin_user, admin_pass = os.getenv("ADMIN_USERNAME", "").strip(), os.getenv("ADMIN_PASSWORD", "")
    if admin_user and len(admin_pass) >= 16:
        with connect() as db:
            exists = db.execute("SELECT 1 FROM platform_admins LIMIT 1").fetchone()
            if not exists:
                db.execute("INSERT INTO platform_admins(id,username,password_hash) VALUES(?,?,?)",
                           (str(uuid4()), admin_user.lower(), hash_password(admin_pass)))
    yield
 
app = FastAPI(title=PRODUCT_FULL_NAME, version=PRODUCT_VERSION, lifespan=lifespan,
              docs_url=None if _is_production() else "/docs", redoc_url=None if _is_production() else "/redoc",
              openapi_url=None if _is_production() else "/openapi.json")
app.add_middleware(SessionMiddleware, secret_key=secret_key(), same_site="lax", https_only=_is_production(), max_age=60*60*8)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
 
# Development uses a process-local limiter. Production uses a shared Redis counter so
# limits remain consistent across multiple API workers/servers.
_RATE: dict[str, list[float]] = {}
_REDIS_LIMITER = None
 
def rate_limit(key: str, limit: int = 8, window: int = 300):
    global _REDIS_LIMITER
    redis_url = os.getenv("REDIS_URL", "").strip()
    if redis_url:
        try:
            if _REDIS_LIMITER is None:
                import redis
                _REDIS_LIMITER = redis.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2, decode_responses=True)
            bucket = int(time.time() // window)
            redis_key = "GEmpresaJLC:ratelimit:" + hashlib.sha256(f"{key}:{bucket}".encode()).hexdigest()
            count = _REDIS_LIMITER.incr(redis_key)
            if count == 1: _REDIS_LIMITER.expire(redis_key, window + 5)
            if count > limit:
                raise HTTPException(429, "Demasiadas tentativas. Aguarde antes de tentar novamente.")
            return
        except HTTPException:
            raise
        except Exception:
            if _is_production():
                raise HTTPException(503, "Serviço de proteção temporariamente indisponível.")
    elif _is_production():
        raise HTTPException(503, "REDIS_URL é obrigatório em produção para limitação distribuída.")
    now = time.time()
    entries = [t for t in _RATE.get(key, []) if now - t < window]
    if len(entries) >= limit:
        raise HTTPException(429, "Demasiadas tentativas. Aguarde antes de tentar novamente.")
    entries.append(now); _RATE[key] = entries
 
def client_key(request: Request, prefix: str):
    return prefix + ":" + (request.client.host if request.client else "unknown")
 
def csrf_for(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = csrf_token(); request.session["csrf_token"] = token
    return token
 
def verify_csrf(request: Request, supplied: str):
    expected = request.session.get("csrf_token", "")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        raise HTTPException(403, "Token CSRF inválido. Atualize a página e tente novamente.")
 
def current_company(request: Request):
    company_id = request.session.get("company_id")
    if not company_id: return None
    with connect() as db:
        return db.execute("SELECT id, name, username, status FROM companies WHERE id=?", (company_id,)).fetchone()
 
def require_company(request: Request):
    company = current_company(request)
    if not company: raise HTTPException(status_code=401, detail="Sessão não autenticada")
    if company["status"] != "active":
        request.session.clear(); raise HTTPException(status_code=403, detail="Empresa bloqueada ou não aprovada")
    if request.session.get("employee_id"):
        with connect() as db:
            employee = db.execute("SELECT active FROM employees WHERE id=? AND company_id=?", (request.session["employee_id"], company["id"])).fetchone()
        if not employee or not employee["active"]:
            request.session.clear(); raise HTTPException(status_code=401, detail="Conta de funcionário desativada")
    return company
 
ROLE_PERMISSIONS = {
    "owner": {"*"}, "admin": {"*"}, "director": {"dashboard.view", "strategy.manage", "reports.view", "projects.manage", "hr.view", "sales.view", "stock.view", "finance.view"},
    "finance": {"dashboard.view", "finance.view", "finance.manage", "reports.view", "cash.manage", "accounting.view"},
    "hr": {"dashboard.view", "hr.view", "hr.manage", "departments.manage", "reports.view"},
    "sales": {"dashboard.view", "sales.view", "sales.manage", "crm.view", "crm.manage", "stock.view", "reports.view"},
    "procurement": {"dashboard.view", "procurement.manage", "stock.view", "stock.manage", "suppliers.manage", "reports.view"},
    "inventory": {"dashboard.view", "stock.view", "stock.manage", "reports.view"},
    "operations": {"dashboard.view", "projects.manage", "stock.view", "stock.manage", "reports.view"},
    "marketing": {"dashboard.view", "marketing.manage", "crm.view", "sales.view", "reports.view"},
    "employee": {"dashboard.view"}, "viewer": {"dashboard.view", "finance.view", "reports.view", "crm.view", "stock.view"},
}
 
 
def require_roles(request: Request, allowed: set[str]):
    # Backward-compatible route guard mapped to a named permission; role overrides
    # are applied centrally by require_permission.
    permission_by_route = {
        frozenset({"owner", "admin", "hr"}): "hr.manage",
        frozenset({"owner", "admin"}): "strategy.manage",
        frozenset({"owner", "admin", "finance"}): "finance.manage",
        frozenset({"owner", "admin", "operations"}): "stock.manage",
        frozenset({"owner", "admin", "operations", "finance"}): "projects.manage",
        frozenset({"owner", "admin", "operations", "sales", "viewer"}): "stock.view",
        frozenset({"owner", "admin", "finance", "viewer"}): "finance.view",
    }
    if not request.session.get("employee_id"):
        return
    permission = permission_by_route.get(frozenset(allowed))
    if permission:
        require_permission(request, permission)
        return
    if request.session.get("employee_role") not in allowed:
        raise HTTPException(403, "O seu perfil não tem permissão para esta operação")
 
 
def require_permission(request: Request, permission: str):
    """Check a server-side role grant; never trust a permission sent by the browser."""
    company = require_company(request)
    employee_id = request.session.get("employee_id")
    if not employee_id:
        return company
    role = request.session.get("employee_role", "employee")
    defaults = ROLE_PERMISSIONS.get(role, set())
    granted = permission in defaults or "*" in defaults
    with connect() as db:
        override = db.execute(
            "SELECT granted FROM role_permissions WHERE company_id=? AND role=? AND permission=?",
            (company["id"], role, permission),
        ).fetchone()
    if override is not None:
        granted = bool(override["granted"])
    if not granted:
        raise HTTPException(403, "O seu perfil não tem permissão para esta operação")
    return company
 
def audit(db, company_id, actor, action, object_id=None, detail=""):
    db.execute("INSERT INTO audit_log(company_id,actor,action,object_id,detail,created_at) VALUES(?,?,?,?,?,?)",
               (company_id, actor, action, object_id, detail[:500], utc_now_iso()))
 
def validate_amount(value: str) -> int:
    if not isinstance(value, str) or len(value) > 32:
        raise ValueError("valor inválido")
    normalized = value.strip().replace(" ", "")
    if "," in normalized and "." in normalized:
        raise ValueError("use apenas um separador decimal; exemplo: 1234,56")
    normalized = normalized.replace(",", ".")
    try: amount = Decimal(normalized)
    except InvalidOperation as exc: raise ValueError("valor inválido") from exc
    if not amount.is_finite(): raise ValueError("valor deve ser finito")
    if amount <= 0 or amount > Decimal(10**10): raise ValueError("o valor deve ser positivo e válido")
    try:
        with localcontext() as ctx:
            ctx.prec = 50
            cents = (amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError("valor fora do intervalo permitido") from exc
    cents_int = int(cents)
    if cents_int <= 0 or cents_int > 10**12: raise ValueError("o valor deve ser positivo e válido")
    return cents_int
 
def secure_base_url(url: str):
    from urllib.parse import urlparse
    parsed = urlparse(url)
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme == "https" and parsed.hostname: return url.rstrip("/")
    if parsed.scheme == "http" and parsed.hostname in local_hosts and not _is_production(): return url.rstrip("/")
    raise HTTPException(400, "A ativação exige HTTPS; HTTP só é permitido para localhost em desenvolvimento.")
 
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if _is_production(): response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
    return response
 
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if current_company(request): return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None, "csrf_token": csrf_for(request)})
 
@app.get("/registo", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse(request=request, name="register.html", context={"error": None, "csrf_token": csrf_for(request)})
 
@app.post("/registo", response_class=HTMLResponse)
def register(request: Request, csrf_token_form: str = Form(..., alias="csrf_token"), company_name: str = Form(...), username: str = Form(...), password: str = Form(...), province: str = Form(""), district: str = Form(""), business_sector: str = Form(""), company_size: str = Form("micro")):
    verify_csrf(request, csrf_token_form); rate_limit(client_key(request, "register"), 4, 3600)
    company_name, username = company_name.strip(), username.strip().lower()
    province, district, business_sector = province.strip(), district.strip(), business_sector.strip()
    if company_size not in {"micro", "small", "medium", "large", "public"} or len(province)>80 or len(district)>80 or len(business_sector)>100:
        raise HTTPException(400, "Dados de localização ou dimensão inválidos")
    if len(company_name) < 2 or len(company_name) > 120 or len(username) < 3 or len(username) > 60 or len(password) < 12:
        return templates.TemplateResponse(request=request, name="register.html", context={"error": "Indique uma empresa válida e uma senha com pelo menos 12 caracteres.", "csrf_token": csrf_for(request)}, status_code=400)
    company_id, code = str(uuid4()), make_activation_code()
    expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat().replace("+00:00", "Z")
    try:
        with connect() as db:
            company_cols = {r["name"] for r in db.execute("PRAGMA table_info(companies)").fetchall()}
            if "activation_code" in company_cols:
                # Legacy schema compatibility: store only an unusable tombstone in the old NOT NULL column.
                db.execute("INSERT INTO companies(id,name,username,password_hash,activation_code,activation_code_hash,activation_expires_at,province,district,business_sector,company_size) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           (company_id, company_name, username, hash_password(password), "INVALIDATED-"+company_id, hash_secret(code), expires, province, district, business_sector, company_size))
            else:
                db.execute("INSERT INTO companies(id,name,username,password_hash,activation_code_hash,activation_expires_at,province,district,business_sector,company_size) VALUES(?,?,?,?,?,?,?,?,?,?)",
                           (company_id, company_name, username, hash_password(password), hash_secret(code), expires, province, district, business_sector, company_size))
            audit(db, company_id, username, "company.registered", company_id, "Empresa criada; código de ativação válido por 24 horas")
    except Exception:
        return templates.TemplateResponse(request=request, name="register.html", context={"error": "Não foi possível criar a conta. Verifique os dados e tente novamente.", "csrf_token": csrf_for(request)}, status_code=400)
    request.session.clear(); request.session["csrf_token"] = csrf_token()
    return templates.TemplateResponse(request=request, name="activation.html", context={"company_name": company_name, "activation_code": code, "csrf_token": csrf_for(request)})
 
@app.post("/login", response_class=HTMLResponse)
def login(request: Request, csrf_token_form: str = Form(..., alias="csrf_token"), username: str = Form(...), password: str = Form(...)):
    rate_limit(client_key(request, "login"), 8, 300)
    verify_csrf(request, csrf_token_form)
    with connect() as db: company = db.execute("SELECT * FROM companies WHERE username=?", (username.strip().lower(),)).fetchone()
    if not company or not verify_password(password, company["password_hash"]):
        # Generic response avoids revealing whether the username exists.
        return templates.TemplateResponse(request=request, name="login.html", context={"error": "Credenciais inválidas.", "csrf_token": csrf_for(request)}, status_code=401)
    if company["status"] != "active":
        return templates.TemplateResponse(request=request, name="login.html", context={"error": "Conta empresarial pendente de aprovação ou bloqueada. Contacte o administrador.", "csrf_token": csrf_for(request)}, status_code=403)
    request.session.clear(); request.session["company_id"] = company["id"]; request.session["csrf_token"] = csrf_token()
    return RedirectResponse("/dashboard", status_code=303)
 
@app.post("/logout")
def logout(request: Request, csrf_token_form: str = Form(..., alias="csrf_token")):
    verify_csrf(request, csrf_token_form); request.session.clear()
    return RedirectResponse("/", status_code=303)
 
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    company = require_company(request)
    with connect() as db:
        rows = db.execute("SELECT kind, COALESCE(SUM(amount_cents),0) AS total FROM transactions WHERE company_id=? GROUP BY kind", (company["id"],)).fetchall()
        recent = db.execute("SELECT * FROM transactions WHERE company_id=? ORDER BY occurred_at DESC LIMIT 8", (company["id"],)).fetchall()
        pending = db.execute("SELECT COUNT(*) FROM transactions WHERE company_id=? AND synced=0", (company["id"],)).fetchone()[0]
    totals = {r["kind"]: r["total"] for r in rows}; income, expense = totals.get("receita", 0), totals.get("despesa", 0)
    return templates.TemplateResponse(request=request, name="dashboard.html", context={"company": company, "income": income, "expense": expense, "balance": income-expense, "recent": recent, "pending": pending, "csrf_token": csrf_for(request)})
 
@app.post("/financeiro/movimento")
def add_transaction(request: Request, csrf_token_form: str = Form(..., alias="csrf_token"), kind: str = Form(...), category: str = Form(...), description: str = Form(...), amount: str = Form(...)):
    company = require_company(request); verify_csrf(request, csrf_token_form)
    if kind not in {"receita", "despesa"}: raise HTTPException(400, "Tipo de movimento inválido")
    try: amount_cents = validate_amount(amount)
    except ValueError as exc: raise HTTPException(400, str(exc))
    category, description = category.strip(), description.strip()
    if not category or len(category) > 80 or not description or len(description) > 240: raise HTTPException(400, "Categoria ou descrição inválida")
    tx_id = str(uuid4()); occurred = utc_now_iso()
    with connect() as db:
        db.execute("INSERT INTO transactions(id,company_id,kind,category,description,amount_cents,source,synced,occurred_at,created_by) VALUES(?,?,?,?,?,?,?,1,?,?)",
                   (tx_id, company["id"], kind, category, description, amount_cents, "online", occurred, company["username"]))
        payload_json = json.dumps({"id":tx_id,"kind":kind,"category":category,"description":description,"amount_cents":amount_cents,"occurred_at":occurred}, ensure_ascii=False)
        db.execute("INSERT INTO sync_changes(company_id,entity,entity_id,operation,payload,version,created_at) VALUES(?,?,?,?,?,?,?)", (company["id"],"transaction",tx_id,"upsert",payload_json,1,occurred))
        audit(db, company["id"], company["username"], "transaction.created", tx_id, json.dumps({"kind":kind,"amount_cents":amount_cents}))
    return RedirectResponse("/dashboard", status_code=303)
 
 
@app.post("/ativacao/novo", response_class=HTMLResponse)
def renew_activation(request: Request, csrf_token_form: str = Form(..., alias="csrf_token")):
    company = require_company(request); verify_csrf(request, csrf_token_form)
    code = make_activation_code(); expires = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat().replace("+00:00", "Z")
    with connect() as db:
        db.execute("UPDATE companies SET activation_code_hash=?,activation_expires_at=?,activation_used_at=NULL WHERE id=?", (hash_secret(code), expires, company["id"]))
        audit(db, company["id"], company["username"], "activation.renewed", company["id"], "Novo código de uso único válido por 24 horas")
    return templates.TemplateResponse(request=request, name="activation.html", context={"company_name": company["name"], "activation_code": code, "csrf_token": csrf_for(request)})
 
@app.post("/api/device/activate")
def activate_device(payload: dict, request: Request):
    code = str(payload.get("activation_code", "")).strip().upper(); device_id = str(payload.get("device_id", ""))
    if len(device_id) < 8 or len(device_id) > 128: raise HTTPException(400, "device_id inválido")
    # Public activation endpoint only accepts TLS outside local development.
    if request.url.scheme != "https" and request.url.hostname not in {"localhost", "127.0.0.1", "::1"}: raise HTTPException(400, "HTTPS obrigatório")
    rate_limit("activate:" + client_key(request, "ip"), 5, 900)
    now = utc_now_iso(); token = secrets.token_urlsafe(48)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        company = db.execute("SELECT id,name,status,activation_expires_at,activation_used_at,activation_code_hash FROM companies WHERE activation_code_hash=?", (hash_secret(code),)).fetchone()
        if not company or company["status"] != "active" or company["activation_used_at"] or not company["activation_expires_at"] or company["activation_expires_at"] < now:
            raise HTTPException(403, "Código inválido, expirado, empresa não aprovada ou já utilizado.")
        existing = db.execute("SELECT company_id,revoked_at FROM activation_devices WHERE device_id=?", (device_id,)).fetchone()
        if existing and (existing["company_id"] != company["id"] or not existing["revoked_at"]):
            raise HTTPException(409, "Este dispositivo já está associado a uma empresa ou continua ativo.")
        if existing:
            db.execute("UPDATE activation_devices SET token_hash=?,activated_at=?,revoked_at=NULL WHERE device_id=? AND company_id=? AND revoked_at IS NOT NULL", (hash_secret(token),now,device_id,company["id"]))
        else:
            db.execute("INSERT INTO activation_devices(device_id,company_id,token_hash) VALUES(?,?,?)", (device_id, company["id"], hash_secret(token)))
        changed = db.execute("UPDATE companies SET activation_used_at=? WHERE id=? AND activation_used_at IS NULL", (now, company["id"])).rowcount
        if changed != 1:
            raise HTTPException(409, "Código já utilizado por outra ativação.")
        audit(db, company["id"], "device:"+device_id, "device.activated", device_id, "Ativação de uso único")
    return {"ok": True, "company_id": company["id"], "company_name": company["name"], "device_token": token}
 
@app.post("/api/sync/push")
def sync_push(payload: dict, authorization: str | None = Header(default=None)):
    if not authorization or not authorization.lower().startswith("bearer "): raise HTTPException(401, "Token do dispositivo obrigatório")
    token = authorization.split(" ",1)[1].strip(); device_id = str(payload.get("device_id", "")); events = payload.get("events", [])
    if not device_id or len(device_id) > 128 or not isinstance(events, list) or len(events) > 500: raise HTTPException(400, "Pedido de sincronização inválido (máximo 500 eventos)")
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > 1_000_000: raise HTTPException(413, "Lote demasiado grande")
    with connect() as db:
        device = db.execute("SELECT company_id,token_hash,revoked_at FROM activation_devices WHERE device_id=?", (device_id,)).fetchone()
        if not device or device["revoked_at"] or not hmac.compare_digest(device["token_hash"], hash_secret(token)):
            raise HTTPException(403, "Dispositivo não autenticado ou revogado")
        created, duplicate, conflicts, rejected = [], [], [], []
        for event in events:
            event_label = event.get("event_id", "desconhecido") if isinstance(event, dict) else "desconhecido"
            try:
                if not isinstance(event, dict): raise ValueError("evento deve ser objeto")
                event_id = str(UUID(str(event["event_id"])))
                kind = str(event["kind"])
                if kind not in {"receita", "despesa"}: raise ValueError("tipo inválido")
                raw_cents = event["amount_cents"]
                if isinstance(raw_cents, bool) or not isinstance(raw_cents, (int, float)) or not float(raw_cents).is_integer(): raise ValueError("amount_cents deve ser inteiro")
                cents = int(raw_cents)
                if cents <= 0 or cents > 10**12: raise ValueError("valor inválido")
                category = str(event.get("category", "Geral"))[:80].strip() or "Geral"
                description = str(event.get("description", ""))[:240].strip()
                if not description: raise ValueError("descrição obrigatória")
                occurred = normalize_timestamp(event.get("occurred_at"))
                existing = db.execute("SELECT kind,category,description,amount_cents,occurred_at FROM transactions WHERE company_id=? AND id=?", (device["company_id"], event_id)).fetchone()
                fingerprint = (kind, category, description, cents, occurred)
                if existing:
                    old = (existing["kind"], existing["category"], existing["description"], existing["amount_cents"], existing["occurred_at"])
                    if old == fingerprint: duplicate.append(event_id)
                    else: conflicts.append({"event_id":event_id,"reason":"ID já existe com conteúdo diferente"})
                    continue
                db.execute("INSERT INTO transactions(id,company_id,kind,category,description,amount_cents,source,synced,occurred_at,device_id) VALUES(?,?,?,?,?,?,?,1,?,?)",
                           (event_id, device["company_id"], kind, category, description, cents, "offline-sync", occurred, device_id))
                sync_payload = json.dumps({"id":event_id,"kind":kind,"category":category,"description":description,"amount_cents":cents,"occurred_at":occurred}, ensure_ascii=False)
                db.execute("INSERT INTO sync_changes(company_id,entity,entity_id,operation,payload,version,created_at) VALUES(?,?,?,?,?,?,?)", (device["company_id"],"transaction",event_id,"upsert",sync_payload,1,utc_now_iso()))
                audit(db, device["company_id"], "device:"+device_id, "transaction.synced", event_id, json.dumps({"kind":kind,"amount_cents":cents}))
                created.append(event_id)
            except (KeyError, TypeError, ValueError, OverflowError, InvalidOperation) as exc:
                rejected.append({"event_id": str(event_label)[:80], "reason": str(exc)[:160]})
        return {"ok": True, "created": created, "duplicate": duplicate, "conflicts": conflicts, "rejected": rejected}
 
 
 
# ---- Platform administration, tenant administration and ERP foundations ----
def require_platform_admin(request: Request):
    admin_id = request.session.get("platform_admin")
    if not admin_id:
        raise HTTPException(401, "Autenticação de administrador geral necessária")
    with connect() as db:
        active = db.execute("SELECT 1 FROM platform_admins WHERE id=? AND active=1", (admin_id,)).fetchone()
    if not active:
        request.session.clear(); raise HTTPException(401, "Sessão de administrador revogada")
 
@app.get("/admin", response_class=HTMLResponse)
def platform_admin_page(request: Request):
    if request.session.get("platform_admin"):
        require_platform_admin(request)
        with connect() as db:
            stats = {r["status"]: r["n"] for r in db.execute("SELECT status,COUNT(*) n FROM companies GROUP BY status").fetchall()}
            companies = db.execute("SELECT id,name,username,status,province,district,created_at FROM companies ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'active' THEN 1 ELSE 2 END,created_at DESC LIMIT 100").fetchall()
        return templates.TemplateResponse(request=request, name="platform_admin.html", context={"authenticated":True,"stats":stats,"companies":companies,"csrf_token":csrf_for(request)})
    return templates.TemplateResponse(request=request, name="platform_admin.html", context={"authenticated":False,"error":None,"csrf_token":csrf_for(request)})
 
@app.post("/admin/login", response_class=HTMLResponse)
def platform_admin_login_form(request: Request, csrf_token_form: str = Form(..., alias="csrf_token"), username: str = Form(...), password: str = Form(...)):
    verify_csrf(request, csrf_token_form); rate_limit(client_key(request, "admin-login-form"), 5, 300)
    with connect() as db:
        admin = db.execute("SELECT * FROM platform_admins WHERE username=? AND active=1", (username.strip().lower(),)).fetchone()
    if not admin or not verify_password(password, admin["password_hash"]):
        return templates.TemplateResponse(request=request, name="platform_admin.html", context={"authenticated":False,"error":"Credenciais inválidas.","csrf_token":csrf_for(request)}, status_code=401)
    request.session.clear(); request.session["platform_admin"] = admin["id"]; request.session["csrf_token"] = csrf_token()
    return RedirectResponse("/admin", status_code=303)
 
@app.post("/admin/logout")
def platform_admin_logout(request: Request, csrf_token_form: str = Form(..., alias="csrf_token")):
    require_platform_admin(request); verify_csrf(request, csrf_token_form); request.session.clear()
    return RedirectResponse("/admin", status_code=303)
 
@app.post("/admin/companies/{company_id}/status")
def platform_admin_status_form(company_id: str, request: Request, csrf_token_form: str = Form(..., alias="csrf_token"), status: str = Form(...)):
    require_platform_admin(request); verify_csrf(request, csrf_token_form)
    if status not in {"active", "blocked", "pending"}: raise HTTPException(400, "Estado inválido")
    with connect() as db:
        changed = db.execute("UPDATE companies SET status=? WHERE id=?", (status, company_id)).rowcount
        if not changed: raise HTTPException(404, "Empresa não encontrada")
        audit(db, company_id, "platform-admin", "company.status_changed", company_id, status)
        db.execute("INSERT INTO platform_admin_audit(admin_id,action,target_type,target_id,detail,created_at) VALUES(?,?,?,?,?,?)", (request.session["platform_admin"],"company.status_changed","company",company_id,status,utc_now_iso()))
    return RedirectResponse("/admin", status_code=303)
 
@app.post("/api/admin/login")
def platform_admin_login(payload: dict, request: Request):
    rate_limit(client_key(request, "admin-login"), 5, 300)
    username = str(payload.get("username", "")).strip().lower()
    password = str(payload.get("password", ""))
    with connect() as db:
        admin = db.execute("SELECT * FROM platform_admins WHERE username=? AND active=1", (username,)).fetchone()
    if not admin or not verify_password(password, admin["password_hash"]):
        raise HTTPException(401, "Credenciais inválidas")
    request.session.clear(); request.session["platform_admin"] = admin["id"]; request.session["csrf_token"] = csrf_token()
    return {"ok": True, "csrf_token": request.session["csrf_token"]}
 
@app.get("/api/admin/companies")
def admin_companies(request: Request, status: str | None = None, q: str = "", page: int = 1, page_size: int = 50):
    require_platform_admin(request)
    page = max(1, page); page_size = min(100, max(1, page_size)); offset = (page - 1) * page_size
    clauses, args = [], []
    if status in {"pending", "active", "blocked"}:
        clauses.append("status=?"); args.append(status)
    if q.strip():
        clauses.append("(name LIKE ? OR username LIKE ? OR province LIKE ? OR district LIKE ?)")
        term = "%" + q.strip()[:80] + "%"; args.extend([term, term, term, term])
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with connect() as db:
        total = db.execute("SELECT COUNT(*) FROM companies" + where, args).fetchone()[0]
        rows = db.execute("SELECT id,name,username,status,province,district,business_sector,company_size,created_at FROM companies" + where + " ORDER BY created_at DESC LIMIT ? OFFSET ?", (*args, page_size, offset)).fetchall()
    return {"companies": [dict(r) for r in rows], "page": page, "page_size": page_size, "total": total, "pages": (total + page_size - 1)//page_size}
 
@app.get("/api/admin/audit")
def admin_audit(request: Request, page: int = 1, page_size: int = 50):
    require_platform_admin(request)
    page = max(1, page); page_size = min(100, max(1, page_size)); offset = (page - 1) * page_size
    with connect() as db:
        total = db.execute("SELECT COUNT(*) FROM platform_admin_audit").fetchone()[0]
        rows = db.execute("SELECT action,target_type,target_id,detail,created_at FROM platform_admin_audit ORDER BY id DESC LIMIT ? OFFSET ?", (page_size, offset)).fetchall()
    return {"events": [dict(x) for x in rows], "page": page, "page_size": page_size, "total": total}
 
@app.get("/api/admin/overview")
def admin_overview(request: Request):
    require_platform_admin(request)
    with connect() as db:
        stats = {r["status"]: r["n"] for r in db.execute("SELECT status,COUNT(*) n FROM companies GROUP BY status").fetchall()}
        employees = db.execute("SELECT COUNT(*) FROM employees WHERE active=1").fetchone()[0]
        devices = db.execute("SELECT COUNT(*) FROM activation_devices WHERE revoked_at IS NULL").fetchone()[0]
        tx = db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        provinces = db.execute("SELECT province,COUNT(*) AS companies FROM companies WHERE province<>'' GROUP BY province ORDER BY companies DESC").fetchall()
    return {"companies": {"pending":stats.get("pending",0), "active":stats.get("active",0), "blocked":stats.get("blocked",0), "total":sum(stats.values())}, "active_employees":employees, "active_devices":devices, "financial_transactions":tx, "companies_by_province":[dict(x) for x in provinces]}
 
@app.post("/api/admin/companies/{company_id}/status")
def admin_company_status(company_id: str, payload: dict, request: Request):
    require_platform_admin(request)
    status = str(payload.get("status", ""))
    if status not in {"active", "blocked", "pending"}: raise HTTPException(400, "Estado inválido")
    with connect() as db:
        row = db.execute("SELECT id FROM companies WHERE id=?", (company_id,)).fetchone()
        if not row: raise HTTPException(404, "Empresa não encontrada")
        db.execute("UPDATE companies SET status=? WHERE id=?", (status, company_id))
        audit(db, company_id, "platform-admin", "company.status_changed", company_id, status)
        db.execute("INSERT INTO platform_admin_audit(admin_id,action,target_type,target_id,detail,created_at) VALUES(?,?,?,?,?,?)",
                   (request.session["platform_admin"], "company.status_changed", "company", company_id, status, utc_now_iso()))
    return {"ok": True, "status": status}
 
@app.get("/api/devices")
def list_devices(request: Request):
    company = require_company(request)
    with connect() as db:
        rows = db.execute("SELECT device_id,activated_at,revoked_at FROM activation_devices WHERE company_id=? ORDER BY activated_at DESC", (company["id"],)).fetchall()
    return {"devices": [dict(r) for r in rows]}
 
@app.post("/api/devices/{device_id}/revoke")
def revoke_device(device_id: str, request: Request):
    company = require_company(request)
    with connect() as db:
        changed = db.execute("UPDATE activation_devices SET revoked_at=? WHERE device_id=? AND company_id=? AND revoked_at IS NULL", (utc_now_iso(), device_id, company["id"])).rowcount
        if not changed: raise HTTPException(404, "Dispositivo ativo não encontrado nesta empresa")
        audit(db, company["id"], company["username"], "device.revoked", device_id, "Revogação solicitada pelo administrador da empresa")
    return {"ok": True, "revoked": True}
 
@app.post("/api/departments")
def create_department(payload: dict, request: Request):
    company = require_company(request); require_roles(request, {"owner", "admin", "hr"}); name = str(payload.get("name", "")).strip()
    if not 2 <= len(name) <= 100: raise HTTPException(400, "Nome de departamento inválido")
    dep_id = str(uuid4())
    try:
        with connect() as db:
            db.execute("INSERT INTO departments(id,company_id,name,description) VALUES(?,?,?,?)", (dep_id, company["id"], name, str(payload.get("description", ""))[:500]))
            audit(db, company["id"], company["username"], "department.created", dep_id, name)
    except Exception: raise HTTPException(409, "Departamento já existe ou dados inválidos")
    return {"id": dep_id, "name": name}
 
@app.get("/api/departments")
def list_departments(request: Request):
    company = require_company(request); require_roles(request, {"owner", "admin", "hr"})
    with connect() as db: rows = db.execute("SELECT id,name,description FROM departments WHERE company_id=? ORDER BY name", (company["id"],)).fetchall()
    return {"departments": [dict(r) for r in rows]}
 
@app.post("/api/employees")
def create_employee(payload: dict, request: Request):
    company = require_company(request); require_roles(request, {"owner", "admin", "hr"})
    name, email, role, password = (str(payload.get(k, "")).strip() for k in ("full_name", "email", "role", "password"))
    allowed = {"admin", "director", "finance", "hr", "sales", "procurement", "inventory", "operations", "marketing", "employee", "viewer"}
    if len(name) < 2 or "@" not in email or role not in allowed or len(password) < 12: raise HTTPException(400, "Dados inválidos; palavra-passe mínima de 12 caracteres")
    dep = payload.get("department_id")
    with connect() as db:
        if dep and not db.execute("SELECT 1 FROM departments WHERE id=? AND company_id=?", (dep, company["id"])).fetchone(): raise HTTPException(400, "Departamento inválido")
        emp_id = str(uuid4())
        try: db.execute("INSERT INTO employees(id,company_id,department_id,full_name,email,role,password_hash) VALUES(?,?,?,?,?,?,?)", (emp_id, company["id"], dep, name, email.lower(), role, hash_password(password)))
        except Exception: raise HTTPException(409, "Email já registado ou dados inválidos")
        audit(db, company["id"], company["username"], "employee.created", emp_id, role)
    return {"id": emp_id, "full_name": name, "role": role}
 
@app.post("/api/employee/login")
def employee_login(payload: dict, request: Request):
    rate_limit(client_key(request, "employee-login"), 8, 300)
    email, password, company_username = (str(payload.get(k, "")).strip() for k in ("email", "password", "company_username"))
    with connect() as db:
        employee = db.execute("SELECT e.*,c.id AS cid,c.status FROM employees e JOIN companies c ON c.id=e.company_id WHERE e.email=? AND c.username=?", (email.lower(),company_username.lower())).fetchone()
    if not employee or not employee["active"] or employee["status"] != "active" or not verify_password(password, employee["password_hash"]):
        raise HTTPException(401, "Credenciais inválidas ou conta inativa")
    request.session.clear(); request.session["company_id"] = employee["cid"]; request.session["employee_id"] = employee["id"]; request.session["employee_role"] = employee["role"]; request.session["employee_name"] = employee["full_name"]; request.session["csrf_token"] = csrf_token()
    return {"ok": True, "employee": employee["full_name"], "role": employee["role"], "csrf_token": request.session["csrf_token"]}
 
@app.get("/api/employees")
def list_employees(request: Request):
    company = require_company(request); require_roles(request, {"owner", "admin", "hr"})
    with connect() as db:
        rows = db.execute("SELECT e.id,e.full_name,e.email,e.role,e.active,d.name AS department FROM employees e LEFT JOIN departments d ON d.id=e.department_id AND d.company_id=e.company_id WHERE e.company_id=? ORDER BY e.full_name", (company["id"],)).fetchall()
    return {"employees": [dict(r) for r in rows]}
 
@app.get("/empresa/permissoes", response_class=HTMLResponse)
def company_permissions_page(request: Request):
    company = require_company(request); require_roles(request, {"owner", "admin"})
    with connect() as db:
        overrides = db.execute("SELECT role,permission,granted FROM role_permissions WHERE company_id=? ORDER BY role,permission", (company["id"],)).fetchall()
    available = sorted({p for role, permissions in ROLE_PERMISSIONS.items() if role not in {"owner", "admin"} for p in permissions if p != "*"})
    return templates.TemplateResponse(request=request, name="permissions.html", context={"company":company,"overrides":overrides,"roles":[r for r in ROLE_PERMISSIONS if r not in {"owner","admin"}],"permissions":available,"csrf_token":csrf_for(request)})
 
@app.post("/empresa/permissoes")
def company_permissions_update(request: Request, csrf_token_form: str = Form(..., alias="csrf_token"), role: str = Form(...), permission: str = Form(...), granted: str = Form(...)):
    company = require_company(request); require_roles(request, {"owner", "admin"}); verify_csrf(request, csrf_token_form)
    valid_permissions = {p for values in ROLE_PERMISSIONS.values() for p in values if p != "*"}
    if role not in ROLE_PERMISSIONS or role in {"owner", "admin"} or permission not in valid_permissions or granted not in {"true", "false"}:
        raise HTTPException(400, "Perfil ou permissão inválida")
    with connect() as db:
        db.execute("INSERT INTO role_permissions(id,company_id,role,permission,granted) VALUES(?,?,?,?,?) ON CONFLICT(company_id,role,permission) DO UPDATE SET granted=excluded.granted", (str(uuid4()), company["id"], role, permission, int(granted == "true")))
        audit(db, company["id"], request.session.get("employee_name", company["username"]), "permission.changed", role, f"{permission}={granted}")
    return RedirectResponse("/empresa/permissoes", status_code=303)
 
@app.get("/api/permissions/roles")
def list_role_permissions(request: Request):
    company = require_company(request); require_roles(request, {"owner", "admin"})
    with connect() as db:
        overrides = db.execute("SELECT role,permission,granted FROM role_permissions WHERE company_id=? ORDER BY role,permission", (company["id"],)).fetchall()
    roles = {role: sorted(perms) if "*" not in perms else ["*"] for role, perms in ROLE_PERMISSIONS.items()}
    return {"defaults": roles, "overrides": [dict(x) for x in overrides]}
 
@app.post("/api/permissions/roles")
def set_role_permission(payload: dict, request: Request):
    company = require_company(request); require_roles(request, {"owner", "admin"})
    supplied_csrf = request.headers.get("X-CSRF-Token") or str(payload.get("csrf_token", ""))
    verify_csrf(request, supplied_csrf)
    role = str(payload.get("role", "")); permission = str(payload.get("permission", "")); granted = payload.get("granted")
    if role not in ROLE_PERMISSIONS or role in {"owner", "admin"} or permission not in {p for values in ROLE_PERMISSIONS.values() for p in values if p != "*"} or not isinstance(granted, bool):
        raise HTTPException(400, "Perfil, permissão ou valor inválido; não é permitido alterar o proprietário/administrador")
    with connect() as db:
        db.execute("INSERT INTO role_permissions(id,company_id,role,permission,granted) VALUES(?,?,?,?,?) ON CONFLICT(company_id,role,permission) DO UPDATE SET granted=excluded.granted", (str(uuid4()), company["id"], role, permission, int(granted)))
        audit(db, company["id"], request.session.get("employee_name", company["username"]), "permission.changed", role, f"{permission}={granted}")
    return {"ok": True, "role": role, "permission": permission, "granted": granted}
 
@app.get("/api/branches")
def list_branches(request: Request):
    company = require_company(request); require_roles(request, {"owner", "admin", "director", "operations"})
    with connect() as db:
        rows = db.execute("SELECT id,name,province,district,address,active FROM company_branches WHERE company_id=? ORDER BY province,district,name", (company["id"],)).fetchall()
    return {"branches": [dict(x) for x in rows]}
 
@app.post("/api/branches")
def create_branch(payload: dict, request: Request):
    company = require_company(request); require_roles(request, {"owner", "admin", "director"})
    name = str(payload.get("name", "")).strip(); province = str(payload.get("province", "")).strip(); district = str(payload.get("district", "")).strip()
    if not 2 <= len(name) <= 120 or len(province) > 80 or len(district) > 80: raise HTTPException(400, "Dados de filial inválidos")
    branch_id = str(uuid4())
    try:
        with connect() as db:
            db.execute("INSERT INTO company_branches(id,company_id,name,province,district,address) VALUES(?,?,?,?,?,?)", (branch_id, company["id"], name, province, district, str(payload.get("address", ""))[:240]))
            audit(db, company["id"], request.session.get("employee_name", company["username"]), "branch.created", branch_id, f"{province}/{district}")
    except Exception: raise HTTPException(409, "Filial já existe ou dados inválidos")
    return {"id": branch_id, "name": name}
 
@app.post("/api/strategy/plans")
def create_strategy_plan(payload: dict, request: Request):
    company = require_company(request); require_roles(request, {"owner", "admin"})
    title, objective, horizon = (str(payload.get(k, "")).strip() for k in ("title", "objective", "horizon"))
    if not title or not objective or horizon not in {"short", "medium", "long"}: raise HTTPException(400, "Plano inválido")
    plan_id = str(uuid4())
    with connect() as db:
        db.execute("INSERT INTO strategic_plans(id,company_id,title,mission,vision,objective,metric,target_value,horizon,due_date) VALUES(?,?,?,?,?,?,?,?,?,?)", (plan_id,company["id"],title,str(payload.get("mission",""))[:1000],str(payload.get("vision",""))[:1000],objective,str(payload.get("metric",""))[:120],payload.get("target_value"),horizon,payload.get("due_date")))
        audit(db, company["id"], company["username"], "strategy.plan_created", plan_id, title)
    return {"id": plan_id, "title": title, "status": "planned"}
 
@app.get("/api/strategy/plans")
def list_strategy_plans(request: Request):
    company = require_permission(request, "strategy.manage")
    with connect() as db: rows = db.execute("SELECT * FROM strategic_plans WHERE company_id=? ORDER BY created_at DESC", (company["id"],)).fetchall()
    return {"plans": [dict(r) for r in rows]}
 
@app.post("/api/finance/documents")
def create_finance_document(payload: dict, request: Request):
    company = require_company(request); require_roles(request, {"owner", "admin", "finance"})
    doc_type = str(payload.get("doc_type", "")); counterparty = str(payload.get("counterparty", "")).strip(); description = str(payload.get("description", "")).strip()
    if doc_type not in {"payable", "receivable"} or not counterparty or not description: raise HTTPException(400, "Documento financeiro inválido")
    try: cents = int(payload.get("amount_cents"))
    except (TypeError, ValueError): raise HTTPException(400, "Valor inválido")
    if cents <= 0 or cents > 10**12: raise HTTPException(400, "Valor inválido")
    doc_id = str(uuid4())
    with connect() as db:
        db.execute("INSERT INTO finance_documents(id,company_id,doc_type,counterparty,description,amount_cents,due_date,created_at) VALUES(?,?,?,?,?,?,?,?)", (doc_id,company["id"],doc_type,counterparty[:160],description[:240],cents,payload.get("due_date"),utc_now_iso()))
        audit(db, company["id"], company["username"], "finance.document_created", doc_id, doc_type)
    return {"id": doc_id, "status": "pending"}
 
@app.get("/api/finance/documents")
def list_finance_documents(request: Request):
    company = require_company(request); require_roles(request, {"owner", "admin", "finance", "viewer"})
    with connect() as db: rows = db.execute("SELECT * FROM finance_documents WHERE company_id=? ORDER BY due_date,created_at", (company["id"],)).fetchall()
    return {"documents": [dict(r) for r in rows]}
 
@app.post("/api/customers")
def create_customer(payload: dict, request: Request):
    company = require_permission(request, "crm.manage"); name = str(payload.get("name", "")).strip()
    if not name: raise HTTPException(400, "Nome obrigatório")
    cid = str(uuid4())
    with connect() as db: db.execute("INSERT INTO customers(id,company_id,name,email,phone,notes) VALUES(?,?,?,?,?,?)", (cid,company["id"],name[:160],str(payload.get("email",""))[:160],str(payload.get("phone",""))[:50],str(payload.get("notes",""))[:1000]))
    return {"id": cid, "name": name}
 
@app.get("/api/customers")
def list_customers(request: Request):
    company = require_permission(request, "crm.view")
    with connect() as db: rows = db.execute("SELECT * FROM customers WHERE company_id=? ORDER BY name", (company["id"],)).fetchall()
    return {"customers": [dict(r) for r in rows]}
 
@app.post("/api/products")
def create_product(payload: dict, request: Request):
    company = require_company(request); require_roles(request, {"owner", "admin", "operations"}); sku = str(payload.get("sku", "")).strip(); name = str(payload.get("name", "")).strip()
    try: quantity = float(payload.get("quantity", 0)); min_quantity = float(payload.get("min_quantity", 0)); cost = int(payload.get("cost_cents", 0)); price = int(payload.get("price_cents", 0))
    except (TypeError, ValueError): raise HTTPException(400, "Dados de stock inválidos")
    if not sku or not name or quantity < 0 or min_quantity < 0 or cost < 0 or price < 0: raise HTTPException(400, "Dados de stock inválidos")
    pid = str(uuid4())
    with connect() as db:
        try: db.execute("INSERT INTO products(id,company_id,sku,name,quantity,min_quantity,cost_cents,price_cents) VALUES(?,?,?,?,?,?,?,?)", (pid,company["id"],sku,name,quantity,min_quantity,cost,price))
        except Exception: raise HTTPException(409, "SKU duplicado ou dados inválidos")
        audit(db, company["id"], company["username"], "stock.product_created", pid, sku)
    return {"id": pid, "sku": sku}
 
@app.get("/api/products")
def list_products(request: Request):
    company = require_company(request); require_roles(request, {"owner", "admin", "operations", "sales", "viewer"})
    with connect() as db: rows = db.execute("SELECT * FROM products WHERE company_id=? ORDER BY name", (company["id"],)).fetchall()
    return {"products": [dict(r) for r in rows]}
 
@app.post("/api/projects")
def create_project(payload: dict, request: Request):
    company = require_permission(request, "projects.manage"); title = str(payload.get("title", "")).strip()
    if not title: raise HTTPException(400, "Título obrigatório")
    pid = str(uuid4())
    with connect() as db: db.execute("INSERT INTO projects(id,company_id,title,description,owner,due_date) VALUES(?,?,?,?,?,?)", (pid,company["id"],title,str(payload.get("description",""))[:2000],str(payload.get("owner",""))[:160],payload.get("due_date")))
    return {"id": pid, "title": title, "status": "planned"}
 
@app.get("/api/projects")
def list_projects(request: Request):
    company = require_permission(request, "projects.manage")
    with connect() as db: rows = db.execute("SELECT * FROM projects WHERE company_id=? ORDER BY created_at DESC", (company["id"],)).fetchall()
    return {"projects": [dict(r) for r in rows]}
 
@app.post("/api/suppliers")
def create_supplier(payload: dict, request: Request):
    company = require_permission(request, "suppliers.manage")
    name = str(payload.get("name", "")).strip()
    if not name: raise HTTPException(400, "Nome obrigatório")
    sid = str(uuid4())
    with connect() as db: db.execute("INSERT INTO suppliers(id,company_id,name,email,phone) VALUES(?,?,?,?,?)", (sid,company["id"],name[:160],str(payload.get("email",""))[:160],str(payload.get("phone",""))[:50]))
    return {"id":sid,"name":name}
 
@app.get("/api/suppliers")
def list_suppliers(request: Request):
    company = require_permission(request, "suppliers.manage")
    with connect() as db: rows = db.execute("SELECT * FROM suppliers WHERE company_id=? ORDER BY name", (company["id"],)).fetchall()
    return {"suppliers":[dict(r) for r in rows]}
 
@app.post("/api/cash/open")
def open_cash(payload: dict, request: Request):
    company = require_company(request); require_roles(request, {"owner", "admin", "finance"})
    try: opening = int(payload.get("opening_cents",0))
    except (TypeError,ValueError): raise HTTPException(400,"Saldo inicial inválido")
    if opening < 0 or opening > 10**12: raise HTTPException(400,"Saldo inicial inválido")
    with connect() as db:
        if db.execute("SELECT 1 FROM cash_sessions WHERE company_id=? AND status='open'",(company["id"],)).fetchone(): raise HTTPException(409,"Já existe uma caixa aberta")
        sid=str(uuid4()); db.execute("INSERT INTO cash_sessions(id,company_id,opened_by,opening_cents,opened_at) VALUES(?,?,?,?,?)",(sid,company["id"],request.session.get("employee_name",company["username"]),opening,utc_now_iso()))
        audit(db,company["id"],company["username"],"cash.opened",sid,str(opening))
    return {"id":sid,"status":"open"}
 
@app.post("/api/cash/{session_id}/close")
def close_cash(session_id: str, payload: dict, request: Request):
    company = require_company(request); require_roles(request, {"owner", "admin", "finance"})
    try: closing = int(payload.get("closing_cents"))
    except (TypeError,ValueError): raise HTTPException(400,"Saldo final inválido")
    if closing < 0 or closing > 10**12: raise HTTPException(400,"Saldo final inválido")
    with connect() as db:
        changed=db.execute("UPDATE cash_sessions SET closing_cents=?,closed_at=?,status='closed' WHERE id=? AND company_id=? AND status='open'",(closing,utc_now_iso(),session_id,company["id"])).rowcount
        if not changed: raise HTTPException(404,"Sessão de caixa aberta não encontrada")
        audit(db,company["id"],company["username"],"cash.closed",session_id,str(closing))
    return {"id":session_id,"status":"closed","closing_cents":closing}
 
@app.get("/reports/finance.xlsx")
def finance_excel(request: Request):
    company=require_company(request); require_roles(request,{"owner","admin","finance","viewer"})
    from io import BytesIO
    from openpyxl import Workbook
    with connect() as db: rows=db.execute("SELECT occurred_at,kind,category,description,amount_cents,source FROM transactions WHERE company_id=? ORDER BY occurred_at",(company["id"],)).fetchall()
    wb=Workbook(); ws=wb.active; ws.title="Movimentos"; ws.append(["Data UTC","Tipo","Categoria","Descrição","Valor MZN","Origem"])
    for r in rows: ws.append([r["occurred_at"],r["kind"],r["category"],r["description"],r["amount_cents"]/100,r["source"]])
    ws.freeze_panes="A2"; ws.auto_filter.ref=ws.dimensions
    output=BytesIO(); wb.save(output); output.seek(0)
    return StreamingResponse(output,media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",headers={"Content-Disposition":"attachment; filename=GEmpresaJLC_relatorio_financeiro.xlsx"})
 
@app.get("/reports/finance.pdf")
def finance_pdf(request: Request):
    company=require_company(request); require_roles(request,{"owner","admin","finance","viewer"})
    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    with connect() as db: rows=db.execute("SELECT occurred_at,kind,category,description,amount_cents FROM transactions WHERE company_id=? ORDER BY occurred_at DESC LIMIT 1000",(company["id"],)).fetchall()
    output=BytesIO(); doc=SimpleDocTemplate(output,pagesize=landscape(A4)); styles=getSampleStyleSheet()
    data=[["Data UTC","Tipo","Categoria","Descrição","Valor (MZN)"]]
    for r in rows: data.append([r["occurred_at"][:16],r["kind"],r["category"],r["description"][:70],f'{r["amount_cents"]/100:,.2f}'])
    table=Table(data,repeatRows=1,colWidths=[100,65,100,360,90]); table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#087f5b")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),0.25,colors.grey),("FONTSIZE",(0,0),(-1,-1),8),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#eef6f1")])]))
    doc.build([Paragraph("GEmpresa-JLC — Relatório financeiro",styles["Title"]),Paragraph(company["name"],styles["Heading2"]),Spacer(1,12),table]); output.seek(0)
    return StreamingResponse(output,media_type="application/pdf",headers={"Content-Disposition":"attachment; filename=GEmpresaJLC_relatorio_financeiro.pdf"})
 
@app.get("/api/sync/pull")
def sync_pull(device_id: str, after_id: int = 0, authorization: str | None = Header(default=None)):
    if not authorization or not authorization.lower().startswith("bearer "): raise HTTPException(401, "Token do dispositivo obrigatório")
    token = authorization.split(" ",1)[1].strip()
    with connect() as db:
        device = db.execute("SELECT company_id,token_hash,revoked_at FROM activation_devices WHERE device_id=?", (device_id,)).fetchone()
        if not device or device["revoked_at"] or not hmac.compare_digest(device["token_hash"], hash_secret(token)): raise HTTPException(403, "Dispositivo não autenticado ou revogado")
        rows = db.execute("SELECT id,entity,entity_id,operation,payload,version,created_at FROM sync_changes WHERE company_id=? AND id>? ORDER BY id LIMIT 500", (device["company_id"], max(0,after_id))).fetchall()
    return {"changes": [dict(r) for r in rows], "next_cursor": rows[-1]["id"] if rows else after_id, "has_more": len(rows) == 500}
 
 
@app.get("/api/product")
def product_info():
    return product_payload()
 
@app.get("/health")
def health():
    try:
        with connect() as db: db.execute("SELECT 1").fetchone()
        return {"status":"ok", "database":"ok", "service":PRODUCT_FULL_NAME, "brand":PRODUCT_BRAND, "version":app.version}
    except Exception:
        raise HTTPException(503, "Serviço indisponível")
 
 
@app.get("/ready")
def readiness():
    """Readiness probe; checks shared Redis in production deployments."""
    try:
        with connect() as db: db.execute("SELECT 1").fetchone()
        redis_url = os.getenv("REDIS_URL", "").strip()
        if _is_production():
            if not redis_url: raise RuntimeError("REDIS_URL ausente")
            import redis
            redis.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2).ping()
        return {"ready": True, "database": "ok", "redis": "ok" if redis_url else "development-only"}
    except Exception:
        raise HTTPException(503, "Dependências não estão prontas")
 
 
{% extends "base.html" %}
{% block title %}Permissões • {{ company.name }}{% endblock %}
{% block content %}
<style>
.perm-wrap{max-width:1000px;margin:38px auto;padding:0 22px}.perm-panel{background:#fff;border:1px solid #e5e9e7;border-radius:16px;padding:22px;margin:18px 0}.perm-form{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;align-items:end}.perm-form label{display:block}.perm-form select{width:100%;margin-top:6px}.perm-table{width:100%;border-collapse:collapse}.perm-table td,.perm-table th{padding:11px;border-bottom:1px solid #edf0ee;text-align:left}.perm-help{color:#63736a;font-size:13px}
</style>
<div class="perm-wrap">
  <a class="back" href="/dashboard">← Voltar ao painel</a>
  <div class="eyebrow">ADMINISTRAÇÃO DA EMPRESA</div><h1>Perfis e permissões</h1>
  <p class="perm-help">As permissões são verificadas no servidor. As alterações aplicam-se a todos os funcionários com o perfil selecionado. Os perfis Proprietário e Administrador mantêm controlo total.</p>
  <section class="perm-panel"><h2>Configurar permissão</h2>
    <form class="perm-form" method="post" action="/empresa/permissoes">
      <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
      <div><label>Perfil</label><select name="role">{% for role in roles %}<option value="{{ role }}">{{ role|capitalize }}</option>{% endfor %}</select></div>
      <div><label>Permissão</label><select name="permission">{% for permission in permissions %}<option value="{{ permission }}">{{ permission }}</option>{% endfor %}</select></div>
      <div><label>Acesso</label><select name="granted"><option value="true">Permitir</option><option value="false">Negar</option></select></div>
      <button class="primary" type="submit">Guardar alteração</button>
    </form>
  </section>
  <section class="perm-panel"><h2>Exceções configuradas</h2>
    <table class="perm-table"><thead><tr><th>Perfil</th><th>Permissão</th><th>Estado</th></tr></thead><tbody>
    {% for item in overrides %}<tr><td>{{ item['role'] }}</td><td>{{ item['permission'] }}</td><td>{{ 'Permitida' if item['granted'] else 'Negada' }}</td></tr>{% else %}<tr><td colspan="3">Ainda não existem exceções. Aplicam-se as permissões padrão de cada perfil.</td></tr>{% endfor %}
    </tbody></table>
  </section>
</div>
{% endblock %}
 
 
{% extends "base.html" %}{% block title %}Entrar • GEmpresa-JLC{% endblock %}
{% block content %}<section class="auth-layout"><div class="welcome"><div class="eyebrow">CONTROLO. CLAREZA. CRESCIMENTO.</div><h1>A sua empresa.<br><span>Num só lugar.</span></h1><p>Gestão financeira e operacional com acompanhamento online e trabalho offline, pronto para sincronizar quando a ligação regressar.</p><div class="feature-list"><div>✓ Registo básico de receitas e despesas</div><div>✓ Resumo financeiro por empresa</div><div>✓ Acesso online do patronato</div><div>✓ Cliente offline com envio de movimentos</div></div></div><div class="auth-card"><div class="card-icon">↗</div><h2>Bem-vindo de volta</h2><p class="muted">Entre no painel da sua empresa.</p>{% if error %}<div class="error">{{ error }}</div>{% endif %}<form method="post" action="/login"><input type="hidden" name="csrf_token" value="{{ csrf_token }}"><label>Username da empresa</label><input name="username" autocomplete="username" required placeholder="ex.: minhaempresa"><label>Senha</label><input name="password" type="password" autocomplete="current-password" required placeholder="A sua senha"><button class="primary" type="submit">Entrar no sistema <span>→</span></button></form><div class="auth-bottom">Ainda não tem conta? <a href="/registo">Registar empresa</a></div><div class="secure-note">● Sessão protegida • Acesso multiempresa</div></div></section>{% endblock %}
 
 
<!doctype html>
<html lang="pt">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{% block title %}GEmpresa-JLC | JLC-tech{% endblock %}</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<header class="topbar"><a class="brand" href="/"><span class="brand-mark">G</span><span>GEmpresa<span class="brand-light">-JLC</span></span></a><span class="top-caption">GESTÃO EMPRESARIAL • JLC-TECH</span></header>
<main>{% block content %}{% endblock %}</main>
<footer>GEmpresa-JLC • Produto da JLC-tech • Gestão empresarial híbrida</footer>
</body></html>
 
 
{% extends "base.html" %}{% block title %}Registar empresa • GEmpresa-JLC{% endblock %}
{% block content %}<section class="single-layout"><div class="auth-card wide"><a class="back" href="/">← Voltar ao login</a><div class="eyebrow">COMECE AQUI</div><h2>Registar a sua empresa</h2><p class="muted">Crie a conta principal. Depois, use o código gerado para associar a instalação do computador.</p>{% if error %}<div class="error">{{ error }}</div>{% endif %}<form method="post" action="/registo"><input type="hidden" name="csrf_token" value="{{ csrf_token }}"><label>Nome da empresa ou instituição</label><input name="company_name" required maxlength="120" placeholder="Nome legal ou comercial"><label>Província</label><select name="province"><option value="">Selecionar mais tarde</option>{% for p in ['Maputo Cidade','Maputo Província','Gaza','Inhambane','Sofala','Manica','Tete','Zambézia','Nampula','Niassa','Cabo Delgado'] %}<option>{{ p }}</option>{% endfor %}</select><label>Distrito / Município</label><input name="district" maxlength="80" placeholder="Ex.: KaMpfumo"><label>Setor de atividade</label><input name="business_sector" maxlength="100" placeholder="Ex.: Comércio, Serviços, Indústria"><label>Dimensão da empresa</label><select name="company_size"><option value="micro">Microempresa</option><option value="small">Pequena</option><option value="medium">Média</option><option value="large">Grande</option><option value="public">Instituição pública</option></select><label>Username da empresa</label><input name="username" required minlength="3" maxlength="60" placeholder="nome_da_empresa"><label>Senha principal (mínimo 12 caracteres)</label><input name="password" type="password" required minlength="12" autocomplete="new-password" placeholder="Crie uma senha forte"><button class="primary" type="submit">Criar conta e gerar código →</button></form><p class="tiny">Guarde o código de ativação. Não o partilhe publicamente.</p></div></section>{% endblock %}
 
 
{% extends "base.html" %}{% block title %}Código de ativação • GEmpresa-JLC{% endblock %}
{% block content %}<section class="single-layout"><div class="auth-card wide"><div class="success-icon">✓</div><div class="eyebrow">CONTA CRIADA</div><h2>{{ company_name }}</h2><p class="muted">Use este código para associar a aplicação local à conta online.</p><div class="activation-code">{{ activation_code }}</div><p class="tiny">O código expira em 24 horas e só pode ser usado uma vez. Guarde-o num local seguro; o sistema guarda apenas o seu hash.</p><a class="primary button-link" href="/dashboard">Abrir dashboard →</a></div></section>{% endblock %}
 
 
{% extends "base.html" %}
{% block title %}Administrador Geral • GEmpresa-JLC{% endblock %}
{% block content %}
<style>
.admin-wrap{max-width:1180px;margin:36px auto;padding:0 22px}.admin-head{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}.admin-head h1{margin:6px 0}.admin-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin:24px 0}.admin-card,.admin-panel{background:#fff;border:1px solid #e5e9e7;border-radius:16px;padding:20px;box-shadow:0 8px 28px #163c2810}.admin-card span{display:block;color:#65756c;font-size:13px}.admin-card strong{display:block;font-size:30px;margin-top:8px}.admin-panel{margin:18px 0;overflow:auto}.admin-panel h2{margin-top:0}.admin-table{width:100%;border-collapse:collapse;min-width:760px}.admin-table th,.admin-table td{text-align:left;padding:12px;border-bottom:1px solid #edf0ee;font-size:14px}.admin-table th{color:#617168;font-weight:600}.admin-actions{display:flex;gap:6px;align-items:center}.admin-actions select{max-width:125px;padding:8px}.admin-login{max-width:430px;margin:70px auto}.admin-login input{width:100%;margin:8px 0 16px}.admin-login button{width:100%}.admin-note{color:#66756c;font-size:13px}.pill-status{padding:5px 9px;border-radius:30px;background:#edf3ef;font-size:12px}.pill-pending{background:#fff4d8}.pill-blocked{background:#ffe6e4}
</style>
<div class="admin-wrap">
{% if not authenticated %}
  <section class="admin-panel admin-login">
    <div class="eyebrow">CENTRO DE CONTROLO NACIONAL</div><h1>Administrador Geral</h1>
    <p class="admin-note">Acesso restrito à equipa de administração da plataforma GEmpresa-JLC.</p>
    {% if error %}<p class="error">{{ error }}</p>{% endif %}
    <form method="post" action="/admin/login">
      <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
      <label>Nome de utilizador</label><input name="username" required autocomplete="username">
      <label>Palavra-passe</label><input name="password" type="password" required autocomplete="current-password">
      <button class="primary" type="submit">Entrar no painel →</button>
    </form>
  </section>
{% else %}
  <div class="admin-head"><div><div class="eyebrow">PLATAFORMA MULTIEMPRESA • MOÇAMBIQUE</div><h1>Centro de Administração Geral</h1><p class="muted">Aprovação, supervisão e controlo das empresas registadas.</p></div>
  <form method="post" action="/admin/logout"><input type="hidden" name="csrf_token" value="{{ csrf_token }}"><button class="secondary">Terminar sessão</button></form></div>
  <div class="admin-cards">
    <div class="admin-card"><span>Total de empresas</span><strong>{{ stats.get('pending',0)+stats.get('active',0)+stats.get('blocked',0) }}</strong></div>
    <div class="admin-card"><span>Aguardam aprovação</span><strong>{{ stats.get('pending',0) }}</strong></div>
    <div class="admin-card"><span>Empresas ativas</span><strong>{{ stats.get('active',0) }}</strong></div>
    <div class="admin-card"><span>Empresas bloqueadas</span><strong>{{ stats.get('blocked',0) }}</strong></div>
  </div>
  <section class="admin-panel"><h2>Diretório de empresas</h2><p class="admin-note">A lista apresenta até 100 registos recentes. Para pesquisa e paginação, utilize a API administrativa.</p>
  <table class="admin-table"><thead><tr><th>Empresa</th><th>Utilizador</th><th>Província</th><th>Distrito</th><th>Estado</th><th>Alterar estado</th></tr></thead><tbody>
  {% for c in companies %}<tr><td><b>{{ c['name'] }}</b><br><small>{{ c['created_at'] }}</small></td><td>{{ c['username'] }}</td><td>{{ c['province'] or '—' }}</td><td>{{ c['district'] or '—' }}</td><td><span class="pill-status {% if c['status']=='pending' %}pill-pending{% elif c['status']=='blocked' %}pill-blocked{% endif %}">{{ c['status'] }}</span></td><td><form class="admin-actions" method="post" action="/admin/companies/{{ c['id'] }}/status"><input type="hidden" name="csrf_token" value="{{ csrf_token }}"><select name="status"><option value="pending" {% if c['status']=='pending' %}selected{% endif %}>Pendente</option><option value="active" {% if c['status']=='active' %}selected{% endif %}>Aprovar</option><option value="blocked" {% if c['status']=='blocked' %}selected{% endif %}>Bloquear</option></select><button class="primary" type="submit">Guardar</button></form></td></tr>{% else %}<tr><td colspan="6">Ainda não existem empresas registadas.</td></tr>{% endfor %}
  </tbody></table></section>
{% endif %}
</div>
{% endblock %}
 
 
{% extends "base.html" %}{% block title %}Dashboard • {{ company.name }}{% endblock %}
{% block content %}<div class="dashboard"><div class="dash-heading"><div><div class="eyebrow">PAINEL DE CONTROLO</div><h1>Olá, {{ company.name }}</h1><p class="muted">Visão geral da atividade e saúde financeira.</p></div><form method="post" action="/logout"><input type="hidden" name="csrf_token" value="{{ csrf_token }}"><button class="secondary" type="submit">Terminar sessão</button></form></div><div class="status-strip"><a class="secondary" href="/empresa/permissoes">Gerir permissões</a><span><i class="dot"></i> Serviço online</span><span>Estado da fila offline: consulte o cliente desktop</span><span>Sincronização disponível quando ligado</span><form method="post" action="/ativacao/novo"><input type="hidden" name="csrf_token" value="{{ csrf_token }}"><button class="secondary" type="submit">Gerar novo código de ativação</button></form></div><div class="metric-grid"><div class="metric"><span>Receitas registadas</span><strong>{{ '%.2f'|format(income/100) }} <small>MZN</small></strong><em>Entradas financeiras</em></div><div class="metric"><span>Despesas registadas</span><strong>{{ '%.2f'|format(expense/100) }} <small>MZN</small></strong><em>Saídas financeiras</em></div><div class="metric highlight"><span>Saldo operacional</span><strong>{{ '%.2f'|format(balance/100) }} <small>MZN</small></strong><em>Receitas menos despesas</em></div><div class="metric"><span>Fila offline local</span><strong>—</strong><em>Estado consultado na aplicação do PC</em></div></div><div class="content-grid"><section class="panel"><div class="panel-heading"><div><h2>Registar movimento</h2><p class="muted">Adicione uma entrada ou saída financeira.</p></div><span class="panel-symbol">＋</span></div><form class="transaction-form" method="post" action="/financeiro/movimento"><input type="hidden" name="csrf_token" value="{{ csrf_token }}"><label>Tipo de movimento</label><select name="kind"><option value="receita">Receita / Entrada</option><option value="despesa">Despesa / Saída</option></select><label>Categoria</label><select name="category"><option>Vendas</option><option>Serviços</option><option>Salários</option><option>Renda</option><option>Transporte</option><option>Compras/Stock</option><option>Impostos</option><option>Outros</option></select><label>Descrição</label><input name="description" required maxlength="240" placeholder="Ex.: Venda de mercadoria"><label>Valor (MZN)</label><input name="amount" inputmode="decimal" required placeholder="0,00"><button class="primary" type="submit">Guardar movimento →</button></form></section><section class="panel"><div class="panel-heading"><div><h2>Movimentos recentes</h2><p class="muted">Últimas operações registadas.</p></div><span class="panel-symbol">↗</span></div>{% if recent %}<div class="table-wrap"><table><thead><tr><th>Movimento</th><th>Tipo</th><th>Valor</th></tr></thead><tbody>{% for item in recent %}<tr><td><b>{{ item['description'] }}</b><small>{{ item['category'] }} • {{ item['occurred_at'][:16] }}</small></td><td><span class="tag {{ item['kind'] }}">{{ item['kind'] }}</span></td><td class="amount">{{ '%.2f'|format(item['amount_cents']/100) }} MZN</td></tr>{% endfor %}</tbody></table></div>{% else %}<div class="empty"><div>◎</div><b>Ainda não há movimentos</b><p>Os registos financeiros aparecerão aqui.</p></div>{% endif %}</section></div><div class="module-grid"><div class="module"><span>◎</span><b>Estratégia e projetos</b><small>API inicial disponível</small></div><div class="module"><span>▦</span><b>Clientes e fornecedores</b><small>Cadastro disponível</small></div><div class="module"><span>◫</span><b>Produtos e stock</b><small>Catálogo disponível</small></div><div class="module"><span>♙</span><b>Equipa e departamentos</b><small>Contas e perfis disponíveis</small></div><div class="module"><span>▤</span><b>Relatórios financeiros</b><small>Exportação PDF e Excel</small></div><div class="module"><span>◷</span><b>Caixa e compromissos</b><small>Abertura, fecho e dívidas</small></div></div></div>{% endblock %}
 
 
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
 
 
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return "scrypt$" + salt.hex() + "$" + digest.hex()
 
 
def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, salt_hex, digest_hex = password_hash.split("$", 2)
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False
 
 
def make_activation_code() -> str:
    return "ATJ-" + secrets.token_hex(4).upper() + "-" + secrets.token_hex(4).upper()
 
 
def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
 
 
def secret_key() -> str:
    key = os.getenv("APP_SECRET_KEY", "").strip()
    insecure = {"DEV-ONLY-change-this-secret-before-production-7c91f2", "replace-with-a-long-random-secret", ""}
    if key in insecure or len(key) < 32:
        raise RuntimeError("APP_SECRET_KEY é obrigatória: defina um segredo aleatório com pelo menos 32 caracteres no ambiente/.env")
    return key
 
 
def csrf_token() -> str:
    return secrets.token_urlsafe(32)
 
 
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
 
 
def normalize_timestamp(value: str | None) -> str:
    if not value:
        return utc_now_iso()
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("data inválida")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("data inválida; use ISO-8601 com fuso horário") from exc
    if parsed.tzinfo is None:
        raise ValueError("a data deve incluir fuso horário")
    now = datetime.now(timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    if parsed > now + timedelta(minutes=10):
        raise ValueError("data futura não permitida")
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
 
 
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
 
 
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@400;500;600;700;800&display=swap');
:root{--green:#20d69a;--green-dark:#087f5b;--navy:#102a2b;--ink:#172e2d;--muted:#748582;--line:#e4eeea;--bg:#f4f8f6;--white:#fff}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:'DM Sans',sans-serif;min-height:100vh}.topbar{height:76px;padding:0 6vw;display:flex;align-items:center;justify-content:space-between;background:#fff;border-bottom:1px solid #e7efeb}.brand{display:flex;align-items:center;gap:10px;color:var(--navy);text-decoration:none;font-family:Manrope,sans-serif;font-weight:800;font-size:19px;letter-spacing:-.6px}.brand-mark{display:grid;place-items:center;width:36px;height:36px;border-radius:12px;background:#d8fff0;color:#07865f;font-size:28px}.brand-light{color:#0c9b70}.top-caption,.eyebrow{font-size:10px;letter-spacing:1.8px;font-weight:700;color:#77918a}.auth-layout{max-width:1160px;margin:56px auto;padding:0 24px;display:grid;grid-template-columns:1.05fr .85fr;gap:90px;align-items:center;min-height:570px}.welcome{padding:25px 0}.welcome h1{font:800 clamp(42px,5vw,64px)/1.08 Manrope,sans-serif;letter-spacing:-2.5px;margin:20px 0;color:#123b35}.welcome h1 span{color:#10a879}.welcome p{font-size:16px;line-height:1.8;color:#71827e;max-width:510px}.feature-list{display:grid;gap:15px;margin-top:35px;color:#34544d;font-size:14px}.feature-list div: first-letter{color:#0caa78}.auth-card{background:#fff;border:1px solid #e5eeea;border-radius:22px;padding:38px;box-shadow:0 20px 70px #173e2a0a}.card-icon,.success-icon{width:48px;height:48px;display:grid;place-items:center;border-radius:15px;background:#ddfff1;color:#07875f;font-size:26px}.auth-card h2{font:800 26px Manrope,sans-serif;margin:22px 0 8px;letter-spacing:-.8px}.muted{color:var(--muted);font-size:13px;line-height:1.65}.auth-card form{display:flex;flex-direction:column;margin-top:26px}.auth-card label,.transaction-form label{font-size:12px;font-weight:700;color:#38534c;margin:14px 0 8px}.auth-card input,.transaction-form input,.transaction-form select{width:100%;padding:14px 13px;border:1px solid #dfe9e5;border-radius:10px;background:#fbfdfc;color:#173c33;font:14px 'DM Sans',sans-serif;outline:none}.auth-card input:focus,.transaction-form input:focus,.transaction-form select:focus{border-color:#20c991;box-shadow:0 0 0 3px #20d69a1a}.primary{display:flex;align-items:center;justify-content:space-between;gap:12px;background:#087f5b;color:#fff;border:0;border-radius:10px;padding:15px 17px;margin-top:23px;font-weight:700;font-size:13px;text-decoration:none;cursor:pointer;transition:.15s}.primary:hover{background:#066b4d}.auth-bottom{text-align:center;margin-top:23px;color:#71827e;font-size:12px}.auth-bottom a,.back{color:#07875f;font-weight:700;text-decoration:none}.secure-note{font-size:10px;color:#93a39e;text-align:center;margin-top:25px}.single-layout{max-width:540px;margin:55px auto;padding:0 20px}.wide{padding:40px}.back{font-size:12px}.wide .eyebrow{margin-top:28px}.tiny{font-size:11px;line-height:1.7;color:#879691;margin-top:20px}.activation-code{padding:20px 10px;margin-top:24px;border:1px dashed #19b983;background:#effff8;color:#087f5b;border-radius:12px;text-align:center;font:800 25px Manrope,sans-serif;letter-spacing:2px}.button-link{display:flex}.error{background:#fff0ef;color:#a43e38;padding:12px;border-radius:8px;font-size:12px;margin-top:18px}.dashboard{max-width:1320px;margin:38px auto;padding:0 28px 50px}.dash-heading{display:flex;justify-content:space-between;align-items:center;gap:20px}.dash-heading h1{font:800 30px Manrope,sans-serif;letter-spacing:-1px;margin:10px 0 5px}.secondary{border:1px solid #dce8e3;background:white;padding:11px 15px;border-radius:9px;color:#46645b;font-weight:700;cursor:pointer}.status-strip{display:flex;gap:24px;flex-wrap:wrap;background:#e9f8f1;border:1px solid #d9f0e5;border-radius:12px;padding:14px 18px;margin:25px 0;color:#456b5d;font-size:11px}.dot{display:inline-block;width:7px;height:7px;background:#12bd80;border-radius:50%;margin-right:7px}.metric-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.metric{background:white;border:1px solid #e5eeea;border-radius:15px;padding:23px;min-width:0}.metric>span{font-size:12px;color:#71827e}.metric strong{display:block;font:800 clamp(22px,2.2vw,30px) Manrope,sans-serif;margin:17px 0 9px;letter-spacing:-.8px;overflow-wrap:anywhere}.metric strong small{font:600 11px 'DM Sans',sans-serif;color:#82918c;letter-spacing:0}.metric em{font-style:normal;color:#8a9994;font-size:10px}.metric.highlight{background:#0b7456;border-color:#0b7456;color:white}.metric.highlight>span,.metric.highlight em,.metric.highlight strong small{color:#c6f5e3}.content-grid{display:grid;grid-template-columns:.8fr 1.2fr;gap:18px;margin-top:20px}.panel{background:white;border:1px solid #e5eeea;border-radius:15px;padding:24px;min-width:0}.panel-heading{display:flex;justify-content:space-between;align-items:center}.panel h2{font:800 17px Manrope,sans-serif;margin:0}.panel-heading p{margin:7px 0 0}.panel-symbol{display:grid;place-items:center;width:34px;height:34px;border-radius:10px;background:#e7fbf2;color:#07875f;font-size:21px}.transaction-form{display:flex;flex-direction:column}.transaction-form label{margin-top:15px}.transaction-form .primary{width:100%;margin-top:20px}.table-wrap{overflow-x:auto;margin-top:18px}table{width:100%;border-collapse:collapse;font-size:12px}th{text-align:left;color:#8b9a95;font-size:10px;font-weight:600;padding:12px 8px;border-bottom:1px solid #edf2ef}td{padding:14px 8px;border-bottom:1px solid #f0f4f2}td small{display:block;color:#93a09b;font-size:10px;margin-top:5px}.tag{font-size:10px;border-radius:6px;padding:5px 7px}.tag.receita{background:#e4fbf0;color:#07875f}.tag.despesa{background:#fff0e9;color:#b76535}.amount{text-align:right;font-weight:700;white-space:nowrap}.empty{text-align:center;padding:40px 10px;color:#81918b}.empty div{font-size:28px;color:#18b984}.empty b{display:block;margin:10px}.empty p{font-size:12px}.module-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:18px}.module{background:#fff;border:1px solid #e5eeea;border-radius:13px;padding:20px;display:grid;gap:9px}.module>span{font-size:21px;color:#0c9b70}.module b{font-size:12px}.module small{font-size:10px;color:#93a09b}footer{text-align:center;color:#9aa8a2;font-size:10px;padding:24px}@media(max-width:900px){.auth-layout{gap:30px}.metric-grid{grid-template-columns:repeat(2,1fr)}.content-grid{grid-template-columns:1fr}.module-grid{grid-template-columns:repeat(2,1fr)}}@media(max-width:620px){.topbar{height:65px;padding:0 20px}.top-caption{display:none}.auth-layout{grid-template-columns:1fr;margin:22px auto;gap:20px}.welcome{padding:10px 0}.welcome h1{font-size:42px}.welcome p{font-size:14px}.auth-card{padding:25px}.single-layout{margin:25px auto}.wide{padding:27px}.dashboard{margin:24px auto;padding:0 15px}.dash-heading h1{font-size:23px}.metric-grid{gap:10px}.metric{padding:16px}.metric strong{font-size:22px}.status-strip{gap:12px}.panel{padding:18px}.module-grid{gap:10px}.module{padding:14px}}
 
/* GEmpresa-JLC / JLC-tech product polish */
.brand{letter-spacing:-.7px}.brand-light{color:#087f5b}.topbar{box-shadow:0 1px 0 rgba(16,42,43,.02)}
button.primary{background:linear-gradient(135deg,#087f5b,#10a879);box-shadow:0 8px 22px rgba(8,127,91,.16)}
button.primary:hover{transform:translateY(-1px);filter:saturate(1.05)}
.metric.highlight{border-color:#bfead9;background:linear-gradient(145deg,#fff,#effaf5)}
@media (max-width:760px){.topbar{height:auto;min-height:68px;padding:14px 20px;gap:12px}.top-caption{display:none}.auth-layout{grid-template-columns:1fr;margin:28px auto;gap:20px;min-height:auto}.welcome h1{font-size:42px}.dashboard{padding:24px 16px}.content-grid{grid-template-columns:1fr}.metric-grid{grid-template-columns:1fr 1fr}.dash-heading{align-items:flex-start}.status-strip{overflow:auto;white-space:nowrap}.admin-wrap{padding:0 14px}.admin-table{min-width:680px}}
 
 
"""Official product identity and build metadata for GEmpresa-JLC."""
 
PRODUCT_NAME = "GEmpresa-JLC"
PRODUCT_BRAND = "JLC-tech"
PRODUCT_FULL_NAME = "GEmpresa-JLC — Produto da JLC-tech"
PRODUCT_TAGLINE = "Gestão empresarial inteligente, integrada e preparada para Moçambique."
PRODUCT_VERSION = "1.0.0"
PRODUCT_CODENAME = "Maputo"
 
 
def product_payload() -> dict:
    return {
        "name": PRODUCT_NAME,
        "brand": PRODUCT_BRAND,
        "full_name": PRODUCT_FULL_NAME,
        "tagline": PRODUCT_TAGLINE,
        "version": PRODUCT_VERSION,
        "codename": PRODUCT_CODENAME,
    }
 
