# Implementation Plan

## Milestone Roadmap

- [x] **Milestone 1: Project Scaffolding, Models, SQLite/SQLAlchemy & Health Services**
  - Modular project structure setup (`backend/`, `frontend/`, `tests/`, `docs/`, `uploads/`).
  - FastAPI app initialization, Uvicorn setup, CORS middleware, and static asset serving.
  - SQLAlchemy 2.0 database engine, session management, and full declarative models.
  - Pydantic v2 schemas for health checks and domain entities.
  - `.gitignore`, `.env.example`, `requirements.txt`, and setup documentation.
  - Test suite covering health checks, DB persistence, static delivery, and config validation.

- [x] **Milestone 2: Authentication Engine, Simulated Time Service & User Seeding**
  - Secure bcrypt password hashing and JWT token handling.
  - FastAPI dependencies for authentication (`get_current_user`, `require_roles`).
  - Seed script (`python -m backend.seed`) with sample accounts for all 4 roles and institutions.
  - Admin user management endpoints (`/api/v1/users`).
  - Frontend login page with 1-click credential filling and role-based redirects.
  - Frontend protected page route guards and logout behavior.

- [x] **Milestone 3: Configurable Workflow Engine & State Machine**
  - Configured 4 initial routes: `ONLY_SCRUTINY`, `SCRUTINY_EVC`, `EVC_SAC`, `ONLY_EVC`.
  - Application submission by institutions with unique format `AICTE/{year}/{region}/{id}`.
  - Automatic initial stage assignment and SLA deadline calculation.
  - Route transition verification, forward/return operations with mandatory remarks.
  - Automatic `EVCVisit` record creation upon entering EVC inspection stage.
  - Strict human decision authority: `DECISION` requires explicit `APPROVE` or `REJECT`.
  - Cryptographically chained audit logging for all application actions.

- [x] **Milestone 4: EVC Management & Compliance Document Expiry Tracking**
  - Automatic EVC record creation on transition to inspection stage with SLA due-date link.
  - Inspection queue filtering by status (`PENDING_SCHEDULE`, `SCHEDULED`, `COMPLETED`, `CANCELLED`, `DELAYED`) and region.
  - Visit scheduling, committee member assignments, and visit mode (`PHYSICAL`/`VIRTUAL`).
  - Rescheduling engine with justification and reschedule counter.
  - Inspection completion recording with recommendations and deficiency notes.
  - Audit logging for all visit lifecycle events (`EVC_VISIT_SCHEDULED`, `EVC_VISIT_RESCHEDULED`, `EVC_VISIT_COMPLETED`, `EVC_VISIT_CANCELLED`).

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
