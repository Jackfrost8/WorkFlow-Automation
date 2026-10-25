import logging
import threading
from datetime import datetime
from typing import Any, Dict, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.services.deadline_service import check_all_deadlines

logger = logging.getLogger("aicte.scheduler")

_scheduler: Optional[BackgroundScheduler] = None
_lock = threading.Lock()
_is_running = False


def scheduled_deadline_job() -> None:
    """Scheduled job executed periodically by APScheduler."""
    logger.info("Executing scheduled AICTE deadline and escalation evaluation...")
    db: Session = SessionLocal()
    try:
        results = check_all_deadlines(db)
        logger.info("Deadline check cycle finished: %s", results)
    except Exception as exc:
        logger.error("Error executing deadline check: %s", exc, exc_info=True)
    finally:
        db.close()


def run_deadline_check_manual(
    db: Optional[Session] = None,
    reference_time: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Direct callable function for triggering deadline checks on-demand,
    in automated test suites, or during live administrator demonstrations.
    """
    if db is not None:
        return check_all_deadlines(db, reference_time=reference_time)

    session: Session = SessionLocal()
    try:
        return check_all_deadlines(session, reference_time=reference_time)
    finally:
        session.close()


def start_scheduler() -> bool:
    """
    Initialize and start the background APScheduler instance.
    Guarantees:
      - Thread-safe singleton execution: prevents multiple instances inside the same process.
      - Worker requirement note: When scaling in production across multiple Uvicorn/Gunicorn
        workers (workers > 1), either designate a dedicated worker, run scheduler in a standalone
        daemon container, or use a distributed database advisory lock / Redis lock.
    """
    global _scheduler, _is_running
    with _lock:
        if _is_running and _scheduler and _scheduler.running:
            logger.debug("APScheduler is already active in this process.")
            return False

        _scheduler = BackgroundScheduler(daemon=True)
        # Check deadlines every 60 minutes in background
        _scheduler.add_job(
            scheduled_deadline_job,
            trigger="interval",
            minutes=60,
            id="aicte_deadline_engine_job",
            name="Periodic statutory deadline and SLA escalation checker",
            replace_existing=True,
        )
        _scheduler.start()
        _is_running = True
        logger.info("APScheduler initialized and started successfully.")
        return True


def shutdown_scheduler() -> None:
    """Gracefully terminate background scheduler during application shutdown."""
    global _scheduler, _is_running
    with _lock:
        if _scheduler and _scheduler.running:
            _scheduler.shutdown(wait=False)
            logger.info("APScheduler stopped cleanly.")
        _is_running = False
        _scheduler = None


def get_scheduler_instance() -> Optional[BackgroundScheduler]:
    """Retrieve the active BackgroundScheduler instance if running."""
    global _scheduler
    return _scheduler
