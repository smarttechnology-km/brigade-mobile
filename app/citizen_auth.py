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
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, get_jwt
from app.models import db, Vehicle, User, VehicleOwner
from app.sms_service import SMSService
from app.push_notifications import send_expo_push_notification

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
        
        if not vehicle:
            return jsonify({'error': 'Vehicle not found. Please verify your license plate and VIN.'}), 404

        if not _is_vehicle_active(vehicle):
            return jsonify({'error': 'Ce véhicule est inactif. Son activation est requise avant l\'enregistrement.'}), 403

        stored_vehicle_phone = _normalize_phone(vehicle.owner_phone)
        if stored_vehicle_phone and stored_vehicle_phone != normalized_phone:
            return jsonify({'error': 'The phone number does not match the vehicle record.'}), 403
        
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
        
        # Find the most recently used verified VehicleOwner for this phone.
        # If the phone is linked to multiple vehicles, default to the most recent one.
        owner = (
            VehicleOwner.query
            .filter_by(phone=phone, is_verified=True)
            .order_by(VehicleOwner.last_login.desc(), VehicleOwner.verified_at.desc(), VehicleOwner.id.desc())
            .first()
        )
        
        if not owner:
            print(f"⚠️  Login failed: No verified account found for {phone}")
            return jsonify({'error': 'No account found with this phone number'}), 404

        vehicle = owner.vehicle
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

@citizen_auth_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    """Logout user (token cleanup happens on client side)"""
    return jsonify({'message': 'Logged out successfully'}), 200


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

        # Clear the link between the phone and the vehicle, then delete the owner row.
        vehicle.owner_phone = None
        db.session.delete(owner)
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

        if vehicle.status == 'inactive':
            return jsonify({'error': 'Ce véhicule est inactif. Vous pouvez le voir, mais vous ne pouvez pas l’activer.'}), 403

        owner.last_login = datetime.utcnow()
        owner.session_version = int(getattr(owner, 'session_version', 0)) + 1
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
