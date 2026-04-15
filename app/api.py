from flask import Blueprint, request, jsonify, send_file, g
from app.models import User, Vehicle, Fine, FineType, Phone, PhoneUsage, PhotoSubmission
from app import db
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from flask_login import login_required, current_user
from datetime import timedelta, datetime
from app.timezone_utils import now_comoros
from io import BytesIO
import qrcode
import os
import uuid
from werkzeug.utils import secure_filename

api_bp = Blueprint('api', __name__, url_prefix='/api')


# Helper function to apply island filter for judiciaire and policier users
def apply_island_filter(query, island_field):
    """Apply island/country filter for judiciaire and policier users.
    Judiciaire and policier users can only see data for their assigned island/country."""
    if current_user.role in ['judiciaire', 'policier'] and current_user.country:
        query = query.filter(island_field == current_user.country)
    return query


def check_island_access(island):
    """Check if current user has access to data from a specific island.
    Raises 403 Forbidden if judiciaire user doesn't have access."""
    if current_user.role == 'judiciaire' and current_user.country:
        if island != current_user.country:
            return jsonify({"error": "Forbidden"}), 403
    return None


def get_current_user():
    """Get current user from JWT (mobile) or session (web)"""
    # Try JWT auth first (mobile)
    try:
        from flask_jwt_extended import get_jwt_identity
        uid = get_jwt_identity()
        user = User.query.get(int(uid))
        if user:
            return user
    except:
        pass
    
    # Fall back to session auth (web)
    if current_user and current_user.is_authenticated:
        return current_user
    
    return None


@api_bp.route('/health', methods=['GET'])
def api_health():
    """Health check endpoint - lightweight, no auth required"""
    return jsonify({
        "status": "ok",
        "message": "Police API is running"
    }), 200


@api_bp.route('/auth/login', methods=['POST'])
def api_login():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')
    if not username or not password:
        return jsonify({"error": "Missing credentials"}), 400
    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return jsonify({"error": "Invalid credentials"}), 401
    # Check if user is active
    if not user.is_active:
        return jsonify({"error": "Account is disabled"}), 403
    # Allow policier and administrateur roles for mobile
    if user.role not in ['policier', 'administrateur']:
        return jsonify({"error": "Unauthorized role"}), 403
    
    access = create_access_token(identity=str(user.id), expires_delta=timedelta(hours=8))
    return jsonify({"access_token": access, "username": user.username, "role": user.role})


@api_bp.route('/track/<token>', methods=['GET'])
@jwt_required()
def api_track(token):
    # Verify caller is a policier or administrateur
    uid = get_jwt_identity()
    user = User.query.get(int(uid))
    if not user or user.role not in ['policier', 'administrateur']:
        return jsonify({"error": "Forbidden"}), 403
    vehicle = Vehicle.query.filter_by(track_token=token).first()
    if not vehicle:
        return jsonify({"error": "Not found"}), 404
    
    # Note: Policiers can access vehicles from any island (patrol can happen anywhere)
    # Island filtering only applies to judiciaire/dashboard access
    if user.role == 'judiciaire' and user.country:
        if vehicle.owner_island != user.country:
            return jsonify({"error": "Forbidden"}), 403
    
    # include recent fines
    fines_q = vehicle.fines.order_by(Fine.issued_at.desc()).limit(20).all()
    fines = [f.to_dict() for f in fines_q]
    return jsonify({"vehicle": vehicle.to_dict(), "fines": fines})


@api_bp.route('/fine-types/list', methods=['GET'])
@jwt_required()
def api_fine_types_list():
    uid = get_jwt_identity()
    user = User.query.get(int(uid))
    if not user or user.role not in ['policier', 'administrateur']:
        return jsonify({"error": "Forbidden"}), 403
    
    fine_types = FineType.query.all()
    return jsonify({
        "fine_types": [{
            "id": ft.id,
            "name": ft.label,
            "default_amount": float(ft.amount)
        } for ft in fine_types]
    })


@api_bp.route('/vehicles/search', methods=['GET'])
@jwt_required(optional=True)
def api_vehicles_search():
    user = get_current_user()
    if not user or user.role not in ['policier', 'administrateur', 'judiciaire']:
        return jsonify({"error": "Forbidden"}), 403
    
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({"vehicles": []})
    
    vehicles_query = Vehicle.query.filter(
        Vehicle.license_plate.ilike(f'%{q}%')
    )
    
    # Note: Policiers can search vehicles from any island (patrol can happen anywhere)
    # Island filtering only applies to judiciaire users
    if user.role == 'judiciaire' and user.country:
        vehicles_query = vehicles_query.filter(Vehicle.owner_island == user.country)
    
    vehicles = vehicles_query.limit(10).all()
    
    return jsonify({
        "vehicles": [v.to_dict() for v in vehicles]
    })


