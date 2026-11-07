GEmpresa-JLC
Business Management System | A JLC-tech Product
Version 1.0.0 · Codename: Maputo · Status: Under Development

GEmpresa-JLC is a software development project designed to bring
essential business management operations together on a hybrid platform
consisting of a Web application and a Desktop client. The project is
being developed with Python and aims to evolve into a modular solution
capable of supporting businesses of different sizes in Mozambique.
Project status: This version represents an evolving functional
foundation. It is not yet a certified accounting ERP, nor is it ready
to be directly exposed to the Internet or used as an official
financial record system without technical, operational, legal, and
security reviews.

Table of Contents
- Overview
- Existing Features
- Architecture and Technologies
- Project Structure
- Requirements
- Installation and Execution
- Running the Desktop Client
- Tests
- Operational Scripts
- Configuration and Security
- Known Limitations
- Planned Development
- Author and Contact
- License
Overview
GEmpresa-JLC is organized around a central Web application and a Desktop
prototype that allows financial transactions to be recorded locally when
there is no Internet connection. When a connection is available, the
client can send pending events to the server and receive updates to
financial transactions.

The solution explores important software development concepts,
including:
- Web applications and REST APIs.
- Data persistence with SQLite.
- Authentication and access control.
- Data separation by company.
- Event logging and synchronization.
- Offline operation and subsequent synchronization.
- Automated testing and maintenance tools.
Existing Features
The features below refer to the code included in version 1.0.0.
Web Application
- Company registration with an initial pending-approval status.
- Company approval, blocking, and status management by the General
  Administrator.
- Authentication and sessions for application access.
- Company dashboard with a summary of financial transactions.
- Revenue and expense recording.
- Basic management of employee accounts, departments, and roles.
- Access checks on selected operations.
- CSRF protection for Web forms.
- Basic security headers.
- Application health endpoint at /health.
- Product identification endpoint at /api/product.
Desktop Client and Offline Operation
- Desktop application developed with Tkinter.
- Local SQLite database for storing transactions.
- Local recording of revenue and expenses without an Internet
  connection.
- Local queue of events pending synchronization.
- Device activation using a single-use, time-limited code.
- Device token storage through the keyring library.
- Sending events to the server through /api/sync/push.
- Receiving financial transaction updates through /api/sync/pull.
- Duplicate event identification and basic conflict handling during
  synchronization.
Synchronization scope in this version: the implemented
synchronization is limited to the financial transactions supported by
the client. It does not yet provide complete synchronization of all ERP
modules, documents, employees, inventory, or other entities.
Maintenance and Testing
- Automated tests with pytest and HTTPX.
- Script for creating SQLite backups.
- Optional scripts for encrypted backups and restoration with
  integrity verification.
- Basic script for testing concurrent requests to the health endpoint.
Architecture and Technologies
  Area                                Technology
  Main programming language           Python 3.11+

  Web application and API             FastAPI

  ASGI server                         Uvicorn

  Web interface                       HTML, CSS, and Jinja2

  Desktop client                      Tkinter

  Operational database in this        SQLite
version                             

  Device credentials                  keyring

  Reports and Excel/PDF files         openpyxl and ReportLab

  Testing                             pytest and HTTPX

  Future infrastructure               PostgreSQL and Redis
(infrastructure preparation)
Version control                     Git and GitHub
Note on PostgreSQL and Redis
The package includes an initial SQL migration for PostgreSQL and a
reference Docker Compose configuration for PostgreSQL and Redis.
However, the application included in this version uses SQLite as its
operational database. The presence of these files does not mean that the
application has already been migrated or that it uses PostgreSQL and
Redis in production.
Project Structure
gempresa_jlc/
├── app/
│   ├── main.py
│   ├── db.py
│   ├── security.py
│   ├── product.py
│   ├── templates/
│   └── static/
├── deploy/
│   └── docker-compose.infrastructure.yml
├── migrations/
│   └── postgresql/
│       └── 001_core.sql
├── scripts/
│   ├── backup_sqlite.py
│   ├── backup_sqlite_encrypted.py
│   ├── restore_sqlite_encrypted.py
│   └── load_test.py
├── tests/
│   └── test_smoke.py
├── desktop_client.py
├── requirements.txt
├── requirements-r2.txt
├── .env.example
├── run_gempresa_jlc.bat
└── run_gempresa_jlc.sh
Requirements
- Python 3.11 or later.
- pip.
- Git (optional, for cloning the repository).
- Tkinter, if you intend to run the Desktop client. On Windows, it is
  usually included with the Python installation; on some Linux
  distributions, it may need to be installed separately.
Installation and Execution
1. Obtain the Project
Clone the repository or extract the ZIP package. Open a terminal in the
gempresa_jlc folder, where the requirements.txt file is located.
cd gempresa_jlc
2. Create a Virtual Environment
Windows PowerShell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
Linux/macOS
python3 -m venv .venv
source .venv/bin/activate
3. Install Dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt
4. Configure Environment Variables
Create the .env file from the example:

Windows PowerShell
Copy-Item .env.example .env
Linux/macOS
cp .env.example .env
Generate a random key:
python -c "import secrets; print(secrets.token_urlsafe(48))"
Place the generated value in APP_SECRET_KEY in the .env file. Use a
private, strong key with at least 32 characters. Do not publish or
upload the .env file to GitHub.

The main variables are:

  Variable            Purpose
  APP_SECRET_KEY    Secret used by the application
DATABASE_PATH     Path to the SQLite database file
APP_MODE          Application operating mode
ADMIN_USERNAME    Initial General Administrator username
ADMIN_PASSWORD    Initial General Administrator password
REDIS_URL         Configuration reserved for future Redis integration
PRODUCT_NAME      Product name
PRODUCT_BRAND     Product brand
PRODUCT_VERSION   Product version

The initial General Administrator is created only if an administrator
does not already exist. Configure strong, unique credentials before
starting the application.
5. Start the Web Application
uvicorn app.main:app --reload
The application will be available at:
- Web application: http://127.0.0.1:8000
- Interactive API documentation, in development mode:
  http://127.0.0.1:8000/docs
- Application health: http://127.0.0.1:8000/health
To stop the server, press Ctrl + C in the terminal.
Running the Desktop Client
Keep the Web server running and open another terminal in the project
folder.
