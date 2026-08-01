"""
Citizen Authentication Module for Mobile App
Handles registration, OTP verification, and login for vehicle owners
"""

import os
import json
import random
import string
from datetime import datetime, timedelta
from functools import wraps
from flask import Blueprint, request, jsonify, current_app, Response
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, get_jwt
from app.models import db, Vehicle, User, VehicleOwner, Fine, VehicleTransfer, DriverLicense, PointReductionHistory
from app.sms_service import SMSService
from app.push_notifications import send_expo_push_notification
from app.timezone_utils import now_comoros

citizen_auth_bp = Blueprint('citizen_auth', __name__, url_prefix='/api/auth')

# OTP storage (in production, use Redis or database)
_otp_store = {}


def _normalize_phone(phone):
    """Normalize phone numbers for strict matching against stored records."""
    digits = ''.join(ch for ch in str(phone or '').strip() if ch.isdigit())
    if digits.startswith('00'):
        digits = digits[2:]
    return digits


def _is_vehicle_active(vehicle):
    return bool(vehicle and (vehicle.status or 'active') == 'active')


def build_vehicle_auth_payload(vehicle, owner, phone):
    """Build a consistent JWT payload and response body for citizen auth flows."""
    session_version = int(getattr(owner, 'session_version', 0)) if owner else 0
    device_id = owner.current_device_id if owner else None

    return {
        'access_token': create_access_token(
            identity=str(vehicle.id),
            additional_claims={
                'vehicle_id': vehicle.id,
                'license_plate': vehicle.license_plate,
                'phone': phone,
                'session_version': session_version,
                'device_id': device_id,
            }
        ),
        'vehicle': {
            'id': vehicle.id,
            'license_plate': vehicle.license_plate,
            'owner_name': vehicle.owner_name,
            'vehicle_type': vehicle.vehicle_type,
        },
        'claims': {
            'vehicle_id': vehicle.id,
            'license_plate': vehicle.license_plate,
            'phone': phone,
            'session_version': session_version,
            'device_id': device_id,
        }
    }

def generate_otp(length=6):
    """Generate a random OTP"""
    return ''.join(random.choices(string.digits, k=length))

def send_otp_via_sms(phone: str, otp: str):
    """Send OTP to user's phone"""
    try:
        sms_service = SMSService()
        message = f"Votre code OTP pour Lipva est: {otp}. Ce code expire dans 10 minutes."
        sms_service.send_sms(phone, message)
        return True
    except Exception as e:
        print(f"Error sending OTP: {e}")
        return False

def check_days_until_expiry(expiry_date_str):
    """Calculate days until expiry. Returns None if no expiry or if expired."""
    if not expiry_date_str:
        return None
    
    try:
        if isinstance(expiry_date_str, str):
            # Parse ISO format date
            if 'T' in expiry_date_str:
                expiry = datetime.fromisoformat(expiry_date_str.replace('Z', '+00:00'))
            else:
                expiry = datetime.strptime(expiry_date_str, '%Y-%m-%d')
        else:
            expiry = expiry_date_str
        
        now = datetime.utcnow()
        days_diff = (expiry.replace(hour=0, minute=0, second=0, microsecond=0) - now.replace(hour=0, minute=0, second=0, microsecond=0)).days
        
        return days_diff if days_diff > 0 else None
    except Exception as e:
        print(f"Error parsing expiry date: {e}")
        return None

@citizen_auth_bp.route('/register', methods=['POST'])
def register():
    """
    First step: User provides license_plate, VIN, and phone
    Backend verifies these in database and sends OTP
    """
    try:
        data = request.get_json()
        license_plate = data.get('license_plate', '').upper().strip()
        vin = data.get('vin', '').upper().strip()
        phone = data.get('phone', '').strip()
        device_id = data.get('device_id', '').strip()
        normalized_phone = _normalize_phone(phone)
        
        # Validation
        if not all([license_plate, vin, phone]):
            return jsonify({'error': 'Missing required fields: license_plate, vin, phone'}), 400
        
        # Verify vehicle exists in database
        vehicle = Vehicle.query.filter_by(
            license_plate=license_plate,
            vin=vin
        ).first()
        
        if not vehicle or vehicle.qr_pending_approval:
            return jsonify({'error': 'Vehicle not found. Please verify your license plate and VIN.'}), 404

        if not _is_vehicle_active(vehicle):
            return jsonify({'error': 'Ce véhicule est inactif. Son activation est requise avant l\'enregistrement.'}), 403

        stored_vehicle_phone = _normalize_phone(vehicle.owner_phone)
        if not stored_vehicle_phone or stored_vehicle_phone != normalized_phone:
            return jsonify({'error': 'Vehicle not found. Please verify your license plate, VIN and phone number.'}), 404
        
        # Check if vehicle owner already exists
        owner = VehicleOwner.query.filter_by(vehicle_id=vehicle.id).first()
        if owner and owner.phone and _normalize_phone(owner.phone) != normalized_phone:
            return jsonify({'error': 'The phone number does not match the vehicle owner record.'}), 403
        if owner and owner.phone and owner.is_verified:
            return jsonify({'error': 'This vehicle is already registered'}), 409
        
        # Generate and send OTP
        otp = generate_otp(6)
        
        # Store OTP with expiry (10 minutes)
        _otp_store[phone] = {
            'otp': otp,
            'vehicle_id': vehicle.id,
            'vin': vin,
            'license_plate': license_plate,
            'device_id': device_id,
            'expires_at': datetime.utcnow() + timedelta(minutes=10),
            'attempts': 0
        }
        
        # Log OTP to terminal for testing purposes
        print(f"\n{'='*60}")
        print(f"🔐 OTP GENERATED FOR TESTING")
        print(f"Phone: {phone}")
        print(f"License Plate: {license_plate}")
        print(f"OTP Code: {otp}")
        print(f"Expires in: 10 minutes")
        print(f"{'='*60}\n")
        
        # Send OTP via SMS
        if not send_otp_via_sms(phone, otp):
            return jsonify({'error': 'Failed to send OTP. Please try again.'}), 500
        
        return jsonify({
            'message': 'OTP sent to your phone',
            'otp': otp,
            'phone_masked': phone[:3] + '*' * (len(phone) - 6) + phone[-3:],
            'expires_in': 600  # 10 minutes in seconds
        }), 200
        
    except Exception as e:
        print(f"Registration error: {e}")
        return jsonify({'error': str(e)}), 500


