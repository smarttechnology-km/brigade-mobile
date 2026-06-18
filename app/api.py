from flask import Blueprint, request, jsonify, send_file, g
from app.models import User, Vehicle, VehicleOwner, Fine, FineType, Phone, PhoneUsage, PhotoSubmission, Insurance, VehicleTransfer, VignetteSetting, PhotoSubmissionReason, VehicleHistory, FineLateRate, DriverLicense, LicenseSetting, PointReductionReason, PointReductionHistory, LicenseStatusRule
from app import db
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, get_jwt
from flask_login import login_required, current_user
from datetime import timedelta, datetime
from app.timezone_utils import now_comoros
from app.push_notifications import send_fine_push_notification
from io import BytesIO
import qrcode
import os
import uuid
from werkzeug.utils import secure_filename

api_bp = Blueprint('api', __name__, url_prefix='/api')


# Helper function to validate JWT session version
def validate_jwt_session():
    """Validate that the JWT's session_version matches user's current session_version.
    This allows admins to invalidate all tokens by incrementing session_version."""
    try:
        claims = get_jwt()
        uid = get_jwt_identity()
        user = User.query.get(int(uid))
        
        if not user or not user.is_active:
            return jsonify({"error": "User not found or inactive"}), 401
        
        # Check if session_version in token matches user's current version
        token_session_version = claims.get('session_version', 0)
        if token_session_version != user.session_version:
            print(f"[SESSION] Token invalid for {user.username}: version {token_session_version} != {user.session_version}")
            return jsonify({"error": "Session expired. Please login again."}), 401
        
        return None  # Valid
    except Exception as e:
        print(f"[SESSION] Validation error: {e}")
        return jsonify({"error": "Invalid token"}), 401


# Helper function to apply island filter for judiciaire and policier users
def apply_island_filter(query, island_field, force_country=None):
    """Apply island/country filter for judiciaire and policier users.
    - Administrateur users can optionally filter by a specific country using force_country parameter.
    - Judiciaire and policier users can only see data for their assigned island/country."""
    # If force_country is explicitly provided and user is admin, apply it
    if force_country and current_user.role == 'administrateur':
        query = query.filter(island_field == force_country)
    # Otherwise apply default role-based filter
    elif current_user.role in ['judiciaire', 'policier'] and current_user.country:
        query = query.filter(island_field == current_user.country)
    return query


def check_island_access(island):
    """Check if current user has access to data from a specific island.
    Raises 403 Forbidden if judiciaire user doesn't have access.
    Insurance accounts can only access their own island."""
    from app.models import InsuranceAccount
    
    # Insurance accounts can only access their own island
    if isinstance(current_user, InsuranceAccount):
        if island != current_user.insurance.island:
            return jsonify({"error": "Forbidden"}), 403
        return None
    
    # Regular users (judiciaire) can only access their country's data
    if hasattr(current_user, 'role') and current_user.role == 'judiciaire' and hasattr(current_user, 'country'):
        if island != current_user.country:
            return jsonify({"error": "Forbidden"}), 403
    return None


def get_current_user():
    """Get current user from JWT (mobile) or session (web).
    Citizen mobile tokens have identity=str(vehicle_id) and a 'vehicle_id' claim.
    Web tokens have identity=str(user_id) with no 'vehicle_id' claim.
    """
    try:
        from flask_jwt_extended import get_jwt_identity, get_jwt
        uid = get_jwt_identity()
        claims = get_jwt()

        # Citizen mobile token: has 'vehicle_id' in additional claims
        if claims.get('vehicle_id'):
            vehicle_id = claims['vehicle_id']
            owner = VehicleOwner.query.filter_by(vehicle_id=int(vehicle_id)).first()
            if owner:
                return owner
            return None

        # Web/police token: identity is the user id
        user = User.query.get(int(uid))
        if user:
            return user
    except Exception:
        pass

    # Fall back to session auth (web)
    if current_user and current_user.is_authenticated:
        return current_user

    return None


def log_user_history(user, action, details):
    """Write a best-effort entry to UserHistory without breaking the main request."""
    if not user:
        return
    try:
        from app.models import UserHistory
        db.session.add(UserHistory(user_id=user.id, action=action, details=details))
        db.session.commit()
    except Exception as e:
        print(f'[UserHistory] {action} logging failed for {getattr(user, "username", user)}: {e}')


def _sync_vehicle_owner_link(vehicle):
    """Best-effort sync between vehicles.owner_phone and vehicle_owners.phone."""
    phone = (vehicle.owner_phone or '').strip()
    if not phone:
        return

    owner_name = (vehicle.owner_name or 'Proprietaire').strip() or 'Proprietaire'
    now = now_comoros()

    try:
        vo = VehicleOwner.query.filter_by(vehicle_id=vehicle.id).first()
        if vo:
            vo.phone = phone
            vo.owner_name = owner_name
            vo.updated_at = now
            if not vo.verified_at:
                vo.verified_at = now
            vo.is_verified = True
        else:
            db.session.add(VehicleOwner(
                vehicle_id=vehicle.id,
                owner_name=owner_name,
                phone=phone,
                is_verified=True,
                session_version=0,
                verified_at=now,
                last_login=None,
                created_at=now,
                updated_at=now,
            ))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[VehicleOwner] sync failed for vehicle {vehicle.id}: {e}")


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
    
    # Invalidate all previous sessions by incrementing session_version
    # This ensures only the current device stays logged in
    user.session_version += 1
    db.session.commit()
    
    # Create JWT token with the current session_version
    # This version will be validated on every protected request
    access = create_access_token(
        identity=str(user.id), 
        expires_delta=timedelta(hours=8),
        additional_claims={'session_version': user.session_version}
    )
    log_user_history(user, 'Connexion mobile', f'Connexion réussie depuis l\'application mobile (Session v{user.session_version})')
    return jsonify({"access_token": access, "username": user.username, "role": user.role})



@api_bp.route('/track/<token>', methods=['GET'])
@jwt_required()
def api_track(token):
    # Validate session version (ensure token hasn't been invalidated)
    validation_error = validate_jwt_session()
    if validation_error:
        return validation_error
    
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
    # Validate session version (ensure token hasn't been invalidated)
    validation_error = validate_jwt_session()
    if validation_error:
        return validation_error
    
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


# Fine Late Rate Routes
@api_bp.route('/fine-late-rates', methods=['GET'])
def get_fine_late_rates():
    user = get_current_user()
    if not user or user.role not in ['administrateur', 'judiciaire', 'policier']:
        return jsonify({'error': 'Access denied'}), 403
    rates = FineLateRate.query.order_by(FineLateRate.months).all()
    return jsonify([r.to_dict() for r in rates]), 200


@api_bp.route('/fine-late-rates', methods=['POST'])
def create_fine_late_rate():
    user = get_current_user()
    if not user or user.role not in ['administrateur', 'judiciaire']:
        return jsonify({'error': 'Access denied'}), 403
    data = request.get_json() or {}
    months = data.get('months')
    percentage = data.get('percentage')
    if months is None or percentage is None:
        return jsonify({'error': 'months et percentage requis'}), 400
    try:
        months = int(months)
        percentage = float(percentage)
    except (ValueError, TypeError):
        return jsonify({'error': 'Valeurs invalides'}), 400
    if months < 1:
        return jsonify({'error': 'Le nombre de mois doit être ≥ 1'}), 400
    if percentage <= 0:
        return jsonify({'error': 'Le pourcentage doit être positif'}), 400
    if FineLateRate.query.filter_by(months=months).first():
        return jsonify({'error': f'Une règle pour {months} mois existe déjà'}), 409
    rate = FineLateRate(months=months, percentage=percentage)
    db.session.add(rate)
    db.session.commit()

    # Apply immediately — no need to wait for the 09:00 cron
    try:
        from app.tasks import apply_fine_late_rates
        apply_fine_late_rates()
    except Exception as e:
        print(f"⚠️ apply_fine_late_rates after create: {e}")

    return jsonify(rate.to_dict()), 201


@api_bp.route('/fine-late-rates/<int:rate_id>', methods=['DELETE'])
def delete_fine_late_rate(rate_id):
    user = get_current_user()
    if not user or user.role not in ['administrateur', 'judiciaire']:
        return jsonify({'error': 'Access denied'}), 403
    rate = FineLateRate.query.get_or_404(rate_id)
    db.session.delete(rate)
    db.session.commit()

    # Re-apply remaining rules immediately after deletion
    try:
        from app.tasks import apply_fine_late_rates
        apply_fine_late_rates()
    except Exception as e:
        print(f"⚠️ apply_fine_late_rates after delete: {e}")

    return jsonify({'message': 'Règle supprimée'}), 200


@api_bp.route('/fine-late-rates/<int:rate_id>', methods=['PUT'])
def update_fine_late_rate(rate_id):
    user = get_current_user()
    if not user or user.role not in ['administrateur', 'judiciaire']:
        return jsonify({'error': 'Access denied'}), 403
    rate = FineLateRate.query.get_or_404(rate_id)
    data = request.get_json() or {}
    try:
        months = int(data['months'])
        percentage = float(data['percentage'])
    except (KeyError, ValueError, TypeError):
        return jsonify({'error': 'months et percentage requis'}), 400
    if months < 1:
        return jsonify({'error': 'Le nombre de mois doit être ≥ 1'}), 400
    if percentage <= 0:
        return jsonify({'error': 'Le pourcentage doit être positif'}), 400
    conflict = FineLateRate.query.filter(FineLateRate.months == months, FineLateRate.id != rate_id).first()
    if conflict:
        return jsonify({'error': f'Une règle pour {months} mois existe déjà'}), 409
    rate.months = months
    rate.percentage = percentage
    db.session.commit()
    try:
        from app.tasks import apply_fine_late_rates
        apply_fine_late_rates()
    except Exception as e:
        print(f"⚠️ apply_fine_late_rates after update: {e}")
    return jsonify(rate.to_dict()), 200


