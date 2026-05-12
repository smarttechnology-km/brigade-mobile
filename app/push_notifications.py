import json
import urllib.error
import urllib.request

EXPO_PUSH_ENDPOINT = 'https://exp.host/--/api/v2/push/send'


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
            result = {
                'success': True,
                'status': response.status,
                'response': json.loads(response_body) if response_body else {},
            }
            print(f"✅ Expo push service response: {result.get('status')}")
            return result
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
    """Notify the vehicle owner's current device that a new fine was issued.
    
    This sends a background push notification via Expo push service that will
    be delivered even if the citizen app is closed. The notification includes
    fine details and will be displayed on the device's lock screen or notification
    center.
    """
    try:
        from app.models import VehicleOwner

        owner = VehicleOwner.query.filter_by(vehicle_id=vehicle.id).first()
        if not owner:
            print(f"❌ No owner found for vehicle {vehicle.license_plate}")
            return {
                'success': False,
                'message': 'No owner account found for vehicle',
            }
        
        if not owner.expo_push_token:
            print(f"⚠️ No Expo push token registered for vehicle {vehicle.license_plate}")
            print(f"   Owner must open the app and grant notification permissions first")
            return {
                'success': False,
                'message': 'No Expo push token registered - owner must open app first',
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

        print(f"📲 Sending push notification to vehicle {vehicle.license_plate}")
        print(f"   Token: {owner.expo_push_token[:30]}...")
        print(f"   Title: {title}")
        print(f"   Body: {body[:100]}...")
        
        result = send_expo_push_notification(owner.expo_push_token, title, body, data)
        
        if result.get('success'):
            print(f"✅ Push notification sent successfully to {vehicle.license_plate}")
        else:
            print(f"❌ Push notification failed: {result.get('message')}")
        
        return result
    except Exception as error:
        print(f"❌ Exception in send_fine_push_notification: {error}")
        import traceback
        traceback.print_exc()
        return {
            'success': False,
            'message': str(error),
        }
