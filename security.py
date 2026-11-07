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
