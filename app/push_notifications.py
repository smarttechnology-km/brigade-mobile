import json
import urllib.error
import urllib.request

EXPO_PUSH_ENDPOINT = 'https://exp.host/--/api/v2/push/send'


def send_expo_push_notification(push_token, title, body, data=None):
    """Send a single Expo push notification.

    Returns a dict with success/error information so callers can log failures
    without breaking the main request flow.
    """
    if not push_token:
        return {'success': False, 'message': 'Missing push token'}

    payload = {
        'to': push_token,
        'sound': 'default',
        'title': title,
        'body': body,
        'data': data or {},
    }

    request = urllib.request.Request(
        EXPO_PUSH_ENDPOINT,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        },
        method='POST',
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response_body = response.read().decode('utf-8')
            return {
                'success': True,
                'status': response.status,
                'response': json.loads(response_body) if response_body else {},
            }
    except urllib.error.HTTPError as error:
        error_body = error.read().decode('utf-8') if error.fp else ''
        return {
            'success': False,
            'status': error.code,
            'message': error_body or str(error),
        }
    except Exception as error:
        return {
            'success': False,
            'message': str(error),
        }


def send_fine_push_notification(vehicle, fine):
    """Notify the vehicle owner's current device that a new fine was issued."""
    try:
        from app.models import VehicleOwner

        owner = VehicleOwner.query.filter_by(vehicle_id=vehicle.id).first()
        if not owner or not owner.expo_push_token:
            return {
                'success': False,
                'message': 'No Expo push token registered for owner',
            }

        amount = float(fine.amount or 0)
        amount_text = f"{amount:,.0f} KMF"
        title = '⚠️ Nouvelle amende'
        body = (
            f"Une nouvelle amende a été émise pour le véhicule {vehicle.license_plate}.\n"
            f"Raison: {fine.reason or 'Non spécifiée'}\n"
            f"Montant: {amount_text}"
        )
        data = {
            'type': 'fine',
            'fine_id': fine.id,
            'vehicle_id': vehicle.id,
            'license_plate': vehicle.license_plate,
            'amount': amount,
            'reason': fine.reason,
            'body': body,
        }

        return send_expo_push_notification(owner.expo_push_token, title, body, data)
    except Exception as error:
        return {
            'success': False,
            'message': str(error),
        }
