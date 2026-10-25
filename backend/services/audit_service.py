import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session
from backend.models.audit import AuditLog


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
    """
    latest = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
    prev_hash = latest.curr_hash if latest and latest.curr_hash else "GENESIS"

    now_utc = datetime.now(timezone.utc)
    details_json = json.dumps(details or {}, sort_keys=True, default=str)

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
