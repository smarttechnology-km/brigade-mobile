from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response
from flask_login import login_user, logout_user, login_required, current_user
from functools import wraps
from app.models import SmartTechAccount, QRCodePayment, Vehicle, Subscription, Expense, Employee, SmartTechSetting, LicensePrintRequest, Insurance, InsuranceAccount, VehicleInsuranceAssignment, HuriDestinationSetting
from app import db

smart_tech_bp = Blueprint('smart_tech', __name__, url_prefix='/smart-tech')


@smart_tech_bp.context_processor
def inject_licences_pending_count():
    try:
        count = _lpr_q().filter(LicensePrintRequest.status == 'pending').count()
    except Exception:
        count = 0
    return {'pending_count': count}


def smart_tech_required(f):
    """Decorator: only SmartTechAccount sessions may access these routes."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, 'is_smart_tech', False):
            return redirect(url_for('smart_tech.login'))
        return f(*args, **kwargs)
    return decorated


def st_admin_required(f):
    """Decorator: SmartTechAccount with role='admin' only."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, 'is_smart_tech', False):
            return redirect(url_for('smart_tech.login'))
        if current_user.role != 'admin':
            return redirect(url_for('smart_tech.dashboard'))
        return f(*args, **kwargs)
    return decorated


def st_no_secretaire_required(f):
    """Decorator: admin or employe only (secretaire is redirected)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, 'is_smart_tech', False):
            return redirect(url_for('smart_tech.login'))
        if current_user.role not in ('admin', 'employe'):
            return redirect(url_for('smart_tech.dashboard'))
        return f(*args, **kwargs)
    return decorated


def st_admin_or_secretaire_required(f):
    """Decorator: admin or secretaire only (employe is redirected)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, 'is_smart_tech', False):
            return redirect(url_for('smart_tech.login'))
        if current_user.role not in ('admin', 'secretaire'):
            return redirect(url_for('smart_tech.dashboard'))
        return f(*args, **kwargs)
    return decorated


def _employe_island():
    """Return the island assigned to the current employe account, or None for admin/secretaire."""
    if getattr(current_user, 'role', None) == 'employe' and current_user.employee:
        return current_user.employee.island or None
    return None


def _vq():
    """Base Vehicle.query filtered to the current employe's island when applicable."""
    island = _employe_island()
    q = Vehicle.query
    if island:
        q = q.filter(Vehicle.owner_island == island)
    return q


def _lpr_q():
    """LicensePrintRequest query filtered by employe island via DriverLicense.holder_island."""
    from app.models import DriverLicense
    island = _employe_island()
    q = LicensePrintRequest.query.join(DriverLicense, LicensePrintRequest.license_id == DriverLicense.id)
    if island:
        q = q.filter(DriverLicense.holder_island == island)
    return q


def _ins_q():
    """Insurance query filtered to the current employe's island when applicable."""
    island = _employe_island()
    q = Insurance.query
    if island:
        q = q.filter(Insurance.island == island)
    return q


