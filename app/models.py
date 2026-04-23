from app import db
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
import uuid
from app.timezone_utils import now_comoros


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
    is_active = db.Column(db.Boolean, nullable=False, default=True)
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


class Vehicle(db.Model):
    __tablename__ = 'vehicles'
    
    id = db.Column(db.Integer, primary_key=True)
    license_plate = db.Column(db.String(20), unique=True, nullable=False)
    owner_name = db.Column(db.String(100), nullable=False)
    owner_phone = db.Column(db.String(15))
    owner_island = db.Column(db.String(50))  # Grande Comores, Anjouan, Moheli
    vehicle_type = db.Column(db.String(50), nullable=False)  # voiture, moto, camion, etc.
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
    qr_code_generated_at = db.Column(db.DateTime, nullable=True)  # When QR code was generated
    qr_code_expiry = db.Column(db.DateTime, nullable=True)  # When QR code expires (2 years after generation)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=now_comoros)
    updated_at = db.Column(db.DateTime, nullable=False, default=now_comoros, onupdate=now_comoros)
    
    def __repr__(self):
        return f'<Vehicle {self.license_plate}>'
    
    def generate_qr_code_with_expiry(self):
        """
        Generate a new QR code token for this vehicle with 2-year expiry.
        Expiry date = Today + 2 years (730 days)
        Also generates a new unique track_token for security.
        """
        from app.timezone_utils import now_comoros
        from datetime import timedelta
        
        # Use current date/time as generation date
        current_time = now_comoros()
        self.qr_code_generated_at = current_time
        
        # Set expiry to 2 years (730 days) from today
        TWO_YEARS_IN_DAYS = 730
        self.qr_code_expiry = current_time + timedelta(days=TWO_YEARS_IN_DAYS)
        
        # Generate a new unique track_token for security
        self.track_token = str(uuid.uuid4())
        
        return self.qr_code_expiry
    
    def is_qr_code_expired(self):
        """Check if the QR code has expired"""
        if not self.qr_code_expiry:
            return False
        from app.timezone_utils import now_comoros
        return now_comoros() > self.qr_code_expiry
    
    def to_dict(self):
        return {
            'id': self.id,
            'license_plate': self.license_plate,
            'owner_name': self.owner_name,
            'owner_phone': self.owner_phone,
            'owner_island': self.owner_island,
            'owner_address': self.owner_address,
            'vehicle_type': self.vehicle_type,
            'usage_type': self.usage_type,
            'status': self.status,
            'make': self.make,
            'model': self.model,
            'year': self.year,
            'color': self.color,
            'vin': self.vin,
            'registration_expiry': self.registration_expiry.strftime('%Y-%m-%d') if self.registration_expiry else None,
            'insurance_company': self.insurance_company,
            'insurance_expiry': self.insurance_expiry.strftime('%Y-%m-%d') if self.insurance_expiry else None,
            'vignette_expiry': self.vignette_expiry.strftime('%Y-%m-%d') if self.vignette_expiry else None,
            'qr_code_generated_at': self.qr_code_generated_at.strftime('%Y-%m-%d') if self.qr_code_generated_at else None,
            'qr_code_expiry': self.qr_code_expiry.strftime('%Y-%m-%d') if self.qr_code_expiry else None,
            'track_token': self.track_token,
            'registration_date': self.registration_date.strftime('%Y-%m-%d'),
            'created_at': self.created_at.strftime('%Y-%m-%d') if self.created_at else None,
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


class Fine(db.Model):
    __tablename__ = 'fines'
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    amount = db.Column(db.Numeric(10,2), nullable=False)
    reason = db.Column(db.String(255), nullable=False)
    officer = db.Column(db.String(100))
    paid = db.Column(db.Boolean, default=False)
    paid_at = db.Column(db.DateTime)
    paid_by = db.Column(db.String(100), nullable=True)
    receipt_number = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text)
    issued_at = db.Column(db.DateTime, nullable=False, default=now_comoros)

    vehicle = db.relationship('Vehicle', backref=db.backref('fines', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'vehicle_id': self.vehicle_id,
            'amount': float(self.amount),
            'reason': self.reason,
            'officer': self.officer,
            'paid': self.paid,
            'paid_at': self.paid_at.isoformat() if self.paid_at else None,
            'paid_at_str': self.paid_at.strftime('%d/%m/%Y %H:%M') if self.paid_at else None,
            'paid_by': self.paid_by,
            'receipt_number': self.receipt_number,
            'notes': self.notes,
            'issued_at': self.issued_at.isoformat(),
            'issued_at_str': self.issued_at.strftime('%d/%m/%Y %H:%M') if self.issued_at else None
        }


class FineType(db.Model):
    __tablename__ = 'fine_types'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=True)
    label = db.Column(db.String(150), nullable=False)
    amount = db.Column(db.Numeric(10,2), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<FineType {self.label} ({self.amount})>'

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'label': self.label,
            'amount': float(self.amount),
            'created_at': self.created_at.isoformat()
        }


class Insurance(db.Model):
    __tablename__ = 'insurances'
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(150), nullable=False, unique=True)
    phone = db.Column(db.String(30), nullable=True)
    island = db.Column(db.String(50), nullable=True)  # Grande Comores, Anjouan, Moheli
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


class VehicleInsuranceAssignment(db.Model):
    """Links vehicles to insurance accounts for management"""
    __tablename__ = 'vehicle_insurance_assignments'
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    insurance_account_id = db.Column(db.Integer, db.ForeignKey('insurance_accounts.id'), nullable=False)
    assigned_at = db.Column(db.DateTime, nullable=False, default=now_comoros)
    assigned_by = db.Column(db.String(100), nullable=True)  # Username who assigned it
    notes = db.Column(db.Text)
    
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
            'notes': self.notes
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
    island = db.Column(db.String(50), nullable=True)  # Grande Comores, Anjouan, Moheli
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
        }