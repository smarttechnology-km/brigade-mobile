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
from flask import Blueprint, request, jsonify, current_app, Response, render_template
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, get_jwt
from app.models import db, Vehicle, User, VehicleOwner, Fine, VehicleTransfer, DriverLicense, PointReductionHistory, LicenseFine
from app import limiter
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
        
        if expiry.tzinfo is not None:
            expiry = expiry.replace(tzinfo=None)
        now = now_comoros().replace(tzinfo=None)
        days_diff = (expiry.replace(hour=0, minute=0, second=0, microsecond=0) - now.replace(hour=0, minute=0, second=0, microsecond=0)).days
        
        return days_diff if days_diff > 0 else None
    except Exception as e:
        print(f"Error parsing expiry date: {e}")
        return None

@citizen_auth_bp.route('/register', methods=['POST'])
@limiter.limit('5/minute')
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
            'expires_at': now_comoros() + timedelta(minutes=10),
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
@limiter.limit('5/minute')
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
            'expires_at': now_comoros() + timedelta(minutes=10),
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
@limiter.limit('10/minute')
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
        if now_comoros() > otp_data['expires_at']:
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
            or f'device_{vehicle.id}_{int(now_comoros().timestamp())}'
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
@limiter.limit('10/minute')
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
        if now_comoros() > otp_data['expires_at']:
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
            owner.last_login = now_comoros()
            owner.session_version = int(getattr(owner, 'session_version', 0)) + 1
            owner.current_device_id = (
                otp_data.get('device_id')
                or owner.current_device_id
                or f'device_{vehicle.id}_{int(now_comoros().timestamp())}'
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
        fines = (LicenseFine.query
                 .filter_by(license_id=lic.id)
                 .order_by(LicenseFine.issued_at.desc())
                 .all())

        fine_by_history = {f.history_id: f for f in fines if f.history_id}

        data = lic.to_dict()
        data['point_history'] = []
        for h in history:
            row = {k: v for k, v in h.to_dict().items() if k != 'created_by'}
            fine = fine_by_history.get(h.id)
            row['fine_paid'] = fine.paid if fine else None
            row['fine_amount'] = float(fine.amount) if fine else None
            row['fine_paid_at'] = fine.paid_at.strftime('%d/%m/%Y %H:%M') if (fine and fine.paid_at) else None
            data['point_history'].append(row)
        data['fines'] = [f.to_dict() for f in fines]
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
@limiter.limit('5/minute')
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
            'expires_at': now_comoros() + timedelta(minutes=10),
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
@limiter.limit('10/minute')
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

        if now_comoros() > otp_data['expires_at']:
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
        now = now_comoros()

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
                    now = now_comoros()
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

        owner.last_login = now_comoros()
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


@citizen_auth_bp.route('/my-technical-inspection-attestation-html', methods=['GET'])
@jwt_required()
def citizen_technical_inspection_attestation_html():
    """Return self-contained technical-inspection attestation HTML for the citizen's own vehicle."""
    from app.models import TechnicalInspection, CarteGriseSetting, TECHNICAL_INSPECTION_ITEMS, TECHNICAL_INSPECTION_SCORE_MAX

    identity = get_jwt_identity()
    vehicle_id = identity.get('vehicle_id') if isinstance(identity, dict) else identity
    if not vehicle_id:
        return jsonify({'error': 'Compte non identifié'}), 401

    vehicle = Vehicle.query.get_or_404(vehicle_id)

    insp = (TechnicalInspection.query
            .filter_by(vehicle_id=vehicle.id, status='approved', smarttech_print_validated=True, payment_status='paid')
            .order_by(TechnicalInspection.issued_at.desc())
            .first())
    if not insp:
        pending_payment = (TechnicalInspection.query
                            .filter_by(vehicle_id=vehicle.id, status='approved', payment_status='unpaid')
                            .first())
        if pending_payment:
            return jsonify({'error': "Le paiement de la visite technique doit être effectué avant de pouvoir consulter l'attestation."}), 404
        pending_validation = (TechnicalInspection.query
                              .filter_by(vehicle_id=vehicle.id, status='approved', smarttech_print_validated=False, payment_status='paid')
                              .first())
        if pending_validation:
            return jsonify({'error': "Votre attestation est en attente de validation par SmartTech avant de pouvoir être consultée."}), 404
        return jsonify({'error': "Aucune attestation de visite technique disponible pour ce véhicule."}), 404

    island = vehicle.owner_island or 'Grande Comore'
    cg_settings = CarteGriseSetting.get(island)

    vehicle_qr_data_uri = None
    if vehicle.track_token:
        try:
            import qrcode, io, base64 as _b64
            _qr = qrcode.QRCode(box_size=5, border=2)
            _qr.add_data(f'VEHICLE_TRACK:{vehicle.track_token}')
            _qr.make(fit=True)
            _img = _qr.make_image(fill_color='black', back_color='white')
            _buf = io.BytesIO()
            _img.save(_buf, format='PNG')
            vehicle_qr_data_uri = 'data:image/png;base64,' + _b64.b64encode(_buf.getvalue()).decode()
        except Exception:
            pass

    html = render_template('citizen_visite_technique_attestation.html',
                           vehicle=vehicle, insp=insp,
                           cg_settings=cg_settings,
                           now_comoros=now_comoros,
                           checklist_items=TECHNICAL_INSPECTION_ITEMS,
                           checklist_result=json.loads(insp.checklist) if insp.checklist else {},
                           score_max=TECHNICAL_INSPECTION_SCORE_MAX,
                           vehicle_qr_data_uri=vehicle_qr_data_uri)
    return Response(html, mimetype='text/html; charset=utf-8')


@citizen_auth_bp.route('/technical-inspection-appointments/price', methods=['GET'])
@jwt_required()
def citizen_technical_inspection_appointment_price():
    """Preview the technical-inspection price for the citizen's own vehicle, before
    booking — free (no price shown) when the vehicle qualifies for a free re-visit
    following a rejection within the last month."""
    from app.models import TECHNICAL_INSPECTION_APPOINTMENT_SLOTS
    from app.mobile_pay import _get_technical_inspection_price
    from app.routes import _free_reinspection_source

    identity = get_jwt_identity()
    vehicle_id = identity.get('vehicle_id') if isinstance(identity, dict) else identity
    if not vehicle_id:
        return jsonify({'error': 'Compte non identifié'}), 401

    vehicle = Vehicle.query.get_or_404(int(vehicle_id))
    free_source = _free_reinspection_source(int(vehicle_id))
    if free_source:
        from dateutil.relativedelta import relativedelta
        free_deadline = free_source.reviewed_at + relativedelta(months=1)
        return jsonify({
            'price_kmf': 0,
            'is_free': True,
            'free_reason': f"Nouvelle visite gratuite (suite au rejet du {free_source.reviewed_at.strftime('%d/%m/%Y')}, déjà payée)",
            'free_until': free_deadline.strftime('%d/%m/%Y'),
            'slots': TECHNICAL_INSPECTION_APPOINTMENT_SLOTS,
        })
    from app.mobile_pay import _get_technical_inspection_duration_months
    price = _get_technical_inspection_price(vehicle)
    duration_months = _get_technical_inspection_duration_months(vehicle)
    return jsonify({'price_kmf': price, 'duration_months': duration_months, 'is_free': False, 'slots': TECHNICAL_INSPECTION_APPOINTMENT_SLOTS})


@citizen_auth_bp.route('/technical-inspection-appointments/my', methods=['GET'])
@jwt_required()
def citizen_list_technical_inspection_appointments():
    from app.models import TechnicalInspectionAppointment
    identity = get_jwt_identity()
    vehicle_id = identity.get('vehicle_id') if isinstance(identity, dict) else identity
    if not vehicle_id:
        return jsonify({'error': 'Compte non identifié'}), 401

    appointments = (TechnicalInspectionAppointment.query
                    .filter_by(vehicle_id=int(vehicle_id))
                    .order_by(TechnicalInspectionAppointment.created_at.desc())
                    .all())
    return jsonify([a.to_dict() for a in appointments])


@citizen_auth_bp.route('/technical-inspection-appointments', methods=['POST'])
@jwt_required()
def citizen_create_technical_inspection_appointment():
    from app.models import TechnicalInspectionAppointment, TECHNICAL_INSPECTION_APPOINTMENT_SLOTS, TECHNICAL_INSPECTION_APPOINTMENT_SLOT_CAPACITY
    from app.mobile_pay import _get_technical_inspection_price

    identity = get_jwt_identity()
    vehicle_id = identity.get('vehicle_id') if isinstance(identity, dict) else identity
    if not vehicle_id:
        return jsonify({'error': 'Compte non identifié'}), 401

    vehicle = Vehicle.query.get_or_404(int(vehicle_id))

    existing = TechnicalInspectionAppointment.query.filter(
        TechnicalInspectionAppointment.vehicle_id == vehicle.id,
        TechnicalInspectionAppointment.status.in_(['confirmed', 'pending_payment'])
    ).first()
    if existing:
        return jsonify({'error': 'Vous avez déjà un rendez-vous en cours pour ce véhicule.'}), 400

    data = request.get_json() or {}
    date_str = (data.get('appointment_date') or '').strip()
    time_str = (data.get('appointment_time') or '').strip()

    try:
        appointment_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return jsonify({'error': 'Date invalide.'}), 400

    if appointment_date.weekday() > 4:
        return jsonify({'error': 'Les rendez-vous sont disponibles du lundi au vendredi uniquement.'}), 400

    today = now_comoros().date()
    if appointment_date < today:
        return jsonify({'error': 'La date choisie est déjà passée.'}), 400

    if time_str not in TECHNICAL_INSPECTION_APPOINTMENT_SLOTS:
        return jsonify({'error': 'Créneau horaire invalide.'}), 400

    if appointment_date == today:
        now_time = now_comoros().strftime('%H:%M')
        if time_str <= now_time:
            return jsonify({'error': "Ce créneau est déjà passé pour aujourd'hui."}), 400

    slot_count = TechnicalInspectionAppointment.query.filter(
        TechnicalInspectionAppointment.appointment_date == appointment_date,
        TechnicalInspectionAppointment.appointment_time == time_str,
        TechnicalInspectionAppointment.status == 'confirmed'
    ).count()
    if slot_count >= TECHNICAL_INSPECTION_APPOINTMENT_SLOT_CAPACITY:
        return jsonify({'error': 'Ce créneau est complet (5 véhicules maximum). Veuillez choisir un autre horaire.'}), 400

    # Payment happens in-app right after booking (see /pay/create,
    # payment_type='technical_inspection_appointment'). The slot is only reserved
    # as 'confirmed' once payment succeeds — until then it sits as
    # 'pending_payment', so an abandoned/cancelled payment never leaves a
    # confirmed-looking appointment behind. Skipped entirely for a free re-visit.
    from app.routes import _free_reinspection_source
    from app.mobile_pay import _get_technical_inspection_duration_months
    free_source = _free_reinspection_source(vehicle.id)
    appointment = TechnicalInspectionAppointment(
        vehicle_id=vehicle.id,
        appointment_date=appointment_date,
        appointment_time=time_str,
        status='confirmed' if free_source else 'pending_payment',
        channel='app_citoyen',
        price_kmf=0 if free_source else _get_technical_inspection_price(vehicle),
        duration_months=_get_technical_inspection_duration_months(vehicle),
        paid_at=now_comoros() if free_source else None,
    )
    db.session.add(appointment)
    db.session.commit()
    return jsonify(appointment.to_dict()), 201


@citizen_auth_bp.route('/technical-inspection-appointments/<int:appointment_id>', methods=['PUT'])
@jwt_required()
def citizen_update_technical_inspection_appointment(appointment_id):
    from app.models import TechnicalInspectionAppointment, TECHNICAL_INSPECTION_APPOINTMENT_SLOTS, TECHNICAL_INSPECTION_APPOINTMENT_SLOT_CAPACITY

    identity = get_jwt_identity()
    vehicle_id = identity.get('vehicle_id') if isinstance(identity, dict) else identity
    if not vehicle_id:
        return jsonify({'error': 'Compte non identifié'}), 401

    appointment = TechnicalInspectionAppointment.query.get_or_404(appointment_id)
    if appointment.vehicle_id != int(vehicle_id):
        return jsonify({'error': 'Accès refusé'}), 403
    if appointment.status not in ('confirmed', 'pending_payment'):
        return jsonify({'error': 'Ce rendez-vous ne peut plus être modifié.'}), 400

    data = request.get_json() or {}
    date_str = (data.get('appointment_date') or '').strip()
    time_str = (data.get('appointment_time') or '').strip()

    try:
        appointment_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return jsonify({'error': 'Date invalide.'}), 400

    if appointment_date.weekday() > 4:
        return jsonify({'error': 'Les rendez-vous sont disponibles du lundi au vendredi uniquement.'}), 400

    today = now_comoros().date()
    if appointment_date < today:
        return jsonify({'error': 'La date choisie est déjà passée.'}), 400

    if time_str not in TECHNICAL_INSPECTION_APPOINTMENT_SLOTS:
        return jsonify({'error': 'Créneau horaire invalide.'}), 400

    if appointment_date == today:
        now_time = now_comoros().strftime('%H:%M')
        if time_str <= now_time:
            return jsonify({'error': "Ce créneau est déjà passé pour aujourd'hui."}), 400

    if (appointment_date, time_str) != (appointment.appointment_date, appointment.appointment_time):
        slot_count = TechnicalInspectionAppointment.query.filter(
            TechnicalInspectionAppointment.appointment_date == appointment_date,
            TechnicalInspectionAppointment.appointment_time == time_str,
            TechnicalInspectionAppointment.status == 'confirmed',
            TechnicalInspectionAppointment.id != appointment.id
        ).count()
        if slot_count >= TECHNICAL_INSPECTION_APPOINTMENT_SLOT_CAPACITY:
            return jsonify({'error': 'Ce créneau est complet (5 véhicules maximum). Veuillez choisir un autre horaire.'}), 400

    appointment.appointment_date = appointment_date
    appointment.appointment_time = time_str
    appointment.updated_at = now_comoros()
    db.session.commit()
    return jsonify(appointment.to_dict())


@citizen_auth_bp.route('/technical-inspection-appointments/<int:appointment_id>/cancel', methods=['POST'])
@jwt_required()
def citizen_cancel_technical_inspection_appointment(appointment_id):
    from app.models import TechnicalInspectionAppointment

    identity = get_jwt_identity()
    vehicle_id = identity.get('vehicle_id') if isinstance(identity, dict) else identity
    if not vehicle_id:
        return jsonify({'error': 'Compte non identifié'}), 401

    appointment = TechnicalInspectionAppointment.query.get_or_404(appointment_id)
    if appointment.vehicle_id != int(vehicle_id):
        return jsonify({'error': 'Accès refusé'}), 403
    if appointment.status == 'confirmed':
        return jsonify({'error': 'Ce rendez-vous est déjà payé et ne peut plus être annulé.'}), 400
    if appointment.status != 'pending_payment':
        return jsonify({'error': 'Ce rendez-vous ne peut plus être annulé.'}), 400

    appointment.status = 'cancelled'
    appointment.cancelled_at = now_comoros()
    appointment.updated_at = now_comoros()
    db.session.commit()
    return jsonify(appointment.to_dict())


# ─────────────────────────────────────────────
#  Pratique du Code de la route (app citoyen)
#  — même banque de questions / barème que l'examen DGRTR, mais sans NIN/dossier
#    ni minuteur : X sessions gratuites (réglage Smart Tech), puis paiement
#    Huri Money par session supplémentaire.
# ─────────────────────────────────────────────

_practice_otp_store = {}  # normalized phone -> {otp, expires_at, attempts}


def _practice_identity():
    """Resolve who's practicing: a logged-in citizen (vehicle_id, from the JWT) or
    an anonymous one, identified by a phone number verified by SMS OTP (not by
    device_id — a device id is lost the moment the app is reinstalled, which
    would silently reset the free-practice quota; a verified phone number isn't).
    Returns (field_name, value) or (None, None) if neither is present. The JWT is
    optional on every practice-exam route so logged-out citizens can use the
    feature too, once their phone is verified."""
    from app.models import PracticePhoneVerification

    try:
        identity = get_jwt_identity()
    except Exception:
        identity = None
    if identity:
        vehicle_id = identity.get('vehicle_id') if isinstance(identity, dict) else identity
        if vehicle_id:
            return 'vehicle_id', int(vehicle_id)

    phone = request.args.get('phone')
    if not phone:
        body = request.get_json(silent=True) or {}
        phone = body.get('phone')
    phone = _normalize_phone(phone) if phone else ''
    if phone and PracticePhoneVerification.query.filter_by(phone=phone).first():
        return 'phone', phone

    return None, None


@citizen_auth_bp.route('/practice-exam/send-otp', methods=['POST'])
@limiter.limit('5/minute')
def citizen_practice_exam_send_otp():
    """First step of anonymous phone verification: send a 6-digit OTP to the
    phone number the citizen wants to practice under."""
    data = request.get_json() or {}
    raw_phone = (data.get('phone') or '').strip()
    if not raw_phone:
        return jsonify({'error': 'Numéro de téléphone requis.'}), 400

    phone = _normalize_phone(raw_phone)
    if not phone:
        return jsonify({'error': 'Numéro de téléphone invalide.'}), 400

    otp = generate_otp(6)
    _practice_otp_store[phone] = {
        'otp': otp,
        'expires_at': now_comoros() + timedelta(minutes=10),
        'attempts': 0,
    }

    print(f"\n{'='*60}\n🔐 PRACTICE OTP for {phone}: {otp}\n{'='*60}\n")

    if not send_otp_via_sms(raw_phone, otp):
        return jsonify({'error': "Impossible d'envoyer le code. Réessayez."}), 500

    return jsonify({
        'message': 'Code envoyé par SMS.',
        'phone_masked': phone[:3] + '*' * max(0, len(phone) - 6) + phone[-3:],
        'expires_in': 600,
    }), 200


@citizen_auth_bp.route('/practice-exam/verify-otp', methods=['POST'])
@limiter.limit('10/minute')
def citizen_practice_exam_verify_otp():
    """Second step: confirm the OTP and mark the phone as verified — from then
    on it's a valid identity for practice-exam quota tracking."""
    from app.models import PracticePhoneVerification

    data = request.get_json() or {}
    raw_phone = (data.get('phone') or '').strip()
    otp = (data.get('otp') or '').strip()
    phone = _normalize_phone(raw_phone)
    if not phone or not otp:
        return jsonify({'error': 'Numéro et code requis.'}), 400

    entry = _practice_otp_store.get(phone)
    if not entry:
        return jsonify({'error': 'Aucun code envoyé pour ce numéro. Demandez un nouveau code.'}), 400
    if now_comoros() > entry['expires_at']:
        del _practice_otp_store[phone]
        return jsonify({'error': 'Ce code a expiré. Demandez un nouveau code.'}), 400
    entry['attempts'] += 1
    if entry['attempts'] > 5:
        del _practice_otp_store[phone]
        return jsonify({'error': 'Trop de tentatives. Demandez un nouveau code.'}), 429
    if otp != entry['otp']:
        return jsonify({'error': 'Code incorrect.'}), 400

    del _practice_otp_store[phone]

    verification = PracticePhoneVerification.query.filter_by(phone=phone).first()
    if verification:
        verification.verified_at = now_comoros()
    else:
        db.session.add(PracticePhoneVerification(phone=phone))
    db.session.commit()

    return jsonify({'verified': True, 'phone': phone}), 200


def _practice_questions_for_ids(ids):
    from app.models import ExamQuestion
    qs = ExamQuestion.query.filter(ExamQuestion.id.in_(ids)).all()
    by_id = {q.id: q for q in qs}
    return [by_id[i].to_dict() for i in ids if i in by_id]


@citizen_auth_bp.route('/practice-exam/status', methods=['GET'])
@jwt_required(optional=True)
def citizen_practice_exam_status():
    from app.models import ExamSetting, ExamQuestion, PracticeAttempt, SmartTechSetting

    field, value = _practice_identity()
    if not field:
        return jsonify({'error': 'Vérification du numéro requise.', 'code': 'phone_verification_required'}), 401

    settings = ExamSetting.get()
    active_count = ExamQuestion.query.filter_by(is_active=True).count()
    configured = settings.questions_per_exam > 0 and active_count >= settings.questions_per_exam

    free_total = int(SmartTechSetting.get('practice_free_count', 2))
    price_kmf = float(SmartTechSetting.get('practice_price_kmf', 500))

    used = PracticeAttempt.query.filter(
        getattr(PracticeAttempt, field) == value,
        PracticeAttempt.submitted_at.isnot(None),
    ).count()
    free_remaining = max(0, free_total - used)

    pending = (PracticeAttempt.query
               .filter_by(status='pending_payment', **{field: value})
               .order_by(PracticeAttempt.id.desc())
               .first())

    return jsonify({
        'configured': configured,
        'questions_per_session': settings.questions_per_exam,
        'min_correct_to_pass': settings.min_correct_to_pass,
        'free_total': free_total,
        'free_remaining': free_remaining,
        'price_kmf': price_kmf,
        'pending_attempt_id': pending.id if pending else None,
    })


@citizen_auth_bp.route('/practice-exam/start', methods=['POST'])
@jwt_required(optional=True)
def citizen_practice_exam_start():
    from app.models import ExamSetting, ExamQuestion, PracticeAttempt, SmartTechSetting

    field, value = _practice_identity()
    if not field:
        return jsonify({'error': 'Vérification du numéro requise.', 'code': 'phone_verification_required'}), 401

    settings = ExamSetting.get()
    active_qs = ExamQuestion.query.filter_by(is_active=True).all()
    if settings.questions_per_exam <= 0 or len(active_qs) < settings.questions_per_exam:
        return jsonify({'error': "La pratique du Code de la route n'est pas encore configurée. Réessayez plus tard."}), 400

    free_total = int(SmartTechSetting.get('practice_free_count', 2))
    used = PracticeAttempt.query.filter(
        getattr(PracticeAttempt, field) == value,
        PracticeAttempt.submitted_at.isnot(None),
    ).count()

    if used >= free_total:
        # Reuse an already-created-but-unpaid session instead of charging twice for it.
        existing = (PracticeAttempt.query
                    .filter_by(status='pending_payment', **{field: value})
                    .order_by(PracticeAttempt.id.desc())
                    .first())
        if existing:
            return jsonify({'status': 'pending_payment', 'attempt_id': existing.id, 'price_kmf': existing.price_kmf})

        price_kmf = float(SmartTechSetting.get('practice_price_kmf', 500))
        attempt = PracticeAttempt(status='pending_payment', price_kmf=price_kmf, **{field: value})
        db.session.add(attempt)
        db.session.commit()
        return jsonify({'status': 'pending_payment', 'attempt_id': attempt.id, 'price_kmf': price_kmf})

    chosen = random.sample(active_qs, settings.questions_per_exam)
    question_ids = [q.id for q in chosen]
    attempt = PracticeAttempt(
        status='ready',
        is_paid=False,
        question_ids=json.dumps(question_ids),
        total_questions=len(question_ids),
        min_correct_required=settings.min_correct_to_pass,
        started_at=now_comoros(),
        **{field: value},
    )
    db.session.add(attempt)
    db.session.commit()

    return jsonify({
        'status': 'ready',
        'attempt_id': attempt.id,
        'questions': [q.to_dict() for q in chosen],
        'total_questions': len(question_ids),
        'min_correct_required': settings.min_correct_to_pass,
    })


@citizen_auth_bp.route('/practice-exam/attempts/<int:attempt_id>', methods=['GET'])
@jwt_required(optional=True)
def citizen_practice_exam_get_attempt(attempt_id):
    from app.models import PracticeAttempt

    field, value = _practice_identity()
    attempt = PracticeAttempt.query.get_or_404(attempt_id)
    if not field or getattr(attempt, field) != value:
        return jsonify({'error': 'Accès refusé'}), 403

    data = attempt.to_dict()
    if attempt.status == 'ready' and not attempt.submitted_at:
        ids = json.loads(attempt.question_ids or '[]')
        data['questions'] = _practice_questions_for_ids(ids)
    return jsonify(data)


@citizen_auth_bp.route('/practice-exam/attempts/<int:attempt_id>/export.pdf', methods=['GET'])
@jwt_required(optional=True)
def citizen_practice_exam_export(attempt_id):
    """PDF récapitulatif des réponses d'une session de pratique — pas d'identité
    du citoyen dedans (nom, photo, NIN…) puisque ce n'est pas l'examen officiel,
    juste un entraînement."""
    from app.models import PracticeAttempt, ExamQuestion

    field, value = _practice_identity()
    attempt = PracticeAttempt.query.get_or_404(attempt_id)
    if not field or getattr(attempt, field) != value:
        return jsonify({'error': 'Accès refusé'}), 403
    if not attempt.submitted_at:
        return jsonify({'error': "Cette session n'est pas encore terminée."}), 400

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER
        from flask import send_file
        from io import BytesIO

        question_ids = json.loads(attempt.question_ids or '[]')
        answers = json.loads(attempt.answers or '{}')
        questions = {q.id: q for q in ExamQuestion.query.filter(ExamQuestion.id.in_(question_ids)).all()}
        option_letters = ['a', 'b', 'c', 'd']

        pdf_buffer = BytesIO()
        doc = SimpleDocTemplate(pdf_buffer, pagesize=A4, topMargin=1.5*cm, bottomMargin=1.5*cm,
                                 leftMargin=1.5*cm, rightMargin=1.5*cm)
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('Title', parent=styles['Normal'], fontSize=14, fontName='Helvetica-Bold',
                                      alignment=TA_CENTER, spaceAfter=4)
        meta_style = ParagraphStyle('Meta', parent=styles['Normal'], fontSize=10, alignment=TA_CENTER,
                                     textColor=colors.grey, spaceAfter=14)
        cell_style = ParagraphStyle('Cell', parent=styles['Normal'], fontSize=9, leading=12)

        elements = [
            Paragraph("Réponses à l'examen théorique du Code de la route", title_style),
            Paragraph(
                f"Pratique — Score {attempt.score}/{attempt.total_questions} "
                f"({'Réussi' if attempt.passed else 'Non réussi'}) — "
                f"le {attempt.submitted_at.strftime('%d/%m/%Y') if attempt.submitted_at else ''}",
                meta_style,
            ),
            Spacer(1, 6),
        ]

        table_data = [['#', 'Question', 'Votre réponse', 'Bonne réponse', 'Résultat']]
        for idx, qid in enumerate(question_ids, start=1):
            q = questions.get(qid)
            if not q:
                continue
            given = answers.get(str(qid))
            correct = given is not None and given == q.correct_option
            given_text = f"{given.upper()}) {getattr(q, 'option_' + given, '')}" if given in option_letters else 'Sans réponse'
            correct_text = f"{q.correct_option.upper()}) {getattr(q, 'option_' + q.correct_option, '')}"
            table_data.append([
                str(idx),
                Paragraph(q.question_text, cell_style),
                Paragraph(given_text, cell_style),
                Paragraph(correct_text, cell_style),
                '✓' if correct else '✗',
            ])

        table = Table(table_data, colWidths=[1*cm, 7*cm, 4.3*cm, 4.3*cm, 1.8*cm], repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f2937')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (4, 0), (4, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d1d5db')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9fafb')]),
        ]))
        elements.append(table)

        doc.build(elements)
        pdf_buffer.seek(0)
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'reponses_pratique_code_route_{attempt.id}.pdf',
        )
    except Exception as e:
        import traceback
        print(f"Practice attempt PDF export error: {e}")
        print(traceback.format_exc())
        return jsonify({'error': f"Impossible de générer le PDF : {e}"}), 500


