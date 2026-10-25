# Implementation Plan

## Milestone Roadmap

- [x] **Milestone 1: Project Scaffolding, Models, SQLite/SQLAlchemy & Health Services**
  - Modular project structure setup (`backend/`, `frontend/`, `tests/`, `docs/`, `uploads/`).
  - FastAPI app initialization, Uvicorn setup, CORS middleware, and static asset serving.
  - SQLAlchemy 2.0 database engine, session management, and full declarative models.
  - Pydantic v2 schemas for health checks and domain entities.
  - `.gitignore`, `.env.example`, `requirements.txt`, and setup documentation.
  - Test suite covering health checks, DB persistence, static delivery, and config validation.

- [ ] **Milestone 2: Authentication Engine, Simulated Time Service & User Seeding**
  - Secure bcrypt password hashing and JWT token handling.
  - FastAPI dependencies for authentication (`get_current_user`, `require_roles`).
  - Simulated `TimeService` (virtual clock offset for demonstrations).
  - Seed script with sample accounts for all 4 roles and default workflow routes.

- [ ] **Milestone 3: Configurable Workflow Engine & State Machine**
  - Application submission by institutions.
  - Route transition verification, forward/return operations with mandatory remarks.
  - Prevention of unauthorized or out-of-sequence transitions.

- [ ] **Milestone 4: EVC Management & Compliance Document Expiry Tracking**
  - Automatic EVC record creation on transition to inspection stage.
  - Committee scheduling and inspection report submission.
  - Document upload with SHA-256 integrity hash and expiry date tracking.
  - Officer verification and rejection with remarks.

- [ ] **Milestone 5: APScheduler, Deadline Engine & Non-Duplicating Escalations**
  - Background scheduler polling SLA status against simulated time.
  - Multi-tier escalations (Level 1 Reminder -> Level 2 Regional -> Level 3 Bureau).
  - Strict human decision integrity: No automatic approval on deadline lapse.

- [ ] **Milestone 6: Frontend Dashboards & Single-Page Application**
  - Role-scoped dashboards for Institution, Regional Officer, Bureau Officer, and Admin.
  - Demo Time Machine UI widget for instant time jumping.
  - Dynamic Chart.js visualizations for stage pendency and SLAs.

- [ ] **Milestone 7: Cryptographic Audit Explorer, Reports (CSV/PDF) & Verification**
  - Immutable SHA-256 hash-chained audit log inspection.
  - Pandas CSV export for SLA and pendency metrics.
  - ReportLab PDF generation for official AICTE Approval Summaries.
  - End-to-end integration test execution.
