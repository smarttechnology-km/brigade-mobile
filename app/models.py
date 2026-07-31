from app import db
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from sqlalchemy import event
import uuid
import json
from app.timezone_utils import now_comoros


def _cloud_url(stored_value, local_folder):
    """Return the public URL for a stored file — Cloudinary URL or local /uploads/ path."""
    if not stored_value:
        return None
    if stored_value.startswith('https://'):
        return stored_value
    return f'/uploads/{local_folder}/{stored_value}'


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    # role can be 'administrateur', 'policier', or 'judiciaire'
    role = db.Column(db.String(30), nullable=False, default='policier')
    full_name = db.Column(db.String(150), nullable=True)
    email = db.Column(db.String(150), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    country = db.Column(db.String(50), nullable=True)  # Grand Comores, Anjouan, Moheli
    region = db.Column(db.String(100), nullable=True)  # Region based on country
    dgrtr_type = db.Column(db.String(30), nullable=True)  # 'employe' | 'directeur_technique' | 'directeur_general'
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    session_version = db.Column(db.Integer, nullable=False, default=0)  # Incremented on each login to invalidate old tokens
    created_at = db.Column(db.DateTime, nullable=False, default=now_comoros)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        """Return a typed session ID to avoid collisions with insurance accounts."""
        return f'user:{self.id}'

    @property
    def is_insurance_account(self):
        return False

    def __repr__(self):
        return f'<User {self.username}>'


class UserHistory(db.Model):
    __tablename__ = 'user_history'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(200), nullable=False)
    details = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=now_comoros)

    user = db.relationship('User', backref=db.backref('history', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'action': self.action,
            'details': self.details,
            'created_at': self.created_at.strftime('%d/%m/%Y à %H:%M:%S') if self.created_at else None
        }


class Vehicle(db.Model):
    __tablename__ = 'vehicles'
    
    id = db.Column(db.Integer, primary_key=True)
    license_plate = db.Column(db.String(20), unique=True, nullable=False)
    owner_name = db.Column(db.String(100), nullable=False)
    owner_phone = db.Column(db.String(15))
    owner_island = db.Column(db.String(50))  # Grande Comore, Anjouan, Moheli
    vehicle_type = db.Column(db.String(50), nullable=False)  # voiture, moto, camion, etc.
    fuel_type = db.Column(db.String(50))  # Essence, Gazoil, Electric, autre
    usage_type = db.Column(db.String(50), default='Personnelle')  # Personnelle, Taxi, Transport public, other
    color = db.Column(db.String(50))
    status = db.Column(db.String(20), default='active')  # active, inactive, suspended
    make = db.Column(db.String(50))
    model = db.Column(db.String(50))
    year = db.Column(db.String(10))
    vin = db.Column(db.String(50))
    owner_address = db.Column(db.String(255))
    registration_expiry = db.Column(db.DateTime)
    track_token = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    registration_date = db.Column(db.DateTime, nullable=False, default=now_comoros)
    last_inspection_date = db.Column(db.DateTime)
    insurance_company = db.Column(db.String(100))
    insurance_expiry = db.Column(db.DateTime)
    vignette_expiry = db.Column(db.DateTime)
    vignette_payment_approved = db.Column(db.Boolean, nullable=False, default=False)
    vignette_payment_approved_at = db.Column(db.DateTime, nullable=True)
    vignette_payment_approved_by = db.Column(db.String(80), nullable=True)
    vignette_payment_method = db.Column(db.String(50), nullable=True)
    vignette_payment_requested_at = db.Column(db.DateTime, nullable=True)
    vignette_payment_requested_by = db.Column(db.String(80), nullable=True)
    vignette_payment_requested_expiry = db.Column(db.DateTime, nullable=True)
    vignette_last_paid_at = db.Column(db.DateTime, nullable=True)
    vignette_last_paid_by = db.Column(db.String(150), nullable=True)
    vignette_last_paid_vignette_amount = db.Column(db.Float, nullable=False, default=0.0)
    vignette_last_paid_penalty_amount = db.Column(db.Float, nullable=False, default=0.0)
    vignette_last_paid_fines_amount = db.Column(db.Float, nullable=False, default=0.0)
    vignette_last_paid_total_amount = db.Column(db.Float, nullable=False, default=0.0)
    qr_code_generated_at = db.Column(db.DateTime, nullable=True)  # When QR code was generated or renewed
    qr_code_expiry = db.Column(db.DateTime, nullable=True)  # When QR code expires (1 year after generation)
    qr_pending_approval = db.Column(db.Boolean, nullable=False, default=False)  # True until SmartTech validates QR creation
    fiscal_class = db.Column(db.String(10))  # A, B, C, D
    cv_class = db.Column(db.String(20))  # 0-5 CV, 6-9 CV, 10-12 CV, 12 CV et +
    work_zone = db.Column(db.String(100))  # Zone de travail for Taxi / Transport public
    notes = db.Column(db.Text)
    created_by = db.Column(db.String(80), nullable=True)   # username who registered the vehicle
    qr_renewed_by = db.Column(db.String(80), nullable=True)  # username who last renewed the QR code
    created_at = db.Column(db.DateTime, nullable=False, default=now_comoros)
    updated_at = db.Column(db.DateTime, nullable=False, default=now_comoros, onupdate=now_comoros)
    
    def __repr__(self):
        return f'<Vehicle {self.license_plate}>'
    
    def generate_qr_code_with_expiry(self):
        """
        Renew the QR code expiry for this vehicle without changing its track token.
        Expiry date = Today + 1 year (365 days)
        """
        from app.timezone_utils import now_comoros
        from datetime import timedelta
        
        # Use current date/time as generation date
        current_time = now_comoros()
        self.qr_code_generated_at = current_time
        
        # Set expiry to 1 year (365 days) from today
        ONE_YEAR_IN_DAYS = 365
        self.qr_code_expiry = current_time + timedelta(days=ONE_YEAR_IN_DAYS)
        
        return self.qr_code_expiry
    
    def is_qr_code_expired(self):
        """Check if the QR code has expired"""
        if not self.qr_code_expiry:
            return False
        from app.timezone_utils import now_comoros, ensure_comoros
        return now_comoros() > ensure_comoros(self.qr_code_expiry)
    
    def to_dict(self):
        def format_date(value, date_format='%Y-%m-%d'):
            if not value:
                return None
            if isinstance(value, str):
                try:
                    value = datetime.fromisoformat(value)
                except Exception:
                    return value
            return value.strftime(date_format)

        return {
            'id': self.id,
            'license_plate': self.license_plate,
            'owner_name': self.owner_name,
            'owner_phone': self.owner_phone,
            'owner_island': self.owner_island,
            'owner_address': self.owner_address,
            'vehicle_type': self.vehicle_type,
            'fuel_type': self.fuel_type,
            'usage_type': self.usage_type,
            'status': self.status,
            'make': self.make,
            'model': self.model,
            'year': self.year,
            'color': self.color,
            'vin': self.vin,
            'fiscal_class': self.fiscal_class,
            'cv_class': self.cv_class,
            'work_zone': self.work_zone,
            'registration_expiry': format_date(self.registration_expiry),
            'insurance_company': self.insurance_company,
            'insurance_expiry': format_date(self.insurance_expiry),
            'vignette_expiry': format_date(self.vignette_expiry),
            'vignette_payment_approved': bool(self.vignette_payment_approved),
            'vignette_payment_approved_at': self.vignette_payment_approved_at.isoformat() if self.vignette_payment_approved_at else None,
            'vignette_payment_approved_by': self.vignette_payment_approved_by,
            'vignette_payment_method': self.vignette_payment_method,
            'vignette_payment_requested_at': self.vignette_payment_requested_at.isoformat() if self.vignette_payment_requested_at else None,
            'vignette_payment_requested_by': self.vignette_payment_requested_by,
            'vignette_payment_requested_expiry': self.vignette_payment_requested_expiry.isoformat() if self.vignette_payment_requested_expiry else None,
            'vignette_last_paid_at': self.vignette_last_paid_at.isoformat() if self.vignette_last_paid_at else None,
            'vignette_last_paid_by': self.vignette_last_paid_by,
            'vignette_last_paid_vignette_amount': float(self.vignette_last_paid_vignette_amount or 0),
            'vignette_last_paid_penalty_amount': float(self.vignette_last_paid_penalty_amount or 0),
            'vignette_last_paid_fines_amount': float(self.vignette_last_paid_fines_amount or 0),
            'vignette_last_paid_total_amount': float(self.vignette_last_paid_total_amount or 0),
            'qr_code_generated_at': format_date(self.qr_code_generated_at),
            'qr_code_expiry': format_date(self.qr_code_expiry),
            'qr_pending_approval': bool(self.qr_pending_approval),
            'track_token': self.track_token,
            'registration_date': format_date(self.registration_date),
            'last_inspection_date': format_date(self.last_inspection_date),
            'created_at': format_date(self.created_at),
            'updated_at': format_date(self.updated_at, '%Y-%m-%d %H:%M:%S'),
            'notes': self.notes,
        }


class Payment(db.Model):
    __tablename__ = 'payments'
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), nullable=False, default='USD')
    status = db.Column(db.String(30), nullable=False, default='pending')
    huri_payment_id = db.Column(db.String(128), nullable=True)
    phone_number = db.Column(db.String(20), nullable=True)
    destination_phone = db.Column(db.String(20), nullable=True)  # Huri Money account this payment's revenue is routed to (per payment type)
    license_plate = db.Column(db.String(50), nullable=False)
    owner_name = db.Column(db.String(150), nullable=False)
    payer_name = db.Column(db.String(150), nullable=True)
    payer_email = db.Column(db.String(150), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=now_comoros)
    paid_at = db.Column(db.DateTime, nullable=True)
    fines = db.Column(db.Text, nullable=True)  # JSON-encoded list of fine IDs

    def to_dict(self):
        return {
            'id': self.id,
            'amount': float(self.amount),
            'currency': self.currency,
            'status': self.status,
            'huri_payment_id': self.huri_payment_id,
            'phone_number': self.phone_number,
            'destination_phone': self.destination_phone,
            'license_plate': self.license_plate,
            'owner_name': self.owner_name,
            'payer_name': self.payer_name,
            'payer_email': self.payer_email,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'paid_at': self.paid_at.isoformat() if self.paid_at else None,
            'fines': self.fines,
        }