@smart_tech_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated and getattr(current_user, 'is_smart_tech', False):
        return redirect(url_for('smart_tech.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        account = SmartTechAccount.query.filter_by(username=username).first()
        if account and account.is_active and account.check_password(password):
            login_user(account)
            return redirect(url_for('smart_tech.dashboard'))

        flash('Nom d\'utilisateur ou mot de passe incorrect.', 'danger')

    return render_template('smart_tech_login.html')


@smart_tech_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('smart_tech.login'))


@smart_tech_bp.route('/parametres')
@st_admin_required
def parametres_page():
    activation_price  = SmartTechSetting.get('qr_activation_price', 5000)
    renewal_price     = SmartTechSetting.get('qr_renewal_price', 3000)
    license_print_price  = SmartTechSetting.get('license_print_price', 0)
    insurance_commission = SmartTechSetting.get('insurance_commission', 0)
    return render_template('smart_tech_parametres.html',
                           activation_price=int(activation_price),
                           renewal_price=int(renewal_price),
                           license_print_price=int(license_print_price),
                           insurance_commission=int(insurance_commission),
                           qr_renewal_destination_phone=HuriDestinationSetting.get().qr_renewal_phone or '',
                           sim_new_vehicles=int(SmartTechSetting.get('sim_new_vehicles', 500)),
                           sim_existing=int(SmartTechSetting.get('sim_existing', 10000)),
                           sim_renewal_rate=float(SmartTechSetting.get('sim_renewal_rate', 10)),
                           sim_rate_growth=float(SmartTechSetting.get('sim_rate_growth', 5)),
                           sim_churn_rate=float(SmartTechSetting.get('sim_churn_rate', 2)),
                           sim_annual_expenses=int(SmartTechSetting.get('sim_annual_expenses', 0)),
                           sim_years=int(SmartTechSetting.get('sim_years', 5)),
                           sim_licenses_per_year=int(SmartTechSetting.get('sim_licenses_per_year', 0)),
                           sim_insurance_rate=float(SmartTechSetting.get('sim_insurance_rate', 0)))


@smart_tech_bp.route('/api/parametres', methods=['GET'])
@st_admin_required
def api_parametres_get():
    return jsonify({
        'qr_activation_price':   SmartTechSetting.get('qr_activation_price', 5000),
        'qr_renewal_price':      SmartTechSetting.get('qr_renewal_price', 3000),
        'license_print_price':   SmartTechSetting.get('license_print_price', 0),
        'insurance_commission':  SmartTechSetting.get('insurance_commission', 0),
        'qr_renewal_destination_phone': HuriDestinationSetting.get().qr_renewal_phone or '',
    })


@smart_tech_bp.route('/api/parametres', methods=['PUT'])
@st_admin_required
def api_parametres_update():
    data = request.get_json(silent=True) or {}
    errors = []
    for key in ('qr_activation_price', 'qr_renewal_price', 'license_print_price', 'insurance_commission'):
        val = data.get(key)
        if val is None:
            continue
        try:
            v = float(val)
            if v < 0:
                raise ValueError
            SmartTechSetting.set(key, v)
        except (ValueError, TypeError):
            errors.append(f"Valeur invalide pour {key}")
    if 'qr_renewal_destination_phone' in data:
        from app.timezone_utils import now_comoros
        setting = HuriDestinationSetting.get()
        setting.qr_renewal_phone = str(data['qr_renewal_destination_phone']).strip() or None
        setting.qr_renewal_phone_updated_at = now_comoros()
        setting.qr_renewal_phone_updated_by = current_user.username if current_user.is_authenticated else None
        db.session.commit()
    _SIM_KEYS = {
        'sim_new_vehicles':      (int,   0,   None),
        'sim_existing':          (int,   0,   None),
        'sim_renewal_rate':      (float, 0,   100),
        'sim_rate_growth':       (float, 0,   50),
        'sim_churn_rate':        (float, 0,   50),
        'sim_annual_expenses':   (int,   0,   None),
        'sim_years':             (int,   1,   20),
        'sim_licenses_per_year': (int,   0,   None),
        'sim_insurance_rate':    (float, 0,   100),
    }
    for key, (cast, mn, mx) in _SIM_KEYS.items():
        if key in data:
            try:
                v = cast(data[key])
                if v < mn or (mx is not None and v > mx):
                    raise ValueError
                SmartTechSetting.set(key, v)
            except (ValueError, TypeError):
                errors.append(f"Valeur invalide pour {key}")
    if errors:
        return jsonify({'error': ' | '.join(errors)}), 400
    return jsonify({
        'ok': True,
        'qr_activation_price': SmartTechSetting.get('qr_activation_price'),
        'qr_renewal_price':    SmartTechSetting.get('qr_renewal_price'),
        'qr_renewal_destination_phone': HuriDestinationSetting.get().qr_renewal_phone or '',
    })


@smart_tech_bp.route('/profil')
@smart_tech_required
def profil():
    return render_template('smart_tech_profil.html')


@smart_tech_bp.route('/api/profil/payment-history')
@smart_tech_required
def api_profil_payment_history():
    subs = (Subscription.query
            .filter(Subscription.last_paid_by == current_user.username,
                    Subscription.last_paid_at != None)
            .order_by(Subscription.last_paid_at.desc())
            .all())
    return jsonify([{
        'id':         s.id,
        'name':       s.name,
        'sub_type':   s.sub_type,
        'amount':     s.amount,
        'frequency':  s.frequency,
        'last_paid_at': s.last_paid_at.strftime('%d/%m/%Y à %H:%M') if s.last_paid_at else None,
    } for s in subs])


@smart_tech_bp.route('/api/profil', methods=['PUT'])
@smart_tech_required
def api_profil_update():
    data       = request.get_json(silent=True) or {}
    first_name = data.get('first_name', '').strip()
    last_name  = data.get('last_name',  '').strip()
    phone      = data.get('phone',  '').strip() or None
    password   = data.get('password', '').strip()
    confirm    = data.get('confirm',  '').strip()
    if password:
        if len(password) < 6:
            return jsonify({'error': 'Le mot de passe doit contenir au moins 6 caractères.'}), 400
        if password != confirm:
            return jsonify({'error': 'Les mots de passe ne correspondent pas.'}), 400
        current_user.set_password(password)
    position = (data.get('position') or '').strip() or None
    island   = data.get('island') or None
    if current_user.employee:
        # Accounts linked to an employee: update employee record + derive full_name
        if first_name:
            current_user.employee.first_name = first_name
        if last_name:
            current_user.employee.last_name = last_name
        current_user.employee.phone = phone  # allows clearing phone
        if current_user.role == 'admin':
            if position:
                current_user.employee.position = position
            current_user.employee.island = island or None
        current_user.full_name = current_user.employee.full_name
    else:
        # System accounts: first_name field holds the full name (single field in UI)
        current_user.full_name = first_name or None
    db.session.commit()
    return jsonify({'ok': True, 'full_name': current_user.full_name or current_user.username})


@smart_tech_bp.route('/dashboard')
@smart_tech_required
def dashboard():
    from app.timezone_utils import now_comoros, ensure_comoros
    from sqlalchemy import func

    now = now_comoros()

    # ── Vehicle QR code stats ──────────────────────────────────────────────────
    total_vehicles = _vq().count()

    # QR actif: qr_code_expiry dans le futur
    qr_active = _vq().filter(
        Vehicle.qr_code_expiry.isnot(None),
        Vehicle.qr_code_expiry > now
    ).count()

    # QR inactif: qr_code_expiry expiré (avaient un QR mais il a expiré)
    qr_inactive = _vq().filter(
        Vehicle.qr_code_expiry.isnot(None),
        Vehicle.qr_code_expiry <= now
    ).count()

    # ── Vehicle QR history for the payments table ─────────────────────────────
    # Include ALL vehicles, sorted by most recent activity:
    #   - vehicles with QR generated → sorted by qr_code_generated_at desc
    #   - vehicles never activated   → sorted by created_at desc (show as Activation pending)
    # Type logic:
    #   - qr_code_generated_at within 3 days of created_at → Activation (new vehicle)
    #   - qr_code_generated_at more than 3 days after      → Renouvellement
    #   - qr_code_generated_at is None                     → Activation (never had QR)
    from sqlalchemy import case, func as sqlfunc
    from app.timezone_utils import ensure_comoros

    all_vehicles = (
        _vq()
        .order_by(
            Vehicle.qr_code_generated_at.desc().nullslast(),
            Vehicle.created_at.desc()
        )
        .limit(20)
        .all()
    )
    vehicle_ids = [v.id for v in all_vehicles]

    # Index manually recorded QRCodePayment entries by vehicle_id
    recorded_payments = {
        p.vehicle_id: p
        for p in QRCodePayment.query.filter_by(status='paid').all()
    }

    # Most recent QR renewal officer per vehicle, from VehicleHistory
    from app.models import VehicleHistory
    renewal_officer = {}
    if vehicle_ids:
        for h in (
            VehicleHistory.query
            .filter(
                VehicleHistory.vehicle_id.in_(vehicle_ids),
                VehicleHistory.action.like('%QR Code renouvelé%')
            )
            .order_by(VehicleHistory.created_at.desc())
            .all()
        ):
            renewal_officer.setdefault(h.vehicle_id, h.officer)

    THREE_DAYS = 3 * 86400  # seconds

    qr_table_rows = []
    for v in all_vehicles:
        recorded = recorded_payments.get(v.id)
        if recorded:
            payment_type = recorded.payment_type
            amount       = recorded.amount
            recorded_by  = recorded.recorded_by
            date         = recorded.paid_at
        else:
            if v.qr_code_generated_at is None:
                payment_type = 'activation'
                date         = v.created_at
            else:
                delta = 0
                if v.created_at:
                    gen = ensure_comoros(v.qr_code_generated_at)
                    cre = ensure_comoros(v.created_at)
                    delta = (gen - cre).total_seconds()
                payment_type = 'activation' if delta < THREE_DAYS else 'renewal'
                date = v.qr_code_generated_at
            amount = None
            if payment_type == 'renewal':
                recorded_by = renewal_officer.get(v.id) or v.qr_renewed_by
            else:
                recorded_by = v.created_by

        qr_table_rows.append({
            'license_plate': v.license_plate,
            'owner_name':    v.owner_name,
            'payment_type':  payment_type,
            'amount':        amount,
            'recorded_by':   recorded_by,
            'date':          date,
        })

    act_price = SmartTechSetting.get('qr_activation_price', 5000)
    ren_price = SmartTechSetting.get('qr_renewal_price', 3000)

    # ── Abonnements : regroupés par type ──────────────────────────────────────
    all_subs = Subscription.query.order_by(Subscription.sub_type, Subscription.name).all()
    subs_by_type = {}
    for s in all_subs:
        subs_by_type.setdefault(s.sub_type, []).append(s)
    sub_types_summary = []
    for stype, items in sorted(subs_by_type.items()):
        active = [i for i in items if i.is_active]
        monthly = sum(i.monthly_cost() for i in active)
        sub_types_summary.append({
            'type':         stype,
            'total':        len(items),
            'active':       len(active),
            'monthly_cost': monthly,
        })

    # ── Dépenses récentes ─────────────────────────────────────────────────────
    from app.timezone_utils import now_comoros as _nc
    _today = _nc().date()
    recent_expenses = (Expense.query
                       .order_by(Expense.expense_date.desc(), Expense.created_at.desc())
                       .limit(5).all())
    expense_month_total = sum(
        e.amount for e in Expense.query.all()
        if e.expense_date and e.expense_date.year == _today.year
        and e.expense_date.month == _today.month
    )

    return render_template(
        'smart_tech_dashboard.html',
        now=now,
        total_vehicles=total_vehicles,
        qr_active=qr_active,
        qr_inactive=qr_inactive,
        qr_table_rows=qr_table_rows,
        activation_price=int(act_price),
        renewal_price=int(ren_price),
        sub_types_summary=sub_types_summary,
        recent_expenses=recent_expenses,
        expense_month_total=expense_month_total,
    )


@smart_tech_bp.route('/qr-payment/record', methods=['POST'])
@smart_tech_required
def record_qr_payment():
    """Record a QR code activation or renewal payment for a vehicle."""
    from app.timezone_utils import now_comoros
    data = request.get_json(silent=True) or {}

    vehicle_id = data.get('vehicle_id')
    payment_type = data.get('payment_type')  # 'activation' or 'renewal'
    amount = float(data.get('amount', 0) or 0)
    if amount == 0:
        if payment_type == 'activation':
            amount = SmartTechSetting.get('qr_activation_price', 5000)
        elif payment_type == 'renewal':
            amount = SmartTechSetting.get('qr_renewal_price', 3000)
    notes = data.get('notes', '')

    if not vehicle_id or payment_type not in ('activation', 'renewal'):
        return jsonify({'error': 'Données invalides.'}), 400

    vehicle = Vehicle.query.get(vehicle_id)
    if not vehicle:
        return jsonify({'error': 'Véhicule introuvable.'}), 404

    now = now_comoros()
    payment = QRCodePayment(
        vehicle_id=vehicle.id,
        payment_type=payment_type,
        amount=amount,
        status='paid',
        paid_at=now,
        recorded_by=current_user.username,
        notes=notes or None,
    )
    db.session.add(payment)
    db.session.commit()

    type_label = 'Activation' if payment_type == 'activation' else 'Renouvellement'
    return jsonify({
        'success': True,
        'message': f'{type_label} QR enregistré pour {vehicle.license_plate}.',
        'payment': payment.to_dict(),
    })


@smart_tech_bp.route('/api/stats')
@smart_tech_required
def api_stats():
    """JSON endpoint for live stats refresh."""
    from app.timezone_utils import now_comoros
    from sqlalchemy import func

    now = now_comoros()
    total = _vq().count()
    active = _vq().filter(
        Vehicle.qr_code_expiry.isnot(None),
        Vehicle.qr_code_expiry > now
    ).count()
    inactive = _vq().filter(
        Vehicle.qr_code_expiry.isnot(None),
        Vehicle.qr_code_expiry <= now
    ).count()
    never = _vq().filter(Vehicle.qr_code_expiry.is_(None)).count()
    island = _employe_island()
    if island:
        island_vehicle_ids = [v.id for v in _vq().with_entities(Vehicle.id).all()]
        revenue = db.session.query(func.sum(QRCodePayment.amount)).filter(
            QRCodePayment.status == 'paid',
            QRCodePayment.vehicle_id.in_(island_vehicle_ids)
        ).scalar() or 0.0
    else:
        revenue = db.session.query(func.sum(QRCodePayment.amount)).filter_by(status='paid').scalar() or 0.0

    return jsonify({
        'total_vehicles': total,
        'qr_active': active,
        'qr_inactive': inactive,
        'qr_never': never,
        'total_revenue': revenue,
    })


def _vehicles_query_filtered(search, type_filter):
    """Return all Vehicle rows matching search, with computed QR type.
    Applies type_filter in Python (type is computed, not a DB column).
    Returns list of row dicts."""
    import math
    from app.timezone_utils import ensure_comoros, now_comoros
    from app.models import VehicleHistory
    _now = now_comoros()

    query = _vq()
    if search:
        term  = f'%{search}%'
        query = query.filter(
            db.or_(
                Vehicle.license_plate.ilike(term),
                Vehicle.owner_name.ilike(term)
            )
        )
    all_vehicles = query.order_by(
        Vehicle.qr_code_generated_at.desc().nullslast(),
        Vehicle.created_at.desc()
    ).all()
    all_ids = [v.id for v in all_vehicles]

    recorded_payments = {}
    if all_ids:
        recorded_payments = {
            p.vehicle_id: p
            for p in QRCodePayment.query.filter(
                QRCodePayment.vehicle_id.in_(all_ids),
                QRCodePayment.status == 'paid'
            ).all()
        }

    renewal_officer = {}
    if all_ids:
        for h in (
            VehicleHistory.query
            .filter(
                VehicleHistory.vehicle_id.in_(all_ids),
                VehicleHistory.action.like('%QR Code renouvelé%')
            )
            .order_by(VehicleHistory.created_at.desc())
            .all()
        ):
            renewal_officer.setdefault(h.vehicle_id, h.officer)

    THREE_DAYS = 3 * 86400
    rows = []
    for v in all_vehicles:
        recorded = recorded_payments.get(v.id)
        if recorded:
            payment_type = recorded.payment_type
            amount       = recorded.amount
            recorded_by  = recorded.recorded_by
            date         = recorded.paid_at
        else:
            if v.qr_code_generated_at is None:
                payment_type = 'activation'
                date         = v.created_at
            else:
                delta = 0
                if v.created_at:
                    gen   = ensure_comoros(v.qr_code_generated_at)
                    cre   = ensure_comoros(v.created_at)
                    delta = (gen - cre).total_seconds()
                payment_type = 'activation' if delta < THREE_DAYS else 'renewal'
                date = v.qr_code_generated_at
            amount = None
            if payment_type == 'renewal':
                recorded_by = renewal_officer.get(v.id) or v.qr_renewed_by
            else:
                recorded_by = v.created_by

        rows.append({
            'vehicle_id':    v.id,
            'license_plate': v.license_plate or '',
            'owner_name':    v.owner_name or '',
            'payment_type':  payment_type,
            'amount':        amount,
            'recorded_by':   recorded_by or None,
            'date':          date,
            'qr_expiry':     v.qr_code_expiry,
            'qr_expired':    bool(v.qr_code_expiry and ensure_comoros(v.qr_code_expiry) <= _now),
        })

    if type_filter in ('activation', 'renewal'):
        rows = [r for r in rows if r['payment_type'] == type_filter]

    return rows


class _Pagination:
    """Minimal pagination helper for manually-sliced querysets."""
    def __init__(self, total, page, per_page):
        import math
        self.total    = total
        self.per_page = per_page
        self.pages    = max(1, math.ceil(total / per_page))
        self.page     = max(1, min(page, self.pages))
        self.has_prev = self.page > 1
        self.has_next = self.page < self.pages


@smart_tech_bp.route('/vehicles')
@smart_tech_required
def vehicles_page():
    page        = request.args.get('page', 1, type=int)
    per_page    = 50
    search      = request.args.get('search', '').strip()
    type_filter = request.args.get('type_filter', '').strip()

    all_rows   = _vehicles_query_filtered(search, type_filter)
    pagination = _Pagination(len(all_rows), page, per_page)
    start      = (pagination.page - 1) * per_page
    qr_rows    = all_rows[start:start + per_page]

    # Convert date objects to strings for template display
    for r in qr_rows:
        r['date_obj'] = r['date']

    act_price = SmartTechSetting.get('qr_activation_price', 5000)
    ren_price = SmartTechSetting.get('qr_renewal_price', 3000)
    return render_template(
        'smart_tech_vehicles.html',
        qr_rows=qr_rows,
        pagination=pagination,
        page=pagination.page,
        per_page=per_page,
        search=search,
        type_filter=type_filter,
        activation_price=int(act_price),
        renewal_price=int(ren_price),
    )


@smart_tech_bp.route('/api/vehicles-table')
@smart_tech_required
def api_vehicles_table():
    """JSON endpoint for live vehicles table (search + type filter aware)."""
    page        = request.args.get('page', 1, type=int)
    per_page    = 50
    search      = request.args.get('search', '').strip()
    type_filter = request.args.get('type_filter', '').strip()

    all_rows   = _vehicles_query_filtered(search, type_filter)
    pagination = _Pagination(len(all_rows), page, per_page)
    start      = (pagination.page - 1) * per_page
    page_rows  = all_rows[start:start + per_page]

    rows = []
    for r in page_rows:
        exp = r['qr_expiry']
        rows.append({
            'vehicle_id':    r['vehicle_id'],
            'license_plate': r['license_plate'],
            'owner_name':    r['owner_name'],
            'payment_type':  r['payment_type'],
            'amount':        r['amount'],
            'recorded_by':   r['recorded_by'],
            'date':          r['date'].strftime('%d/%m/%Y %H:%M') if r['date'] else None,
            'qr_expiry':     exp.strftime('%d/%m/%Y') if exp else None,
            'qr_expired':    r['qr_expired'],
        })

    return jsonify({
        'rows':             rows,
        'total':            pagination.total,
        'pages':            pagination.pages,
        'page':             pagination.page,
        'per_page':         per_page,
        'activation_price': int(SmartTechSetting.get('qr_activation_price', 5000)),
        'renewal_price':    int(SmartTechSetting.get('qr_renewal_price', 3000)),
    })


@smart_tech_bp.route('/api/vehicle-history/<int:vehicle_id>')
@smart_tech_required
def api_vehicle_history(vehicle_id):
    """Return QR activation date + all renewal events for one vehicle."""
    from app.models import VehicleHistory
    from app.timezone_utils import ensure_comoros

    vehicle = Vehicle.query.get_or_404(vehicle_id)

    # Activation date: earliest QR generation event or fallback to created_at
    activation_record = (
        VehicleHistory.query
        .filter(
            VehicleHistory.vehicle_id == vehicle_id,
            VehicleHistory.action.like('%QR Code%'),
        )
        .order_by(VehicleHistory.created_at.asc())
        .first()
    )
    activation_date    = activation_record.created_at if activation_record else (vehicle.qr_code_generated_at or vehicle.created_at)
    activation_officer = activation_record.officer if activation_record else vehicle.created_by

    # All QR renewal events, newest first
    renewal_records = (
        VehicleHistory.query
        .filter(
            VehicleHistory.vehicle_id == vehicle_id,
            VehicleHistory.action.like('%QR Code renouvelé%')
        )
        .order_by(VehicleHistory.created_at.desc())
        .all()
    )

    renewals = [
        {
            'date':    h.created_at.strftime('%d/%m/%Y %H:%M') if h.created_at else None,
            'officer': h.officer or '—',
        }
        for h in renewal_records
    ]

    return jsonify({
        'vehicle_id':          vehicle_id,
        'license_plate':       vehicle.license_plate,
        'owner_name':          vehicle.owner_name,
        'activation_date':     activation_date.strftime('%d/%m/%Y %H:%M') if activation_date else None,
        'activation_officer':  activation_officer or '—',
        'renewals':            renewals,
    })


@smart_tech_bp.route('/api/pending-qr-vehicles')
@smart_tech_required
def api_pending_qr_vehicles():
    """Return vehicles awaiting SmartTech QR activation approval."""
    vehicles = (
        _vq()
        .filter_by(qr_pending_approval=True)
        .order_by(Vehicle.created_at.desc())
        .all()
    )
    rows = []
    for v in vehicles:
        cg = getattr(v, 'carte_grise', None)
        rows.append({
            'id': v.id,
            'license_plate': v.license_plate or '',
            'owner_name': v.owner_name or '',
            'owner_island': v.owner_island or '',
            'vehicle_type': v.vehicle_type or '',
            'make': v.make or '',
            'model': v.model or '',
            'year': v.year or '',
            'created_by': v.created_by or '',
            'created_at': v.created_at.strftime('%d/%m/%Y %H:%M') if v.created_at else '',
            'carrosserie': cg.carrosserie if cg and cg.carrosserie else '',
            'places_assises': cg.places_assises if cg and cg.places_assises else '',
        })
    return jsonify({'vehicles': rows, 'count': len(rows)})


@smart_tech_bp.route('/api/last-update')
@smart_tech_required
def api_last_update():
    """Lightweight change-detection endpoint — returns a key string only."""
    from sqlalchemy import func
    result = _vq().with_entities(
        func.max(Vehicle.updated_at).label('last_update'),
        func.count(Vehicle.id).label('total')
    ).one()
    last_update = result.last_update.strftime('%Y-%m-%d %H:%M:%S') if result.last_update else ''
    return jsonify({'key': f'{last_update}|{result.total}'})


@smart_tech_bp.route('/api/qr-table')
@smart_tech_required
def api_qr_table():
    """JSON endpoint returning stats + qr_table_rows for live re-render."""
    from app.timezone_utils import now_comoros, ensure_comoros

    now = now_comoros()
    total    = _vq().count()
    active   = _vq().filter(Vehicle.qr_code_expiry.isnot(None), Vehicle.qr_code_expiry > now).count()
    inactive = _vq().filter(Vehicle.qr_code_expiry.isnot(None), Vehicle.qr_code_expiry <= now).count()

    all_vehicles = (
        _vq()
        .order_by(
            Vehicle.qr_code_generated_at.desc().nullslast(),
            Vehicle.created_at.desc()
        )
        .limit(20)
        .all()
    )
    vehicle_ids = [v.id for v in all_vehicles]

    recorded_payments = {
        p.vehicle_id: p
        for p in QRCodePayment.query.filter(
            QRCodePayment.status == 'paid',
            QRCodePayment.vehicle_id.in_(vehicle_ids) if vehicle_ids else db.false()
        ).all()
    }

    from app.models import VehicleHistory
    renewal_officer = {}
    if vehicle_ids:
        for h in (
            VehicleHistory.query
            .filter(
                VehicleHistory.vehicle_id.in_(vehicle_ids),
                VehicleHistory.action.like('%QR Code renouvelé%')
            )
            .order_by(VehicleHistory.created_at.desc())
            .all()
        ):
            renewal_officer.setdefault(h.vehicle_id, h.officer)

    THREE_DAYS = 3 * 86400
    rows = []
    for v in all_vehicles:
        recorded = recorded_payments.get(v.id)
        if recorded:
            payment_type = recorded.payment_type
            amount       = recorded.amount
            recorded_by  = recorded.recorded_by
            date         = recorded.paid_at
        else:
            if v.qr_code_generated_at is None:
                payment_type = 'activation'
                date         = v.created_at
            else:
                delta = 0
                if v.created_at:
                    gen   = ensure_comoros(v.qr_code_generated_at)
                    cre   = ensure_comoros(v.created_at)
                    delta = (gen - cre).total_seconds()
                payment_type = 'activation' if delta < THREE_DAYS else 'renewal'
                date = v.qr_code_generated_at
            amount = None
            if payment_type == 'renewal':
                recorded_by = renewal_officer.get(v.id) or v.qr_renewed_by
            else:
                recorded_by = v.created_by

        rows.append({
            'license_plate': v.license_plate,
            'owner_name':    v.owner_name,
            'payment_type':  payment_type,
            'amount':        amount,
            'recorded_by':   recorded_by,
            'date':          date.strftime('%d/%m/%Y %H:%M') if date else None,
        })

    return jsonify({
        'stats':             {'total': total, 'active': active, 'inactive': inactive},
        'rows':              rows,
        'activation_price':  int(SmartTechSetting.get('qr_activation_price', 5000)),
        'renewal_price':     int(SmartTechSetting.get('qr_renewal_price', 3000)),
    })


# ── Gestion des Véhicules ──────────────────────────────────────────────────────

@smart_tech_bp.route('/gestion-vehicules')
@st_no_secretaire_required
def gestion_vehicules_page():
    return render_template('smart_tech_gestion_vehicules.html')


# ── Renouvellement QR ──────────────────────────────────────────────────────────

@smart_tech_bp.route('/renouvellement')
@st_no_secretaire_required
def renouvellement_page():
    renewal_price = int(SmartTechSetting.get('qr_renewal_price', 3000))
    return render_template('smart_tech_renouvellement.html', renewal_price=renewal_price)


# ── Subscriptions ──────────────────────────────────────────────────────────────

@smart_tech_bp.route('/subscriptions')
@st_admin_or_secretaire_required
def subscriptions_page():
    subs          = Subscription.query.order_by(Subscription.created_at.desc()).all()
    active_subs   = [s for s in subs if s.is_active]
    total_monthly = sum(s.monthly_cost() for s in active_subs)
    total_paid    = sum(s.amount for s in subs if s.is_active and (s.payment_mode == 'automatique' or s.last_paid_at is not None))
    return render_template(
        'smart_tech_subscriptions.html',
        subs=subs,
        total_monthly=total_monthly,
        total_annual=total_monthly * 12,
        active_count=len(active_subs),
        total_paid=total_paid,
    )


@smart_tech_bp.route('/api/subscriptions', methods=['GET'])
@smart_tech_required
def api_subscriptions_list():
    subs          = Subscription.query.order_by(Subscription.created_at.desc()).all()
    active_subs   = [s for s in subs if s.is_active]
    total_monthly = sum(s.monthly_cost() for s in active_subs)
    total_paid    = sum(s.amount for s in subs if s.is_active and (s.payment_mode == 'automatique' or s.last_paid_at is not None))
    return jsonify({
        'subscriptions': [s.to_dict() for s in subs],
        'total_monthly': round(total_monthly, 2),
        'total_annual':  round(total_monthly * 12, 2),
        'active_count':  len(active_subs),
        'total_paid':    round(total_paid, 2),
    })


@smart_tech_bp.route('/api/subscriptions', methods=['POST'])
@smart_tech_required
def api_subscription_create():
    from datetime import date as _date
    data         = request.get_json(silent=True) or {}
    name         = (data.get('name') or '').strip()
    sub_type     = (data.get('sub_type') or '').strip()
    frequency    = (data.get('frequency') or '').strip()
    amount       = float(data.get('amount') or 0)
    payment_mode = (data.get('payment_mode') or 'manuel').strip()
    phone_id     = data.get('phone_id') or None
    employee_id  = data.get('employee_id') or None
    notes        = (data.get('notes') or '').strip() or None
    is_active    = bool(data.get('is_active', True))
    start_date_raw = (data.get('start_date') or '').strip() or None
    start_date   = _date.fromisoformat(start_date_raw) if start_date_raw else _date.today()

    if not name or not sub_type or not frequency:
        return jsonify({'error': 'Nom, type et fréquence sont requis.'}), 400

    sub = Subscription(
        name=name, sub_type=sub_type, frequency=frequency,
        amount=amount, payment_mode=payment_mode,
        phone_id=int(phone_id) if phone_id else None,
        employee_id=int(employee_id) if employee_id else None,
        notes=notes, is_active=is_active,
        start_date=start_date,
        created_by=current_user.username,
    )
    db.session.add(sub)
    db.session.commit()
    return jsonify({'success': True, 'subscription': sub.to_dict()}), 201


@smart_tech_bp.route('/api/subscriptions/<int:sub_id>', methods=['PUT'])
@smart_tech_required
def api_subscription_update(sub_id):
    from datetime import date as _date
    sub  = Subscription.query.get_or_404(sub_id)
    data = request.get_json(silent=True) or {}
    if 'name'         in data: sub.name         = (data['name'] or '').strip()
    if 'sub_type'     in data: sub.sub_type      = (data['sub_type'] or '').strip()
    if 'frequency'    in data: sub.frequency     = (data['frequency'] or '').strip()
    if 'amount'       in data: sub.amount        = float(data['amount'] or 0)
    if 'payment_mode' in data: sub.payment_mode  = (data['payment_mode'] or 'manuel').strip()
    if 'phone_id'     in data: sub.phone_id      = int(data['phone_id'])    if data['phone_id']    else None
    if 'employee_id'  in data: sub.employee_id   = int(data['employee_id']) if data['employee_id'] else None
    if 'notes'        in data: sub.notes         = (data['notes'] or '').strip() or None
    if 'is_active'    in data: sub.is_active     = bool(data['is_active'])
    if 'start_date'   in data:
        raw = (data['start_date'] or '').strip() or None
        sub.start_date = _date.fromisoformat(raw) if raw else None
    db.session.commit()
    return jsonify({'success': True, 'subscription': sub.to_dict()})


@smart_tech_bp.route('/api/subscriptions/available-phones')
@smart_tech_required
def api_available_phones():
    """Active phones not already linked to an active Recharge mobile subscription."""
    from app.models import Phone
    exclude_id = request.args.get('sub_id', type=int)
    used = {
        s.phone_id for s in Subscription.query
        .filter_by(is_active=True, sub_type='Recharge mobile').all()
        if s.phone_id and (exclude_id is None or s.id != exclude_id)
    }
    phones = Phone.query.filter_by(status='active').order_by(Phone.phone_code).all()
    return jsonify([
        {'id': p.id, 'label': f"{p.phone_code} — {p.brand} {p.model}" + (f" ({p.island})" if p.island else "")}
        for p in phones if p.id not in used
    ])


@smart_tech_bp.route('/api/subscriptions/available-employees')
@smart_tech_required
def api_available_employees():
    """Active employees not already linked to an active Salaire subscription."""
    exclude_id = request.args.get('sub_id', type=int)
    used = {
        s.employee_id for s in Subscription.query
        .filter_by(is_active=True, sub_type='Salaire').all()
        if s.employee_id and (exclude_id is None or s.id != exclude_id)
    }
    emps = Employee.query.filter_by(status='actif').order_by(Employee.last_name, Employee.first_name).all()
    return jsonify([
        {'id': e.id, 'salary': e.salary,
         'label': f"{e.full_name} — {e.position}" + (f" ({e.island})" if e.island else "")}
        for e in emps if e.id not in used
    ])


@smart_tech_bp.route('/api/subscriptions/<int:sub_id>/pay', methods=['POST'])
@smart_tech_required
def api_subscription_pay(sub_id):
    """Mark a manual subscription as paid (validated)."""
    from app.timezone_utils import now_comoros
    sub = Subscription.query.get_or_404(sub_id)
    paid_at = now_comoros()
    sub.last_paid_at = paid_at
    sub.last_paid_by = current_user.username
    sub.start_date   = paid_at.date()
    db.session.commit()
    return jsonify({'success': True, 'subscription': sub.to_dict()})


@smart_tech_bp.route('/api/subscriptions/<int:sub_id>', methods=['DELETE'])
@smart_tech_required
def api_subscription_delete(sub_id):
    sub = Subscription.query.get_or_404(sub_id)
    db.session.delete(sub)
    db.session.commit()
    return jsonify({'success': True})


# ── Expenses ────────────────────────────────────────────────────────────────

@smart_tech_bp.route('/depenses')
@st_admin_or_secretaire_required
def depenses_page():
    from app.timezone_utils import now_comoros
    from datetime import date
    expenses = Expense.query.order_by(Expense.expense_date.desc(), Expense.created_at.desc()).all()
    today = now_comoros().date()
    total_all   = sum(e.amount for e in expenses)
    total_month = sum(e.amount for e in expenses
                      if e.expense_date and e.expense_date.year == today.year
                      and e.expense_date.month == today.month)
    return render_template(
        'smart_tech_depenses.html',
        expenses=expenses,
        categories=Expense.CATEGORIES,
        total_all=total_all,
        total_month=total_month,
        count=len(expenses),
    )


@smart_tech_bp.route('/api/expenses', methods=['GET'])
@smart_tech_required
def api_expenses_list():
    from app.timezone_utils import now_comoros
    expenses  = Expense.query.order_by(Expense.expense_date.desc(), Expense.created_at.desc()).all()
    today     = now_comoros().date()
    total_all   = sum(e.amount for e in expenses)
    total_month = sum(e.amount for e in expenses
                      if e.expense_date and e.expense_date.year == today.year
                      and e.expense_date.month == today.month)
    return jsonify({
        'expenses':    [e.to_dict() for e in expenses],
        'total_all':   round(total_all, 2),
        'total_month': round(total_month, 2),
        'count':       len(expenses),
    })


@smart_tech_bp.route('/api/expenses', methods=['POST'])
@smart_tech_required
def api_expense_create():
    from datetime import date as _date
    data        = request.get_json(silent=True) or {}
    description = (data.get('description') or '').strip()
    category    = (data.get('category') or '').strip()
    amount      = float(data.get('amount') or 0)
    date_raw    = (data.get('expense_date') or '').strip()
    vendor      = (data.get('vendor') or '').strip() or None
    notes       = (data.get('notes') or '').strip() or None

    if not description or not category or not date_raw:
        return jsonify({'error': 'Description, catégorie et date sont requis.'}), 400

    exp = Expense(
        description=description, category=category, amount=amount,
        expense_date=_date.fromisoformat(date_raw),
        vendor=vendor, notes=notes,
        created_by=current_user.username,
    )
    db.session.add(exp)
    db.session.commit()
    return jsonify({'success': True, 'expense': exp.to_dict()}), 201


@smart_tech_bp.route('/api/expenses/<int:exp_id>', methods=['PUT'])
@smart_tech_required
def api_expense_update(exp_id):
    from datetime import date as _date
    exp  = Expense.query.get_or_404(exp_id)
    data = request.get_json(silent=True) or {}
    if 'description'  in data: exp.description  = (data['description'] or '').strip()
    if 'category'     in data: exp.category      = (data['category'] or '').strip()
    if 'amount'       in data: exp.amount        = float(data['amount'] or 0)
    if 'expense_date' in data:
        raw = (data['expense_date'] or '').strip()
        exp.expense_date = _date.fromisoformat(raw) if raw else exp.expense_date
    if 'vendor' in data: exp.vendor = (data['vendor'] or '').strip() or None
    if 'notes'  in data: exp.notes  = (data['notes'] or '').strip() or None
    db.session.commit()
    return jsonify({'success': True, 'expense': exp.to_dict()})


@smart_tech_bp.route('/api/expenses/<int:exp_id>', methods=['DELETE'])
@smart_tech_required
def api_expense_delete(exp_id):
    exp = Expense.query.get_or_404(exp_id)
    db.session.delete(exp)
    db.session.commit()
    return jsonify({'success': True})


# ── Reports ─────────────────────────────────────────────────────────────────

def _period_bounds(period_type, period_value):
    """Return (start_dt, end_dt) as timezone-aware Comoros datetimes."""
    import calendar as _cal
    from datetime import datetime, date as _date
    from app.timezone_utils import COMOROS_TZ
    if period_type == 'daily':
        d = _date.fromisoformat(period_value)
        start = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=COMOROS_TZ)
        end   = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=COMOROS_TZ)
    elif period_type == 'monthly':
        year, month = map(int, period_value.split('-'))
        last_day = _cal.monthrange(year, month)[1]
        start = datetime(year, month, 1, 0, 0, 0, tzinfo=COMOROS_TZ)
        end   = datetime(year, month, last_day, 23, 59, 59, tzinfo=COMOROS_TZ)
    else:  # annual
        year  = int(period_value)
        start = datetime(year, 1, 1,  0, 0, 0,  tzinfo=COMOROS_TZ)
        end   = datetime(year, 12, 31, 23, 59, 59, tzinfo=COMOROS_TZ)
    return start, end


