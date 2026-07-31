from flask import Blueprint, request, jsonify, current_app, url_for, render_template, send_file
from app import db
from app.models import Payment, Fine, Vehicle, VehicleHistory, VignetteSetting, QRCodePayment, SmartTechSetting, HuriDestinationSetting, FineType
from datetime import datetime, timedelta
import io
import json
import hashlib
import hmac
import qrcode
from app.timezone_utils import now_comoros, ensure_comoros

mobile_pay_bp = Blueprint('mobile_pay', __name__, url_prefix='/pay')


def _is_vehicle_active(vehicle):
    return bool(vehicle and (vehicle.status or 'active') == 'active')


def _parse_vignette_datetime(value):
    if not value:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except Exception:
            return None
    return ensure_comoros(value)


def _effective_days_late(vignette_expiry, now=None):
    """Days late for penalty calculation, ignoring skipped renewal years.

    Rule: penalties only count from the most recent March 31 deadline that has
    already passed — never from an older expiry date. This way a vehicle that
    missed a full year pays the same penalty as one that just missed this year's
    deadline, because the skipped year is written off.

    Returns 0 when we are still before the current year's March 31 (i.e. the
    owner is in the early-renewal window and no new deadline has passed yet).
    """
    if now is None:
        now = now_comoros()
    if not vignette_expiry or vignette_expiry >= now:
        return 0

    from datetime import date as _date
    current_year = now.year
    march_31_this_year = ensure_comoros(datetime(current_year, 3, 31, 23, 59, 59))

    if now.date() > _date(current_year, 3, 31):
        # Past this year's deadline: cap the reference to this year's March 31
        # so older missed years do not inflate the penalty.
        effective_ref = max(vignette_expiry, march_31_this_year)
    else:
        # Still before this year's March 31 (early-renewal window).
        # The previous year's penalties are forgiven; a new cycle is starting.
        return 0

    return max(0, (now - effective_ref).days)


def _get_renewal_opening_datetime():
    """Return the configured renewal opening date as a timezone-aware Comoros datetime, or None."""
    try:
        setting = VignetteSetting.query.first()
        if setting and setting.renewal_opening_date:
            return ensure_comoros(datetime.combine(setting.renewal_opening_date, datetime.min.time()))
    except Exception:
        pass
    return None


def _calculate_unpaid_fines_amount(vehicle):
    if not vehicle:
        return 0.0

    try:
        unpaid_fines = vehicle.fines.filter_by(paid=False).all()
        return float(sum(float(f.amount or 0.0) for f in unpaid_fines))
    except Exception:
        return 0.0


def _get_vignette_rate_breakdown(vehicle):
    if not vehicle:
        return None

    try:
        from app.models import VignetteRate

        vehicle_age = None
        if vehicle.year:
            try:
                current_year = datetime.utcnow().year
                vehicle_age = current_year - int(vehicle.year)
            except Exception:
                vehicle_age = None

        query = VignetteRate.query.filter(VignetteRate.is_active == True)

        if vehicle.fiscal_class:
            query = query.filter((VignetteRate.fiscal_class == vehicle.fiscal_class) | (VignetteRate.fiscal_class.is_(None)))
        else:
            query = query.filter(VignetteRate.fiscal_class.is_(None))

        if vehicle.cv_class:
            query = query.filter((VignetteRate.cv_class == vehicle.cv_class) | (VignetteRate.cv_class.is_(None)))
        else:
            query = query.filter(VignetteRate.cv_class.is_(None))

        if vehicle.fuel_type:
            query = query.filter((VignetteRate.fuel_type == vehicle.fuel_type) | (VignetteRate.fuel_type.is_(None)))
        else:
            query = query.filter(VignetteRate.fuel_type.is_(None))

        if vehicle_age is not None:
            query = query.filter(
                (VignetteRate.vehicle_age_min.is_(None) | (VignetteRate.vehicle_age_min <= vehicle_age)) &
                (VignetteRate.vehicle_age_max.is_(None) | (VignetteRate.vehicle_age_max >= vehicle_age))
            )
        else:
            query = query.filter(VignetteRate.vehicle_age_min.is_(None), VignetteRate.vehicle_age_max.is_(None))

        rates = query.all()
        if not rates:
            return None

        def specificity_score(rate):
            score = 0
            if rate.fiscal_class is not None:
                score += 10
            if rate.cv_class is not None:
                score += 10
            if rate.fuel_type is not None:
                score += 10
            if rate.vehicle_age_min is not None or rate.vehicle_age_max is not None:
                score += 5
            return score

        rates.sort(key=specificity_score, reverse=True)
        best_rate = rates[0]
        base_amount = float(best_rate.price_kmf) if best_rate.price_kmf else 0.0
        annual_ds_amount = float(best_rate.annual_ds) if getattr(best_rate, 'annual_ds', None) is not None else 1000.0

        return {
            'base_amount': base_amount,
            'annual_ds_amount': annual_ds_amount,
            'total_amount': base_amount + annual_ds_amount,
        }

    except Exception:
        return None


def _calculate_penalty_amount(days_late):
    """
    Calculate penalty amount based on days late using configured penalty rates.
    
    Penalties apply to vehicles that have not renewed their vignette after March 31st (expiration date).
    Aux Comores, les vignettes expirent le 31 mars. Les pénalités ne s'appliquent que si le véhicule 
    ne renouvelle pas sa vignette après cette date.
    
    Args:
        days_late (int): Number of days past vignette expiry date (March 31st)
        
    Returns:
        float: Penalty amount in KMF. Returns 0 if no penalty applies or days_late is 0 or negative.
    """

    try:
        from app.models import PenaltyRate

        penalty_rate = PenaltyRate.query.filter(
            PenaltyRate.is_active == True,
            PenaltyRate.days_late_min <= days_late,
            PenaltyRate.days_late_max >= days_late
        ).first()

        if not penalty_rate:
            return 0.0

        previous_max = 0
        prev_rates = PenaltyRate.query.filter(
            PenaltyRate.is_active == True,
            PenaltyRate.days_late_max < penalty_rate.days_late_min
        ).order_by(PenaltyRate.days_late_max.desc()).first()

        if prev_rates:
            previous_max = prev_rates.days_late_max

        penalty_per_day = float(penalty_rate.penalty_per_day)
        penalty_days = max(0, days_late - previous_max)
        return float(penalty_days * penalty_per_day)

    except Exception:
        return 0.0


def _calculate_vignette_price(vehicle):
    breakdown = _get_vignette_rate_breakdown(vehicle)
    return float(breakdown['total_amount']) if breakdown else 0.0