class VehicleHistory(db.Model):
    __tablename__ = 'vehicle_history'
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    action = db.Column(db.String(200), nullable=False)
    officer = db.Column(db.String(100))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=now_comoros)

    vehicle = db.relationship('Vehicle', backref=db.backref('history', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'vehicle_id': self.vehicle_id,
            'action': self.action,
            'officer': self.officer,
            'notes': self.notes,
            'created_at': self.created_at.isoformat()
        }


class VehicleOwner(db.Model):
    """Mobile app owner authentication and registration"""
    __tablename__ = 'vehicle_owners'
    
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False, unique=True)
    owner_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(15), nullable=False)
    is_verified = db.Column(db.Boolean, default=False)
    session_version = db.Column(db.Integer, nullable=False, default=0)
    current_device_id = db.Column(db.String(128), nullable=True)
    expo_push_token = db.Column(db.String(255), nullable=True)
    verified_at = db.Column(db.DateTime)
    last_login = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=now_comoros)
    updated_at = db.Column(db.DateTime, nullable=False, default=now_comoros, onupdate=now_comoros)
    
    vehicle = db.relationship('Vehicle', backref=db.backref('owner_account', uselist=False))
    
    def to_dict(self):
        return {
            'id': self.id,
            'vehicle_id': self.vehicle_id,
            'owner_name': self.owner_name,
            'phone': self.phone,
            'is_verified': self.is_verified,
            'session_version': self.session_version,
            'current_device_id': self.current_device_id,
            'expo_push_token': self.expo_push_token,
            'verified_at': self.verified_at.isoformat() if self.verified_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Fine(db.Model):
    __tablename__ = 'fines'
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    amount = db.Column(db.Numeric(10,2), nullable=False)
    base_amount = db.Column(db.Numeric(10,2), nullable=True)  # original amount before late-rate increases
    reason = db.Column(db.String(255), nullable=False)
    officer = db.Column(db.String(100))
    paid = db.Column(db.Boolean, default=False)
    paid_at = db.Column(db.DateTime)
    paid_by = db.Column(db.String(100), nullable=True)
    receipt_number = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text)
    issued_at = db.Column(db.DateTime, nullable=False, default=now_comoros)
    photo_filename = db.Column(db.String(255), nullable=True)

    vehicle = db.relationship('Vehicle', backref=db.backref('fines', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'vehicle_id': self.vehicle_id,
            'amount': float(self.amount),
            'base_amount': float(self.base_amount) if self.base_amount else float(self.amount),
            'reason': self.reason,
            'officer': self.officer,
            'paid': self.paid,
            'paid_at': self.paid_at.isoformat() if self.paid_at else None,
            'paid_at_str': self.paid_at.strftime('%d/%m/%Y %H:%M') if self.paid_at else None,
            'paid_by': self.paid_by,
            'receipt_number': self.receipt_number,
            'notes': self.notes,
            'issued_at': self.issued_at.isoformat(),
            'issued_at_str': self.issued_at.strftime('%d/%m/%Y %H:%M') if self.issued_at else None,
            'photo_url': _cloud_url(self.photo_filename, 'fine_photos')
        }


def _delete_upload_file(filename, subdir):
    """Remove a file — from Cloudinary if it's a URL, else from local disk."""
    if not filename:
        return
    try:
        from app.cloudinary_utils import delete_file as cloud_delete
        cloud_delete(filename, local_folder=subdir)
    except Exception:
        pass


def _delete_fine_photo_file(filename):
    """Remove a fine's photo from disk, regardless of which code path marked it paid/deleted."""
    _delete_upload_file(filename, 'fine_photos')


@event.listens_for(Fine, 'before_update')
def _fine_delete_photo_on_paid(mapper, connection, target):
    """Once a fine is paid, its photo proof is no longer needed — free up disk space."""
    history = db.inspect(target).attrs.paid.history
    if history.has_changes() and target.paid and target.photo_filename:
        _delete_fine_photo_file(target.photo_filename)
        target.photo_filename = None


@event.listens_for(Fine, 'before_delete')
def _fine_delete_photo_on_delete(mapper, connection, target):
    """If a fine record is deleted outright (e.g. exoneration cleanup), don't orphan its photo."""
    _delete_fine_photo_file(target.photo_filename)


class FineArticle(db.Model):
    __tablename__ = 'fine_articles'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), nullable=False)          # e.g. "Art. 234-2"
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'description': self.description,
            'created_at': self.created_at.isoformat(),
        }


class FineType(db.Model):
    __tablename__ = 'fine_types'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=True)
    label = db.Column(db.String(150), nullable=False)
    amount = db.Column(db.Numeric(10,2), nullable=False)
    article_id = db.Column(db.Integer, db.ForeignKey('fine_articles.id'), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    article = db.relationship('FineArticle', backref='fine_types', lazy=True)

    def __repr__(self):
        return f'<FineType {self.label} ({self.amount})>'

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'label': self.label,
            'amount': float(self.amount),
            'article_id': self.article_id,
            'article_code': self.article.code if self.article else None,
            'created_at': self.created_at.isoformat(),
        }


class FineLateRate(db.Model):
    """Penalty percentage applied to unpaid fines based on overdue duration (months)."""
    __tablename__ = 'fine_late_rates'
    id = db.Column(db.Integer, primary_key=True)
    months = db.Column(db.Integer, nullable=False, unique=True)
    percentage = db.Column(db.Numeric(10, 2), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now_comoros)
    updated_at = db.Column(db.DateTime, nullable=False, default=now_comoros, onupdate=now_comoros)

    def to_dict(self):
        return {
            'id': self.id,
            'months': self.months,
            'percentage': float(self.percentage),
            'created_at': self.created_at.isoformat(),
        }


