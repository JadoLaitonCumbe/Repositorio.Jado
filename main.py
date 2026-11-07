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