def _auto_subs_in_period(subs, start_date, end_date):
    """Return automatic active subscriptions that have a debit date in [start_date, end_date]."""
    from dateutil.relativedelta import relativedelta
    result = []
    freq_delta = {
        'hebdomadaire':  relativedelta(weeks=1),
        'mensuelle':     relativedelta(months=1),
        'trimestrielle': relativedelta(months=3),
        'semestrielle':  relativedelta(months=6),
        'annuelle':      relativedelta(years=1),
    }
    for s in subs:
        if s.payment_mode != 'automatique' or not s.is_active or not s.start_date:
            continue
        delta = freq_delta.get(s.frequency)
        if delta is None:
            # ponctuelle: include if start_date in range
            if start_date <= s.start_date <= end_date:
                result.append(s)
            continue
        d = s.start_date
        found = False
        while d <= end_date and not found:
            if d >= start_date:
                found = True
            d = d + delta
        if found:
            result.append(s)
    return result


def _build_report(period_type, period_value):
    """Compile all report data for the given period."""
    from app.timezone_utils import ensure_comoros
    from datetime import date as _date
    start_dt, end_dt = _period_bounds(period_type, period_value)
    start_d, end_d   = start_dt.date(), end_dt.date()

    # QR payments — filter by paid_at (the actual payment date)
    qr_all = QRCodePayment.query.filter(
        QRCodePayment.status == 'paid'
    ).all()
    qr_in  = [q for q in qr_all
              if q.paid_at and start_dt <= ensure_comoros(q.paid_at) <= end_dt]
    activations = [q for q in qr_in if q.payment_type == 'activation']
    renewals    = [q for q in qr_in if q.payment_type == 'renewal']

    # All active subscriptions (displayed in every report)
    active_subs = Subscription.query.filter_by(is_active=True)\
                      .order_by(Subscription.sub_type, Subscription.name).all()

    # Manual subscriptions validated in period
    manual_paid_ids = set()
    manual_paid = []
    for s in active_subs:
        if s.payment_mode == 'manuel' and s.last_paid_at and \
                start_dt <= ensure_comoros(s.last_paid_at) <= end_dt:
            manual_paid.append(s)
            manual_paid_ids.add(s.id)

    # Automatic subscriptions with a debit in period
    auto_subs = [s for s in active_subs if s.payment_mode == 'automatique']
    auto_due  = _auto_subs_in_period(auto_subs, start_d, end_d)
    auto_due_ids = {s.id for s in auto_due}

    # Expenses in period
    expenses = Expense.query.filter(
        Expense.expense_date >= start_d,
        Expense.expense_date <= end_d,
    ).order_by(Expense.expense_date).all()

    # Printed licenses in period — use the price stored at print time
    license_print_price = float(SmartTechSetting.get('license_print_price', 0))
    licenses_printed = LicensePrintRequest.query.filter(
        LicensePrintRequest.status == 'printed',
        LicensePrintRequest.printed_at >= start_dt,
        LicensePrintRequest.printed_at <= end_dt,
    ).order_by(LicensePrintRequest.printed_at.desc()).all()
    license_total = sum(lr.unit_price for lr in licenses_printed)

    act_total   = sum(q.amount for q in activations)
    ren_total   = sum(q.amount for q in renewals)
    man_total   = sum(s.amount for s in manual_paid)
    auto_total  = sum(s.amount for s in auto_due)
    sub_total   = man_total + auto_total
    exp_total   = sum(e.amount for e in expenses)
    revenue     = act_total + ren_total + license_total
    net         = revenue - sub_total - exp_total

    # Commission Assurance
    # Commission is a monthly concept: always aggregate per-month so the Rapport
    # matches the Mouvements tab regardless of whether the user selected a day or a month.
    commission_rate = int(SmartTechSetting.get('insurance_commission', 0))
    is_monthly = (period_type == 'monthly')
    if period_type == 'daily':
        receipt_month = period_value[:7]           # "2026-06-21" → "2026-06" (for receipt lookup)
    elif period_type == 'monthly':
        receipt_month = period_value
    else:
        receipt_month = None                       # annual — no single-month receipt
    companies  = Insurance.query.order_by(Insurance.company_name).all()
    insurance_commissions = []
    commission_total = 0
    for ins in companies:
        account_ids = [acc.id for acc in ins.accounts]
        if account_ids:
            assignments = VehicleInsuranceAssignment.query.filter(
                VehicleInsuranceAssignment.insurance_account_id.in_(account_ids)
            ).all()
            vids = list({a.vehicle_id for a in assignments})
        else:
            vids = []
        if vids:
            vids_set = set(vids)
            payments = [q for q in qr_in if q.vehicle_id in vids_set]
            comp_acts = sum(1 for p in payments if p.payment_type == 'activation')
            comp_rens = sum(1 for p in payments if p.payment_type == 'renewal')
        else:
            comp_acts = comp_rens = 0
        comp_comm = (comp_acts + comp_rens) * commission_rate
        confirmed = False
        confirmed_at = None
        confirmed_by = None
        if receipt_month:
            rval = SmartTechSetting.get('commission_received_%s_%s' % (ins.id, receipt_month), '')
            if rval and rval != '0':
                confirmed = True
                parts = str(rval).split('|', 1)
                confirmed_at = parts[0]
                confirmed_by = parts[1] if len(parts) > 1 else None
        insurance_commissions.append({
            'id': ins.id, 'company_name': ins.company_name, 'island': ins.island or '',
            'activations': comp_acts, 'renewals': comp_rens,
            'commission': comp_comm, 'confirmed': confirmed,
            'confirmed_at': confirmed_at, 'confirmed_by': confirmed_by,
        })
        commission_total += comp_comm

    return {
        'period_type':        period_type,
        'period_value':       period_value,
        'start_dt':           start_dt,
        'end_dt':             end_dt,
        'activations':        activations,
        'renewals':           renewals,
        'active_subs':        active_subs,
        'manual_paid_ids':    manual_paid_ids,
        'auto_due_ids':       auto_due_ids,
        'manual_paid':        manual_paid,
        'auto_due':           auto_due,
        'expenses':           expenses,
        'licenses_printed':   licenses_printed,
        'license_print_price': license_print_price,
        'license_total':      license_total,
        'act_total':          act_total,
        'ren_total':          ren_total,
        'man_total':          man_total,
        'auto_total':         auto_total,
        'sub_total':          sub_total,
        'exp_total':          exp_total,
        'revenue':            revenue,
        'net':                net,
        'insurance_commissions': insurance_commissions,
        'commission_total':   commission_total,
        'commission_rate':    commission_rate,
        'is_monthly':         is_monthly,
        'has_receipt':        receipt_month is not None,
        'receipt_month':      receipt_month,
    }