class Insurance(db.Model):
    __tablename__ = 'insurances'
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(150), nullable=False, unique=True)
    phone = db.Column(db.String(30), nullable=True)
    island = db.Column(db.String(50), nullable=True)  # Grande Comore, Anjouan, Moheli
    address = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=now_comoros)
    updated_at = db.Column(db.DateTime, nullable=False, default=now_comoros, onupdate=now_comoros)

    def __repr__(self):
        return f'<Insurance {self.company_name}>'

    def to_dict(self):
        return {
            'id': self.id,
            'company_name': self.company_name,
            'phone': self.phone,
            'island': self.island,
            'address': self.address,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class InsuranceAccount(db.Model, UserMixin):
    """Represents an insurance company account with login credentials"""
    __tablename__ = 'insurance_accounts'
    id = db.Column(db.Integer, primary_key=True)
    insurance_id = db.Column(db.Integer, db.ForeignKey('insurances.id'), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    contact_person = db.Column(db.String(150), nullable=True)
    contact_email = db.Column(db.String(150), nullable=True)
    contact_phone = db.Column(db.String(30), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    attestation_template = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=now_comoros)
    updated_at = db.Column(db.DateTime, nullable=False, default=now_comoros, onupdate=now_comoros)

    insurance = db.relationship('Insurance', backref=db.backref('accounts', lazy=True))
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        """Return a typed session ID to avoid collisions with regular users."""
        return f'insurance:{self.id}'
    
    def __repr__(self):
        return f'<InsuranceAccount {self.username}>'
    
    @property
    def is_insurance_account(self):
        """Property to easily check if user is an insurance account"""
        return True
    
    def to_dict(self):
        return {
            'id': self.id,
            'insurance_id': self.insurance_id,
            'insurance_name': self.insurance.company_name if self.insurance else None,
            'username': self.username,
            'contact_person': self.contact_person,
            'contact_email': self.contact_email,
            'contact_phone': self.contact_phone,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class QRCodePayment(db.Model):
    """Tracks QR code activation and renewal payments managed by Smart Development."""
    __tablename__ = 'qr_code_payments'
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    # 'activation' = first QR code for a new vehicle
    # 'renewal'    = renewing an expired QR code
    payment_type = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Float, nullable=False, default=0.0)
    status = db.Column(db.String(20), nullable=False, default='paid')  # 'pending' | 'paid'
    paid_at = db.Column(db.DateTime, nullable=True)
    recorded_by = db.Column(db.String(80), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=now_comoros)

    vehicle = db.relationship('Vehicle', backref=db.backref('qr_payments', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'vehicle_id': self.vehicle_id,
            'license_plate': self.vehicle.license_plate if self.vehicle else None,
            'owner_name': self.vehicle.owner_name if self.vehicle else None,
            'payment_type': self.payment_type,
            'amount': float(self.amount),
            'status': self.status,
            'paid_at': self.paid_at.strftime('%d/%m/%Y %H:%M') if self.paid_at else None,
            'recorded_by': self.recorded_by,
            'notes': self.notes,
            'created_at': self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else None,
        }


class SmartTechAccount(db.Model, UserMixin):
    """Smart Development agency account — independent finance dashboard login."""
    __tablename__ = 'smart_tech_accounts'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    full_name = db.Column(db.String(150), nullable=True)
    email = db.Column(db.String(150), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now_comoros)
    employee_id = db.Column(db.Integer, db.ForeignKey('st_employees.id'), nullable=True, unique=True)
    employee = db.relationship('Employee', backref=db.backref('account', uselist=False))
    role = db.Column(db.String(20), nullable=False, default='admin')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        return f'smarttech:{self.id}'

    @property
    def is_smart_tech(self):
        return True

    def __repr__(self):
        return f'<SmartTechAccount {self.username}>'


class VehicleInsuranceAssignment(db.Model):
    """Links vehicles to insurance accounts for management"""
    __tablename__ = 'vehicle_insurance_assignments'
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    insurance_account_id = db.Column(db.Integer, db.ForeignKey('insurance_accounts.id'), nullable=False)
    assigned_at = db.Column(db.DateTime, nullable=False, default=now_comoros)
    assigned_by = db.Column(db.String(100), nullable=True)  # Username who assigned it
    notes = db.Column(db.Text)
    driver_license_numbers = db.Column(db.Text)  # JSON array of license number strings
    
    vehicle = db.relationship('Vehicle', backref=db.backref('insurance_assignments', lazy=True))
    insurance_account = db.relationship('InsuranceAccount', backref=db.backref('vehicle_assignments', lazy=True))
    
    __table_args__ = (db.UniqueConstraint('vehicle_id', 'insurance_account_id', name='unique_vehicle_insurance'),)
    
    def __repr__(self):
        return f'<VehicleInsuranceAssignment {self.vehicle_id} -> {self.insurance_account_id}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'vehicle_id': self.vehicle_id,
            'insurance_account_id': self.insurance_account_id,
            'assigned_at': self.assigned_at.isoformat() if self.assigned_at else None,
            'assigned_by': self.assigned_by,
            'notes': self.notes,
            'driver_license_numbers': self.driver_license_numbers
        }


class ExoneratedVehicle(db.Model):
    __tablename__ = 'exonerated_vehicles'
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False, unique=True)
    reason = db.Column(db.String(255), nullable=False)
    added_by = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=now_comoros)

    vehicle = db.relationship('Vehicle', backref=db.backref('exoneration', uselist=False, lazy=True))

    def __repr__(self):
        return f'<ExoneratedVehicle {self.vehicle_id}>'

    def to_dict(self):
        return {
            'id': self.id,
            'vehicle_id': self.vehicle_id,
            'license_plate': self.vehicle.license_plate if self.vehicle else None,
            'owner_name': self.vehicle.owner_name if self.vehicle else None,
            'reason': self.reason,
            'added_by': self.added_by,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'created_at_str': self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else None
        }

class Phone(db.Model):
    __tablename__ = 'phones'
    id = db.Column(db.Integer, primary_key=True)
    phone_code = db.Column(db.String(20), unique=True, nullable=True)  # Compact ID like TP00001
    color = db.Column(db.String(100), nullable=True)
    brand = db.Column(db.String(100), nullable=False)
    model = db.Column(db.String(100), nullable=False)
    island = db.Column(db.String(50), nullable=True)  # Grande Comore, Anjouan, Moheli
    status = db.Column(db.String(30), nullable=False, default='active')  # 'active' or 'inactive'
    qr_code_data = db.Column(db.String(255), nullable=True)  # Dynamic QR code data (changes daily)
    qr_code_generated_at = db.Column(db.DateTime, nullable=True)  # When QR code was last generated
    created_at = db.Column(db.DateTime, nullable=False, default=now_comoros)
    notes = db.Column(db.Text, nullable=True)

    def generate_qr_code(self):
        """Generate a new QR code for this phone"""
        import uuid
        from app.timezone_utils import now_comoros
        self.qr_code_data = f"{self.phone_code}_{uuid.uuid4().hex[:12]}"
        self.qr_code_generated_at = now_comoros()
        return self.qr_code_data

    def to_dict(self):
        return {
            'id': self.id,
            'phone_code': self.phone_code,
            'color': self.color,
            'brand': self.brand,
            'model': self.model,
            'island': self.island,
            'status': self.status,
            'qr_code_data': self.qr_code_data if self.qr_code_data else self.phone_code,
            'qr_code_generated_at': self.qr_code_generated_at.isoformat() if self.qr_code_generated_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'created_at_str': self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else None,
            'notes': self.notes,
        }


