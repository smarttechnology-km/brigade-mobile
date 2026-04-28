from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User, InsuranceAccount
from app import db, login_manager

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')


@login_manager.user_loader
def load_user(user_id):
    """Load user from ID - supports both User and InsuranceAccount"""
    # New format: "user:<id>" or "insurance:<id>" to avoid table ID collisions.
    if isinstance(user_id, str) and ':' in user_id:
        account_type, raw_id = user_id.split(':', 1)
        if not raw_id.isdigit():
            return None
        account_id = int(raw_id)

        if account_type == 'insurance':
            return InsuranceAccount.query.get(account_id)
        if account_type == 'user':
            return User.query.get(account_id)
        return None

    # Backward compatibility for old sessions that stored only numeric IDs.
    # Prefer regular users first to avoid treating admin/police/judicial as insurance.
    if isinstance(user_id, str) and user_id.isdigit():
        account_id = int(user_id)
        user = User.query.get(account_id)
        if user:
            return user
        return InsuranceAccount.query.get(account_id)

    return None


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        # Redirect to appropriate dashboard based on user type
        if isinstance(current_user, InsuranceAccount):
            return redirect(url_for('main.insurance_dashboard'))
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Try to authenticate as insurance account FIRST
        insurance_account = InsuranceAccount.query.filter_by(username=username).first()
        if insurance_account and insurance_account.is_active and insurance_account.check_password(password):
            login_user(insurance_account)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('main.insurance_dashboard'))
        
        # Then try as regular user
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            
            # Log user login
            try:
                from app.models import UserHistory
                from app.timezone_utils import now_comoros
                history = UserHistory(
                    user_id=user.id,
                    action='Connexion',
                    details='Connexion réussie à l\'application'
                )
                db.session.add(history)
                db.session.commit()
            except Exception as e:
                print(f'Error logging user login: {e}')
            
            next_page = request.args.get('next')
            return redirect(next_page or url_for('main.index'))
        
        flash('Nom d\'utilisateur ou mot de passe incorrect', 'danger')

    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    # Log user logout before ending the session so the actor is still available
    try:
        from app.models import UserHistory
        history = UserHistory(
            user_id=current_user.id,
            action='Déconnexion',
            details='Déconnexion de l\'application'
        )
        db.session.add(history)
        db.session.commit()
    except Exception as e:
        print(f'Error logging user logout: {e}')

    logout_user()
    flash('Vous êtes déconnecté', 'success')
    return redirect(url_for('auth.login'))
