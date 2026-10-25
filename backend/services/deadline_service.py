import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.models.application import Application, ApplicationStatus
from backend.models.document import DocumentStatus, UndertakingDocument
from backend.models.evc import EVCStatus, EVCVisit
from backend.models.notification import (
    DeadlineRule,
    EscalationLevel,
    EscalationRecord,
    Notification,
    NotificationType,
    TrackableEntityType,
)
from backend.models.undertaking import Undertaking, UndertakingStatus
from backend.models.user import Institution, User, UserRole
from backend.services.audit_service import log_audit_event
from backend.services.email_service import send_email_alert
from backend.core.time_service import get_effective_time

logger = logging.getLogger("aicte.deadline_engine")


@dataclass
class TrackableItem:
    """Standardized representation of any trackable workflow entity with a deadline."""

    entity_type: TrackableEntityType
    entity_id: int
    title: str
    due_date: datetime
    institution_id: Optional[int]
    region: Optional[str]
    application_id: Optional[int] = None
    stage_id: Optional[int] = None
    extra_details: Dict[str, Any] = field(default_factory=dict)


DEFAULT_RULES = [
    {
        "entity_type": TrackableEntityType.APPLICATION_STAGE,
        "name": "Application Stage SLA Rule",
        "reminder_threshold_days": 3,
        "escalation_threshold_days": 2,
        "escalation_recipient_role": UserRole.BUREAU_OFFICER,
        "is_active": True,
        "description": "Monitors SLA deadline for active institutional approval applications.",
    },
    {
        "entity_type": TrackableEntityType.EVC_VISIT,
        "name": "EVC Inspection Visit Rule",
        "reminder_threshold_days": 3,
        "escalation_threshold_days": 2,
        "escalation_recipient_role": UserRole.REGIONAL_OFFICER,
        "is_active": True,
        "description": "Monitors scheduling and visit execution deadlines for Expert Visit Committees.",
    },
    {
        "entity_type": TrackableEntityType.UNDERTAKING,
        "name": "Statutory Undertaking Proof Rule",
        "reminder_threshold_days": 5,
        "escalation_threshold_days": 3,
        "escalation_recipient_role": UserRole.REGIONAL_OFFICER,
        "is_active": True,
        "description": "Monitors compliance proof submission due dates for institutional undertakings.",
    },
    {
        "entity_type": TrackableEntityType.DOCUMENT_EXPIRY,
        "name": "Compliance & Lease Document Expiry Rule",
        "reminder_threshold_days": 30,
        "escalation_threshold_days": 7,
        "escalation_recipient_role": UserRole.REGIONAL_OFFICER,
        "is_active": True,
        "description": "Tracks upcoming lease expiries, fire safety, and building certifications.",
    },
]


def ensure_default_deadline_rules(db: Session) -> None:
    """Seed or update default configurable deadline rules idempotently."""
    for rule_data in DEFAULT_RULES:
        existing = (
            db.query(DeadlineRule)
            .filter(DeadlineRule.entity_type == rule_data["entity_type"])
            .first()
        )
        if not existing:
            new_rule = DeadlineRule(**rule_data)
            db.add(new_rule)
    db.commit()