class PhoneUsage(db.Model):
    __tablename__ = 'phone_usages'
    id = db.Column(db.Integer, primary_key=True)
    phone_id = db.Column(db.Integer, db.ForeignKey('phones.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    checkout_at = db.Column(db.DateTime, nullable=False, default=now_comoros)
    checkin_at = db.Column(db.DateTime, nullable=True)  # NULL if not returned yet
    notes = db.Column(db.Text, nullable=True)

    # Relationships
    phone = db.relationship('Phone', backref='usages')
    user = db.relationship('User', backref='phone_usages')

    def to_dict(self):
        return {
            'id': self.id,
            'phone_id': self.phone_id,
            'phone_code': self.phone.phone_code if self.phone else None,
            'phone_brand': self.phone.brand if self.phone else None,
            'phone_model': self.phone.model if self.phone else None,
            'user_id': self.user_id,
            'user_username': self.user.username if self.user else None,
            'user_email': self.user.email if self.user else None,
            'user_role': self.user.role if self.user else None,
            'checkout_at': self.checkout_at.isoformat() if self.checkout_at else None,
            'checkout_at_str': self.checkout_at.strftime('%d/%m/%Y %H:%M') if self.checkout_at else None,
            'checkin_at': self.checkin_at.isoformat() if self.checkin_at else None,
            'checkin_at_str': self.checkin_at.strftime('%d/%m/%Y %H:%M') if self.checkin_at else None,
            'is_active': self.checkin_at is None,
            'notes': self.notes,
        }


class PhotoSubmission(db.Model):
    __tablename__ = 'photo_submissions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=True)
    license_plate = db.Column(db.String(20), nullable=True)
    description = db.Column(db.Text, nullable=True)
    photo_filename = db.Column(db.String(255), nullable=False)
    photo_path = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected, resolved
    submitted_at = db.Column(db.DateTime, nullable=False, default=now_comoros)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_notes = db.Column(db.Text, nullable=True)
    
    # Relationships
    submitter = db.relationship('User', foreign_keys=[user_id], backref='photo_submissions')
    vehicle = db.relationship('Vehicle', backref='photo_submissions')
    reviewer = db.relationship('User', foreign_keys=[reviewed_by])
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'submitter_username': self.submitter.username if self.submitter else None,
            'submitter_full_name': self.submitter.full_name if self.submitter else None,
            'vehicle_id': self.vehicle_id,
            'license_plate': self.license_plate,
            'description': self.description,
            'photo_filename': self.photo_filename,
            'status': self.status,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
            'submitted_at_str': self.submitted_at.strftime('%d/%m/%Y %H:%M') if self.submitted_at else None,
            'reviewed_by': self.reviewed_by,
            'reviewer_username': self.reviewer.username if self.reviewer else None,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'reviewed_at_str': self.reviewed_at.strftime('%d/%m/%Y %H:%M') if self.reviewed_at else None,
            'review_notes': self.review_notes,
            'vehicle_type': self.vehicle.vehicle_type if self.vehicle else None,
            'usage_type': self.vehicle.usage_type if self.vehicle else None,
            'photo_url': _cloud_url(self.photo_filename, 'photo_submissions'),
        }


class VignetteRate(db.Model):
    """Vignette pricing rules based on fiscal class, CV class, fuel, and age"""
    __tablename__ = 'vignette_rates'
    
    id = db.Column(db.Integer, primary_key=True)
    fiscal_class = db.Column(db.String(10), nullable=True)  # A, B, C, D or NULL for all
    cv_class = db.Column(db.String(20), nullable=True)  # 0-5 CV, 6-9 CV, 10-12 CV, 12 CV et + or NULL for all
    fuel_type = db.Column(db.String(50), nullable=True)  # Essence, Gazoil, Electric or NULL for all
    vehicle_age_min = db.Column(db.Integer, nullable=True, default=0)  # Min age in years
    vehicle_age_max = db.Column(db.Integer, nullable=True)  # Max age in years (NULL for unlimited)
    price_kmf = db.Column(db.Numeric(10, 2), nullable=False)  # Price in KMF
    annual_ds = db.Column(db.Numeric(10, 2), nullable=True, default=1000)  # Annual DS (Droits de Stationnement) in KMF
    description = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=now_comoros)
    updated_at = db.Column(db.DateTime, nullable=False, default=now_comoros, onupdate=now_comoros)
    
    def __repr__(self):
        return f'<VignetteRate {self.fiscal_class}/{self.cv_class}/{self.fuel_type}>'
    
    def to_dict(self):
        price = float(self.price_kmf) if self.price_kmf else 0.0
        annual_ds = float(self.annual_ds) if self.annual_ds else 1000.0
        return {
            'id': self.id,
            'fiscal_class': self.fiscal_class,
            'cv_class': self.cv_class,
            'fuel_type': self.fuel_type,
            'vehicle_age_min': self.vehicle_age_min,
            'vehicle_age_max': self.vehicle_age_max,
            'price_kmf': price,
            'annual_ds': annual_ds,
            'total_price_kmf': price + annual_ds,
            'description': self.description,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class VehicleTransfer(db.Model):
    """Record of vehicle ownership transfers requested by owners"""
    __tablename__ = 'vehicle_transfers'
    
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    current_owner_phone = db.Column(db.String(15), nullable=False)  # Phone of current owner making the request
    new_owner_phone = db.Column(db.String(15), nullable=False)  # Phone of new owner (may not be registered yet)
    new_owner_name = db.Column(db.String(100), nullable=True)  # Name of new owner if known
    transfer_type = db.Column(db.String(50), nullable=False)  # 'sale', 'gift', 'inheritance', 'other'
    reason = db.Column(db.Text, nullable=True)  # Details about the transfer reason
    identity_document_path = db.Column(db.String(255), nullable=True)  # Path to uploaded identity document (PDF or image)
    status = db.Column(db.String(20), default='pending')  # 'pending', 'approved', 'rejected', 'completed'
    created_at = db.Column(db.DateTime, nullable=False, default=now_comoros)
    processed_at = db.Column(db.DateTime, nullable=True)
    processed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # Admin who processed it
    notes = db.Column(db.Text, nullable=True)  # Admin notes
    
    vehicle = db.relationship('Vehicle', backref='transfers')
    processor = db.relationship('User', foreign_keys=[processed_by])
    
    def to_dict(self):
        return {
            'id': self.id,
            'vehicle_id': self.vehicle_id,
            'current_owner_phone': self.current_owner_phone,
            'current_owner_name': (self.vehicle.owner_name or '') if self.vehicle else '',
            'new_owner_phone': self.new_owner_phone,
            'new_owner_name': self.new_owner_name,
            'transfer_type': self.transfer_type,
            'reason': self.reason,
            'identity_document_path': self.identity_document_path,
            'identity_document_url': _cloud_url(self.identity_document_path, 'identity_documents'),
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'processed_at': self.processed_at.isoformat() if self.processed_at else None,
            'processed_by': self.processed_by,
            'processor_username': self.processor.username if self.processor else None,
            'notes': self.notes,
        }


class PenaltyRate(db.Model):
    """Penalty pricing based on days late for vignette renewal"""
    __tablename__ = 'penalty_rates'
    
    id = db.Column(db.Integer, primary_key=True)
    days_late_min = db.Column(db.Integer, nullable=False)  # Minimum days late
    days_late_max = db.Column(db.Integer, nullable=False)  # Maximum days late
    penalty_per_day = db.Column(db.Numeric(10, 2), nullable=False)  # Penalty amount per day in KMF
    description = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=now_comoros)
    updated_at = db.Column(db.DateTime, nullable=False, default=now_comoros, onupdate=now_comoros)
    
    __table_args__ = (
        db.UniqueConstraint('days_late_min', 'days_late_max', name='unique_penalty_range'),
    )
    
    def __repr__(self):
        return f'<PenaltyRate {self.days_late_min}-{self.days_late_max} days>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'days_late_min': self.days_late_min,
            'days_late_max': self.days_late_max,
            'penalty_per_day': float(self.penalty_per_day),
            'description': self.description,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class VignetteSetting(db.Model):
    """Global vignette renewal settings — single-row table (singleton)."""
    __tablename__ = 'vignette_settings'

    id = db.Column(db.Integer, primary_key=True)
    renewal_opening_date = db.Column(db.Date, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=True, default=now_comoros, onupdate=now_comoros)
    updated_by = db.Column(db.String(80), nullable=True)

    @classmethod
    def get(cls):
        """Return the singleton row, creating it if it doesn't exist."""
        setting = cls.query.first()
        if not setting:
            setting = cls()
            db.session.add(setting)
            db.session.commit()
        return setting

    def to_dict(self):
        return {
            'renewal_opening_date': self.renewal_opening_date.isoformat() if self.renewal_opening_date else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'updated_by': self.updated_by,
        }


class Subscription(db.Model):
    """Smart Development recurring cost subscriptions."""
    __tablename__ = 'st_subscriptions'

    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(120), nullable=False)
    sub_type     = db.Column(db.String(80),  nullable=False)
    frequency    = db.Column(db.String(30),  nullable=False)
    amount       = db.Column(db.Float, nullable=False, default=0.0)
    payment_mode = db.Column(db.String(20), nullable=False, default='manuel')  # automatique / manuel
    phone_id     = db.Column(db.Integer, db.ForeignKey('phones.id'), nullable=True)
    notes        = db.Column(db.Text, nullable=True)
    is_active    = db.Column(db.Boolean, nullable=False, default=True)
    start_date   = db.Column(db.Date, nullable=True)
    last_paid_at = db.Column(db.DateTime, nullable=True)
    last_paid_by = db.Column(db.String(80), nullable=True)
    created_at   = db.Column(db.DateTime, nullable=False, default=now_comoros)
    created_by   = db.Column(db.String(80), nullable=True)
    employee_id  = db.Column(db.Integer, db.ForeignKey('st_employees.id'), nullable=True)
    phone        = db.relationship('Phone',     backref=db.backref('subscriptions', lazy=True), foreign_keys=[phone_id])
    employee     = db.relationship('Employee',  backref=db.backref('subscriptions', lazy=True), foreign_keys=[employee_id])

    _MONTHLY_FACTOR = {
        'hebdomadaire':  52 / 12,
        'mensuelle':     1,
        'trimestrielle': 1 / 3,
        'semestrielle':  1 / 6,
        'annuelle':      1 / 12,
        'ponctuelle':    0,
    }

    _NEXT_DUE_DELTA = {
        'hebdomadaire':  {'weeks': 1},
        'mensuelle':     {'months': 1},
        'trimestrielle': {'months': 3},
        'semestrielle':  {'months': 6},
        'annuelle':      {'years': 1},
    }

    def monthly_cost(self):
        return self.amount * self._MONTHLY_FACTOR.get(self.frequency, 1)

    def _build_delta(self):
        delta_kwargs = self._NEXT_DUE_DELTA.get(self.frequency)
        if not delta_kwargs:
            return None
        try:
            from dateutil.relativedelta import relativedelta
            return relativedelta(**delta_kwargs)
        except ImportError:
            from datetime import timedelta
            approx = {'weeks': 7, 'months': 30, 'years': 365}
            return timedelta(days=sum(approx.get(k, 30) * v for k, v in delta_kwargs.items()))

    def next_payment_date(self):
        """Next upcoming debit date (>= today) for automatic subscriptions."""
        delta = self._build_delta()
        if delta is None:
            return None
        base = self.start_date
        if base is None:
            return None
        from app.timezone_utils import now_comoros
        today = now_comoros().date()
        d = base
        while d < today:
            d = d + delta
        return d

    def next_manual_due_date(self):
        """Next due date for manual subscriptions: last_paid_at + delta, or start_date if never paid."""
        delta = self._build_delta()
        if delta is None:
            return None
        if self.last_paid_at:
            return self.last_paid_at.date() + delta
        return self.start_date

    def last_debit_date(self):
        """Date of the most recent past debit (next_payment_date − one period).
        Returns None when the first debit hasn't happened yet."""
        npd = self.next_payment_date()
        if npd is None or npd == self.start_date:
            return None
        delta = self._build_delta()
        if delta is None:
            return None
        return npd - delta

    def is_payment_due(self):
        """Return True when this manual subscription needs a new payment."""
        if self.payment_mode == 'automatique':
            return False
        if self.frequency == 'ponctuelle':
            return self.last_paid_at is None
        if self.last_paid_at is None:
            return True
        from app.timezone_utils import now_comoros, ensure_comoros
        delta = self._build_delta()
        if delta is None:
            return False
        return now_comoros() >= ensure_comoros(self.last_paid_at) + delta

    def to_dict(self):
        return {
            'id':           self.id,
            'name':         self.name,
            'sub_type':     self.sub_type,
            'frequency':    self.frequency,
            'amount':       self.amount,
            'payment_mode': self.payment_mode,
            'phone_id':       self.phone_id,
            'phone_label':    (f"{self.phone.phone_code} — {self.phone.brand} {self.phone.model}" if self.phone else None),
            'employee_id':    self.employee_id,
            'employee_label': (f"{self.employee.full_name} — {self.employee.position}" if self.employee else None),
            'notes':        self.notes,
            'is_active':    self.is_active,
            'monthly_cost': round(self.monthly_cost(), 2),
            'is_due':       self.is_payment_due(),
            'start_date':        self.start_date.strftime('%d/%m/%Y') if self.start_date else None,
            'start_date_iso':    self.start_date.isoformat() if self.start_date else None,
            'next_payment_date': (
                (self.next_manual_due_date().strftime('%d/%m/%Y') if self.next_manual_due_date() else None)
                if self.payment_mode == 'manuel'
                else (self.next_payment_date().strftime('%d/%m/%Y') if self.next_payment_date() else None)
            ),
            'last_debit_date':   self.last_debit_date().strftime('%d/%m/%Y') if self.last_debit_date() else None,
            'last_paid_at': self.last_paid_at.strftime('%d/%m/%Y %H:%M') if self.last_paid_at else None,
            'last_paid_by': self.last_paid_by,
            'created_at':   self.created_at.strftime('%d/%m/%Y') if self.created_at else None,
            'created_by':   self.created_by,
        }