def get_vignette_expiry_date(reference_date=None):
    """
    Calculate vignette expiry date: March 31st of the current or next year.
    
    Aux Comores, les vignettes expirent le 31 mars de chaque année.
    - Si la date de référence est avant ou égale au 31 mars, la vignette expire le 31 mars de l'année courante
    - Si la date de référence est après le 31 mars, la vignette expire le 31 mars de l'année prochaine
    
    Args:
        reference_date: Date de référence (par défaut: maintenant en heure Comores)
    
    Returns:
        datetime: Date d'expiration le 31 mars (23:59:59)
    """
    if reference_date is None:
        reference_date = now_comoros()
    else:
        reference_date = ensure_comoros(reference_date)
    
    current_year = reference_date.year
    march_31_current_year = ensure_comoros(datetime(current_year, 3, 31, 23, 59, 59))
    
    # Si nous sommes avant ou le 31 mars, expiration le 31 mars de cette année
    if reference_date.date() <= march_31_current_year.date():
        return march_31_current_year
    else:
        # Sinon, expiration le 31 mars de l'année prochaine
        return ensure_comoros(datetime(current_year + 1, 3, 31, 23, 59, 59))


@mobile_pay_bp.route('/lookup', methods=['GET'])
def lookup():
    """Public lookup endpoint: ?q=<track_token_or_plate>
    Returns outstanding fines for the provided token or plate. (Stubbed)
    """
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'error': 'Missing query parameter q'}), 400

    q_normalized = q.upper().strip()

    # Try track_token first (exact), then exact plate match only — no partial search
    vehicle = Vehicle.query.filter_by(track_token=q).first()
    if not vehicle:
        vehicle = Vehicle.query.filter_by(license_plate=q_normalized).first()

    if not vehicle or vehicle.qr_pending_approval:
        return jsonify({'fines': [], 'vehicle': None})

    # Return unpaid fines only
    raw_fines = vehicle.fines.filter_by(paid=False).order_by(Fine.issued_at.desc()).all()

    # Batch-lookup article info keyed by reason label (avoids N+1)
    reasons = {f.reason for f in raw_fines if f.reason}
    fine_types = FineType.query.filter(FineType.label.in_(reasons)).all() if reasons else []
    article_map = {
        ft.label: {
            'article_code': ft.article.code if ft.article else None,
            'article_description': ft.article.description if ft.article else None,
        }
        for ft in fine_types
    }

    unpaid_fines = []
    for f in raw_fines:
        d = f.to_dict()
        info = article_map.get(f.reason, {})
        d['article_code'] = info.get('article_code')
        d['article_description'] = info.get('article_description')
        unpaid_fines.append(d)

    unpaid_fines_amount = _calculate_unpaid_fines_amount(vehicle)

    now = now_comoros()
    vignette_expiry = _parse_vignette_datetime(vehicle.vignette_expiry)

    renewal_opening = _get_renewal_opening_datetime()
    in_renewal_period = renewal_opening is not None and now >= renewal_opening
    payment_approved = bool(getattr(vehicle, 'vignette_payment_approved', False))
    renewal_needed = bool(
        in_renewal_period
        and vignette_expiry
        and vignette_expiry >= now
        and not payment_approved
    )

    vignette_status = 'no_vignette'
    penalty_amount = 0.0
    if vignette_expiry:
        if vignette_expiry < now:
            vignette_status = 'expired'
            penalty_amount = float(_calculate_penalty_amount(_effective_days_late(vignette_expiry, now)) or 0.0)
        elif vignette_expiry < now + timedelta(days=30):
            vignette_status = 'expiring'
        else:
            vignette_status = 'active'

    vignette_breakdown = _get_vignette_rate_breakdown(vehicle)
    vignette_price = float(vignette_breakdown['base_amount']) if vignette_breakdown else 0.0
    annual_ds_amount = float(vignette_breakdown['annual_ds_amount']) if vignette_breakdown else 0.0
    vignette_total = float(vignette_breakdown['total_amount']) if vignette_breakdown else 0.0
    if renewal_needed and vignette_expiry:
        # Early renewal during the open window: quote the vignette extended by
        # one year from its current expiry (matches the agent approval flow).
        requested_expiry = ensure_comoros(datetime(
            vignette_expiry.year + 1, vignette_expiry.month, vignette_expiry.day, 23, 59, 59
        ))
    else:
        requested_expiry = get_vignette_expiry_date(now)
    renewal_allowed = not (vignette_expiry and vignette_expiry > now) or renewal_needed

    vehicle_payload = vehicle.to_dict()
    vehicle_payload['renewal_needed'] = renewal_needed
    vehicle_payload['renewal_period_open'] = bool(in_renewal_period)

    # Attach whether the vehicle's insurance company has uploaded a maquette
    from app.models import VehicleInsuranceAssignment as _VIA, InsuranceAccount as _InsAcct
    import json as _json
    _assign = _VIA.query.filter_by(vehicle_id=vehicle.id).first()
    _has_tpl = False
    if _assign:
        _acc = _InsAcct.query.get(_assign.insurance_account_id)
        if _acc and _acc.attestation_template:
            try:
                _has_tpl = bool(_json.loads(_acc.attestation_template))
            except Exception:
                pass
    vehicle_payload['has_attestation_template'] = _has_tpl

    qr_expiry = ensure_comoros(vehicle.qr_code_expiry) if vehicle.qr_code_expiry else None
    qr_status = 'none'
    if qr_expiry:
        if qr_expiry < now:
            qr_status = 'expired'
        elif qr_expiry < now + timedelta(days=30):
            qr_status = 'expiring'
        else:
            qr_status = 'active'
    qr_renewal_price = float(SmartTechSetting.get('qr_renewal_price', 3000) or 3000)

    return jsonify({
        'vehicle': vehicle_payload,
        'fines': unpaid_fines,
        'vignette_quote': {
            'status': vignette_status,
            'base_amount': round(vignette_price, 2),
            'annual_ds_amount': round(annual_ds_amount, 2),
            'penalty_amount': round(penalty_amount, 2),
            'fines_amount': round(unpaid_fines_amount, 2),
            'total_amount': round(vignette_total + penalty_amount + unpaid_fines_amount, 2) if renewal_allowed else 0.0,
            'requested_expiry': requested_expiry.isoformat() if requested_expiry else None,
            'is_renewal': bool(vignette_expiry and (vignette_expiry < now or renewal_needed)),
            'renewal_allowed': renewal_allowed,
            'renewal_needed': renewal_needed,
            'renewal_period_open': bool(in_renewal_period),
        },
        'qr_quote': {
            'status': qr_status,
            'price': round(qr_renewal_price, 2),
            'expiry': qr_expiry.isoformat() if qr_expiry else None,
            # QR code renewal is only payable once it has actually expired.
            'renewal_allowed': qr_status == 'expired',
        }
    })