@smart_tech_bp.route('/rapport')
@st_admin_or_secretaire_required
def rapport_page():
    from app.timezone_utils import now_comoros
    today = now_comoros().date()
    act_price = SmartTechSetting.get('qr_activation_price', 5000)
    ren_price = SmartTechSetting.get('qr_renewal_price', 3000)
    return render_template(
        'smart_tech_rapport.html',
        today=today.isoformat(),
        current_month=today.strftime('%Y-%m'),
        current_year=today.year,
        activation_price=int(act_price),
        renewal_price=int(ren_price),
    )


@smart_tech_bp.route('/api/rapport')
@st_admin_or_secretaire_required
def api_rapport():
    period_type  = request.args.get('type', 'daily')
    period_value = request.args.get('value', '')
    if not period_value:
        from app.timezone_utils import now_comoros
        today = now_comoros().date()
        if period_type == 'daily':
            period_value = today.isoformat()
        elif period_type == 'monthly':
            period_value = today.strftime('%Y-%m')
        else:
            period_value = str(today.year)
    try:
        r = _build_report(period_type, period_value)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

    paid_ids    = r['manual_paid_ids']
    debited_ids = r['auto_due_ids']

    def fmt_sub(s):
        if s.payment_mode == 'automatique':
            status = 'paid'
        elif s.id in paid_ids:
            status = 'paid'
        elif s.payment_mode == 'manuel' and s.is_payment_due():
            status = 'due'
        else:
            status = 'scheduled'
        npd = s.next_payment_date() if s.payment_mode == 'automatique' else s.next_manual_due_date()
        return {
            'id': s.id, 'name': s.name, 'sub_type': s.sub_type,
            'payment_mode': s.payment_mode,
            'frequency': s.frequency, 'amount': s.amount,
            'last_paid_at': s.last_paid_at.strftime('%d/%m/%Y %H:%M') if s.last_paid_at else None,
            'last_paid_by': s.last_paid_by,
            'start_date': s.start_date.strftime('%d/%m/%Y') if s.start_date else None,
            'next_payment_date': npd.strftime('%d/%m/%Y') if npd else None,
            'status': status,
        }

    return jsonify({
        'period_type':       r['period_type'],
        'period_value':      r['period_value'],
        'period_label':      _period_label(r['period_type'], r['period_value']),
        'activations':       [q.to_dict() for q in r['activations']],
        'renewals':          [q.to_dict() for q in r['renewals']],
        'subscriptions':     [fmt_sub(s) for s in r['manual_paid'] + r['auto_due']],
        'licenses_printed':  [lr.to_dict() for lr in r['licenses_printed']],
        'license_price':     r['license_print_price'],
        'license_total':     round(r['license_total'], 2),
        'manual_paid':       [fmt_sub(s) for s in r['manual_paid']],
        'auto_due':          [fmt_sub(s) for s in r['auto_due']],
        'expenses':          [e.to_dict() for e in r['expenses']],
        'act_total':         round(r['act_total'], 2),
        'ren_total':         round(r['ren_total'], 2),
        'man_total':         round(r['man_total'], 2),
        'auto_total':        round(r['auto_total'], 2),
        'sub_total':         round(r['sub_total'], 2),
        'exp_total':         round(r['exp_total'], 2),
        'revenue':           round(r['revenue'], 2),
        'net':               round(r['net'], 2),
        'activation_price':  int(SmartTechSetting.get('qr_activation_price', 5000)),
        'renewal_price':     int(SmartTechSetting.get('qr_renewal_price', 3000)),
        'insurance_commissions': r['insurance_commissions'],
        'commission_total':  round(r['commission_total'], 2),
        'commission_rate':   r['commission_rate'],
        'is_monthly':        r['is_monthly'],
        'has_receipt':       r['has_receipt'],
        'receipt_month':     r['receipt_month'],
    })