@api_bp.route('/vehicles', methods=['POST'])
@jwt_required(optional=True)
def api_vehicles_create():
    user = get_current_user()
    if not user or user.role not in ['administrateur']:
        return jsonify({"error": "Forbidden"}), 403
    
    data = request.get_json() or {}
    license_plate = data.get('license_plate', '').upper().strip()
    
    if not license_plate:
        return jsonify({"error": "License plate is required"}), 400
    
    # Check if vehicle already exists
    existing = Vehicle.query.filter_by(license_plate=license_plate).first()
    if existing:
        return jsonify({"error": "Vehicle with this license plate already exists"}), 400
    
    vehicle = Vehicle(
        license_plate=license_plate,
        owner_name=data.get('owner_name', ''),
        owner_phone=data.get('owner_phone', ''),
        owner_island=data.get('owner_island', ''),
        vehicle_type=data.get('vehicle_type', ''),
        usage_type=data.get('usage_type', 'Personnelle'),
        color=data.get('color', ''),
        make=data.get('make', ''),
        model=data.get('model', ''),
        year=data.get('year', ''),
        owner_address=data.get('owner_address', ''),
        vin=data.get('vin', ''),
        status=data.get('status', 'active'),
        insurance_company=data.get('insurance_company', ''),
        notes=data.get('notes', '')
    )
    
    # Handle dates
    if data.get('registration_date'):
        try:
            vehicle.registration_date = datetime.strptime(data['registration_date'], '%Y-%m-%d')
        except:
            pass
    
    if data.get('registration_expiry'):
        try:
            vehicle.registration_expiry = datetime.strptime(data['registration_expiry'], '%Y-%m-%d')
        except:
            pass
    
    if data.get('insurance_expiry'):
        try:
            vehicle.insurance_expiry = datetime.strptime(data['insurance_expiry'], '%Y-%m-%d')
        except:
            pass
    
    if data.get('vignette_expiry'):
        try:
            vehicle.vignette_expiry = datetime.strptime(data['vignette_expiry'], '%Y-%m-%d')
        except:
            pass
    
    if data.get('last_inspection_date'):
        try:
            vehicle.last_inspection_date = datetime.strptime(data['last_inspection_date'], '%Y-%m-%d')
        except:
            pass
    
    db.session.add(vehicle)
    db.session.commit()
    
    return jsonify({
        "message": "Vehicle created successfully",
        "vehicle": vehicle.to_dict()
    }), 201


@api_bp.route('/vehicles/<int:vehicle_id>', methods=['PUT'])
@jwt_required(optional=True)
def api_vehicles_update(vehicle_id):
    user = get_current_user()
    if not user or user.role not in ['administrateur', 'judiciaire']:
        return jsonify({"error": "Forbidden"}), 403
    
    vehicle = Vehicle.query.get(vehicle_id)
    if not vehicle:
        return jsonify({"error": "Vehicle not found"}), 404
    
    # Check island access for judiciaire users
    if user.role == 'judiciaire' and user.country:
        if vehicle.owner_island != user.country:
            return jsonify({"error": "Forbidden"}), 403
    
    data = request.get_json() or {}
    
    # Update string fields
    if 'license_plate' in data:
        new_plate = data['license_plate'].upper().strip()
        # Check if new plate already exists (and is not this vehicle)
        existing = Vehicle.query.filter(
            Vehicle.license_plate == new_plate,
            Vehicle.id != vehicle_id
        ).first()
        if existing:
            return jsonify({"error": "Another vehicle with this license plate already exists"}), 400
        vehicle.license_plate = new_plate
    
    if 'owner_name' in data:
        vehicle.owner_name = data['owner_name']
    if 'owner_phone' in data:
        vehicle.owner_phone = data['owner_phone']
    if 'owner_island' in data:
        vehicle.owner_island = data['owner_island']
    if 'vehicle_type' in data:
        vehicle.vehicle_type = data['vehicle_type']
    if 'usage_type' in data:
        vehicle.usage_type = data['usage_type']
    if 'color' in data:
        vehicle.color = data['color']
    if 'make' in data:
        vehicle.make = data['make']
    if 'model' in data:
        vehicle.model = data['model']
    if 'year' in data:
        vehicle.year = data['year']
    if 'owner_address' in data:
        vehicle.owner_address = data['owner_address']
    if 'vin' in data:
        vehicle.vin = data['vin']
    if 'status' in data:
        vehicle.status = data['status']
    if 'insurance_company' in data:
        vehicle.insurance_company = data['insurance_company']
    if 'notes' in data:
        vehicle.notes = data['notes']
    
    # Update date fields
    if 'registration_date' in data and data['registration_date']:
        try:
            vehicle.registration_date = datetime.strptime(data['registration_date'], '%Y-%m-%d')
        except:
            pass
    
    if 'registration_expiry' in data and data['registration_expiry']:
        try:
            vehicle.registration_expiry = datetime.strptime(data['registration_expiry'], '%Y-%m-%d')
        except:
            pass
    
    if 'insurance_expiry' in data and data['insurance_expiry']:
        try:
            vehicle.insurance_expiry = datetime.strptime(data['insurance_expiry'], '%Y-%m-%d')
        except:
            pass
    
    if 'vignette_expiry' in data and data['vignette_expiry']:
        try:
            vehicle.vignette_expiry = datetime.strptime(data['vignette_expiry'], '%Y-%m-%d')
        except:
            pass
    
    if 'last_inspection_date' in data and data['last_inspection_date']:
        try:
            vehicle.last_inspection_date = datetime.strptime(data['last_inspection_date'], '%Y-%m-%d')
        except:
            pass
    
    vehicle.updated_at = now_comoros()
    db.session.commit()
    
    return jsonify({
        "message": "Vehicle updated successfully",
        "vehicle": vehicle.to_dict()
    })


