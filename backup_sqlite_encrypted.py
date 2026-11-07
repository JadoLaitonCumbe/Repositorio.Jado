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