def _build_vignette_payment_payload(vehicle, requested_expiry=None):
    """Build the payment payload and amount for a vignette transaction."""
    now = now_comoros()
    current_expiry = _parse_vignette_datetime(vehicle.vignette_expiry)

    if not requested_expiry:
        requested_expiry = get_vignette_expiry_date(now)
    elif isinstance(requested_expiry, str):
        try:
            requested_expiry = ensure_comoros(datetime.fromisoformat(requested_expiry))
        except Exception:
            requested_expiry = get_vignette_expiry_date(now)

    vignette_breakdown = _get_vignette_rate_breakdown(vehicle)
    vignette_price = float(vignette_breakdown['base_amount']) if vignette_breakdown else 0.0
    annual_ds_amount = float(vignette_breakdown['annual_ds_amount']) if vignette_breakdown else 0.0
    if vignette_price <= 0:
        raise ValueError('Impossible de calculer le montant de la vignette pour ce véhicule.')

    penalty_amount = float(_calculate_penalty_amount(_effective_days_late(current_expiry, now)) or 0.0)

    unpaid_fines = vehicle.fines.filter_by(paid=False).all()
    unpaid_fines_ids = [f.id for f in unpaid_fines]
    unpaid_fines_amount = float(sum(float(f.amount or 0.0) for f in unpaid_fines))

    total_amount = round(vignette_price + annual_ds_amount + penalty_amount + unpaid_fines_amount, 2)
    payload = {
        'type': 'vignette_request',
        'payment_type': 'vignette',
        'vehicle_id': vehicle.id,
        'license_plate': vehicle.license_plate,
        'owner_name': vehicle.owner_name,
        'requested_expiry': requested_expiry.isoformat(),
        'vignette_price': vignette_price,
        'annual_ds_amount': annual_ds_amount,
        'penalty_amount': penalty_amount,
        'fine_ids': unpaid_fines_ids,
        'fines_amount': unpaid_fines_amount,
        'total_amount': total_amount,
    }

    return payload, total_amount, requested_expiry, vignette_price, penalty_amount


@mobile_pay_bp.route('/create', methods=['POST'])
def create_payment():
    """Create a payment session with Huri Money (stub).
    Expects JSON: { "fines": [id, ...], "payer_name": ..., "payer_email": ... }
    Returns a placeholder `checkout_url` until Huri credentials are provided.
    """
    data = request.get_json() or {}
    payment_type = (data.get('payment_type') or 'fines').strip().lower()
    fines_ids = data.get('fines') or []
    payer_name = data.get('payer_name')
    payer_email = data.get('payer_email')

    if payment_type == 'vignette':
        vehicle_id = data.get('vehicle_id')
        if not vehicle_id:
            return jsonify({'error': 'vehicle_id is required for vignette payments'}), 400

        vehicle = Vehicle.query.get(vehicle_id)
        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404

        if not _is_vehicle_active(vehicle):
            return jsonify({'error': 'Ce véhicule est inactif. Activez-le avant de payer la vignette.'}), 400

        current_expiry = _parse_vignette_datetime(vehicle.vignette_expiry)
        if current_expiry and current_expiry > now_comoros():
            return jsonify({
                'error': 'Ce véhicule a déjà une vignette active. Le renouvellement est possible après expiration.',
            }), 400

        try:
            payload, total, requested_expiry, vignette_price, penalty_amount = _build_vignette_payment_payload(
                vehicle,
                data.get('requested_expiry')
            )
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400

        payment = Payment(
            amount=total,
            currency='KMF',
            status='pending',
            license_plate=vehicle.license_plate,
            owner_name=vehicle.owner_name,
            payer_name=payer_name,
            payer_email=payer_email,
            destination_phone=HuriDestinationSetting.get().phone_for('vignette'),
            fines=json.dumps(payload)
        )
        db.session.add(payment)
        db.session.commit()

        checkout_url = url_for('mobile_pay.checkout_page', payment_id=payment.id, _external=True)

        return jsonify({
            'payment_id': payment.id,
            'checkout_url': checkout_url,
            'amount': round(total, 2),
            'currency': 'KMF',
            'status': 'pending',
            'payment_type': 'vignette',
            'vehicle': vehicle.to_dict(),
            'quote': {
                'base_amount': round(vignette_price, 2),
                'annual_ds_amount': round(payload.get('annual_ds_amount') or 0.0, 2),
                'penalty_amount': round(penalty_amount, 2),
                'fines_amount': round(float(payload.get('fines_amount') or 0.0), 2),
                'total_amount': round(total, 2),
                'requested_expiry': requested_expiry.isoformat() if requested_expiry else None,
            }
        })

    if payment_type == 'qr_renewal':
        vehicle_id = data.get('vehicle_id')
        if not vehicle_id:
            return jsonify({'error': 'vehicle_id is required for QR code renewal'}), 400

        vehicle = Vehicle.query.get(vehicle_id)
        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404

        qr_expiry = ensure_comoros(vehicle.qr_code_expiry) if vehicle.qr_code_expiry else None
        if qr_expiry and qr_expiry > now_comoros():
            return jsonify({'error': 'Le code QR de ce véhicule est encore valide.'}), 400

        amount = float(SmartTechSetting.get('qr_renewal_price', 3000) or 3000)
        payload = {
            'type': 'qr_renewal_request',
            'payment_type': 'qr_renewal',
            'vehicle_id': vehicle.id,
            'license_plate': vehicle.license_plate,
            'owner_name': vehicle.owner_name,
            'amount': amount,
        }

        payment = Payment(
            amount=amount,
            currency='KMF',
            status='pending',
            license_plate=vehicle.license_plate,
            owner_name=vehicle.owner_name,
            payer_name=payer_name,
            payer_email=payer_email,
            destination_phone=HuriDestinationSetting.get().phone_for('qr_renewal'),
            fines=json.dumps(payload)
        )
        db.session.add(payment)
        db.session.commit()

        checkout_url = url_for('mobile_pay.checkout_page', payment_id=payment.id, _external=True)

        return jsonify({
            'payment_id': payment.id,
            'checkout_url': checkout_url,
            'amount': round(amount, 2),
            'currency': 'KMF',
            'status': 'pending',
            'payment_type': 'qr_renewal',
            'vehicle': vehicle.to_dict(),
        })

    if not fines_ids:
        return jsonify({'error': 'No fines specified'}), 400

    # Compute total amount
    fines = Fine.query.filter(Fine.id.in_(fines_ids)).all()
    if not fines:
        return jsonify({'error': 'Fines not found'}), 404

    # Get license plate and owner name from the first fine's vehicle
    vehicle = fines[0].vehicle if fines else None
    if not vehicle:
        return jsonify({'error': 'Vehicle not found for fines'}), 400

    if not _is_vehicle_active(vehicle):
        return jsonify({'error': 'Ce véhicule est inactif. Activez-le avant de payer les amendes.'}), 400
    
    license_plate = vehicle.license_plate
    owner_name = vehicle.owner_name

    total = sum([f.amount for f in fines])

    payment = Payment(
        amount=total,
        currency='KMF',
        status='pending',
        license_plate=license_plate,
        owner_name=owner_name,
        payer_name=payer_name,
        payer_email=payer_email,
        destination_phone=HuriDestinationSetting.get().phone_for('fine'),
        fines=str(fines_ids)
    )
    db.session.add(payment)
    db.session.commit()

    # Checkout URL pointing to the simulated payment page (HTML)
    checkout_url = url_for('mobile_pay.checkout_page', payment_id=payment.id, _external=True)

    return jsonify({
        'payment_id': payment.id, 
        'checkout_url': checkout_url,
        'amount': round(float(total), 2),
        'currency': 'KMF',
        'status': 'pending'
    })