def _period_label(period_type, period_value):
    MONTHS_FR = ['Janvier','Février','Mars','Avril','Mai','Juin',
                 'Juillet','Août','Septembre','Octobre','Novembre','Décembre']
    if period_type == 'daily':
        from datetime import date as _date
        d = _date.fromisoformat(period_value)
        return d.strftime('%d/%m/%Y')
    elif period_type == 'monthly':
        year, month = map(int, period_value.split('-'))
        return f'{MONTHS_FR[month-1]} {year}'
    else:
        return f'Année {period_value}'


@smart_tech_bp.route('/rapport/pdf')
@st_admin_or_secretaire_required
def rapport_pdf():
    period_type  = request.args.get('type', 'daily')
    period_value = request.args.get('value', '')
    if not period_value:
        from app.timezone_utils import now_comoros
        today = now_comoros().date()
        period_value = today.isoformat() if period_type == 'daily' else \
                       today.strftime('%Y-%m') if period_type == 'monthly' else str(today.year)
    try:
        r = _build_report(period_type, period_value)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

    pdf_bytes = _generate_pdf(r)
    label     = _period_label(period_type, period_value).replace(' ', '_').replace('/', '-')
    filename  = f'rapport_smart_technology_{label}.pdf'
    return Response(
        pdf_bytes,
        mimetype='application/pdf',
        headers={'Content-Disposition': f'inline; filename="{filename}"'},
    )


def _generate_pdf(r):
    """Generate a PDF report using ReportLab and return bytes."""
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                     TableStyle, HRFlowable)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    W = A4[0] - 4*cm
    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle('Title', parent=styles['Normal'],
        fontSize=18, fontName='Helvetica-Bold', textColor=colors.HexColor('#0d1117'),
        spaceAfter=8, alignment=TA_CENTER)
    sub_style = ParagraphStyle('Sub', parent=styles['Normal'],
        fontSize=11, textColor=colors.HexColor('#0d3460'), fontName='Helvetica-Bold',
        alignment=TA_CENTER, spaceAfter=4)
    section_style = ParagraphStyle('Section', parent=styles['Normal'],
        fontSize=11, fontName='Helvetica-Bold',
        textColor=colors.HexColor('#0d3460'), spaceBefore=14, spaceAfter=6)
    normal = ParagraphStyle('N', parent=styles['Normal'], fontSize=9)
    small  = ParagraphStyle('S', parent=styles['Normal'], fontSize=8,
                             textColor=colors.HexColor('#666'))
    cell   = ParagraphStyle('C', parent=styles['Normal'], fontSize=8, leading=10)
    cell_h = ParagraphStyle('CH', parent=styles['Normal'], fontSize=8, leading=10,
                             fontName='Helvetica-Bold', textColor=colors.white)

    def p(text, style=None): return Paragraph(str(text) if text else '—', style or cell)
    def ph(text): return Paragraph(str(text), cell_h)
    def fmt(n): return f'{round(n):,}'.replace(',', ' ') + ' KMF'
    def tbl_style(header_color):
        return TableStyle([
            ('BACKGROUND',    (0,0), (-1,0), header_color),
            ('ROWBACKGROUNDS',(0,1), (-1,-1), [colors.white, colors.HexColor('#f8fafc')]),
            ('GRID',          (0,0), (-1,-1), 0.4, colors.HexColor('#dde')),
            ('VALIGN',        (0,0), (-1,-1), 'TOP'),
            ('TOPPADDING',    (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('LEFTPADDING',   (0,0), (-1,-1), 6),
            ('RIGHTPADDING',  (0,0), (-1,-1), 6),
        ])

    story = []

    # ── Header ──
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph('Smart Development', title_style))
    story.append(Paragraph('Rapport — ' + _period_label(r['period_type'], r['period_value']), sub_style))
    from app.timezone_utils import now_comoros
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph('Généré le ' + now_comoros().strftime('%d/%m/%Y à %H:%M'), small))
    story.append(Spacer(1, 0.4*cm))
    story.append(HRFlowable(width=W, thickness=1.5, color=colors.HexColor('#0d3460'), spaceAfter=14))

    # ── Summary table ──
    story.append(Paragraph('Résumé', section_style))
    auto_subs   = [s for s in r['active_subs'] if s.payment_mode == 'automatique']
    manuel_subs = [s for s in r['active_subs'] if s.payment_mode == 'manuel']
    comm_companies = sum(1 for c in r['insurance_commissions'] if c['commission'] > 0)
    summary_data = [
        [ph('Catégorie'), ph('Quantité'), ph('Montant')],
        [p('Activations QR Code'),       p(str(len(r['activations']))),        p(fmt(r['act_total']))],
        [p('Renouvellements QR Code'),   p(str(len(r['renewals']))),            p(fmt(r['ren_total']))],
        [p('Licences imprimées'),        p(str(len(r['licenses_printed']))),    p(fmt(r['license_total']))],
        [p('Commission Assurance'),      p(str(comm_companies) + ' compagnies'), p(fmt(r['commission_total']))],
        [p('Abonnements automatiques'),  p(str(len(auto_subs))),                p(fmt(sum(s.amount for s in auto_subs)))],
        [p('Abonnements manuels'),       p(str(len(manuel_subs))),              p(fmt(sum(s.amount for s in manuel_subs)))],
        [p('Dépenses'),                  p(str(len(r['expenses']))),            p(fmt(r['exp_total']))],
    ]
    summary_data += [
        [p('Revenus totaux (Activations + Renouvellements + Licences)'), p(''), p(fmt(r['revenue']))],
        [p('Charges totales (Abonnements + Dépenses)'),                  p(''), p(fmt(r['sub_total'] + r['exp_total']))],
        [p('Résultat net'),                                               p(''), p(fmt(r['net']))],
    ]
    summary_tbl = Table(summary_data, colWidths=[W*0.55, W*0.2, W*0.25])
    base = tbl_style(colors.HexColor('#0d3460'))
    base.add('BACKGROUND', (0, len(summary_data)-3), (-1, len(summary_data)-3), colors.HexColor('#dce8ff'))
    base.add('BACKGROUND', (0, len(summary_data)-2), (-1, len(summary_data)-2), colors.HexColor('#ffe4e4'))
    net_color = colors.HexColor('#d4edda') if r['net'] >= 0 else colors.HexColor('#f8d7da')
    base.add('BACKGROUND', (0, len(summary_data)-1), (-1, len(summary_data)-1), net_color)
    base.add('FONTNAME',   (0, len(summary_data)-3), (-1, -1), 'Helvetica-Bold')
    base.add('SPAN', (0, len(summary_data)-3), (1, len(summary_data)-3))
    base.add('SPAN', (0, len(summary_data)-2), (1, len(summary_data)-2))
    base.add('SPAN', (0, len(summary_data)-1), (1, len(summary_data)-1))
    summary_tbl.setStyle(base)
    story.append(summary_tbl)

    # ── Activations ──
    if r['activations']:
        story.append(Paragraph(f"Activations QR Code ({len(r['activations'])})", section_style))
        data = [[ph('Véhicule'), ph('Propriétaire'), ph('Montant'), ph('Enregistré par'), ph('Date')]]
        for q in r['activations']:
            data.append([
                p(q.vehicle.license_plate if q.vehicle else '—'),
                p((q.vehicle.owner_name or '—') if q.vehicle else '—'),
                p(fmt(q.amount)),
                p(q.recorded_by or '—'),
                p(q.created_at.strftime('%d/%m/%Y %H:%M') if q.created_at else '—'),
            ])
        tbl = Table(data, colWidths=[W*0.18, W*0.25, W*0.17, W*0.2, W*0.2], repeatRows=1)
        tbl.setStyle(tbl_style(colors.HexColor('#0080cc')))
        story.append(tbl)

    # ── Renewals ──
    if r['renewals']:
        story.append(Paragraph(f"Renouvellements QR Code ({len(r['renewals'])})", section_style))
        data = [[ph('Véhicule'), ph('Propriétaire'), ph('Montant'), ph('Enregistré par'), ph('Date')]]
        for q in r['renewals']:
            data.append([
                p(q.vehicle.license_plate if q.vehicle else '—'),
                p((q.vehicle.owner_name or '—') if q.vehicle else '—'),
                p(fmt(q.amount)),
                p(q.recorded_by or '—'),
                p(q.created_at.strftime('%d/%m/%Y %H:%M') if q.created_at else '—'),
            ])
        tbl = Table(data, colWidths=[W*0.18, W*0.25, W*0.17, W*0.2, W*0.2], repeatRows=1)
        tbl.setStyle(tbl_style(colors.HexColor('#00aa88')))
        story.append(tbl)

    # ── Licenses printed ──
    if r['licenses_printed']:
        story.append(Paragraph(f"Licences imprimées ({len(r['licenses_printed'])})", section_style))
        data = [[ph('N° Permis'), ph('Titulaire'), ph('Imprimé par'), ph('Date impression'), ph('Montant')]]
        for lr in r['licenses_printed']:
            lic = lr.license
            holder = ''
            if lic:
                holder = ((lic.holder_firstname or '') + ' ' + (lic.holder_name or '')).strip()
            data.append([
                p(lr.license.license_number if lr.license else '—'),
                p(holder or '—'),
                p(lr.printed_by or '—'),
                p(lr.printed_at.strftime('%d/%m/%Y %H:%M') if lr.printed_at else '—'),
                p(fmt(lr.unit_price)),
            ])
        tbl = Table(data, colWidths=[W*0.2, W*0.25, W*0.2, W*0.2, W*0.15], repeatRows=1)
        tbl.setStyle(tbl_style(colors.HexColor('#6e40c9')))
        story.append(tbl)

    # ── All active subscriptions ──
    if r['active_subs']:
        paid_ids_pdf    = r['manual_paid_ids']
        debited_ids_pdf = r['auto_due_ids']
        story.append(Paragraph(f"Abonnements actifs ({len(r['active_subs'])})", section_style))
        data = [[ph('Nom'), ph('Type'), ph('Mode'), ph('Fréquence'), ph('Montant'), ph('Statut / Date')]]
        for s in r['active_subs']:
            if s.payment_mode == 'automatique':
                statut = 'Payé (auto)'
                date_info = 'Prélèvement automatique'
            elif s.id in paid_ids_pdf:
                statut = 'Payé'
                date_info = s.last_paid_at.strftime('%d/%m/%Y') if s.last_paid_at else '—'
                if s.last_paid_by:
                    date_info += f' par {s.last_paid_by}'
            elif s.is_payment_due():
                statut = 'Dû'
                date_info = f'Depuis le {s.start_date.strftime("%d/%m/%Y")}' if s.start_date else '—'
            else:
                statut = 'Prévu'
                date_info = '—'
            data.append([
                p(s.name), p(s.sub_type),
                p('Auto' if s.payment_mode == 'automatique' else 'Manuel'),
                p(s.frequency), p(fmt(s.amount)),
                p(f'{statut} — {date_info}'),
            ])
        tbl = Table(data, colWidths=[W*0.2, W*0.14, W*0.1, W*0.14, W*0.14, W*0.28], repeatRows=1)
        tbl.setStyle(tbl_style(colors.HexColor('#c47c00')))
        story.append(tbl)

    # ── Expenses ──
    if r['expenses']:
        story.append(Paragraph(f"Dépenses ({len(r['expenses'])})", section_style))
        data = [[ph('Description'), ph('Catégorie'), ph('Fournisseur'), ph('Montant'), ph('Date')]]
        for e in r['expenses']:
            data.append([
                p(e.description), p(e.category), p(e.vendor or '—'),
                p(fmt(e.amount)),
                p(e.expense_date.strftime('%d/%m/%Y') if e.expense_date else '—'),
            ])
        tbl = Table(data, colWidths=[W*0.3, W*0.18, W*0.2, W*0.15, W*0.17], repeatRows=1)
        tbl.setStyle(tbl_style(colors.HexColor('#cc3333')))
        story.append(tbl)

    # ── Commission Assurance ──
    comm_list = [c for c in r['insurance_commissions'] if c['activations'] or c['renewals'] or c['commission']]
    if comm_list or r['commission_rate']:
        story.append(Paragraph(f"Commission Assurance ({r['commission_rate']:,} KMF/abonnement)".replace(',', ' '), section_style))
        has_receipt = r.get('has_receipt', r.get('is_monthly', False))
        receipt_month = r.get('receipt_month') or ''
        hdr = [ph('Compagnie'), ph('Île'), ph('Activations'), ph('Renouvellements'), ph('Commission')]
        if has_receipt:
            hdr.append(ph('Réception'))
        data = [hdr]
        for c in r['insurance_commissions']:
            row = [
                p(c['company_name']), p(c['island'] or '—'),
                p(str(c['activations'])), p(str(c['renewals'])),
                p(fmt(c['commission'])),
            ]
            if has_receipt:
                if c['confirmed'] and c['confirmed_at']:
                    try:
                        from datetime import datetime as _dt
                        dt = _dt.fromisoformat(c['confirmed_at'])
                        rcpt_txt = 'Reçue le ' + dt.strftime('%d/%m/%Y')
                    except Exception:
                        rcpt_txt = 'Reçue'
                else:
                    rcpt_txt = 'Non confirmée'
                row.append(p(rcpt_txt))
            data.append(row)
        # Total row
        total_row = [p('Total'), p(''), p(''), p(''), p(fmt(r['commission_total']))]
        if has_receipt:
            confirmed_count = sum(1 for c in r['insurance_commissions'] if c['confirmed'])
            total_row.append(p(f'{confirmed_count}/{len(r["insurance_commissions"])} reçues'))
        data.append(total_row)
        col_widths = [W*0.28, W*0.14, W*0.14, W*0.16, W*0.14]
        if has_receipt:
            col_widths.append(W*0.14)
        tbl = Table(data, colWidths=col_widths, repeatRows=1)
        s = tbl_style(colors.HexColor('#b07a00'))
        s.add('BACKGROUND', (0, len(data)-1), (-1, len(data)-1), colors.HexColor('#fff3cd'))
        s.add('FONTNAME',   (0, len(data)-1), (-1, len(data)-1), 'Helvetica-Bold')
        tbl.setStyle(s)
        story.append(tbl)

    story.append(Spacer(1, 1*cm))
    story.append(HRFlowable(width=W, thickness=0.5, color=colors.HexColor('#ccc')))
    story.append(Paragraph('Smart Development — Rapport généré automatiquement', small))

    doc.build(story)
    return buf.getvalue()