class Employee(db.Model):
    """Smart Development employee registry."""
    __tablename__ = 'st_employees'

    id         = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(80),  nullable=False)
    last_name  = db.Column(db.String(80),  nullable=False)
    phone      = db.Column(db.String(30),  nullable=True)
    email      = db.Column(db.String(120), nullable=True)
    island     = db.Column(db.String(50),  nullable=True)
    position   = db.Column(db.String(100), nullable=False)
    salary     = db.Column(db.Float, nullable=False, default=0.0)
    hire_date  = db.Column(db.Date, nullable=True)
    status     = db.Column(db.String(20),  nullable=False, default='actif')
    notes      = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=now_comoros)
    created_by = db.Column(db.String(80), nullable=True)

    POSITIONS = [
        'Directeur', 'Responsable technique', 'Technicien',
        'Commercial', 'Comptable', 'Secrétaire', 'Agent de terrain', 'Autre',
    ]
    ISLANDS = ['Grande Comore', 'Anjouan', 'Moheli']

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'

    def to_dict(self):
        return {
            'id':         self.id,
            'first_name': self.first_name,
            'last_name':  self.last_name,
            'full_name':  self.full_name,
            'phone':      self.phone,
            'email':      self.email,
            'island':     self.island,
            'position':   self.position,
            'salary':     self.salary,
            'hire_date':     self.hire_date.strftime('%d/%m/%Y') if self.hire_date else None,
            'hire_date_iso': self.hire_date.isoformat()          if self.hire_date else None,
            'status':     self.status,
            'notes':      self.notes,
            'created_at': self.created_at.strftime('%d/%m/%Y')  if self.created_at else None,
            'created_by': self.created_by,
            'account_id':       self.account.id        if self.account else None,
            'account_username': self.account.username  if self.account else None,
            'account_active':   self.account.is_active if self.account else None,
            'account_role':     self.account.role      if self.account else None,
        }


class Expense(db.Model):
    """Smart Development one-off expenses (purchases, travel, training, etc.)."""
    __tablename__ = 'st_expenses'

    id           = db.Column(db.Integer, primary_key=True)
    description  = db.Column(db.String(200), nullable=False)
    category     = db.Column(db.String(80),  nullable=False)
    amount       = db.Column(db.Float, nullable=False, default=0.0)
    expense_date = db.Column(db.Date, nullable=False)
    vendor       = db.Column(db.String(120), nullable=True)
    notes        = db.Column(db.Text, nullable=True)
    created_at   = db.Column(db.DateTime, nullable=False, default=now_comoros)
    created_by   = db.Column(db.String(80), nullable=True)

    CATEGORIES = [
        'Achat produit',
        'Équipement',
        'Déplacement',
        'Formation',
        'Maintenance',
        'Logiciel',
        'Fournitures',
        'Autre',
    ]

    def to_dict(self):
        return {
            'id':           self.id,
            'description':  self.description,
            'category':     self.category,
            'amount':       self.amount,
            'expense_date': self.expense_date.strftime('%d/%m/%Y') if self.expense_date else None,
            'expense_date_iso': self.expense_date.isoformat() if self.expense_date else None,
            'vendor':       self.vendor,
            'notes':        self.notes,
            'created_at':   self.created_at.strftime('%d/%m/%Y') if self.created_at else None,
            'created_by':   self.created_by,
        }


class SmartTechSetting(db.Model):
    """Key-value config store for Smart Development parameters."""
    __tablename__ = 'st_settings'

    id         = db.Column(db.Integer, primary_key=True)
    key        = db.Column(db.String(60), unique=True, nullable=False)
    value      = db.Column(db.String(200), nullable=False, default='0')
    updated_at = db.Column(db.DateTime, nullable=False, default=now_comoros, onupdate=now_comoros)

    @staticmethod
    def get(key, default=0):
        row = SmartTechSetting.query.filter_by(key=key).first()
        if not row:
            return default
        try:
            f = float(row.value)
            return int(f) if f == int(f) else f
        except (ValueError, TypeError):
            return row.value

    @staticmethod
    def set(key, value):
        row = SmartTechSetting.query.filter_by(key=key).first()
        if row:
            row.value = str(value)
            row.updated_at = now_comoros()
        else:
            db.session.add(SmartTechSetting(key=key, value=str(value)))
        db.session.commit()


class PhotoSubmissionReason(db.Model):
    __tablename__ = 'photo_submission_reasons'
    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(200), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now_comoros)

    def to_dict(self):
        return {
            'id': self.id,
            'label': self.label,
            'is_active': self.is_active,
            'sort_order': self.sort_order,
        }


class DriverLicense(db.Model):
    __tablename__ = 'driver_licenses'
    id = db.Column(db.Integer, primary_key=True)
    license_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    holder_name = db.Column(db.String(150), nullable=False)   # nom de famille
    holder_firstname = db.Column(db.String(100))              # prénom
    holder_phone = db.Column(db.String(30))
    holder_island = db.Column(db.String(50))
    holder_address = db.Column(db.String(255))
    nationalite = db.Column(db.String(100))
    sexe = db.Column(db.String(10))  # 'masculin' | 'feminin'
    points = db.Column(db.Integer, nullable=False, default=12)
    date_of_birth = db.Column(db.Date)
    lieu_naissance = db.Column(db.String(150))
    centre_immatriculation = db.Column(db.String(150))
    type_permis = db.Column(db.String(20), nullable=False, default='permanent')  # 'permanent' | 'temporaire'
    categories = db.Column(db.String(100))  # comma-separated: "A,B,C"
    category_details = db.Column(db.Text, nullable=True)  # JSON: {"A": {"identifiant": "...", "date": "YYYY-MM-DD"}, ...}
    issue_date = db.Column(db.Date)
    expiry_date = db.Column(db.Date)
    status = db.Column(db.String(20), nullable=False, default='actif')  # actif, suspendu, revoque, expire
    photo_filename = db.Column(db.String(255))
    notes = db.Column(db.Text)
    created_by = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, nullable=False, default=now_comoros)
    updated_at = db.Column(db.DateTime, nullable=False, default=now_comoros, onupdate=now_comoros)
    # Links this license to a citizen app account (VehicleOwner.phone is the stable
    # identity across that person's vehicles), so it can show on their dashboard.
    registered_phone = db.Column(db.String(20), nullable=True, unique=True, index=True)
    registered_at = db.Column(db.DateTime, nullable=True)

    @property
    def photo_url(self):
        return _cloud_url(self.photo_filename, 'license_photos') or ''

    @property
    def is_expired(self):
        if not self.expiry_date:
            return False
        return self.expiry_date < now_comoros().date()

    def to_dict(self):
        try:
            category_details = json.loads(self.category_details) if self.category_details else {}
        except (ValueError, TypeError):
            category_details = {}
        return {
            'id': self.id,
            'license_number': self.license_number,
            'holder_name': self.holder_name,
            'holder_firstname': self.holder_firstname or '',
            'holder_phone': self.holder_phone or '',
            'holder_island': self.holder_island or '',
            'holder_address': self.holder_address or '',
            'nationalite': self.nationalite or '',
            'sexe': self.sexe or '',
            'points': self.points if self.points is not None else 12,
            'date_of_birth': self.date_of_birth.strftime('%Y-%m-%d') if self.date_of_birth else '',
            'lieu_naissance': self.lieu_naissance or '',
            'centre_immatriculation': self.centre_immatriculation or '',
            'type_permis': self.type_permis or 'permanent',
            'categories': self.categories or '',
            'category_details': category_details,
            'issue_date': self.issue_date.strftime('%Y-%m-%d') if self.issue_date else '',
            'expiry_date': self.expiry_date.strftime('%Y-%m-%d') if self.expiry_date else '',
            'status': self.status,
            'photo_filename': self.photo_filename or '',
            'photo_url': self.photo_url,
            'notes': self.notes or '',
            'created_by': self.created_by or '',
            'created_at': self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else '',
            'updated_at': self.updated_at.strftime('%d/%m/%Y %H:%M') if self.updated_at else '',
            'is_expired': self.is_expired,
            'registered_phone': self.registered_phone or '',
            'registered_at': self.registered_at.strftime('%d/%m/%Y %H:%M') if self.registered_at else '',
        }


