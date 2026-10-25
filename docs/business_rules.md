# Business Rules

## 1. Role-Based Access Control
- **Institution**: Can create and edit draft applications, view their own institution's applications, upload compliance documents, and view stage deadlines. They must never view records belonging to another institution.
- **Regional Officer**: Can process applications assigned to their regional jurisdiction, schedule EVC visits, verify undertakings, and forward/return applications with remarks.
- **Bureau Officer**: Can view applications across regions, receive overdue escalations, and review workload pendency.
- **Admin**: Configures workflow routes, controls simulated demo time, reviews audit logs, and manages accounts.

## 2. Workflow Routing & State Transitions
- Applications must strictly transition along configured routes (`workflow_stages`, `stage_transitions`).
- Returning an application to an earlier stage requires an explicit remark.
- Transitioning into an EVC stage automatically creates an associated `evc_visits` record.
- Final approval requires an explicit decision recorded by an authorized officer; deadlines lapsing will mark applications as `OVERDUE` and escalate, but will never cause automated approval or rejection.

## 3. SLA and Escalation Rules
- Each stage specifies an SLA in days (`sla_days`).
- Deadline checks consult the simulated `TimeService.now()` clock.
- When an application's stage deadline lapses:
  - Application status becomes `OVERDUE`.
  - Level 1 Reminder: Dispatched when 80% of SLA is consumed.
  - Level 2 Escalation: Dispatched to Regional Officer when SLA lapses.
  - Level 3 Escalation: Dispatched to Bureau Officer after extended overdue.
- Escalation checks must be idempotent—repeated scheduler triggers must not duplicate alerts for the same stage instance.

## 4. Compliance & Expiry Monitoring
- Land leases, building completion, and fire safety undertakings require documented expiry dates.
- Documents expiring within 30 days are flagged on the institution and officer dashboards.
- Expired documents block final approval clearance.

## 5. Audit & Security Integrity
- All transitions, approvals, rejections, EVC reports, and time adjustments are appended to `audit_logs`.
- Logs cannot be updated or deleted via application endpoints.
- Each audit log entry is chained using SHA-256 (`curr_hash = SHA256(prev_hash + details)`).
