# AICTE Workflow Automation Platform

A modern, transparent, and SLA-governed institutional approval automation system for the All India Council for Technical Education (AICTE).

The platform manages the complete regulatory lifecycle of technical institutions:
- Application submission and multi-stage workflow routing.
- Deadline and SLA tracking with non-duplicating escalation alerts.
- Expert Visit Committee (EVC) scheduling, inspection, and report tracking.
- Land lease, fire safety, and compliance undertaking expiry monitoring.
- Tamper-resistant, append-only cryptographic audit logging.
- Human-in-the-loop decision authority (no automated approval without authorized officer concurrence).
- Administrator-controlled demo time simulation ("Time Machine") without modifying host OS clocks.
- Comprehensive CSV and PDF report generation.

---

## Technology Stack

- **Backend**: Python 3.11+, FastAPI, Uvicorn, SQLAlchemy 2.0, Pydantic v2
- **Database**: SQLite (local development / demonstration), easily swappable to PostgreSQL
- **Frontend**: HTML5, CSS3, Tailwind CSS (CDN), Vanilla JavaScript, Chart.js
- **Background Tasks**: APScheduler
- **Reporting**: Pandas (CSV), ReportLab (PDF)
- **Testing**: Pytest, HTTPX

---

## Project Structure

```
d:\SIH Workflow project\
├── .env.example
├── .gitignore
├── requirements.txt
├── pytest.ini
├── README.md
├── backend\
│   ├── config.py              # Application settings & environment validation
│   ├── database.py            # SQLite/SQLAlchemy engine, sessionmaker & init_db
│   ├── main.py                # FastAPI entry point & static file mounts
│   ├── models\                # Declarative SQLAlchemy models
│   │   ├── base.py            # Reusable TimestampMixin
│   │   ├── user.py            # User, Role, Institution
│   │   ├── workflow.py        # ApplicationType, WorkflowRoute, Stage, Transition
│   │   ├── application.py     # Application, ApplicationStageHistory
│   │   ├── evc.py             # EVCVisit, EVCStatus
│   │   ├── document.py        # UndertakingDocument, DocType, VerificationStatus
│   │   ├── notification.py    # Notification, EscalationRecord
│   │   ├── audit.py           # AuditLog (append-only hash chain)
│   │   └── setting.py         # SystemSetting (simulated time offset)
│   ├── schemas\               # Pydantic schemas (request/response)
│   │   ├── common.py
│   │   ├── health.py
│   │   ├── institution.py
│   │   └── user.py
│   └── routers\               # API route handlers
│       └── health.py          # /api/v1/health & diagnostic endpoints
├── frontend\                  # Static frontend client
│   ├── index.html             # Overview & portal portal landing
│   ├── login.html             # Authentication view shell
│   ├── institution.html       # Institution dashboard shell
│   ├── officer.html           # Regional / Bureau officer workspace shell
│   ├── admin.html             # Admin console & time machine shell
│   ├── css\custom.css         # Styling & AICTE theme
│   └── js\
│       ├── api.js             # Centralized API fetch client
│       └── app.js             # Client lifecycle script
├── tests\                     # Pytest automated test suite
│   ├── conftest.py
│   ├── test_config.py
│   ├── test_database.py
│   └── test_health.py
├── docs\                      # Architecture, specifications & reports
│   ├── architecture.md
│   ├── implementation_plan.md
│   ├── api_contracts.md
│   ├── business_rules.md
│   └── verification_report.md
└── uploads\                   # Secure storage for uploaded documents (.gitkeep)
```

---

## Demo Accounts & Development Credentials

The platform includes an idempotent seed script to populate demo institutions and role-based officer accounts for immediate local demonstration.

To seed/reset demo accounts:
```powershell
python -m backend.seed
```

| Role | Email | Password | Region / Campus |
| :--- | :--- | :--- | :--- |
| **Admin** | `admin@aicte.gov.in` | `Demo@AICTE2026!` | AICTE Headquarters |
| **Bureau Officer** | `bureau@aicte.gov.in` | `Demo@AICTE2026!` | HQ - New Delhi |
| **Regional Officer** | `ro.north@aicte.gov.in` | `Demo@AICTE2026!` | Northern Region |
| **Regional Officer** | `ro.west@aicte.gov.in` | `Demo@AICTE2026!` | Western Region |
| **Institution (DTU)** | `inst.dtu@aicte.gov.in` | `Demo@AICTE2026!` | Delhi Technological University |
| **Institution (COEP)** | `inst.coep@aicte.gov.in` | `Demo@AICTE2026!` | College of Engineering Pune |

> [!NOTE]
> All passwords are cryptographically hashed using **bcrypt** (salt rounds: 12) and passwords/hashes are never exposed via API endpoints.

---

## Windows Setup & Execution Guide

### Prerequisites
- Python 3.10+ (Tested on Python 3.14)
- Git for Windows
- PowerShell or Windows Command Prompt

### Step 1: Clone or Open Workspace
```powershell
cd "d:\SIH Workflow project"
```

### Step 2: Configure Environment
Copy `.env.example` to `.env`:
```powershell
Copy-Item .env.example .env
```

### Step 3: Install Dependencies
```powershell
python -m pip install -r requirements.txt
```

### Step 4: Run Automated Tests
```powershell
python -m pytest
```

### Step 5: Start the Development Server
```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

### Step 6: Access the Application
- **Main Portal**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- **Interactive Swagger API Docs**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc API Documentation**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)
- **Health Check Endpoint**: [http://127.0.0.1:8000/api/v1/health](http://127.0.0.1:8000/api/v1/health)

---

## Security & Persistence Defaults
- **Excluded from Git**: `.env`, SQLite database files (`*.db`), and uploaded document binaries in `uploads/*` are excluded via `.gitignore`.
- **Validation**: Enforced via Pydantic; invalid database schemes and overly short secret keys fail during configuration boot.