# ── Island Statistics ────────────────────────────────────────────────────────

ISLANDS = ['Grande Comore', 'Anjouan', 'Moheli']


def _island_stats(year=None):
    """Compute per-island stats.
    Activations/renewals are inferred from Vehicle.qr_code_generated_at (same
    logic as the dashboard), filtered by year when provided.
    Revenue comes from recorded QRCodePayment rows.
    """
    from app.timezone_utils import ensure_comoros, COMOROS_TZ
    from datetime import datetime

    THREE_DAYS = 3 * 86400  # seconds

    all_vehicles = Vehicle.query.all()

    # Build year-range helpers
    if year:
        start_dt = datetime(year, 1, 1, 0, 0, 0, tzinfo=COMOROS_TZ)
        end_dt   = datetime(year, 12, 31, 23, 59, 59, tzinfo=COMOROS_TZ)
    else:
        start_dt = end_dt = None

    def in_year(dt):
        if dt is None:
            return False
        if start_dt is None:
            return True
        return start_dt <= ensure_comoros(dt) <= end_dt

    def count_qr_ops(vehicles):
        """Return (activations, renewals) for a list of vehicles, filtered by year."""
        acts = rens = 0
        for v in vehicles:
            if not in_year(v.qr_code_generated_at):
                continue
            delta = 0
            if v.created_at and v.qr_code_generated_at:
                delta = (ensure_comoros(v.qr_code_generated_at) -
                         ensure_comoros(v.created_at)).total_seconds()
            if delta < THREE_DAYS:
                acts += 1
            else:
                rens += 1
        return acts, rens

    # Revenue: from recorded QRCodePayment rows, filtered by year
    qr_query = QRCodePayment.query.filter_by(status='paid')
    if year:
        all_qr = [q for q in qr_query.all()
                  if in_year(q.created_at)]
    else:
        all_qr = qr_query.all()

    def isle_stats(vehicles):
        """Build stats dict for a list of vehicles.
        When a year is active, only vehicles with qr_code_generated_at in that
        year are counted for every metric.  When no year filter, all vehicles
        are shown with their current state.
        """
        if year:
            scope = [v for v in vehicles if in_year(v.qr_code_generated_at)]
        else:
            scope = vehicles
        active   = sum(1 for v in scope if v.status == 'active')
        qr_valid = sum(1 for v in scope if v.qr_code_expiry and not v.is_qr_code_expired())
        qr_exp   = sum(1 for v in scope if v.qr_code_expiry and v.is_qr_code_expired())
        acts, rens = count_qr_ops(vehicles)   # already filters by in_year internally
        v_ids   = {v.id for v in scope}
        i_qr    = [q for q in all_qr if q.vehicle_id in v_ids]
        revenue = sum(q.amount for q in i_qr)
        return {
            'vehicles': len(scope), 'active': active,
            'qr_valid': qr_valid, 'qr_expired': qr_exp,
            'activations': acts, 'renewals': rens, 'revenue': round(revenue, 2),
        }

    result = {}
    totals = {'vehicles': 0, 'active': 0, 'qr_valid': 0, 'qr_expired': 0,
              'activations': 0, 'renewals': 0, 'revenue': 0.0}

    for island in ISLANDS:
        ivehicles = [v for v in all_vehicles if (v.owner_island or '') == island]
        result[island] = isle_stats(ivehicles)
        for k in totals:
            totals[k] += result[island][k]

    other = [v for v in all_vehicles if (v.owner_island or '') not in ISLANDS]
    result['Autre'] = isle_stats(other)

    grand = {k: totals[k] + result['Autre'][k] for k in totals}
    return {'islands': result, 'totals': grand, 'year': year}


@smart_tech_bp.route('/stats-iles')
@st_admin_or_secretaire_required
def stats_iles_page():
    from app.timezone_utils import now_comoros
    current_year = now_comoros().year
    act_price = SmartTechSetting.get('qr_activation_price', 5000)
    ren_price = SmartTechSetting.get('qr_renewal_price', 3000)
    return render_template('smart_tech_stats_iles.html',
                           current_year=current_year,
                           activation_price=int(act_price),
                           renewal_price=int(ren_price))


@smart_tech_bp.route('/api/stats-iles')
@st_admin_or_secretaire_required
def api_stats_iles():
    year_raw = request.args.get('year', '')
    year = int(year_raw) if year_raw.isdigit() else None
    data = _island_stats(year)
    data['activation_price'] = int(SmartTechSetting.get('qr_activation_price', 5000))
    data['renewal_price']    = int(SmartTechSetting.get('qr_renewal_price', 3000))
    return jsonify(data)


# ── Licences (cartes biométriques) ────────────────────────────────────────────

@smart_tech_bp.route('/licences')
@st_no_secretaire_required
def licences_page():
    pending_count = LicensePrintRequest.query.filter_by(status='pending').count()
    return render_template('smart_tech_licences.html', pending_count=pending_count)


@smart_tech_bp.route('/api/licences/last-update')
@smart_tech_required
def api_licences_last_update():
    """Lightweight change-detection key for print requests."""
    from sqlalchemy import func
    result = _lpr_q().with_entities(
        func.max(LicensePrintRequest.requested_at).label('last_req'),
        func.max(LicensePrintRequest.printed_at).label('last_print'),
        func.count(LicensePrintRequest.id).label('total'),
    ).one()
    last_req   = result.last_req.strftime('%Y-%m-%d %H:%M:%S')   if result.last_req   else ''
    last_print = result.last_print.strftime('%Y-%m-%d %H:%M:%S') if result.last_print else ''
    return jsonify({'key': f'{last_req}|{last_print}|{result.total}'})


@smart_tech_bp.route('/api/licences/requests')
@smart_tech_required
def api_licences_requests():
    """All pending print requests, newest first."""
    reqs = (_lpr_q()
            .filter(LicensePrintRequest.status == 'pending')
            .order_by(LicensePrintRequest.requested_at.asc())
            .all())
    return jsonify([r.to_dict() for r in reqs])


@smart_tech_bp.route('/api/licences/requests/<int:req_id>/validate', methods=['POST'])
@smart_tech_required
def api_licences_request_validate(req_id):
    from app.timezone_utils import now_comoros
    req = LicensePrintRequest.query.get_or_404(req_id)
    if req.status != 'pending':
        return jsonify({'error': 'Cette demande n\'est plus en attente.'}), 409
    req.status     = 'printed'
    req.printed_by = current_user.username
    req.printed_at = now_comoros()
    req.unit_price = float(SmartTechSetting.get('license_print_price', 0))
    db.session.commit()
    return jsonify({'ok': True, 'request': req.to_dict()})


@smart_tech_bp.route('/api/licences/requests/<int:req_id>/cancel', methods=['POST'])
@smart_tech_required
def api_licences_request_cancel(req_id):
    req = LicensePrintRequest.query.get_or_404(req_id)
    if req.status != 'pending':
        return jsonify({'error': 'Cette demande n\'est plus en attente.'}), 409
    req.status = 'cancelled'
    db.session.commit()
    return jsonify({'ok': True})


@smart_tech_bp.route('/api/licences/requests/stats')
@smart_tech_required
def api_licences_requests_stats():
    from datetime import datetime, timedelta
    from app.timezone_utils import now_comoros
    now   = now_comoros()
    today = now.date()
    first_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    pending_count   = _lpr_q().filter(LicensePrintRequest.status == 'pending').count()
    printed_today   = _lpr_q().filter(
        LicensePrintRequest.status == 'printed',
        LicensePrintRequest.printed_at >= datetime.combine(today, datetime.min.time())
    ).count()
    printed_month   = _lpr_q().filter(
        LicensePrintRequest.status == 'printed',
        LicensePrintRequest.printed_at >= first_of_month
    ).count()
    printed_total   = _lpr_q().filter(LicensePrintRequest.status == 'printed').count()
    cancelled_total = _lpr_q().filter(LicensePrintRequest.status == 'cancelled').count()

    return jsonify({
        'pending_count':   pending_count,
        'printed_today':   printed_today,
        'printed_month':   printed_month,
        'printed_total':   printed_total,
        'cancelled_total': cancelled_total,
    })


@smart_tech_bp.route('/api/licences/requests/history')
@smart_tech_required
def api_licences_requests_history():
    """All printed requests, newest first. Supports ?from=dd/mm/yyyy&to=dd/mm/yyyy."""
    from datetime import datetime
    q = _lpr_q().filter(LicensePrintRequest.status == 'printed')
    date_from = request.args.get('from')
    date_to   = request.args.get('to')
    if date_from:
        try:
            q = q.filter(LicensePrintRequest.printed_at >= datetime.strptime(date_from, '%d/%m/%Y'))
        except ValueError:
            pass
    if date_to:
        try:
            from datetime import timedelta
            end = datetime.strptime(date_to, '%d/%m/%Y') + timedelta(days=1)
            q = q.filter(LicensePrintRequest.printed_at < end)
        except ValueError:
            pass
    reqs = q.order_by(LicensePrintRequest.printed_at.desc()).all()
    return jsonify([r.to_dict() for r in reqs])


@smart_tech_bp.route('/api/licences')
@smart_tech_required
def api_licences_list():
    import math
    from app.models import DriverLicense
    page         = request.args.get('page', 1, type=int)
    per_page     = 50
    search       = request.args.get('search', '').strip()
    type_filter  = request.args.get('type_filter', '').strip()
    status_filter = request.args.get('status_filter', '').strip()

    island = _employe_island()
    query = DriverLicense.query
    if island:
        query = query.filter(DriverLicense.holder_island == island)
    if search:
        term  = f'%{search}%'
        query = query.filter(
            db.or_(
                DriverLicense.license_number.ilike(term),
                DriverLicense.holder_name.ilike(term),
                DriverLicense.holder_firstname.ilike(term),
            )
        )
    if type_filter:
        query = query.filter(DriverLicense.type_permis == type_filter)
    if status_filter:
        query = query.filter(DriverLicense.status == status_filter)

    total    = query.count()
    licenses = (query.order_by(DriverLicense.created_at.desc())
                .offset((page - 1) * per_page).limit(per_page).all())
    pages    = max(1, math.ceil(total / per_page))

    return jsonify({
        'licenses': [l.to_dict() for l in licenses],
        'total':    total,
        'pages':    pages,
        'page':     page,
        'per_page': per_page,
    })


