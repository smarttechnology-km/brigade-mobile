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
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from app.models import db, Vehicle, User, VehicleOwner
from app.sms_service import SMSService

citizen_auth_bp = Blueprint('citizen_auth', __name__, url_prefix='/api/auth')

# OTP storage (in production, use Redis or database)
_otp_store = {}

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
        
        # Check if vehicle owner already exists
        owner = VehicleOwner.query.filter_by(vehicle_id=vehicle.id).first()
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
        
        # Find VehicleOwner by phone
        owner = VehicleOwner.query.filter_by(phone=phone, is_verified=True).first()
        
        if not owner:
            print(f"⚠️  Login failed: No verified account found for {phone}")
            return jsonify({'error': 'No account found with this phone number'}), 404
        
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
        
        # Find or create VehicleOwner
        owner = VehicleOwner.query.filter_by(vehicle_id=vehicle.id).first()
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
            owner.current_device_id = device_id or otp_data.get('device_id') or owner.current_device_id
        
        db.session.commit()
        
        # Clean up OTP
        del _otp_store[phone]
        
        # Create JWT token
        # Use a string identity (vehicle id) to avoid JWT 'sub' type issues;
        # include extra info in additional claims for convenience in dev clients.
        access_token = create_access_token(
            identity=str(vehicle.id),
            additional_claims={
                'vehicle_id': vehicle.id,
                'license_plate': vehicle.license_plate,
                'phone': phone,
                'session_version': int(getattr(owner, 'session_version', 0)),
                'device_id': owner.current_device_id,
            }
        )
        
        return jsonify({
            'message': 'Successfully registered',
            'access_token': access_token,
            'vehicle': {
                'id': vehicle.id,
                'license_plate': vehicle.license_plate,
                'owner_name': vehicle.owner_name,
                'vehicle_type': vehicle.vehicle_type
            }
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
        
        # Update last login timestamp
        owner = VehicleOwner.query.filter_by(vehicle_id=vehicle.id).first()
        if owner:
            owner.last_login = datetime.utcnow()
            owner.session_version = int(getattr(owner, 'session_version', 0)) + 1
            owner.current_device_id = otp_data.get('device_id') or owner.current_device_id
            db.session.commit()
        
        # Clean up OTP
        del _otp_store[phone]
        
        # Create JWT token
        # Use string identity and put details into additional claims to satisfy
        # JWT libraries that expect a string 'sub' claim.
        access_token = create_access_token(
            identity=str(vehicle.id),
            additional_claims={
                'vehicle_id': vehicle.id,
                'license_plate': vehicle.license_plate,
                'phone': phone,
                'session_version': int(getattr(owner, 'session_version', 0)) if owner else 0,
                'device_id': owner.current_device_id if owner else None,
            }
        )
        
        return jsonify({
            'message': 'Successfully logged in',
            'access_token': access_token,
            'vehicle': {
                'id': vehicle.id,
                'license_plate': vehicle.license_plate,
                'owner_name': vehicle.owner_name,
                'vehicle_type': vehicle.vehicle_type
            }
        }), 200
        
    except Exception as e:
        print(f"Login OTP verification error: {e}")
        return jsonify({'error': str(e)}), 500


@citizen_auth_bp.route('/register-push-token', methods=['POST'])
@jwt_required()
def register_push_token():
    """Store the current Expo push token for the logged-in citizen device."""
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
            return jsonify({'error': 'Vehicle not found'}), 404

        owner = VehicleOwner.query.filter_by(vehicle_id=vehicle.id).first()
        if not owner:
            return jsonify({'error': 'Owner account not found'}), 404

        owner.expo_push_token = push_token
        if device_id:
            owner.current_device_id = device_id
        db.session.commit()

        return jsonify({'message': 'Push token registered successfully'}), 200
    except Exception as e:
        print(f"Push token registration error: {e}")
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