class LicensePrintRequest(db.Model):
    __tablename__ = 'license_print_requests'
    id           = db.Column(db.Integer, primary_key=True)
    license_id   = db.Column(db.Integer, db.ForeignKey('driver_licenses.id'), nullable=False)
    requested_by = db.Column(db.String(100), nullable=False)
    requested_at = db.Column(db.DateTime, nullable=False, default=now_comoros)
    status       = db.Column(db.String(20), nullable=False, default='pending')  # pending | printed | cancelled
    printed_by   = db.Column(db.String(100))
    printed_at   = db.Column(db.DateTime)
    unit_price   = db.Column(db.Float, nullable=False, default=0)
    notes        = db.Column(db.Text)

    license = db.relationship('DriverLicense', backref=db.backref('print_requests', lazy='dynamic'))

    def to_dict(self):
        lic = self.license
        return {
            'id':           self.id,
            'license_id':   self.license_id,
            'license_number': lic.license_number if lic else '',
            'holder_name':    lic.holder_name    if lic else '',
            'holder_firstname': lic.holder_firstname if lic else '',
            'type_permis':  lic.type_permis      if lic else '',
            'categories':   lic.categories       if lic else '',
            'photo_filename': lic.photo_filename  if lic else '',
            'photo_url':      lic.photo_url       if lic else '',
            'requested_by': self.requested_by,
            'requested_at': self.requested_at.strftime('%d/%m/%Y %H:%M') if self.requested_at else '',
            'status':       self.status,
            'printed_by':   self.printed_by or '',
            'printed_at':   self.printed_at.strftime('%d/%m/%Y %H:%M') if self.printed_at else '',
            'unit_price':   self.unit_price or 0,
            'notes':        self.notes or '',
        }


class PointReductionArticle(db.Model):
    __tablename__ = 'point_reduction_articles'
    id          = db.Column(db.Integer, primary_key=True)
    code        = db.Column(db.String(50), nullable=False)   # e.g. "Art. R234-2"
    description = db.Column(db.Text, nullable=True)
    created_at  = db.Column(db.DateTime, nullable=False, default=now_comoros)

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'description': self.description,
            'created_at': self.created_at.isoformat(),
        }


class PointReductionReason(db.Model):
    __tablename__ = 'point_reduction_reasons'
    id               = db.Column(db.Integer, primary_key=True)
    label            = db.Column(db.String(200), nullable=False)
    points_to_deduct = db.Column(db.Integer, nullable=False, default=1)
    article_id       = db.Column(db.Integer, db.ForeignKey('point_reduction_articles.id'), nullable=True)
    created_at       = db.Column(db.DateTime, nullable=False, default=now_comoros)

    article = db.relationship('PointReductionArticle', backref='reasons', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'label': self.label,
            'points_to_deduct': self.points_to_deduct,
            'article_id': self.article_id,
            'article_code': self.article.code if self.article else None,
        }


class LicenseStatusRule(db.Model):
    __tablename__ = 'license_status_rules'
    id        = db.Column(db.Integer, primary_key=True)
    status    = db.Column(db.String(20), nullable=False)   # 'suspendu' | 'revoque'
    operator  = db.Column(db.String(5),  nullable=False, default='lte')  # 'lte' | 'eq'
    threshold = db.Column(db.Integer,    nullable=False)

    def to_dict(self):
        return {'id': self.id, 'status': self.status, 'operator': self.operator, 'threshold': self.threshold}


class PointReductionHistory(db.Model):
    __tablename__ = 'point_reduction_history'
    id              = db.Column(db.Integer, primary_key=True)
    license_id      = db.Column(db.Integer, db.ForeignKey('driver_licenses.id', ondelete='CASCADE'), nullable=False)
    reason_label    = db.Column(db.String(200), nullable=False)
    points_deducted = db.Column(db.Integer, nullable=False)
    points_before   = db.Column(db.Integer, nullable=False)
    points_after    = db.Column(db.Integer, nullable=False)
    created_by      = db.Column(db.String(100))
    created_at      = db.Column(db.DateTime, nullable=False, default=now_comoros)

    def to_dict(self):
        from datetime import timedelta
        from app.timezone_utils import now_comoros, ensure_comoros
        is_reset = self.points_after > self.points_before
        in_window = bool(self.created_at) and now_comoros() <= ensure_comoros(self.created_at) + timedelta(days=7)
        return {
            'id':              self.id,
            'license_id':      self.license_id,
            'reason_label':    self.reason_label,
            'points_deducted': self.points_deducted,
            'points_before':   self.points_before,
            'points_after':    self.points_after,
            'created_by':      self.created_by,
            'created_at':      self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else None,
            'is_reset':        is_reset,
            'reclaimable':     (not is_reset) and in_window,
        }


class LicenseSetting(db.Model):
    __tablename__ = 'license_settings'
    id                   = db.Column(db.Integer, primary_key=True)
    initial_points       = db.Column(db.Integer, nullable=False, default=12)
    temp_validity_months = db.Column(db.Integer, nullable=False, default=12)
    permanent_validity_years = db.Column(db.Integer, nullable=False, default=10)
    directeur_general_name = db.Column(db.String(150), nullable=True)
    directeur_signature_filename = db.Column(db.String(255), nullable=True)
    category_validity = db.Column(db.Text, nullable=True)

    @property
    def directeur_signature_url(self):
        return _cloud_url(self.directeur_signature_filename, 'signatures') or ''

    @staticmethod
    def get():
        s = LicenseSetting.query.first()
        if not s:
            s = LicenseSetting()
            db.session.add(s)
            db.session.commit()
        return s

    def to_dict(self):
        try:
            cat_validity = json.loads(self.category_validity) if self.category_validity else {}
        except (ValueError, TypeError):
            cat_validity = {}
        return {
            'initial_points':       self.initial_points,
            'temp_validity_months': self.temp_validity_months,
            'permanent_validity_years': self.permanent_validity_years,
            'directeur_general_name': self.directeur_general_name or '',
            'directeur_signature_filename': self.directeur_signature_filename or '',
            'directeur_signature_url': self.directeur_signature_url,
            'category_validity': cat_validity,
        }


class HuriDestinationSetting(db.Model):
    """Singleton config: which Huri Money account (phone number) receives the revenue
    for each mobile payment type, so fines/vignette/QR renewal income can be kept
    separate once real Huri Money payouts are wired up (currently a stub/simulation)."""
    __tablename__ = 'huri_destination_settings'
    id                = db.Column(db.Integer, primary_key=True)
    fine_phone        = db.Column(db.String(20), nullable=True)
    fine_phone_updated_at = db.Column(db.DateTime, nullable=True)
    fine_phone_updated_by = db.Column(db.String(80), nullable=True)
    vignette_phone    = db.Column(db.String(20), nullable=True)
    vignette_phone_updated_at = db.Column(db.DateTime, nullable=True)
    vignette_phone_updated_by = db.Column(db.String(80), nullable=True)
    qr_renewal_phone  = db.Column(db.String(20), nullable=True)
    qr_renewal_phone_updated_at = db.Column(db.DateTime, nullable=True)
    qr_renewal_phone_updated_by = db.Column(db.String(80), nullable=True)

    @staticmethod
    def get():
        s = HuriDestinationSetting.query.first()
        if not s:
            s = HuriDestinationSetting()
            db.session.add(s)
            db.session.commit()
        return s

    def phone_for(self, payment_type):
        return {
            'fine': self.fine_phone,
            'vignette': self.vignette_phone,
            'qr_renewal': self.qr_renewal_phone,
        }.get(payment_type)

    def to_dict(self):
        def fmt(dt):
            return dt.strftime('%d/%m/%Y %H:%M') if dt else None
        return {
            'fine_phone': self.fine_phone or '',
            'fine_phone_updated_at': fmt(self.fine_phone_updated_at),
            'fine_phone_updated_by': self.fine_phone_updated_by,
            'vignette_phone': self.vignette_phone or '',
            'vignette_phone_updated_at': fmt(self.vignette_phone_updated_at),
            'vignette_phone_updated_by': self.vignette_phone_updated_by,
            'qr_renewal_phone': self.qr_renewal_phone or '',
            'qr_renewal_phone_updated_at': fmt(self.qr_renewal_phone_updated_at),
            'qr_renewal_phone_updated_by': self.qr_renewal_phone_updated_by,
        }


