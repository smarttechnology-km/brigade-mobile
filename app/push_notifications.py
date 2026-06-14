import json
import urllib.error
import urllib.request

EXPO_PUSH_ENDPOINT = 'https://exp.host/--/api/v2/push/send'


def _get_vehicle_tokens(vehicle):
    """Return the set of Expo push tokens registered for a vehicle's owner."""
    from app.models import VehicleOwner
    tokens = set()
    try:
        owner = VehicleOwner.query.filter_by(vehicle_id=vehicle.id).first()
        if owner and owner.expo_push_token:
            tokens.add(owner.expo_push_token)
        phone = vehicle.owner_phone or (owner.phone if owner else None)
        if phone:
            for o in VehicleOwner.query.filter_by(phone=phone).all():
                if o.expo_push_token:
                    tokens.add(o.expo_push_token)
    except Exception as e:
        print(f"❌ Error collecting tokens for vehicle {vehicle.license_plate}: {e}")
    return tokens


def _send_to_vehicle(vehicle, title, body, data=None):
    """Send a push notification to all tokens linked to a vehicle. Returns True if at least one succeeded."""
    tokens = _get_vehicle_tokens(vehicle)
    if not tokens:
        print(f"⚠️ No push token for vehicle {vehicle.license_plate}")
        return False
    results = []
    for token in tokens:
        r = send_expo_push_notification(token, title, body, data or {})
        results.append(r)
    return any(r.get('success') for r in results)


def send_vignette_expiry_notification(vehicle, days_until):
    """Notify owner that their vignette is expiring or has expired."""
    plate = vehicle.license_plate
    if days_until < 0:
        title = '🚨 Vignette expirée'
        body = f"La vignette de votre véhicule {plate} a expiré. Veuillez la renouveler dès que possible."
        notif_type = 'vignette_expired'
    elif days_until == 0:
        title = '🚨 Vignette expire aujourd\'hui'
        body = f"La vignette de votre véhicule {plate} expire aujourd'hui. Renouvelez-la immédiatement."
        notif_type = 'vignette_expiry_today'
    else:
        title = f'⚠️ Vignette expire dans {days_until} jour{"s" if days_until > 1 else ""}'
        body = f"La vignette de votre véhicule {plate} expire dans {days_until} jour{'s' if days_until > 1 else ''}. Pensez à la renouveler."
        notif_type = 'vignette_expiry_soon'
    return _send_to_vehicle(vehicle, title, body, {
        'type': notif_type,
        'vehicle_id': vehicle.id,
        'license_plate': plate,
        'days_until': days_until,
    })


def send_vignette_renewal_notification(vehicle):
    """Notify owner that the vignette renewal period is now open."""
    plate = vehicle.license_plate
    title = '🔄 Renouvellement vignette ouvert'
    body = f"La période de renouvellement de vignette est ouverte pour votre véhicule {plate}. Renouvelez dès maintenant."
    return _send_to_vehicle(vehicle, title, body, {
        'type': 'vignette_renewal_open',
        'vehicle_id': vehicle.id,
        'license_plate': plate,
    })


def send_insurance_expiry_notification(vehicle, days_until):
    """Notify owner that their insurance is expiring."""
    plate = vehicle.license_plate
    if days_until == 0:
        title = '🚨 Assurance expire aujourd\'hui'
        body = f"L'assurance de votre véhicule {plate} expire aujourd'hui. Renouvelez-la immédiatement."
    else:
        title = f'⚠️ Assurance expire dans {days_until} jour{"s" if days_until > 1 else ""}'
        body = f"L'assurance de votre véhicule {plate} expire dans {days_until} jour{'s' if days_until > 1 else ''}. Pensez à la renouveler."
    return _send_to_vehicle(vehicle, title, body, {
        'type': 'insurance_expiry_soon',
        'vehicle_id': vehicle.id,
        'license_plate': plate,
        'days_until': days_until,
    })


def send_expo_push_notification(push_token, title, body, data=None):
    """Send a single Expo push notification via Expo push service.
    
    This sends notifications that will be delivered to the device even when
    the app is closed, via Expo's push notification service at exp.host.
    
    Returns a dict with success/error information so callers can log failures
    without breaking the main request flow.
    """
    if not push_token:
        print("❌ Cannot send push notification: missing push token")
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
        print(f"📤 Sending to Expo push service: {EXPO_PUSH_ENDPOINT}")
        with urllib.request.urlopen(request, timeout=10) as response:
            response_body = response.read().decode('utf-8')
            parsed = json.loads(response_body) if response_body else {}

            # Expo returns {"data": [{"status": "ok"|"error", ...}]}
            # HTTP 200 only means the request was accepted — must check ticket status
            ticket = (parsed.get('data') or [{}])[0] if isinstance(parsed.get('data'), list) else {}
            ticket_status = ticket.get('status', 'ok')

            if ticket_status == 'error':
                error_msg = ticket.get('message', 'Unknown Expo error')
                error_detail = ticket.get('details', {})
                print(f"❌ Expo ticket error: {error_msg} | details: {error_detail}")
                return {
                    'success': False,
                    'message': error_msg,
                    'expo_error': error_detail,
                    'response': parsed,
                }

            print(f"✅ Expo push accepted — ticket id: {ticket.get('id', '?')}")
            return {
                'success': True,
                'status': response.status,
                'ticket_id': ticket.get('id'),
                'response': parsed,
            }
    except urllib.error.HTTPError as error:
        error_body = error.read().decode('utf-8') if error.fp else ''
        print(f"❌ HTTP Error {error.code}: {error_body}")
        return {
            'success': False,
            'status': error.code,
            'message': error_body or str(error),
        }
    except Exception as error:
        print(f"❌ Exception sending to Expo: {error}")
        return {
            'success': False,
            'message': str(error),
        }


def send_fine_push_notification(vehicle, fine):
    """Notify the vehicle owner's current device that a new fine was issued."""
    try:
        amount = float(fine.amount or 0)
        title = '⚠️ Nouvelle amende'
        body = (
            f"Une nouvelle amende a été émise pour le véhicule {vehicle.license_plate}.\n"
            f"Raison: {fine.reason or 'Non spécifiée'}\n"
            f"Montant: {amount:,.0f} KMF"
        )
        success = _send_to_vehicle(vehicle, title, body, {
            'type': 'fine',
            'fine_id': fine.id,
            'vehicle_id': vehicle.id,
            'license_plate': vehicle.license_plate,
            'amount': amount,
            'reason': fine.reason,
        })
        return {'success': success}
    except Exception as error:
        print(f"❌ Exception in send_fine_push_notification: {error}")
        return {'success': False, 'message': str(error)}
