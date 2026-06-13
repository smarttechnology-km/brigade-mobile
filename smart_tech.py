from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response
from flask_login import login_user, logout_user, login_required, current_user
from functools import wraps
from app.models import SmartTechAccount, QRCodePayment, Vehicle, Subscription, Expense, Employee, SmartTechSetting
from app import db

smart_tech_bp = Blueprint('smart_tech', __name__, url_prefix='/smart-tech')


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
    activation_price = SmartTechSetting.get('qr_activation_price', 5000)
    renewal_price    = SmartTechSetting.get('qr_renewal_price', 3000)
    return render_template('smart_tech_parametres.html',
                           activation_price=int(activation_price),
                           renewal_price=int(renewal_price),
                           app_name=SmartTechSetting.get('app_name', 'SmartTech Brigade'),
                           app_island=SmartTechSetting.get('app_island', 'Nationale'),
                           app_contact=SmartTechSetting.get('app_contact', ''),
                           sim_new_vehicles=int(SmartTechSetting.get('sim_new_vehicles', 500)),
                           sim_existing=int(SmartTechSetting.get('sim_existing', 10000)),
                           sim_renewal_rate=float(SmartTechSetting.get('sim_renewal_rate', 10)),
                           sim_rate_growth=float(SmartTechSetting.get('sim_rate_growth', 5)),
                           sim_churn_rate=float(SmartTechSetting.get('sim_churn_rate', 2)),
                           sim_annual_expenses=int(SmartTechSetting.get('sim_annual_expenses', 0)),
                           sim_years=int(SmartTechSetting.get('sim_years', 5)))


@smart_tech_bp.route('/api/parametres', methods=['GET'])
@st_admin_required
def api_parametres_get():
    return jsonify({
        'qr_activation_price': SmartTechSetting.get('qr_activation_price', 5000),
        'qr_renewal_price':    SmartTechSetting.get('qr_renewal_price', 3000),
        'app_name':    SmartTechSetting.get('app_name', 'SmartTech Brigade'),
        'app_island':  SmartTechSetting.get('app_island', 'Nationale'),
        'app_contact': SmartTechSetting.get('app_contact', ''),
    })


_VALID_ISLANDS = {'Nationale', 'Grande Comore', 'Anjouan', 'Moheli'}