@api_bp.route('/fines/create', methods=['POST'])
@jwt_required()
def api_fines_create():
    uid = get_jwt_identity()
    user = User.query.get(int(uid))
    if not user or user.role not in ['policier', 'administrateur']:
        return jsonify({"error": "Forbidden"}), 403
    
    data = request.get_json() or {}
    vehicle_id = data.get('vehicle_id')
    amount = data.get('amount')
    reason = data.get('reason')
    
    if not vehicle_id or not amount or not reason:
        return jsonify({"error": "Missing required fields"}), 400
    
    vehicle = Vehicle.query.get(vehicle_id)
    if not vehicle:
        return jsonify({"error": "Vehicle not found"}), 404
    
    fine = Fine(
        vehicle_id=vehicle_id,
        amount=amount,
        reason=reason,
        officer=user.username,
        issued_at=now_comoros(),
        paid=False
    )
    
    db.session.add(fine)
    db.session.commit()
    
    return jsonify({
        "message": "Fine created successfully",
        "fine": fine.to_dict()
    }), 201


@api_bp.route('/profile', methods=['GET'])
@jwt_required()
def api_profile():
    uid = get_jwt_identity()
    user = User.query.get(int(uid))
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    return jsonify({
        "user": {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "email": user.email,
            "phone": user.phone,
            "role": user.role
        }
    })


@api_bp.route('/profile/update', methods=['POST'])
@jwt_required()
def api_profile_update():
    uid = get_jwt_identity()
    user = User.query.get(int(uid))
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    data = request.get_json() or {}
    
    if 'full_name' in data:
        user.full_name = data['full_name']
    if 'email' in data:
        user.email = data['email']
    if 'phone' in data:
        user.phone = data['phone']
    
    db.session.commit()
    
    return jsonify({
        "message": "Profile updated successfully",
        "user": {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "email": user.email,
            "phone": user.phone,
            "role": user.role
        }
    })


@api_bp.route('/profile/change-password', methods=['POST'])
@jwt_required()
def api_profile_change_password():
    uid = get_jwt_identity()
    user = User.query.get(int(uid))
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    data = request.get_json() or {}
    current_password = data.get('current_password')
    new_password = data.get('new_password')
    
    if not current_password or not new_password:
        return jsonify({"error": "Missing required fields"}), 400
    
    if not user.check_password(current_password):
        return jsonify({"error": "Current password is incorrect"}), 401
    
    if len(new_password) < 6:
        return jsonify({"error": "New password must be at least 6 characters"}), 400
    
    user.set_password(new_password)
    db.session.commit()
    
    return jsonify({"message": "Password changed successfully"})


@api_bp.route('/reports/vehicles-with-fines', methods=['GET'])
@jwt_required()
def api_reports_vehicles_with_fines():
    uid = get_jwt_identity()
    user = User.query.get(int(uid))
    if not user or user.role not in ['policier', 'administrateur']:
        return jsonify({"error": "Forbidden"}), 403
    
    # Get vehicles with their fines count and amounts
    from sqlalchemy import func, case
    
    vehicles_with_fines = db.session.query(
        Vehicle.id,
        Vehicle.license_plate,
        Vehicle.owner_name,
        Vehicle.vehicle_type,
        Vehicle.track_token,
        func.count(Fine.id).label('fines_count'),
        func.sum(Fine.amount).label('total_amount')
    ).join(
        Fine, Vehicle.id == Fine.vehicle_id
    )
    
    # Apply island filter for judiciaire and policier users
    if user.role in ['judiciaire', 'policier'] and user.country:
        vehicles_with_fines = vehicles_with_fines.filter(Vehicle.owner_island == user.country)
    
    vehicles_with_fines = vehicles_with_fines.group_by(
        Vehicle.id
    ).order_by(
        func.count(Fine.id).desc()
    ).all()
    
    vehicles_data = []
    for v in vehicles_with_fines:
        # Count unpaid fines for this vehicle
        unpaid_count = db.session.query(func.count(Fine.id)).filter(
            Fine.vehicle_id == v.id,
            Fine.paid == False
        ).scalar() or 0
        
        vehicles_data.append({
            'id': v.id,
            'license_plate': v.license_plate,
            'owner_name': v.owner_name,
            'vehicle_type': v.vehicle_type,
            'track_token': v.track_token,
            'fines_count': v.fines_count,
            'total_amount': float(v.total_amount or 0),
            'unpaid_count': unpaid_count
        })
    
    # Calculate statistics
    stats_query = db.session.query(Fine).join(Vehicle)
    if user.role in ['judiciaire', 'policier'] and user.country:
        stats_query = stats_query.filter(Vehicle.owner_island == user.country)
    
    total_fines = stats_query.with_entities(func.count(Fine.id)).scalar() or 0
    unpaid_fines = stats_query.filter(Fine.paid == False).with_entities(func.count(Fine.id)).scalar() or 0
    total_amount = stats_query.with_entities(func.sum(Fine.amount)).scalar() or 0
    
    expired_query = db.session.query(Vehicle).filter(
        Vehicle.registration_expiry < now_comoros().date()
    )
    if user.role in ['judiciaire', 'policier'] and user.country:
        expired_query = expired_query.filter(Vehicle.owner_island == user.country)
    expired_count = expired_query.with_entities(func.count(Vehicle.id)).scalar() or 0
    
    stats = {
        'totalFines': total_fines,
        'unpaidFines': unpaid_fines,
        'totalAmount': float(total_amount),
        'expiredCount': expired_count
    }
    
    return jsonify({
        "vehicles": vehicles_data,
        "stats": stats
    })