def get_trackable_items(db: Session, entity_type: TrackableEntityType) -> List[TrackableItem]:
    """Retrieve active trackable items for a specific entity type."""
    items: List[TrackableItem] = []

    if entity_type == TrackableEntityType.APPLICATION_STAGE:
        active_statuses = [
            ApplicationStatus.SUBMITTED,
            ApplicationStatus.IN_REVIEW,
            ApplicationStatus.ACTION_REQUIRED,
            ApplicationStatus.OVERDUE,
        ]
        apps = (
            db.query(Application)
            .filter(
                Application.status.in_(active_statuses),
                Application.current_stage_deadline.isnot(None),
            )
            .all()
        )
        for app in apps:
            region = app.institution.region if app.institution else None
            items.append(
                TrackableItem(
                    entity_type=TrackableEntityType.APPLICATION_STAGE,
                    entity_id=app.id,
                    title=f"Application {app.application_number} ({app.title})",
                    due_date=app.current_stage_deadline,
                    institution_id=app.institution_id,
                    region=region,
                    application_id=app.id,
                    stage_id=app.current_stage_id,
                )
            )

    elif entity_type == TrackableEntityType.EVC_VISIT:
        visits = (
            db.query(EVCVisit)
            .filter(
                EVCVisit.status.in_([EVCStatus.PENDING_SCHEDULE, EVCStatus.SCHEDULED]),
                EVCVisit.due_date.isnot(None),
            )
            .all()
        )
        for v in visits:
            inst = v.application.institution if v.application else None
            region = inst.region if inst else None
            items.append(
                TrackableItem(
                    entity_type=TrackableEntityType.EVC_VISIT,
                    entity_id=v.id,
                    title=f"EVC Visit for Application #{v.application_id}",
                    due_date=v.due_date,
                    institution_id=inst.id if inst else None,
                    region=region,
                    application_id=v.application_id,
                )
            )

    elif entity_type == TrackableEntityType.UNDERTAKING:
        undertakings = (
            db.query(Undertaking)
            .filter(
                Undertaking.status.in_(
                    [UndertakingStatus.PENDING, UndertakingStatus.SUBMITTED, UndertakingStatus.REJECTED]
                ),
                Undertaking.due_date.isnot(None),
            )
            .all()
        )
        for u in undertakings:
            inst = u.institution
            region = inst.region if inst else None
            items.append(
                TrackableItem(
                    entity_type=TrackableEntityType.UNDERTAKING,
                    entity_id=u.id,
                    title=f"Undertaking: {u.description[:60]}",
                    due_date=u.due_date,
                    institution_id=u.institution_id,
                    region=region,
                    application_id=u.application_id,
                )
            )

    elif entity_type == TrackableEntityType.DOCUMENT_EXPIRY:
        docs = (
            db.query(UndertakingDocument)
            .filter(
                UndertakingDocument.status.in_([DocumentStatus.ACTIVE, DocumentStatus.EXPIRED]),
                UndertakingDocument.expiry_date.isnot(None),
            )
            .all()
        )
        for d in docs:
            inst = d.institution
            region = inst.region if inst else None
            items.append(
                TrackableItem(
                    entity_type=TrackableEntityType.DOCUMENT_EXPIRY,
                    entity_id=d.id,
                    title=f"Document '{d.title}' ({d.doc_type.value})",
                    due_date=d.expiry_date,
                    institution_id=d.institution_id,
                    region=region,
                    application_id=d.application_id,
                )
            )

    return items


def resolve_recipients(
    db: Session,
    item: TrackableItem,
    target_role: Optional[UserRole] = None,
) -> Dict[str, Optional[User]]:
    """
    Resolve responsible institution, regional officer, bureau officer, and admin users.
    Provides safe fallbacks if regional officer or specific user is missing.
    """
    recipients: Dict[str, Optional[User]] = {
        "institution_user": None,
        "regional_officer": None,
        "bureau_officer": None,
        "admin_user": None,
        "target_escalation_user": None,
    }

    if item.institution_id:
        recipients["institution_user"] = (
            db.query(User)
            .filter(
                User.institution_id == item.institution_id,
                User.role == UserRole.INSTITUTION,
                User.is_active == True,
            )
            .first()
        )

    if item.region:
        recipients["regional_officer"] = (
            db.query(User)
            .filter(
                User.role == UserRole.REGIONAL_OFFICER,
                User.region == item.region,
                User.is_active == True,
            )
            .first()
        )

    recipients["bureau_officer"] = (
        db.query(User)
        .filter(User.role == UserRole.BUREAU_OFFICER, User.is_active == True)
        .first()
    )

    recipients["admin_user"] = (
        db.query(User)
        .filter(User.role == UserRole.ADMIN, User.is_active == True)
        .first()
    )

    # Resolve target escalation role
    if target_role == UserRole.REGIONAL_OFFICER:
        recipients["target_escalation_user"] = (
            recipients["regional_officer"]
            or recipients["bureau_officer"]
            or recipients["admin_user"]
        )
    elif target_role == UserRole.BUREAU_OFFICER:
        recipients["target_escalation_user"] = (
            recipients["bureau_officer"] or recipients["admin_user"]
        )
    elif target_role == UserRole.ADMIN:
        recipients["target_escalation_user"] = recipients["admin_user"]
    else:
        recipients["target_escalation_user"] = (
            recipients["bureau_officer"] or recipients["admin_user"]
        )

    return recipients


