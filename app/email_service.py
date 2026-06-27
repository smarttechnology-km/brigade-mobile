"""
Email service for sending sensitive approval codes (e.g. payment destination
phone number changes) to a fixed, server-side-only recipient.

Unlike app/sms_service.py, this service does NOT simulate success when
unconfigured: for a security control to mean anything, the confirmation code
must travel through a channel the admin requesting the change does not
control. If SMTP isn't configured, sending fails loudly so the caller can
refuse the change instead of silently treating it as delivered.
"""
import os
import smtplib
from email.mime.text import MIMEText


def send_approval_email(subject, body):
    """Send a plain-text email via SMTP using server-side environment variables.

    Required env vars: SMTP_HOST, SMTP_USER, SMTP_PASSWORD, PAYMENT_CHANGE_APPROVAL_EMAIL.
    Optional: SMTP_PORT (default 587), SMTP_FROM (default SMTP_USER).

    Returns {'success': bool, 'message': str}.
    """
    host = os.environ.get('SMTP_HOST')
    user = os.environ.get('SMTP_USER')
    password = os.environ.get('SMTP_PASSWORD')
    to_addr = os.environ.get('PAYMENT_CHANGE_APPROVAL_EMAIL')
    port = int(os.environ.get('SMTP_PORT', 587))
    from_addr = os.environ.get('SMTP_FROM') or user

    missing = [name for name, val in (
        ('SMTP_HOST', host), ('SMTP_USER', user), ('SMTP_PASSWORD', password),
        ('PAYMENT_CHANGE_APPROVAL_EMAIL', to_addr),
    ) if not val]
    if missing:
        return {
            'success': False,
            'message': f"Configuration manquante côté serveur: {', '.join(missing)}. "
                       f"Le changement ne peut pas être traité sans canal de confirmation."
        }

    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = from_addr
    msg['To'] = to_addr

    try:
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(from_addr, [to_addr], msg.as_string())
        return {'success': True, 'message': 'Email envoyé.'}
    except Exception as e:
        return {'success': False, 'message': f'Erreur envoi email: {e}'}
