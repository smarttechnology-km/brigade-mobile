from flask import Flask, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from flask_migrate import Migrate
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import text
import os
import logging

logger = logging.getLogger(__name__)

db = SQLAlchemy()
login_manager = LoginManager()
scheduler = BackgroundScheduler()

def create_app():
    app = Flask(__name__)

    # Configuration
    basedir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    db_path = os.path.join(basedir, 'police.db')
    database_url = os.environ.get('DATABASE_URL', f'sqlite:///{db_path}')
    # Render fournit parfois "postgres://" (ancien format) — SQLAlchemy veut "postgresql://"
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_recycle': 280,
    }
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    # JWT configuration (used by mobile app)
    app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'dev-jwt-secret-change')

    # Initialiser la base de données
    db.init_app(app)
    
    # Initialiser Flask-Migrate
    migrate = Migrate(app, db)

    # Initialiser Flask-Login
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    # Enregistrer les blueprints
    from app.routes import main_bp, vehicle_bp
    from app.api import api_bp
    from app.auth import auth_bp
    from app.citizen_auth import citizen_auth_bp
    from app.mobile_pay import mobile_pay_bp
    from app.smart_tech import smart_tech_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(vehicle_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(citizen_auth_bp)
    app.register_blueprint(mobile_pay_bp)
    app.register_blueprint(smart_tech_bp)

    # Enable CORS for API endpoints during development (restrict in production)
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Initialize JWT
    jwt = JWTManager()
    jwt.init_app(app)

    @jwt.token_in_blocklist_loader
    def is_token_revoked(jwt_header, jwt_payload):
        """Revoke tokens whose session_version no longer matches the user record.
        Mobile tokens are validated against the VehicleOwner session_version so a
        new login on another phone invalidates the previous one."""
        try:
            # Check if this is a mobile/citizen token.
            # Can be in jwt_payload directly or inside 'sub'
            vehicle_id = jwt_payload.get('vehicle_id')
            if not vehicle_id and isinstance(jwt_payload.get('sub'), dict):
                vehicle_id = jwt_payload.get('sub', {}).get('vehicle_id')
            
            if vehicle_id:
                from app.models import VehicleOwner

                owner = VehicleOwner.query.filter_by(vehicle_id=int(vehicle_id)).first()
                if not owner or not owner.is_verified:
                    print(f"⚠️  Mobile token rejected: owner missing or unverified for vehicle_id={vehicle_id}")
                    return True

                token_session_version = jwt_payload.get('session_version')
                token_device_id = jwt_payload.get('device_id')
                if token_session_version is None:
                    print(f"⚠️  No session_version in mobile token for vehicle_id={vehicle_id}")
                    return True

                # Only enforce device_id when the owner has one stored.
                # Owners created before OTP login have device_id=None — don't reject their tokens.
                if owner.current_device_id:
                    if not token_device_id or str(owner.current_device_id) != str(token_device_id):
                        print(f"⚠️  Mobile device mismatch for vehicle_id={vehicle_id}")
                        return True

                result = int(token_session_version) != int(getattr(owner, 'session_version', 0))
                if result:
                    print(f"⚠️  Mobile session version mismatch for vehicle_id={vehicle_id}")
                return result
            
            # This is a web/user token
            uid = jwt_payload.get('sub')
            
            # If 'sub' is a dict (old format), extract uid from it
            if isinstance(uid, dict):
                uid = uid.get('id') or uid.get('user_id')
            
            if not uid:
                print(f"⚠️  No uid or vehicle_id in token")
                return True

            from app.models import User
            user = User.query.get(int(uid))
            if not user or not user.is_active:
                print(f"⚠️  User not found or inactive for uid={uid}")
                return True

            token_session_version = jwt_payload.get('session_version')
            if token_session_version is None:
                # Old tokens without session_version are considered invalid.
                print(f"⚠️  No session_version in token for uid={uid}")
                return True

            result = int(token_session_version) != int(getattr(user, 'session_version', 0))
            if result:
                print(f"⚠️  Session version mismatch for uid={uid}")
            return result
        except Exception as e:
            print(f"❌ JWT revocation check failed: {e}")
            import traceback
            traceback.print_exc()
            return True

    @jwt.revoked_token_loader
    def revoked_token_callback(jwt_header, jwt_payload):
        return jsonify({'error': 'Session expired. Please login again.'}), 401

    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        return jsonify({'error': 'Session expired. Please login again.'}), 401

    @jwt.invalid_token_loader
    def invalid_token_callback(reason):
        print(f"❌ JWT Invalid token: {reason}")
        return jsonify({'error': 'Invalid token'}), 401

    @jwt.unauthorized_loader
    def missing_token_callback(reason):
        print(f"❌ JWT Missing token: {reason}")
        return jsonify({'error': 'Missing token'}), 401

    # Error handlers
    @app.errorhandler(403)
    def forbidden(error):
        from flask import render_template
        return render_template('unauthorized.html'), 403

    @app.errorhandler(401)
    def unauthorized(error):
        from flask import render_template
        return render_template('unauthorized.html'), 401

    # Skip scheduler initialization during Flask CLI invocations (e.g. flask db)
    # to avoid side effects while migration commands load the app multiple times.
    if not os.environ.get('FLASK_RUN_FROM_CLI'):
        # Initialize scheduler only once.
        if not scheduler.running:
            scheduler.start()

        # Set app instance for background tasks
        from app.tasks import set_app as tasks_set_app
        tasks_set_app(app)

        # Add the exoneration task to run every hour
        from app.tasks import process_exonerated_fines, regenerate_phone_qr_codes, check_vehicle_qr_code_expiry, send_expiry_notifications
        scheduler.add_job(
            func=process_exonerated_fines,
            trigger=IntervalTrigger(hours=1),
            id='process_exonerated_fines',
            name='Process exonerated fines after 24 hours',
            replace_existing=True
        )

        # Add the phone QR code regeneration task to run daily at 01:00 AM
        scheduler.add_job(
            func=regenerate_phone_qr_codes,
            trigger=CronTrigger(hour=1, minute=0),
            id='regenerate_phone_qr_codes',
            name='Regenerate phone QR codes daily at 01:00 AM',
            replace_existing=True
        )

        # Add the vehicle QR code expiry check task to run daily at 02:00 AM
        scheduler.add_job(
            func=check_vehicle_qr_code_expiry,
            trigger=CronTrigger(hour=2, minute=0),
            id='check_vehicle_qr_code_expiry',
            name='Check vehicle QR code expiry and mark as inactive daily at 02:00 AM',
            replace_existing=True
        )

        # Send push notifications for vignette/insurance expiry daily at 08:00 AM
        scheduler.add_job(
            func=send_expiry_notifications,
            trigger=CronTrigger(hour=8, minute=0),
            id='send_expiry_notifications',
            name='Send vignette and insurance expiry push notifications daily at 08:00 AM',
            replace_existing=True
        )

    # Créer les tables et s'assurer que l'admin existe
    with app.app_context():
        db.create_all()

        # SQLite compatibility guard:
        # `create_all()` does not alter existing tables, so older databases may
        # miss newly added columns (e.g. users.session_version).
        try:
            if str(app.config.get('SQLALCHEMY_DATABASE_URI', '')).startswith('sqlite'):
                with db.engine.begin() as conn:
                    users_table_exists = conn.execute(
                        text("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
                    ).first() is not None

                    if users_table_exists:
                        existing_columns = {
                            row[1] for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()
                        }
                        if 'session_version' not in existing_columns:
                            conn.execute(
                                text("ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0")
                            )
                            logger.info("Added missing users.session_version column for SQLite compatibility")

                    vehicle_owners_table_exists = conn.execute(
                        text("SELECT name FROM sqlite_master WHERE type='table' AND name='vehicle_owners'")
                    ).first() is not None

                    if vehicle_owners_table_exists:
                        vehicle_owner_columns = {
                            row[1] for row in conn.execute(text("PRAGMA table_info(vehicle_owners)")).fetchall()
                        }
                        if 'session_version' not in vehicle_owner_columns:
                            conn.execute(
                                text("ALTER TABLE vehicle_owners ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0")
                            )
                            logger.info("Added missing vehicle_owners.session_version column for SQLite compatibility")
                        if 'current_device_id' not in vehicle_owner_columns:
                            conn.execute(
                                text("ALTER TABLE vehicle_owners ADD COLUMN current_device_id VARCHAR(128)")
                            )
                            logger.info("Added missing vehicle_owners.current_device_id column for SQLite compatibility")
                        if 'expo_push_token' not in vehicle_owner_columns:
                            conn.execute(
                                text("ALTER TABLE vehicle_owners ADD COLUMN expo_push_token VARCHAR(255)")
                            )
                            logger.info("Added missing vehicle_owners.expo_push_token column for SQLite compatibility")

                    vehicles_table_exists = conn.execute(
                        text("SELECT name FROM sqlite_master WHERE type='table' AND name='vehicles'")
                    ).first() is not None

                    if vehicles_table_exists:
                        vehicle_columns = {
                            row[1] for row in conn.execute(text("PRAGMA table_info(vehicles)" )).fetchall()
                        }
                        vehicle_column_definitions = {
                            'vignette_payment_approved': "ALTER TABLE vehicles ADD COLUMN vignette_payment_approved BOOLEAN NOT NULL DEFAULT 0",
                            'vignette_payment_approved_at': "ALTER TABLE vehicles ADD COLUMN vignette_payment_approved_at DATETIME",
                            'vignette_payment_approved_by': "ALTER TABLE vehicles ADD COLUMN vignette_payment_approved_by VARCHAR(80)",
                            'vignette_payment_method': "ALTER TABLE vehicles ADD COLUMN vignette_payment_method VARCHAR(50)",
                            'vignette_payment_requested_at': "ALTER TABLE vehicles ADD COLUMN vignette_payment_requested_at DATETIME",
                            'vignette_payment_requested_by': "ALTER TABLE vehicles ADD COLUMN vignette_payment_requested_by VARCHAR(80)",
                            'vignette_payment_requested_expiry': "ALTER TABLE vehicles ADD COLUMN vignette_payment_requested_expiry DATETIME",
                            'vignette_last_paid_at': "ALTER TABLE vehicles ADD COLUMN vignette_last_paid_at DATETIME",
                            'vignette_last_paid_by': "ALTER TABLE vehicles ADD COLUMN vignette_last_paid_by VARCHAR(150)",
                            'vignette_last_paid_vignette_amount': "ALTER TABLE vehicles ADD COLUMN vignette_last_paid_vignette_amount FLOAT NOT NULL DEFAULT 0.0",
                            'vignette_last_paid_penalty_amount': "ALTER TABLE vehicles ADD COLUMN vignette_last_paid_penalty_amount FLOAT NOT NULL DEFAULT 0.0",
                            'vignette_last_paid_fines_amount': "ALTER TABLE vehicles ADD COLUMN vignette_last_paid_fines_amount FLOAT NOT NULL DEFAULT 0.0",
                            'vignette_last_paid_total_amount': "ALTER TABLE vehicles ADD COLUMN vignette_last_paid_total_amount FLOAT NOT NULL DEFAULT 0.0",
                            'created_by': "ALTER TABLE vehicles ADD COLUMN created_by VARCHAR(80)",
                            'qr_renewed_by': "ALTER TABLE vehicles ADD COLUMN qr_renewed_by VARCHAR(80)",
                        }
                        for column_name, alter_sql in vehicle_column_definitions.items():
                            if column_name not in vehicle_columns:
                                conn.execute(text(alter_sql))
                                logger.info(f"Added missing vehicles.{column_name} column for SQLite compatibility")
                    st_subs_exists = conn.execute(
                        text("SELECT name FROM sqlite_master WHERE type='table' AND name='st_subscriptions'")
                    ).first() is not None
                    if st_subs_exists:
                        sub_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(st_subscriptions)")).fetchall()}
                        st_sub_col_defs = {
                            'payment_mode': "ALTER TABLE st_subscriptions ADD COLUMN payment_mode VARCHAR(20) NOT NULL DEFAULT 'manuel'",
                            'last_paid_at': "ALTER TABLE st_subscriptions ADD COLUMN last_paid_at DATETIME",
                            'last_paid_by': "ALTER TABLE st_subscriptions ADD COLUMN last_paid_by VARCHAR(80)",
                            'phone_id':     "ALTER TABLE st_subscriptions ADD COLUMN phone_id INTEGER",
                            'start_date':   "ALTER TABLE st_subscriptions ADD COLUMN start_date DATE",
                            'employee_id':  "ALTER TABLE st_subscriptions ADD COLUMN employee_id INTEGER REFERENCES st_employees(id)",
                        }
                        for col, sql in st_sub_col_defs.items():
                            if col not in sub_cols:
                                conn.execute(text(sql))
                                logger.info(f"Added missing st_subscriptions.{col} column")

                    st_exp_exists = conn.execute(
                        text("SELECT name FROM sqlite_master WHERE type='table' AND name='st_expenses'")
                    ).first() is not None
                    if not st_exp_exists:
                        conn.execute(text(
                            "CREATE TABLE IF NOT EXISTS st_expenses ("
                            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                            "description VARCHAR(200) NOT NULL,"
                            "category VARCHAR(80) NOT NULL,"
                            "amount FLOAT NOT NULL DEFAULT 0.0,"
                            "expense_date DATE NOT NULL,"
                            "vendor VARCHAR(120),"
                            "notes TEXT,"
                            "created_at DATETIME NOT NULL,"
                            "created_by VARCHAR(80)"
                            ")"
                        ))
                        logger.info("Created st_expenses table")

                    st_accts_exists = conn.execute(
                        text("SELECT name FROM sqlite_master WHERE type='table' AND name='smart_tech_accounts'")
                    ).first() is not None
                    if st_accts_exists:
                        acct_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(smart_tech_accounts)")).fetchall()}
                        if 'employee_id' not in acct_cols:
                            conn.execute(text("ALTER TABLE smart_tech_accounts ADD COLUMN employee_id INTEGER REFERENCES st_employees(id)"))
                            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_smart_tech_accounts_employee_id ON smart_tech_accounts(employee_id) WHERE employee_id IS NOT NULL"))
                            logger.info("Added missing smart_tech_accounts.employee_id column")
                        if 'role' not in acct_cols:
                            conn.execute(text("ALTER TABLE smart_tech_accounts ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'admin'"))
                            logger.info("Added missing smart_tech_accounts.role column")

                    st_emp_exists = conn.execute(
                        text("SELECT name FROM sqlite_master WHERE type='table' AND name='st_employees'")
                    ).first() is not None
                    if not st_emp_exists:
                        conn.execute(text(
                            "CREATE TABLE IF NOT EXISTS st_employees ("
                            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                            "first_name VARCHAR(80) NOT NULL,"
                            "last_name VARCHAR(80) NOT NULL,"
                            "phone VARCHAR(30),"
                            "email VARCHAR(120),"
                            "island VARCHAR(50),"
                            "position VARCHAR(100) NOT NULL,"
                            "salary FLOAT NOT NULL DEFAULT 0.0,"
                            "hire_date DATE,"
                            "status VARCHAR(20) NOT NULL DEFAULT 'actif',"
                            "notes TEXT,"
                            "created_at DATETIME NOT NULL,"
                            "created_by VARCHAR(80)"
                            ")"
                        ))
                        logger.info("Created st_employees table")

        except Exception as e:
            logger.warning(f"Could not auto-fix SQLite schema: {e}")
        
        # Initialize QR codes for all phones that don't have one
        from app.models import Phone, User
        try:
            phones_without_qr = Phone.query.filter(
                (Phone.qr_code_data == None) | (Phone.qr_code_data == '')
            ).all()
            
            for phone in phones_without_qr:
                phone.generate_qr_code()
                logger.info(f"Generated initial QR code for phone {phone.phone_code}")
            
            if phones_without_qr:
                db.session.commit()
                logger.info(f"Initialized QR codes for {len(phones_without_qr)} phones")
        except Exception as e:
            logger.warning(f"Could not initialize QR codes (DB columns might not exist yet): {str(e)}")
            db.session.rollback()
        
        # S'assurer que l'utilisateur admin existe toujours
        admin_username = 'admin'
        admin_password = 'admin123'

        admin = User.query.filter_by(username=admin_username).first()
        if not admin:
            admin = User(username=admin_username, is_admin=True, role='administrateur')
            admin.set_password(admin_password)
            db.session.add(admin)
            db.session.commit()
            print(f"✓ Admin créé automatiquement: {admin_username}")
        elif not admin.is_admin or admin.role != 'administrateur':
            admin.is_admin = True
            admin.role = 'administrateur'
            db.session.commit()
            print(f"✓ Droits admin restaurés: {admin_username}")

        # Supprimer le compte système smarttech s'il existe encore
        from app.models import SmartTechAccount
        st_account = SmartTechAccount.query.filter_by(username='smarttech').first()
        if st_account:
            db.session.delete(st_account)
            db.session.commit()
            print("✓ Compte système smarttech supprimé")

        # Initialiser les paramètres par défaut Smart Technology
        from app.models import SmartTechSetting
        for key, default_val in [('qr_activation_price', '5000'), ('qr_renewal_price', '3000')]:
            if not SmartTechSetting.query.filter_by(key=key).first():
                db.session.add(SmartTechSetting(key=key, value=default_val))
        db.session.commit()

        # Backfill QRCodePayment pour véhicules existants sans enregistrement
        try:
            from app.models import QRCodePayment, VehicleHistory, Vehicle
            from app.timezone_utils import now_comoros as _now
            act_price = SmartTechSetting.get('qr_activation_price', 5000)
            ren_price = SmartTechSetting.get('qr_renewal_price', 3000)

            vehicles_with_qr = Vehicle.query.filter(Vehicle.qr_code_expiry.isnot(None)).all()
            for v in vehicles_with_qr:
                # Activation : une seule fois par véhicule
                if not QRCodePayment.query.filter_by(vehicle_id=v.id, payment_type='activation', status='paid').first():
                    db.session.add(QRCodePayment(
                        vehicle_id=v.id,
                        payment_type='activation',
                        amount=act_price,
                        status='paid',
                        paid_at=v.qr_code_generated_at or v.created_at or _now(),
                        recorded_by=v.created_by or 'system',
                    ))

                # Renouvellements : un enregistrement par entrée d'historique
                renewals = VehicleHistory.query.filter(
                    VehicleHistory.vehicle_id == v.id,
                    VehicleHistory.action.like('%QR Code renouvelé%')
                ).order_by(VehicleHistory.created_at).all()
                for r in renewals:
                    from datetime import timedelta
                    already = QRCodePayment.query.filter(
                        QRCodePayment.vehicle_id == v.id,
                        QRCodePayment.payment_type == 'renewal',
                        QRCodePayment.status == 'paid',
                        QRCodePayment.paid_at >= r.created_at - timedelta(minutes=5),
                        QRCodePayment.paid_at <= r.created_at + timedelta(minutes=5),
                    ).first()
                    if not already:
                        db.session.add(QRCodePayment(
                            vehicle_id=v.id,
                            payment_type='renewal',
                            amount=ren_price,
                            status='paid',
                            paid_at=r.created_at or _now(),
                            recorded_by=r.officer or 'system',
                        ))

            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Warning: QRCodePayment backfill failed: {e}")

    return app
