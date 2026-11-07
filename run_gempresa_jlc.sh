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