@smart_tech_bp.route('/licences/<int:license_id>/card')
@smart_tech_required
def licences_card(license_id):
    import io, base64, qrcode as _qrcode
    from app.models import DriverLicense, LicenseSetting
    from app.timezone_utils import now_comoros as _nc, now_comoros
    from app.routes import parse_category_details

    lic      = DriverLicense.query.get_or_404(license_id)
    settings = LicenseSetting.get()

    # Generate QR inline — avoids the /licenses/<id>/qrcode route which requires police auth
    qr = _qrcode.QRCode(box_size=6, border=2)
    qr.add_data(lic.license_number)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    qr_data_uri = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()

    category_details = parse_category_details(lic)

    from dateutil.relativedelta import relativedelta
    from app.routes import compute_category_expiries
    computed_expiry = None
    if not lic.expiry_date and lic.issue_date:
        if lic.type_permis == 'temporaire':
            computed_expiry = lic.issue_date + relativedelta(months=(settings.temp_validity_months or 12))
        else:
            computed_expiry = lic.issue_date + relativedelta(years=(settings.permanent_validity_years or 10))
    main_expiry = lic.expiry_date or computed_expiry
    computed_cat_expiries = compute_category_expiries(lic, settings, main_expiry)

    return render_template('license_card.html', lic=lic, settings=settings,
                           computed_expiry=computed_expiry, qr_data_uri=qr_data_uri,
                           category_details=category_details,
                           computed_cat_expiries=computed_cat_expiries,
                           now_comoros=now_comoros)


# ── Employés ──────────────────────────────────────────────────────────────────

@smart_tech_bp.route('/employes')
@st_admin_required
def employes_page():
    return render_template('smart_tech_employes.html')


@smart_tech_bp.route('/api/employes', methods=['GET'])
@st_admin_required
def api_employes_list():
    employees = Employee.query.order_by(Employee.last_name, Employee.first_name).all()
    return jsonify([e.to_dict() for e in employees])



@smart_tech_bp.route('/api/employes', methods=['POST'])
@st_admin_required
def api_employe_create():
    import datetime as dt
    data = request.get_json()
    has_account  = bool(data.get('has_account', False))
    username     = (data.get('username') or '').strip()
    password     = (data.get('password') or '').strip()
    account_role = data.get('account_role', 'employe')
    if has_account:
        if not username or not password:
            return jsonify({'error': "Nom d'utilisateur et mot de passe requis pour créer un accès."}), 400
        if SmartTechAccount.query.filter_by(username=username).first():
            return jsonify({'error': "Ce nom d'utilisateur est déjà utilisé."}), 400
    emp = Employee(
        first_name=data['first_name'].strip(),
        last_name=data['last_name'].strip(),
        phone=data.get('phone', '').strip() or None,
        email=data.get('email', '').strip() or None,
        island=data.get('island', '').strip() or None,
        position=data['position'].strip(),
        salary=float(data.get('salary') or 0),
        hire_date=dt.date.fromisoformat(data['hire_date']) if data.get('hire_date') else None,
        status=data.get('status', 'actif'),
        notes=data.get('notes', '').strip() or None,
        created_by=current_user.username,
    )
    db.session.add(emp)
    db.session.flush()
    if has_account:
        acct = SmartTechAccount(username=username, full_name=emp.full_name,
                                employee_id=emp.id, role=account_role)
        acct.set_password(password)
        db.session.add(acct)
    db.session.commit()
    return jsonify(emp.to_dict()), 201


@smart_tech_bp.route('/api/employes/<int:emp_id>', methods=['PUT'])
@st_admin_required
def api_employe_update(emp_id):
    import datetime as dt
    emp = Employee.query.get_or_404(emp_id)
    data = request.get_json()
    emp.first_name = data.get('first_name', emp.first_name).strip()
    emp.last_name  = data.get('last_name',  emp.last_name).strip()
    emp.phone      = data.get('phone', '').strip() or None
    emp.email      = data.get('email', '').strip() or None
    emp.island     = data.get('island', '').strip() or None
    emp.position   = data.get('position', emp.position).strip()
    emp.salary     = float(data.get('salary') or 0)
    emp.hire_date  = dt.date.fromisoformat(data['hire_date']) if data.get('hire_date') else None
    new_status     = data.get('status', emp.status)
    if new_status != emp.status:
        if new_status == 'inactif':
            for sub in Subscription.query.filter_by(employee_id=emp.id, is_active=True).all():
                sub.is_active = False
            if emp.account:
                emp.account.is_active = False
        elif new_status == 'actif':
            for sub in Subscription.query.filter_by(employee_id=emp.id, is_active=False).all():
                sub.is_active = True
            if emp.account:
                emp.account.is_active = True
    emp.status     = new_status
    emp.notes      = data.get('notes', '').strip() or None

    # ── Account management ──
    has_account    = bool(data.get('has_account', False))
    username       = (data.get('username') or '').strip()
    password       = (data.get('password') or '').strip()
    account_active = bool(data.get('account_active', True))
    account_role   = data.get('account_role', 'employe')
    if has_account:
        if emp.account:
            # Update existing account
            if username and username != emp.account.username:
                if SmartTechAccount.query.filter(SmartTechAccount.username == username, SmartTechAccount.id != emp.account.id).first():
                    return jsonify({'error': "Ce nom d'utilisateur est déjà utilisé."}), 400
                emp.account.username = username
            if password:
                emp.account.set_password(password)
            emp.account.is_active  = account_active
            emp.account.full_name  = emp.full_name
            emp.account.role       = account_role
        else:
            # Create new account
            if not username or not password:
                return jsonify({'error': "Nom d'utilisateur et mot de passe requis pour créer un accès."}), 400
            if SmartTechAccount.query.filter_by(username=username).first():
                return jsonify({'error': "Ce nom d'utilisateur est déjà utilisé."}), 400
            acct = SmartTechAccount(username=username, full_name=emp.full_name,
                                    is_active=account_active, employee_id=emp.id,
                                    role=account_role)
            acct.set_password(password)
            db.session.add(acct)
    else:
        if emp.account:
            db.session.delete(emp.account)

    db.session.commit()
    return jsonify(emp.to_dict())


@smart_tech_bp.route('/api/employes/<int:emp_id>', methods=['DELETE'])
@st_admin_required
def api_employe_delete(emp_id):
    emp = Employee.query.get_or_404(emp_id)
    db.session.delete(emp)
    db.session.commit()
    return jsonify({'ok': True})


# ── Backup / Restore ─────────────────────────────────────────────────────────

_st_restore_tasks = {}  # task_id -> {'status': 'running'|'done'|'error', 'message': ..., 'tables': ...}


@smart_tech_bp.route('/api/backup')
@st_admin_required
def api_st_backup():
    import zipfile, json, io, os
    from sqlalchemy import inspect, text
    from flask import current_app, send_file
    from app.timezone_utils import now_comoros

    timestamp = now_comoros().strftime('%Y%m%d_%H%M%S')
    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    zip_buf = io.BytesIO()

    def default_serial(obj):
        import datetime
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        raise TypeError(f'Type {type(obj)} not serializable')

    with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        if db_uri.startswith('sqlite'):
            db_path = db_uri.replace('sqlite:///', '')
            if os.path.isfile(db_path):
                zf.write(db_path, f'smarttech_backup_{timestamp}.db')

        inspector = inspect(db.engine)
        all_tables = inspector.get_table_names()
        backup_data = {}
        with db.engine.connect() as conn:
            for table in all_tables:
                try:
                    rows = conn.execute(text(f'SELECT * FROM "{table}"')).mappings().all()
                    backup_data[table] = [dict(r) for r in rows]
                except Exception:
                    backup_data[table] = []

        manifest = {
            'created_at': now_comoros().isoformat(),
            'tables': {t: len(backup_data.get(t, [])) for t in all_tables},
        }
        zf.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        json_bytes = json.dumps(backup_data, ensure_ascii=False, indent=2, default=default_serial).encode('utf-8')
        zf.writestr(f'smarttech_backup_{timestamp}.json', json_bytes)

    zip_buf.seek(0)
    return send_file(
        zip_buf,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'smarttech_backup_{timestamp}.zip'
    )


@smart_tech_bp.route('/api/restore', methods=['POST'])
@st_admin_required
def api_st_restore():
    import zipfile, json, uuid, threading, io
    from flask import current_app

    f = request.files.get('backup_file')
    if not f:
        return jsonify({'error': 'Aucun fichier fourni.'}), 400

    try:
        raw_zip = f.read()
        with zipfile.ZipFile(io.BytesIO(raw_zip)) as zf:
            json_names = [n for n in zf.namelist() if n.endswith('.json') and 'backup' in n]
            if not json_names:
                return jsonify({'error': 'Aucun fichier JSON de backup trouvé dans le ZIP.'}), 400
            raw = zf.read(json_names[0])
            backup_data = json.loads(raw.decode('utf-8'))
    except Exception as e:
        return jsonify({'error': f'Fichier ZIP invalide : {e}'}), 400

    task_id = str(uuid.uuid4())
    _st_restore_tasks[task_id] = {'status': 'running', 'message': 'Restauration en cours…'}

    sorted_names = sorted(backup_data.keys())
    app = current_app._get_current_object()

    def do_restore():
        from sqlalchemy import text, inspect

        _COL_RENAMES = {
            'carte_grise_setting': {'signature_image': 'signature_filename'},
        }

        def _adapt_row(table_name, row, actual_cols):
            renames = _COL_RENAMES.get(table_name, {})
            adapted = {}
            for k, v in row.items():
                k2 = renames.get(k, k)
                if k2 in actual_cols:
                    adapted[k2] = v
            return adapted

        def _actual_cols_sqlite(conn, name):
            rows = conn.execute(text(f"PRAGMA table_info(\"{name}\")")).fetchall()
            return {r[1] for r in rows}

        def _actual_cols_pg(conn, name):
            rows = conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = :t"
            ), {'t': name}).fetchall()
            return {r[0] for r in rows}

        with app.app_context():
            try:
                inspector = inspect(db.engine)
                existing_tables = set(inspector.get_table_names())
                tables_to_restore = [n for n in sorted_names if n in backup_data and backup_data[n]]
                stats = {}
                with db.engine.begin() as conn:
                    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
                    if db_uri.startswith('sqlite'):
                        conn.execute(text('PRAGMA foreign_keys = OFF'))
                        for name in reversed(tables_to_restore):
                            if name in existing_tables:
                                conn.execute(text(f'DELETE FROM "{name}"'))
                        for name in tables_to_restore:
                            if name not in existing_tables:
                                continue
                            rows = backup_data[name]
                            if not rows:
                                stats[name] = 0
                                continue
                            actual_cols = _actual_cols_sqlite(conn, name)
                            adapted = [_adapt_row(name, r, actual_cols) for r in rows]
                            adapted = [r for r in adapted if r]
                            if not adapted:
                                stats[name] = 0
                                continue
                            cols = list(adapted[0].keys())
                            placeholders = ', '.join(f':{c}' for c in cols)
                            col_list = ', '.join(f'"{c}"' for c in cols)
                            for row in adapted:
                                conn.execute(text(f'INSERT OR IGNORE INTO "{name}" ({col_list}) VALUES ({placeholders})'), row)
                            stats[name] = len(adapted)
                        conn.execute(text('PRAGMA foreign_keys = ON'))
                    else:
                        for name in reversed(tables_to_restore):
                            if name in existing_tables:
                                conn.execute(text(f'TRUNCATE TABLE "{name}" CASCADE'))
                        for name in tables_to_restore:
                            if name not in existing_tables:
                                continue
                            rows = backup_data[name]
                            if not rows:
                                stats[name] = 0
                                continue
                            actual_cols = _actual_cols_pg(conn, name)
                            adapted = [_adapt_row(name, r, actual_cols) for r in rows]
                            adapted = [r for r in adapted if r]
                            if not adapted:
                                stats[name] = 0
                                continue
                            cols = list(adapted[0].keys())
                            placeholders = ', '.join(f':{c}' for c in cols)
                            col_list = ', '.join(f'"{c}"' for c in cols)
                            for row in adapted:
                                conn.execute(text(f'INSERT INTO "{name}" ({col_list}) VALUES ({placeholders}) ON CONFLICT DO NOTHING'), row)
                            stats[name] = len(adapted)
                        # Reset sequences so new inserts don't conflict with restored IDs
                        for name in tables_to_restore:
                            if name not in existing_tables:
                                continue
                            try:
                                conn.execute(text(
                                    f"SELECT setval(pg_get_serial_sequence('\"{ name }\"', 'id'), "
                                    f"COALESCE((SELECT MAX(id) FROM \"{name}\"), 0) + 1, false)"
                                ))
                            except Exception:
                                pass
                _st_restore_tasks[task_id] = {'status': 'done', 'message': 'Restauration réussie.', 'tables': stats}
            except Exception as e:
                _st_restore_tasks[task_id] = {'status': 'error', 'message': f'Restauration échouée : {e}'}

    threading.Thread(target=do_restore, daemon=True).start()
    return jsonify({'task_id': task_id})


@smart_tech_bp.route('/api/restore/status/<task_id>', methods=['GET'])
@st_admin_required
def api_st_restore_status(task_id):
    task = _st_restore_tasks.get(task_id)
    if not task:
        return jsonify({'error': 'Tâche inconnue.'}), 404
    return jsonify(task)


# ── Agence Assurance ─────────────────────────────────────────────────────────

@smart_tech_bp.route('/assurance')
@smart_tech_required
def assurance_page():
    return render_template('smart_tech_assurance.html')


# --- Companies ---

