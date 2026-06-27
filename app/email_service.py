"""
Email service for sending sensitive approval codes (e.g. payment destination
phone number changes) to a fixed, server-side-only recipient.

Uses the Resend HTTP API rather than raw SMTP: Render (the production host)
blocks outbound SMTP ports (25/465/587), but HTTPS to api.resend.com is not
blocked, so raw smtplib connections fail there with "Network is unreachable".

Unlike app/sms_service.py, this service does NOT simulate success when
unconfigured: for a security control to mean anything, the confirmation code
must travel through a channel the admin requesting the change does not
control. If Resend isn't configured, sending fails loudly so the caller can
refuse the change instead of silently treating it as delivered.
"""
import os
import requests

RESEND_API_URL = 'https://api.resend.com/emails'


def send_approval_email(subject, body):
    """Send a plain-text email via the Resend API.

    Required env vars: RESEND_API_KEY, RESEND_FROM, PAYMENT_CHANGE_APPROVAL_EMAIL.

    Returns {'success': bool, 'message': str}.
    """
    api_key = os.environ.get('RESEND_API_KEY')
    from_addr = os.environ.get('RESEND_FROM')
    to_addr = os.environ.get('PAYMENT_CHANGE_APPROVAL_EMAIL')

    missing = [name for name, val in (
        ('RESEND_API_KEY', api_key), ('RESEND_FROM', from_addr),
        ('PAYMENT_CHANGE_APPROVAL_EMAIL', to_addr),
    ) if not val]
    if missing:
        return {
            'success': False,
            'message': f"Configuration manquante côté serveur: {', '.join(missing)}. "
                       f"Le changement ne peut pas être traité sans canal de confirmation."
        }

    try:
        resp = requests.post(
            RESEND_API_URL,
            headers={'Authorization': f'Bearer {api_key}'},
            json={
                'from': from_addr,
                'to': [to_addr],
                'subject': subject,
                'text': body,
            },
            timeout=10,
        )
        if resp.status_code >= 400:
            return {'success': False, 'message': f'Erreur envoi email ({resp.status_code}): {resp.text}'}
        return {'success': True, 'message': 'Email envoyé.'}
    except requests.RequestException as e:
        return {'success': False, 'message': f'Erreur envoi email: {e}'}
