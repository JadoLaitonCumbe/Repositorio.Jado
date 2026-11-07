@echo off
setlocal
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  echo [GEmpresa-JLC] A criar ambiente virtual...
  python -m venv .venv
  call .venv\Scripts\activate.bat
  python -m pip install --upgrade pip
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate.bat
)
if not defined APP_SECRET_KEY set APP_SECRET_KEY=CHANGE_ME_BEFORE_PRODUCTION
if not defined APP_MODE set APP_MODE=development
python -m uvicorn app.main:app --reload