@mobile_pay_bp.route('/check-balance', methods=['POST'])
def check_balance():
    """Check if Huri Money account has sufficient balance for payment.

    Expected JSON:
    {
        "phone_number": "3123456",
        "required_amount": 13000  // in KMF
    }
    """
    data = request.get_json() or {}
    phone_number = data.get('phone_number')
    required_amount = data.get('required_amount')

    if not phone_number or required_amount is None:
        return jsonify({'error': 'Missing phone_number or required_amount'}), 400

    # Simulated balances in KMF
    simulated_balances = {
        '3111111': 100,    # Insufficient (100 KMF)
        '3122222': 20000,  # Sufficient (20,000 KMF) - test number
        '3133333': 50,     # Insufficient (50 KMF)
    }

    # Default: 20,000 KMF
    account_balance = simulated_balances.get(phone_number, 20000)
    has_sufficient_balance = account_balance >= required_amount

    print(f'💰 Balance Check: phone={phone_number}, required={required_amount} KMF, balance={account_balance} KMF, ok={has_sufficient_balance}')

    if has_sufficient_balance:
        return jsonify({
            'status': 'connected',
            'has_sufficient_balance': True,
            'balance': account_balance,
            'message': 'Balance is sufficient'
        }), 200
    else:
        return jsonify({
            'status': 'insufficient_balance',
            'has_sufficient_balance': False,
            'balance': account_balance,
            'required': required_amount,
            'message': f'Insufficient balance. Required: {required_amount} KMF, Available: {account_balance} KMF'
        }), 200


@mobile_pay_bp.route('/webhook', methods=['POST'])
def webhook():
    """Webhook receiver for Huri Money. This is a stub that accepts a POST and
    marks payment as paid if `payment_id` and `status=paid` are present in payload.
    Proper verification will be added once Huri webhook secret is provided.
    """
    data = request.get_json() or {}
    huri_id = data.get('huri_payment_id')
    status = data.get('status')
    local_payment_id = data.get('local_payment_id')
    phone_number = data.get('phone_number')

    if not local_payment_id:
        return jsonify({'error': 'Missing local_payment_id'}), 400

    # Try to parse local_payment_id as integer (normal Payment ID)
    try:
        payment_id_int = int(local_payment_id)
        payment = Payment.query.get(payment_id_int)
    except (ValueError, TypeError):
        # local_payment_id is not a valid integer (e.g., 'VIGN_64_1778518673141')
        # For vignette payments created client-side, reject with helpful error
        return jsonify({
            'error': 'Invalid payment ID format. Vignette payments must be created via /pay/create endpoint first.'
        }), 400

    if not payment:
        return jsonify({'error': 'Payment not found'}), 404

    if status == 'paid':
        payment.status = 'paid'
        payment.huri_payment_id = huri_id
        payment.phone_number = phone_number
        payment.paid_at = now_comoros()
        db.session.commit()

        # Mark fines as paid, or finalize a vignette payment request.
        try:
            fine_payload = json.loads(payment.fines or '[]')
        except Exception:
            fine_payload = []

        if isinstance(fine_payload, dict) and fine_payload.get('type') == 'vignette_request':
            vehicle_id = fine_payload.get('vehicle_id')
            vehicle = Vehicle.query.get(int(vehicle_id)) if vehicle_id else None
            if vehicle:
                payment_time = payment.paid_at or now_comoros()
                try:
                    requested_expiry = datetime.fromisoformat(fine_payload.get('requested_expiry')) if fine_payload.get('requested_expiry') else None
                except Exception:
                    requested_expiry = None

                if not requested_expiry:
                    requested_expiry = get_vignette_expiry_date(payment_time)

                citizen_label = f"App Citoyen / {payment.payer_name or payment.phone_number or 'Inconnu'}"
                vehicle.vignette_payment_requested_at = payment_time
                vehicle.vignette_payment_requested_by = citizen_label
                vehicle.vignette_payment_requested_expiry = requested_expiry
                vehicle.vignette_payment_approved = True
                vehicle.vignette_payment_approved_at = payment_time
                vehicle.vignette_payment_approved_by = citizen_label
                vehicle.vignette_payment_method = 'huri_money' if payment.huri_payment_id else 'app_mobile'
                vehicle.vignette_expiry = requested_expiry
                vehicle.vignette_last_paid_at = payment_time
                vehicle.vignette_last_paid_by = citizen_label
                vehicle.vignette_last_paid_vignette_amount = float(fine_payload.get('vignette_price') or 0.0) + float(fine_payload.get('annual_ds_amount') or 0.0)
                vehicle.vignette_last_paid_penalty_amount = float(fine_payload.get('penalty_amount') or 0.0)
                vehicle.vignette_last_paid_fines_amount = float(fine_payload.get('fines_amount') or 0.0)
                vehicle.vignette_last_paid_total_amount = float(payment.amount or 0.0)
                vehicle.vignette_payment_requested_at = None
                vehicle.vignette_payment_requested_by = None
                vehicle.vignette_payment_requested_expiry = None

                db.session.add(VehicleHistory(
                    vehicle_id=vehicle.id,
                    action='Paiement vignette via mobile citoyen',
                    officer='App Mobile',
                    notes=f"Montant: {round(float(payment.amount or 0.0), 2)} KMF | Expiration: {requested_expiry.strftime('%Y-%m-%d')}"
                ))

                fine_ids = fine_payload.get('fine_ids') or []
                for fid in fine_ids:
                    f = Fine.query.get(int(fid))
                    if f:
                        f.paid = True
                        f.paid_at = payment_time
                        f.paid_by = citizen_label
                        f.receipt_number = f'VEN-{f.id}-{int(payment_time.timestamp())}'

                db.session.commit()
        elif isinstance(fine_payload, dict) and fine_payload.get('type') == 'qr_renewal_request':
            vehicle_id = fine_payload.get('vehicle_id')
            vehicle = Vehicle.query.get(int(vehicle_id)) if vehicle_id else None
            if vehicle:
                payment_time = payment.paid_at or now_comoros()
                vehicle.generate_qr_code_with_expiry()
                vehicle.status = 'active'

                citizen_name = payment.payer_name or payment.phone_number or 'Inconnu'
                db.session.add(QRCodePayment(
                    vehicle_id=vehicle.id,
                    payment_type='renewal',
                    amount=float(payment.amount or 0.0),
                    status='paid',
                    paid_at=payment_time,
                    recorded_by=f'App Citoyen / {citizen_name}',
                ))
                db.session.add(VehicleHistory(
                    vehicle_id=vehicle.id,
                    action='Renouvellement QR Code via mobile citoyen',
                    officer='App Mobile',
                    notes=f"Montant: {round(float(payment.amount or 0.0), 2)} KMF | Nouvelle expiration: {vehicle.qr_code_expiry.strftime('%Y-%m-%d')}"
                ))
                db.session.commit()
        else:
            citizen_label = f"App Citoyen / {payment.payer_name or payment.phone_number or 'Inconnu'}"
            for fid in fine_payload:
                f = Fine.query.get(int(fid))
                if f:
                    f.paid = True
                    f.paid_at = now_comoros()
                    f.paid_by = citizen_label
                    f.receipt_number = f'REC-{f.id}-{int(f.paid_at.timestamp())}'
            db.session.commit()

    return jsonify({'ok': True})