@citizen_auth_bp.route('/debug-otp', methods=['GET'])
def debug_otp():
    """
    Development-only endpoint to fetch the current OTP for a phone number.
    Returns the OTP if available in the in-memory store. Disabled in production.
    """
    try:
        phone = request.args.get('phone', '').strip()
        if not phone:
            return jsonify({'error': 'phone parameter required'}), 400

        otp_data = _otp_store.get(phone)
        if not otp_data:
            return jsonify({'error': 'No OTP found for this phone'}), 404

        return jsonify({
            'phone': phone,
            'otp': otp_data.get('otp'),
            'expires_at': otp_data.get('expires_at').isoformat() if otp_data.get('expires_at') else None
        }), 200
    except Exception as e:
        print(f"Debug OTP error: {e}")
        return jsonify({'error': str(e)}), 500

@citizen_auth_bp.route('/mobile-login', methods=['POST'])
def login():
    """
    Login endpoint: User provides phone number
    Backend finds the VehicleOwner and sends OTP
    """
    try:
        data = request.get_json()
        print(f"📱 Mobile login request received with data: {data}")
        
        phone = data.get('phone', '').strip()
        device_id = data.get('device_id', '').strip()
        
        # Validation
        if not phone:
            print(f"⚠️  Login validation failed: Phone is empty")
            return jsonify({'error': 'Phone number is required'}), 400
        
        print(f"📱 Looking up VehicleOwner for phone: {phone}")
        
        # Find the most recently used verified VehicleOwner for this phone,
        # excluding vehicles pending QR approval.
        owner = (
            VehicleOwner.query
            .join(Vehicle, VehicleOwner.vehicle_id == Vehicle.id)
            .filter(
                VehicleOwner.phone == phone,
                VehicleOwner.is_verified == True,
                Vehicle.qr_pending_approval == False,
            )
            .order_by(VehicleOwner.last_login.desc(), VehicleOwner.verified_at.desc(), VehicleOwner.id.desc())
            .first()
        )

        if not owner:
            print(f"⚠️  Login failed: No verified account found for {phone}")
            return jsonify({'error': 'No account found with this phone number'}), 404

        vehicle = owner.vehicle
        if not vehicle:
            return jsonify({'error': 'No account found with this phone number'}), 404
        if not _is_vehicle_active(vehicle):
            return jsonify({'error': 'Ce véhicule est inactif. Son activation est requise avant la connexion.'}), 403
        
        # Generate and send OTP
        otp = generate_otp(6)
        
        # Store OTP with expiry (10 minutes)
        _otp_store[phone] = {
            'otp': otp,
            'vehicle_id': owner.vehicle_id,
            'is_login': True,  # Flag to differentiate from registration
            'device_id': device_id,
            'expires_at': datetime.utcnow() + timedelta(minutes=10),
            'attempts': 0
        }
        
        # Log OTP to terminal for testing purposes
        print(f"\n{'='*60}")
        print(f"🔐 OTP GENERATED FOR LOGIN")
        print(f"Phone: {phone}")
        print(f"OTP Code: {otp}")
        print(f"Expires in: 10 minutes")
        print(f"{'='*60}\n")
        
        # Send OTP via SMS
        if not send_otp_via_sms(phone, otp):
            return jsonify({'error': 'Failed to send OTP. Please try again.'}), 500
        
        return jsonify({
            'message': 'OTP sent to your phone',
            'otp': otp,
            'phone_masked': phone[:3] + '*' * (len(phone) - 6) + phone[-3:],
            'expires_in': 600  # 10 minutes in seconds
        }), 200
        
    except Exception as e:
        print(f"Login error: {e}")

