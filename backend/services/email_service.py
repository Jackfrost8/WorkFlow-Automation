import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, Tuple

from backend.config import get_settings

logger = logging.getLogger("aicte.email")
settings = get_settings()


def send_email_alert(
    to_email: str,
    subject: str,
    body_text: str,
    body_html: Optional[str] = None,
) -> Tuple[bool, bool, Optional[str]]:
    """
    Attempt to send an email alert via configured SMTP server.
    Returns:
        (attempted: bool, success: bool, error_message: Optional[str])
    Guarantees:
        - Never logs SMTP passwords or sensitive credentials.
        - Catches all transport/authentication exceptions so in-app notifications
          and DB transactions are never aborted.
    """
    if not settings.SMTP_ENABLED:
        return (False, False, "SMTP is disabled in settings.")

    attempted = True
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = settings.SMTP_FROM_EMAIL
        msg["To"] = to_email
        msg["Subject"] = f"[{settings.APP_NAME}] {subject}"

        part_text = MIMEText(body_text, "plain", "utf-8")
        msg.attach(part_text)

        if body_html:
            part_html = MIMEText(body_html, "html", "utf-8")
            msg.attach(part_html)

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                try:
                    server.starttls()
                except Exception as tls_err:
                    logger.debug("SMTP starttls ignored: %s", str(tls_err))
                # Never log settings.SMTP_PASSWORD
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)

            server.send_message(msg)

        logger.info("Successfully delivered email alert to %s", to_email)
        return (attempted, True, None)

    except Exception as exc:
        error_msg = f"Failed delivering email to {to_email}: {type(exc).__name__} - {str(exc)}"
        # Note: Log without exposing passwords
        logger.warning(error_msg)
        return (attempted, False, str(exc))