@mobile_pay_bp.route('/checkout/<int:payment_id>', methods=['GET'])
def checkout_page(payment_id):
    """Render the simulated checkout page (HTML) for payment."""
    p = Payment.query.get(payment_id)
    if not p:
        return jsonify({'error': 'Payment not found'}), 404
    
    # Format amount with thousand separators
    amount_formatted = f"{p.amount:,.0f}"
    
    return render_template('checkout.html',
                          payment_id=p.id,
                          amount=amount_formatted,
                          license_plate=p.license_plate or 'N/A',
                          owner_name=p.owner_name or 'N/A',
                          payer_name=p.payer_name)


@mobile_pay_bp.route('/receipt/<int:payment_id>', methods=['GET'])
def get_receipt(payment_id):
    """Get receipt data for a payment (returns JSON for API)."""
    p = Payment.query.get(payment_id)
    if not p:
        return jsonify({'error': 'Payment not found'}), 404

    payment_type = 'fine'
    vehicle = None
    vignette_quote = None
    fines_details = []
    try:
        payload = json.loads(p.fines or '[]')
        if isinstance(payload, dict) and payload.get('type') == 'vignette_request':
            payment_type = 'vignette'
            vehicle = Vehicle.query.get(payload.get('vehicle_id')) if payload.get('vehicle_id') else None
            vignette_quote = {
                'base_amount': float(payload.get('vignette_price') or 0.0),
                'annual_ds_amount': float(payload.get('annual_ds_amount') or 0.0),
                'penalty_amount': float(payload.get('penalty_amount') or 0.0),
                'fines_amount': float(payload.get('fines_amount') or 0.0),
                'total_amount': float(payload.get('total_amount') or p.amount or 0.0),
                'requested_expiry': payload.get('requested_expiry'),
            }
            fine_ids = payload.get('fine_ids') or []
        elif isinstance(payload, dict) and payload.get('type') == 'qr_renewal_request':
            payment_type = 'qr_renewal'
            vehicle = Vehicle.query.get(payload.get('vehicle_id')) if payload.get('vehicle_id') else None
            fine_ids = []
        else:
            fine_ids = payload if isinstance(payload, list) else []

        if fine_ids:
            parsed_fine_ids = []
            for fid in fine_ids:
                try:
                    parsed_fine_ids.append(int(fid))
                except Exception:
                    continue

            if parsed_fine_ids:
                fines = Fine.query.filter(Fine.id.in_(parsed_fine_ids)).all()
                fines_by_id = {fine.id: fine for fine in fines}
                for fid in parsed_fine_ids:
                    fine = fines_by_id.get(fid)
                    if fine:
                        fines_details.append(fine.to_dict())

                if payment_type == 'fine' and fines:
                    vehicle = fines[0].vehicle
    except Exception:
        payload = []

    # Generate receipt number
    receipt_prefix = 'VGN' if payment_type == 'vignette' else 'QRR' if payment_type == 'qr_renewal' else 'RCP'
    receipt_number = f'{receipt_prefix}-{p.id}-{int(p.created_at.timestamp())}'
    
    return jsonify({
        'payment_id': str(p.id),
        'receipt_number': receipt_number,
        'amount': round(float(p.amount), 2),
        'currency': p.currency,
        'status': p.status,
        'payment_type': payment_type,
        'payment_method': 'huri_money',
        'created_at': p.created_at.isoformat() if p.created_at else None,
        'paid_at': p.paid_at.isoformat() if p.paid_at else None,
        'license_plate': p.license_plate,
        'owner_name': p.owner_name,
        'payer_name': p.payer_name,
        'payer_email': p.payer_email,
        'vehicle': vehicle.to_dict() if vehicle else None,
        'fines_count': len(fines_details),
        'fines_details': fines_details,
        'vignette_quote': vignette_quote,
    })


@mobile_pay_bp.route('/receipt/<int:payment_id>.json', methods=['GET'])
def payment_success(payment_id):
    """Return simple JSON receipt for a payment (used as placeholder)."""
    p = Payment.query.get(payment_id)
    if not p:
        return jsonify({'error': 'Payment not found'}), 404

    return jsonify({'payment': p.to_dict()})


@mobile_pay_bp.route('/last-receipt', methods=['GET'])
def last_receipt_by_plate():
    """Get the last receipt for a vehicle by license plate.
    Query params: plate=<license_plate>, optional date=YYYY-MM-DD
    Returns the most recent payment OR a generated receipt from paid fines.
    """
    plate = request.args.get('plate', '').strip()
    date_str = request.args.get('date', '').strip()
    if not plate:
        return jsonify({'error': 'Missing plate parameter'}), 400

    selected_date = None
    start_dt = None
    end_dt = None
    if date_str:
        try:
            selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            start_dt = ensure_comoros(datetime(selected_date.year, selected_date.month, selected_date.day, 0, 0, 0))
            end_dt = ensure_comoros(datetime(selected_date.year, selected_date.month, selected_date.day, 23, 59, 59, 999999))
        except ValueError:
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
    
    # Find vehicle by exact plate only — no partial search
    vehicle = Vehicle.query.filter_by(license_plate=plate.upper().strip()).first()
    if not vehicle or vehicle.qr_pending_approval:
        return jsonify({'error': 'Immatriculation introuvable. Veuillez entrer l\'immatriculation complète.'}), 404

    from sqlalchemy import or_, and_

    payment_query = Payment.query.filter(
        Payment.license_plate.ilike(f'%{vehicle.license_plate}%')
    )
    if start_dt and end_dt:
        payment_query = payment_query.filter(
            or_(
                and_(Payment.paid_at.isnot(None), Payment.paid_at >= start_dt, Payment.paid_at <= end_dt),
                and_(Payment.created_at.isnot(None), Payment.created_at >= start_dt, Payment.created_at <= end_dt),
            )
        )

    # First priority: try to get a paid/completed payment for this vehicle
    last_payment = payment_query.filter(
        Payment.status.in_(['paid', 'completed'])
    ).order_by(
        Payment.paid_at.desc().nullslast(),
        Payment.created_at.desc()
    ).first()

    # Second priority: get the most recent payment of any status
    if not last_payment:
        last_payment = payment_query.order_by(
            Payment.created_at.desc()
        ).first()
    
    # Fourth priority: Generate receipt from most recent paid fine(s)
    # For a date-specific lookup, only payment receipts are returned to keep download support consistent.
    if selected_date and not last_payment:
        return jsonify({'error': 'Aucun reçu trouvé pour cette date'}), 404

    # This handles cases where fines were marked paid but no Payment record exists
    if not last_payment:
        # Get most recent paid fine for this vehicle
        paid_fines = Fine.query.filter_by(
            vehicle_id=vehicle.id,
            paid=True
        ).order_by(Fine.paid_at.desc()).all()
        
        if paid_fines:
            # Use the most recent paid fine as a receipt
            recent_fine = paid_fines[0]
            
            # Create a synthetic payment dict from the fine
            payment_dict = {
                'id': recent_fine.id,
                'amount': float(recent_fine.amount),
                'currency': 'KMF',
                'status': 'paid',
                'huri_payment_id': f'FINE_{recent_fine.id}',
                'license_plate': vehicle.license_plate,
                'owner_name': vehicle.owner_name,
                'payer_name': vehicle.owner_name,
                'payer_email': None,
                'created_at': recent_fine.issued_at.isoformat() if recent_fine.issued_at else None,
                'paid_at': recent_fine.paid_at.isoformat() if recent_fine.paid_at else None,
                'fines': str(recent_fine.id),
                'vehicle': vehicle.to_dict(),
                '_source': 'fine'  # Mark as synthetic receipt
            }
            return jsonify({'payment': payment_dict})
    
    if not last_payment:
        return jsonify({'error': 'Aucun paiement trouvé pour ce véhicule'}), 404
    
    # Add vehicle info to response
    payment_dict = last_payment.to_dict()
    payment_dict['vehicle'] = vehicle.to_dict()
    payment_dict['_source'] = 'payment'  # Mark as real payment
    
    return jsonify({'payment': payment_dict})