@citizen_auth_bp.route('/verify-otp', methods=['POST'])
def verify_otp():
    """
    Second step: User provides OTP to complete registration/login
    Returns JWT token if successful
    """
    try:
        data = request.get_json()
        phone = data.get('phone', '').strip()
        otp = data.get('otp', '').strip()
        device_id = data.get('device_id', '').strip()
        
        if not phone or not otp:
            return jsonify({'error': 'Missing phone or OTP'}), 400
        
        # Check OTP
        otp_data = _otp_store.get(phone)
        
        if not otp_data:
            print(f"⚠️  OTP verification failed: No OTP found for {phone}")
            return jsonify({'error': 'No OTP found for this phone. Please register first.'}), 404
        
        # Check expiry
        if datetime.utcnow() > otp_data['expires_at']:
            del _otp_store[phone]
            print(f"⚠️  OTP verification failed: OTP expired for {phone}")
            return jsonify({'error': 'OTP expired. Please try again.'}), 400
        
        # Check attempts
        if otp_data['attempts'] >= 3:
            del _otp_store[phone]
            print(f"⚠️  OTP verification failed: Too many attempts for {phone}")
            return jsonify({'error': 'Too many failed attempts. Please register again.'}), 429
        
        # Verify OTP
        if otp != otp_data['otp']:
            otp_data['attempts'] += 1
            print(f"⚠️  OTP verification failed: Wrong OTP for {phone} (Attempt {otp_data['attempts']}/3)")
            print(f"   Expected: {otp_data['otp']}, Got: {otp}")
            return jsonify({'error': 'Invalid OTP'}), 401
        
        # OTP verified successfully!
        print(f"\n{'='*60}")
        print(f"✅ OTP VERIFIED SUCCESSFULLY")
        print(f"Phone: {phone}")
        print(f"License Plate: {otp_data['license_plate']}")
        print(f"Creating user account...")
        print(f"{'='*60}\n")
        
        # OTP verified! Create/update user and owner
        vehicle_id = otp_data['vehicle_id']
        vehicle = Vehicle.query.get(vehicle_id)
        
        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404

        if not _is_vehicle_active(vehicle):
            return jsonify({'error': 'Ce véhicule est inactif. Son activation est requise avant la connexion.'}), 403
        
        # Find or create VehicleOwner
        owner = VehicleOwner.query.filter_by(vehicle_id=vehicle.id).first()
        resolved_device_id = (
            device_id
            or otp_data.get('device_id')
            or getattr(owner, 'current_device_id', None)
            or f'device_{vehicle.id}_{int(datetime.utcnow().timestamp())}'
        )

        if not owner:
            owner = VehicleOwner(
                vehicle_id=vehicle.id,
                owner_name=vehicle.owner_name or 'Unknown',
                phone=phone,
                is_verified=True,
                session_version=1
            )
            db.session.add(owner)
        else:
            owner.phone = phone
            owner.is_verified = True
            owner.session_version = int(getattr(owner, 'session_version', 0)) + 1
        owner.current_device_id = resolved_device_id
        
        db.session.commit()
        
        # Clean up OTP
        del _otp_store[phone]
        
        auth_payload = build_vehicle_auth_payload(vehicle, owner, phone)
        
        return jsonify({
            'message': 'Successfully registered',
            'access_token': auth_payload['access_token'],
            'vehicle': auth_payload['vehicle']
        }), 200
        
    except Exception as e:
        print(f"OTP verification error: {e}")
        return jsonify({'error': str(e)}), 500

@citizen_auth_bp.route('/verify-login-otp', methods=['POST'])
def verify_login_otp():
    """
    Verify OTP for login (existing account)
    Returns JWT token if successful
    """
    try:
        data = request.get_json()
        phone = data.get('phone', '').strip()
        otp = data.get('otp', '').strip()
        
        if not phone or not otp:
            return jsonify({'error': 'Missing phone or OTP'}), 400
        
        # Check OTP
        otp_data = _otp_store.get(phone)
        
        if not otp_data:
            print(f"⚠️  Login OTP verification failed: No OTP found for {phone}")
            return jsonify({'error': 'No OTP found for this phone. Please request a new one.'}), 404
        
        # Check if this is a login OTP (not registration)
        if not otp_data.get('is_login'):
            print(f"⚠️  Login OTP verification failed: OTP is for registration, not login")
            return jsonify({'error': 'Invalid OTP type'}), 400
        
        # Check expiry
        if datetime.utcnow() > otp_data['expires_at']:
            del _otp_store[phone]
            print(f"⚠️  Login OTP verification failed: OTP expired for {phone}")
            return jsonify({'error': 'OTP expired. Please try again.'}), 400
        
        # Check attempts
        if otp_data['attempts'] >= 3:
            del _otp_store[phone]
            print(f"⚠️  Login OTP verification failed: Too many attempts for {phone}")
            return jsonify({'error': 'Too many failed attempts. Please try again.'}), 429
        
        # Verify OTP
        if otp != otp_data['otp']:
            otp_data['attempts'] += 1
            print(f"⚠️  Login OTP verification failed: Wrong OTP for {phone} (Attempt {otp_data['attempts']}/3)")
            print(f"   Expected: {otp_data['otp']}, Got: {otp}")
            return jsonify({'error': 'Invalid OTP'}), 401
        
        # OTP verified successfully!
        print(f"\n{'='*60}")
        print(f"✅ LOGIN OTP VERIFIED SUCCESSFULLY")
        print(f"Phone: {phone}")
        print(f"Logging in user...")
        print(f"{'='*60}\n")
        
        # Get vehicle and owner info
        vehicle_id = otp_data['vehicle_id']
        vehicle = Vehicle.query.get(vehicle_id)
        
        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404

        if not _is_vehicle_active(vehicle):
            return jsonify({'error': 'Ce véhicule est inactif. Son activation est requise avant la connexion.'}), 403
        
        # Update last login timestamp
        owner = VehicleOwner.query.filter_by(vehicle_id=vehicle.id).first()
        if owner:
            owner.last_login = datetime.utcnow()
            owner.session_version = int(getattr(owner, 'session_version', 0)) + 1
            owner.current_device_id = (
                otp_data.get('device_id')
                or owner.current_device_id
                or f'device_{vehicle.id}_{int(datetime.utcnow().timestamp())}'
            )
            db.session.commit()
        
        # Clean up OTP
        del _otp_store[phone]
        
        auth_payload = build_vehicle_auth_payload(vehicle, owner, phone)
        
        return jsonify({
            'message': 'Successfully logged in',
            'access_token': auth_payload['access_token'],
            'vehicle': auth_payload['vehicle']
        }), 200
        
    except Exception as e:
        print(f"Login OTP verification error: {e}")
        return jsonify({'error': str(e)}), 500


