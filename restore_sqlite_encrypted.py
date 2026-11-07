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
