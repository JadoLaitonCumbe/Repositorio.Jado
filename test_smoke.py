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