@smart_tech_bp.route('/api/assurance/companies', methods=['GET'])
@smart_tech_required
def api_assurance_companies():
    companies = _ins_q().order_by(Insurance.company_name).all()
    return jsonify([c.to_dict() for c in companies])


@smart_tech_bp.route('/api/assurance/companies', methods=['POST'])
@st_admin_required
def api_assurance_company_create():
    data = request.get_json() or {}
    name = data.get('company_name', '').strip()
    if not name:
        return jsonify({'error': "Le nom de la compagnie est requis."}), 400
    if Insurance.query.filter_by(company_name=name).first():
        return jsonify({'error': "Cette compagnie existe déjà."}), 400
    ins = Insurance(
        company_name=name,
        phone=data.get('phone', '').strip() or None,
        island=data.get('island', '').strip() or None,
        address=data.get('address', '').strip() or None,
    )
    db.session.add(ins)
    db.session.commit()
    return jsonify(ins.to_dict()), 201


@smart_tech_bp.route('/api/assurance/companies/<int:ins_id>', methods=['PUT'])
@st_admin_required
def api_assurance_company_update(ins_id):
    ins = Insurance.query.get_or_404(ins_id)
    data = request.get_json() or {}
    if 'company_name' in data:
        name = data['company_name'].strip()
        if not name:
            return jsonify({'error': "Le nom ne peut pas être vide."}), 400
        conflict = Insurance.query.filter_by(company_name=name).first()
        if conflict and conflict.id != ins_id:
            return jsonify({'error': "Ce nom existe déjà."}), 400
        ins.company_name = name
    ins.phone   = data.get('phone',   ins.phone   or '').strip() or None
    ins.island  = data.get('island',  ins.island  or '').strip() or None
    ins.address = data.get('address', ins.address or '').strip() or None
    db.session.commit()
    return jsonify(ins.to_dict())


@smart_tech_bp.route('/api/assurance/companies/<int:ins_id>', methods=['DELETE'])
@st_admin_required
def api_assurance_company_delete(ins_id):
    ins = Insurance.query.get_or_404(ins_id)
    if ins.accounts:
        return jsonify({'error': "Supprimez d'abord les comptes liés à cette compagnie."}), 400
    db.session.delete(ins)
    db.session.commit()
    return jsonify({'ok': True})


# --- Accounts ---

@smart_tech_bp.route('/api/assurance/accounts', methods=['GET'])
@smart_tech_required
def api_assurance_accounts():
    island = _employe_island()
    if island:
        accounts = (InsuranceAccount.query
                    .join(Insurance, InsuranceAccount.insurance_id == Insurance.id)
                    .filter(Insurance.island == island)
                    .order_by(InsuranceAccount.created_at.desc())
                    .all())
    else:
        accounts = InsuranceAccount.query.order_by(InsuranceAccount.created_at.desc()).all()
    return jsonify([a.to_dict() for a in accounts])


@smart_tech_bp.route('/api/assurance/accounts', methods=['POST'])
@st_admin_required
def api_assurance_account_create():
    from werkzeug.security import generate_password_hash
    data = request.get_json() or {}
    ins_id   = data.get('insurance_id')
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    if not ins_id or not username or not password:
        return jsonify({'error': "Compagnie, nom d'utilisateur et mot de passe requis."}), 400
    if not Insurance.query.get(ins_id):
        return jsonify({'error': "Compagnie introuvable."}), 404
    if InsuranceAccount.query.filter_by(username=username).first():
        return jsonify({'error': "Ce nom d'utilisateur est déjà utilisé."}), 400
    acc = InsuranceAccount(
        insurance_id=ins_id,
        username=username,
        contact_person=data.get('contact_person', '').strip() or None,
        contact_email=data.get('contact_email', '').strip() or None,
        contact_phone=data.get('contact_phone', '').strip() or None,
        is_active=bool(data.get('is_active', True)),
    )
    acc.set_password(password)
    db.session.add(acc)
    db.session.commit()
    return jsonify(acc.to_dict()), 201


@smart_tech_bp.route('/api/assurance/accounts/<int:acc_id>', methods=['PUT'])
@st_admin_required
def api_assurance_account_update(acc_id):
    acc = InsuranceAccount.query.get_or_404(acc_id)
    data = request.get_json() or {}
    if 'insurance_id' in data:
        if not Insurance.query.get(data['insurance_id']):
            return jsonify({'error': "Compagnie introuvable."}), 404
        acc.insurance_id = data['insurance_id']
    if 'username' in data:
        uname = data['username'].strip()
        if not uname:
            return jsonify({'error': "Le nom d'utilisateur ne peut pas être vide."}), 400
        conflict = InsuranceAccount.query.filter_by(username=uname).first()
        if conflict and conflict.id != acc_id:
            return jsonify({'error': "Ce nom d'utilisateur est déjà utilisé."}), 400
        acc.username = uname
    if data.get('password', '').strip():
        acc.set_password(data['password'].strip())
    acc.contact_person = data.get('contact_person', acc.contact_person or '').strip() or None
    acc.contact_email  = data.get('contact_email',  acc.contact_email  or '').strip() or None
    acc.contact_phone  = data.get('contact_phone',  acc.contact_phone  or '').strip() or None
    if 'is_active' in data:
        acc.is_active = bool(data['is_active'])
    db.session.commit()
    return jsonify(acc.to_dict())


@smart_tech_bp.route('/api/assurance/accounts/<int:acc_id>', methods=['DELETE'])
@st_admin_required
def api_assurance_account_delete(acc_id):
    acc = InsuranceAccount.query.get_or_404(acc_id)
    db.session.delete(acc)
    db.session.commit()
    return jsonify({'ok': True})


# --- Movements ---

@smart_tech_bp.route('/api/assurance/movements')
@smart_tech_required
def api_assurance_movements():
    from datetime import datetime, timedelta
    from app.timezone_utils import now_comoros, COMOROS_TZ

    import re, calendar as _cal
    period = request.args.get('period', 'month')
    now = now_comoros()
    since = until = None

    if re.match(r'^\d{4}-\d{2}$', period):
        year, month = map(int, period.split('-'))
        last_day = _cal.monthrange(year, month)[1]
        since = datetime(year, month, 1, 0, 0, 0, tzinfo=COMOROS_TZ)
        until = datetime(year, month, last_day, 23, 59, 59, tzinfo=COMOROS_TZ)
    elif period == 'year':
        since = datetime(now.year, 1, 1, 0, 0, 0, tzinfo=COMOROS_TZ)
    # 'all' → since/until remain None

    commission_rate = int(SmartTechSetting.get('insurance_commission', 0))
    companies = _ins_q().order_by(Insurance.company_name).all()
    result = []

    for ins in companies:
        account_ids = [acc.id for acc in ins.accounts]
        if account_ids:
            assignments = VehicleInsuranceAssignment.query.filter(
                VehicleInsuranceAssignment.insurance_account_id.in_(account_ids)
            ).all()
            vehicle_ids = list({a.vehicle_id for a in assignments})
        else:
            vehicle_ids = []

        if vehicle_ids:
            qr_q = QRCodePayment.query.filter(
                QRCodePayment.vehicle_id.in_(vehicle_ids),
                QRCodePayment.status == 'paid'
            )
            if since:
                qr_q = qr_q.filter(QRCodePayment.paid_at >= since)
            if until:
                qr_q = qr_q.filter(QRCodePayment.paid_at <= until)
            payments = qr_q.all()
            activations = sum(1 for p in payments if p.payment_type == 'activation')
            renewals    = sum(1 for p in payments if p.payment_type == 'renewal')
            vehicles    = Vehicle.query.filter(Vehicle.id.in_(vehicle_ids)).all()
            active      = sum(1 for v in vehicles if v.status == 'active')
            total       = len(vehicles)
        else:
            activations = renewals = active = total = 0

        is_month = re.match(r'^\d{4}-\d{2}$', period)
        confirmed = False
        confirmed_at = None
        confirmed_by = None
        if is_month:
            rval = SmartTechSetting.get('commission_received_%s_%s' % (ins.id, period), '')
            if rval and rval != '0':
                confirmed = True
                parts = str(rval).split('|', 1)
                confirmed_at = parts[0]
                confirmed_by = parts[1] if len(parts) > 1 else None

        result.append({
            'insurance_id':    ins.id,
            'company_name':    ins.company_name,
            'island':          ins.island,
            'activations':     activations,
            'renewals':        renewals,
            'active_vehicles': active,
            'total_vehicles':  total,
            'commission':      (activations + renewals) * commission_rate,
            'confirmed':       confirmed,
            'confirmed_at':    confirmed_at,
            'confirmed_by':    confirmed_by,
        })

    return jsonify(result)


@smart_tech_bp.route('/api/assurance/commission-received', methods=['POST'])
@st_admin_required
def api_commission_received_toggle():
    import re as _re
    data = request.get_json(silent=True) or {}
    period = data.get('period', '')
    insurance_id = data.get('insurance_id')
    if not _re.match(r'^\d{4}-\d{2}$', period) or not insurance_id:
        return jsonify({'error': 'Invalid period or insurance_id'}), 400
    key = 'commission_received_%s_%s' % (insurance_id, period)
    current = SmartTechSetting.get(key, '')
    name = getattr(current_user, 'full_name', None) or getattr(current_user, 'username', '') or ''
    if current and current != '0':
        parts = str(current).split('|', 1)
        orig_ts = parts[0]
        if len(parts) == 1:
            # Old format without name — backfill with current user
            SmartTechSetting.set(key, f'{orig_ts}|{name}')
            return jsonify({'confirmed': True, 'confirmed_at': orig_ts, 'confirmed_by': name})
        return jsonify({'confirmed': True, 'confirmed_at': orig_ts, 'confirmed_by': parts[1]})
    from app.timezone_utils import now_comoros
    ts = now_comoros().strftime('%Y-%m-%dT%H:%M:%S')
    SmartTechSetting.set(key, f'{ts}|{name}')
    return jsonify({'confirmed': True, 'confirmed_at': ts, 'confirmed_by': name})


@smart_tech_bp.route('/rapport-journalier')
@smart_tech_required
def rapport_journalier_page():
    from app.timezone_utils import now_comoros
    today = now_comoros().date()
    return render_template(
        'smart_tech_rapport_journalier.html',
        today=today.isoformat(),
    )


@smart_tech_bp.route('/api/rapport-journalier')
@smart_tech_required
def api_rapport_journalier():
    from app.timezone_utils import now_comoros
    from datetime import date as date_type, datetime, timedelta
    from sqlalchemy import func

    day_str = request.args.get('date', '')
    try:
        day = date_type.fromisoformat(day_str)
    except (ValueError, TypeError):
        day = now_comoros().date()

    day_start = datetime(day.year, day.month, day.day, 0, 0, 0)
    day_end   = datetime(day.year, day.month, day.day, 23, 59, 59)

    q = QRCodePayment.query.filter(
        QRCodePayment.status == 'paid',
        QRCodePayment.paid_at >= day_start,
        QRCodePayment.paid_at <= day_end,
    )

    emp_island = _employe_island()
    if emp_island:
        # employe: always restricted to their own island
        island_vehicle_ids = [v.id for v in Vehicle.query.filter_by(owner_island=emp_island).all()]
        q = q.filter(QRCodePayment.vehicle_id.in_(island_vehicle_ids))
    else:
        # admin/secretaire: optional island filter from query param
        requested_island = request.args.get('island', '').strip()
        if requested_island:
            island_vehicle_ids = [v.id for v in Vehicle.query.filter_by(owner_island=requested_island).all()]
            q = q.filter(QRCodePayment.vehicle_id.in_(island_vehicle_ids))

    payments = q.order_by(QRCodePayment.paid_at.asc()).all()

    activations = [p for p in payments if p.payment_type == 'activation']
    renewals    = [p for p in payments if p.payment_type == 'renewal']
    total_amount = sum(p.amount for p in payments)

    act_price = float(SmartTechSetting.get('qr_activation_price', 5000))
    ren_price = float(SmartTechSetting.get('qr_renewal_price', 3000))

    rows = []
    for p in payments:
        v = p.vehicle
        rows.append({
            'id':            p.id,
            'vehicle_id':    p.vehicle_id,
            'license_plate': v.license_plate if v else '—',
            'owner_name':    v.owner_name if v else '—',
            'owner_island':  v.owner_island if v else '—',
            'payment_type':  p.payment_type,
            'amount':        float(p.amount),
            'paid_at':       p.paid_at.strftime('%H:%M') if p.paid_at else '—',
            'recorded_by':   p.recorded_by or '—',
        })

    return jsonify({
        'date':            day.strftime('%d/%m/%Y'),
        'date_iso':        day.isoformat(),
        'nb_total':        len(payments),
        'nb_activations':  len(activations),
        'nb_renewals':     len(renewals),
        'total_amount':    total_amount,
        'act_price':       act_price,
        'ren_price':       ren_price,
        'rows':            rows,
    })