@api_bp.route('/reports/expired-registrations', methods=['GET'])
@jwt_required()
def api_reports_expired_registrations():
    uid = get_jwt_identity()
    user = User.query.get(int(uid))
    if not user or user.role not in ['policier', 'administrateur']:
        return jsonify({"error": "Forbidden"}), 403
    
    # Get vehicles with expired registrations
    expired_vehicles_query = Vehicle.query.filter(
        Vehicle.registration_expiry < now_comoros().date()
    )
    
    # Apply island filter for judiciaire and policier users
    if user.role in ['judiciaire', 'policier'] and user.country:
        expired_vehicles_query = expired_vehicles_query.filter(Vehicle.owner_island == user.country)
    
    expired_vehicles = expired_vehicles_query.order_by(
        Vehicle.registration_expiry.asc()
    ).all()
    
    vehicles_data = []
    for vehicle in expired_vehicles:
        vehicles_data.append({
            'id': vehicle.id,
            'license_plate': vehicle.license_plate,
            'owner_name': vehicle.owner_name,
            'vehicle_type': vehicle.vehicle_type,
            'registration_expiry': vehicle.registration_expiry.isoformat() if vehicle.registration_expiry else None,
            'track_token': vehicle.track_token
        })
    
    return jsonify({
        "vehicles": vehicles_data
    })


@api_bp.route('/reports/expired-insurances', methods=['GET'])
@jwt_required()
def api_reports_expired_insurances():
    uid = get_jwt_identity()
    user = User.query.get(int(uid))
    if not user or user.role not in ['policier', 'administrateur']:
        return jsonify({"error": "Forbidden"}), 403

    # Get vehicles with expired insurance
    expired_insurance_query = Vehicle.query.filter(
        Vehicle.insurance_expiry != None,
        Vehicle.insurance_expiry < datetime.utcnow().date()
    )
    
    # Apply island filter for judiciaire and policier users
    if user.role in ['judiciaire', 'policier'] and user.country:
        expired_insurance_query = expired_insurance_query.filter(Vehicle.owner_island == user.country)
    
    expired_insurance_vehicles = expired_insurance_query.order_by(
        Vehicle.insurance_expiry.asc()
    ).all()

    vehicles_data = []
    for vehicle in expired_insurance_vehicles:
        vehicles_data.append({
            'id': vehicle.id,
            'license_plate': vehicle.license_plate,
            'owner_name': vehicle.owner_name,
            'vehicle_type': vehicle.vehicle_type,
            'insurance_company': vehicle.insurance_company or '',
            'insurance_expiry': vehicle.insurance_expiry.isoformat() if vehicle.insurance_expiry else None,
            'track_token': vehicle.track_token
        })

    return jsonify({
        "vehicles": vehicles_data
    })


