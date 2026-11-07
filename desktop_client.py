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
        tk.Label(root, text="GESTÃO EMPRESARIAL · MODO OFFLINE", bg="#f3f8f5", fg="#70857d", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=24, pady=(0, 14))
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
        self.status.set(f"{pending} movimento(s) pendente(s) · Dados guardados neste PC")

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
