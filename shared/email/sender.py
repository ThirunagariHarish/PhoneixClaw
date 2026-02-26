import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from shared.config.base_config import config

logger = logging.getLogger(__name__)


def send_html_email(to_email: str, subject: str, html_body: str) -> bool:
    """Send an HTML email via SMTP. Returns True on success."""
    smtp_cfg = config.smtp
    if not smtp_cfg.host or not smtp_cfg.from_email:
        logger.warning("SMTP not configured — skipping email to %s", to_email)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_cfg.from_email
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))

    try:
        if smtp_cfg.use_tls:
            server = smtplib.SMTP(smtp_cfg.host, smtp_cfg.port, timeout=30)
            server.ehlo()
            server.starttls()
        else:
            server = smtplib.SMTP(smtp_cfg.host, smtp_cfg.port, timeout=30)
            server.ehlo()

        if smtp_cfg.user and smtp_cfg.password:
            server.login(smtp_cfg.user, smtp_cfg.password)

        server.sendmail(smtp_cfg.from_email, [to_email], msg.as_string())
        server.quit()
        logger.info("Email sent to %s: %s", to_email, subject)
        return True
    except Exception:
        logger.exception("Failed to send email to %s", to_email)
        return False