@api_bp.route('/fine-late-rates/apply-now', methods=['POST'])
def apply_fine_late_rates_now():
    user = get_current_user()
    if not user or user.role not in ['administrateur', 'judiciaire']:
        return jsonify({'error': 'Access denied'}), 403
    try:
        from app.tasks import apply_fine_late_rates
        apply_fine_late_rates()
        return jsonify({'message': 'Majorations appliquées'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Insurance Management Routes
@api_bp.route('/insurances', methods=['GET'])
@jwt_required(optional=True)
def api_insurances_list():
    insurances = Insurance.query.order_by(Insurance.company_name).all()
    return jsonify({
        "insurances": [ins.to_dict() for ins in insurances]
    })


@api_bp.route('/insurances', methods=['POST'])
@jwt_required()
def api_insurances_create():
    # Validate session version (ensure token hasn't been invalidated)
    validation_error = validate_jwt_session()
    if validation_error:
        return validation_error
    
    uid = get_jwt_identity()
    user = User.query.get(int(uid))
    if not user or user.role not in ['administrateur']:
        return jsonify({"error": "Forbidden"}), 403
    
    data = request.get_json() or {}
    company_name = data.get('company_name', '').strip()
    
    if not company_name:
        return jsonify({"error": "Company name is required"}), 400
    
    # Check if already exists
    existing = Insurance.query.filter_by(company_name=company_name).first()
    if existing:
        return jsonify({"error": "This insurance company already exists"}), 400
    
    insurance = Insurance(
        company_name=company_name,
        phone=data.get('phone', '').strip(),
        island=data.get('island', ''),
        address=data.get('address', '').strip()
    )
    
    db.session.add(insurance)
    db.session.commit()
    
    return jsonify(insurance.to_dict()), 201


@api_bp.route('/insurances/<int:insurance_id>', methods=['PUT'])
@jwt_required()
def api_insurances_update(insurance_id):
    # Validate session version (ensure token hasn't been invalidated)
    validation_error = validate_jwt_session()
    if validation_error:
        return validation_error
    
    uid = get_jwt_identity()
    user = User.query.get(int(uid))
    if not user or user.role not in ['administrateur']:
        return jsonify({"error": "Forbidden"}), 403
    
    insurance = Insurance.query.get_or_404(insurance_id)
    data = request.get_json() or {}
    
    if 'company_name' in data:
        new_name = data.get('company_name', '').strip()
        # Check if new name conflicts with another insurance
        existing = Insurance.query.filter_by(company_name=new_name).first()
        if existing and existing.id != insurance_id:
            return jsonify({"error": "This insurance company name already exists"}), 400
        insurance.company_name = new_name
    
    if 'phone' in data:
        insurance.phone = data.get('phone', '').strip()
    
    if 'island' in data:
        insurance.island = data.get('island', '')
    
    if 'address' in data:
        insurance.address = data.get('address', '').strip()
    
    db.session.commit()
    return jsonify(insurance.to_dict())


@api_bp.route('/insurances/<int:insurance_id>', methods=['DELETE'])
@jwt_required()
def api_insurances_delete(insurance_id):
    # Validate session version (ensure token hasn't been invalidated)
    validation_error = validate_jwt_session()
    if validation_error:
        return validation_error
    
    uid = get_jwt_identity()
    user = User.query.get(int(uid))
    if not user or user.role not in ['administrateur']:
        return jsonify({"error": "Forbidden"}), 403
    
    insurance = Insurance.query.get_or_404(insurance_id)
    db.session.delete(insurance)
    db.session.commit()
    
    return jsonify({"message": "Insurance deleted successfully"})


@api_bp.route('/vehicles/lookup-phone', methods=['GET'])
@jwt_required(optional=True)
def api_lookup_phone():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Forbidden"}), 403
    phone = request.args.get('phone', '').strip()
    if not phone:
        return jsonify({"found": False})
    vehicle = Vehicle.query.filter_by(owner_phone=phone).order_by(Vehicle.created_at.desc()).first()
    if vehicle and vehicle.owner_name:
        return jsonify({"found": True, "owner_name": vehicle.owner_name})
    from app.models import VehicleOwner
    vo = VehicleOwner.query.filter_by(phone=phone).order_by(VehicleOwner.created_at.desc()).first()
    if vo and vo.owner_name:
        return jsonify({"found": True, "owner_name": vo.owner_name})
    return jsonify({"found": False})


@api_bp.route('/vehicles/check-plate', methods=['GET'])
@jwt_required(optional=True)
def api_check_plate():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Forbidden"}), 403
    plate = request.args.get('plate', '').upper().strip()
    if not plate:
        return jsonify({"exists": False})
    exists = Vehicle.query.filter_by(license_plate=plate).first() is not None
    return jsonify({"exists": exists, "plate": plate})


@api_bp.route('/vehicles/search', methods=['GET'])
@jwt_required(optional=True)
def api_vehicles_search():
    user = get_current_user()
    if not user or user.role not in ['policier', 'administrateur', 'judiciaire']:
        return jsonify({"error": "Forbidden"}), 403
    
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({"vehicles": []})
    
    # Exact plate match only — no partial search
    vehicles_query = Vehicle.query.filter(
        Vehicle.license_plate == q.upper().strip()
    )

    if user.role == 'judiciaire' and user.country:
        vehicles_query = vehicles_query.filter(Vehicle.owner_island == user.country)

    vehicles = vehicles_query.limit(10).all()

    setting = VignetteSetting.get()
    renewal_opening = None
    if setting and setting.renewal_opening_date:
        from datetime import date
        renewal_opening = setting.renewal_opening_date
    now_date = now_comoros().date()

    def vehicle_dict_with_renewal(v):
        d = v.to_dict()
        if renewal_opening:
            in_renewal = now_date >= renewal_opening
            expiry_str = d.get('vignette_expiry')
            vignette_active = bool(expiry_str and expiry_str >= str(now_date))
            payment_approved = bool(getattr(v, 'vignette_payment_approved', False))
            d['renewal_needed'] = in_renewal and vignette_active and not payment_approved
            d['renewal_period_open'] = in_renewal
        else:
            d['renewal_needed'] = False
            d['renewal_period_open'] = False
        return d

    return jsonify({
        "vehicles": [vehicle_dict_with_renewal(v) for v in vehicles]
    })


@api_bp.route('/vehicles/<int:vehicle_id>/qrcode/renew', methods=['POST'])
@login_required
def api_vehicle_qrcode_renew(vehicle_id):
    """Renew QR code for a vehicle and record a SmartTech payment."""
    from app.models import QRCodePayment, SmartTechSetting
    from datetime import timedelta

    vehicle = Vehicle.query.get(vehicle_id)
    if not vehicle:
        return jsonify({'error': 'Véhicule introuvable.'}), 404

    now = now_comoros()
    vehicle.qr_code_expiry = now + timedelta(days=365)
    vehicle.status = 'active'

    amount = float(SmartTechSetting.get('qr_renewal_price', 3000) or 3000)
    payment = QRCodePayment(
        vehicle_id=vehicle.id,
        payment_type='renewal',
        amount=amount,
        status='paid',
        paid_at=now,
        recorded_by=current_user.username,
    )
    db.session.add(payment)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': f'QR Code renouvelé pour {vehicle.license_plate}.',
        'new_expiry': vehicle.qr_code_expiry.strftime('%d/%m/%Y'),
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

    if vehicle.owner_phone:
        _sync_vehicle_owner_link(vehicle)

    log_user_history(
        user,
        'Véhicule créé (mobile)',
        f"Véhicule {vehicle.license_plate} - {vehicle.owner_name} ({vehicle.vehicle_type})"
    )
    
    return jsonify({
        "message": "Vehicle created successfully",
        "vehicle": vehicle.to_dict()
    }), 201


@api_bp.route('/vehicles/<int:vehicle_id>', methods=['PUT'])
@jwt_required(optional=True)
def api_vehicles_update(vehicle_id):
    user = get_current_user()
    if not user or user.role not in ['administrateur', 'judiciaire', 'policier']:
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

    if 'owner_phone' in data or 'owner_name' in data:
        _sync_vehicle_owner_link(vehicle)

    changed_fields = []
    for field in [
        'license_plate', 'owner_name', 'owner_phone', 'owner_island',
        'vehicle_type', 'usage_type', 'color', 'make', 'model', 'year',
        'owner_address', 'vin', 'status', 'insurance_company', 'notes',
        'registration_date', 'registration_expiry', 'insurance_expiry',
        'vignette_expiry', 'last_inspection_date'
    ]:
        if field in data:
            changed_fields.append(field.replace('_', ' '))

    if changed_fields:
        log_user_history(
            user,
            'Véhicule modifié (mobile)',
            f"Véhicule {vehicle.license_plate}: {', '.join(changed_fields)}"
        )
    
    return jsonify({
        "message": "Vehicle updated successfully",
        "vehicle": vehicle.to_dict()
    })


@api_bp.route('/vehicles/<int:vehicle_id>/status', methods=['PUT'])
@jwt_required(optional=True)
def api_vehicles_update_status(vehicle_id):
    user = get_current_user()
    if not user or user.role not in ['administrateur', 'judiciaire', 'policier']:
        return jsonify({"error": "Forbidden"}), 403

    validation_error = validate_jwt_session()
    if validation_error:
        return validation_error

    vehicle = Vehicle.query.get(vehicle_id)
    if not vehicle:
        return jsonify({"error": "Vehicle not found"}), 404

    if user.role == 'judiciaire' and user.country:
        if vehicle.owner_island != user.country:
            return jsonify({"error": "Forbidden"}), 403

    data = request.get_json() or {}
    status = str(data.get('status', '')).strip().lower()
    if status not in ['active', 'inactive', 'suspended']:
        return jsonify({"error": "Invalid status"}), 400

    old_status = vehicle.status
    vehicle.status = status
    vehicle.updated_at = now_comoros()

    from app.models import VehicleHistory
    status_labels = {
        'active': 'Actif',
        'inactive': 'Inactif',
        'suspended': 'Suspendu',
    }
    db.session.add(VehicleHistory(
        vehicle_id=vehicle.id,
        action='Statut du véhicule modifié (mobile)',
        officer=getattr(user, 'username', '') or '',
        notes=f"Statut changé de {status_labels.get(old_status, old_status or 'Inconnu')} à {status_labels.get(status, status or 'Inconnu')}"
    ))
    db.session.commit()

    return jsonify({
        "message": "Vehicle status updated successfully",
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
        base_amount=amount,
        reason=reason,
        officer=user.username,
        issued_at=now_comoros(),
        paid=False
    )
    
    db.session.add(fine)
    db.session.commit()

    log_user_history(
        user,
        'Amende créée (mobile)',
        f"Amende pour {vehicle.license_plate}: {reason} ({amount})"
    )

    # Send push notification to vehicle owner
    push_result = send_fine_push_notification(vehicle, fine)
    print(f"📲 Push notification result: {push_result}")
    
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

    log_user_history(
        user,
        'Profil modifié (mobile)',
        'Modification du profil depuis l\'application mobile'
    )
    
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

    log_user_history(
        user,
        'Mot de passe modifié (mobile)',
        'Changement du mot de passe depuis l\'application mobile'
    )
    
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
        
        unpaid_amount = db.session.query(func.sum(Fine.amount)).filter(
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
            'unpaid_count': unpaid_count,
            'unpaid_amount': float(unpaid_amount or 0)
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
    country = request.args.get('country', '')
    query = Phone.query
    query = apply_island_filter(query, Phone.island, force_country=country)
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

    log_user_history(
        current_user,
        'Téléphone créé (mobile)',
        f"Téléphone {phone.phone_code} - {phone.brand} {phone.model}"
    )
    
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

    log_user_history(
        current_user,
        'Téléphone modifié (mobile)',
        f"Téléphone {phone.phone_code} mis à jour"
    )
    
    return jsonify(phone.to_dict())


@api_bp.route('/phones/<int:phone_id>', methods=['DELETE'])
@login_required
def api_phone_delete(phone_id):
    """Delete a phone"""
    phone = Phone.query.get(phone_id)
    if not phone:
        return jsonify({'error': 'Phone not found'}), 404

    phone_code = phone.phone_code
    
    db.session.delete(phone)
    db.session.commit()

    log_user_history(
        current_user,
        'Téléphone supprimé (mobile)',
        f"Téléphone {phone_code} supprimé"
    )
    
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
    # Handle notes safely - can be None or empty string
    notes = data.get('notes')
    if notes:
        notes = notes.strip() or None
    else:
        notes = None
    checkout_at = data.get('checkout_at')  # Optional: for manual borrow by admin/judiciaire
    
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
    
    # Use provided checkout_at or current time
    if checkout_at:
        try:
            from datetime import datetime
            # Clean up the ISO string for parsing
            # Remove 'Z' and replace it with empty (assume UTC)
            clean_checkout = checkout_at.replace('Z', '')
            # Remove timezone offset if present
            if '+' in clean_checkout:
                clean_checkout = clean_checkout.split('+')[0]
            elif clean_checkout.count('-') > 2:  # More than date dashes
                # Has timezone offset
                clean_checkout = clean_checkout[:clean_checkout.rfind('-')]
            
            # Parse using fromisoformat
            checkout_datetime = datetime.fromisoformat(clean_checkout)
        except Exception as e:
            print(f'Date parsing error: {str(e)}, Input: {checkout_at}')
            return jsonify({'error': f'Invalid date format. Please use ISO 8601 format.'}), 400
    else:
        checkout_datetime = now_comoros()
    
    usage = PhoneUsage(
        phone_id=phone_id,
        user_id=user_id,
        checkout_at=checkout_datetime,
        notes=notes
    )
    
    db.session.add(usage)
    db.session.commit()

    lender_name = getattr(current_user, 'username', 'system') if current_user else 'system'
    log_user_history(
        user,
        'Téléphone emprunté',
        f"Téléphone {phone.phone_code} emprunté à {lender_name}" + (f" - Notes: {notes}" if notes else '')
    )
    
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

    log_user_history(
        usage.user,
        'Téléphone retourné',
        f"Téléphone {usage.phone.phone_code if usage.phone else usage.phone_id} retourné"
    )
    
    return jsonify(usage.to_dict())


@api_bp.route('/phone-usage/list', methods=['GET'])
@login_required
def api_phone_usage_list():
    """Get phone usage records - by default only active (checked out) phones"""
    # Get query parameter: show_all=true to show all records, otherwise only active
    show_all = request.args.get('show_all', 'false').lower() == 'true'
    country = request.args.get('country', '')
    
    query = PhoneUsage.query.join(Phone)
    query = apply_island_filter(query, Phone.island, force_country=country)
    
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
    country = request.args.get('country', '')
    
    query_phones = Phone.query
    query_phones = apply_island_filter(query_phones, Phone.island, force_country=country)
    
    total_phones = query_phones.count()
    active_phones = query_phones.filter_by(status='active').count()
    inactive_phones = query_phones.filter_by(status='inactive').count()
    
    query_usages = PhoneUsage.query.join(Phone)
    query_usages = apply_island_filter(query_usages, Phone.island, force_country=country)
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
    """Get all users - no country filtering"""
    # Show all policiers and admins regardless of country
    query = User.query.filter(User.role.in_(['policier', 'administrateur']))
    users = query.order_by(User.username).all()
    
    return jsonify([{
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
    } for u in users])


@api_bp.route('/users/policiers', methods=['GET'])
@login_required
def api_policiers_list():
    """Get list of policiers - accessible to admin and judiciaire
    If judiciaire, filters by their country. If admin, shows all."""
    # Allow admin and judiciaire to access this endpoint
    if not (current_user.is_admin or current_user.role == 'judiciaire'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    query = User.query.filter(User.role == 'policier')
    
    # If user is judiciaire, filter by their country
    if current_user.role == 'judiciaire' and current_user.country:
        query = query.filter(User.country == current_user.country)
    
    users = query.order_by(User.username).all()
    return jsonify([{
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
    } for u in users])


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

        log_user_history(
            user,
            'Téléphone retourné (mobile)',
            f"Téléphone {phone.phone_code} retourné via scan QR"
        )
        
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

        log_user_history(
            user,
            'Téléphone attribué (mobile)',
            f"Téléphone {phone.phone_code} attribué via scan QR"
        )
        
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

@api_bp.route('/phone/manual-checkout', methods=['POST'])
@jwt_required()
def api_manual_checkout_debug():
    """Admin endpoint to manually checkout a phone to a user (for setup purposes)"""
    uid = get_jwt_identity()
    admin = User.query.get(int(uid))
    
    if not admin or admin.role != 'administrateur':
        return jsonify({"error": "Only admins can use this"}), 403
    
    data = request.get_json()
    phone_code = data.get('phone_code')
    username = data.get('username')
    
    if not phone_code or not username:
        return jsonify({"error": "phone_code and username required"}), 400
    
    # Find phone
    phone = Phone.query.filter_by(phone_code=phone_code).first()
    if not phone:
        return jsonify({"error": f"Phone {phone_code} not found"}), 404
    
    # Find user
    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify({"error": f"User {username} not found"}), 404
    
    # Check if already checked out to someone else
    existing = PhoneUsage.query.filter_by(phone_id=phone.id, checkin_at=None).first()
    if existing and existing.user_id != user.id:
        return jsonify({"error": f"Phone already checked out to {existing.user.username}"}), 409
    
    # If already checked out to same user, return it
    if existing and existing.user_id == user.id:
        return jsonify({
            'message': f'Phone {phone_code} already checked out to {user.username}',
            'phone': existing.to_dict()
        })
    
    # Create new checkout
    from datetime import datetime
    usage = PhoneUsage(
        phone_id=phone.id,
        user_id=user.id,
        checkout_at=now_comoros(),
        notes=f"Manual checkout by admin {admin.username}"
    )
    db.session.add(usage)
    db.session.commit()

    log_user_history(
        user,
        'Téléphone emprunté',
        f"Téléphone {phone.phone_code} attribué par {admin.username}"
    )

    log_user_history(
        admin,
        'Téléphone attribué manuellement (mobile)',
        f"Téléphone {phone.phone_code} attribué à {user.username}"
    )
    
    print(f"[MANUAL CHECKOUT] Phone {phone_code} checked out to {user.username}")
    
    return jsonify({
        'message': f'Phone {phone_code} successfully checked out to {user.username}',
        'phone': usage.to_dict()
    }), 201

@api_bp.route('/debug/user-phones', methods=['GET'])
@jwt_required()
def api_debug_user_phones():
    """Debug endpoint to see user's phone assignments"""
    uid = get_jwt_identity()
    user = User.query.get(int(uid))
    
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    # Find ALL phone usages for this user (active or not)
    all_usages = PhoneUsage.query.filter_by(user_id=user.id).all()
    
    usages = []
    for usage in all_usages:
        usages.append({
            'id': usage.id,
            'phone_id': usage.phone_id,
            'phone_code': usage.phone.phone_code if usage.phone else 'N/A',
            'checkout_at': usage.checkout_at.isoformat() if usage.checkout_at else None,
            'checkin_at': usage.checkin_at.isoformat() if usage.checkin_at else None,
            'is_active': usage.checkin_at is None,
            'notes': usage.notes
        })
    
    return jsonify({
        'user_id': user.id,
        'username': user.username,
        'role': user.role,
        'total_usages': len(all_usages),
        'active_usages': sum(1 for u in all_usages if u.checkin_at is None),
        'usages': usages
    })

@api_bp.route('/phone/my-checkout', methods=['GET'])
@jwt_required()
def api_my_checked_out_phone():
    """Get current user's checked-out phone (if any)"""
    uid = get_jwt_identity()
    user = User.query.get(int(uid))
    
    print(f"[my-checkout] User ID: {uid}, User: {user.username if user else 'NOT FOUND'}")
    
    if not user or user.role not in ['policier', 'administrateur']:
        print(f"[my-checkout] Unauthorized: role={user.role if user else 'N/A'}")
        return jsonify({"error": "Unauthorized"}), 403
    
    # Find active (checked out) phone usage for current user
    active_usage = PhoneUsage.query.filter_by(user_id=user.id, checkin_at=None).first()
    
    print(f"[my-checkout] Query result for user {user.id}: {active_usage}")
    
    if not active_usage:
        # Debug: Log if no phone found
        print(f"[my-checkout] No active phone usage found for user {user.id} ({user.username})")
        # Also list all usages to debug
        all_usages = PhoneUsage.query.filter_by(user_id=user.id).all()
        print(f"[my-checkout] Total usages for user: {len(all_usages)}")
        for usage in all_usages:
            print(f"  - Usage {usage.id}: phone_id={usage.phone_id}, checkout={usage.checkout_at}, checkin={usage.checkin_at}")
        return jsonify({'phone': None})
    
    phone = active_usage.phone
    if not phone:
        print(f"[my-checkout] PhoneUsage exists but phone is None for usage {active_usage.id}")
        return jsonify({'phone': None})
    
    print(f"[my-checkout] Found phone {phone.phone_code} for user {user.username}")
    
    phone_data = {
        'phone_code': phone.phone_code,
        'brand': phone.brand,
        'model': phone.model,
        'color': phone.color,
        'check_out_time': active_usage.checkout_at.isoformat() if active_usage.checkout_at else None,
        'qr_code_data': phone.qr_code_data,
        'phone_id': phone.id,
        'usage_id': active_usage.id
    }
    
    print(f"[my-checkout] Returning phone data: {phone_data}")
    
    return jsonify({
        'phone': phone_data,
        'success': True
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

    # Get vehicle details if available
    vehicle_info = {}
    if vehicle_id:
        vehicle = Vehicle.query.get(vehicle_id)
        if vehicle:
            vehicle_info = {
                'vehicle_type': vehicle.vehicle_type,
                'usage_type': vehicle.usage_type,
                'color': vehicle.color,
                'owner_name': vehicle.owner_name
            }
    elif license_plate:
        # Try to find vehicle by license plate
        vehicle = Vehicle.query.filter_by(license_plate=license_plate).first()
        if vehicle:
            vehicle_info = {
                'vehicle_type': vehicle.vehicle_type,
                'usage_type': vehicle.usage_type,
                'color': vehicle.color,
                'owner_name': vehicle.owner_name
            }

    log_user_history(
        user,
        'Photo soumise (mobile)',
        f"Photo soumise pour {license_plate or 'véhicule non précisé'}"
    )
    
    return jsonify({
        "message": "Photo submitted successfully",
        "submission_id": submission.id,
        "status": "pending",
        "license_plate": license_plate,
        "description": description,
        "vehicle": vehicle_info
    }), 201


@api_bp.route('/photo-submissions/count-pending', methods=['GET'])
def count_pending_photo_submissions():
    """Get count of pending photo submissions"""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    
    pending_count = PhotoSubmission.query.filter_by(status='pending').count()
    return jsonify({'pending_count': pending_count})


@api_bp.route('/photo-submissions/list', methods=['GET'])
def list_photo_submissions():
    # Support both JWT (mobile) and session auth (web admin)
    user = get_current_user()
    
    print(f"[DEBUG] /photo-submissions/list - User: {user}")
    print(f"[DEBUG] current_user: {current_user}, is_authenticated: {current_user.is_authenticated if current_user else 'N/A'}")
    
    if not user or user.role not in ['administrateur', 'policier', 'judiciaire']:
        print(f"[DEBUG] Access denied - user={user}, role={user.role if user else 'N/A'}")
        return jsonify({"error": "Forbidden", "user": str(user)}), 403
    
    status = request.args.get('status', 'all')
    country = request.args.get('country', '')
    
    # Join with Vehicle (for owner_island) and User (for submitter's country)
    query = PhotoSubmission.query.join(
        Vehicle, PhotoSubmission.vehicle_id == Vehicle.id, isouter=True
    ).join(
        User, PhotoSubmission.user_id == User.id
    )
    
    # Apply island filter: 
    # - Administrators can filter by country parameter, or see all if no country specified
    # - Policiers and Judiciaires see submissions for vehicles in their country OR submissions by officers in their country
    if user.role == 'administrateur' and country:
        # Admin with country filter: show submissions for vehicles in that country
        # OR submissions submitted by officers in that country (some submissions may not be linked to a vehicle)
        query = query.filter(
            (Vehicle.owner_island == country) | (User.country == country)
        )
    elif user.role in ['policier', 'judiciaire'] and user.country:
        # Non-admin: filter by their country
        query = query.filter(
            (Vehicle.owner_island == user.country) | 
            (User.country == user.country)
        )
    
    if status != 'all':
        query = query.filter(PhotoSubmission.status == status)
    
    submissions = query.order_by(PhotoSubmission.submitted_at.desc()).all()
    
    print(f"[DEBUG] Found {len(submissions)} photo submissions")
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
    submitter = submission.submitter
    vehicle_plate = submission.license_plate or (submission.vehicle.license_plate if submission.vehicle else None)
    
    # Delete photo file if status is 'resolved' to save disk space
    if status == 'resolved' and submission.photo_path and os.path.exists(submission.photo_path):
        try:
            os.remove(submission.photo_path)
            print(f"Deleted photo file: {submission.photo_path}")
        except Exception as e:
            print(f"Error deleting photo file: {e}")
    
    db.session.commit()

    log_user_history(
        user,
        'Photo traitée',
        f"Photo #{submission.id} traitée pour {vehicle_plate or 'véhicule non précisé'} - statut: {status}"
        + (f" - Notes: {review_notes}" if review_notes else '')
    )

    if submitter and submitter.id != user.id:
        log_user_history(
            submitter,
            'Photo traitée',
            f"Votre photo #{submission.id} pour {vehicle_plate or 'véhicule non précisé'} a été traitée par {user.username}"
        )
    
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

    submitter = submission.submitter
    vehicle_plate = submission.license_plate or (submission.vehicle.license_plate if submission.vehicle else None)
    
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

    log_user_history(
        user,
        'Photo supprimée',
        f"Photo #{submission_id} supprimée pour {vehicle_plate or 'véhicule non précisé'}"
    )

    if submitter and submitter.id != user.id:
        log_user_history(
            submitter,
            'Photo supprimée',
            f"Votre photo #{submission_id} pour {vehicle_plate or 'véhicule non précisé'} a été supprimée par {user.username}"
        )
    
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
    

@api_bp.route('/vehicle/track/<token>/renew-qrcode', methods=['POST'])
@login_required
def renew_vehicle_qrcode_by_token(token):
    """Renew QR code for a vehicle using track token and reactivate it"""
    try:
        vehicle = Vehicle.query.filter_by(track_token=token).first_or_404()
        
        # Check island access for judiciaire users
        if current_user.role == 'judiciaire' and current_user.country:
            if vehicle.owner_island != current_user.country:
                return jsonify({"success": False, "error": "Accès refusé"}), 403
        
        # Store old values for logging
        old_expiry = vehicle.qr_code_expiry.strftime('%Y-%m-%d') if vehicle.qr_code_expiry else 'Non défini'
        old_status = vehicle.status
        
        # Renew QR code expiry without changing the token
        vehicle.generate_qr_code_with_expiry()
        
        # Reactivate vehicle
        vehicle.status = 'active'
        
        # Log the action in vehicle history while preserving the token
        from app.models import VehicleHistory
        history = VehicleHistory(
            vehicle_id=vehicle.id,
            action=f"QR Code renouvelé - Token conservé",
            officer=current_user.username,
            notes=f"Token conservé: {vehicle.track_token}\nAncien expiry: {old_expiry}\nNouvelle expiry: {vehicle.qr_code_expiry.strftime('%Y-%m-%d')}"
        )
        db.session.add(history)
        
        db.session.commit()

        log_user_history(
            current_user,
            'QR Code renouvelé (mobile)',
            f"Véhicule {vehicle.license_plate}: QR code renouvelé et véhicule réactivé"
        )
        
        return jsonify({
            "success": True,
            "message": f"Code QR renouvelé et véhicule réactivé",
            "old_status": old_status,
            "new_status": vehicle.status,
            "track_token": vehicle.track_token,
            "token_unchanged": True,
            "old_expiry": old_expiry,
            "new_expiry": vehicle.qr_code_expiry.strftime('%Y-%m-%d'),
            "generated_at": vehicle.qr_code_generated_at.strftime('%Y-%m-%d %H:%M:%S')
        }), 200
    
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# VEHICLE TRANSFER ENDPOINTS (ADMIN)
# ============================================================================

@api_bp.route('/vehicle-transfers', methods=['GET'])
def get_vehicle_transfers():
    """Get all vehicle transfer requests"""
    try:
        # Get current user
        user = get_current_user()
        print(f"[DEBUG] /vehicle-transfers - User: {user}")

        if not user or user.role not in ['administrateur', 'judiciaire']:
            print(f"[DEBUG] Access denied - user={user}, role={user.role if user else 'N/A'}")
            return jsonify({'error': 'Access denied'}), 403

        # Get query parameters for filtering
        status = request.args.get('status', '')
        license_plate = request.args.get('license_plate', '').upper()
        transfer_type = request.args.get('transfer_type', '')
        country = request.args.get('country', '')

        # Join with Vehicle to allow island filtering and plate search
        query = VehicleTransfer.query.join(
            Vehicle, VehicleTransfer.vehicle_id == Vehicle.id, isouter=True
        )

        # Apply island filter:
        # - Judiciaire: automatically restricted to their island
        # - Administrateur: filtered only when a country param is explicitly provided
        if user.role == 'judiciaire' and user.country:
            query = query.filter(Vehicle.owner_island == user.country)
        elif user.role == 'administrateur' and country:
            query = query.filter(Vehicle.owner_island == country)

        # Apply other filters
        if status:
            query = query.filter(VehicleTransfer.status == status)
        if transfer_type:
            query = query.filter(VehicleTransfer.transfer_type == transfer_type)
        if license_plate:
            query = query.filter(Vehicle.license_plate.ilike(f'%{license_plate}%'))

        # Sort by created date descending
        transfers = query.order_by(VehicleTransfer.created_at.desc()).all()

        # Pre-fetch vehicles by ID in one query — bypasses ORM relationship loading
        # issues (e.g. SQLite FK enforcement off, or joinedload conflict with explicit join).
        transfer_vehicle_ids = list({t.vehicle_id for t in transfers if t.vehicle_id})
        vehicles_by_id = {}
        if transfer_vehicle_ids:
            vehicles_by_id = {
                v.id: v for v in Vehicle.query.filter(Vehicle.id.in_(transfer_vehicle_ids)).all()
            }

        # Build result with proper current_owner_name
        result = []
        for t in transfers:
            transfer_dict = t.to_dict()
            vehicle = t.vehicle or vehicles_by_id.get(t.vehicle_id)
            if vehicle:
                transfer_dict['current_owner_name'] = vehicle.owner_name
                transfer_dict['vehicle'] = {
                    'id': vehicle.id,
                    'license_plate': vehicle.license_plate,
                    'current_owner': vehicle.owner_name,
                    'track_token': vehicle.track_token,
                }
            result.append(transfer_dict)
        
        print(f"✅ Fetched {len(result)} vehicle transfers")
        return jsonify(result), 200
    
    except Exception as e:
        print(f"❌ Error fetching transfers: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@api_bp.route('/vehicle-transfers', methods=['POST'])
def create_vehicle_transfer():
    """Create a new vehicle transfer request (citizen submission)"""
    try:
        # Get current user (mobile app)
        user = get_current_user()
        if not user:
            return jsonify({'error': 'Authentication required'}), 401
        
        # Get form data
        vehicle_id = request.form.get('vehicle_id', type=int)
        transfer_type = request.form.get('transfer_type', '').strip()
        new_owner_phone = request.form.get('new_owner_phone', '').strip()
        new_owner_name = request.form.get('new_owner_name', '').strip()
        transfer_reason = request.form.get('transfer_reason', '').strip() or None
        
        # Validate required fields
        if not vehicle_id or not transfer_type or not new_owner_phone or not new_owner_name:
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Validate transfer type
        valid_types = ['sale', 'gift', 'inheritance', 'other']
        if transfer_type not in valid_types:
            return jsonify({'error': f'Invalid transfer type. Must be one of: {", ".join(valid_types)}'}), 400
        
        # Get vehicle
        vehicle = Vehicle.query.get(vehicle_id)
        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404
        
        # Verify user owns the vehicle
        if vehicle.owner_phone != user.phone:
            return jsonify({'error': 'You can only transfer vehicles you own'}), 403
        
        # Handle identity document upload
        identity_document_path = None
        if 'identity_document' in request.files:
            doc_file = request.files['identity_document']
            
            if doc_file.filename != '':
                # Validate file type (PDF or image)
                allowed_types = ['application/pdf', 'image/jpeg', 'image/png', 'image/jpg', 'image/gif', 'image/webp']
                if doc_file.content_type not in allowed_types:
                    return jsonify({'error': 'Only PDF and image files (JPEG, PNG, GIF, WebP) are allowed'}), 400
                
                # Create uploads directory if not exists
                upload_dir = os.path.join(os.path.dirname(__file__), 'static', 'identity_documents')
                os.makedirs(upload_dir, exist_ok=True)
                
                # Generate unique filename
                ext = secure_filename(doc_file.filename).split('.')[-1]
                filename = f"transfer_{uuid.uuid4()}.{ext}"
                filepath = os.path.join(upload_dir, filename)
                
                # Save file
                doc_file.save(filepath)
                identity_document_path = filename
                
                print(f"[DEBUG] Identity document saved: {filename}")
        
        # Create vehicle transfer record
        transfer = VehicleTransfer(
            vehicle_id=vehicle_id,
            current_owner_phone=user.phone,
            new_owner_phone=new_owner_phone,
            new_owner_name=new_owner_name,
            transfer_type=transfer_type,
            reason=transfer_reason,
            identity_document_path=identity_document_path,
            status='pending'
        )
        
        db.session.add(transfer)
        db.session.commit()
        
        print(f"✅ Vehicle transfer created: {vehicle.license_plate} by {user.phone}")
        
        return jsonify({
            'message': 'Transfer request submitted successfully',
            'transfer': transfer.to_dict()
        }), 201
    
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error creating transfer: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500




@api_bp.route('/vehicle-transfers/<int:transfer_id>', methods=['PUT'])
def update_vehicle_transfer(transfer_id):
    """Update a vehicle transfer request.
    - Admins (Flask session): can edit all fields including current owner info.
    - Citizens (JWT): can only edit their own pending transfers (new owner fields + reason).
    """
    try:
        user = get_current_user()
        is_admin = user and hasattr(user, 'role') and user.role in ['administrateur', 'judiciaire']
        is_citizen = False

        if not user:
            # Fall back to JWT for citizen mobile app
            try:
                from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity as _get_identity
                verify_jwt_in_request()
                citizen_id = _get_identity()
                citizen = User.query.get(citizen_id)
                if citizen and citizen.role == 'citizen':
                    user = citizen
                    is_citizen = True
            except Exception:
                return jsonify({'error': 'Authentication required'}), 401
        elif not is_admin:
            is_citizen = True

        if not user:
            return jsonify({'error': 'Authentication required'}), 401

        transfer = VehicleTransfer.query.get(transfer_id)
        if not transfer:
            return jsonify({'error': 'Transfer not found'}), 404

        if not is_admin:
            # Citizens can only edit their own pending transfers
            vehicle = Vehicle.query.get(transfer.vehicle_id)
            if not vehicle or vehicle.owner_phone != getattr(user, 'phone', None):
                return jsonify({'error': 'You can only edit your own transfer requests'}), 403

        if transfer.status != 'pending':
            return jsonify({'error': 'Can only edit pending transfer requests'}), 400

        data = request.get_json()

        # Fields editable by everyone
        if 'new_owner_phone' in data:
            transfer.new_owner_phone = data['new_owner_phone']
        if 'new_owner_name' in data:
            transfer.new_owner_name = data['new_owner_name']
        if 'reason' in data:
            transfer.reason = data['reason']

        # Fields editable by admins only
        vehicle = transfer.vehicle or Vehicle.query.get(transfer.vehicle_id)
        if is_admin:
            if 'current_owner_phone' in data:
                transfer.current_owner_phone = data['current_owner_phone']
            if 'current_owner_name' in data and vehicle:
                vehicle.owner_name = data['current_owner_name']

        db.session.commit()
        result = transfer.to_dict()
        if vehicle:
            result['current_owner_name'] = vehicle.owner_name
            result['vehicle'] = {
                'id': vehicle.id,
                'license_plate': vehicle.license_plate,
                'current_owner': vehicle.owner_name
            }
        return jsonify(result), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Error updating transfer: {str(e)}'}), 500


@api_bp.route('/vehicle-transfers/<int:transfer_id>/identity-document', methods=['GET'])
def get_transfer_identity_document(transfer_id):
    """Get identity document for a vehicle transfer (admin only)"""
    try:
        # Get current user
        user = get_current_user()
        if not user or user.role not in ['administrateur', 'judiciaire']:
            return jsonify({'error': 'Access denied'}), 403
        
        # Get transfer
        transfer = VehicleTransfer.query.get(transfer_id)
        if not transfer or not transfer.identity_document_path:
            return jsonify({'error': 'Document not found'}), 404
        
        # Build file path — handle two upload conventions:
        # - Mobile/api.py uploads: path is just the filename, stored in static/identity_documents/
        # - Web/routes.py uploads: path includes directory prefix like "vehicle_transfers/file.jpg"
        static_dir = os.path.join(os.path.dirname(__file__), 'static')
        if os.sep in transfer.identity_document_path or '/' in transfer.identity_document_path:
            doc_path = os.path.join(static_dir, transfer.identity_document_path)
        else:
            doc_path = os.path.join(static_dir, 'identity_documents', transfer.identity_document_path)

        if not os.path.exists(doc_path):
            return jsonify({'error': 'Document file not found'}), 404

        # Determine MIME type
        ext = transfer.identity_document_path.rsplit('.', 1)[-1].lower()
        mime_type = 'application/pdf' if ext == 'pdf' else f'image/{ext}' if ext in ('jpg', 'jpeg', 'png', 'gif') else 'application/octet-stream'
        
        print(f"[DEBUG] Serving identity document: {transfer.identity_document_path}")
        
        return send_file(
            doc_path,
            mimetype=mime_type,
            as_attachment=False,
            download_name=f"transfer_{transfer.id}_identity.{transfer.identity_document_path.split('.')[-1]}"
        )
    
    except Exception as e:
        print(f"❌ Error retrieving identity document: {e}")
        return jsonify({'error': str(e)}), 500


@api_bp.route('/vehicle-transfers/approve', methods=['POST'])
def approve_vehicle_transfer():
    """Approve a vehicle transfer request (admin only)"""
    try:
        # Get current user
        user = get_current_user()
        if not user or user.role not in ['administrateur', 'judiciaire']:
            return jsonify({'error': 'Access denied'}), 403
        
        data = request.get_json() or {}
        transfer_id = data.get('transfer_id')
        notes = data.get('notes', '')
        
        if not transfer_id:
            return jsonify({'error': 'transfer_id required'}), 400
        
        # Get the transfer
        transfer = VehicleTransfer.query.get(transfer_id)
        if not transfer:
            return jsonify({'error': 'Transfer not found'}), 404
        
        if transfer.status != 'pending':
            return jsonify({'error': 'Only pending transfers can be approved'}), 400
        
        # Get the vehicle
        vehicle = Vehicle.query.get(transfer.vehicle_id)
        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404
        
        # Capture old owner details before overwriting
        old_owner_name = vehicle.owner_name or ''
        old_owner_phone = vehicle.owner_phone or ''

        # Update transfer status
        transfer.status = 'approved'
        transfer.processed_at = now_comoros()
        transfer.processed_by = user.id
        transfer.notes = notes

        # Update vehicle owner information
        vehicle.owner_name = transfer.new_owner_name
        vehicle.owner_phone = transfer.new_owner_phone
        vehicle.updated_at = now_comoros()

        # Save old owner push token before we hand the VehicleOwner record to the new owner
        current_owner = VehicleOwner.query.filter_by(vehicle_id=vehicle.id).first()
        old_push_token = current_owner.expo_push_token if current_owner else None

        # Force-logout current owner: bump session_version so their JWT is rejected
        if current_owner:
            current_owner.session_version = (current_owner.session_version or 0) + 1
            current_owner.current_device_id = None
            current_owner.expo_push_token = None  # new owner registers their own token

        # Force-logout new owner: they may have an account on another vehicle
        for acct in VehicleOwner.query.filter_by(phone=transfer.new_owner_phone).all():
            acct.session_version = (acct.session_version or 0) + 1
            acct.current_device_id = None

        # Create or update VehicleOwner record for this vehicle
        vehicle_owner = current_owner
        if not vehicle_owner:
            vehicle_owner = VehicleOwner(
                vehicle_id=vehicle.id,
                phone=transfer.new_owner_phone,
                owner_name=transfer.new_owner_name,
                session_version=1
            )
            db.session.add(vehicle_owner)
        else:
            vehicle_owner.owner_name = transfer.new_owner_name
            vehicle_owner.phone = transfer.new_owner_phone
            vehicle_owner.updated_at = now_comoros()

        # Record the transfer approval in the vehicle history so the track page shows it
        approver_name = getattr(user, 'username', None) or str(user.id)
        _type_labels = {'sale': 'Vente', 'gift': 'Donation', 'inheritance': 'Héritage', 'other': 'Autre'}
        _type_label = _type_labels.get(transfer.transfer_type, transfer.transfer_type)
        history_notes = (
            f"Ancien: {old_owner_name} ({old_owner_phone}) → "
            f"Nouveau: {transfer.new_owner_name} ({transfer.new_owner_phone}) | "
            f"Type: {_type_label}"
        )
        if notes:
            history_notes += f" | Notes: {notes}"
        db.session.add(VehicleHistory(
            vehicle_id=vehicle.id,
            action='Transfert de propriété approuvé',
            officer=approver_name,
            notes=history_notes,
        ))

        db.session.commit()

        # Notify old owner that the transfer was approved (token saved before reassignment)
        try:
            from app.push_notifications import send_transfer_approved_notification
            send_transfer_approved_notification(old_push_token, vehicle.license_plate)
        except Exception as notif_err:
            print(f"⚠️ Transfer approval notification failed: {notif_err}")

        print(f"✅ Transfer approved: {vehicle.license_plate} to {transfer.new_owner_name}")

        return jsonify({
            'message': 'Transfer approved and vehicle owner updated',
            'transfer': transfer.to_dict(),
            'vehicle': {
                'id': vehicle.id,
                'license_plate': vehicle.license_plate,
                'owner_name': vehicle.owner_name,
                'owner_phone': vehicle.owner_phone
            }
        }), 200
    
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error approving transfer: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@api_bp.route('/vehicle-transfers/reject', methods=['POST'])
def reject_vehicle_transfer():
    """Reject a vehicle transfer request (admin only)"""
    try:
        # Get current user
        user = get_current_user()
        if not user or user.role not in ['administrateur', 'judiciaire']:
            return jsonify({'error': 'Access denied'}), 403
        
        data = request.get_json() or {}
        transfer_id = data.get('transfer_id')
        notes = data.get('notes', '')
        
        if not transfer_id:
            return jsonify({'error': 'transfer_id required'}), 400
        
        # Get the transfer
        transfer = VehicleTransfer.query.get(transfer_id)
        if not transfer:
            return jsonify({'error': 'Transfer not found'}), 404
        
        if transfer.status != 'pending':
            return jsonify({'error': 'Only pending transfers can be rejected'}), 400
        
        # Update transfer status
        transfer.status = 'rejected'
        transfer.processed_at = now_comoros()
        transfer.processed_by = user.id
        transfer.notes = notes

        # Record the rejection in the vehicle history
        rejecter_name = getattr(user, 'username', None) or str(user.id)
        _type_labels = {'sale': 'Vente', 'gift': 'Donation', 'inheritance': 'Héritage', 'other': 'Autre'}
        _type_label = _type_labels.get(transfer.transfer_type, transfer.transfer_type)
        rejection_notes = (
            f"Vers: {transfer.new_owner_name} ({transfer.new_owner_phone}) | "
            f"Type: {_type_label}"
        )
        if notes:
            rejection_notes += f" | Motif: {notes}"
        if transfer.vehicle:
            db.session.add(VehicleHistory(
                vehicle_id=transfer.vehicle_id,
                action='Transfert de propriété refusé',
                officer=rejecter_name,
                notes=rejection_notes,
            ))

        db.session.commit()

        # Notify the owner that their transfer request was rejected
        try:
            from app.push_notifications import send_transfer_rejected_notification
            if transfer.vehicle:
                send_transfer_rejected_notification(transfer.vehicle, notes)
        except Exception as notif_err:
            print(f"⚠️ Transfer rejection notification failed: {notif_err}")

        print(f"✅ Transfer rejected: {transfer.vehicle.license_plate if transfer.vehicle else 'Unknown'}")

        return jsonify({
            'message': 'Transfer rejected',
            'transfer': transfer.to_dict()
        }), 200
    
    except Exception as e:
        db.session.rollback()
        print(f"❌ Error rejecting transfer: {e}")
        return jsonify({'error': str(e)}), 500
@api_bp.route('/vehicle-transfers/<int:transfer_id>', methods=['DELETE'])
def delete_vehicle_transfer(transfer_id):
    user = get_current_user()
    if not user or user.role not in ['administrateur', 'judiciaire']:
        return jsonify({'error': 'Access denied'}), 403
    transfer = VehicleTransfer.query.get(transfer_id)
    if not transfer:
        return jsonify({'error': 'Transfer not found'}), 404
    db.session.delete(transfer)
    db.session.commit()
    return jsonify({'message': 'Transfer deleted'}), 200


@api_bp.route('/vehicle-transfers/check/<int:vehicle_id>', methods=['GET'])
@jwt_required()
def check_vehicle_transfer_status(vehicle_id):
    """Check if there's a pending vehicle transfer for this vehicle"""
    try:
        # Citizen tokens have identity=str(vehicle.id) and a vehicle_id claim
        claims = get_jwt()
        token_vehicle_id = claims.get('vehicle_id')
        if not token_vehicle_id or int(token_vehicle_id) != vehicle_id:
            return jsonify({'error': 'You can only check transfers for vehicles you own'}), 403

        # Get vehicle
        vehicle = Vehicle.query.get(vehicle_id)
        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404
        
        # Get the pending transfer for this vehicle (most recent one)
        transfer = VehicleTransfer.query.filter_by(
            vehicle_id=vehicle_id,
            status='pending'
        ).order_by(VehicleTransfer.created_at.desc()).first()
        
        if transfer:
            return jsonify({
                'has_pending_transfer': True,
                'transfer': transfer.to_dict()
            }), 200
        else:
            return jsonify({
                'has_pending_transfer': False,
                'transfer': None
            }), 200
            
    except Exception as e:
        print(f"Error checking transfer status: {str(e)}")
        return jsonify({'error': str(e)}), 500


# ── Photo Submission Reasons ──────────────────────────────────────────────────

def _sort_reasons(reasons):
    """'Autre' always last, rest by sort_order."""
    return sorted(reasons, key=lambda r: (r.label.strip().lower() == 'autre', r.sort_order))


@api_bp.route('/photo-submission-reasons', methods=['GET'])
def get_photo_submission_reasons():
    """Public endpoint used by mobile app to fetch active reasons."""
    reasons = PhotoSubmissionReason.query.filter_by(is_active=True)\
        .order_by(PhotoSubmissionReason.sort_order).all()
    return jsonify([r.to_dict() for r in _sort_reasons(reasons)])


@api_bp.route('/photo-submission-reasons/manage', methods=['GET'])
@login_required
def manage_photo_submission_reasons():
    """Admin list — includes inactive reasons."""
    reasons = PhotoSubmissionReason.query.order_by(PhotoSubmissionReason.sort_order).all()
    return jsonify([r.to_dict() for r in _sort_reasons(reasons)])


@api_bp.route('/photo-submission-reasons', methods=['POST'])
@login_required
def create_photo_submission_reason():
    data = request.get_json() or {}
    label = (data.get('label') or '').strip()
    if not label:
        return jsonify({'error': 'Le libellé est requis.'}), 400
    max_order = db.session.query(db.func.max(PhotoSubmissionReason.sort_order)).scalar() or 0
    reason = PhotoSubmissionReason(label=label, sort_order=max_order + 1)
    db.session.add(reason)
    db.session.commit()
    return jsonify(reason.to_dict()), 201


@api_bp.route('/photo-submission-reasons/<int:reason_id>', methods=['PUT'])
@login_required
def update_photo_submission_reason(reason_id):
    reason = PhotoSubmissionReason.query.get_or_404(reason_id)
    data = request.get_json() or {}
    if 'label' in data:
        label = data['label'].strip()
        if not label:
            return jsonify({'error': 'Le libellé est requis.'}), 400
        reason.label = label
    if 'is_active' in data:
        if reason.label.strip().lower() == 'autre':
            return jsonify({'error': '"Autre" ne peut pas être désactivé.'}), 400
        reason.is_active = bool(data['is_active'])
    db.session.commit()
    return jsonify(reason.to_dict())


@api_bp.route('/photo-submission-reasons/<int:reason_id>', methods=['DELETE'])
@login_required
def delete_photo_submission_reason(reason_id):
    reason = PhotoSubmissionReason.query.get_or_404(reason_id)
    if reason.label.strip().lower() == 'autre':
        return jsonify({'error': '"Autre" ne peut pas être supprimé.'}), 400
    db.session.delete(reason)
    db.session.commit()
    return jsonify({'ok': True})


# ── Driver Licenses ──────────────────────────────────────────────────────────

@api_bp.route('/licenses/settings', methods=['GET'])
@login_required
def api_licenses_settings_get():
    return jsonify(LicenseSetting.get().to_dict())


@api_bp.route('/licenses/settings', methods=['PUT'])
@login_required
def api_licenses_settings_put():
    if not current_user.is_admin:
        return jsonify({'error': 'Réservé à l\'administrateur'}), 403
    data = request.get_json() or {}
    s = LicenseSetting.get()
    if 'initial_points' in data:
        try:
            s.initial_points = max(0, min(20, int(data['initial_points'])))
        except (ValueError, TypeError):
            pass
    if 'temp_validity_months' in data:
        try:
            s.temp_validity_months = max(1, min(120, int(data['temp_validity_months'])))
        except (ValueError, TypeError):
            pass
    # Propagate new initial_points to all existing licenses
    DriverLicense.query.update({'points': s.initial_points})
    db.session.commit()
    return jsonify(s.to_dict())


@api_bp.route('/licenses/point-reasons', methods=['GET'])
@login_required
def api_point_reasons_list():
    reasons = PointReductionReason.query.order_by(PointReductionReason.created_at).all()
    return jsonify([r.to_dict() for r in reasons])


@api_bp.route('/licenses/point-reasons', methods=['POST'])
@login_required
def api_point_reasons_create():
    if not current_user.is_admin:
        return jsonify({'error': 'Réservé à l\'administrateur'}), 403
    data  = request.get_json() or {}
    label = (data.get('label') or '').strip()
    if not label:
        return jsonify({'error': 'Libellé obligatoire'}), 400
    try:
        pts = max(1, int(data.get('points_to_deduct', 1)))
    except (ValueError, TypeError):
        pts = 1
    r = PointReductionReason(label=label, points_to_deduct=pts)
    db.session.add(r)
    db.session.commit()
    return jsonify(r.to_dict()), 201


@api_bp.route('/licenses/point-reasons/<int:reason_id>', methods=['PUT'])
@login_required
def api_point_reasons_update(reason_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Réservé à l\'administrateur'}), 403
    r = PointReductionReason.query.get_or_404(reason_id)
    data = request.get_json() or {}
    if 'label' in data:
        r.label = data['label'].strip()
    if 'points_to_deduct' in data:
        r.points_to_deduct = int(data['points_to_deduct'])
    db.session.commit()
    return jsonify(r.to_dict())


@api_bp.route('/licenses/point-reasons/<int:reason_id>', methods=['DELETE'])
@login_required
def api_point_reasons_delete(reason_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Réservé à l\'administrateur'}), 403
    r = PointReductionReason.query.get_or_404(reason_id)
    db.session.delete(r)
    db.session.commit()
    return jsonify({'ok': True})


@api_bp.route('/licenses/status-rules', methods=['GET'])
@login_required
def api_status_rules_list():
    return jsonify([r.to_dict() for r in LicenseStatusRule.query.order_by(LicenseStatusRule.threshold).all()])


@api_bp.route('/licenses/status-rules', methods=['POST'])
@login_required
def api_status_rules_create():
    if not current_user.is_admin:
        return jsonify({'error': 'Réservé à l\'administrateur'}), 403
    data = request.get_json() or {}
    rule = LicenseStatusRule(
        status    = data.get('status', 'revoque'),
        operator  = data.get('operator', 'lt'),
        threshold = int(data.get('threshold', 0)),
    )
    db.session.add(rule)
    db.session.commit()
    return jsonify(rule.to_dict()), 201


@api_bp.route('/licenses/status-rules/apply', methods=['POST'])
@login_required
def api_status_rules_apply():
    if not current_user.is_admin:
        return jsonify({'error': 'Réservé à l\'administrateur'}), 403
    rules = LicenseStatusRule.query.order_by(LicenseStatusRule.threshold.desc()).all()
    updated = 0
    for lic in DriverLicense.query.all():
        pts = lic.points if lic.points is not None else 0
        for rule in rules:
            matched = (rule.operator == 'lt'  and pts <  rule.threshold) or \
                      (rule.operator == 'lte' and pts <= rule.threshold) or \
                      (rule.operator == 'eq'  and pts == rule.threshold)
            if matched:
                if lic.status != rule.status:
                    lic.status = rule.status
                    updated += 1
                break
    db.session.commit()
    return jsonify({'updated': updated})


@api_bp.route('/licenses/status-rules/<int:rule_id>', methods=['DELETE'])
@login_required
def api_status_rules_delete(rule_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Réservé à l\'administrateur'}), 403
    r = LicenseStatusRule.query.get_or_404(rule_id)
    db.session.delete(r)
    db.session.commit()
    return jsonify({'ok': True})


@api_bp.route('/licenses/<int:license_id>/reduce-points', methods=['POST'])
@login_required
def api_licenses_reduce_points(license_id):
    lic = DriverLicense.query.get_or_404(license_id)
    err = check_island_access(lic.holder_island)
    if err:
        return err
    data      = request.get_json() or {}
    reason_id = data.get('reason_id')
    reason    = PointReductionReason.query.get_or_404(reason_id)
    before     = lic.points or 0
    after      = max(0, before - reason.points_to_deduct)
    lic.points = after

    # Apply status rules
    rules = LicenseStatusRule.query.order_by(LicenseStatusRule.threshold.desc()).all()
    for rule in rules:
        matched = (rule.operator == 'lte' and after <= rule.threshold) or \
                  (rule.operator == 'eq'  and after == rule.threshold)
        if matched:
            lic.status = rule.status
            break

    history = PointReductionHistory(
        license_id      = lic.id,
        reason_label    = reason.label,
        points_deducted = reason.points_to_deduct,
        points_before   = before,
        points_after    = after,
        created_by      = current_user.username,
    )
    db.session.add(history)
    db.session.commit()
    return jsonify(lic.to_dict())


@api_bp.route('/licenses/<int:license_id>/reset-points', methods=['POST'])
@login_required
def api_licenses_reset_points(license_id):
    lic = DriverLicense.query.get_or_404(license_id)
    err = check_island_access(lic.holder_island)
    if err:
        return err
    s = LicenseSetting.get()
    before       = lic.points or 0
    lic.points   = s.initial_points
    lic.status   = 'actif'
    history = PointReductionHistory(
        license_id      = lic.id,
        reason_label    = 'Réinitialisation des points',
        points_deducted = 0,
        points_before   = before,
        points_after    = s.initial_points,
        created_by      = current_user.username,
    )
    db.session.add(history)
    db.session.commit()
    return jsonify(lic.to_dict())


@api_bp.route('/licenses/<int:license_id>/point-history', methods=['GET'])
@login_required
def api_licenses_point_history(license_id):
    lic = DriverLicense.query.get_or_404(license_id)
    err = check_island_access(lic.holder_island)
    if err:
        return err
    rows = PointReductionHistory.query.filter_by(license_id=license_id)\
        .order_by(PointReductionHistory.created_at.desc()).all()
    return jsonify([r.to_dict() for r in rows])


@api_bp.route('/licenses/stats', methods=['GET'])
@login_required
def api_licenses_stats():
    country = request.args.get('country', '').strip()
    base_q  = apply_island_filter(DriverLicense.query, DriverLicense.holder_island, force_country=country)

    total      = base_q.count()
    actif      = base_q.filter_by(status='actif').count()
    suspendu   = base_q.filter_by(status='suspendu').count()
    revoque    = base_q.filter_by(status='revoque').count()
    temporaire = base_q.filter_by(type_permis='temporaire').count()
    permanent  = base_q.filter_by(type_permis='permanent').count()

    return jsonify({
        'total':      total,
        'actif':      actif,
        'suspendu':   suspendu,
        'revoque':    revoque,
        'temporaire': temporaire,
        'permanent':  permanent,
    })


@api_bp.route('/licenses/last-update', methods=['GET'])
@login_required
def api_licenses_last_update():
    from sqlalchemy import func
    country = request.args.get('country', '').strip()
    q = apply_island_filter(DriverLicense.query, DriverLicense.holder_island, force_country=country)
    result = db.session.query(
        func.max(DriverLicense.updated_at).label('last_update'),
        func.count(DriverLicense.id).label('total'),
    ).select_from(q.subquery()).one()
    ts = result.last_update.strftime('%Y-%m-%d %H:%M:%S') if result.last_update else ''
    return jsonify({'key': f'{ts}|{result.total}'})


@api_bp.route('/licenses', methods=['GET'])
@login_required
def api_licenses_list():
    search   = request.args.get('q', '').strip()
    status_f = request.args.get('status', '').strip()
    type_f   = request.args.get('type', '').strip()
    country  = request.args.get('country', '').strip()
    page     = request.args.get('page', 1, type=int)
    per_page = 50

    query = apply_island_filter(DriverLicense.query, DriverLicense.holder_island, force_country=country)
    if search:
        term  = f'%{search}%'
        query = query.filter(
            db.or_(
                DriverLicense.license_number.ilike(term),
                DriverLicense.holder_name.ilike(term),
                DriverLicense.holder_firstname.ilike(term),
                DriverLicense.holder_phone.ilike(term),
            )
        )
    if status_f:
        query = query.filter(DriverLicense.status == status_f)
    if type_f:
        query = query.filter(DriverLicense.type_permis == type_f)

    total   = query.count()
    items   = query.order_by(DriverLicense.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return jsonify({
        'items': [l.to_dict() for l in items],
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': max(1, (total + per_page - 1) // per_page),
    })


@api_bp.route('/licenses', methods=['POST'])
@login_required
def api_licenses_create():
    if not (current_user.is_admin or getattr(current_user, 'role', '') in ['administrateur', 'judiciaire']):
        return jsonify({'error': 'Accès refusé'}), 403
    data = request.get_json() or {}
    num = (data.get('license_number') or '').strip().upper()
    name = (data.get('holder_name') or '').strip()
    if not num or not name:
        return jsonify({'error': 'Numéro de permis et nom obligatoires'}), 400
    if DriverLicense.query.filter_by(license_number=num).first():
        return jsonify({'error': 'Ce numéro de permis existe déjà'}), 400

    # Judiciaire can only create licenses for their assigned island
    if getattr(current_user, 'role', '') == 'judiciaire' and getattr(current_user, 'country', None):
        data['holder_island'] = current_user.country

    lic = DriverLicense(
        license_number        = num,
        holder_name           = name,
        holder_firstname      = (data.get('holder_firstname') or '').strip() or None,
        holder_phone          = (data.get('holder_phone') or '').strip() or None,
        holder_island         = data.get('holder_island') or None,
        holder_address        = (data.get('holder_address') or '').strip() or None,
        nationalite           = (data.get('nationalite') or '').strip() or None,
        sexe                  = data.get('sexe') or None,
        points                = LicenseSetting.get().initial_points,
        lieu_naissance        = (data.get('lieu_naissance') or '').strip() or None,
        centre_immatriculation= (data.get('centre_immatriculation') or '').strip() or None,
        type_permis           = data.get('type_permis') or 'permanent',
        categories            = (data.get('categories') or '').strip() or None,
        status                = data.get('status') or 'actif',
        notes                 = (data.get('notes') or '').strip() or None,
        created_by            = current_user.username,
    )
    for field, fmt in [('date_of_birth', '%Y-%m-%d'), ('issue_date', '%Y-%m-%d'), ('expiry_date', '%Y-%m-%d')]:
        val = data.get(field)
        if val:
            try:
                from datetime import date
                setattr(lic, field, datetime.strptime(val, fmt).date())
            except ValueError:
                pass
    db.session.add(lic)
    db.session.commit()
    return jsonify(lic.to_dict()), 201


@api_bp.route('/licenses/<int:license_id>', methods=['GET'])
@login_required
def api_licenses_get(license_id):
    lic = DriverLicense.query.get_or_404(license_id)
    err = check_island_access(lic.holder_island)
    if err:
        return err
    return jsonify(lic.to_dict())


@api_bp.route('/licenses/<int:license_id>/scan', methods=['GET'])
@jwt_required()
def api_licenses_scan(license_id):
    """JWT-protected license lookup for police mobile app."""
    validation_error = validate_jwt_session()
    if validation_error:
        return validation_error
    uid = get_jwt_identity()
    user = User.query.get(int(uid))
    if not user or user.role not in ['policier', 'administrateur', 'judiciaire']:
        return jsonify({'error': 'Accès refusé'}), 403
    lic = DriverLicense.query.get_or_404(license_id)
    return jsonify(lic.to_dict())


@api_bp.route('/licenses/<int:license_id>', methods=['PUT'])
@login_required
def api_licenses_update(license_id):
    if not (current_user.is_admin or getattr(current_user, 'role', '') in ['administrateur', 'judiciaire']):
        return jsonify({'error': 'Accès refusé'}), 403
    lic  = DriverLicense.query.get_or_404(license_id)
    err = check_island_access(lic.holder_island)
    if err:
        return err
    data = request.get_json() or {}

    num = (data.get('license_number') or '').strip().upper()
    if num and num != lic.license_number:
        if DriverLicense.query.filter(DriverLicense.license_number == num, DriverLicense.id != lic.id).first():
            return jsonify({'error': 'Ce numéro de permis existe déjà'}), 400
        lic.license_number = num

    if 'points' in data:
        try:
            lic.points = max(0, min(12, int(data['points'])))
        except (ValueError, TypeError):
            pass
    for field in ['holder_name', 'holder_firstname', 'holder_phone', 'holder_island', 'holder_address',
                  'nationalite', 'sexe', 'lieu_naissance', 'centre_immatriculation', 'type_permis', 'categories', 'status', 'notes']:
        if field in data:
            setattr(lic, field, (data[field] or '').strip() or None)
    if 'holder_name' in data and not (data['holder_name'] or '').strip():
        return jsonify({'error': 'Nom obligatoire'}), 400

    for field, fmt in [('date_of_birth', '%Y-%m-%d'), ('issue_date', '%Y-%m-%d'), ('expiry_date', '%Y-%m-%d')]:
        if field in data:
            val = data[field]
            if val:
                try:
                    setattr(lic, field, datetime.strptime(val, fmt).date())
                except ValueError:
                    pass
            else:
                setattr(lic, field, None)

    db.session.commit()
    return jsonify(lic.to_dict())


@api_bp.route('/licenses/<int:license_id>', methods=['DELETE'])
@login_required
def api_licenses_delete(license_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Réservé à l\'administrateur'}), 403
    lic = DriverLicense.query.get_or_404(license_id)
    if PointReductionHistory.query.filter_by(license_id=lic.id).first():
        return jsonify({'error': 'Ce permis a un historique de points et ne peut pas être supprimé.'}), 400
    if lic.photo_filename:
        try:
            photo_path = os.path.join('app', 'static', 'uploads', 'license_photos', lic.photo_filename)
            if os.path.exists(photo_path):
                os.remove(photo_path)
        except Exception:
            pass
    db.session.delete(lic)
    db.session.commit()
    return jsonify({'ok': True})


@api_bp.route('/licenses/<int:license_id>/photo', methods=['POST'])
@login_required
def api_licenses_photo(license_id):
    lic  = DriverLicense.query.get_or_404(license_id)
    file = request.files.get('photo')
    if not file or not file.filename:
        return jsonify({'error': 'Aucun fichier reçu'}), 400
    ext = os.path.splitext(secure_filename(file.filename))[1].lower()
    if ext not in {'.jpg', '.jpeg', '.png', '.webp'}:
        return jsonify({'error': 'Format non autorisé (jpg, png, webp)'}), 400
    upload_dir = os.path.join('app', 'static', 'uploads', 'license_photos')
    os.makedirs(upload_dir, exist_ok=True)
    if lic.photo_filename:
        old_path = os.path.join(upload_dir, lic.photo_filename)
        if os.path.exists(old_path):
            os.remove(old_path)
    filename = f'{uuid.uuid4().hex}{ext}'
    file.save(os.path.join(upload_dir, filename))
    lic.photo_filename = filename
    db.session.commit()
    return jsonify({'photo_url': f'/static/uploads/license_photos/{filename}'})