@api_bp.route('/vehicles/<int:vehicle_id>/qr-code', methods=['GET'])
@jwt_required()
def api_vehicle_qr_code(vehicle_id):
    uid = get_jwt_identity()
    user = User.query.get(int(uid))
    if not user or user.role not in ['policier', 'administrateur']:
        return jsonify({"error": "Forbidden"}), 403
    
    vehicle = Vehicle.query.get(vehicle_id)
    if not vehicle:
        return jsonify({"error": "Vehicle not found"}), 404
    
    # Apply island filter for policier and judiciaire users
    if user.role in ['policier', 'judiciaire'] and user.country:
        if vehicle.owner_island != user.country:
            return jsonify({"error": "Forbidden"}), 403
    
    try:
        import qrcode
        import io
        import base64
        from PIL import Image
        
        # Create QR code with tracking token
        qr_data = f"VEHICLE_TRACK:{vehicle.track_token}"
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)
        
        # Create image
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert to base64
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        
        qr_code_base64 = base64.b64encode(buffer.getvalue()).decode()
        
        return jsonify({
            "qr_code": f"data:image/png;base64,{qr_code_base64}",
            "track_token": vehicle.track_token,
            "vehicle": vehicle.to_dict()
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to generate QR code: {str(e)}"}), 500


# ===== PHONES MANAGEMENT =====

@api_bp.route('/phones/list', methods=['GET'])
@login_required
def api_phones_list():
    """Get all phones"""
    query = Phone.query
    query = apply_island_filter(query, Phone.island)
    phones = query.order_by(Phone.created_at.desc()).all()
    return jsonify({
        'success': True,
        'phones': [p.to_dict() for p in phones]
    })


@api_bp.route('/phones', methods=['POST'])
@login_required
def api_phone_create():
    """Create a new phone"""
    data = request.get_json() or {}
    
    if not data.get('brand') or not data.get('model'):
        return jsonify({'error': 'Brand and model are required'}), 400
    
    phone = Phone(
        brand=data.get('brand').strip(),
        model=data.get('model').strip(),
        color=data.get('color', '').strip() or None,
        island=data.get('island', '').strip() or None,
        status=data.get('status', 'active'),
        notes=data.get('notes', '').strip() or None
    )
    
    db.session.add(phone)
    db.session.flush()  # Generate ID
    phone.phone_code = f"TP{phone.id:05d}"  # Generate compact code like TP00001
    db.session.commit()
    
    return jsonify(phone.to_dict()), 201


@api_bp.route('/phones/<int:phone_id>', methods=['GET'])
@login_required
def api_phone_get(phone_id):
    """Get a specific phone"""
    phone = Phone.query.get(phone_id)
    if not phone:
        return jsonify({'error': 'Phone not found'}), 404
    
    # Check island access for policier users
    if current_user.role == 'policier' and current_user.country:
        if not phone.island or phone.island != current_user.country:
            return jsonify({'error': 'Unauthorized access to phone from different island'}), 403
    
    return jsonify(phone.to_dict())


@api_bp.route('/phones/<int:phone_id>', methods=['PUT'])
@login_required
def api_phone_update(phone_id):
    """Update a phone"""
    phone = Phone.query.get(phone_id)
    if not phone:
        return jsonify({'error': 'Phone not found'}), 404
    
    # Check island access for policier users - restrict to own island
    if current_user.role == 'policier' and current_user.country:
        if not phone.island or phone.island != current_user.country:
            return jsonify({'error': 'Cannot update phone from different island'}), 403
    
    data = request.get_json() or {}
    
    if data.get('brand'):
        phone.brand = data['brand'].strip()
    if data.get('model'):
        phone.model = data['model'].strip()
    if 'color' in data:
        phone.color = data['color'].strip() if data['color'] else None
    if 'island' in data:
        phone.island = data['island'].strip() if data['island'] else None
    if data.get('status'):
        phone.status = data['status']
    if 'notes' in data:
        phone.notes = data['notes'].strip() if data['notes'] else None
    
    db.session.commit()
    
    return jsonify(phone.to_dict())


@api_bp.route('/phones/<int:phone_id>', methods=['DELETE'])
@login_required
def api_phone_delete(phone_id):
    """Delete a phone"""
    phone = Phone.query.get(phone_id)
    if not phone:
        return jsonify({'error': 'Phone not found'}), 404
    
    db.session.delete(phone)
    db.session.commit()
    
    return jsonify({'ok': True})


@api_bp.route('/phone/<int:phone_id>/qrcode', methods=['GET'])
@login_required
def api_phone_qrcode(phone_id):
    """Generate QR code for a phone - encodes the dynamic qr_code_data"""
    phone = Phone.query.get(phone_id)
    if not phone:
        return jsonify({'error': 'Phone not found'}), 404
    
    # Check island access for policier users
    if current_user.role == 'policier' and current_user.country:
        if not phone.island or phone.island != current_user.country:
            return jsonify({'error': 'Unauthorized access to phone from different island'}), 403
    
    # If phone doesn't have a QR code, generate one
    if not phone.qr_code_data:
        phone.generate_qr_code()
        db.session.commit()
    
    try:
        # Generate QR code with the dynamic qr_code_data
        # This includes phone_code + daily-changing UUID
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=2,
        )
        qr.add_data(phone.qr_code_data)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Save to BytesIO object
        img_io = BytesIO()
        img.save(img_io, 'PNG')
        img_io.seek(0)
        
        return send_file(
            img_io,
            mimetype='image/png',
            as_attachment=True,
            download_name=f'phone_{phone.phone_code}_qrcode.png'
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ===== PHONE USAGE MANAGEMENT =====

@api_bp.route('/phone-usage/checkout', methods=['POST'])
@login_required
def api_checkout_phone():
    """Check out a phone to a user"""
    data = request.get_json() or {}
    phone_id = data.get('phone_id')
    user_id = data.get('user_id')
    notes = data.get('notes', '').strip() or None
    
    if not phone_id or not user_id:
        return jsonify({'error': 'phone_id and user_id are required'}), 400
    
    phone = Phone.query.get(phone_id)
    if not phone:
        return jsonify({'error': 'Phone not found'}), 404
    
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    # Check if phone is already checked out
    active_usage = PhoneUsage.query.filter_by(phone_id=phone_id, checkin_at=None).first()
    if active_usage:
        return jsonify({'error': f'Phone already checked out to {active_usage.user.username}'}), 400
    
    usage = PhoneUsage(
        phone_id=phone_id,
        user_id=user_id,
        checkout_at=now_comoros(),
        notes=notes
    )
    
    db.session.add(usage)
    db.session.commit()
    
    return jsonify(usage.to_dict()), 201


@api_bp.route('/phone-usage/<int:usage_id>/checkin', methods=['POST'])
@login_required
def api_checkin_phone(usage_id):
    """Check in a phone from a user"""
    usage = PhoneUsage.query.get(usage_id)
    if not usage:
        return jsonify({'error': 'Usage record not found'}), 404
    
    if usage.checkin_at:
        return jsonify({'error': 'Phone already checked in'}), 400
    
    usage.checkin_at = now_comoros()
    db.session.commit()
    
    return jsonify(usage.to_dict())


@api_bp.route('/phone-usage/list', methods=['GET'])
@login_required
def api_phone_usage_list():
    """Get phone usage records - by default only active (checked out) phones"""
    # Get query parameter: show_all=true to show all records, otherwise only active
    show_all = request.args.get('show_all', 'false').lower() == 'true'
    
    query = PhoneUsage.query.join(Phone)
    query = apply_island_filter(query, Phone.island)
    
    if show_all:
        usages = query.order_by(PhoneUsage.checkout_at.desc()).all()
    else:
        # Show only currently checked out phones (checkin_at is NULL)
        usages = query.filter(PhoneUsage.checkin_at.is_(None)).order_by(PhoneUsage.checkout_at.desc()).all()
    
    return jsonify([u.to_dict() for u in usages])


@api_bp.route('/phone-usage/stats', methods=['GET'])
@login_required
def api_phone_usage_stats():
    """Get phone usage statistics"""
    query_phones = Phone.query
    query_phones = apply_island_filter(query_phones, Phone.island)
    
    total_phones = query_phones.count()
    active_phones = query_phones.filter_by(status='active').count()
    inactive_phones = query_phones.filter_by(status='inactive').count()
    
    query_usages = PhoneUsage.query.join(Phone)
    query_usages = apply_island_filter(query_usages, Phone.island)
    active_usages = query_usages.filter(PhoneUsage.checkin_at.is_(None)).count()
    
    return jsonify({
        'total_phones': total_phones,
        'active_phones': active_phones,
        'inactive_phones': inactive_phones,
        'phones_currently_checked_out': active_usages
    })


@api_bp.route('/users/list', methods=['GET'])
@login_required
def api_users_list():
    """Get all users"""
    users = User.query.filter(User.role.in_(['policier', 'administrateur'])).order_by(User.username).all()
    return jsonify({
        'success': True,
        'users': [{
            'id': u.id,
            'username': u.username,
            'full_name': u.full_name,
            'email': u.email,
            'phone': u.phone,
            'country': u.country,
            'region': u.region,
            'role': u.role,
            'is_active': u.is_active,
            'created_at': u.created_at.strftime('%d/%m/%Y %H:%M') if u.created_at else None
        } for u in users]
    })


@api_bp.route('/users/<int:user_id>/details', methods=['GET'])
@login_required
def api_user_details(user_id):
    """Get details for a specific user"""
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    return jsonify({
        'id': user.id,
        'username': user.username,
        'full_name': user.full_name,
        'email': user.email,
        'phone': user.phone,
        'country': user.country,
        'region': user.region,
        'role': user.role,
        'is_active': user.is_active,
        'created_at': user.created_at.strftime('%d/%m/%Y %H:%M') if user.created_at else None
    })


@api_bp.route('/phone/<int:phone_id>/usage-history', methods=['GET'])
@login_required
def api_phone_usage_history(phone_id):
    """Get usage history for a specific phone"""
    from sqlalchemy import and_, or_
    
    phone = Phone.query.get(phone_id)
    if not phone:
        return jsonify({'error': 'Phone not found'}), 404
    error_response = check_island_access(phone.island)
    if error_response:
        return error_response
    
    usages_query = PhoneUsage.query.filter_by(phone_id=phone_id)
    
    # For judiciaire users, filter usages to only show their country's users
    if current_user.role == 'judiciaire' and current_user.country:
        # Join with User table and filter by country
        # Show only: administrators (any country) OR users with same country (must not be NULL)
        usages_query = usages_query.join(User).filter(
            or_(
                User.role == 'administrateur',
                and_(
                    User.country == current_user.country,
                    User.country.isnot(None)  # Ensure country is not NULL
                )
            )
        )
    
    usages = usages_query.order_by(PhoneUsage.checkout_at.desc()).all()
    
    return jsonify({
        'phone': phone.to_dict(),
        'usages': [u.to_dict() for u in usages]
    })


@api_bp.route('/phone/scan', methods=['POST'])
@jwt_required()
def api_scan_phone_qr():
    """Mobile app: Scan QR code to checkout/checkin a phone"""
    uid = get_jwt_identity()
    user = User.query.get(int(uid))
    
    if not user or user.role not in ['policier', 'administrateur']:
        return jsonify({"error": "Unauthorized"}), 403
    
    data = request.get_json() or {}
    phone_id = data.get('phone_id')
    phone_code = data.get('phone_code')
    qr_code_data = data.get('qr_code_data')  # The scanned QR code (format: T00001_abc123)
    
    # If qr_code_data is provided, extract phone_code from it
    if qr_code_data and not phone_code:
        # Format: "T00001_uuid" - extract the phone_code part
        phone_code = qr_code_data.split('_')[0] if '_' in qr_code_data else qr_code_data
    
    # Find phone by ID or code
    phone = None
    if phone_id:
        phone = Phone.query.get(phone_id)
    elif phone_code:
        phone = Phone.query.filter_by(phone_code=phone_code).first()
    else:
        return jsonify({'error': 'phone_id, phone_code, or qr_code_data required'}), 400
    
    if not phone:
        return jsonify({
            'error': 'Phone not found',
            'phone_code': phone_code,
            'qr_data_received': qr_code_data
        }), 404
    
    if phone.status != 'active':
        return jsonify({'error': 'Phone is inactive'}), 400
    
    # For policier users with assigned country, check island match
    if user.role == 'policier' and user.country:
        if not phone.island or phone.island != user.country:
            return jsonify({
                'error': f'Cannot checkout phone from {phone.island or "unknown island"}. You are assigned to {user.country}.',
                'user_country': user.country,
                'phone_island': phone.island,
                'reason': 'Island mismatch'
            }), 400
    
    # Check if phone is currently checked out
    active_usage = PhoneUsage.query.filter_by(phone_id=phone.id, checkin_at=None).first()
    
    if active_usage:
        # Phone is checked out - check if it's by this user
        if active_usage.user_id != user.id:
            return jsonify({
                'error': f'Phone is currently checked out by {active_usage.user.username}',
                'current_user': active_usage.user.username
            }), 400
        
        # For check-in, verify QR code if provided
        if qr_code_data:
            # The scanned QR code must match the current phone's QR code
            if not phone.qr_code_data or phone.qr_code_data != qr_code_data:
                return jsonify({
                    'error': 'Invalid QR code. The QR code for this phone has changed. Please scan the current QR code at the station.',
                    'phone_code': phone.phone_code,
                    'reason': 'QR code mismatch - daily QR code rotation active',
                    'expected_qr': phone.qr_code_data,
                    'received_qr': qr_code_data
                }), 400
        
        # Check in the phone
        active_usage.checkin_at = now_comoros()
        db.session.commit()
        
        return jsonify({
            'action': 'checkin',
            'message': f'Phone {phone.phone_code} returned successfully',
            'usage': active_usage.to_dict()
        }), 200
    else:
        # Check out the phone
        usage = PhoneUsage(
            phone_id=phone.id,
            user_id=user.id,
            checkout_at=now_comoros()
        )
        db.session.add(usage)
        db.session.commit()
        
        return jsonify({
            'action': 'checkout',
            'message': f'Phone {phone.phone_code} checked out successfully',
            'usage': usage.to_dict()
        }), 201


@api_bp.route('/phone/<phone_code>/current-status', methods=['GET'])
@jwt_required()
def api_phone_current_status(phone_code):
    """Check the current status of a phone (if it's still checked out)"""
    uid = get_jwt_identity()
    user = User.query.get(int(uid))
    
    if not user or user.role not in ['policier', 'administrateur']:
        return jsonify({"error": "Unauthorized"}), 403
    
    # Find phone by code
    phone = Phone.query.filter_by(phone_code=phone_code).first()
    if not phone:
        return jsonify({'error': 'Phone not found'}), 404
    
    # Check for active (checked out) usage
    active_usage = PhoneUsage.query.filter_by(phone_id=phone.id, checkin_at=None).first()
    
    # For policiers, allow status check if they have the phone checked out, even if island doesn't match
    # (This handles legacy data where phones might not have island assigned)
    if user.role == 'policier' and not active_usage:
        # Phone is not checked out by anyone - only allow check if user has island access
        if user.country and phone.island and phone.island != user.country:
            return jsonify({'error': 'Unauthorized: Phone from different island'}), 403
    
    return jsonify({
        'phone_code': phone_code,
        'is_checked_out': active_usage is not None,
        'checked_out_by': active_usage.user.username if active_usage else None,
        'checked_out_at': active_usage.checkout_at.isoformat() if active_usage else None,
        'is_checked_out_by_current_user': active_usage and active_usage.user_id == user.id
    })

@api_bp.route('/photo-submissions/upload', methods=['POST'])
@jwt_required()
def upload_photo_submission():
    uid = get_jwt_identity()
    user = User.query.get(int(uid))
    if not user or user.role not in ['policier', 'administrateur']:
        return jsonify({"error": "Forbidden"}), 403
    
    # Check if photo file is present
    if 'photo' not in request.files:
        return jsonify({"error": "No photo provided"}), 400
    
    photo_file = request.files['photo']
    description = request.form.get('description', '').strip() or None
    license_plate = request.form.get('license_plate', '').strip().upper() or None
    vehicle_id = request.form.get('vehicle_id', type=int)
    
    if photo_file.filename == '':
        return jsonify({"error": "No photo selected"}), 400
    
    # Validate file type
    if not photo_file.content_type.startswith('image/'):
        return jsonify({"error": "Only image files allowed"}), 400
    
    # Create uploads directory if not exists
    upload_dir = os.path.join(os.path.dirname(__file__), 'static', 'photo_submissions')
    os.makedirs(upload_dir, exist_ok=True)
    
    # Generate unique filename
    ext = secure_filename(photo_file.filename).split('.')[-1]
    filename = f"{uuid.uuid4()}.{ext}"
    filepath = os.path.join(upload_dir, filename)
    
    # Save file
    photo_file.save(filepath)
    
    # Create database entry
    submission = PhotoSubmission(
        user_id=user.id,
        vehicle_id=vehicle_id,
        license_plate=license_plate,
        description=description,
        photo_filename=filename,
        photo_path=filepath,
        status='pending'
    )
    db.session.add(submission)
    db.session.commit()
    
    return jsonify({
        "message": "Photo submitted successfully",
        "submission_id": submission.id,
        "status": "pending"
    }), 201


@api_bp.route('/photo-submissions/list', methods=['GET'])
def list_photo_submissions():
    # Support both JWT (mobile) and session auth (web admin)
    user = get_current_user()
    
    if not user or user.role not in ['administrateur', 'policier', 'judiciaire']:
        return jsonify({"error": "Forbidden"}), 403
    
    status = request.args.get('status', 'all')
    
    # Join with Vehicle (for owner_island) and User (for submitter's country)
    query = PhotoSubmission.query.join(
        Vehicle, PhotoSubmission.vehicle_id == Vehicle.id, isouter=True
    ).join(
        User, PhotoSubmission.user_id == User.id
    )
    
    # Apply island filter: 
    # - Administrators see all submissions
    # - Policiers and Judiciaires see submissions for vehicles in their country OR submissions by officers in their country
    if user.role in ['policier', 'judiciaire'] and user.country:
        query = query.filter(
            (Vehicle.owner_island == user.country) | 
            (User.country == user.country)
        )
    
    if status != 'all':
        query = query.filter(PhotoSubmission.status == status)
    
    submissions = query.order_by(PhotoSubmission.submitted_at.desc()).all()
    
    return jsonify({
        "submissions": [s.to_dict() for s in submissions]
    })


@api_bp.route('/photo-submissions/<int:submission_id>/review', methods=['POST'])
def review_photo_submission(submission_id):
    # Support both JWT (mobile) and session auth (web admin)
    user = get_current_user()
    
    if not user or user.role not in ['administrateur', 'policier', 'judiciaire']:
        return jsonify({"error": "Forbidden"}), 403
    
    submission = PhotoSubmission.query.get(submission_id)
    if not submission:
        return jsonify({"error": "Submission not found"}), 404
    
    if submission.vehicle_id:
        vehicle = Vehicle.query.get(submission.vehicle_id)
        if vehicle and user.role == 'judiciaire':
            check_island_access(vehicle.owner_island)
    
    data = request.get_json() or {}
    status = data.get('status')  # only 'resolved' is allowed
    review_notes = data.get('review_notes', '')
    
    if status != 'resolved':
        return jsonify({"error": "Invalid status - only 'resolved' is allowed"}), 400
    
    submission.status = status
    submission.reviewed_by = user.id
    submission.reviewed_at = now_comoros()
    submission.review_notes = review_notes
    
    # Delete photo file if status is 'resolved' to save disk space
    if status == 'resolved' and submission.photo_path and os.path.exists(submission.photo_path):
        try:
            os.remove(submission.photo_path)
            print(f"Deleted photo file: {submission.photo_path}")
        except Exception as e:
            print(f"Error deleting photo file: {e}")
    
    db.session.commit()
    
    return jsonify({
        "message": "Submission reviewed",
        "submission": submission.to_dict()
    })


@api_bp.route('/photo-submissions/<int:submission_id>/delete', methods=['DELETE'])
def delete_photo_submission(submission_id):
    # Support both JWT (mobile) and session auth (web admin)
    user = get_current_user()
    
    if not user or user.role not in ['administrateur', 'policier', 'judiciaire']:
        return jsonify({"error": "Forbidden"}), 403
    
    submission = PhotoSubmission.query.get(submission_id)
    if not submission:
        return jsonify({"error": "Submission not found"}), 404
    
    if submission.vehicle_id:
        vehicle = Vehicle.query.get(submission.vehicle_id)
        if vehicle and user.role == 'judiciaire':
            error_response = check_island_access(vehicle.owner_island)
            if error_response:
                return error_response
    
    # Delete photo file if it exists
    if submission.photo_path and os.path.exists(submission.photo_path):
        try:
            os.remove(submission.photo_path)
            print(f"Deleted photo file: {submission.photo_path}")
        except Exception as e:
            print(f"Error deleting photo file: {e}")
    
    # Delete from database
    db.session.delete(submission)
    db.session.commit()
    
    return jsonify({
        "message": "Submission deleted successfully"
    })


@api_bp.route('/photo-submissions/<int:submission_id>/photo', methods=['GET'])
def get_photo_submission(submission_id):
    # Support both JWT (mobile) and session auth (web admin)
    user = get_current_user()
    
    if not user or user.role not in ['administrateur', 'policier', 'judiciaire']:
        return jsonify({"error": "Forbidden"}), 403
    
    submission = PhotoSubmission.query.get(submission_id)
    if not submission or not os.path.exists(submission.photo_path):
        return jsonify({"error": "Photo not found"}), 404
    
    if submission.vehicle_id:
        vehicle = Vehicle.query.get(submission.vehicle_id)
        if vehicle and user.role == 'judiciaire':
            error_response = check_island_access(vehicle.owner_island)
            if error_response:
                return error_response
    
    with open(submission.photo_path, 'rb') as photo:
        return send_file(
            photo,
            mimetype='image/jpeg',
            as_attachment=False
        )
    
    return send_file(submission.photo_path, mimetype='image/jpeg')