def send_in_app_and_email_notification(
    db: Session,
    recipient: User,
    title: str,
    message: str,
    notification_type: NotificationType,
    entity_type: str,
    entity_id: int,
    event_key: str,
    application_id: Optional[int] = None,
) -> Tuple[bool, bool, bool]:
    """
    Create an in-app notification if not already created for this event_key and user,
    and trigger email alert if SMTP is enabled.
    Returns (created: bool, email_attempted: bool, email_sent: bool)
    """
    existing = (
        db.query(Notification)
        .filter(Notification.user_id == recipient.id, Notification.event_key == event_key)
        .first()
    )
    if existing:
        return (False, False, False)

    notification = Notification(
        user_id=recipient.id,
        application_id=application_id,
        title=title,
        message=message,
        notification_type=notification_type,
        entity_type=entity_type,
        entity_id=entity_id,
        event_key=event_key,
        is_read=False,
    )
    db.add(notification)
    db.flush()

    email_attempted, email_sent, _ = send_email_alert(
        to_email=recipient.email,
        subject=title,
        body_text=message,
    )

    return (True, email_attempted, email_sent)


def check_all_deadlines(
    db: Session,
    reference_time: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Main Deadline Engine evaluation cycle.
    Evaluates:
      1. Upcoming Reminders (diff <= reminder_threshold_days)
      2. Due Today alerts
      3. Overdue notices (diff < 0)
      4. SLA Escalations (lapsed >= escalation_threshold_days)
    Guarantees:
      - Uses explicit UTC timezone handling throughout.
      - Uses configurable rules stored in the database.
      - Idempotent: repeated executions do NOT generate duplicate notifications or escalations.
      - Human authority preserved: Workflow applications are never auto-approved or rejected.
    """
    ensure_default_deadline_rules(db)

    now_utc = reference_time or get_effective_time(db)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    summary = {
        "reference_time": now_utc.isoformat(),
        "reminders_created": 0,
        "overdue_created": 0,
        "escalations_created": 0,
        "emails_attempted": 0,
        "emails_sent": 0,
        "rules_evaluated": 0,
        "items_tracked": 0,
    }

    rules = db.query(DeadlineRule).filter(DeadlineRule.is_active == True).all()

    for rule in rules:
        summary["rules_evaluated"] += 1
        items = get_trackable_items(db, rule.entity_type)
        summary["items_tracked"] += len(items)

        for item in items:
            due_utc = (
                item.due_date if item.due_date.tzinfo is not None else item.due_date.replace(tzinfo=timezone.utc)
            )
            diff = due_utc - now_utc
            diff_days = diff.total_seconds() / 86400.0

            recipients = resolve_recipients(db, item, rule.escalation_recipient_role)
            due_date_str = due_utc.strftime("%Y-%m-%d")

            # -------------------------------------------------------------
            # 1. UPCOMING REMINDER (0 <= diff_days <= reminder_threshold_days)
            # -------------------------------------------------------------
            if 0 <= diff_days <= rule.reminder_threshold_days:
                notif_type = NotificationType.DUE_TODAY if diff_days < 1.0 else NotificationType.UPCOMING
                subject = (
                    f"Action Required Today: {item.title}"
                    if notif_type == NotificationType.DUE_TODAY
                    else f"Upcoming Deadline ({round(diff_days, 1)}d): {item.title}"
                )
                body = (
                    f"Reminder: '{item.title}' is due on {due_date_str} (UTC). "
                    f"Please review and complete the necessary statutory requirements."
                )
                event_key = f"REMINDER:{rule.entity_type.value}:{item.entity_id}:{due_date_str}"

                # Send to institution and regional officer
                target_users = [
                    u
                    for u in [recipients["institution_user"], recipients["regional_officer"]]
                    if u is not None
                ]
                for user in target_users:
                    created, attempted, sent = send_in_app_and_email_notification(
                        db=db,
                        recipient=user,
                        title=subject,
                        message=body,
                        notification_type=notif_type,
                        entity_type=rule.entity_type.value,
                        entity_id=item.entity_id,
                        event_key=event_key,
                        application_id=item.application_id,
                    )
                    if created:
                        summary["reminders_created"] += 1
                    if attempted:
                        summary["emails_attempted"] += 1
                    if sent:
                        summary["emails_sent"] += 1

            # -------------------------------------------------------------
            # 2. OVERDUE NOTIFICATION (diff_days < 0)
            # -------------------------------------------------------------
            if diff_days < 0:
                lapsed_days = abs(round(diff_days, 1))
                subject = f"OVERDUE ({lapsed_days}d): {item.title}"
                body = (
                    f"Attention: '{item.title}' passed its statutory due date on {due_date_str} "
                    f"and is currently overdue by {lapsed_days} day(s)."
                )
                event_key = f"OVERDUE:{rule.entity_type.value}:{item.entity_id}:{due_date_str}"

                target_users = [
                    u
                    for u in [recipients["institution_user"], recipients["regional_officer"]]
                    if u is not None
                ]
                for user in target_users:
                    created, attempted, sent = send_in_app_and_email_notification(
                        db=db,
                        recipient=user,
                        title=subject,
                        message=body,
                        notification_type=NotificationType.OVERDUE,
                        entity_type=rule.entity_type.value,
                        entity_id=item.entity_id,
                        event_key=event_key,
                        application_id=item.application_id,
                    )
                    if created:
                        summary["overdue_created"] += 1
                    if attempted:
                        summary["emails_attempted"] += 1
                    if sent:
                        summary["emails_sent"] += 1

            # -------------------------------------------------------------
            # 3. SLA ESCALATION (-diff_days >= escalation_threshold_days)
            # -------------------------------------------------------------
            if -diff_days >= rule.escalation_threshold_days:
                lapsed_days = abs(round(diff_days, 1))
                senior_recipient = recipients["target_escalation_user"]

                if senior_recipient:
                    esc_event_key = f"ESCALATION:{rule.entity_type.value}:{item.entity_id}:{due_date_str}"

                    # Check if escalation record already logged
                    existing_esc = (
                        db.query(EscalationRecord)
                        .filter(EscalationRecord.event_key == esc_event_key)
                        .first()
                    )

                    if not existing_esc:
                        esc_reason = (
                            f"Statutory item '{item.title}' is overdue by {lapsed_days} days "
                            f"(exceeded {rule.escalation_threshold_days}-day threshold). "
                            f"Escalated to {rule.escalation_recipient_role.value} for statutory intervention."
                        )

                        esc_record = EscalationRecord(
                            application_id=item.application_id,
                            stage_id=item.stage_id,
                            entity_type=rule.entity_type.value,
                            entity_id=item.entity_id,
                            event_key=esc_event_key,
                            escalation_level=EscalationLevel.LEVEL_2_REGIONAL,
                            recipient_user_id=senior_recipient.id,
                            reason=esc_reason,
                            trigger_time=now_utc,
                            acknowledged=False,
                        )
                        db.add(esc_record)
                        db.flush()

                        # Audit Log with cryptographic chaining
                        log_audit_event(
                            db=db,
                            action="SLA_ESCALATION",
                            resource_type=rule.entity_type.value,
                            resource_id=str(item.entity_id),
                            user_id=senior_recipient.id,
                            details={
                                "escalation_id": esc_record.id,
                                "entity_type": rule.entity_type.value,
                                "entity_id": item.entity_id,
                                "lapsed_days": lapsed_days,
                                "threshold_days": rule.escalation_threshold_days,
                                "recipient_role": rule.escalation_recipient_role.value,
                                "recipient_email": senior_recipient.email,
                            },
                        )

                        # Create in-app escalation notification
                        esc_subject = f"ESCALATION ALERT: {item.title}"
                        created, attempted, sent = send_in_app_and_email_notification(
                            db=db,
                            recipient=senior_recipient,
                            title=esc_subject,
                            message=esc_reason,
                            notification_type=NotificationType.ESCALATION,
                            entity_type=rule.entity_type.value,
                            entity_id=item.entity_id,
                            event_key=esc_event_key,
                            application_id=item.application_id,
                        )
                        summary["escalations_created"] += 1
                        if attempted:
                            summary["emails_attempted"] += 1
                        if sent:
                            summary["emails_sent"] += 1

    db.commit()
    return summary
