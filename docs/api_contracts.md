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

## 2. Authentication & Profile (`/api/v1/auth` & `/api/auth`)

### `POST /api/auth/login` (and `/api/v1/auth/login`)
Authenticates credentials and returns a signed JWT access token.

**Request Body**:
```json
{
  "email": "admin@aicte.gov.in",
  "password": "Demo@AICTE2026!"
}
```

**Response**:
`200 OK`
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "email": "admin@aicte.gov.in",
    "full_name": "AICTE Platform Administrator",
    "role": "ADMIN",
    "region": null,
    "institution_id": null,
    "is_active": true,
    "created_at": "2026-10-25T05:37:41.037788Z",
    "updated_at": "2026-10-25T05:37:41.037791Z"
  }
}
```

### `GET /api/v1/auth/me`
Returns the profile of the authenticated user. Requires `Authorization: Bearer <token>`.

---

## 3. Applications & Workflow (`/api/applications` & `/api/v1/applications`)

### `POST /api/applications`
Submits a new institutional approval application. Restricted to `INSTITUTION` (or `ADMIN`).

**Request Body**:
```json
{
  "route_type": "SCRUTINY_EVC",
  "title": "Technical Campus Expansion Proposal",
  "description": "Addition of Artificial Intelligence and Data Science department",
  "academic_year": "2026-2027"
}
```

**Response**:
`201 Created`
```json
{
  "id": 1,
  "application_number": "AICTE/2026/NORTH/00001",
  "institution_id": 1,
  "route_type": "SCRUTINY_EVC",
  "status": "SUBMITTED",
  "current_stage": {
    "id": 3,
    "stage_key": "SCRUTINY",
    "name": "Scrutiny Committee Review",
    "order_index": 1,
    "sla_days": 7,
    "is_evc_stage": false,
    "is_final": false
  },
  "current_stage_deadline": "2026-11-01T05:58:28.000Z",
  "stage_history": [
    {
      "id": 1,
      "stage_id": 3,
      "action": "SUBMIT",
      "remarks": "Application submitted by institution",
      "entered_at": "2026-10-25T05:58:28.000Z"
    }
  ]
}
```

### `GET /api/applications`
Lists applications with role-based scoping:
- `INSTITUTION`: Own institution's applications only.
- `REGIONAL_OFFICER`: Applications belonging to assigned region.
- `BUREAU_OFFICER` & `ADMIN`: Authorized cross-region monitoring across all regions.

### `GET /api/applications/{id}`
Returns application details, active stage, and complete stage history. Subject to ownership and regional access boundaries.

### `POST /api/applications/{id}/complete-stage`
Advances an application to the next valid stage, or records final approval/rejection decision. Restricted to authorized officers (`REGIONAL_OFFICER`, `BUREAU_OFFICER`, `ADMIN`).

**Request Body**:
```json
{
  "remarks": "All documents verified in accordance with AICTE Approval Process Handbook",
  "decision": "APPROVE",
  "expected_stage_id": 5
}
```

### `POST /api/applications/{id}/return`
Returns an application to the previous stage or marks `ACTION_REQUIRED` for deficiencies. Requires substantive `reason` (minimum 3 characters).

---

## 4. User Management (`/api/v1/users`)

- **`GET /api/v1/users`**: List users with optional role and region filters (Admin only).
- **`POST /api/v1/users`**: Provision a new user account with role assignment (Admin only).
- **`GET /api/v1/users/{id}`**: Retrieve user details (Admin or self).
- **`PATCH /api/v1/users/{id}`**: Update user details. Non-administrators are blocked with `HTTP 403` if attempting to change their own role or active status.
- **`DELETE /api/v1/users/{id}`**: Soft-delete/deactivate user (Admin only).

---

## 4. Planned API Endpoints for Upcoming Milestones

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