@mobile_pay_bp.route('/receipts-by-date', methods=['GET'])
def receipts_by_date():
    """Get all receipts for a vehicle on a specific date.
    Query params: plate=<license_plate>, date=YYYY-MM-DD
    Returns all payments for that date.
    """
    plate = request.args.get('plate', '').strip()
    date_str = request.args.get('date', '').strip()
    
    if not plate or not date_str:
        return jsonify({'error': 'Missing plate or date parameter'}), 400

    try:
        selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        start_dt = ensure_comoros(datetime(selected_date.year, selected_date.month, selected_date.day, 0, 0, 0))
        end_dt = ensure_comoros(datetime(selected_date.year, selected_date.month, selected_date.day, 23, 59, 59, 999999))
    except ValueError:
        return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
    
    # Find vehicle by exact plate only — no partial search
    vehicle = Vehicle.query.filter_by(license_plate=plate.upper().strip()).first()
    if not vehicle or vehicle.qr_pending_approval:
        return jsonify({'error': 'Immatriculation introuvable. Veuillez entrer l\'immatriculation complète.'}), 404

    from sqlalchemy import or_, and_

    # Get all payments for this vehicle on the selected date
    payments = Payment.query.filter(
        Payment.license_plate.ilike(f'%{vehicle.license_plate}%')
    ).filter(
        or_(
            and_(Payment.paid_at.isnot(None), Payment.paid_at >= start_dt, Payment.paid_at <= end_dt),
            and_(Payment.created_at.isnot(None), Payment.created_at >= start_dt, Payment.created_at <= end_dt),
        )
    ).order_by(
        Payment.paid_at.desc().nullslast(),
        Payment.created_at.desc()
    ).all()
    
    if not payments:
        return jsonify({'error': 'Aucun paiement trouvé pour cette date', 'payments': []}), 200
    
    # Return all payments with vehicle info
    payments_list = []
    for payment in payments:
        payment_dict = payment.to_dict()
        payment_dict['vehicle'] = vehicle.to_dict()
        payment_dict['_source'] = 'payment'
        payments_list.append(payment_dict)
    
    return jsonify({
        'date': date_str,
        'plate': vehicle.license_plate,
        'payments': payments_list,
        'count': len(payments_list)
    }), 200