class HuriDestinationPhoneHistory(db.Model):
    """Audit log of changes to Huri Money destination phone numbers, one row per change,
    so admins can see who changed which number and when (per payment type)."""
    __tablename__ = 'huri_destination_phone_history'
    id         = db.Column(db.Integer, primary_key=True)
    field      = db.Column(db.String(20), nullable=False)  # 'fine_phone' | 'vignette_phone' | 'qr_renewal_phone'
    old_value  = db.Column(db.String(20), nullable=True)
    new_value  = db.Column(db.String(20), nullable=True)
    changed_at = db.Column(db.DateTime, nullable=False, default=now_comoros)
    changed_by = db.Column(db.String(80), nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'old_value': self.old_value or '—',
            'new_value': self.new_value or '—',
            'changed_at': self.changed_at.strftime('%d/%m/%Y %H:%M') if self.changed_at else None,
            'changed_by': self.changed_by,
        }


class PendingPhoneChange(db.Model):
    """A requested change to a Huri Money destination phone number, awaiting confirmation
    via a code sent out-of-band (email) to a server-side-only address. Only applied once
    confirmed, so a single compromised/malicious admin account cannot redirect payment
    revenue on its own — the confirmation channel is outside the in-app account system."""
    __tablename__ = 'pending_phone_changes'
    id           = db.Column(db.Integer, primary_key=True)
    field        = db.Column(db.String(20), nullable=False)  # 'fine_phone' | 'vignette_phone'
    old_value    = db.Column(db.String(20), nullable=True)
    new_value    = db.Column(db.String(20), nullable=True)
    code_hash    = db.Column(db.String(255), nullable=False)
    attempts     = db.Column(db.Integer, nullable=False, default=0)
    requested_by = db.Column(db.String(80), nullable=True)
    requested_at = db.Column(db.DateTime, nullable=False, default=now_comoros)
    expires_at   = db.Column(db.DateTime, nullable=False)
    consumed     = db.Column(db.Boolean, nullable=False, default=False)

    MAX_ATTEMPTS = 5

    def set_code(self, code):
        self.code_hash = generate_password_hash(code)

    def check_code(self, code):
        return check_password_hash(self.code_hash, code)

    @property
    def is_expired(self):
        from app.timezone_utils import ensure_comoros
        return now_comoros() > ensure_comoros(self.expires_at)


alert_vehicles = db.Table(
    'alert_vehicles',
    db.Column('alert_id', db.Integer, db.ForeignKey('alerts.id'), primary_key=True),
    db.Column('vehicle_id', db.Integer, db.ForeignKey('vehicles.id'), primary_key=True),
)


class Alert(db.Model):
    __tablename__ = 'alerts'

    ALERT_TYPE_LABELS = {
        'accident':              'Accident',
        'recherche_vehicule':    'Recherche de véhicule',
        'route_construction':    'Route en construction',
        'evenement_circulation': 'Évènement bloquant la circulation',
        'travaux_planifies':     'Travaux planifiés',
        'autre':                 'Autre',
    }
    ISLANDS = ['Grande Comore', 'Anjouan', 'Moheli']
    NATIONAL = 'National'  # special island value: visible on all three islands
    ISLAND_OPTIONS = ISLANDS + [NATIONAL]
    VEHICLE_LINK_TYPES = ('accident', 'recherche_vehicule')  # alert types that link to vehicles in the database
    ZONE_TYPES = ('route_construction', 'evenement_circulation', 'travaux_planifies')  # alert types that show the zone field

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    alert_type = db.Column(db.String(50), nullable=False)
    custom_type_label = db.Column(db.String(100), nullable=True)  # used when alert_type == 'autre'
    island = db.Column(db.String(50), nullable=False)
    zone = db.Column(db.String(255), nullable=True)
    description = db.Column(db.Text, nullable=True)
    contact_phones = db.Column(db.Text, nullable=True)  # comma-separated phone numbers to call if the vehicle is found (recherche_vehicule)
    is_pinned = db.Column(db.Boolean, nullable=False, default=False)  # pinned alerts show first in the citizen app
    send_notification = db.Column(db.Boolean, nullable=False, default=False)
    starts_at = db.Column(db.DateTime, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)
    manually_expired = db.Column(db.Boolean, nullable=False, default=False)
    created_by = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=now_comoros)

    photos = db.relationship('AlertPhoto', backref='alert', lazy='dynamic', cascade='all, delete-orphan')
    vehicles = db.relationship('Vehicle', secondary='alert_vehicles', lazy='dynamic')

    @property
    def is_expired(self):
        if self.manually_expired:
            return True
        if self.expires_at is None:
            return False
        from app.timezone_utils import ensure_comoros
        return now_comoros() > ensure_comoros(self.expires_at)

    def to_dict(self):
        photos = self.photos.order_by(AlertPhoto.id.asc()).all()
        primary = next((p for p in photos if p.is_primary), photos[0] if photos else None)
        label = self.custom_type_label if (self.alert_type == 'autre' and self.custom_type_label) \
            else self.ALERT_TYPE_LABELS.get(self.alert_type, self.alert_type)
        return {
            'id': self.id,
            'title': self.title,
            'alert_type': self.alert_type,
            'alert_type_label': label,
            'custom_type_label': self.custom_type_label or '',
            'island': self.island,
            'zone': self.zone or '',
            'description': self.description or '',
            'contact_phones': [p.strip() for p in (self.contact_phones or '').split(',') if p.strip()],
            'vehicles': [
                {'id': v.id, 'license_plate': v.license_plate, 'owner_name': v.owner_name}
                for v in self.vehicles
            ],
            'send_notification': self.send_notification,
            'is_pinned': self.is_pinned,
            'starts_at': self.starts_at.isoformat() if self.starts_at else None,
            'starts_at_str': self.starts_at.strftime('%d/%m/%Y %H:%M') if self.starts_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'expires_at_str': self.expires_at.strftime('%d/%m/%Y %H:%M') if self.expires_at else None,
            'is_expired': self.is_expired,
            'manually_expired': self.manually_expired,
            'created_by': self.created_by or '',
            'created_at': self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else None,
            'photos': [p.to_dict() for p in photos],
            'primary_photo_url': primary.to_dict()['photo_url'] if primary else None,
        }


