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
