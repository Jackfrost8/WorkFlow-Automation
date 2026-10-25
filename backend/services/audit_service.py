import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from backend.models.audit import AuditLog

# Keys that must NEVER be persisted in plaintext inside audit details
SENSITIVE_KEY_PATTERNS = (
    "password",
    "hashed_password",
    "token",
    "secret",
    "api_key",
    "access_token",
    "refresh_token",
    "smtp_password",
    "credentials",
    "authorization",
    "auth_header",
)


def sanitize_audit_details(obj: Any) -> Any:
    """
    Recursively sanitize dictionaries and lists, redacting any sensitive credentials,
    passwords, tokens, or cryptographic secrets prior to persistence.
    """
    if isinstance(obj, dict):
        sanitized = {}
        for k, v in obj.items():
            k_lower = str(k).lower()
            if any(p in k_lower for p in SENSITIVE_KEY_PATTERNS):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_audit_details(v)
        return sanitized
    elif isinstance(obj, list):
        return [sanitize_audit_details(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(sanitize_audit_details(item) for item in obj)
    return obj


def log_audit_event(
    db: Session,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    user_id: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
) -> AuditLog:
    """
    Append an immutable, cryptographically chained audit log entry within the active transaction.
    Guarantees automatic redaction of sensitive credentials and strict SHA-256 hash chaining.
    """
    latest = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
    prev_hash = latest.curr_hash if latest and latest.curr_hash else "GENESIS"

    now_utc = datetime.now(timezone.utc)
    clean_details = sanitize_audit_details(details or {})
    details_json = json.dumps(clean_details, sort_keys=True, default=str)

    raw_payload = f"{prev_hash}|{now_utc.isoformat()}|{user_id}|{action}|{resource_type}|{resource_id}|{details_json}"
    curr_hash = hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()

    audit_entry = AuditLog(
        timestamp=now_utc,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        ip_address=ip_address,
        details_json=details_json,
        prev_hash=prev_hash,
        curr_hash=curr_hash,
    )
    db.add(audit_entry)
    return audit_entry


def query_audit_logs(
    db: Session,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    user_id: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
) -> Tuple[List[AuditLog], int]:
    """
    Query audit logs with multi-parameter filtering and total count calculation.
    """
    query = db.query(AuditLog)

    if action:
        query = query.filter(AuditLog.action == action)
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)
    if resource_id:
        query = query.filter(AuditLog.resource_id == str(resource_id))
    if user_id is not None:
        query = query.filter(AuditLog.user_id == user_id)
    if start_date:
        query = query.filter(AuditLog.timestamp >= start_date)
    if end_date:
        query = query.filter(AuditLog.timestamp <= end_date)
    if search:
        search_pattern = f"%{search.strip()}%"
        query = query.filter(
            (AuditLog.action.ilike(search_pattern))
            | (AuditLog.resource_type.ilike(search_pattern))
            | (AuditLog.resource_id.ilike(search_pattern))
            | (AuditLog.details_json.ilike(search_pattern))
        )

    total_count = query.count()
    logs = query.order_by(AuditLog.id.desc()).offset(skip).limit(limit).all()
    return logs, total_count


def verify_audit_hash_chain(db: Session) -> Dict[str, Any]:
    """
    Cryptographically verify the integrity of the entire append-only audit trail from genesis.
    Returns status, record count, and any broken links.
    """
    records = db.query(AuditLog).order_by(AuditLog.id.asc()).all()
    if not records:
        return {"chain_intact": True, "total_records": 0, "broken_at_id": None}

    expected_prev = "GENESIS"
    for r in records:
        if r.prev_hash != expected_prev:
            return {
                "chain_intact": False,
                "total_records": len(records),
                "broken_at_id": r.id,
                "reason": f"Record #{r.id} prev_hash mismatch: expected '{expected_prev}', got '{r.prev_hash}'",
            }
        if r.timestamp:
            ts_iso = (
                f"{r.timestamp.isoformat()}+00:00"
                if r.timestamp.tzinfo is None
                else r.timestamp.isoformat()
            )
        else:
            ts_iso = ""
        raw = f"{r.prev_hash}|{ts_iso}|{r.user_id}|{r.action}|{r.resource_type}|{r.resource_id}|{r.details_json}"
        expected_curr = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if r.curr_hash != expected_curr:
            return {
                "chain_intact": False,
                "total_records": len(records),
                "broken_at_id": r.id,
                "reason": f"Record #{r.id} hash corruption: expected '{expected_curr}', got '{r.curr_hash}'",
            }
        expected_prev = r.curr_hash

    return {"chain_intact": True, "total_records": len(records), "broken_at_id": None}