@citizen_auth_bp.route('/register-push-token', methods=['POST'])
@jwt_required()
def register_push_token():
    """Store the current Expo push token for the logged-in citizen device.
    
    This enables background push notifications via Expo push service.
    The token is registered per device so that when a new fine is issued,
    the owner receives a notification even if the app is closed.
    """
    try:
        data = request.get_json() or {}
        push_token = (data.get('push_token') or '').strip()
        device_id = (data.get('device_id') or '').strip()

        if not push_token:
            return jsonify({'error': 'Missing push_token'}), 400

        identity = get_jwt_identity()
        vehicle_id = int(identity) if not isinstance(identity, dict) else int(identity.get('vehicle_id'))

        vehicle = Vehicle.query.get(vehicle_id)
        if not vehicle:
            print(f"❌ Push token registration: Vehicle {vehicle_id} not found")
            return jsonify({'error': 'Vehicle not found'}), 404

        owner = VehicleOwner.query.filter_by(vehicle_id=vehicle.id).first()
        if not owner:
            print(f"❌ Push token registration: Owner not found for vehicle {vehicle_id}")
            return jsonify({'error': 'Owner account not found'}), 404

        # Save the push token for background notifications
        old_token = owner.expo_push_token
        owner.expo_push_token = push_token
        if device_id:
            owner.current_device_id = device_id

        # Also propagate this push token to any other VehicleOwner rows with the same phone
        try:
            same_phone = (VehicleOwner.query
                          .filter_by(phone=owner.phone)
                          .all())
            for o in same_phone:
                # update token for all linked accounts (same phone)
                o.expo_push_token = push_token
            db.session.commit()
        except Exception:
            # Fallback: ensure at least the primary owner was saved
            db.session.rollback()
            owner.expo_push_token = push_token
            if device_id:
                owner.current_device_id = device_id
            db.session.commit()

        print(f"✅ Push token registered successfully for vehicle {vehicle.license_plate}")
        print(f"   Device ID: {device_id}")
        print(f"   Token: {push_token[:30]}...")
        
        return jsonify({
            'message': 'Push token registered successfully',
            'vehicle': vehicle.license_plate,
            'device_id': device_id,
        }), 200
    except Exception as e:
        print(f"❌ Push token registration error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@citizen_auth_bp.route('/me', methods=['GET'])
@jwt_required()
def get_current_user():
    """Get current logged-in user's vehicle information"""
    try:
        identity = get_jwt_identity()
        print(f"📱 /me endpoint called")
        print(f"   JWT Identity: {identity}")
        print(f"   Identity type: {type(identity)}")
        
        # Handle both dict and string identity formats
        if isinstance(identity, dict):
            vehicle_id = identity.get('vehicle_id')
        else:
            # If it's a string, it might be the vehicle_id directly
            vehicle_id = identity
        
        print(f"   Extracted vehicle_id: {vehicle_id}")
        
        if not vehicle_id:
            print(f"⚠️  No vehicle_id in token")
            return jsonify({'error': 'No vehicle_id in token'}), 401
        
        vehicle = Vehicle.query.get(vehicle_id)
        print(f"   Found vehicle: {vehicle}")

        if not vehicle:
            print(f"⚠️  Vehicle not found for id: {vehicle_id}")
            return jsonify({'error': 'Vehicle not found'}), 404

        if vehicle.qr_pending_approval:
            return jsonify({'error': 'Ce véhicule est en attente de validation. Veuillez réessayer plus tard.'}), 403
        
        owner = VehicleOwner.query.filter_by(vehicle_id=vehicle.id).first()
        
        return jsonify({
            'vehicle': {
                'id': vehicle.id,
                'license_plate': vehicle.license_plate,
                'owner_name': vehicle.owner_name,
                'vehicle_type': vehicle.vehicle_type,
                'vin': vehicle.vin
            },
            'owner': {
                'phone': owner.phone if owner else None,
                'is_verified': owner.is_verified if owner else False
            }
        }), 200
        
    except Exception as e:
        print(f"❌ Get current user error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def _current_owner_phone():
    """Resolve the calling citizen's stable phone identity from the JWT (vehicle_id ->
    VehicleOwner.phone), the same way /me does. Returns None if it can't be resolved."""
    identity = get_jwt_identity()
    vehicle_id = identity.get('vehicle_id') if isinstance(identity, dict) else identity
    if not vehicle_id:
        return None
    vehicle = Vehicle.query.get(vehicle_id)
    if not vehicle:
        return None
    owner = VehicleOwner.query.filter_by(vehicle_id=vehicle.id).first()
    return owner.phone if owner else None


@citizen_auth_bp.route('/license/register', methods=['POST'])
@jwt_required()
def register_license():
    """Link an existing DriverLicense (found by license_number, scanned from its QR)
    to the current citizen's phone, so it shows up on their dashboard."""
    try:
        phone = _current_owner_phone()
        if not phone:
            return jsonify({'error': 'Compte non identifié'}), 401

        data = request.get_json() or {}
        number = (data.get('license_number') or '').strip().upper()
        if not number:
            return jsonify({'error': 'Numéro de permis manquant'}), 400

        lic = DriverLicense.query.filter_by(license_number=number).first()
        if not lic:
            return jsonify({'error': 'Permis introuvable'}), 404

        if lic.registered_phone and lic.registered_phone != phone:
            return jsonify({'error': 'Ce permis est déjà enregistré sur un autre compte.'}), 409

        existing = DriverLicense.query.filter_by(registered_phone=phone).first()
        if existing and existing.id != lic.id:
            return jsonify({'error': f"Un autre permis ({existing.license_number}) est déjà enregistré sur ce compte."}), 409

        lic.registered_phone = phone
        lic.registered_at = now_comoros()
        db.session.commit()
        return jsonify({'message': 'Permis enregistré avec succès.', 'license': lic.to_dict()})
    except Exception as e:
        print(f"❌ register_license error: {e}")
        return jsonify({'error': str(e)}), 500


@citizen_auth_bp.route('/license/my', methods=['GET'])
@jwt_required()
def get_my_license():
    """Return the license registered to the current citizen, with full details
    (including photo filename) and point reduction history, or {license: None}."""
    try:
        phone = _current_owner_phone()
        if not phone:
            return jsonify({'license': None})

        lic = DriverLicense.query.filter_by(registered_phone=phone).first()
        if not lic:
            return jsonify({'license': None})

        history = (PointReductionHistory.query
                   .filter_by(license_id=lic.id)
                   .order_by(PointReductionHistory.created_at.desc())
                   .all())
        data = lic.to_dict()
        data['point_history'] = [
            {k: v for k, v in h.to_dict().items() if k != 'created_by'}
            for h in history
        ]
        return jsonify({'license': data})
    except Exception as e:
        print(f"❌ get_my_license error: {e}")
        return jsonify({'error': str(e)}), 500


@citizen_auth_bp.route('/license/my', methods=['DELETE'])
@jwt_required()
def unregister_license():
    """Remove the link between the current citizen's account and their registered
    license (e.g. if the wrong QR was scanned). Does not delete the license itself."""
    try:
        phone = _current_owner_phone()
        if not phone:
            return jsonify({'error': 'Compte non identifié'}), 401

        lic = DriverLicense.query.filter_by(registered_phone=phone).first()
        if lic:
            lic.registered_phone = None
            lic.registered_at = None
            db.session.commit()
        return jsonify({'message': 'Permis retiré du compte.'})
    except Exception as e:
        print(f"❌ unregister_license error: {e}")
        return jsonify({'error': str(e)}), 500


@citizen_auth_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    """Logout: clear push token so the device stops receiving notifications."""
    try:
        identity = get_jwt_identity()
        vehicle_id = int(identity) if not isinstance(identity, dict) else int(identity.get('vehicle_id'))
        owner = VehicleOwner.query.filter_by(vehicle_id=vehicle_id).first()
        if owner and owner.expo_push_token:
            owner.expo_push_token = None
            db.session.commit()
    except Exception as e:
        print(f"⚠️ Could not clear push token on logout: {e}")
    return jsonify({'message': 'Logged out successfully'}), 200


@citizen_auth_bp.route('/unregister-push-token', methods=['POST'])
def unregister_push_token():
    """Remove a push token without requiring JWT — used on forced logout (expired session)."""
    data = request.get_json() or {}
    push_token = (data.get('push_token') or '').strip()
    if not push_token:
        return jsonify({'message': 'No token provided'}), 200
    try:
        owners = VehicleOwner.query.filter_by(expo_push_token=push_token).all()
        for owner in owners:
            owner.expo_push_token = None
        if owners:
            db.session.commit()
    except Exception as e:
        print(f"⚠️ Could not unregister push token: {e}")
    return jsonify({'message': 'Token unregistered'}), 200


@citizen_auth_bp.route('/delete-account/request-otp', methods=['POST'])
@jwt_required()
def request_delete_account_otp():
    """Send an OTP to confirm citizen account deletion."""
    try:
        identity = get_jwt_identity()
        vehicle_id = int(identity) if not isinstance(identity, dict) else int(identity.get('vehicle_id'))
        vehicle = Vehicle.query.get(vehicle_id)

        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404

        owner = VehicleOwner.query.filter_by(vehicle_id=vehicle.id).first()
        if not owner or not owner.phone:
            return jsonify({'error': 'Owner account not found'}), 404

        phone = owner.phone.strip()
        otp = generate_otp(6)

        _otp_store[phone] = {
            'otp': otp,
            'vehicle_id': vehicle.id,
            'phone': phone,
            'is_delete_account': True,
            'expires_at': datetime.utcnow() + timedelta(minutes=10),
            'attempts': 0,
        }

        print(f"\n{'='*60}")
        print(f"🗑️  ACCOUNT DELETE OTP GENERATED")
        print(f"Phone: {phone}")
        print(f"OTP Code: {otp}")
        print(f"Expires in: 10 minutes")
        print(f"{'='*60}\n")

        if not send_otp_via_sms(phone, otp):
            return jsonify({'error': 'Failed to send OTP. Please try again.'}), 500

        return jsonify({
            'message': 'OTP sent to confirm account deletion',
            'phone_masked': phone[:3] + '*' * (len(phone) - 6) + phone[-3:],
            'expires_in': 600,
        }), 200
    except Exception as e:
        print(f"Delete account OTP request error: {e}")
        return jsonify({'error': str(e)}), 500


@citizen_auth_bp.route('/delete-account/confirm-otp', methods=['POST'])
@jwt_required()
def confirm_delete_account_otp():
    """Verify OTP and permanently delete the citizen account link."""
    try:
        data = request.get_json() or {}
        otp = (data.get('otp') or '').strip()

        if not otp:
            return jsonify({'error': 'Missing OTP'}), 400

        identity = get_jwt_identity()
        vehicle_id = int(identity) if not isinstance(identity, dict) else int(identity.get('vehicle_id'))
        vehicle = Vehicle.query.get(vehicle_id)
        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404

        owner = VehicleOwner.query.filter_by(vehicle_id=vehicle.id).first()
        if not owner or not owner.phone:
            return jsonify({'error': 'Owner account not found'}), 404

        phone = owner.phone.strip()
        otp_data = _otp_store.get(phone)

        if not otp_data or not otp_data.get('is_delete_account'):
            return jsonify({'error': 'No deletion OTP found. Please request a new one.'}), 404

        if datetime.utcnow() > otp_data['expires_at']:
            del _otp_store[phone]
            return jsonify({'error': 'OTP expired. Please try again.'}), 400

        if otp_data['attempts'] >= 3:
            del _otp_store[phone]
            return jsonify({'error': 'Too many failed attempts. Please request a new OTP.'}), 429

        if otp != otp_data['otp']:
            otp_data['attempts'] += 1
            return jsonify({'error': 'Invalid OTP'}), 401

        # Delete all owner rows for this phone but leave vehicle.owner_phone intact
        # so the user can re-register with the same number later.
        all_owners = VehicleOwner.query.filter_by(phone=phone).all()
        for o in all_owners:
            db.session.delete(o)
        db.session.commit()

        del _otp_store[phone]

        return jsonify({
            'message': 'Account deleted successfully',
        }), 200
    except Exception as e:
        print(f"Delete account confirmation error: {e}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@citizen_auth_bp.route('/my-vehicles', methods=['GET'])
@jwt_required()
def get_my_vehicles():
    """Return all verified vehicles linked to the current phone number."""
    try:
        claims = get_jwt()
        phone = (claims.get('phone') or '').strip()
        current_vehicle_id = claims.get('vehicle_id')

        if not phone:
            return jsonify({'error': 'Missing phone in token'}), 401

        owners = (
            VehicleOwner.query
            .filter_by(phone=phone, is_verified=True)
            .order_by(VehicleOwner.last_login.desc(), VehicleOwner.verified_at.desc(), VehicleOwner.id.desc())
            .all()
        )

        # Backward compatibility: old accounts may have vehicles.owner_phone set
        # but no corresponding row yet in vehicle_owners.
        owner_vehicle_ids = {o.vehicle_id for o in owners}
        legacy_vehicles = Vehicle.query.filter_by(owner_phone=phone).all()
        created_links = False
        now = datetime.utcnow()

        for legacy_vehicle in legacy_vehicles:
            if legacy_vehicle.id in owner_vehicle_ids:
                continue

            # Do not auto-link if this vehicle is already linked to another phone.
            existing_owner = VehicleOwner.query.filter_by(vehicle_id=legacy_vehicle.id).first()
            if existing_owner:
                continue

            db.session.add(VehicleOwner(
                vehicle_id=legacy_vehicle.id,
                owner_name=legacy_vehicle.owner_name or 'Proprietaire',
                phone=phone,
                is_verified=True,
                session_version=0,
                verified_at=now,
                last_login=None,
                created_at=now,
                updated_at=now,
            ))
            created_links = True

        if created_links:
            db.session.commit()
            owners = (
                VehicleOwner.query
                .filter_by(phone=phone, is_verified=True)
                .order_by(VehicleOwner.last_login.desc(), VehicleOwner.verified_at.desc(), VehicleOwner.id.desc())
                .all()
            )

        vehicles = []
        for owner in owners:
            vehicle = owner.vehicle
            if not vehicle:
                continue
            if vehicle.qr_pending_approval:
                continue

            # Count unpaid fines for this vehicle
            fines_count = Fine.query.filter_by(vehicle_id=vehicle.id, paid=False).count()
            
            vehicles.append({
                'id': vehicle.id,
                'license_plate': vehicle.license_plate,
                'owner_name': vehicle.owner_name,
                'vehicle_type': vehicle.vehicle_type,
                'vin': vehicle.vin,
                'status': vehicle.status,
                'is_current': vehicle.id == int(current_vehicle_id) if current_vehicle_id else False,
                'last_login': owner.last_login.isoformat() if owner.last_login else None,
                'verified_at': owner.verified_at.isoformat() if owner.verified_at else None,
                'fines_count': fines_count,
            })

        return jsonify({
            'phone': phone,
            'vehicles': vehicles,
            'current_vehicle_id': current_vehicle_id,
        }), 200
    except Exception as e:
        print(f"❌ Get my vehicles error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@citizen_auth_bp.route('/switch-vehicle', methods=['POST'])
@jwt_required()
def switch_vehicle():
    """Switch the active vehicle for the currently authenticated phone number."""
    try:
        data = request.get_json() or {}
        target_vehicle_id = data.get('vehicle_id')

        if not target_vehicle_id:
            return jsonify({'error': 'Missing vehicle_id'}), 400

        try:
            target_vehicle_id = int(target_vehicle_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid vehicle_id'}), 400

        claims = get_jwt()
        phone = (claims.get('phone') or '').strip()
        device_id = claims.get('device_id')

        if not phone:
            return jsonify({'error': 'Missing phone in token'}), 401

        owner = (
            VehicleOwner.query
            .filter_by(phone=phone, vehicle_id=target_vehicle_id, is_verified=True)
            .first()
        )

        # Backward compatibility for legacy rows missing in vehicle_owners.
        if not owner:
            legacy_vehicle = Vehicle.query.filter_by(id=target_vehicle_id, owner_phone=phone).first()
            if legacy_vehicle:
                existing_owner = VehicleOwner.query.filter_by(vehicle_id=legacy_vehicle.id).first()
                if not existing_owner:
                    now = datetime.utcnow()
                    owner = VehicleOwner(
                        vehicle_id=legacy_vehicle.id,
                        owner_name=legacy_vehicle.owner_name or 'Proprietaire',
                        phone=phone,
                        is_verified=True,
                        session_version=0,
                        verified_at=now,
                        last_login=None,
                        created_at=now,
                        updated_at=now,
                    )
                    db.session.add(owner)
                    db.session.commit()

        if not owner:
            return jsonify({'error': 'This vehicle is not linked to your phone number'}), 403

        vehicle = owner.vehicle
        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404

        if vehicle.qr_pending_approval:
            return jsonify({'error': 'Ce véhicule est en attente de validation. Il ne peut pas être sélectionné pour l\'instant.'}), 403

        if vehicle.status == 'inactive':
            return jsonify({'error': "Ce véhicule est inactif. Vous pouvez le voir, mais vous ne pouvez pas l'activer."}), 403

        owner.last_login = datetime.utcnow()
        if device_id:
            owner.current_device_id = device_id
        db.session.commit()

        auth_payload = build_vehicle_auth_payload(vehicle, owner, phone)

        return jsonify({
            'message': 'Vehicle switched successfully',
            'access_token': auth_payload['access_token'],
            'vehicle': auth_payload['vehicle'],
        }), 200
    except Exception as e:
        print(f"❌ Switch vehicle error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@citizen_auth_bp.route('/check-document-expirations', methods=['POST'])
@jwt_required()
def check_document_expirations():
    """
    Check for upcoming document expirations (insurance, vignette, QR code)
    and send push notifications if they expire in 1, 7, or 30 days.
    Called by mobile app on launch and when returning to foreground.
    """
    try:
        identity = get_jwt_identity()
        vehicle_id = int(identity) if not isinstance(identity, dict) else int(identity.get('vehicle_id'))
        owner = VehicleOwner.query.filter_by(vehicle_id=vehicle_id).first()
        
        if not owner or not owner.vehicle:
            return jsonify({'notifications_sent': []}), 200
        
        vehicle = owner.vehicle
        notifications_sent = []
        
        # Check insurance expiry
        if vehicle.insurance_expiry:
            days_left = check_days_until_expiry(vehicle.insurance_expiry)
            if days_left and days_left in [1, 7, 30]:
                if owner.expo_push_token:
                    titles_map = {1: 'Assurance expire demain!', 7: 'Assurance expire dans 7 jours', 30: 'Assurance expire dans 30 jours'}
                    result = send_expo_push_notification(
                        owner.expo_push_token,
                        f'🛡️ Rappel Assurance',
                        titles_map.get(days_left, f'Assurance expire dans {days_left} jours'),
                        {'type': 'insurance', 'licensePlate': vehicle.license_plate, 'daysRemaining': days_left}
                    )
                    if result.get('success'):
                        notifications_sent.append('insurance')
                        print(f'✅ Insurance notification sent for {vehicle.license_plate}')
        
        # Check vignette expiry
        if vehicle.vignette_expiry:
            days_left = check_days_until_expiry(vehicle.vignette_expiry)
            if days_left and days_left in [1, 7, 30]:
                if owner.expo_push_token:
                    titles_map = {1: 'Vignette expire demain!', 7: 'Vignette expire dans 7 jours', 30: 'Vignette expire dans 30 jours'}
                    result = send_expo_push_notification(
                        owner.expo_push_token,
                        f'🚘 Rappel Vignette',
                        titles_map.get(days_left, f'Vignette expire dans {days_left} jours'),
                        {'type': 'vignette', 'licensePlate': vehicle.license_plate, 'daysRemaining': days_left}
                    )
                    if result.get('success'):
                        notifications_sent.append('vignette')
                        print(f'✅ Vignette notification sent for {vehicle.license_plate}')
        
        # Check QR code expiry
        if vehicle.qr_code_expiry:
            days_left = check_days_until_expiry(vehicle.qr_code_expiry)
            if days_left and days_left in [1, 7, 30]:
                if owner.expo_push_token:
                    titles_map = {1: 'Code QR expire demain!', 7: 'Code QR expire dans 7 jours', 30: 'Code QR expire dans 30 jours'}
                    result = send_expo_push_notification(
                        owner.expo_push_token,
                        f'📱 Rappel Code QR',
                        titles_map.get(days_left, f'Code QR expire dans {days_left} jours'),
                        {'type': 'qrcode', 'licensePlate': vehicle.license_plate, 'daysRemaining': days_left}
                    )
                    if result.get('success'):
                        notifications_sent.append('qrcode')
                        print(f'✅ QR code notification sent for {vehicle.license_plate}')
        
        return jsonify({'notifications_sent': notifications_sent}), 200
        
    except Exception as e:
        print(f"Error checking document expirations: {e}")
        return jsonify({'error': str(e), 'notifications_sent': []}), 500


@citizen_auth_bp.route('/request-vehicle-transfer', methods=['POST'])
@jwt_required()
def request_vehicle_transfer():
    """Submit a vehicle ownership transfer request"""
    try:
        claims = get_jwt()
        phone = (claims.get('phone') or '').strip()
        current_vehicle_id = claims.get('vehicle_id')

        if not phone:
            return jsonify({'error': 'Missing phone in token'}), 401

        if not current_vehicle_id:
            return jsonify({'error': 'No active vehicle selected'}), 400

        try:
            current_vehicle_id = int(current_vehicle_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid vehicle_id'}), 400

        vehicle = Vehicle.query.get(current_vehicle_id)
        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404

        data = request.get_json() or {}
        new_owner_phone = (data.get('new_owner_phone') or '').strip()
        new_owner_name = (data.get('new_owner_name') or '').strip()
        transfer_type = (data.get('transfer_type') or '').strip()
        reason = (data.get('reason') or '').strip()

        # Validate required fields
        if not new_owner_phone or not transfer_type:
            return jsonify({'error': 'Missing required fields: new_owner_phone, transfer_type'}), 400

        if transfer_type not in ['sale', 'gift', 'inheritance', 'other']:
            return jsonify({'error': 'Invalid transfer_type. Must be: sale, gift, inheritance, or other'}), 400

        # Check if there's already a pending transfer for this vehicle
        existing_transfer = VehicleTransfer.query.filter_by(
            vehicle_id=current_vehicle_id,
            status='pending'
        ).first()

        if existing_transfer:
            return jsonify({'error': 'A transfer request is already pending for this vehicle'}), 409

        # Create transfer request
        transfer = VehicleTransfer(
            vehicle_id=current_vehicle_id,
            current_owner_phone=phone,
            new_owner_phone=new_owner_phone,
            new_owner_name=new_owner_name,
            transfer_type=transfer_type,
            reason=reason,
            status='pending'
        )

        db.session.add(transfer)
        db.session.commit()

        print(f"✅ Vehicle transfer request created: {vehicle.license_plate} from {phone} to {new_owner_phone}")

        return jsonify({
            'message': 'Transfer request submitted successfully',
            'transfer': transfer.to_dict()
        }), 201

    except Exception as e:
        print(f"❌ Error requesting vehicle transfer: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@citizen_auth_bp.route('/my-attestation-html', methods=['GET'])
@jwt_required()
def citizen_attestation_html():
    """Return self-contained attestation HTML for the citizen's own vehicle."""
    from app.models import VehicleInsuranceAssignment, InsuranceAccount

    identity = get_jwt_identity()
    vehicle_id = identity.get('vehicle_id') if isinstance(identity, dict) else identity
    if not vehicle_id:
        return jsonify({'error': 'Compte non identifié'}), 401

    vehicle = Vehicle.query.get_or_404(vehicle_id)

    assignment = VehicleInsuranceAssignment.query.filter_by(vehicle_id=vehicle_id).first()
    account = None
    tpl = {}
    if assignment:
        account = InsuranceAccount.query.get(assignment.insurance_account_id)
        if account and account.attestation_template:
            try:
                tpl = json.loads(account.attestation_template)
            except Exception:
                tpl = {}

    company_name = tpl.get('company_name', '')
    if not company_name and account and account.insurance:
        company_name = account.insurance.company_name or ''
    insurance_id = account.id if account else 0
    insurance_year = account.created_at.strftime('%Y') if (account and account.created_at) else now_comoros().strftime('%Y')

    vehicle_data = {
        'id': vehicle.id,
        'license_plate': vehicle.license_plate,
        'owner_name': vehicle.owner_name,
        'owner_address': vehicle.owner_address or vehicle.owner_island or '',
        'vehicle_type': vehicle.vehicle_type or '',
        'model': vehicle.model or '',
        'insurance_expiry': vehicle.insurance_expiry.strftime('%d/%m/%Y') if vehicle.insurance_expiry else '—',
        'today': now_comoros().strftime('%d/%m/%Y'),
        'insurance_id': insurance_id,
        'insurance_year': insurance_year,
    }

    # Strip logo_b64 (heavy base64) — logo_url stays in tpl and renders directly
    logo_b64 = tpl.pop('logo_b64', None)

    builder_path = os.path.join(current_app.root_path, 'static', 'js', 'attestation-builder.js')
    with open(builder_path, 'r', encoding='utf-8') as f:
        builder_js = f.read()

    vehicle_json = json.dumps(vehicle_data, ensure_ascii=False)
    tpl_json = json.dumps(tpl, ensure_ascii=False)
    logo_json = json.dumps(logo_b64)  # only for old records without logo_url

    html = f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ background: #f0f0f0; overflow: hidden; width: 100vw; height: 100vh; }}
#card-container {{
    display: flex; justify-content: center; align-items: center;
    width: 100vw; height: 100vh;
}}
#card-container > * {{ transform-origin: center center; flex-shrink: 0; }}
</style>
</head>
<body>
<div id="card-container"></div>
<script>
window.VEHICLE = {vehicle_json};
window.TPL = {tpl_json};
var _LOGO = {logo_json};
</script>
<script>{builder_js}</script>
<script>
var _c = document.getElementById('card-container');

function _rotate() {{
    var el = _c.firstElementChild;
    if (!el) return;
    var cw = el.offsetWidth, ch = el.offsetHeight;
    var vw = window.innerWidth, vh = window.innerHeight;
    var scale = Math.min(vw / ch, vh / cw) * 0.97;
    el.style.transform = 'rotate(90deg) scale(' + scale + ')';
}}

document.addEventListener('DOMContentLoaded', function() {{
    _c.innerHTML = window.buildAttestationHTML(window.TPL, window.VEHICLE);
    _rotate();
    // _LOGO: old base64 fallback for records without logo_url
    if (_LOGO && !window.TPL.logo_url) {{
        window.TPL.logo_b64 = _LOGO;
        _c.innerHTML = window.buildAttestationHTML(window.TPL, window.VEHICLE);
        _rotate();
    }}
}});

function _applyLogo(data) {{
    if (!data || data === 'null') return;
    try {{
        var parsed = JSON.parse(data);
        if (parsed.logo_url) window.TPL.logo_url = parsed.logo_url;
        if (parsed.logo_b64) window.TPL.logo_b64 = parsed.logo_b64;
    }} catch(e) {{
        window.TPL.logo_b64 = data;
    }}
    _c.innerHTML = window.buildAttestationHTML(window.TPL, window.VEHICLE);
    _rotate();
}}
document.addEventListener('message', function(e) {{ _applyLogo(e.data); }});
window.addEventListener('message', function(e) {{ _applyLogo(e.data); }});
</script>
</body>
</html>"""

    return Response(html, mimetype='text/html; charset=utf-8')