@citizen_auth_bp.route('/practice-exam/attempts/<int:attempt_id>/submit', methods=['POST'])
@jwt_required(optional=True)
def citizen_practice_exam_submit(attempt_id):
    from app.models import PracticeAttempt, ExamQuestion

    field, value = _practice_identity()
    attempt = PracticeAttempt.query.get_or_404(attempt_id)
    if not field or getattr(attempt, field) != value:
        return jsonify({'error': 'Accès refusé'}), 403
    if attempt.status != 'ready':
        return jsonify({'error': "Cette session n'est pas disponible."}), 400
    if attempt.submitted_at:
        return jsonify({
            'status': 'submitted',
            'score': attempt.score,
            'total_questions': attempt.total_questions,
            'min_correct_required': attempt.min_correct_required,
            'passed': attempt.passed,
        })

    data = request.get_json() or {}
    answers = data.get('answers') or {}
    ids = json.loads(attempt.question_ids or '[]')
    qs = ExamQuestion.query.filter(ExamQuestion.id.in_(ids)).all()
    correct_map = {q.id: q.correct_option for q in qs}

    score = 0
    for qid in ids:
        given = answers.get(str(qid))
        if given and correct_map.get(qid) == given:
            score += 1

    passed = score >= attempt.min_correct_required
    attempt.answers = json.dumps(answers)
    attempt.score = score
    attempt.passed = passed
    attempt.submitted_at = now_comoros()
    attempt.status = 'completed'
    db.session.commit()

    return jsonify({
        'status': 'submitted',
        'score': score,
        'total_questions': attempt.total_questions,
        'min_correct_required': attempt.min_correct_required,
        'passed': passed,
    })
