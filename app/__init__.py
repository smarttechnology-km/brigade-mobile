from flask import Flask
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
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = 'dev-secret-key-change-in-production'
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
    from app.mobile_pay import mobile_pay_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(vehicle_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(mobile_pay_bp)

    # Enable CORS for API endpoints during development (restrict in production)
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Initialize JWT
    jwt = JWTManager()
    jwt.init_app(app)

    # Error handlers
    @app.errorhandler(403)
    def forbidden(error):
        from flask import render_template
        return render_template('unauthorized.html'), 403

    @app.errorhandler(401)
    def unauthorized(error):
        from flask import render_template
        return render_template('unauthorized.html'), 401

    # Initialize scheduler
    scheduler.start()

    # Set app instance for background tasks
    from app.tasks import set_app as tasks_set_app
    tasks_set_app(app)

    # Add the exoneration task to run every hour
    from app.tasks import process_exonerated_fines, regenerate_phone_qr_codes, check_vehicle_qr_code_expiry
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

    return app
