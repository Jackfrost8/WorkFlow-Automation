# API Contracts

## 1. Health & Diagnostics

### `GET /api/v1/health`
Checks backend responsiveness, environment, and database connectivity.

**Response**:
`200 OK`
```json
{
  "status": "healthy",
  "app_name": "AICTE Workflow Automation Platform",
  "app_env": "development",
  "database_connected": true,
  "timestamp": "2026-10-25T05:27:26.553563Z",
  "time_simulation_enabled": true,
  "version": "1.0.0"
}
```

---

## 2. Planned API Endpoints for Upcoming Milestones

### Authentication (`/api/v1/auth`)
- `POST /login`: Validates credentials and returns JWT bearer token.
- `GET /me`: Returns profile and permissions of authenticated user.

### Applications & Workflow (`/api/v1/applications`)
- `GET /`: Lists applications filtered by user role and region.
- `POST /`: Creates a new approval application (Institution only).
- `GET /{id}`: Returns application details, current stage, and stage history.
- `POST /{id}/transition`: Forwards, returns, approves, or rejects an application with remarks.

### EVC Inspection (`/api/v1/evc`)
- `GET /{application_id}`: Returns EVC visit details.
- `POST /{application_id}/schedule`: Schedules committee visit date and members.
- `POST /{application_id}/report`: Uploads signed inspection report and recommendations.

### Documents & Undertakings (`/api/v1/documents`)
- `POST /upload`: Uploads undertaking with SHA-256 hash and expiry date.
- `GET /{id}/download`: Streams secure document with RBAC verification.
- `POST /{id}/verify`: Officer verification or rejection with mandatory remarks.

### Demo Time & Admin (`/api/v1/admin`)
- `GET /time`: Returns simulated current time and offset seconds.
- `POST /time/fast-forward`: Advances simulated time by specified days/hours.
- `GET /audit`: Returns searchable, cryptographically verified audit records.
- `GET /reports/applications.csv`: Exports application SLA metrics in CSV format.
- `GET /reports/{id}/approval.pdf`: Generates official AICTE Approval Order in PDF format.
