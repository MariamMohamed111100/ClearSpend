from __future__ import annotations

import smtplib
from email.message import EmailMessage

from flask import current_app


def send_auth_email(recipient: str, subject: str, link: str) -> None:
    send_email(recipient, subject, f"Open this link to continue: {link}")


def send_email(recipient: str, subject: str, body: str) -> None:
    if current_app.config["MAIL_SUPPRESS_SEND"]:
        current_app.logger.info("Email suppressed for %s: %s", recipient, subject)
        return

    message = EmailMessage()
    message["From"] = current_app.config["MAIL_DEFAULT_SENDER"]
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(current_app.config["MAIL_SERVER"], current_app.config["MAIL_PORT"]) as smtp:
        smtp.starttls()
        if current_app.config["MAIL_USERNAME"]:
            smtp.login(current_app.config["MAIL_USERNAME"], current_app.config["MAIL_PASSWORD"])
        smtp.send_message(message)