class AlertPhoto(db.Model):
    __tablename__ = 'alert_photo_files'

    id = db.Column(db.Integer, primary_key=True)
    alert_id = db.Column(db.Integer, db.ForeignKey('alerts.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    is_primary = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=now_comoros)

    def to_dict(self):
        return {
            'id': self.id,
            'photo_url': _cloud_url(self.filename, 'alert_photos'),
            'is_primary': self.is_primary,
        }


@event.listens_for(AlertPhoto, 'before_delete')
def _alert_photo_delete_file(mapper, connection, target):
    _delete_upload_file(target.filename, 'alert_photos')


class LicenseDossier(db.Model):
    """Dossier de demande de permis de conduire — workflow en 5 étapes.
    Le permis est créé dans DriverLicense uniquement quand toutes les étapes sont validées."""
    __tablename__ = 'license_dossiers'
    id               = db.Column(db.Integer, primary_key=True)
    dossier_number   = db.Column(db.String(30), unique=True, nullable=True, index=True)

    # Informations du candidat (saisies à l'étape 2)
    nom                    = db.Column(db.String(150), nullable=True)
    prenom                 = db.Column(db.String(100), nullable=True)
    date_naissance         = db.Column(db.Date, nullable=True)
    lieu_naissance         = db.Column(db.String(150), nullable=True)
    sexe                   = db.Column(db.String(10), nullable=True)
    nationalite            = db.Column(db.String(100), nullable=True)
    holder_address         = db.Column(db.String(255), nullable=True)
    telephone              = db.Column(db.String(30), nullable=True)
    country                = db.Column(db.String(50), nullable=True)
    # Détails du permis (étape 2)
    license_number_proposed = db.Column(db.String(50), nullable=True)
    type_permis            = db.Column(db.String(20), nullable=True)
    issue_date             = db.Column(db.Date, nullable=True)
    expiry_date            = db.Column(db.Date, nullable=True)
    centre_immatriculation = db.Column(db.String(150), nullable=True)
    categories             = db.Column(db.String(100), nullable=True)
    category_details       = db.Column(db.Text, nullable=True)

    # Étape 1 — Validation des documents
    doc_autoecole          = db.Column(db.Boolean, nullable=False, default=False)
    doc_medical            = db.Column(db.Boolean, nullable=False, default=False)
    doc_residence          = db.Column(db.Boolean, nullable=False, default=False)
    doc_fiche_individuelle = db.Column(db.Boolean, nullable=False, default=False)
    doc_carte_nationale    = db.Column(db.Boolean, nullable=False, default=False)
    doc_recu_paiement      = db.Column(db.Boolean, nullable=False, default=False)
    step1_validated_at     = db.Column(db.DateTime, nullable=True)
    step1_validated_by     = db.Column(db.String(100), nullable=True)

    # Step 3 — Photo du candidat
    photo_filename         = db.Column(db.String(255), nullable=True)
    # Step 4 — Statut final du permis à créer
    final_status           = db.Column(db.String(20), nullable=True, default='actif')

    # Étapes 2–5 — données JSON + validation
    step2_data         = db.Column(db.Text, nullable=True)
    step2_validated_at = db.Column(db.DateTime, nullable=True)
    step2_validated_by = db.Column(db.String(100), nullable=True)

    step3_data         = db.Column(db.Text, nullable=True)
    step3_validated_at = db.Column(db.DateTime, nullable=True)
    step3_validated_by = db.Column(db.String(100), nullable=True)

    step4_data         = db.Column(db.Text, nullable=True)
    step4_validated_at = db.Column(db.DateTime, nullable=True)
    step4_validated_by = db.Column(db.String(100), nullable=True)

    step5_data         = db.Column(db.Text, nullable=True)
    step5_validated_at = db.Column(db.DateTime, nullable=True)
    step5_validated_by = db.Column(db.String(100), nullable=True)

    step6_data         = db.Column(db.Text, nullable=True)
    step6_validated_at = db.Column(db.DateTime, nullable=True)
    step6_validated_by = db.Column(db.String(100), nullable=True)

    # État du workflow
    current_step = db.Column(db.Integer, nullable=False, default=0)
    status       = db.Column(db.String(20), nullable=False, default='en_cours')  # en_cours | complet | rejete

    # Rejet
    rejected_at     = db.Column(db.DateTime, nullable=True)
    rejected_by     = db.Column(db.String(100), nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)

    # Permis créé en fin de chaîne (step 5)
    license_id = db.Column(db.Integer, db.ForeignKey('driver_licenses.id'), nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=now_comoros)
    created_by = db.Column(db.String(100), nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=now_comoros, onupdate=now_comoros)

    license = db.relationship('DriverLicense', foreign_keys=[license_id])

    @property
    def all_docs_checked(self):
        return all([self.doc_autoecole, self.doc_medical, self.doc_residence,
                    self.doc_fiche_individuelle, self.doc_carte_nationale,
                    self.doc_recu_paiement])

    def _ui_current_step(self):
        # Ordre UI : step1 → step3(photo) → step2(info) → step4(vérif) → step5(signature DG) → step6(impression)
        if self.step5_validated_at:
            return 6  # signature DG faite → en attente impression (ou déjà complet)
        if self.step4_validated_at:
            return 5  # vérification faite → en attente signature DG
        if self.step2_validated_at:
            return 4
        if self.step3_validated_at:
            return 3
        if self.step1_validated_at:
            return 2
        return 1

    def to_dict(self):
        return {
            'id': self.id,
            'dossier_number': self.dossier_number or '',
            'nom': self.nom or '',
            'prenom': self.prenom or '',
            'date_naissance': self.date_naissance.strftime('%Y-%m-%d') if self.date_naissance else '',
            'lieu_naissance': self.lieu_naissance or '',
            'sexe': self.sexe or '',
            'nationalite': self.nationalite or '',
            'holder_address': self.holder_address or '',
            'telephone': self.telephone or '',
            'country': self.country or '',
            'license_number_proposed': self.license_number_proposed or '',
            'type_permis': self.type_permis or '',
            'issue_date': self.issue_date.strftime('%Y-%m-%d') if self.issue_date else '',
            'expiry_date': self.expiry_date.strftime('%Y-%m-%d') if self.expiry_date else '',
            'centre_immatriculation': self.centre_immatriculation or '',
            'categories': self.categories or '',
            'category_details': json.loads(self.category_details) if self.category_details else {},
            'photo_filename': self.photo_filename or '',
            'photo_url': _cloud_url(self.photo_filename, 'license_photos') or '',
            'final_status': self.final_status or 'actif',
            'doc_autoecole': self.doc_autoecole,
            'doc_medical': self.doc_medical,
            'doc_residence': self.doc_residence,
            'doc_fiche_individuelle': self.doc_fiche_individuelle,
            'doc_carte_nationale': self.doc_carte_nationale,
            'doc_recu_paiement': self.doc_recu_paiement,
            'step1_validated_at': self.step1_validated_at.strftime('%d/%m/%Y %H:%M') if self.step1_validated_at else '',
            'step1_validated_by': self.step1_validated_by or '',
            'step2_validated_at': self.step2_validated_at.strftime('%d/%m/%Y %H:%M') if self.step2_validated_at else '',
            'step2_validated_by': self.step2_validated_by or '',
            'step3_validated_at': self.step3_validated_at.strftime('%d/%m/%Y %H:%M') if self.step3_validated_at else '',
            'step3_validated_by': self.step3_validated_by or '',
            'step4_validated_at': self.step4_validated_at.strftime('%d/%m/%Y %H:%M') if self.step4_validated_at else '',
            'step4_validated_by': self.step4_validated_by or '',
            'step5_validated_at': self.step5_validated_at.strftime('%d/%m/%Y %H:%M') if self.step5_validated_at else '',
            'step5_validated_by': self.step5_validated_by or '',
            'step6_validated_at': self.step6_validated_at.strftime('%d/%m/%Y %H:%M') if self.step6_validated_at else '',
            'step6_validated_by': self.step6_validated_by or '',
            'completed_at': (self.step6_validated_at or self.step5_validated_at).strftime('%d/%m/%Y %H:%M') if (self.step6_validated_at or self.step5_validated_at) else '',
            'completed_by': self.step6_validated_by or self.step5_validated_by or '',
            'current_step': self._ui_current_step(),
            'all_docs_checked': self.all_docs_checked,
            'status': self.status,
            'rejected_at': self.rejected_at.strftime('%d/%m/%Y %H:%M') if self.rejected_at else '',
            'rejected_by': self.rejected_by or '',
            'rejection_reason': self.rejection_reason or '',
            'license_id': self.license_id,
            'created_at': self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else '',
            'created_by': self.created_by or '',
            'updated_at': self.updated_at.strftime('%d/%m/%Y %H:%M') if self.updated_at else '',
        }


class CarteGrise(db.Model):
    __tablename__ = 'carte_grise'

    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), unique=True, nullable=False)

    civilite               = db.Column(db.String(10))
    carrosserie            = db.Column(db.String(100))
    places_assises         = db.Column(db.String(20))
    poids_total_autorise   = db.Column(db.String(50))
    poids_a_vide           = db.Column(db.String(50))
    charge_utile_ptc       = db.Column(db.String(50))
    profession_proprietaire = db.Column(db.String(150))
    observation            = db.Column(db.Text)
    date_emission          = db.Column(db.Date)
    prix                   = db.Column(db.Float)

    # Workflow: brouillon → en_attente → signee
    status                     = db.Column(db.String(30), default='brouillon', nullable=False)
    signature_requested_at     = db.Column(db.DateTime)
    signature_requested_by     = db.Column(db.String(100))
    signed_at                  = db.Column(db.DateTime)
    signed_by                  = db.Column(db.String(100))

    created_at  = db.Column(db.DateTime, default=now_comoros)
    updated_at  = db.Column(db.DateTime, default=now_comoros, onupdate=now_comoros)
    created_by  = db.Column(db.String(100))

    vehicle = db.relationship('Vehicle', backref=db.backref('carte_grise', uselist=False))

    def to_dict(self):
        return {
            'id': self.id,
            'vehicle_id': self.vehicle_id,
            'civilite': self.civilite or '',
            'carrosserie': self.carrosserie or '',
            'places_assises': self.places_assises or '',
            'poids_total_autorise': self.poids_total_autorise or '',
            'poids_a_vide': self.poids_a_vide or '',
            'charge_utile_ptc': self.charge_utile_ptc or '',
            'profession_proprietaire': self.profession_proprietaire or '',
            'observation': self.observation or '',
            'date_emission': self.date_emission.strftime('%Y-%m-%d') if self.date_emission else '',
            'prix': self.prix if self.prix is not None else '',
            'status': self.status or 'brouillon',
            'signature_requested_at': self.signature_requested_at.strftime('%d/%m/%Y %H:%M') if self.signature_requested_at else '',
            'signature_requested_by': self.signature_requested_by or '',
            'signed_at': self.signed_at.strftime('%d/%m/%Y %H:%M') if self.signed_at else '',
            'signed_by': self.signed_by or '',
            'created_at': self.created_at.strftime('%d/%m/%Y %H:%M') if self.created_at else '',
            'created_by': self.created_by or '',
            'updated_at': self.updated_at.strftime('%d/%m/%Y %H:%M') if self.updated_at else '',
        }




class CarteGriseSetting(db.Model):
    __tablename__ = 'carte_grise_setting'
    id                    = db.Column(db.Integer, primary_key=True)
    island                = db.Column(db.String(50), nullable=False, default='Grande Comore')
    directeur_nom         = db.Column(db.String(200))
    signature_filename    = db.Column(db.String(255))
    duree_validite        = db.Column(db.Integer, default=90)
    footer_telephone      = db.Column(db.String(100))
    footer_adresse        = db.Column(db.String(200))

    @property
    def signature_url(self):
        return _cloud_url(self.signature_filename, 'signatures') or ''

    @classmethod
    def get(cls, island='Grande Comore'):
        obj = cls.query.filter_by(island=island).first()
        if obj is None:
            obj = cls(island=island, duree_validite=90)
            db.session.add(obj)
            db.session.commit()
        return obj