@smart_tech_bp.route('/api/parametres', methods=['PUT'])
@st_admin_required
def api_parametres_update():
    data = request.get_json(silent=True) or {}
    errors = []
    for key in ('qr_activation_price', 'qr_renewal_price'):
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
    if 'app_name' in data:
        name = str(data['app_name']).strip()[:120]
        if name:
            SmartTechSetting.set('app_name', name)
    if 'app_island' in data:
        isle = str(data['app_island']).strip()
        if isle in _VALID_ISLANDS:
            SmartTechSetting.set('app_island', isle)
    if 'app_contact' in data:
        SmartTechSetting.set('app_contact', str(data['app_contact']).strip()[:60])
    _SIM_KEYS = {
        'sim_new_vehicles': (int, 0, None),
        'sim_existing':     (int, 0, None),
        'sim_renewal_rate': (float, 0, 100),
        'sim_rate_growth':  (float, 0, 50),
        'sim_churn_rate':   (float, 0, 50),
        'sim_annual_expenses': (int, 0, None),
        'sim_years':        (int, 1, 20),
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
        'app_name':    SmartTechSetting.get('app_name', 'SmartTech Brigade'),
        'app_island':  SmartTechSetting.get('app_island', 'Nationale'),
        'app_contact': SmartTechSetting.get('app_contact', ''),
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
    total_vehicles = Vehicle.query.count()

    # QR actif: qr_code_expiry dans le futur
    qr_active = Vehicle.query.filter(
        Vehicle.qr_code_expiry.isnot(None),
        Vehicle.qr_code_expiry > now
    ).count()

    # QR inactif: qr_code_expiry expiré (avaient un QR mais il a expiré)
    qr_inactive = Vehicle.query.filter(
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
        Vehicle.query
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
    total = Vehicle.query.count()
    active = Vehicle.query.filter(
        Vehicle.qr_code_expiry.isnot(None),
        Vehicle.qr_code_expiry > now
    ).count()
    inactive = Vehicle.query.filter(
        Vehicle.qr_code_expiry.isnot(None),
        Vehicle.qr_code_expiry <= now
    ).count()
    never = Vehicle.query.filter(Vehicle.qr_code_expiry.is_(None)).count()
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

    query = Vehicle.query
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


@smart_tech_bp.route('/api/last-update')
@smart_tech_required
def api_last_update():
    """Lightweight change-detection endpoint — returns a key string only."""
    from sqlalchemy import func
    result = db.session.query(
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
    total    = Vehicle.query.count()
    active   = Vehicle.query.filter(Vehicle.qr_code_expiry.isnot(None), Vehicle.qr_code_expiry > now).count()
    inactive = Vehicle.query.filter(Vehicle.qr_code_expiry.isnot(None), Vehicle.qr_code_expiry <= now).count()

    all_vehicles = (
        Vehicle.query
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
        for p in QRCodePayment.query.filter_by(status='paid').all()
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


# ── Subscriptions ──────────────────────────────────────────────────────────────

@smart_tech_bp.route('/subscriptions')
@smart_tech_required
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
@smart_tech_required
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

    # QR payments — compare aware datetimes
    qr_all = QRCodePayment.query.filter(
        QRCodePayment.status == 'paid'
    ).all()
    qr_in  = [q for q in qr_all
              if q.created_at and start_dt <= ensure_comoros(q.created_at) <= end_dt]
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

    act_total   = sum(q.amount for q in activations)
    ren_total   = sum(q.amount for q in renewals)
    man_total   = sum(s.amount for s in manual_paid)
    auto_total  = sum(s.amount for s in auto_due)
    sub_total   = man_total + auto_total
    exp_total   = sum(e.amount for e in expenses)
    revenue     = act_total + ren_total
    net         = revenue - sub_total - exp_total

    return {
        'period_type':    period_type,
        'period_value':   period_value,
        'start_dt':       start_dt,
        'end_dt':         end_dt,
        'activations':    activations,
        'renewals':       renewals,
        'active_subs':    active_subs,
        'manual_paid_ids': manual_paid_ids,
        'auto_due_ids':    auto_due_ids,
        'manual_paid':    manual_paid,
        'auto_due':       auto_due,
        'expenses':       expenses,
        'act_total':      act_total,
        'ren_total':      ren_total,
        'man_total':      man_total,
        'auto_total':     auto_total,
        'sub_total':      sub_total,
        'exp_total':      exp_total,
        'revenue':        revenue,
        'net':            net,
    }


@smart_tech_bp.route('/rapport')
@st_admin_required
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
@st_admin_required
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
        'subscriptions':     [fmt_sub(s) for s in r['active_subs']],
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
@st_admin_required
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
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
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
    story.append(Paragraph('Smart Technology', title_style))
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
    summary_data = [
        [ph('Catégorie'), ph('Quantité'), ph('Montant')],
        [p('Activations QR Code'),       p(str(len(r['activations']))),  p(fmt(r['act_total']))],
        [p('Renouvellements QR Code'),   p(str(len(r['renewals']))),     p(fmt(r['ren_total']))],
        [p('Abonnements automatiques'),  p(str(len(auto_subs))),         p(fmt(sum(s.amount for s in auto_subs)))],
        [p('Abonnements manuels'),       p(str(len(manuel_subs))),       p(fmt(sum(s.amount for s in manuel_subs)))],
        [p('Dépenses'),                  p(str(len(r['expenses']))),     p(fmt(r['exp_total']))],
    ]
    summary_data += [
        [p('Revenus totaux (Activations + Renouvellements)'), p(''), p(fmt(r['revenue']))],
        [p('Charges totales (Abonnements + Dépenses)'),       p(''), p(fmt(r['sub_total'] + r['exp_total']))],
        [p('Résultat net'),                                    p(''), p(fmt(r['net']))],
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

    story.append(Spacer(1, 1*cm))
    story.append(HRFlowable(width=W, thickness=0.5, color=colors.HexColor('#ccc')))
    story.append(Paragraph('Smart Technology — Rapport généré automatiquement', small))

    doc.build(story)
    return buf.getvalue()


# ── Island Statistics ────────────────────────────────────────────────────────

ISLANDS = ['Grande Comores', 'Anjouan', 'Moheli']


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
@st_admin_required
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
@st_admin_required
def api_stats_iles():
    year_raw = request.args.get('year', '')
    year = int(year_raw) if year_raw.isdigit() else None
    data = _island_stats(year)
    data['activation_price'] = int(SmartTechSetting.get('qr_activation_price', 5000))
    data['renewal_price']    = int(SmartTechSetting.get('qr_renewal_price', 3000))
    return jsonify(data)


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