@mobile_pay_bp.route('/receipt/<payment_id>.pdf', methods=['GET'])
def download_receipt_pdf(payment_id):
    """Generate and download receipt as PDF."""
    # Try to find payment by ID - convert to int if possible
    payment = None
    try:
        payment = Payment.query.get(int(payment_id))
    except (ValueError, TypeError) as e:
        print(f"Error parsing payment_id: {e}")
        pass
    
    if not payment:
        # Return 404 with error details
        return jsonify({'error': f'Payment not found: {payment_id}'}), 404
    
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, HRFlowable
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib import colors
        from io import BytesIO
        from datetime import datetime
        
        # Create PDF in memory - 8.5x11 inches (letter)
        pdf_buffer = BytesIO()
        doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, topMargin=0.7*inch, bottomMargin=0.7*inch, leftMargin=0.7*inch, rightMargin=0.7*inch)
        
        # Container for PDF elements
        elements = []
        styles = getSampleStyleSheet()
        
        # Custom styles matching web template
        title_style = ParagraphStyle(
            'Title',
            parent=styles['Normal'],
            fontSize=14,
            fontName='Helvetica-Bold',
            textColor=colors.black,
            spaceAfter=2,
            spaceBefore=0
        )
        
        subtitle_style = ParagraphStyle(
            'Subtitle',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.grey,
            spaceAfter=0
        )
        
        heading_style = ParagraphStyle(
            'Heading',
            parent=styles['Normal'],
            fontSize=12,
            fontName='Helvetica-Bold',
            textColor=colors.black,
            spaceAfter=8
        )
        
        normal_style = ParagraphStyle(
            'Normal',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.black,
            spaceAfter=3,
            leading=12
        )
        
        small_style = ParagraphStyle(
            'Small',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.grey,
            spaceAfter=2
        )
        
        # Get fine information from payment
        import json as json_lib
        fine = None
        fines = []
        vehicle = None
        receipt_number = None
        payment_kind = 'fine'
        
        try:
            raw_payload = json_lib.loads(payment.fines) if payment.fines else []
            fine_ids = []

            if isinstance(raw_payload, dict) and raw_payload.get('type') == 'vignette_request':
                payment_kind = 'vignette'
                vehicle_id = raw_payload.get('vehicle_id')
                if vehicle_id:
                    vehicle = Vehicle.query.get(int(vehicle_id))
                fine_ids = raw_payload.get('fine_ids') or []
            elif isinstance(raw_payload, list):
                fine_ids = raw_payload

            parsed_fine_ids = []
            for fid in fine_ids:
                try:
                    parsed_fine_ids.append(int(fid))
                except (ValueError, TypeError):
                    continue

            if parsed_fine_ids:
                fines = Fine.query.filter(Fine.id.in_(parsed_fine_ids)).all()
                fines_by_id = {f.id: f for f in fines}
                fines = [fines_by_id[fid] for fid in parsed_fine_ids if fid in fines_by_id]

                if fines:
                    fine = fines[0]
                    if not vehicle:
                        vehicle = Vehicle.query.get(fine.vehicle_id)
                    if payment_kind != 'vignette':
                        receipt_number = fine.receipt_number or f"REC-{fine.id}"
        except Exception as e:
            print(f"Error loading fines data: {e}")

        # For vignette payments use a VGN- receipt number
        if payment_kind == 'vignette' and not receipt_number:
            ts = int(payment.created_at.timestamp()) if payment.created_at else payment.id
            receipt_number = f"VGN-{payment.id}-{ts}"

        # HEADER SECTION - matching web receipt
        header_left = Paragraph("<b>Police Nationale - Controle Routier</b><br/>Service des amendes et paiements", title_style)

        receipt_num = receipt_number or f"REC-{payment.id}"
        paid_date = payment.paid_at.strftime('%d/%m/%Y %H:%M') if payment.paid_at else ''
        header_right = Paragraph(f"<b>Recu n {receipt_num}</b><br/>{paid_date}", title_style)
        
        header_data = [[header_left, header_right]]
        header_table = Table(header_data, colWidths=[3.5*inch, 2.1*inch])
        header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 0.12*inch))
        
        # Horizontal line
        elements.append(HRFlowable(width=5.7*inch, thickness=1, lineCap='square'))
        elements.append(Spacer(1, 0.12*inch))
        
        # TWO COLUMN SECTION - Vehicle info (left) and Payment details (right)
        if vehicle:
            col1_items = []
            col1_items.append(Paragraph("<b>Informations Vehicule / Proprietaire</b>", heading_style))
            col1_items.append(Paragraph(f"<b>Immatriculation:</b> {vehicle.license_plate or '—'}", normal_style))
            col1_items.append(Paragraph(f"<b>Proprietaire:</b> {vehicle.owner_name or '—'}", normal_style))
            col1_items.append(Paragraph(f"<b>Telephone:</b> {vehicle.owner_phone or '—'}", normal_style))
            col1_items.append(Paragraph(f"<b>Adresse:</b> {vehicle.owner_address or '—'}", normal_style))
            
            col2_items = []
            col2_items.append(Paragraph("<b>Details du paiement</b>", heading_style))
            if payment_kind == 'vignette':
                col2_items.append(Paragraph("<b>Type:</b> Paiement vignette", normal_style))
            else:
                col2_items.append(Paragraph(f"<b>Type:</b> Paiement amendes ({len(fines)} selectionnee(s))", normal_style))
            col2_items.append(Paragraph(f"<b>Montant total paye:</b> <b>{round(float(payment.amount or 0.0), 2)} KMF</b>", normal_style))
            col2_items.append(Paragraph(f"<b>Reference recu:</b> {receipt_number or '—'}", normal_style))
            if payment_kind == 'vignette' and isinstance(raw_payload, dict):
                expiry = raw_payload.get('requested_expiry', '')
                if expiry:
                    try:
                        expiry = datetime.fromisoformat(expiry).strftime('%d/%m/%Y')
                    except Exception:
                        pass
                    col2_items.append(Paragraph(f"<b>Expiration vignette:</b> {expiry}", normal_style))
            
            # Create nested tables for each column
            col1_table = Table([[item] for item in col1_items], colWidths=[2.7*inch])
            col1_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))
            
            col2_table = Table([[item] for item in col2_items], colWidths=[2.7*inch])
            col2_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))
            
            # Main row with both columns
            main_data = [[col1_table, col2_table]]
            main_table = Table(main_data, colWidths=[2.8*inch, 2.8*inch])
            main_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]))
            elements.append(main_table)

        # VIGNETTE BREAKDOWN SECTION
        if payment_kind == 'vignette' and isinstance(raw_payload, dict):
            elements.append(Spacer(1, 0.15 * inch))
            elements.append(Paragraph("<b>Decomposition du paiement</b>", heading_style))

            vig_price   = float(raw_payload.get('vignette_price') or 0.0)
            annual_ds   = float(raw_payload.get('annual_ds_amount') or 0.0)
            penalty     = float(raw_payload.get('penalty_amount') or 0.0)
            fines_amt   = float(raw_payload.get('fines_amount') or 0.0)
            total_amt   = float(payment.amount or 0.0)

            breakdown_data = [
                [Paragraph('<b>Composante</b>', normal_style), Paragraph('<b>Montant (KMF)</b>', normal_style)],
            ]
            if vig_price > 0:
                breakdown_data.append(['Vignette annuelle', f"{round(vig_price, 2)}"])
            if annual_ds > 0:
                breakdown_data.append(['DS annuelle', f"{round(annual_ds, 2)}"])
            if penalty > 0:
                breakdown_data.append(['Penalite de retard', f"{round(penalty, 2)}"])
            if fines_amt > 0:
                breakdown_data.append([f'Amendes incluses ({len(fines)})', f"{round(fines_amt, 2)}"])
            breakdown_data.append([
                Paragraph('<b>TOTAL</b>', normal_style),
                Paragraph(f'<b>{round(total_amt, 2)}</b>', normal_style),
            ])

            breakdown_table = Table(breakdown_data, colWidths=[3.5 * inch, 1.8 * inch])
            breakdown_table.setStyle(TableStyle([
                ('GRID',        (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ('BACKGROUND',  (0, 0), (-1,  0), colors.whitesmoke),
                ('BACKGROUND',  (0, -1), (-1, -1), colors.HexColor('#f0f0f0')),
                ('FONTNAME',    (0, 0), (-1,  0), 'Helvetica-Bold'),
                ('ALIGN',       (1, 0), (1, -1), 'RIGHT'),
                ('VALIGN',      (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING',  (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
            elements.append(breakdown_table)

        if fines:
            elements.append(Spacer(1, 0.15 * inch))
            elements.append(Paragraph(f"<b>Amendes reglees ({len(fines)})</b>", heading_style))

            fines_table_data = [[
                Paragraph('<b>#</b>', normal_style),
                Paragraph('<b>Motif</b>', normal_style),
                Paragraph('<b>Montant (KMF)</b>', normal_style),
                Paragraph('<b>Date paiement</b>', normal_style),
            ]]

            total_fines_amount = 0.0
            for index, paid_fine in enumerate(fines, start=1):
                total_fines_amount += float(paid_fine.amount or 0.0)
                paid_at_str = paid_fine.paid_at.strftime('%d/%m/%Y %H:%M') if paid_fine.paid_at else '—'
                fines_table_data.append([
                    str(index),
                    paid_fine.reason or '—',
                    f"{round(float(paid_fine.amount or 0.0), 2)}",
                    paid_at_str,
                ])

            fines_table_data.append([
                '',
                Paragraph('<b>Total amendes</b>', normal_style),
                Paragraph(f"<b>{round(total_fines_amount, 2)}</b>", normal_style),
                '',
            ])

            fines_table = Table(fines_table_data, colWidths=[0.4 * inch, 2.8 * inch, 1.1 * inch, 1.4 * inch])
            fines_table.setStyle(TableStyle([
                ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ('BACKGROUND', (0, 0), (-1, 0), colors.whitesmoke),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('ALIGN', (0, 0), (0, -1), 'CENTER'),
                ('ALIGN', (2, 1), (2, -1), 'RIGHT'),
                ('ALIGN', (3, 1), (3, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
            ]))
            elements.append(fines_table)
        
        elements.append(Spacer(1, 0.15*inch))
        
        # NOTES AND QR SECTION - Side by side like web (65% notes, 35% QR)
        notes_items = []
        notes_items.append(Paragraph("<b>Notes</b>", small_style))
        if fine and fine.notes:
            notes_items.append(Paragraph(fine.notes, normal_style))
        elif payment_kind == 'vignette':
            notes_items.append(Paragraph("Paiement vignette effectue depuis l'application mobile citoyen.", normal_style))
        elif fines and len(fines) > 1:
            notes_items.append(Paragraph("Ce recu couvre plusieurs amendes reglees dans une seule transaction.", normal_style))
        else:
            notes_items.append(Paragraph("—", normal_style))
        
        # QR items container
        qr_content = []
        qr_content.append(Paragraph("<b>Voir le suivi</b>", small_style))
        qr_content.append(Spacer(1, 0.05*inch))
        
        try:
            import qrcode
            from reportlab.platypus import Image
            
            # Generate signature for verification
            secret_key = current_app.config.get('SECRET_KEY', 'default-secret-key-change-in-production')
            payment_data = f"{payment.id}|{payment.amount}|{payment.status}|{payment.created_at}|{payment.paid_at or ''}"
            signature = hmac.new(
                secret_key.encode(),
                payment_data.encode(),
                hashlib.sha256
            ).hexdigest()[:16]
            
            # Create verification URL
            verify_url = f"{request.host_url.rstrip('/')}/pay/verify/{payment.id}/{signature}"
            
            # Generate QR code
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=8,
                border=1,
            )
            qr.add_data(verify_url)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white")
            
            # Save QR code to BytesIO
            qr_buffer = BytesIO()
            qr_img.save(qr_buffer, format='PNG')
            qr_buffer.seek(0)
            
            # QR code image
            qr_image = Image(qr_buffer, width=1.0*inch, height=1.0*inch)
            # Create nested table for QR to center it
            qr_img_table = Table([[qr_image]], colWidths=[1.8*inch])
            qr_img_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]))
            qr_content.append(qr_img_table)
            
        except Exception as qr_error:
            print(f"QR code generation warning: {str(qr_error)}")
            qr_content.append(Paragraph("—", normal_style))
        
        # Create nested tables for notes and QR columns
        notes_table = Table([[item] for item in notes_items], colWidths=[3.6*inch])
        notes_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        
        qr_table = Table([[item] for item in qr_content], colWidths=[1.8*inch])
        qr_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        
        # Main row: Notes (65%) + QR (35%)
        notes_qr_row = [[notes_table, qr_table]]
        notes_qr_table = Table(notes_qr_row, colWidths=[3.6*inch, 1.8*inch])
        notes_qr_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(notes_qr_table)
        
        elements.append(Spacer(1, 0.15*inch))
        
        # SIGNATURE SECTION - Full width table for proper alignment
        sig_items = []
        sig_items.append(Paragraph("<b>Signature de l agent</b>", small_style))
        sig_items.append(Spacer(1, 0.02*inch))
        sig_items.append(Paragraph("<b>App Mobile</b>", normal_style))
        sig_items.append(Spacer(1, 0.06*inch))
        sig_items.append(Paragraph("_" * 40, normal_style))
        
        sig_table = Table([[item] for item in sig_items], colWidths=[5.7*inch])
        sig_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(sig_table)
        
        # Build PDF
        try:
            doc.build(elements)
        except Exception as build_error:
            print(f"PDF build error: {str(build_error)}")
            raise
        
        pdf_buffer.seek(0)
        
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'recu_paiement_{payment.id}.pdf'
        )
        
    except Exception as e:
        import traceback
        print(f"PDF generation error: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        return jsonify({'error': f'Could not generate receipt PDF: {str(e)}'}), 500


@mobile_pay_bp.route('/verify/<int:payment_id>/<signature>', methods=['GET'])
def verify_receipt(payment_id, signature):
    """Verify receipt authenticity using QR code signature."""
    p = Payment.query.get(payment_id)
    if not p:
        return render_template('verify_receipt.html', 
                             valid=False, 
                             message="Reçu introuvable",
                             payment=None)
    
    # Generate expected signature
    secret_key = current_app.config.get('SECRET_KEY', 'default-secret-key-change-in-production')
    payment_data = f"{p.id}|{p.amount}|{p.status}|{p.created_at}|{p.paid_at or ''}"
    expected_signature = hmac.new(
        secret_key.encode(),
        payment_data.encode(),
        hashlib.sha256
    ).hexdigest()[:16]
    
    # Verify signature
    valid = hmac.compare_digest(signature, expected_signature)
    
    if valid:
        message = "✓ Ce reçu est authentique et n'a pas été modifié"
    else:
        message = "✗ ATTENTION: Ce reçu a été modifié ou est frauduleux"
    
    return render_template('verify_receipt.html',
                         valid=valid,
                         message=message,
                         payment=p.to_dict(),
                         now=now_comoros())


@mobile_pay_bp.route('/confirm', methods=['POST'])
def confirm_payment():
    """Confirm a payment and mark associated fines as paid.
    Expects JSON: { "paymentId": ... }
    Updates fine statuses to 'paid' in the database.
    """
    data = request.get_json() or {}
    payment_id = data.get('paymentId')

    if not payment_id:
        return jsonify({'error': 'Missing paymentId'}), 400

    # Find the payment by ID
    # If paymentId is numeric, use it directly; otherwise try to parse
    try:
        payment = Payment.query.get(int(payment_id))
    except (ValueError, TypeError):
        # paymentId might be a string like "PAY_123456", try exact match
        payment = Payment.query.filter_by(id=payment_id).first()
    
    if not payment:
        # Payment not found - could be in mock mode
        # Return success anyway since mock is handling it locally
        return jsonify({
            'message': 'Payment confirmed',
            'paymentId': payment_id,
            'finesUpdated': 0
        }), 200

    # Mark all fines for this payment as paid
    fines_updated = 0
    try:
        # Fines are stored as JSON string in payment.fines
        fine_ids = json.loads(payment.fines) if isinstance(payment.fines, str) else []
    except Exception as e:
        fine_ids = []
    
    for fine_id in fine_ids:
        try:
            fine = Fine.query.get(int(fine_id))
            if fine and not fine.paid:
                fine.paid = True
                fine.paid_at = now_comoros()
                fines_updated += 1
        except Exception as e:
            print(f"Error updating fine {fine_id}: {e}")
    
    if fines_updated > 0:
        payment.status = 'paid'
        payment.paid_at = now_comoros()
        db.session.commit()
    
    return jsonify({
        'message': 'Payment confirmed, fines marked as paid',
        'paymentId': payment_id,
        'finesUpdated': fines_updated
    }), 200

