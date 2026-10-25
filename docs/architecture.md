# System Architecture Document

## 1. Overview
The AICTE Workflow Automation Platform is a centralized web system for statutory approvals of technical institutions across India. It routes applications through multi-stage pipelines with strict SLA monitoring, EVC inspection tracking, document validity enforcement, append-only audit tracking, and simulated time management.

## 2. Layered Architecture

```
+--------------------------------------------------------------------------+
|                 PRESENTATION LAYER (Frontend SPA)                        |
|   Tailwind CSS (CDN)  |  Chart.js (CDN)  |  Vanilla JS  |  API Client    |
+--------------------------------------------------------------------------+
                                     |
                                REST API
                                     v
+--------------------------------------------------------------------------+
|                  APPLICATION LAYER (FastAPI Backend)                     |
|  - Routers: /health, /auth, /applications, /evc, /documents, /reports    |
|  - Middleware: CORS, Request Context, Exception Handlers                |
|  - Dependencies: Security Guards, Database Session, Current User        |
+--------------------------------------------------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|                     DOMAIN / BUSINESS LOGIC SERVICES                     |
|  - Workflow Engine (State Machine & Transition Rules)                   |
|  - Deadline & Escalation Engine (SLA calculations & non-duplicate alerts)|
|  - EVC Management Service (Committee scheduling & inspection reports)   |
|  - Document & Undertaking Service (SHA-256 hashing & expiry monitoring)  |
|  - Simulated Time Service (Virtual clock offsets without OS tampering)   |
|  - Cryptographic Audit Logger (Append-only hash-chained logging)         |
|  - Report Generator (Pandas CSV & ReportLab PDF)                         |
+--------------------------------------------------------------------------+
                                     |
                                     v
+--------------------------------------------------------------------------+
|                     PERSISTENCE & STORAGE LAYER                          |
|  - SQLAlchemy 2.0 ORM Declarative Models                                 |
|  - SQLite Database (Production convertible to PostgreSQL)                |
|  - Secure File Storage (/uploads) with RBAC Stream Serving               |
+--------------------------------------------------------------------------+
```

## 3. Database Entities & Relationships
1. **User**: Credentials, role (`INSTITUTION`, `REGIONAL_OFFICER`, `BUREAU_OFFICER`, `ADMIN`), regional jurisdiction, institution link.
2. **Institution**: Registered name, AICTE unique code, region, address, contact details.
3. **ApplicationType & WorkflowRoute**: Defines approval routes per category.
4. **WorkflowStage & StageTransition**: Configurable directed graph of approval stages with role permissions and SLAs.
5. **Application & ApplicationStageHistory**: The core approval subject, retaining complete immutable stage history.
6. **EVCVisit**: Records committee members, scheduled inspection dates, recommendations, and reports.
7. **UndertakingDocument**: Stores cryptographic file hash, expiry date, verification status, and officer remarks.
8. **Notification & EscalationRecord**: SLA breach tracking across multi-tier officer hierarchies.
9. **AuditLog**: Tamper-evident ledger chaining entries using SHA-256 hashes (`curr_hash = SHA256(prev_hash + data)`).
10. **SystemSetting**: Stores dynamic configurations including the simulated time offset.
