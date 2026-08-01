from flask import Blueprint, render_template, jsonify, request, redirect, url_for, flash, abort, send_file, send_from_directory, current_app
from flask_login import login_required, current_user
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from functools import wraps
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from app import db
from app.models import Vehicle, User, Phone, Insurance, InsuranceAccount, VehicleInsuranceAssignment, Fine, VehicleHistory, VehicleOwner, VehicleTransfer
from decimal import Decimal
import qrcode
import io
import csv
from datetime import datetime, timedelta
import os
from app.timezone_utils import now_comoros, ensure_comoros
from app.models import _cloud_url
import json
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.pagesizes import landscape
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.platypus import Image as RLImage
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

main_bp = Blueprint('main', __name__)
vehicle_bp = Blueprint('vehicles', __name__, url_prefix='/api/vehicles')

# Logo path (optional) - used in PDF exports
logo_path = os.path.join(os.path.dirname(__file__), 'static', 'img', 'logo.png')

# Helper function: Calculate vignette expiry date (March 31st)
def _make_qr_with_plate(data, plate_text, box_size=10, border=2):
    """Generate a QR code image with the license plate text overlaid in the center."""
    from PIL import Image, ImageDraw, ImageFont
    import qrcode as _qrcode

    qr = _qrcode.QRCode(
        error_correction=_qrcode.constants.ERROR_CORRECT_H,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert('RGB')

    draw = ImageDraw.Draw(qr_img)
    w, h = qr_img.size
    font_size = max(16, int(h * 0.10))

    font = None
    for fp in [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]:
        try:
            font = ImageFont.truetype(fp, size=font_size)
            break
        except Exception:
            pass
    if font is None:
        try:
            font = ImageFont.load_default(size=font_size)
        except Exception:
            font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), plate_text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    pad = int(h * 0.03)

    rx1 = (w - tw) // 2 - pad
    ry1 = (h - th) // 2 - pad
    rx2 = (w + tw) // 2 + pad
    ry2 = (h + th) // 2 + pad
    draw.rectangle([rx1, ry1, rx2, ry2], fill='white')
    draw.text(
        ((w - tw) // 2 - bbox[0], (h - th) // 2 - bbox[1]),
        plate_text, fill='black', font=font,
    )
    return qr_img


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

def get_renewal_opening_datetime():
    """Return the configured renewal opening date as a timezone-aware datetime, or None."""
    try:
        from app.models import VignetteSetting
        from datetime import datetime as _dt
        setting = VignetteSetting.query.first()
        if setting and setting.renewal_opening_date:
            return ensure_comoros(_dt.combine(setting.renewal_opening_date, _dt.min.time()))
    except Exception:
        pass
    return None


# Helper function to apply island filter for judiciaire and policier users
def apply_island_filter(query, island_field, force_country=None):
    """Apply island/country filter for judiciaire and policier users with assigned country.
    Judiciaire and policier users can only see data for their assigned island/country.
    Administrateur users can optionally filter by a specific country using force_country parameter."""
    # If force_country is explicitly provided and user is admin, apply it
    if force_country and current_user.role == 'administrateur':
        query = query.filter(island_field == force_country)
    # Otherwise apply default role-based filtering
    elif current_user.role in ['judiciaire', 'policier', 'dgrtr'] and current_user.country:
        query = query.filter(island_field == current_user.country)
    return query

def check_island_access(island):
    """Check if current user has access to data from a specific island.
    Raises 403 Forbidden if judiciaire or policier user doesn't have access.
    Insurance accounts can only access their own island."""
    
    # Insurance accounts can only access their own island
    if isinstance(current_user, InsuranceAccount):
        if island != current_user.insurance.island:
            abort(403)
        return True
    
    # Regular users (judiciaire/policier) can only access their country's data
    if hasattr(current_user, 'role') and current_user.role in ['judiciaire', 'policier'] and hasattr(current_user, 'country'):
        if island != current_user.country:
            abort(403)
    return True


def vehicle_has_unpaid_fines(vehicle_id):
    return Fine.query.filter_by(vehicle_id=vehicle_id, paid=False).first() is not None


def _record_qr_payment(vehicle, payment_type, officer):
    """Auto-record a SmartTech QRCodePayment. Activation recorded once; renewal always."""
    try:
        from app.models import QRCodePayment, SmartTechSetting
        if payment_type == 'activation':
            if QRCodePayment.query.filter_by(vehicle_id=vehicle.id, payment_type='activation', status='paid').first():
                return
            amount = SmartTechSetting.get('qr_activation_price', 5000)
        else:
            amount = SmartTechSetting.get('qr_renewal_price', 3000)
        db.session.add(QRCodePayment(
            vehicle_id=vehicle.id,
            payment_type=payment_type,
            amount=amount,
            status='paid',
            paid_at=now_comoros(),
            recorded_by=officer,
        ))
        db.session.commit()
    except Exception as e:
        print(f"Warning: could not record QR payment: {e}")


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


def get_first_unpaid_fine(vehicle_id):
    return Fine.query.filter_by(vehicle_id=vehicle_id, paid=False).order_by(Fine.issued_at.desc()).first()


def format_kmf_amount(amount):
    return int(round(float(amount))) if amount is not None else None


def calculate_penalty_amount(days_late):
    """
    Calculate penalty amount based on days late using configured penalty rates.
    
    Penalties apply to vehicles that have not renewed their vignette after March 31st (expiration date).
    Aux Comores, les vignettes expirent le 31 mars. Les pénalités ne s'appliquent que si le véhicule 
    ne renouvelle pas sa vignette après cette date.
    
    Args:
        days_late (int): Number of days past vignette expiry date (March 31st)
        
    Returns:
        float: Penalty amount in KMF. Returns 0 if no penalty applies or days_late is 0 or negative.
        
    Example (with penalties configured):
        - 0-10 days late: 0 KMF (no penalty)
        - 11-20 days late: (days - 10) × penalty_per_day KMF
        - 21-30 days late: (days - 20) × penalty_per_day KMF (if configured)
    """
    if not days_late or days_late <= 0:
        return 0.0
    
    try:
        from app.models import PenaltyRate
        
        # Find applicable penalty rate for these days
        penalty_rate = PenaltyRate.query.filter(
            PenaltyRate.is_active == True,
            PenaltyRate.days_late_min <= days_late,
            PenaltyRate.days_late_max >= days_late
        ).first()
        
        if not penalty_rate:
            # No configured penalty for these days
            return 0.0
        
        # Calculate: (days_late - previous_max_days) × penalty_per_day
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


def calculate_vignette_price(vehicle):
    """
    Calculate vignette price based on vehicle attributes using configured rates.

    Args:
        vehicle (Vehicle): Vehicle object with fiscal_class, cv_class, fuel_type, year.

    Returns:
        float: Total price in KMF (vignette base + annual DS). Returns 0.0 if no applicable rate found.
    """
    if not vehicle:
        return 0.0

    try:
        from app.models import VignetteRate

        # Get vehicle age
        vehicle_age = None
        if vehicle.year:
            try:
                current_year = datetime.utcnow().year
                vehicle_age = current_year - int(vehicle.year)
            except Exception:
                vehicle_age = None

        query = VignetteRate.query.filter(VignetteRate.is_active == True)

        # Match fiscal_class.
        if vehicle.fiscal_class:
            query = query.filter((VignetteRate.fiscal_class == vehicle.fiscal_class) | (VignetteRate.fiscal_class.is_(None)))
        else:
            query = query.filter(VignetteRate.fiscal_class.is_(None))

        # Match cv_class.
        if vehicle.cv_class:
            query = query.filter((VignetteRate.cv_class == vehicle.cv_class) | (VignetteRate.cv_class.is_(None)))
        else:
            query = query.filter(VignetteRate.cv_class.is_(None))

        # Match fuel_type.
        if vehicle.fuel_type:
            query = query.filter((VignetteRate.fuel_type == vehicle.fuel_type) | (VignetteRate.fuel_type.is_(None)))
        else:
            query = query.filter(VignetteRate.fuel_type.is_(None))

        # Match age range.
        if vehicle_age is not None:
            query = query.filter(
                (VignetteRate.vehicle_age_min.is_(None) | (VignetteRate.vehicle_age_min <= vehicle_age)) &
                (VignetteRate.vehicle_age_max.is_(None) | (VignetteRate.vehicle_age_max >= vehicle_age))
            )
        else:
            query = query.filter(VignetteRate.vehicle_age_min.is_(None), VignetteRate.vehicle_age_max.is_(None))

        rates = query.all()
        if not rates:
            return 0.0

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
        base_price = float(best_rate.price_kmf) if best_rate.price_kmf else 0.0
        annual_ds = float(best_rate.annual_ds) if getattr(best_rate, 'annual_ds', None) is not None else 1000.0
        return base_price + annual_ds

    except Exception:
        return 0.0


def get_pending_vignette_request_expiry(vehicle):
    """Return a pending requested vignette expiry, if any.

    The primary source is the vehicle request fields. If those are absent,
    fall back to a pending Payment row created for a vignette request.
    """
    requested_expiry = getattr(vehicle, 'vignette_payment_requested_expiry', None)
    if requested_expiry:
        return requested_expiry

    try:
        from app.models import Payment

        pending_payments = Payment.query.filter_by(
            license_plate=vehicle.license_plate,
            status='pending'
        ).order_by(Payment.created_at.desc()).all()

        for payment in pending_payments:
            try:
                payload = json.loads(payment.fines or '{}')
            except Exception:
                continue

            if isinstance(payload, dict) and payload.get('type') == 'vignette_request':
                expiry_value = payload.get('requested_expiry')
                if expiry_value:
                    try:
                        return datetime.fromisoformat(expiry_value)
                    except Exception:
                        return None
    except Exception:
        pass

    return None


def get_vehicle_block_reason_for_insurance(vehicle):
    unpaid_fine = get_first_unpaid_fine(vehicle.id)
    if unpaid_fine:
        fine_label = f"Amende #{unpaid_fine.id}"
        if unpaid_fine.reason:
            fine_label += f" - {unpaid_fine.reason}"
        if unpaid_fine.amount is not None:
                fine_label += f" ({format_kmf_amount(unpaid_fine.amount)} KMF)"
        return f"{fine_label}. Vous devez d'abord la régler avant d'ajouter ou de modifier l'assurance."

    try:
        qr_expired = vehicle.is_qr_code_expired()
    except Exception:
        qr_expired = False

    inactive_reasons = []
    if vehicle.status == 'inactive':
        inactive_reasons.append(f"statut: {vehicle.status}")
    if qr_expired:
        inactive_reasons.append("QR code expiré")

    if inactive_reasons:
        return "Ce véhicule est inactif (" + " et ".join(inactive_reasons) + "). Vous ne pouvez pas l'ajouter à l'assurance tant qu'il n'est pas réactivé."

    now_dt = now_comoros()
    now_dt_naive = now_dt.replace(tzinfo=None) if getattr(now_dt, 'tzinfo', None) else now_dt
    has_insurance_company = bool(vehicle.insurance_company and vehicle.insurance_company.strip())
    expiry_dt = vehicle.insurance_expiry
    expiry_dt_naive = expiry_dt.replace(tzinfo=None) if (expiry_dt and getattr(expiry_dt, 'tzinfo', None)) else expiry_dt
    has_active_insurance = has_insurance_company and (expiry_dt_naive is None or expiry_dt_naive >= now_dt_naive)

    if has_active_insurance:
        if vehicle.insurance_company:
            return f"Ce véhicule a déjà une assurance active ({vehicle.insurance_company})."
        return "Ce véhicule a déjà une assurance active."

    return None


def fine_to_block_payload(fine):
    if not fine:
        return None
    return {
        'id': fine.id,
        'reason': fine.reason,
        'amount': float(fine.amount) if fine.amount is not None else None,
        'officer': fine.officer,
        'issued_at': fine.issued_at.isoformat() if fine.issued_at else None,
        'issued_at_str': fine.issued_at.strftime('%d/%m/%Y %H:%M') if fine.issued_at else None,
        'receipt_number': fine.receipt_number,
    }


def _is_noop_vehicle_update_history(action, notes):
    """Return True for old vehicle update history rows that only captured unchanged values."""
    action_text = (action or '').strip().lower()
    if not action_text.startswith('mise à jour:'):
        return False

    notes_text = (notes or '').strip()
    if 'ancien:' not in notes_text.lower() or '→ nouveau:' not in notes_text.lower():
        return False

    try:
        old_part = notes_text.split('Ancien:', 1)[1].split('→ Nouveau:', 1)[0].strip()
        new_part = notes_text.split('→ Nouveau:', 1)[1].strip()
    except Exception:
        return False

    def _normalize(value):
        return (value or '').strip().strip('—').strip()

    old_value = _normalize(old_part)
    new_value = _normalize(new_part)
    return old_value == new_value or (old_value == '' and new_value == '')

def _build_pdf_table(buffer, title_text, headers, rows, landscape_mode=False):
    """Helper function to build a professional PDF table with header/footer."""
    if not REPORTLAB_AVAILABLE:
        return None
    pagesize = landscape(A4) if landscape_mode else A4
    leftMargin = rightMargin = 2*cm
    topMargin = 3.5*cm
    bottomMargin = 2*cm
    doc = SimpleDocTemplate(buffer, pagesize=pagesize, leftMargin=leftMargin, rightMargin=rightMargin, topMargin=topMargin, bottomMargin=bottomMargin)
    styles = getSampleStyleSheet()
    elems = []

    # Date et info du rapport
    date_info = now_comoros().strftime('%d/%m/%Y à %H:%M')
    elems.append(Spacer(1, 0.5*cm))
    
    # Titre principal avec style personnalisé
    from reportlab.lib.styles import ParagraphStyle
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#1a1a1a'),
        spaceAfter=8,
        alignment=1,  # Center
        fontName='Helvetica-Bold'
    )
    elems.append(Paragraph(title_text, title_style))
    
    # Ligne de séparation
    from reportlab.graphics.shapes import Drawing, Line
    d = Drawing(pagesize[0] - leftMargin - rightMargin, 1)
    line = Line(0, 0, pagesize[0] - leftMargin - rightMargin, 0)
    line.strokeColor = colors.HexColor('#007bff')
    line.strokeWidth = 2
    d.add(line)
    elems.append(d)
    elems.append(Spacer(1, 0.3*cm))
    
    # Informations du rapport
    info_style = ParagraphStyle(
        'InfoStyle',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.HexColor('#666666')
    )
    elems.append(Paragraph(f'<b>Date du rapport:</b> {date_info}', info_style))
    elems.append(Paragraph(f'<b>Nombre d\'enregistrements:</b> {len(rows)}', info_style))
    elems.append(Spacer(1, 0.5*cm))

    # Prepare table data (headers + rows)
    data = [headers] + rows

    # Estimate column widths
    total_width = pagesize[0] - leftMargin - rightMargin
    col_count = len(headers)
    default_w = total_width / col_count
    colWidths = [default_w] * col_count
    
    # Adjust widths for specific columns
    for i, h in enumerate(headers):
        lh = str(h).lower()
        # Make owner/propriétaire column wider so long names fit nicely
        if 'propri' in lh or ('owner' in lh and 'address' not in lh):
            colWidths[i] = default_w * 2.8
        # Keep address/notes wide as before
        elif 'address' in lh or 'notes' in lh or 'owner_address' in lh:
            colWidths[i] = default_w * 2.5
        # Make "Motif" column wider for fines report
        elif 'motif' in lh:
            colWidths[i] = default_w * 3.0
        # Reduce date columns in fines report
        elif 'mis le' in lh or 'payée le' in lh or 'émis le' in lh:
            colWidths[i] = default_w * 0.7
        # Reduce immatriculation column
        elif 'immatriculation' in lh:
            colWidths[i] = default_w * 0.9
        # Reduce montant column
        elif 'montant' in lh:
            colWidths[i] = default_w * 0.8
        # Reduce agent column
        elif 'agent' in lh or 'officer' in lh:
            colWidths[i] = default_w * 0.7
    
    # Normalize widths
    s = sum(colWidths)
    if s != total_width:
        factor = total_width / s
        colWidths = [w * factor for w in colWidths]

    table = Table(data, repeatRows=1, colWidths=colWidths)
    table.setStyle(TableStyle([
        # En-tête du tableau
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#007bff')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        
        # Corps du tableau
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('ALIGN', (0, 1), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 1), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        
        # Bordures
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dee2e6')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#007bff')),
    ]))
    elems.append(table)

    # header/footer callbacks
    def _on_page(c, doc):
        c.saveState()
        
        # En-tête avec fond coloré
        c.setFillColor(colors.HexColor('#007bff'))
        c.rect(0, pagesize[1] - 2.8*cm, pagesize[0], 2.8*cm, fill=True, stroke=False)
        
        # Logo ou nom de l'organisation
        c.setFillColor(colors.white)
        c.setFont('Helvetica-Bold', 16)
        try:
            if os.path.exists(logo_path):
                c.drawImage(logo_path, leftMargin, pagesize[1] - 2.5*cm, width=2*cm, height=2*cm, preserveAspectRatio=True, mask='auto')
                c.drawString(leftMargin + 2.5*cm, pagesize[1] - 1.5*cm, 'SYSTÈME DE CONTRÔLE POLICIER')
            else:
                c.drawString(leftMargin, pagesize[1] - 1.5*cm, '🚔 SYSTÈME DE CONTRÔLE POLICIER')
        except Exception:
            c.drawString(leftMargin, pagesize[1] - 1.5*cm, '🚔 SYSTÈME DE CONTRÔLE POLICIER')
        
        # Sous-titre de l'en-tête
        c.setFont('Helvetica', 10)
        c.drawString(leftMargin, pagesize[1] - 2*cm, 'Direction de la Sécurité Publique')
        
        # Pied de page avec ligne
        c.setStrokeColor(colors.HexColor('#dee2e6'))
        c.setLineWidth(0.5)
        c.line(leftMargin, 1.5*cm, pagesize[0] - rightMargin, 1.5*cm)
        
        # Informations du pied de page
        c.setFillColor(colors.HexColor('#666666'))
        c.setFont('Helvetica', 8)
        page_num = c.getPageNumber()
        
        # Gauche: Date de génération
        c.drawString(leftMargin, 1*cm, f'Généré le {now_comoros().strftime("%d/%m/%Y à %H:%M")}')
        
        # Centre: Confidentiel
        c.drawCentredString(pagesize[0] / 2.0, 1*cm, '📋 Document Officiel - Confidentiel')
        
        # Droite: Numéro de page
        c.drawRightString(pagesize[0] - rightMargin, 1*cm, f'Page {page_num}')
        
        c.restoreState()

    doc.build(elems, onFirstPage=_on_page, onLaterPages=_on_page)
    buffer.seek(0)
    return buffer


def roles_required(*allowed_roles):
    """Decorator to restrict access to users with given roles (or admin)."""
    def deco(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login', next=request.path))
            # determine role: prefer `role` field, fall back to is_admin
            role = getattr(current_user, 'role', None)
            if not role and getattr(current_user, 'is_admin', False):
                role = 'administrateur'
            if role == 'administrateur' or role in allowed_roles:
                return f(*args, **kwargs)
            abort(403)
        return wrapped
    return deco


@main_bp.route('/uploads/<path:filename>')
def serve_upload(filename):
    """Serve files from UPLOAD_FOLDER (persistent disk on Render, static/ in dev)."""
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)


@main_bp.route('/')
def index():
    """Page d'accueil du dashboard"""
    # Require login before showing the public index/welcome page
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login', next=url_for('main.index')))
    
    # Redirect insurance accounts to their dashboard
    from app.models import InsuranceAccount
    if isinstance(current_user, InsuranceAccount):
        return redirect(url_for('main.insurance_dashboard'))
    
    # Redirect agent_impot to vignette dashboard
    if getattr(current_user, 'role', None) == 'agent_impot':
        return redirect(url_for('main.vignette_dashboard'))

    # Redirect mobile money agents to their payment dashboard
    if getattr(current_user, 'role', None) == 'mobile_money_agent':
        return redirect(url_for('main.mobile_money_dashboard'))
    
    return render_template('index.html')


@main_bp.route('/dashboard')
@roles_required('administrateur','judiciaire','dgrtr')
def dashboard():
    _require_dr_only()
    query = Vehicle.query
    if current_user.role == 'judiciaire' and current_user.country:
        query = query.filter(Vehicle.owner_island == current_user.country)
    recent = query.order_by(Vehicle.created_at.desc()).limit(10).all()
    initial_vehicles = [v.to_dict() for v in recent]
    return render_template('dashboard.html', initial_vehicles=initial_vehicles)


@main_bp.route('/insurance-dashboard')
@login_required
def insurance_dashboard():
    """Dashboard for insurance accounts to manage their vehicles"""
    # Check if user is an insurance account
    if not isinstance(current_user, InsuranceAccount):
        current_app.logger.warning(f"Non-insurance account tried to access dashboard: {current_user.__class__.__name__} ID={current_user.id}")
        abort(403)
    
    if not current_user.is_active:
        current_app.logger.warning(f"Inactive insurance account tried to access dashboard: {current_user.username}")
        abort(403)
    
    return render_template('insurance_dashboard.html')


@main_bp.route('/insurance-sigva')
@login_required
def insurance_sigva():
    """S.I.G.V.A commission page for insurance accounts."""
    if not isinstance(current_user, InsuranceAccount) or not current_user.is_active:
        abort(403)
    return render_template('insurance_sigva.html')


@main_bp.route('/insurance-sigva/receipt/<month>')
@login_required
def insurance_sigva_receipt(month):
    """Generate a PDF receipt for a confirmed commission month."""
    import re as _re, io
    from flask import send_file
    from app.models import InsuranceAccount, QRCodePayment, SmartTechSetting, VehicleInsuranceAssignment
    from app.timezone_utils import ensure_comoros, now_comoros
    from datetime import timezone, timedelta, datetime
    import calendar

    if not isinstance(current_user, InsuranceAccount) or not current_user.is_active:
        abort(403)
    if not _re.match(r'^\d{4}-\d{2}$', month):
        abort(400)

    ins = current_user.insurance
    commission_rate = int(SmartTechSetting.get('insurance_commission', 0))
    COMOROS_TZ = timezone(timedelta(hours=3))

    # Check the month is confirmed
    rval = SmartTechSetting.get('commission_received_%s_%s' % (ins.id, month), '')
    if not rval or rval == '0':
        abort(404)
    parts = str(rval).split('|', 1)
    confirmed_at_str = parts[0]
    confirmed_by     = parts[1] if len(parts) > 1 else None

    # Commission data for the month
    year_n, month_n = map(int, month.split('-'))
    last_day = calendar.monthrange(year_n, month_n)[1]
    m_start  = datetime(year_n, month_n, 1, 0, 0, 0, tzinfo=COMOROS_TZ)
    m_end    = datetime(year_n, month_n, last_day, 23, 59, 59, tzinfo=COMOROS_TZ)

    assignments = VehicleInsuranceAssignment.query.filter_by(insurance_account_id=current_user.id).all()
    vehicle_ids = list({a.vehicle_id for a in assignments})
    if vehicle_ids:
        from app.models import QRCodePayment
        qr_all = QRCodePayment.query.filter(
            QRCodePayment.vehicle_id.in_(vehicle_ids),
            QRCodePayment.status == 'paid'
        ).all()
    else:
        qr_all = []
    m_qr = [q for q in qr_all if q.paid_at and m_start <= ensure_comoros(q.paid_at) <= m_end]
    acts = sum(1 for q in m_qr if q.payment_type == 'activation')
    rens = sum(1 for q in m_qr if q.payment_type == 'renewal')
    commission = (acts + rens) * commission_rate

    MONTHS_FR = ['Janvier','Février','Mars','Avril','Mai','Juin',
                 'Juillet','Août','Septembre','Octobre','Novembre','Décembre']
    month_label = MONTHS_FR[month_n - 1] + ' ' + str(year_n)

    # ── Build PDF ──
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm, mm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, HRFlowable, KeepTogether)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

    # ── Palette ──
    NAVY     = colors.HexColor('#0B1D35')
    NAVY2    = colors.HexColor('#122540')
    CYAN     = colors.HexColor('#00B4CC')
    CYAN_LT  = colors.HexColor('#E5F7FA')
    GREEN    = colors.HexColor('#0D7A45')
    GREEN_LT = colors.HexColor('#EAF7F0')
    GREEN_BD = colors.HexColor('#A8D5BE')
    SLATE    = colors.HexColor('#556070')
    STEEL    = colors.HexColor('#E4EAF1')
    WHITE    = colors.white

    confirmed_at_display = '—'
    try:
        from datetime import datetime as _dt2
        confirmed_at_display = _dt2.fromisoformat(confirmed_at_str).strftime('%d/%m/%Y à %H:%M')
    except Exception:
        confirmed_at_display = confirmed_at_str

    receipt_ref = f'SIGVA/{ins.id:04d}/{year_n}/{month_n:02d}'
    generated_at = now_comoros().strftime('%d/%m/%Y à %H:%M')

    buf = io.BytesIO()
    MX, MY = 1.8*cm, 1.5*cm
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=MX, rightMargin=MX,
                            topMargin=MY, bottomMargin=MY)
    W = A4[0] - 2*MX
    styles = getSampleStyleSheet()

    # ── Typography ──
    def ps(name, **kw):
        return ParagraphStyle(name, parent=styles['Normal'], **kw)

    hdr_brand  = ps('HB', fontSize=15, fontName='Helvetica-Bold', textColor=WHITE, leading=18)
    hdr_sub    = ps('HS', fontSize=8,  fontName='Helvetica',      textColor=colors.HexColor('#90B8D4'), leading=11, spaceBefore=2)
    hdr_ref_l  = ps('RL', fontSize=8,  fontName='Helvetica',      textColor=colors.HexColor('#90B8D4'), alignment=TA_RIGHT, leading=11)
    hdr_ref_v  = ps('RV', fontSize=13, fontName='Helvetica-Bold', textColor=WHITE, alignment=TA_RIGHT, leading=16)
    hdr_recu   = ps('RC', fontSize=9,  fontName='Helvetica-Bold', textColor=CYAN,  alignment=TA_RIGHT, leading=11, spaceBefore=3)

    meta_s     = ps('ME', fontSize=7.5, textColor=SLATE, alignment=TA_RIGHT)
    sec_s      = ps('SE', fontSize=8.5, fontName='Helvetica-Bold', textColor=SLATE,
                    spaceBefore=14, spaceAfter=5, letterSpacing=0.8)
    lbl_s      = ps('LB', fontSize=8,  textColor=SLATE, leading=11)
    val_s      = ps('VL', fontSize=10, fontName='Helvetica-Bold', textColor=NAVY, leading=13)
    val_sm     = ps('VS', fontSize=8.5,fontName='Helvetica-Bold', textColor=NAVY, leading=11)
    amt_lbl_s  = ps('AL', fontSize=8,  fontName='Helvetica-Bold', textColor=CYAN,
                    alignment=TA_CENTER, letterSpacing=1.2, spaceAfter=2)
    amt_val_s  = ps('AV', fontSize=28, fontName='Helvetica-Bold', textColor=NAVY, alignment=TA_CENTER)
    amt_sub_s  = ps('AS', fontSize=8,  textColor=SLATE, alignment=TA_CENTER, spaceBefore=2)
    det_hdr_s  = ps('DH', fontSize=8,  fontName='Helvetica-Bold', textColor=WHITE,
                    alignment=TA_CENTER, leading=11)
    det_val_s  = ps('DV', fontSize=9,  alignment=TA_CENTER, leading=12, textColor=NAVY)
    det_amt_s  = ps('DA', fontSize=9,  fontName='Helvetica-Bold', alignment=TA_CENTER,
                    leading=12, textColor=NAVY)
    cert_ttl_s = ps('CT', fontSize=13, fontName='Helvetica-Bold', textColor=GREEN,
                    alignment=TA_CENTER, spaceAfter=2)
    cert_lbl_s = ps('CL', fontSize=8,  textColor=SLATE, leading=11)
    cert_val_s = ps('CV', fontSize=9.5,fontName='Helvetica-Bold', textColor=NAVY, leading=13)
    foot_s     = ps('FT', fontSize=7,  textColor=SLATE, alignment=TA_CENTER)

    def p(text, style=None): return Paragraph(str(text) if text else '—', style or det_val_s)
    def fmt(n):              return f'{round(n):,}'.replace(',', ' ') + ' KMF'

    story = []

    # ══════════════════════════════════════════════
    # HEADER BAND
    # ══════════════════════════════════════════════
    hdr_left = [
        Paragraph('Smart Development', hdr_brand),
        Paragraph('Système S.I.G.V.A · Commission Assurance', hdr_sub),
    ]
    hdr_right = [
        Paragraph('REÇU DE COMMISSION', hdr_recu),
        Paragraph(receipt_ref, hdr_ref_v),
        Paragraph('Référence document', hdr_ref_l),
    ]
    hdr_tbl = Table(
        [[hdr_left, hdr_right]],
        colWidths=[W*0.55, W*0.45],
    )
    hdr_tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), NAVY),
        ('TOPPADDING',    (0,0), (-1,-1), 16),
        ('BOTTOMPADDING', (0,0), (-1,-1), 16),
        ('LEFTPADDING',   (0,0), (0,0),  16),
        ('RIGHTPADDING',  (-1,0),(-1,-1),16),
        ('LEFTPADDING',   (1,0), (1,-1), 8),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(hdr_tbl)

    # Cyan accent stripe
    story.append(Table([['']], colWidths=[W]))
    story[-1].setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), CYAN),
        ('TOPPADDING',    (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))

    # Meta line (ref + date) right-aligned
    story.append(Spacer(1, 0.25*cm))
    story.append(Paragraph(
        f'Réf. {receipt_ref}  ·  Généré le {generated_at}',
        meta_s))
    story.append(Spacer(1, 0.5*cm))

    # ══════════════════════════════════════════════
    # PARTIES : Émetteur | Destinataire
    # ══════════════════════════════════════════════
    emetteur = [
        Paragraph('ÉMETTEUR', sec_s),
        Paragraph('Smart Development', val_s),
        Paragraph('Système S.I.G.V.A', ps('e2', fontSize=8.5, textColor=SLATE, leading=11)),
        Paragraph('République des Comores', ps('e3', fontSize=8.5, textColor=SLATE, leading=11)),
    ]
    destinataire = [
        Paragraph('DESTINATAIRE', ps('DS', fontSize=8.5, fontName='Helvetica-Bold',
                  textColor=SLATE, spaceBefore=0, spaceAfter=5, letterSpacing=0.8)),
        Paragraph(ins.company_name, val_s),
        Paragraph(ins.island or 'Comores', ps('d2', fontSize=8.5, textColor=SLATE, leading=11)),
        Paragraph('Compagnie d\'assurance', ps('d3', fontSize=8.5, textColor=SLATE, leading=11)),
    ]
    parties_tbl = Table([[emetteur, destinataire]], colWidths=[W*0.5, W*0.5])
    parties_tbl.setStyle(TableStyle([
        ('BACKGROUND',    (1,0), (1,-1), STEEL),
        ('TOPPADDING',    (0,0), (-1,-1), 12),
        ('BOTTOMPADDING', (0,0), (-1,-1), 12),
        ('LEFTPADDING',   (0,0), (0,-1), 0),
        ('RIGHTPADDING',  (0,0), (0,-1), 16),
        ('LEFTPADDING',   (1,0), (1,-1), 16),
        ('VALIGN',        (0,0), (-1,-1), 'TOP'),
        ('LINEAFTER',     (0,0), (0,-1), 0.5, STEEL),
    ]))
    story.append(parties_tbl)
    story.append(Spacer(1, 0.6*cm))

    # ══════════════════════════════════════════════
    # PÉRIODE
    # ══════════════════════════════════════════════
    period_data = [
        [p('PÉRIODE', ps('PL', fontSize=8, fontName='Helvetica-Bold', textColor=SLATE,
                          letterSpacing=0.8, alignment=TA_CENTER)),
         p('TAUX UNITAIRE', ps('TL', fontSize=8, fontName='Helvetica-Bold', textColor=SLATE,
                                letterSpacing=0.8, alignment=TA_CENTER))],
        [p(month_label, ps('PV', fontSize=12, fontName='Helvetica-Bold', textColor=NAVY,
                            alignment=TA_CENTER)),
         p(f'{commission_rate:,} KMF / véhicule'.replace(',', ' '),
           ps('TV', fontSize=11, fontName='Helvetica-Bold', textColor=NAVY,
               alignment=TA_CENTER))],
    ]
    period_tbl = Table(period_data, colWidths=[W*0.5, W*0.5])
    period_tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0), CYAN_LT),
        ('BACKGROUND',    (0,1), (-1,1), colors.white),
        ('BOX',           (0,0), (-1,-1), 0.8, CYAN),
        ('LINEAFTER',     (0,0), (0,-1), 0.5, CYAN),
        ('TOPPADDING',    (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(period_tbl)
    story.append(Spacer(1, 0.55*cm))

    # ══════════════════════════════════════════════
    # AMOUNT BOX
    # ══════════════════════════════════════════════
    amt_box = Table([
        [Paragraph('MONTANT DE LA COMMISSION', amt_lbl_s)],
        [Paragraph(fmt(commission), amt_val_s)],
        [Paragraph(f'{acts + rens} véhicule(s) × {commission_rate:,} KMF'.replace(',', ' '), amt_sub_s)],
    ], colWidths=[W])
    amt_box.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), colors.white),
        ('BOX',           (0,0), (-1,-1), 1.5, CYAN),
        ('TOPPADDING',    (0,0), (-1,-1), 12),
        ('BOTTOMPADDING', (0,0), (-1,0),  4),
        ('BOTTOMPADDING', (0,1), (-1,1),  4),
        ('BOTTOMPADDING', (0,2), (-1,2), 12),
        ('LEFTPADDING',   (0,0), (-1,-1), 10),
        ('RIGHTPADDING',  (0,0), (-1,-1), 10),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(amt_box)
    story.append(Spacer(1, 0.6*cm))

    # ══════════════════════════════════════════════
    # BREAKDOWN TABLE
    # ══════════════════════════════════════════════
    story.append(Paragraph('DÉTAIL DU CALCUL', sec_s))
    det_data = [
        [p('Activations', det_hdr_s), p('Renouvellements', det_hdr_s),
         p('Total véhicules', det_hdr_s), p('Taux unitaire', det_hdr_s), p('Commission', det_hdr_s)],
        [p(str(acts), det_val_s), p(str(rens), det_val_s), p(str(acts + rens), det_val_s),
         p(fmt(commission_rate), det_val_s), p(fmt(commission), det_amt_s)],
    ]
    det_tbl = Table(det_data, colWidths=[W*0.17, W*0.22, W*0.21, W*0.2, W*0.2])
    det_tbl.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,0), NAVY),
        ('BACKGROUND',    (0,1), (-1,1), colors.HexColor('#F7F9FC')),
        ('BOX',           (0,0), (-1,-1), 0.5, STEEL),
        ('LINEBELOW',     (0,0), (-1,0), 0.5, NAVY2),
        ('GRID',          (0,0), (-1,-1), 0.4, STEEL),
        ('TOPPADDING',    (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
        # Highlight commission column
        ('BACKGROUND',    (4,1), (4,1), CYAN_LT),
        ('TEXTCOLOR',     (4,1), (4,1), NAVY),
    ]))
    story.append(det_tbl)
    story.append(Spacer(1, 0.7*cm))

    # ══════════════════════════════════════════════
    # CERTIFICATION BLOCK
    # ══════════════════════════════════════════════
    cert_inner = [
        [Paragraph('✓  RÉCEPTION CONFIRMÉE', cert_ttl_s)],
        [Spacer(1, 0.15*cm)],
        [Table([
            [p('Date de confirmation', cert_lbl_s), p(confirmed_at_display, cert_val_s)],
            [p('Validé par',           cert_lbl_s), p(confirmed_by or '—',   cert_val_s)],
        ], colWidths=[W*0.32, W*0.50],
        style=TableStyle([
            ('TOPPADDING',    (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING',   (0,0), (-1,-1), 0),
            ('RIGHTPADDING',  (0,0), (-1,-1), 0),
            ('LINEBELOW',     (0,0), (-1,-2), 0.3, GREEN_BD),
            ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
        ]))],
    ]
    cert_content_tbl = Table(cert_inner, colWidths=[W*0.86])
    cert_content_tbl.setStyle(TableStyle([
        ('TOPPADDING',    (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING',   (0,0), (-1,-1), 0),
        ('RIGHTPADDING',  (0,0), (-1,-1), 0),
        ('ALIGN',         (0,0), (-1,-1), 'CENTER'),
    ]))
    cert_outer = Table([[cert_content_tbl]], colWidths=[W])
    cert_outer.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), GREEN_LT),
        ('BOX',           (0,0), (-1,-1), 1.2, GREEN),
        ('TOPPADDING',    (0,0), (-1,-1), 14),
        ('BOTTOMPADDING', (0,0), (-1,-1), 14),
        ('LEFTPADDING',   (0,0), (-1,-1), 20),
        ('RIGHTPADDING',  (0,0), (-1,-1), 20),
        ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(KeepTogether(cert_outer))
    story.append(Spacer(1, 0.8*cm))

    # ══════════════════════════════════════════════
    # FOOTER
    # ══════════════════════════════════════════════
    story.append(Table([['']], colWidths=[W]))
    story[-1].setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), CYAN),
        ('TOPPADDING',    (0,0), (-1,-1), 1),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(
        f'Ce document est généré automatiquement par le Système S.I.G.V.A — Smart Development · {generated_at}',
        foot_s))

    doc.build(story)
    buf.seek(0)
    filename = f'recu_SIGVA_{ins.company_name.replace(" ", "_")}_{month}.pdf'
    return send_file(buf, mimetype='application/pdf',
                     as_attachment=True, download_name=filename)


@main_bp.route('/mobile-money-dashboard')
@roles_required('mobile_money_agent')
def mobile_money_dashboard():
    """Dashboard for mobile money agents to confirm payments manually."""
    return render_template('mobile_money_dashboard.html')


@main_bp.route('/mobile-money-vignettes')
@roles_required('mobile_money_agent')
def mobile_money_vignettes_page():
    """Dashboard for mobile money agents to accept vignette renewal payments."""
    return render_template('mobile_money_vignettes.html')


@main_bp.route('/mobile-money-qr-renewal')
@roles_required('mobile_money_agent')
def mobile_money_qr_renewal_page():
    """Page for mobile money agents to process QR code renewals."""
    from app.models import SmartTechSetting
    renewal_price = float(SmartTechSetting.get('qr_renewal_price', 3000) or 3000)
    return render_template('mobile_money_qr_renewal.html', renewal_price=renewal_price)


@main_bp.route('/mobile-money-archive')
@roles_required('mobile_money_agent')
def mobile_money_archive_page():
    """Archive page for mobile money agents showing paid fines and paid vignettes."""
    return render_template('mobile_money_archive.html')


@main_bp.route('/vignette-dashboard')
@roles_required('agent_impot')
def vignette_dashboard():
    """Dashboard for tax agents to monitor vehicle vignettes"""
    return render_template('vignette_dashboard.html')


@main_bp.route('/vignette-without')
@roles_required('agent_impot')
def vignette_without_dashboard():
    """Dashboard for tax agents to monitor vehicles without vignette"""
    return render_template('vignette_without_dashboard.html')


@main_bp.route('/insurance-profile')
@login_required
def insurance_profile():
    """Profile page for insurance accounts to update their information"""
    if not isinstance(current_user, InsuranceAccount) or not current_user.is_active:
        abort(403)
    return render_template('insurance_profile.html')


@main_bp.route('/insurance-reports')
@login_required
def insurance_reports():
    """Reports page for insurance accounts to view and print reports"""
    if not isinstance(current_user, InsuranceAccount) or not current_user.is_active:
        abort(403)
    return render_template('insurance_reports.html')


@main_bp.route('/insurance-attestation')
@login_required
def insurance_attestation():
    if not isinstance(current_user, InsuranceAccount) or not current_user.is_active:
        abort(403)
    return render_template('insurance_attestation.html')


@main_bp.route('/uninsured-vehicles')
@login_required
def uninsured_vehicles_page():
    """Page showing uninsured vehicles (insurance accounts only)"""
    # Check if user is an insurance account
    if not isinstance(current_user, InsuranceAccount) or not current_user.is_active:
        abort(403)
    return render_template('uninsured_vehicles.html')


@main_bp.route('/add-vehicle-insurance')
@login_required
def add_vehicle_insurance_page():
    """Page for insurance accounts to add new vehicles"""
    # Check if user is an insurance account
    if not isinstance(current_user, InsuranceAccount) or not current_user.is_active:
        abort(403)
    return render_template('add_vehicle_insurance.html')


@main_bp.route('/vehicles')
@roles_required('administrateur','judiciaire','dgrtr')
def vehicles_page():
    _require_dr_only()
    return render_template('vehicles.html')


@main_bp.route('/licenses')
@roles_required('administrateur', 'dgrtr')
def licenses_page():
    _require_dgrtr_staff()
    return render_template('licenses.html')


@main_bp.route('/dgrtr-dashboard')
@roles_required('administrateur', 'dgrtr')
def dgrtr_dashboard():
    _require_dgrtr_staff()
    return render_template('dgrtr_dashboard.html')


@main_bp.route('/dgrtr-statistiques')
@roles_required('administrateur', 'dgrtr')
def dgrtr_statistiques():
    if current_user.role == 'dgrtr' and getattr(current_user, 'dgrtr_type', None) not in ('directeur_technique', 'directeur_general'):
        abort(403)
    return render_template('dgrtr_stats.html')


@main_bp.route('/dgrtr-dossiers-complets')
@roles_required('administrateur', 'dgrtr')
def dgrtr_dossiers_complets():
    if current_user.role == 'dgrtr' and getattr(current_user, 'dgrtr_type', None) not in ('directeur_technique', 'directeur_general'):
        from flask import abort
        abort(403)
    return render_template('dgrtr_dossiers_complets.html')


@main_bp.route('/dgrtr/ajouter-permis')
@roles_required('administrateur', 'dgrtr')
def dgrtr_add_license():
    if current_user.role == 'dgrtr' and getattr(current_user, 'dgrtr_type', None) != 'employe':
        abort(403)
    return render_template('dgrtr_add_license.html')


def compute_category_expiries(lic, settings, main_expiry):
    """Return {code: 'DD/MM/YYYY'} for each owned category.
    If category_validity[code].mode == 'custom', expiry = date_obtention + years.
    Otherwise falls back to main_expiry (the license-level expiry date)."""
    from dateutil.relativedelta import relativedelta
    try:
        raw_details = json.loads(lic.category_details) if lic.category_details else {}
    except (ValueError, TypeError):
        raw_details = {}
    try:
        cat_validity = json.loads(settings.category_validity) if settings.category_validity else {}
    except (ValueError, TypeError):
        cat_validity = {}
    result = {}
    for code, det in raw_details.items():
        entry = cat_validity.get(code, {})
        expiry = None
        if entry.get('mode') == 'custom' and entry.get('years'):
            date_str = det.get('date')
            if date_str:
                try:
                    obtention = datetime.strptime(date_str, '%Y-%m-%d').date()
                    expiry = obtention + relativedelta(years=int(entry['years']))
                except Exception:
                    pass
        if expiry is None:
            expiry = main_expiry
        if expiry:
            result[code] = expiry.strftime('%d/%m/%Y')
    return result


@main_bp.route('/dgrtr/licenses/<int:license_id>/print-a4')
@roles_required('administrateur', 'dgrtr')
def dgrtr_license_print_a4(license_id):
    _require_dgrtr_staff()
    from app.models import DriverLicense, LicenseSetting
    from dateutil.relativedelta import relativedelta
    lic = DriverLicense.query.get_or_404(license_id)
    settings = LicenseSetting.get()
    category_details = parse_category_details(lic)
    months = settings.temp_validity_months or 12
    computed_expiry = lic.issue_date + relativedelta(months=months) if lic.issue_date else None
    main_expiry = lic.expiry_date or computed_expiry
    computed_cat_expiries = compute_category_expiries(lic, settings, main_expiry)
    # Le PDF A4 DGRTR est toujours un permis temporaire
    return render_template('dgrtr_license_a4.html', lic=lic, settings=settings,
                           category_details=category_details, force_temporaire=True,
                           computed_expiry=main_expiry,
                           computed_cat_expiries=computed_cat_expiries)


@main_bp.route('/licenses/<int:license_id>/qrcode')
@roles_required('administrateur', 'judiciaire', 'dgrtr')
def license_qrcode(license_id):
    from app.models import DriverLicense
    lic = DriverLicense.query.get_or_404(license_id)
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(lic.license_number)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')


def parse_category_details(lic):
    """Parse a DriverLicense.category_details JSON blob and reformat its
    date/expiration fields from ISO (YYYY-MM-DD) to display (DD/MM/YYYY)."""
    try:
        raw_details = json.loads(lic.category_details) if lic.category_details else {}
    except (ValueError, TypeError):
        raw_details = {}
    category_details = {}
    for cat, d in raw_details.items():
        formatted = dict(d)
        for field in ('date', 'expiration'):
            if d.get(field):
                try:
                    formatted[field] = datetime.strptime(d[field], '%Y-%m-%d').strftime('%d/%m/%Y')
                except ValueError:
                    pass
        category_details[cat] = formatted
    return category_details


@main_bp.route('/licenses/<int:license_id>/print')
@roles_required('administrateur', 'judiciaire', 'dgrtr')
def license_print(license_id):
    from app.models import DriverLicense, LicenseSetting
    from dateutil.relativedelta import relativedelta
    lic = DriverLicense.query.get_or_404(license_id)
    settings = LicenseSetting.get()
    force_temporaire = request.args.get('temporaire') == '1'
    computed_expiry = None
    if not lic.expiry_date and lic.issue_date:
        if force_temporaire or lic.type_permis == 'temporaire':
            computed_expiry = lic.issue_date + relativedelta(months=(settings.temp_validity_months or 12))
        else:
            computed_expiry = lic.issue_date + relativedelta(years=(settings.permanent_validity_years or 10))
    main_expiry = lic.expiry_date or computed_expiry
    computed_cat_expiries = compute_category_expiries(lic, settings, main_expiry)
    category_details = parse_category_details(lic)
    return render_template('license_print.html', lic=lic, settings=settings,
                           force_temporaire=force_temporaire, computed_expiry=computed_expiry,
                           computed_cat_expiries=computed_cat_expiries,
                           category_details=category_details)


@main_bp.route('/licenses/<int:license_id>/print-folded')
@roles_required('administrateur', 'judiciaire', 'dgrtr')
def license_print_folded(license_id):
    from app.models import DriverLicense, LicenseSetting
    from dateutil.relativedelta import relativedelta
    lic = DriverLicense.query.get_or_404(license_id)
    settings = LicenseSetting.get()
    computed_expiry = None
    if not lic.expiry_date and lic.issue_date:
        if lic.type_permis == 'temporaire':
            computed_expiry = lic.issue_date + relativedelta(months=(settings.temp_validity_months or 12))
        else:
            computed_expiry = lic.issue_date + relativedelta(years=(settings.permanent_validity_years or 10))
    main_expiry = lic.expiry_date or computed_expiry
    computed_cat_expiries = compute_category_expiries(lic, settings, main_expiry)
    category_details = parse_category_details(lic)
    return render_template('license_folded_card.html', lic=lic, settings=settings,
                           computed_expiry=computed_expiry, category_details=category_details,
                           computed_cat_expiries=computed_cat_expiries)


@main_bp.route('/licenses/insurance-view/<license_number>')
@login_required
def license_insurance_view(license_number):
    """View a folded license card for an insurance account (only for their registered drivers)."""
    from app.models import DriverLicense, LicenseSetting, VehicleInsuranceAssignment, InsuranceAccount
    from dateutil.relativedelta import relativedelta
    if not isinstance(current_user, InsuranceAccount):
        return jsonify({"error": "Forbidden"}), 403
    num = license_number.strip().upper()
    assignments = VehicleInsuranceAssignment.query.filter_by(insurance_account_id=current_user.id).all()
    allowed = set()
    for a in assignments:
        if a.driver_license_numbers:
            try:
                allowed.update(json.loads(a.driver_license_numbers))
            except Exception:
                pass
    if num not in allowed:
        return "Permis non autorisé", 403
    lic = DriverLicense.query.filter_by(license_number=num).first_or_404()
    settings = LicenseSetting.get()
    computed_expiry = None
    if not lic.expiry_date and lic.issue_date:
        if lic.type_permis == 'temporaire':
            computed_expiry = lic.issue_date + relativedelta(months=(settings.temp_validity_months or 12))
        else:
            computed_expiry = lic.issue_date + relativedelta(years=(settings.permanent_validity_years or 10))
    main_expiry = lic.expiry_date or computed_expiry
    computed_cat_expiries = compute_category_expiries(lic, settings, main_expiry)
    category_details = parse_category_details(lic)
    return render_template('license_folded_card.html', lic=lic, settings=settings,
                           computed_expiry=computed_expiry, category_details=category_details,
                           computed_cat_expiries=computed_cat_expiries)


@main_bp.route('/licenses/<int:license_id>/print-card')
@roles_required('administrateur', 'judiciaire', 'dgrtr')
def license_print_card(license_id):
    from app.models import DriverLicense, LicenseSetting
    from dateutil.relativedelta import relativedelta
    lic = DriverLicense.query.get_or_404(license_id)
    settings = LicenseSetting.get()
    computed_expiry = None
    if not lic.expiry_date and lic.issue_date:
        if lic.type_permis == 'temporaire':
            computed_expiry = lic.issue_date + relativedelta(months=(settings.temp_validity_months or 12))
        else:
            computed_expiry = lic.issue_date + relativedelta(years=(settings.permanent_validity_years or 10))
    main_expiry = lic.expiry_date or computed_expiry
    computed_cat_expiries = compute_category_expiries(lic, settings, main_expiry)
    category_details = parse_category_details(lic)
    return render_template('license_card.html', lic=lic, settings=settings, now_comoros=now_comoros,
                           computed_expiry=computed_expiry, category_details=category_details,
                           computed_cat_expiries=computed_cat_expiries)


@main_bp.route('/licenses/print-requests')
@roles_required('administrateur', 'judiciaire', 'dgrtr')
def license_print_requests_page():
    return render_template('license_print_requests.html')


@main_bp.route('/licenses/<int:license_id>/print-history')
@roles_required('administrateur', 'judiciaire', 'dgrtr')
def license_print_history(license_id):
    from app.models import DriverLicense, LicenseSetting, PointReductionHistory
    lic = DriverLicense.query.get_or_404(license_id)
    settings = LicenseSetting.get()
    history = PointReductionHistory.query.filter_by(license_id=license_id)\
        .order_by(PointReductionHistory.created_at.desc()).all()
    return render_template('license_print_history.html', lic=lic, settings=settings, history=history)


@main_bp.route('/reports')
@roles_required('administrateur','judiciaire','dgrtr')
def reports_page():
    _require_dr_only()
    return render_template('reports.html')


@main_bp.route('/fines')
@roles_required('administrateur','policier')
def fines_page():
    """Page d'administration des amandes/fines"""
    return render_template('fines.html')


@main_bp.route('/fines/stats')
@roles_required()
def fines_stats_page():
    """Page de statistiques des amandes"""
    return render_template('fines_stats.html')


@main_bp.route('/exoneration')
@roles_required('administrateur')
def exoneration_page():
    """Page de gestion des véhicules exonérés"""
    return render_template('exoneration.html')


@main_bp.route('/alerts')
@roles_required('policier', 'judiciaire', 'dgrtr')
def alerts_page():
    _require_dr_only()
    return render_template('alerts.html')


@main_bp.route('/recherche')
@roles_required('administrateur', 'policier')
def recherche_page():
    """Page de recherche de permis par véhicule (policier)"""
    return render_template('recherche.html')


@vehicle_bp.route('/stats', methods=['GET'])
@login_required
def get_vehicle_stats():
    """Retourner les statistiques des véhicules en JSON"""
    country = request.args.get('country', type=str)  # New country filter for admin
    
    query = db.session.query(Vehicle)
    query = apply_island_filter(query, Vehicle.owner_island, force_country=country)
    
    total_vehicles = query.with_entities(func.count(Vehicle.id)).scalar() or 0

    # Compter par type de véhicule
    vehicle_by_type = query.with_entities(
        Vehicle.vehicle_type,
        func.count(Vehicle.id).label('count')
    ).group_by(Vehicle.vehicle_type).all()

    # Compter par statut
    vehicle_by_status = query.with_entities(
        Vehicle.status,
        func.count(Vehicle.id).label('count')
    ).group_by(Vehicle.status).all()

    return jsonify({
        'total_vehicles': total_vehicles,
        'by_type': [{'type': v[0], 'count': v[1]} for v in vehicle_by_type],
        'by_status': [{'status': v[0], 'count': v[1]} for v in vehicle_by_status],
    })
@vehicle_bp.route('/list', methods=['GET'])
@login_required
def get_vehicles_list():
    """Retourner la liste des véhicules"""
    country = request.args.get('country', type=str)  # New country filter for admin

    query = Vehicle.query
    query = apply_island_filter(query, Vehicle.owner_island, force_country=country)
    vehicles = query.order_by(Vehicle.created_at.desc()).all()
    return jsonify([v.to_dict() for v in vehicles])


@vehicle_bp.route('/last-update', methods=['GET'])
@login_required
def vehicles_last_update():
    """Lightweight endpoint: returns the most recent updated_at and vehicle count.
    Used by the dashboard to detect changes without fetching all vehicle data."""
    from sqlalchemy import func
    country = request.args.get('country', type=str)
    query = Vehicle.query
    query = apply_island_filter(query, Vehicle.owner_island, force_country=country)
    result = query.with_entities(
        func.max(Vehicle.updated_at).label('last_update'),
        func.count(Vehicle.id).label('total')
    ).one()
    last_update = result.last_update.strftime('%Y-%m-%d %H:%M:%S') if result.last_update else ''
    return jsonify({'last_update': last_update, 'total': result.total})


@vehicle_bp.route('/<int:vehicle_id>', methods=['GET'])
@login_required
def get_vehicle_detail(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    d = vehicle.to_dict()
    d['fines'] = [f.to_dict() for f in vehicle.fines.filter_by(paid=False).all()]
    cg = getattr(vehicle, 'carte_grise', None)
    if cg:
        d['carte_grise'] = cg.to_dict()
    else:
        d['carte_grise'] = None
    return jsonify(d)


@vehicle_bp.route('/query', methods=['GET'])
@login_required
def query_vehicles():
    """Retourner une liste filtrée de véhicules selon query params"""
    q = request.args.get('q', type=str)
    vtype = request.args.get('type', type=str)
    status = request.args.get('status', type=str)
    start = request.args.get('start_date', type=str)
    end = request.args.get('end_date', type=str)
    country = request.args.get('country', type=str)  # New country filter for admin

    expired = request.args.get('expired', type=str)
    qr_expired = request.args.get('qr_expired', type=str)
    insurance_expired = request.args.get('insurance_expired', type=str)

    query = Vehicle.query
    query = apply_island_filter(query, Vehicle.owner_island, force_country=country)
    from app.models import SmartTechAccount
    if isinstance(current_user, SmartTechAccount):
        # Pending vehicles are only shown in "En attente d'activation QR", never in the main table
        query = query.filter(Vehicle.qr_pending_approval == False)
        if current_user.role == 'employe':
            emp_island = current_user.employee.island if current_user.employee else None
            if emp_island:
                query = query.filter(Vehicle.owner_island == emp_island)
    if vtype:
        query = query.filter(Vehicle.vehicle_type == vtype)
    if status:
        query = query.filter(Vehicle.status == status)
    if q:
        like = f"%{q}%"
        query = query.filter((Vehicle.license_plate.ilike(like)) | (Vehicle.owner_name.ilike(like)) | (Vehicle.vin.ilike(like)))
    # filter by creation date range
    if start:
        try:
            sd = datetime.fromisoformat(start)
            query = query.filter(Vehicle.created_at >= sd)
        except Exception:
            pass
    if end:
        try:
            ed = datetime.fromisoformat(end)
            query = query.filter(Vehicle.created_at <= ed)
        except Exception:
            pass
    # filter by expired vignette if requested
    if expired is not None:
        try:
            if expired.lower() in ('1','true','yes'):
                query = query.filter(Vehicle.vignette_expiry != None).filter(Vehicle.vignette_expiry <= now_comoros())
        except Exception:
            pass
    
    # filter by expired QR codes if requested
    if qr_expired is not None:
        try:
            if qr_expired.lower() in ('1','true','yes'):
                # include vehicles with qr_code_expiry set and before now
                query = query.filter(Vehicle.qr_code_expiry != None).filter(Vehicle.qr_code_expiry <= now_comoros())
        except Exception:
            pass
    
    # filter by expired insurance if requested
    if insurance_expired is not None:
        try:
            if insurance_expired.lower() in ('1','true','yes'):
                # include vehicles with insurance_expiry set and before now
                query = query.filter(Vehicle.insurance_expiry != None).filter(Vehicle.insurance_expiry <= now_comoros())
        except Exception:
            pass

    vehicles = query.order_by(Vehicle.created_at.desc()).all()
    return jsonify([v.to_dict() for v in vehicles])


@vehicle_bp.route('/export', methods=['GET'])
@login_required
def export_vehicles_csv():
    """Exporter les véhicules filtrés en CSV (utilise mêmes params que /query)."""
    # reuse query logic
    q = request.args.get('q', type=str)
    vtype = request.args.get('type', type=str)
    status = request.args.get('status', type=str)
    start = request.args.get('start_date', type=str)
    end = request.args.get('end_date', type=str)
    country = request.args.get('country', type=str)  # New country filter for admin

    expired = request.args.get('expired', type=str)
    qr_expired = request.args.get('qr_expired', type=str)
    insurance_expired = request.args.get('insurance_expired', type=str)
    
    query = Vehicle.query
    query = apply_island_filter(query, Vehicle.owner_island, force_country=country)
    if vtype:
        query = query.filter(Vehicle.vehicle_type == vtype)
    if status:
        query = query.filter(Vehicle.status == status)
    if q:
        like = f"%{q}%"
        query = query.filter((Vehicle.license_plate.ilike(like)) | (Vehicle.owner_name.ilike(like)) | (Vehicle.vin.ilike(like)))
    if start:
        try:
            sd = datetime.fromisoformat(start)
            query = query.filter(Vehicle.created_at >= sd)
        except Exception:
            pass
    if end:
        try:
            ed = datetime.fromisoformat(end)
            query = query.filter(Vehicle.created_at <= ed)
        except Exception:
            pass
    # handle expired filter for CSV export
    if expired is not None:
        try:
            if expired.lower() in ('1','true','yes'):
                query = query.filter(Vehicle.registration_expiry != None).filter(Vehicle.registration_expiry <= now_comoros())
        except Exception:
            pass
    
    # handle expired QR code filter
    if qr_expired is not None:
        try:
            if qr_expired.lower() in ('1','true','yes'):
                query = query.filter(Vehicle.qr_code_expiry != None).filter(Vehicle.qr_code_expiry <= now_comoros())
        except Exception:
            pass
    
    # handle expired insurance filter
    if insurance_expired is not None:
        try:
            if insurance_expired.lower() in ('1','true','yes'):
                query = query.filter(Vehicle.insurance_expiry != None).filter(Vehicle.insurance_expiry <= now_comoros())
        except Exception:
            pass

    vehicles = query.order_by(Vehicle.created_at.desc()).all()

    export = request.args.get('export', type=str)

    # If PDF requested and reportlab is available, produce a nicer PDF
    if export and export.lower() == 'pdf' and REPORTLAB_AVAILABLE:
        # compact vehicle export: only essential columns to keep PDF minimal
        headers = ['Immatriculation', 'Propriétaire', 'Type', 'Expiration Vignette']
        rows = []
        for v in vehicles:
            expiry_date = ''
            if v.registration_expiry:
                expiry_date = v.registration_expiry.strftime('%d/%m/%Y %H:%M')
            rows.append([
                v.license_plate or '',
                v.owner_name or '',
                v.vehicle_type or '',
                expiry_date
            ])
        buf = io.BytesIO()
        title_text = 'Export Véhicules'
        pdf_buf = _build_pdf_table(buf, title_text, headers, rows, landscape_mode=False)
        if pdf_buf:
            filename = f"vehicles_export_{now_comoros().strftime('%Y%m%d_%H%M%S')}.pdf"
            return send_file(pdf_buf, mimetype='application/pdf', download_name=filename, as_attachment=True)

    # build CSV
    si = io.StringIO()
    writer = csv.writer(si)
    # header
    writer.writerow(['id','license_plate','owner_name','vehicle_type','fuel_type','status','make','model','year','vin','color','owner_phone','owner_address','Expiration Vignette','created_at'])
    for v in vehicles:
        writer.writerow([
            v.id,
            v.license_plate,
            v.owner_name,
            v.vehicle_type,
            v.fuel_type or '',
            v.status,
            v.make or '',
            v.model or '',
            v.year or '',
            v.vin or '',
            v.color or '',
            v.owner_phone or '',
            v.owner_address or '',
            v.registration_expiry.isoformat() if v.registration_expiry else '',
            v.created_at.isoformat() if v.created_at else ''
        ])

    mem = io.BytesIO()
    mem.write(si.getvalue().encode('utf-8'))
    mem.seek(0)
    filename = f"vehicles_export_{now_comoros().strftime('%Y%m%d_%H%M%S')}.csv"
    return send_file(mem, mimetype='text/csv', download_name=filename, as_attachment=True)
@vehicle_bp.route('', methods=['POST'])
@login_required
def create_vehicle():
    """Créer un nouveau véhicule à partir des données JSON ou formulaire"""
    data = request.get_json() or request.form
    license_plate = data.get('license_plate')
    owner_name = data.get('owner_name')
    vehicle_type = data.get('vehicle_type')
    usage_type = data.get('usage_type', 'Personnelle')

    # extra fields
    make = data.get('make')
    model = data.get('model')
    year = data.get('year')
    vin = data.get('vin')
    fuel_type = data.get('fuel_type')
    owner_address = data.get('owner_address')
    registration_expiry = data.get('registration_expiry')
    vignette_expiry = data.get('vignette_expiry')
    insurance_company = data.get('insurance_company')
    insurance_expiry = data.get('insurance_expiry')
    fiscal_class = data.get('fiscal_class')
    cv_class = data.get('cv_class')

    owner_phone = (data.get('owner_phone') or '').strip()

    if not license_plate or not owner_name or not owner_phone or not vehicle_type:
        return jsonify({'error': 'license_plate, owner_name, owner_phone et vehicle_type requis'}), 400

    # Vérifier unicité immatriculation
    if Vehicle.query.filter_by(license_plate=license_plate).first():
        return jsonify({'error': 'Véhicule avec cette immatriculation existe déjà'}), 400

    vehicle = Vehicle(
        license_plate=license_plate,
        owner_name=owner_name,
        owner_phone=data.get('owner_phone'),
        owner_island=data.get('owner_island'),
        vehicle_type=vehicle_type,
        fuel_type=fuel_type,
        usage_type=usage_type,
        color=data.get('color'),
        status=data.get('status') or 'active',
        make=make,
        model=model,
        year=year,
        vin=vin,
        owner_address=owner_address,
        insurance_company=insurance_company,
        fiscal_class=fiscal_class,
        cv_class=cv_class
    )
    # Use vignette_expiry as the source of truth for vignette management.
    # Keep compatibility with older clients that may still send registration_expiry.
    if not vignette_expiry and registration_expiry:
        vignette_expiry = registration_expiry
    # parse registration_expiry if provided
    if registration_expiry:
        try:
            from datetime import datetime
            vehicle.registration_expiry = datetime.fromisoformat(registration_expiry)
        except Exception:
            pass
    if vignette_expiry:
        # Force vignette expiry to March 31st (Comores regulation)
        vehicle.vignette_expiry = get_vignette_expiry_date(now_comoros())
    # parse insurance_expiry if provided
    if insurance_expiry:
        try:
            from datetime import datetime
            vehicle.insurance_expiry = datetime.fromisoformat(insurance_expiry)
        except Exception:
            pass
    if current_user and getattr(current_user, 'is_authenticated', False):
        vehicle.created_by = getattr(current_user, 'username', None)
    vehicle.qr_pending_approval = True
    db.session.add(vehicle)
    db.session.flush()  # Flush to get the vehicle ID before committing
    
    # Auto-assign to insurance account if insurance_company is provided
    if insurance_company and insurance_company.strip() and insurance_company != 'Autre':
        try:
            # Find the insurance by company name
            insurance = Insurance.query.filter_by(company_name=insurance_company).first()
            if insurance and insurance.accounts:
                # Use the first account for this insurance
                account = insurance.accounts[0]
                assignment = VehicleInsuranceAssignment(
                    vehicle_id=vehicle.id,
                    insurance_account_id=account.id,
                    assigned_by='system',
                    notes='Auto-assigned on vehicle creation'
                )
                db.session.add(assignment)
        except Exception as e:
            # Log but don't fail vehicle creation if assignment fails
            print(f"Warning: Could not auto-assign vehicle to insurance account: {e}")
    
    db.session.commit()

    # Create CarteGrise record with complementary fields from payload
    try:
        from app.models import CarteGrise as _CG
        from datetime import datetime as _cg_dt
        _s = lambda k: (data.get(k) or '').strip()
        cg = _CG.query.filter_by(vehicle_id=vehicle.id).first()
        if cg is None:
            cg = _CG(vehicle_id=vehicle.id, status='brouillon',
                     created_by=getattr(current_user, 'username', ''))
            db.session.add(cg)
        cg.carrosserie             = _s('carrosserie') or None
        cg.places_assises          = _s('places_assises') or None
        cg.poids_total_autorise    = _s('poids_total_autorise') or None
        cg.poids_a_vide            = _s('poids_a_vide') or None
        cg.charge_utile_ptc        = _s('charge_utile_ptc') or None
        cg.profession_proprietaire = _s('profession_proprietaire') or None
        cg.observation             = _s('observation') or None
        raw_de = _s('date_emission')
        if raw_de:
            try:
                cg.date_emission = _cg_dt.strptime(raw_de, '%Y-%m-%d').date()
            except Exception:
                pass
        db.session.commit()
    except Exception as e:
        print(f'Warning: CarteGrise creation failed for vehicle {vehicle.id}: {e}')

    if vehicle.owner_phone:
        _sync_vehicle_owner_link(vehicle)

    # Log action in user history
    try:
        from app.models import UserHistory
        user_history = UserHistory(
            user_id=current_user.id,
            action='Véhicule créé',
            details=f'Véhicule {vehicle.license_plate} - {owner_name} ({vehicle_type})'
        )
        db.session.add(user_history)
        db.session.commit()
    except Exception as e:
        print(f'Error logging vehicle creation: {e}')

    return jsonify({'message': 'Vehicle created successfully', 'vehicle': vehicle.to_dict()}), 201
@vehicle_bp.route('/lookup-vin', methods=['GET'])
@login_required
def lookup_vehicle_by_vin():
    from app.models import Fine
    vin = request.args.get('vin', '').strip()
    if not vin:
        return jsonify({'vehicle': None})
    vehicle = Vehicle.query.filter(Vehicle.vin.ilike(vin)).first()
    if not vehicle:
        return jsonify({'vehicle': None})
    unpaid = Fine.query.filter_by(vehicle_id=vehicle.id, paid=False).order_by(Fine.issued_at.desc()).all()
    return jsonify({'vehicle': {
        'id': vehicle.id,
        'license_plate': vehicle.license_plate,
        'owner_name': vehicle.owner_name,
        'fines': [f.to_dict() for f in unpaid],
    }})


@vehicle_bp.route('/<int:vehicle_id>', methods=['GET'])
@login_required
def get_vehicle(vehicle_id):
    from app.models import Fine
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    check_island_access(vehicle.owner_island)
    fines = Fine.query.filter_by(vehicle_id=vehicle.id).order_by(Fine.issued_at.desc()).all()
    return jsonify({**vehicle.to_dict(), 'fines': [f.to_dict() for f in fines]})


@vehicle_bp.route('/<int:vehicle_id>/history', methods=['GET'])
@login_required
def get_vehicle_history(vehicle_id):
    from app.models import VehicleHistory
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    check_island_access(vehicle.owner_island)
    from app.models import VehicleHistory, Fine
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    hist = VehicleHistory.query.filter_by(vehicle_id=vehicle.id).order_by(VehicleHistory.created_at.desc()).all()
    fines = Fine.query.filter_by(vehicle_id=vehicle.id).order_by(Fine.issued_at.desc()).all()
    items = []
    for h in hist:
        items.append({'type':'history','created_at':h.created_at.isoformat(),'action':h.action,'officer':h.officer,'notes':h.notes})
    for f in fines:
        items.append({'type':'fine','created_at':f.issued_at.isoformat(),'amount':float(f.amount),'reason':f.reason,'officer':f.officer,'paid':f.paid,'notes':f.notes})
    items.sort(key=lambda x: x['created_at'], reverse=True)
    return jsonify(items)


@vehicle_bp.route('/<int:vehicle_id>/fines', methods=['POST'])
@login_required
def create_fine(vehicle_id):
    from app.models import Fine, VehicleHistory, ExoneratedVehicle
    from app.sms_service import sms_service
    from app.push_notifications import send_fine_push_notification
    
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    check_island_access(vehicle.owner_island)
    data = request.get_json() or request.form
    # Use the authenticated user's username as the officer to prevent spoofing
    try:
        from flask_login import current_user
        officer = current_user.username if (current_user and getattr(current_user, 'is_authenticated', False)) else (data.get('officer') or '')
    except Exception:
        officer = data.get('officer')
    notes = data.get('notes')
    # Parse amount and reason
    amount = data.get('amount')
    try:
        amount = float(amount)
    except Exception:
        amount = 0.0
    reason = data.get('reason')
    if not reason or amount <= 0:
        return jsonify({'error':'reason et amount requis'}), 400
    
    # Check if vehicle is exonerated
    exonerated = ExoneratedVehicle.query.filter_by(vehicle_id=vehicle.id).first()
    is_exonerated = exonerated is not None
    
    fine = Fine(vehicle_id=vehicle.id, amount=amount, base_amount=amount, reason=reason, officer=officer, notes=notes)
    
    # If vehicle is exonerated, mark it for automatic deletion after 60 minutes
    # (will be deleted automatically by background task - no trace left)
    if is_exonerated:
        # Add a note indicating this fine will be auto-deleted after 60 minutes
        if notes:
            fine.notes = f"{notes}\n[EXONÉRÉ - Suppression automatique après 60 min]"
        else:
            fine.notes = "[EXONÉRÉ - Suppression automatique après 60 min]"
    
    db.session.add(fine)
    
    # also add a history entry
    action_text = f"Amande émise: {reason} ({amount})"
    hist = VehicleHistory(vehicle_id=vehicle.id, action=action_text, officer=officer, notes=notes)
    db.session.add(hist)
    db.session.commit()
    
    # Log action in user history
    try:
        from app.models import UserHistory
        user_history = UserHistory(
            user_id=current_user.id,
            action='Amende émise',
            details=f'Amende #{fine.id} pour {vehicle.license_plate}: {reason} ({amount} KMF)'
        )
        db.session.add(user_history)
        db.session.commit()
    except Exception as e:
        print(f'Error logging fine creation: {e}')
    
    # Send SMS notification to vehicle owner
    try:
        sms_result = sms_service.send_fine_notification(vehicle, fine)
        print(f"✉️  SMS Notification Result: {sms_result}")
    except Exception as e:
        print(f"❌ SMS Notification Error: {str(e)}")
        sms_result = {'success': False, 'message': str(e)}

    # Send push notification to the current citizen device, if registered
    try:
        push_result = send_fine_push_notification(vehicle, fine)
        print(f"📲 Push Notification Result: {push_result}")
    except Exception as e:
        print(f"❌ Push Notification Error: {str(e)}")
        push_result = {'success': False, 'message': str(e)}
    
    return jsonify({
        'fine': fine.to_dict(), 
        'history': hist.to_dict(),
        'is_exonerated': is_exonerated,
        'sms_sent': sms_result.get('success', False),
        'sms_message': sms_result.get('message', ''),
        'push_sent': push_result.get('success', False),
        'push_message': push_result.get('message', '')
    }), 201

@vehicle_bp.route('/<int:vehicle_id>/fines', methods=['GET'])
@login_required
def list_fines(vehicle_id):
    from app.models import Fine
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    check_island_access(vehicle.owner_island)
    fines = Fine.query.filter_by(vehicle_id=vehicle.id).order_by(Fine.issued_at.desc()).all()
    result = []
    for f in fines:
        d = f.to_dict()
        try:
            d['license_plate'] = f.vehicle.license_plate
            d['owner_name'] = f.vehicle.owner_name
            d['vehicle_id'] = f.vehicle_id
            d['track_token'] = f.vehicle.track_token
        except Exception:
            d['license_plate'] = None
            d['owner_name'] = None
            d['vehicle_id'] = None
            d['track_token'] = None
        result.append(d)
    return jsonify(result)


@vehicle_bp.route('/fines/all', methods=['GET'])
@login_required
def list_all_fines():
    from app.models import Fine, Vehicle
    allowed_roles = ('administrateur', 'judiciaire', 'policier', 'mobile_money_agent')
    role = getattr(current_user, 'role', None)
    if role not in allowed_roles and not getattr(current_user, 'is_admin', False):
        abort(403)

    # optional filters
    q = request.args.get('q', type=str)
    paid = request.args.get('paid', type=str)
    export = request.args.get('export', type=str)
    start_date = request.args.get('start_date', type=str)
    end_date = request.args.get('end_date', type=str)
    country = request.args.get('country', type=str)  # New country filter for admin
    
    # Debug logging
    print(f"[FINES EXPORT] Received params - start_date: {start_date}, end_date: {end_date}, paid: {paid}, export: {export}")

    query = Fine.query.join(Vehicle)
    query = apply_island_filter(query, Vehicle.owner_island, force_country=country)
    if q:
        like = f"%{q}%"
        query = query.filter((Vehicle.license_plate.ilike(like)) | (Vehicle.owner_name.ilike(like)))
    if paid is not None:
        if paid.lower() in ('1','true','yes'):
            query = query.filter(Fine.paid.is_(True))
        elif paid.lower() in ('0','false','no'):
            query = query.filter(Fine.paid.is_(False))
    
    # Filter by date range if provided
    if start_date and end_date:
        try:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            # End date at 23:59:59
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            end_dt = end_dt.replace(hour=23, minute=59, second=59)
            print(f"[FINES EXPORT] Applying date filter: {start_dt} to {end_dt}")
            # Filter by date range
            query = query.filter(
                Fine.paid_at.isnot(None),
                Fine.paid_at >= start_dt,
                Fine.paid_at <= end_dt
            )
        except ValueError as e:
            print(f"[FINES EXPORT] Error parsing dates: {e}")

    fines = query.order_by(Fine.issued_at.desc()).all()
    print(f"[FINES EXPORT] Found {len(fines)} fines after filtering")
    result = []
    for f in fines:
        d = f.to_dict()
        try:
            d['license_plate'] = f.vehicle.license_plate
            d['track_token'] = f.vehicle.track_token
            d['status'] = f.vehicle.status
            # Add QR code expiry information
            d['qr_code_expiry'] = f.vehicle.qr_code_expiry.isoformat() if f.vehicle.qr_code_expiry else None
            d['is_qr_expired'] = f.vehicle.is_qr_code_expired()
        except Exception as e:
            print(f"[FINES] Error loading vehicle for fine {f.id}: {e}")
            d['license_plate'] = None
            d['track_token'] = None
            d['status'] = None
            d['qr_code_expiry'] = None
            d['is_qr_expired'] = False
        result.append(d)
    # support CSV export for paid fines archive
    if export and export.lower() == 'pdf' and REPORTLAB_AVAILABLE:
        # build a nicer PDF for fines
        headers = ['Immatriculation', 'Motif', 'Montant (KMF)', 'Émis le', 'Payée le', 'Agent']
        rows = []
        total_amount = 0.0
        
        for d in result:
            issued_date = ''
            if d.get('issued_at'):
                try:
                    # Parse ISO date and format to French
                    dt = datetime.fromisoformat(d['issued_at'].replace('Z', '+00:00'))
                    issued_date = dt.strftime('%d/%m/%Y')
                except:
                    issued_date = d.get('issued_at') or ''
            
            paid_date = ''
            if d.get('paid_at'):
                try:
                    dt = datetime.fromisoformat(d['paid_at'].replace('Z', '+00:00'))
                    paid_date = dt.strftime('%d/%m/%Y')
                except:
                    paid_date = d.get('paid_at') or ''
            
            amount = d.get('amount') or 0
            total_amount += float(amount)
            
            rows.append([
                d.get('license_plate') or '',
                d.get('reason') or '',
                f"{int(amount):,}".replace(',', ' '),
                issued_date,
                paid_date,
                d.get('officer') or ''
            ])

        if start_date and end_date:
            buffer = io.BytesIO()
            try:
                start_formatted = datetime.strptime(start_date, '%Y-%m-%d').strftime('%d/%m/%Y')
                end_formatted = datetime.strptime(end_date, '%Y-%m-%d').strftime('%d/%m/%Y')
                title_text = f'Rapport des Amendes Payées<br/><font size="12">Période: {start_formatted} - {end_formatted}</font>'
            except:
                title_text = 'Rapport des Amendes Payées'
        else:
            title_text = 'Rapport Complet des Amendes Payées<br/><font size="12">Toutes les archives</font>'
        
        pdf_buf = _build_pdf_table(buffer, title_text, headers, rows, landscape_mode=True)
        if pdf_buf:
            filename = f"fines_report_{now_comoros().strftime('%Y%m%d_%H%M%S')}.pdf"
            return send_file(pdf_buf, mimetype='application/pdf', download_name=filename, as_attachment=True)

    if export and export.lower() == 'csv':
        # build CSV in memory
        si = io.StringIO()
        writer = csv.writer(si)
        writer.writerow(['id','license_plate','amount','reason','issued_at','paid_at','receipt_number','officer','notes'])
        for d in result:
            writer.writerow([
                d.get('id'),
                d.get('license_plate'),
                d.get('amount'),
                d.get('reason'),
                d.get('issued_at'),
                d.get('paid_at') or '',
                d.get('receipt_number') or '',
                d.get('officer') or '',
                d.get('notes') or ''
            ])
        mem = io.BytesIO()
        mem.write(si.getvalue().encode('utf-8'))
        mem.seek(0)
        filename = f"fines_archive_{now_comoros().strftime('%Y%m%d_%H%M%S')}.csv"
        return send_file(mem, mimetype='text/csv', download_name=filename, as_attachment=True)

    return jsonify(result)


@vehicle_bp.route('/fines/articles', methods=['GET', 'POST'])
@login_required
def manage_fine_articles():
    """GET: list fine articles. POST: create a new fine article."""
    from app.models import FineArticle
    if request.method == 'GET':
        articles = FineArticle.query.order_by(FineArticle.code).all()
        return jsonify([a.to_dict() for a in articles])
    data = request.get_json() or request.form
    code = (data.get('code') or '').strip()
    description = (data.get('description') or '').strip()
    if not code:
        return jsonify({'error': 'code requis'}), 400
    article = FineArticle(code=code, description=description or None)
    db.session.add(article)
    db.session.commit()
    return jsonify(article.to_dict()), 201


@vehicle_bp.route('/fines/articles/<int:article_id>', methods=['PUT', 'DELETE'])
@login_required
def fine_article_detail(article_id):
    from app.models import FineArticle
    article = FineArticle.query.get_or_404(article_id)
    if request.method == 'DELETE':
        db.session.delete(article)
        db.session.commit()
        return jsonify({'message': 'Supprimé'})
    data = request.get_json() or request.form
    if 'code' in data:
        article.code = (data['code'] or '').strip()
    if 'description' in data:
        article.description = (data['description'] or '').strip() or None
    db.session.commit()
    return jsonify(article.to_dict())


@vehicle_bp.route('/fines/types', methods=['GET', 'POST'])
@login_required
def manage_fine_types():
    """GET: list fine types. POST: create a new fine type."""
    from app.models import FineType
    if request.method == 'GET':
        types = FineType.query.order_by(FineType.label).all()
        return jsonify([t.to_dict() for t in types])
    # POST: create
    data = request.get_json() or request.form
    label = data.get('label')
    amount = data.get('amount')
    code = data.get('code')
    article_id = data.get('article_id') or None
    if not label or not amount:
        return jsonify({'error': 'label et amount requis'}), 400
    try:
        amt = Decimal(str(amount))
    except Exception:
        return jsonify({'error': 'Montant invalide'}), 400
    ft = FineType(label=label, amount=amt, code=code,
                  article_id=int(article_id) if article_id else None)
    db.session.add(ft)
    db.session.commit()
    return jsonify(ft.to_dict()), 201


@vehicle_bp.route('/fines/types/<int:type_id>', methods=['PUT', 'DELETE'])
@login_required
def fine_type_detail(type_id):
    from app.models import FineType
    ft = FineType.query.get_or_404(type_id)
    if request.method == 'DELETE':
        db.session.delete(ft)
        db.session.commit()
        return jsonify({'message': 'Supprimé'})
    # PUT update
    data = request.get_json() or request.form
    if 'label' in data:
        ft.label = data.get('label')
    if 'amount' in data:
        try:
            ft.amount = Decimal(str(data.get('amount')))
        except Exception:
            return jsonify({'error': 'Montant invalide'}), 400
    if 'code' in data:
        ft.code = data.get('code')
    if 'article_id' in data:
        ft.article_id = int(data['article_id']) if data['article_id'] else None
    db.session.commit()
    return jsonify(ft.to_dict())


# Mark a fine as paid and create a receipt + history entry
def _apply_fine_payment(fine, paid_by, payment_method=''):
    fine.paid = True
    fine.paid_at = now_comoros()
    fine.paid_by = paid_by
    fine.receipt_number = f"REC-{fine.id}-{int(fine.paid_at.timestamp())}"
    db.session.add(fine)

    hist = VehicleHistory(
        vehicle_id=fine.vehicle_id,
        action=f"Amande payée ({fine.receipt_number}) - {format_kmf_amount(fine.amount)} KMF",
        officer=paid_by,
        notes=(payment_method or '')
    )
    db.session.add(hist)
    return hist


@vehicle_bp.route('/fines/<int:fine_id>/reason', methods=['PATCH'])
@login_required
def update_fine_reason(fine_id):
    from app.models import Fine, VehicleHistory
    from decimal import Decimal
    fine = Fine.query.get_or_404(fine_id)
    age = (now_comoros() - ensure_comoros(fine.issued_at)).total_seconds()
    if age > 3 * 24 * 3600:
        return jsonify({'error': 'Le motif ne peut être modifié que dans les 3 jours suivant l\'émission.'}), 403
    data = request.get_json() or {}
    new_reason = (data.get('reason') or '').strip()
    if not new_reason:
        return jsonify({'error': 'Le motif ne peut pas être vide.'}), 400
    old_reason = fine.reason
    old_amount = float(fine.amount)
    fine.reason = new_reason
    new_amount = old_amount
    if data.get('amount') is not None:
        try:
            new_amount = float(data['amount'])
            fine.amount = Decimal(str(new_amount))
        except (ValueError, TypeError):
            pass
    officer = getattr(current_user, 'username', 'inconnu')
    notes = f'Ancien motif : « {old_reason} » ({int(old_amount)} KMF) → Nouveau : « {new_reason} » ({int(new_amount)} KMF)'
    db.session.add(VehicleHistory(
        vehicle_id=fine.vehicle_id,
        action=f'Amende #{fine.id} modifiée',
        officer=officer,
        notes=notes
    ))
    db.session.commit()
    return jsonify({'ok': True, 'reason': fine.reason, 'amount': float(fine.amount)})


@vehicle_bp.route('/fines/<int:fine_id>/pay', methods=['POST'])
@login_required
def pay_fine(fine_id):
    from app.models import Fine
    allowed_roles = ('administrateur', 'judiciaire', 'policier', 'mobile_money_agent')
    role = getattr(current_user, 'role', None)
    if role not in allowed_roles and not getattr(current_user, 'is_admin', False):
        return jsonify({'error': 'Accès refusé'}), 403

    fine = Fine.query.get_or_404(fine_id)
    if fine.paid:
        return jsonify({'error': 'Amande déjà payée'}), 400
    
    # Check if vehicle QR code is expired
    vehicle = fine.vehicle
    if vehicle and vehicle.is_qr_code_expired():
        return jsonify({'error': 'Impossible de payer: le code QR du véhicule est expiré. Veuillez renouveler le code QR.'}), 400
    
    data = request.get_json() or request.form
    # optional: payment_method, paid_by
    payment_method = data.get('payment_method')
    paid_by = data.get('paid_by') or current_user.username if current_user and current_user.is_authenticated else None

    # mark paid
    hist = _apply_fine_payment(fine, paid_by, payment_method)
    db.session.commit()
    
    # Log action in user history
    try:
        from app.models import UserHistory
        user_history = UserHistory(
            user_id=current_user.id,
            action='Amende payée',
            details=f'Amende #{fine.id} ({fine.receipt_number}): {fine.vehicle.license_plate} - {format_kmf_amount(fine.amount)} KMF'
        )
        db.session.add(user_history)
        db.session.commit()
    except Exception as e:
        print(f'Error logging fine payment: {e}')

    # return updated fine and history
    resp = {'fine': fine.to_dict(), 'history': hist.to_dict()}
    return jsonify(resp), 200


@vehicle_bp.route('/<int:vehicle_id>/fines/pay-all', methods=['POST'])
@login_required
def pay_all_fines_for_vehicle(vehicle_id):
    from app.models import Fine, Vehicle, VehicleHistory

    allowed_roles = ('administrateur', 'judiciaire', 'policier', 'mobile_money_agent')
    role = getattr(current_user, 'role', None)
    if role not in allowed_roles and not getattr(current_user, 'is_admin', False):
        return jsonify({'error': 'Accès refusé'}), 403

    vehicle = Vehicle.query.get_or_404(vehicle_id)
    try:
        check_island_access(vehicle.owner_island)
    except Exception:
        return jsonify({'error': 'Accès refusé pour ce véhicule'}), 403

    # Check if vehicle QR code is expired
    if vehicle.is_qr_code_expired():
        return jsonify({'error': 'Impossible de payer: le code QR du véhicule est expiré. Veuillez renouveler le code QR.'}), 400

    unpaid_fines = Fine.query.filter_by(vehicle_id=vehicle.id, paid=False).order_by(Fine.issued_at.asc()).all()
    if not unpaid_fines:
        return jsonify({'error': 'Aucune amende impayée pour ce véhicule'}), 400

    data = request.get_json() or request.form
    payment_method = data.get('payment_method') or 'mobile_money_manual'
    paid_by = data.get('paid_by') or (current_user.username if current_user and current_user.is_authenticated else None)

    paid_items = []
    total_amount = 0.0
    for fine in unpaid_fines:
        total_amount += float(fine.amount or 0)
        _apply_fine_payment(fine, paid_by, payment_method)
        paid_items.append({
            'id': fine.id,
            'receipt_number': fine.receipt_number,
            'amount': float(fine.amount),
        })

    db.session.add(VehicleHistory(
        vehicle_id=vehicle.id,
        action=f"Paiement groupé de {len(paid_items)} amende(s) - {format_kmf_amount(total_amount)} KMF",
        officer=paid_by,
        notes=payment_method
    ))
    db.session.commit()

    return jsonify({
        'ok': True,
        'vehicle_id': vehicle.id,
        'license_plate': vehicle.license_plate,
        'paid_count': len(paid_items),
        'total_amount': total_amount,
        'paid_items': paid_items,
        'first_fine_id': paid_items[0]['id'],
        'message': 'Paiement groupé confirmé.'
    })


@vehicle_bp.route('/fines/stats', methods=['GET'])
@login_required
def get_fines_stats():
    """Retourner les statistiques des amendes en JSON"""
    from app.models import Fine
    from sqlalchemy import func, extract
    from datetime import datetime, timedelta
    
    country = request.args.get('country', type=str)  # New country filter for admin

    try:
        # Build base query with island filter for judiciaire users
        base_query = db.session.query(Fine).join(Vehicle)
        base_query = apply_island_filter(base_query, Vehicle.owner_island, force_country=country)
        
        # Statistiques générales
        total_fines = base_query.with_entities(func.count(Fine.id)).scalar() or 0
        paid_fines = base_query.filter(Fine.paid == True).with_entities(func.count(Fine.id)).scalar() or 0
        unpaid_fines = total_fines - paid_fines

        # Utiliser coalesce pour éviter les None
        total_amount_result = base_query.with_entities(func.coalesce(func.sum(Fine.amount), 0)).scalar()
        total_amount = float(total_amount_result) if total_amount_result else 0

        paid_amount_result = base_query.filter(Fine.paid == True).with_entities(func.coalesce(func.sum(Fine.amount), 0)).scalar()
        paid_amount = float(paid_amount_result) if paid_amount_result else 0

        unpaid_amount = total_amount - paid_amount

        # Statistiques par agent (officer)
        officer_stats = base_query.with_entities(
            Fine.officer,
            func.count(Fine.id).label('count'),
            func.coalesce(func.sum(Fine.amount), 0).label('total_amount')
        ).filter(Fine.officer.isnot(None)).group_by(Fine.officer).order_by(func.count(Fine.id).desc()).all()

        # Statistiques mensuelles (derniers 12 mois)
        now = now_comoros()  # Utiliser la même fonction que le modèle
        monthly_stats = []
        for i in range(11, -1, -1):
            month_start = (now - timedelta(days=30*i)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)

            month_query = base_query.filter(
                Fine.issued_at >= month_start,
                Fine.issued_at <= month_end
            )
            month_fines = month_query.with_entities(func.count(Fine.id)).scalar() or 0

            month_paid = month_query.filter(Fine.paid == True).with_entities(func.count(Fine.id)).scalar() or 0

            monthly_stats.append({
                'month': month_start.strftime('%Y-%m'),
                'total': month_fines,
                'paid': month_paid,
                'unpaid': month_fines - month_paid
            })

        # Statistiques par motif (reason)
        reason_stats = base_query.with_entities(
            Fine.reason,
            func.count(Fine.id).label('count'),
            func.coalesce(func.sum(Fine.amount), 0).label('total_amount')
        ).group_by(Fine.reason).order_by(func.count(Fine.id).desc()).limit(10).all()

        # Statistiques de paiement (derniers 30 jours)
        thirty_days_ago = now - timedelta(days=30)
        recent_payments = base_query.filter(
            Fine.paid_at >= thirty_days_ago
        ).with_entities(func.count(Fine.id)).scalar() or 0

        return jsonify({
            'general': {
                'total_fines': total_fines,
                'paid_fines': paid_fines,
                'unpaid_fines': unpaid_fines,
                'total_amount': total_amount,
                'paid_amount': paid_amount,
                'unpaid_amount': unpaid_amount
            },
            'officers': [{
                'name': stat[0] or 'Non spécifié',
                'count': stat[1],
                'total_amount': float(stat[2]) if stat[2] else 0
            } for stat in officer_stats],
            'monthly': monthly_stats,
            'reasons': [{
                'reason': stat[0] or 'Non spécifié',
                'count': stat[1],
                'total_amount': float(stat[2]) if stat[2] else 0
            } for stat in reason_stats],
            'recent_payments': recent_payments
        })

    except Exception as e:
        print(f"Erreur dans get_fines_stats: {str(e)}")
        return jsonify({'error': f'Erreur serveur: {str(e)}'}), 500


@vehicle_bp.route('/<int:vehicle_id>/qrcode', methods=['GET'])
@login_required
def get_vehicle_qrcode(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    check_island_access(vehicle.owner_island)

    if vehicle.qr_pending_approval:
        return jsonify({'error': 'QR Code en attente de validation SmartTech.'}), 403

    # Initialize QR code expiry if not already set
    if not vehicle.qr_code_expiry:
        vehicle.generate_qr_code_with_expiry()
        db.session.commit()
        _record_qr_payment(vehicle, 'activation', current_user.username)

    # URL publique de suivi
    track_url = vehicle.license_plate
    # Générer QR code PNG
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(track_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png', download_name=f'{vehicle.license_plate}_qrcode.png')


@vehicle_bp.route('/<int:vehicle_id>/qrcode/pdf', methods=['GET'])
@login_required
def get_vehicle_qrcode_pdf(vehicle_id):
    """Retourne un PDF avec QR code + numéro d'immatriculation + texte descriptif"""
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    check_island_access(vehicle.owner_island)

    if vehicle.qr_pending_approval:
        return jsonify({'error': 'QR Code en attente de validation SmartTech.'}), 403

    if not REPORTLAB_AVAILABLE:
        return jsonify({'error': 'PDF generation not available'}), 500
    
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib.enums import TA_CENTER


        # Générer QR code avec numéro d'immatriculation intégré
        qr_img = _make_qr_with_plate(vehicle.license_plate, vehicle.license_plate)
        qr_buf = io.BytesIO()
        qr_img.save(qr_buf, format='PNG')
        qr_buf.seek(0)

        pdf_buf = io.BytesIO()
        card_size = (10*cm, 10*cm)
        doc = SimpleDocTemplate(
            pdf_buf, pagesize=card_size,
            topMargin=0.4*cm, bottomMargin=0.35*cm,
            leftMargin=0.4*cm, rightMargin=0.4*cm
        )
        styles = getSampleStyleSheet()

        footer_style = ParagraphStyle(
            'QRFooter', parent=styles['Normal'],
            fontSize=7, textColor=colors.HexColor('#555555'),
            alignment=TA_CENTER, fontName='Helvetica-Oblique', leading=9,
        )
        qr_big = RLImage(qr_buf, width=8.0*cm, height=8.0*cm)
        qr_band = Table([[qr_big]], colWidths=[9.2*cm], rowHeights=[8.28*cm])
        qr_band.setStyle(TableStyle([
            ('ALIGN',         (0,0), (-1,-1), 'CENTER'),
            ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
            ('BACKGROUND',    (0,0), (-1,-1), colors.white),
            ('TOPPADDING',    (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ]))

        footer_band = Table(
            [[Paragraph('Brigade Mobile — Comores', footer_style)]],
            colWidths=[9.2*cm], rowHeights=[0.46*cm]
        )
        footer_band.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,-1), colors.HexColor('#eef2ff')),
            ('TOPPADDING',    (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ]))

        card = Table(
            [[qr_band], [footer_band]],
            colWidths=[9.2*cm],
            rowHeights=[8.28*cm, 0.46*cm],
        )
        card.setStyle(TableStyle([
            ('BOX',           (0,0), (-1,-1), 1.5, colors.HexColor('#003399')),
            ('NOSPLIT',       (0,0), (-1,-1)),
            ('TOPPADDING',    (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
            ('LEFTPADDING',   (0,0), (-1,-1), 0),
            ('RIGHTPADDING',  (0,0), (-1,-1), 0),
        ]))

        doc.build([card])
        pdf_buf.seek(0)

        return send_file(pdf_buf, mimetype='application/pdf', download_name=f'qrcode_{vehicle.track_token[:8]}.pdf')
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@vehicle_bp.route('/<int:vehicle_id>/sheet.pdf', methods=['GET'])
@login_required
def vehicle_sheet_pdf(vehicle_id):
    """Fiche complète véhicule : infos + QR code"""
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    check_island_access(vehicle.owner_island)

    if not REPORTLAB_AVAILABLE:
        return jsonify({'error': 'PDF generation not available'}), 500

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage, HRFlowable
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib.enums import TA_CENTER, TA_LEFT

        # ── QR code ──────────────────────────────────────────────────────────
        if not vehicle.qr_code_expiry:
            vehicle.generate_qr_code_with_expiry()
            db.session.commit()
            _record_qr_payment(vehicle, 'activation', current_user.username)

        track_url = vehicle.license_plate
        qr = qrcode.QRCode(box_size=6, border=2)
        qr.add_data(track_url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color='black', back_color='white')
        qr_buf = io.BytesIO()
        qr_img.save(qr_buf, format='PNG')
        qr_buf.seek(0)

        # ── PDF A4 ────────────────────────────────────────────────────────────
        pdf_buf = io.BytesIO()
        doc = SimpleDocTemplate(
            pdf_buf, pagesize=A4,
            topMargin=1.5*cm, bottomMargin=1.5*cm,
            leftMargin=2*cm, rightMargin=2*cm
        )
        W = A4[0] - 4*cm
        styles = getSampleStyleSheet()

        def ps(name, **kw):
            return ParagraphStyle(name, parent=styles['Normal'], **kw)

        title_s   = ps('T',  fontSize=16, fontName='Helvetica-Bold', textColor=colors.HexColor('#003399'), alignment=TA_CENTER, spaceAfter=10)
        sub_s     = ps('S',  fontSize=9,  textColor=colors.HexColor('#555'), alignment=TA_CENTER, spaceAfter=10)
        section_s = ps('SE', fontSize=10, fontName='Helvetica-Bold', textColor=colors.HexColor('#003399'), spaceBefore=10, spaceAfter=4)
        label_s   = ps('L',  fontSize=8,  textColor=colors.HexColor('#888'))
        value_s   = ps('V',  fontSize=9,  fontName='Helvetica-Bold')
        footer_s  = ps('F',  fontSize=7,  textColor=colors.HexColor('#aaa'), alignment=TA_CENTER)

        def field(lbl, val):
            return [Paragraph(lbl, label_s), Paragraph(str(val) if val else '—', value_s)]

        def date_fmt(d):
            if not d: return '—'
            try: return d.strftime('%d/%m/%Y')
            except: return str(d)

        story = []

        # Header
        story.append(Paragraph('FICHE D\'IMMATRICULATION', title_s))
        story.append(Paragraph('Brigade Mobile — Comores', sub_s))
        story.append(HRFlowable(width=W, thickness=1.5, color=colors.HexColor('#003399'), spaceAfter=10))

        # QR + plaque côte à côte
        qr_rl = RLImage(qr_buf, width=4.5*cm, height=4.5*cm)
        plate_s = ps('PL', fontSize=22, fontName='Helvetica-Bold',
                     textColor=colors.HexColor('#003399'), alignment=TA_CENTER)
        plate_sub = ps('PS', fontSize=8, textColor=colors.HexColor('#666'), alignment=TA_CENTER)
        top_tbl = Table([
            [qr_rl, [
                Paragraph(vehicle.license_plate, plate_s),
                Spacer(1, 12),
                Paragraph(f'{vehicle.make or ""} {vehicle.model or ""}'.strip() or '—', ps('MK', fontSize=11, alignment=TA_CENTER)),
                Spacer(1, 4),
                Paragraph(f'Statut : {vehicle.status or "—"}', plate_sub),
                Paragraph(f'Enregistré le : {date_fmt(vehicle.registration_date)}', plate_sub),
            ]]
        ], colWidths=[4.8*cm, W - 4.8*cm])
        top_tbl.setStyle(TableStyle([
            ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
            ('ALIGN',         (1,0), (1,0),  'CENTER'),
            ('LEFTPADDING',   (0,0), (-1,-1), 4),
            ('RIGHTPADDING',  (0,0), (-1,-1), 4),
            ('TOPPADDING',    (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('BOX',           (0,0), (-1,-1), 0.8, colors.HexColor('#dde')),
            ('BACKGROUND',    (0,0), (-1,-1), colors.HexColor('#f5f7ff')),
        ]))
        story.append(top_tbl)
        story.append(Spacer(1, 6))

        # ── Section véhicule ──
        story.append(Paragraph('Informations du Véhicule', section_s))
        veh_data = [
            field('Type', vehicle.vehicle_type) + field("Type d'usage", vehicle.usage_type),
            field('Marque', vehicle.make) + field('Modèle', vehicle.model),
            field('Année', vehicle.year) + field('Couleur', vehicle.color),
            field('Carburant', vehicle.fuel_type) + field('Classe fiscale', vehicle.fiscal_class),
            field('Classe CV', vehicle.cv_class) + field('VIN', vehicle.vin),
        ]
        veh_tbl = Table(veh_data, colWidths=[W*0.16, W*0.34, W*0.16, W*0.34])
        veh_tbl.setStyle(TableStyle([
            ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white, colors.HexColor('#f8fafc')]),
            ('GRID', (0,0), (-1,-1), 0.3, colors.HexColor('#dde')),
            ('TOPPADDING',    (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ('LEFTPADDING',   (0,0), (-1,-1), 5),
            ('RIGHTPADDING',  (0,0), (-1,-1), 5),
        ]))
        story.append(veh_tbl)

        # ── Section propriétaire ──
        story.append(Paragraph('Propriétaire', section_s))
        own_data = [
            field('Nom complet', vehicle.owner_name) + field('Téléphone', vehicle.owner_phone),
            field('Île', vehicle.owner_island) + field('Adresse', vehicle.owner_address),
        ]
        own_tbl = Table(own_data, colWidths=[W*0.16, W*0.34, W*0.16, W*0.34])
        own_tbl.setStyle(TableStyle([
            ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white, colors.HexColor('#f8fafc')]),
            ('GRID', (0,0), (-1,-1), 0.3, colors.HexColor('#dde')),
            ('TOPPADDING',    (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ('LEFTPADDING',   (0,0), (-1,-1), 5),
            ('RIGHTPADDING',  (0,0), (-1,-1), 5),
        ]))
        story.append(own_tbl)

        # ── Section assurance / vignette ──
        story.append(Paragraph('Assurance & Vignette', section_s))
        ins_data = [
            field('Compagnie', vehicle.insurance_company) + field("Expiration assurance", date_fmt(vehicle.insurance_expiry)),
            field('Expiration vignette', date_fmt(vehicle.vignette_expiry)) + field('Expiration QR Code', date_fmt(vehicle.qr_code_expiry)),
        ]
        ins_tbl = Table(ins_data, colWidths=[W*0.16, W*0.34, W*0.16, W*0.34])
        ins_tbl.setStyle(TableStyle([
            ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white, colors.HexColor('#f8fafc')]),
            ('GRID', (0,0), (-1,-1), 0.3, colors.HexColor('#dde')),
            ('TOPPADDING',    (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ('LEFTPADDING',   (0,0), (-1,-1), 5),
            ('RIGHTPADDING',  (0,0), (-1,-1), 5),
        ]))
        story.append(ins_tbl)

        if vehicle.notes:
            story.append(Paragraph('Notes', section_s))
            story.append(Paragraph(vehicle.notes, ps('N', fontSize=8, textColor=colors.HexColor('#444'))))

        story.append(Spacer(1, 10))
        story.append(HRFlowable(width=W, thickness=0.5, color=colors.HexColor('#ccc'), spaceAfter=4))
        from app.timezone_utils import now_comoros as _now
        story.append(Paragraph(f'Généré le {_now().strftime("%d/%m/%Y à %H:%M")} — Brigade Mobile Comores', footer_s))

        doc.build(story)
        pdf_buf.seek(0)
        return send_file(pdf_buf, mimetype='application/pdf',
                         download_name=f'fiche_{vehicle.license_plate}.pdf')
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@vehicle_bp.route('/<int:vehicle_id>/qrcode/renew', methods=['POST'])
@login_required
def renew_vehicle_qrcode(vehicle_id):
    """Renouvelle le QR code d'un véhicule avec une nouvelle date d'expiration de 1 an sans changer le token"""
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    check_island_access(vehicle.owner_island)
    
    try:
        old_expiry = vehicle.qr_code_expiry.strftime('%Y-%m-%d') if vehicle.qr_code_expiry else 'Non défini'
        old_status = vehicle.status
        
        # Renouveler uniquement l'expiration du QR code
        vehicle.generate_qr_code_with_expiry()
        vehicle.qr_renewed_by = current_user.username

        # Réactiver le véhicule s'il était inactif
        if vehicle.status == 'inactive':
            vehicle.status = 'active'

        # Enregistrer dans l'historique
        from app.models import VehicleHistory
        history = VehicleHistory(
            vehicle_id=vehicle.id,
            action=f"QR Code renouvelé - Token conservé",
            officer=current_user.username,
            notes=f"Token conservé: {vehicle.track_token}\nAncien expiry: {old_expiry}\nNouvelle expiry: {vehicle.qr_code_expiry.strftime('%Y-%m-%d')}"
        )
        db.session.add(history)
        db.session.commit()
        _record_qr_payment(vehicle, 'renewal', current_user.username)

        from app.models import SmartTechSetting
        renewal_amount = float(SmartTechSetting.get('qr_renewal_price', 3000) or 3000)
        return jsonify({
            'success': True,
            'message': f'Code QR renouvelé pour {vehicle.license_plate}',
            'track_token': vehicle.track_token,
            'token_unchanged': True,
            'old_expiry': old_expiry,
            'new_expiry': vehicle.qr_code_expiry.strftime('%d/%m/%Y'),
            'old_status': old_status,
            'new_status': vehicle.status,
            'generated_at': vehicle.qr_code_generated_at.strftime('%Y-%m-%d %H:%M:%S'),
            'owner_name': vehicle.owner_name or '',
            'amount': renewal_amount,
            'payment_type': 'renewal',
            'recorded_by': current_user.username,
            'paid_at': now_comoros().strftime('%d/%m/%Y %H:%M'),
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@vehicle_bp.route('/<int:vehicle_id>/qrcode/activate', methods=['POST'])
@login_required
def activate_vehicle_qrcode(vehicle_id):
    """Activate QR code for a vehicle (first time) and return receipt data."""
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    check_island_access(vehicle.owner_island)
    try:
        already_active = bool(vehicle.qr_code_expiry and not vehicle.is_qr_code_expired())
        if not vehicle.qr_code_expiry:
            vehicle.generate_qr_code_with_expiry()
        if vehicle.qr_pending_approval:
            vehicle.qr_pending_approval = False
        db.session.commit()
        _record_qr_payment(vehicle, 'activation', current_user.username)
        from app.models import SmartTechSetting
        activation_amount = float(SmartTechSetting.get('qr_activation_price', 5000) or 5000)
        return jsonify({
            'success': True,
            'already_active': already_active,
            'license_plate': vehicle.license_plate,
            'owner_name': vehicle.owner_name or '',
            'new_expiry': vehicle.qr_code_expiry.strftime('%d/%m/%Y'),
            'amount': activation_amount,
            'payment_type': 'activation',
            'recorded_by': current_user.username,
            'paid_at': now_comoros().strftime('%d/%m/%Y %H:%M'),
            'pdf_url': f'/api/vehicles/{vehicle.id}/qrcode/pdf',
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@vehicle_bp.route('/<int:vehicle_id>/qrcode/last-receipt', methods=['GET'])
@login_required
def vehicle_qrcode_last_receipt(vehicle_id):
    """Return the latest QR payment receipt data for a vehicle."""
    from app.models import QRCodePayment
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    check_island_access(vehicle.owner_island)
    payment = QRCodePayment.query.filter_by(
        vehicle_id=vehicle.id, status='paid'
    ).order_by(QRCodePayment.paid_at.desc()).first()
    if not payment:
        return jsonify({'error': 'Aucun paiement enregistré pour ce véhicule.'}), 404
    return jsonify({
        'license_plate': vehicle.license_plate,
        'owner_name': vehicle.owner_name or '',
        'payment_type': payment.payment_type,
        'amount': float(payment.amount),
        'paid_at': payment.paid_at.strftime('%d/%m/%Y %H:%M') if payment.paid_at else '—',
        'new_expiry': vehicle.qr_code_expiry.strftime('%d/%m/%Y') if vehicle.qr_code_expiry else '—',
        'recorded_by': payment.recorded_by or '—',
    })


@main_bp.route('/vehicles/<int:vehicle_id>/track')
@login_required
def vehicle_track_redirect(vehicle_id):
    """Redirect from vehicle ID to its public track page (used when track_token is unknown client-side)."""
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    if not vehicle.track_token:
        abort(404)
    return redirect(url_for('main_bp.public_track', token=vehicle.track_token))


@main_bp.route('/track/<token>')
def public_track(token):
    # page sécurisée - accessible seulement aux utilisateurs connectés
    if not current_user.is_authenticated:
        abort(403)
    vehicle = Vehicle.query.filter_by(track_token=token).first_or_404()
    # Normalize commonly-used datetime fields to Comoros timezone so templates can compare safely
    datetime_fields = [
        'vignette_expiry', 'registration_expiry', 'qr_code_expiry', 'insurance_expiry',
        'last_inspection_date', 'registration_date', 'created_at', 'updated_at'
    ]
    for f in datetime_fields:
        val = getattr(vehicle, f, None)
        if val:
            try:
                setattr(vehicle, f, ensure_comoros(val))
            except Exception:
                pass
    # collect history entries and fines
    history_items = []
    unpaid_count = 0
    # vehicle history
    try:
        from app.models import VehicleHistory, Fine
        hist = VehicleHistory.query.filter_by(vehicle_id=vehicle.id).order_by(VehicleHistory.created_at.desc()).all()
        for h in hist:
            # Skip exoneration history entries
            if 'exonération' in h.action.lower() or 'exonération' in (h.notes or '').lower():
                continue
            # Skip legacy no-op update rows where nothing actually changed
            if _is_noop_vehicle_update_history(h.action, h.notes):
                continue
            history_items.append({
                'type': 'history',
                'created_at': h.created_at.isoformat(),
                'created_at_str': h.created_at.strftime('%Y-%m-%d %H:%M'),
                'title': h.action,
                'details': h.notes or '',
                'actor': h.officer or ''
            })
        fines = Fine.query.filter_by(vehicle_id=vehicle.id).order_by(Fine.issued_at.desc()).all()
        for f in fines:
            # Skip exonerated fines (with auto-deletion note)
            if f.notes and '[EXONÉRÉ - Suppression automatique après 60 min]' in f.notes:
                continue
            history_items.append({
                'type': 'fine',
                'id': f.id,
                'created_at': f.issued_at.isoformat(),
                'created_at_str': f.issued_at.strftime('%Y-%m-%d %H:%M'),
                'reason': f.reason,
                'amount': float(f.amount),
                'paid': bool(f.paid),
                'paid_at': f.paid_at.isoformat() if f.paid_at else None,
                'receipt_number': f.receipt_number,
                'details': f.notes or '',
                'actor': f.officer or ''
            })
        # sort by date desc
        history_items.sort(key=lambda x: x['created_at'], reverse=True)
        # compute unpaid fines count
        unpaid_count = Fine.query.filter_by(vehicle_id=vehicle.id, paid=False).count()
    except Exception:
        history_items = []
    
    # Pass Comoros-aware now function for expiry calculations in template
    return render_template('track.html', vehicle=vehicle, history=history_items, unpaid_count=unpaid_count, now=now_comoros)


@main_bp.route('/payments')
@roles_required('policier')
def payments_page():
    """Page de gestion des paiements des amandes"""
    return render_template('payments.html')


@main_bp.route('/payments/settings')
@roles_required('judiciaire', 'policier')
def payments_settings_page():
    """Paramètres de la gestion des paiements."""
    accounts_query = User.query.filter_by(role='mobile_money_agent')

    user_country = getattr(current_user, 'country', None)
    user_role = getattr(current_user, 'role', None)
    if user_country and user_role in ('judiciaire', 'policier'):
        accounts_query = accounts_query.filter(User.country == user_country)

    q = (request.args.get('q') or '').strip()
    if q:
        like_q = f'%{q}%'
        accounts_query = accounts_query.filter(
            or_(
                User.username.ilike(like_q),
                User.full_name.ilike(like_q),
                User.phone.ilike(like_q),
                User.email.ilike(like_q),
                User.country.ilike(like_q)
            )
        )

    mobile_money_accounts = accounts_query.order_by(User.created_at.desc()).all()

    status = request.args.get('status', '').strip()
    message = request.args.get('message', '').strip()

    return render_template(
        'payments_settings.html',
        mobile_money_accounts=mobile_money_accounts,
        status=status,
        message=message,
        q=q
    )


@main_bp.route('/api/payments/mobile-money-agents/create', methods=['POST'])
@roles_required('judiciaire', 'policier')
def create_mobile_money_agent_account():
    """Créer un compte agent Mobile Money pour le module paiements."""
    data = request.form if request.form else (request.get_json() or {})

    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    full_name = (data.get('full_name') or '').strip()
    phone = (data.get('phone') or '').strip()
    email = (data.get('email') or '').strip()
    country = (data.get('country') or '').strip()

    if not username or not password:
        return redirect(url_for(
            'main.payments_settings_page',
            status='error',
            message='Le nom utilisateur et le mot de passe sont obligatoires.'
        ))

    if User.query.filter_by(username=username).first():
        return redirect(url_for(
            'main.payments_settings_page',
            status='error',
            message='Ce nom utilisateur existe déjà.'
        ))

    if not country:
        return redirect(url_for(
            'main.payments_settings_page',
            status='error',
            message='Le pays est obligatoire.'
        ))

    creator_country = getattr(current_user, 'country', None)
    creator_region = getattr(current_user, 'region', None)
    if creator_country and country != creator_country:
        return redirect(url_for(
            'main.payments_settings_page',
            status='error',
            message='Vous ne pouvez créer un compte que dans votre pays.'
        ))

    account = User(
        username=username,
        role='mobile_money_agent',
        full_name=full_name or None,
        phone=phone or None,
        email=email or None,
        country=country,
        region=creator_region,
        is_active=True
    )
    account.set_password(password)
    db.session.add(account)
    db.session.commit()

    return redirect(url_for(
        'main.payments_settings_page',
        status='success',
        message='Compte agent Mobile Money créé avec succès.'
    ))


@main_bp.route('/api/payments/mobile-money-agents/<int:user_id>/update', methods=['POST'])
@roles_required('judiciaire', 'policier')
def update_mobile_money_agent_account(user_id):
    """Modifier un compte agent Mobile Money."""
    data = request.form if request.form else (request.get_json() or {})

    account = User.query.get_or_404(user_id)
    if account.role != 'mobile_money_agent':
        return redirect(url_for(
            'main.payments_settings_page',
            status='error',
            message='Compte introuvable.'
        ))

    user_country = getattr(current_user, 'country', None)
    user_role = getattr(current_user, 'role', None)
    if user_country and user_role in ('judiciaire', 'policier') and account.country != user_country:
        return redirect(url_for(
            'main.payments_settings_page',
            status='error',
            message='Accès refusé pour ce compte.'
        ))

    username = (data.get('username') or '').strip()
    full_name = (data.get('full_name') or '').strip()
    phone = (data.get('phone') or '').strip()
    email = (data.get('email') or '').strip()
    country = (data.get('country') or '').strip()
    password = data.get('password') or ''
    redirect_q = (data.get('q') or '').strip()

    if not username or not country:
        return redirect(url_for(
            'main.payments_settings_page',
            q=redirect_q,
            status='error',
            message='Nom utilisateur et pays sont obligatoires.'
        ))

    existing = User.query.filter(User.username == username, User.id != account.id).first()
    if existing:
        return redirect(url_for(
            'main.payments_settings_page',
            q=redirect_q,
            status='error',
            message='Ce nom utilisateur existe déjà.'
        ))

    if user_country and user_role in ('judiciaire', 'policier') and country != user_country:
        return redirect(url_for(
            'main.payments_settings_page',
            q=redirect_q,
            status='error',
            message='Vous ne pouvez définir que votre pays.'
        ))

    account.username = username
    account.full_name = full_name or None
    account.phone = phone or None
    account.email = email or None
    account.country = country
    if password:
        account.set_password(password)

    db.session.commit()

    return redirect(url_for(
        'main.payments_settings_page',
        q=redirect_q,
        status='success',
        message='Compte agent Mobile Money modifié avec succès.'
    ))


@main_bp.route('/api/payments/mobile-money-agents/<int:user_id>/toggle-active', methods=['POST'])
@roles_required('judiciaire', 'policier')
def toggle_mobile_money_agent_account(user_id):
    """Activer ou désactiver un compte agent Mobile Money."""
    data = request.form if request.form else (request.get_json() or {})

    account = User.query.get_or_404(user_id)
    if account.role != 'mobile_money_agent':
        return redirect(url_for(
            'main.payments_settings_page',
            status='error',
            message='Compte introuvable.'
        ))

    user_country = getattr(current_user, 'country', None)
    user_role = getattr(current_user, 'role', None)
    if user_country and user_role in ('judiciaire', 'policier') and account.country != user_country:
        return redirect(url_for(
            'main.payments_settings_page',
            status='error',
            message='Accès refusé pour ce compte.'
        ))

    redirect_q = (data.get('q') or '').strip()
    action = (data.get('action') or '').strip()
    if action == 'deactivate':
        account.is_active = False
        success_message = 'Compte agent Mobile Money désactivé.'
    else:
        account.is_active = True
        success_message = 'Compte agent Mobile Money activé.'

    db.session.commit()

    return redirect(url_for(
        'main.payments_settings_page',
        q=redirect_q,
        status='success',
        message=success_message
    ))


@main_bp.route('/api/payments/mobile-money-agents/<int:user_id>/delete', methods=['POST'])
@roles_required('judiciaire', 'policier')
def delete_mobile_money_agent_account(user_id):
    """Supprimer un compte agent Mobile Money."""
    data = request.form if request.form else (request.get_json() or {})

    account = User.query.get_or_404(user_id)
    if account.role != 'mobile_money_agent':
        return redirect(url_for(
            'main.payments_settings_page',
            status='error',
            message='Compte introuvable.'
        ))

    user_country = getattr(current_user, 'country', None)
    user_role = getattr(current_user, 'role', None)
    if user_country and user_role in ('judiciaire', 'policier') and account.country != user_country:
        return redirect(url_for(
            'main.payments_settings_page',
            status='error',
            message='Accès refusé pour ce compte.'
        ))

    redirect_q = (data.get('q') or '').strip()
    db.session.delete(account)
    db.session.commit()

    return redirect(url_for(
        'main.payments_settings_page',
        q=redirect_q,
        status='success',
        message='Compte agent Mobile Money supprimé avec succès.'
    ))


@main_bp.route('/fines/receipt/<int:fine_id>')
@login_required
def fine_receipt(fine_id):
    from app.models import Fine, Vehicle
    fine = Fine.query.get_or_404(fine_id)
    vehicle = Vehicle.query.get(fine.vehicle_id)
    payment_notes = (fine.notes or '').lower()
    is_app_mobile_payment = (
        request.args.get('source') == 'app_mobile'
        or (fine.paid_by or '').strip().lower() == 'app mobile'
        or 'app mobile' in payment_notes
        or 'mobile citizen' in payment_notes
        or 'mobile_citizen' in payment_notes
    )
    signature_text = 'App Mobile' if is_app_mobile_payment else (fine.paid_by or '—')
    # receipts are part of payments area: show but ensure access control
    # allow admin, judiciaire and policier to view receipt
    role = getattr(current_user, 'role', None)
    if not role and getattr(current_user, 'is_admin', False):
        role = 'administrateur'
    if role not in ('administrateur','judiciaire','policier'):
        abort(403)
    return render_template(
        'receipt.html',
        fine=fine,
        vehicle=vehicle,
        signature_text=signature_text,
    )


@main_bp.route('/users')
@roles_required('administrateur')
def users_page():
    return render_template('users.html')


@main_bp.route('/api/users/backup')
@roles_required('administrateur')
def api_users_backup():
    import zipfile
    from sqlalchemy import inspect, text
    timestamp = now_comoros().strftime('%Y%m%d_%H%M%S')
    db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
    zip_buf = io.BytesIO()

    with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        # --- SQLite: include raw .db file ---
        if db_uri.startswith('sqlite'):
            db_path = db_uri.replace('sqlite:///', '')
            if os.path.isfile(db_path):
                zf.write(db_path, f'police_backup_{timestamp}.db')

        # --- JSON dump of all tables (works on SQLite + PostgreSQL) ---
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

        import decimal
        def default_serial(obj):
            if isinstance(obj, (datetime, )):
                return obj.isoformat()
            if isinstance(obj, decimal.Decimal):
                return float(obj)
            return str(obj)

        json_bytes = json.dumps(backup_data, ensure_ascii=False, indent=2, default=default_serial).encode('utf-8')
        zf.writestr(f'police_backup_{timestamp}.json', json_bytes)

        # --- Manifest ---
        manifest = {
            'timestamp': timestamp,
            'database': 'sqlite' if db_uri.startswith('sqlite') else 'postgresql',
            'tables': {t: len(backup_data.get(t, [])) for t in all_tables},
        }
        zf.writestr('manifest.json', json.dumps(manifest, indent=2))

    zip_buf.seek(0)
    return send_file(
        zip_buf,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'backup_{timestamp}.zip'
    )


_restore_tasks = {}  # task_id -> {'status': 'running'|'done'|'error', 'message': ..., 'tables': ...}


@main_bp.route('/api/users/restore', methods=['POST'])
@roles_required('administrateur')
def api_users_restore():
    import zipfile
    import threading
    import uuid as _uuid

    f = request.files.get('backup_file')
    if not f or not f.filename.endswith('.zip'):
        return jsonify({'error': 'Fichier ZIP requis.'}), 400

    try:
        zip_buf = io.BytesIO(f.read())
        with zipfile.ZipFile(zip_buf, 'r') as zf:
            json_names = [n for n in zf.namelist() if n.endswith('.json') and 'backup' in n]
            if not json_names:
                return jsonify({'error': 'Aucun fichier JSON de backup trouvé dans le ZIP.'}), 400
            raw = zf.read(json_names[0])
            backup_data = json.loads(raw.decode('utf-8'))
    except Exception as e:
        return jsonify({'error': f'Lecture du ZIP échouée : {e}'}), 400

    task_id = str(_uuid.uuid4())
    _restore_tasks[task_id] = {'status': 'running', 'message': 'Restauration en cours…'}

    app_ref = current_app._get_current_object()

    def do_restore():
        from sqlalchemy import text
        db_uri = app_ref.config.get('SQLALCHEMY_DATABASE_URI', '')
        is_pg = not db_uri.startswith('sqlite')
        sorted_names = [t.name for t in db.metadata.sorted_tables]
        tables_to_restore = [n for n in sorted_names if n in backup_data and backup_data[n]]
        stats = {}
        try:
            with app_ref.app_context():
                with db.engine.begin() as conn:
                    if is_pg:
                        tables_quoted = ', '.join(f'"{n}"' for n in tables_to_restore)
                        conn.execute(text(f'TRUNCATE {tables_quoted} CASCADE'))
                    else:
                        conn.execute(text('PRAGMA foreign_keys = OFF'))
                        for name in reversed(tables_to_restore):
                            conn.execute(text(f'DELETE FROM "{name}"'))

                    from sqlalchemy import Boolean as _SABool

                    def _prepare_rows(name, rows):
                        table_obj = db.metadata.tables.get(name)
                        if table_obj is not None:
                            db_col_map = {c.name: c for c in table_obj.columns}
                        else:
                            db_col_map = {k: None for k in rows[0].keys()}
                        col_names = [c for c in rows[0].keys() if c in db_col_map]
                        if not col_names:
                            return None, None, None
                        bool_cols = {
                            c for c in col_names
                            if db_col_map[c] is not None and isinstance(db_col_map[c].type, _SABool)
                        }
                        def _fix(row):
                            r = {c: row[c] for c in col_names}
                            for bc in bool_cols:
                                if r[bc] is not None:
                                    r[bc] = bool(r[bc])
                            return r
                        return col_names, ', '.join(f'"{c}"' for c in col_names), [_fix(r) for r in rows]

                    deferred = []  # tables qui ont échoué au premier passage (FK)
                    for name in tables_to_restore:
                        rows = backup_data[name]
                        if not rows:
                            continue
                        col_names, cols_sql, filtered_rows = _prepare_rows(name, rows)
                        if not col_names:
                            continue
                        vals_sql = ', '.join(f':{c}' for c in col_names)
                        stmt = text(f'INSERT INTO "{name}" ({cols_sql}) VALUES ({vals_sql})')
                        if is_pg:
                            sp = f'sp_{name.replace("-", "_")}'
                            conn.execute(text(f'SAVEPOINT {sp}'))
                            try:
                                conn.execute(stmt, filtered_rows)
                                conn.execute(text(f'RELEASE SAVEPOINT {sp}'))
                                stats[name] = len(filtered_rows)
                            except Exception:
                                conn.execute(text(f'ROLLBACK TO SAVEPOINT {sp}'))
                                deferred.append((name, col_names, cols_sql, filtered_rows))
                        else:
                            conn.execute(stmt, filtered_rows)
                            stats[name] = len(filtered_rows)

                    # Deuxième passage pour les tables avec FK non résolues au premier tour
                    for name, col_names, cols_sql, filtered_rows in deferred:
                        vals_sql = ', '.join(f':{c}' for c in col_names)
                        stmt = text(f'INSERT INTO "{name}" ({cols_sql}) VALUES ({vals_sql})')
                        sp = f'sp2_{name.replace("-", "_")}'
                        conn.execute(text(f'SAVEPOINT {sp}'))
                        try:
                            conn.execute(stmt, filtered_rows)
                            conn.execute(text(f'RELEASE SAVEPOINT {sp}'))
                            stats[name] = len(filtered_rows)
                        except Exception as e2:
                            conn.execute(text(f'ROLLBACK TO SAVEPOINT {sp}'))
                            stats[name] = f'SKIPPED: {e2}'

                    if not is_pg:
                        conn.execute(text('PRAGMA foreign_keys = ON'))

                if is_pg:
                    for name in tables_to_restore:
                        try:
                            with db.engine.begin() as conn:
                                conn.execute(text(
                                    f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), "
                                    f"COALESCE((SELECT MAX(id) FROM \"{name}\"), 1))"
                                ))
                        except Exception:
                            pass

            _restore_tasks[task_id] = {'status': 'done', 'message': 'Restauration réussie.', 'tables': stats}
        except Exception as e:
            _restore_tasks[task_id] = {'status': 'error', 'message': f'Restauration échouée : {e}'}

    threading.Thread(target=do_restore, daemon=True).start()
    return jsonify({'task_id': task_id, 'status': 'running'})


@main_bp.route('/api/users/restore/status/<task_id>', methods=['GET'])
def api_users_restore_status(task_id):
    # Pas d'auth requise : le task_id UUID 128 bits est non-devinable et ne retourne pas de données sensibles.
    # L'auth session serait de toute façon invalide pendant la restauration (users table vidée).
    task = _restore_tasks.get(task_id)
    if not task:
        return jsonify({'error': 'Tâche introuvable.'}), 404
    return jsonify(task)


@main_bp.route('/api/users/list')
@roles_required('administrateur')
def api_users_list():
    # Determine which users to show based on current user's role
    current_role = getattr(current_user, 'role', None)
    current_country = getattr(current_user, 'country', None)
    
    # Super admin (administrateur, no country restriction) → sees ALL users (all roles)
    # Admin with country → sees judiciaire + policier + agent_impot
    # Judiciaire → sees policier + agent_impot
    # Agent_impot → sees other agent_impot only (if needed)
    
    if current_role == 'administrateur':
        if not current_country:
            # Super admin: show all users (all roles)
            target_roles = ['administrateur', 'judiciaire', 'policier', 'agent_impot', 'dgrtr']
        else:
            # Regular admin: show judiciaire + policier + agent_impot + dgrtr users
            target_roles = ['judiciaire', 'policier', 'agent_impot', 'dgrtr']
    elif current_role == 'judiciaire':
        # Judiciaire: show policier + agent_impot users
        target_roles = ['policier', 'agent_impot']
    else:
        # Other roles cannot access this page (already filtered by roles_required)
        return jsonify([])
    
    # Query users with target roles
    users = User.query.filter(User.role.in_(target_roles)).order_by(User.created_at.desc()).all()
    out = []
    for u in users:
        out.append({
            'id': u.id,
            'username': u.username,
            'role': getattr(u, 'role', 'policier'),
            'full_name': getattr(u, 'full_name', '') or '',
            'email': getattr(u, 'email', '') or '',
            'phone': getattr(u, 'phone', '') or '',
            'country': getattr(u, 'country', '') or '',
            'region': getattr(u, 'region', '') or '',
            'dgrtr_type': getattr(u, 'dgrtr_type', '') or '',
            'is_active': bool(getattr(u, 'is_active', True)),
            'created_at': u.created_at.strftime('%Y-%m-%d %H:%M')
        })
    return jsonify(out)


@main_bp.route('/api/users/create', methods=['POST'])
@roles_required('administrateur', 'dgrtr')
def api_users_create():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')
    role = data.get('role') or 'policier'
    full_name = data.get('full_name')
    email = data.get('email')
    phone = data.get('phone')
    country = data.get('country')
    region = data.get('region')
    is_active = data.get('is_active', True)
    # dgrtr users: only DG can create dgrtr + judiciaire; others cannot create users
    if current_user.role == 'dgrtr':
        is_dg = getattr(current_user, 'dgrtr_type', None) == 'directeur_general'
        if not is_dg:
            return jsonify({'error': 'Accès refusé'}), 403
        if role not in ('dgrtr', 'judiciaire'):
            return jsonify({'error': 'Accès refusé'}), 403
    if not username or not password:
        return jsonify({'error':'username and password required'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'error':'username already exists'}), 400
    u = User(username=username, role=role)
    u.full_name = full_name
    u.email = email
    u.phone = phone
    u.country = country
    u.region = region
    u.dgrtr_type = data.get('dgrtr_type') or None
    u.is_active = bool(is_active)
    u.set_password(password)
    # if role is administrateur mark is_admin True for backwards compatibility
    if role == 'administrateur':
        u.is_admin = True
    db.session.add(u)
    db.session.commit()
    return jsonify({'ok': True, 'id': u.id})


@main_bp.route('/api/users/<int:user_id>/update', methods=['POST'])
@roles_required('administrateur', 'dgrtr')
def api_users_update(user_id):
    data = request.get_json() or {}
    u = User.query.get_or_404(user_id)
    # Only update allowed fields
    if 'username' in data and data.get('username'):
        # ensure uniqueness
        existing = User.query.filter(User.username == data.get('username'), User.id != u.id).first()
        if existing:
            return jsonify({'error': 'username already exists'}), 400
        u.username = data.get('username')
    if 'full_name' in data:
        u.full_name = data.get('full_name')
    if 'email' in data:
        u.email = data.get('email')
    if 'phone' in data:
        u.phone = data.get('phone')
    if 'country' in data:
        u.country = data.get('country')
    if 'region' in data:
        u.region = data.get('region')
    if 'role' in data:
        u.role = data.get('role')
        if u.role == 'administrateur':
            u.is_admin = True
        else:
            u.is_admin = False
    if 'is_active' in data:
        u.is_active = bool(data.get('is_active'))
    if 'dgrtr_type' in data:
        u.dgrtr_type = data.get('dgrtr_type') or None
    if 'password' in data and data.get('password'):
        u.set_password(data.get('password'))

    db.session.commit()
    return jsonify({'ok': True})


@main_bp.route('/api/users/<int:user_id>/delete', methods=['POST'])
@roles_required('administrateur', 'dgrtr')
def api_users_delete(user_id):
    if current_user.id == user_id:
        return jsonify({'error':'cannot delete yourself'}), 400
    u = User.query.get_or_404(user_id)
    if current_user.role == 'dgrtr' and u.role not in ('dgrtr', 'judiciaire'):
        return jsonify({'error': 'Accès refusé'}), 403
    if u.role == 'administrateur' and User.query.filter_by(role='administrateur').count() <= 1:
        return jsonify({'error': 'Impossible de supprimer le dernier administrateur.'}), 400
    
    from app.models import PhoneUsage, UserHistory
    PhoneUsage.query.filter_by(user_id=user_id).delete()
    UserHistory.query.filter_by(user_id=user_id).delete()

    db.session.delete(u)
    db.session.commit()
    return jsonify({'ok': True})


@main_bp.route('/api/users/<int:user_id>/history')
@roles_required('administrateur')
def api_users_history(user_id):
    """Get action history for a specific user (excluding administrators)"""
    u = User.query.get_or_404(user_id)
    
    # Don't show history for administrators (security)
    if u.role == 'administrateur':
        return jsonify({'error': 'Cannot view history for administrators'}), 403
    
    # Get user history, ordered by most recent first
    from app.models import UserHistory
    history_query = UserHistory.query.filter_by(user_id=user_id)

    day = request.args.get('day', type=str)
    if day:
        try:
            history_query = history_query.filter(func.date(UserHistory.created_at) == day)
        except Exception:
            return jsonify({'error': 'Invalid day format, expected YYYY-MM-DD'}), 400

    history = history_query.order_by(UserHistory.created_at.desc()).all()
    
    return jsonify([h.to_dict() for h in history])


@main_bp.route('/profile')
@login_required
def profile_page():
    return render_template('profile.html')


@main_bp.route('/api/users/me')
@login_required
def api_users_me():
    u = current_user
    return jsonify({
        'id': u.id,
        'username': u.username,
        'full_name': getattr(u, 'full_name', '') or '',
        'email': getattr(u, 'email', '') or '',
        'phone': getattr(u, 'phone', '') or '',
        'is_active': bool(getattr(u, 'is_active', True)),
        'role': getattr(u, 'role', '')
    })


@main_bp.route('/api/profile')
@jwt_required()
def api_profile():
    user_id = get_jwt_identity()
    u = User.query.get(int(user_id))
    if not u:
        return jsonify({'error': 'User not found'}), 404
    return jsonify({
        'id': u.id,
        'username': u.username,
        'full_name': getattr(u, 'full_name', '') or '',
        'email': getattr(u, 'email', '') or '',
        'phone': getattr(u, 'phone', '') or '',
        'country': getattr(u, 'country', '') or '',
        'region': getattr(u, 'region', '') or '',
        'is_active': bool(getattr(u, 'is_active', True)),
        'role': getattr(u, 'role', '')
    })


@main_bp.route('/api/profile/update', methods=['POST'])
@jwt_required()
def api_profile_update():
    user_id = get_jwt_identity()
    u = User.query.get(int(user_id))
    if not u:
        return jsonify({'error':'user not found'}), 404
    data = request.get_json() or {}
    u.full_name = data.get('full_name')
    u.email = data.get('email')
    u.phone = data.get('phone')
    # only admin can toggle is_active for themselves? allow for now
    if 'is_active' in data:
        u.is_active = bool(data.get('is_active'))
    db.session.commit()
    return jsonify({'ok': True})


@main_bp.route('/api/profile/change-password', methods=['POST'])
@jwt_required()
def api_profile_change_password():
    user_id = get_jwt_identity()
    u = User.query.get(int(user_id))
    if not u:
        return jsonify({'error':'user not found'}), 404
    data = request.get_json() or {}
    current_password = data.get('current_password')
    new_password = data.get('new_password')
    if not current_password or not new_password:
        return jsonify({'error':'current and new password required'}), 400
    if not u.check_password(current_password):
        return jsonify({'error':'current password incorrect'}), 400
    u.set_password(new_password)
    db.session.commit()
    return jsonify({'ok': True})


@main_bp.route('/api/users/profile', methods=['POST'])
@login_required
def api_users_profile_update():
    data = request.get_json() or {}
    u = User.query.get(current_user.id)
    if not u:
        return jsonify({'error':'user not found'}), 404
    u.full_name = data.get('full_name')
    u.email = data.get('email')
    u.phone = data.get('phone')
    # only admin can toggle is_active for themselves? allow for now
    if 'is_active' in data:
        u.is_active = bool(data.get('is_active'))
    db.session.commit()
    return jsonify({'ok': True})


@main_bp.route('/api/users/profile/password', methods=['POST'])
@login_required
def api_users_profile_password():
    data = request.get_json() or {}
    current_password = data.get('current_password')
    new_password = data.get('new_password')
    if not current_password or not new_password:
        return jsonify({'error':'current and new password required'}), 400
    u = User.query.get(current_user.id)
    if not u.check_password(current_password):
        return jsonify({'error':'current password incorrect'}), 400
    u.set_password(new_password)
    db.session.commit()
    return jsonify({'ok': True})


@main_bp.route('/track/<token>/qrcode')
def public_track_qrcode(token):
    """Générer un QR sécurisé pour le token (accessible seulement aux utilisateurs connectés)"""
    if not current_user.is_authenticated:
        abort(403)
    vehicle = Vehicle.query.filter_by(track_token=token).first_or_404()
    if vehicle.qr_pending_approval:
        abort(403)
    # point the QR to the public tracking page itself
    track_url = vehicle.license_plate
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(track_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')


@main_bp.route('/track/<token>/qrcode/pdf')
def public_track_qrcode_pdf(token):
    """Télécharger QR code en PDF avec numéro d'immatriculation et texte descriptif"""
    if not current_user.is_authenticated:
        abort(403)
    
    vehicle = Vehicle.query.filter_by(track_token=token).first_or_404()

    if vehicle.qr_pending_approval:
        abort(403)

    if not REPORTLAB_AVAILABLE:
        return jsonify({'error': 'PDF generation not available'}), 500
    
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib.enums import TA_CENTER


        # Générer QR code avec numéro d'immatriculation intégré
        qr_img = _make_qr_with_plate(vehicle.license_plate, vehicle.license_plate)
        qr_buf = io.BytesIO()
        qr_img.save(qr_buf, format='PNG')
        qr_buf.seek(0)

        # Générer le PDF avec format petit (carte autocollante 10x10cm)
        pdf_buf = io.BytesIO()
        card_size = (10*cm, 10*cm)  # Petit format pour autocollant parebrise
        doc = SimpleDocTemplate(pdf_buf, pagesize=card_size, topMargin=0.2*cm, bottomMargin=0.2*cm, leftMargin=0.2*cm, rightMargin=0.2*cm)
        styles = getSampleStyleSheet()
        elems = []
        
        # QR Code image (plus grand)
        qr_image = RLImage(qr_buf, width=6.5*cm, height=6.5*cm)
        
        # Créer une table pour centrer l'image
        qr_table = Table([[qr_image]])
        qr_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, 0), 'CENTER'),
            ('VALIGN', (0, 0), (0, 0), 'MIDDLE'),
        ]))
        elems.append(qr_table)
        elems.append(Spacer(1, 0.05*cm))
        
        # Numéro d'immatriculation
        license_plate_style = ParagraphStyle(
            'LicensePlate',
            parent=styles['Normal'],
            fontSize=14,
            textColor=colors.HexColor('#003366'),
            alignment=TA_CENTER,
            fontName='Helvetica-Bold',
            spaceAfter=0.15*cm
        )
        elems.append(Paragraph(f'<b>{vehicle.license_plate}</b>', license_plate_style))
        
        # Espace supplémentaire avant le texte descriptif
        elems.append(Spacer(1, 0.05*cm))
        
        # Texte descriptif "votre identifiant numérique"
        subtitle_style = ParagraphStyle(
            'Subtitle',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#0066CC'),
            alignment=TA_CENTER,
            fontName='Helvetica-Oblique',
            spaceAfter=0
        )
        # ── Nouveau design : bandeau bleu + QR grand + footer ──────────────────
        footer_style = ParagraphStyle(
            'QRFooter', parent=styles['Normal'],
            fontSize=7, textColor=colors.HexColor('#555555'),
            alignment=TA_CENTER, fontName='Helvetica-Oblique', leading=9,
        )

        qr_big = RLImage(qr_buf, width=8.0*cm, height=8.0*cm)
        qr_band = Table([[qr_big]], colWidths=[9.2*cm], rowHeights=[8.28*cm])
        qr_band.setStyle(TableStyle([
            ('ALIGN',         (0,0), (-1,-1), 'CENTER'),
            ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
            ('BACKGROUND',    (0,0), (-1,-1), colors.white),
            ('TOPPADDING',    (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ]))

        footer_band = Table(
            [[Paragraph('Brigade Mobile — Comores', footer_style)]],
            colWidths=[9.2*cm], rowHeights=[0.46*cm]
        )
        footer_band.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,-1), colors.HexColor('#eef2ff')),
            ('TOPPADDING',    (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ]))

        card = Table(
            [[qr_band], [footer_band]],
            colWidths=[9.2*cm],
            rowHeights=[8.28*cm, 0.46*cm],
        )
        card.setStyle(TableStyle([
            ('BOX',           (0,0), (-1,-1), 1.5, colors.HexColor('#003399')),
            ('NOSPLIT',       (0,0), (-1,-1)),
            ('TOPPADDING',    (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 0),
            ('LEFTPADDING',   (0,0), (-1,-1), 0),
            ('RIGHTPADDING',  (0,0), (-1,-1), 0),
        ]))

        doc.build([card])
        pdf_buf.seek(0)

        return send_file(pdf_buf, mimetype='application/pdf', download_name=f'qrcode_{vehicle.track_token[:8]}.pdf')
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@vehicle_bp.route('/<int:vehicle_id>', methods=['PUT'])
@login_required
def update_vehicle(vehicle_id):
    from app.models import VehicleHistory
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    check_island_access(vehicle.owner_island)
    data = request.get_json() or request.form

    tracked_fields = [
        'license_plate', 'owner_name', 'owner_phone', 'owner_island',
        'vehicle_type', 'fuel_type', 'usage_type', 'color', 'status', 'make', 'model',
        'year', 'vin', 'owner_address', 'registration_expiry',
        'insurance_company', 'insurance_expiry', 'vignette_expiry', 'fiscal_class', 'cv_class', 'notes'
    ]
    old_values = {field: getattr(vehicle, field) for field in tracked_fields}

    insurance_fields_requested = any(field in data for field in ['insurance_company', 'insurance_expiry'])
    if isinstance(current_user, InsuranceAccount) and insurance_fields_requested and vehicle_has_unpaid_fines(vehicle.id):
        return jsonify({'error': "Ce véhicule a une amende non payée. Vous devez d'abord la régler avant de modifier l'assurance."}), 400

    # Prevent insurance accounts from modifying insurance dates when vehicle is inactive or QR code expired
    if isinstance(current_user, InsuranceAccount) and insurance_fields_requested:
        try:
            qr_expired = vehicle.is_qr_code_expired()
        except Exception:
            qr_expired = False
        if vehicle.status == 'inactive' or qr_expired:
            return jsonify({'error': "Impossible de modifier l'assurance: le véhicule est inactif ou le QR code est expiré."}), 400
        # Block modification when the current insurance is still active
        if vehicle.insurance_expiry:
            ins_exp = ensure_comoros(vehicle.insurance_expiry)
            if ins_exp > now_comoros():
                return jsonify({'error': "Impossible de modifier l'assurance: l'assurance actuelle est encore active jusqu'au "
                                         + ins_exp.strftime('%d/%m/%Y') + "."}), 400

    # Tax agents can renew vignette only when vehicle QR code is active.
    vignette_update_requested = 'vignette_expiry' in data
    if getattr(current_user, 'role', None) == 'agent_impot' and vignette_update_requested:
        try:
            qr_expired = vehicle.is_qr_code_expired()
        except Exception:
            qr_expired = False
        if qr_expired:
            return jsonify({'error': 'Impossible de renouveler la vignette: le QR code du véhicule est expiré. Activez d\'abord le QR code.'}), 400
        if not getattr(vehicle, 'vignette_payment_approved', False):
            return jsonify({'error': 'Impossible de renouveler la vignette: le paiement Mobile Money doit être approuvé d\'abord.'}), 400
    
    owner_phone = (data.get('owner_phone') or '').strip()
    if 'owner_phone' in data and not owner_phone:
        return jsonify({'error': 'owner_phone requis'}), 400

    # Mettre à jour les champs autorisés
    date_fields = ['registration_expiry', 'insurance_expiry', 'vignette_expiry']
    for field in ['license_plate', 'owner_name', 'owner_phone', 'owner_island', 'vehicle_type', 'fuel_type', 'usage_type', 'color', 'status', 'make', 'model', 'year', 'vin', 'owner_address', 'registration_expiry', 'insurance_company', 'insurance_expiry', 'vignette_expiry', 'fiscal_class', 'cv_class', 'notes', 'work_zone']:
        if field in data and data.get(field) is not None:
            # Handle empty strings for date fields - set to None instead
            if field in date_fields and data.get(field) == '':
                setattr(vehicle, field, None)
            else:
                setattr(vehicle, field, data.get(field))
    
    # parse registration_expiry if present
    if 'registration_expiry' in data and data.get('registration_expiry'):
        try:
            vehicle.registration_expiry = datetime.fromisoformat(data.get('registration_expiry'))
        except Exception:
            pass
    # parse insurance_expiry if present
    if 'insurance_expiry' in data and data.get('insurance_expiry'):
        try:
            vehicle.insurance_expiry = datetime.fromisoformat(data.get('insurance_expiry'))
        except Exception:
            pass
    # parse vignette_expiry if present - Force to March 31st (Comores regulation)
    if 'vignette_expiry' in data and data.get('vignette_expiry'):
        # If client provided a reference date, compute the March 31st expiry for that date's year
        try:
            ref_dt = datetime.fromisoformat(data.get('vignette_expiry'))
            vehicle.vignette_expiry = get_vignette_expiry_date(ref_dt)
        except Exception:
            # Fallback to compute based on now if parsing fails
            vehicle.vignette_expiry = get_vignette_expiry_date(now_comoros())
    elif 'vignette_expiry' in data and data.get('vignette_expiry') == '':
        # Allow clearing vignette_expiry by sending empty string
        vehicle.vignette_expiry = None

    auto_paid_fines = []
    if getattr(current_user, 'role', None) == 'agent_impot' and vignette_update_requested:
        old_vignette_expiry = old_values.get('vignette_expiry')
        old_vignette_expiry_cmp = old_vignette_expiry.replace(tzinfo=None) if isinstance(old_vignette_expiry, datetime) else None
        now_cmp = now_comoros().replace(tzinfo=None)
        was_vignette_expired = bool(old_vignette_expiry_cmp and old_vignette_expiry_cmp < now_cmp)
        if was_vignette_expired:
            payer_name = current_user.username if (current_user and getattr(current_user, 'is_authenticated', False)) else 'agent_impot'
            unpaid_fines = Fine.query.filter_by(vehicle_id=vehicle.id, paid=False).order_by(Fine.issued_at.asc()).all()
            auto_paid_fines_amount = sum(float(f.amount or 0) for f in unpaid_fines)
            for fine in unpaid_fines:
                _apply_fine_payment(
                    fine,
                    payer_name,
                    'Paiement automatique lors du renouvellement de vignette par agent d\'impôt'
                )
                auto_paid_fines.append(fine)
            if auto_paid_fines_amount > 0:
                vehicle.vignette_last_paid_fines_amount = auto_paid_fines_amount
        vehicle.vignette_payment_approved = False
        vehicle.vignette_payment_approved_at = None
        vehicle.vignette_payment_approved_by = None
        vehicle.vignette_payment_method = None
    
    def _normalize_for_compare(value):
        if isinstance(value, datetime):
            return value.replace(tzinfo=None)
        if isinstance(value, str):
            return value.strip()
        return value

    def _is_blank(value):
        return value is None or (isinstance(value, str) and value.strip() == '')

    def _display_value(field_name, value):
        if value is None or value == '':
            return '—'
        if field_name in ['registration_expiry', 'insurance_expiry', 'vignette_expiry'] and isinstance(value, datetime):
            return value.strftime('%d/%m/%Y')
        if field_name == 'status':
            status_labels = {'active': 'Actif', 'inactive': 'Inactif', 'suspended': 'Suspendu'}
            return status_labels.get(value, value)
        return str(value)

    field_labels = {
        'license_plate': 'Immatriculation',
        'owner_name': 'Propriétaire',
        'owner_phone': 'Téléphone propriétaire',
        'owner_island': 'Île',
        'vehicle_type': 'Type de véhicule',
        'fuel_type': 'Carburant',
        'usage_type': 'Type d\'usage',
        'color': 'Couleur',
        'status': 'Statut',
        'make': 'Marque',
        'model': 'Modèle',
        'year': 'Année',
        'vin': 'VIN',
        'owner_address': 'Adresse propriétaire',
        'registration_expiry': 'Expiration vignette',
        'insurance_company': 'Compagnie d\'assurance',
        'insurance_expiry': 'Expiration assurance',
        'vignette_expiry': 'Expiration vignette automobile',
        'notes': 'Notes'
    }

    try:
        officer = current_user.username if (current_user and getattr(current_user, 'is_authenticated', False)) else 'Système'
    except Exception:
        officer = 'Système'

    for field in tracked_fields:
        old_value = old_values.get(field)
        new_value = getattr(vehicle, field)
        if _is_blank(old_value) and _is_blank(new_value):
            continue
        if _normalize_for_compare(old_value) == _normalize_for_compare(new_value):
            continue

        label = field_labels.get(field, field)
        hist = VehicleHistory(
            vehicle_id=vehicle.id,
            action=f"Mise à jour: {label}",
            officer=officer,
            notes=f"Ancien: {_display_value(field, old_value)} → Nouveau: {_display_value(field, new_value)}"
        )
        db.session.add(hist)
    
    # Auto-assign/reassign to insurance account if insurance_company changed
    if 'insurance_company' in data:
        insurance_company = data.get('insurance_company')
        if insurance_company and insurance_company.strip() and insurance_company != 'Autre':
            try:
                # Remove old assignments for this vehicle
                VehicleInsuranceAssignment.query.filter_by(vehicle_id=vehicle.id).delete()
                
                # Find the insurance by company name
                insurance = Insurance.query.filter_by(company_name=insurance_company).first()
                if insurance and insurance.accounts:
                    # Use the first account for this insurance
                    account = insurance.accounts[0]
                    assignment = VehicleInsuranceAssignment(
                        vehicle_id=vehicle.id,
                        insurance_account_id=account.id,
                        assigned_by='system',
                        notes='Auto-assigned on vehicle update'
                    )
                    db.session.add(assignment)
            except Exception as e:
                # Log but don't fail vehicle update if assignment fails
                print(f"Warning: Could not auto-assign vehicle to insurance account: {e}")
    
    db.session.commit()

    if 'owner_phone' in data or 'owner_name' in data:
        _sync_vehicle_owner_link(vehicle)
    
    # Log action in user history
    try:
        from app.models import UserHistory
        # Build a summary of changes
        changes = []
        for field in tracked_fields:
            old_value = old_values.get(field)
            new_value = getattr(vehicle, field)
            if _normalize_for_compare(old_value) != _normalize_for_compare(new_value):
                label = field_labels.get(field, field)
                changes.append(label)
        
        if changes:
            user_history = UserHistory(
                user_id=current_user.id,
                action='Véhicule modifié',
                details=f'Véhicule {vehicle.license_plate}: {" | ".join(changes[:3])}' + (f' + {len(changes)-3} autres' if len(changes) > 3 else '') + (f' | {len(auto_paid_fines)} amende(s) payée(s) automatiquement' if auto_paid_fines else '')
            )
            db.session.add(user_history)
            db.session.commit()
    except Exception as e:
        print(f'Error logging vehicle update: {e}')
    
    return jsonify(vehicle.to_dict())


@vehicle_bp.route('/<int:vehicle_id>', methods=['DELETE'])
@login_required
def delete_vehicle(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    license_plate = vehicle.license_plate
    owner_name = vehicle.owner_name

    # Prevent deletion when a vehicle has history rows that require vehicle_id.
    if vehicle.history.count() > 0:
        return jsonify({'error': 'Cette voiture ne peut pas etre supprimee car elle a un historique.'}), 400
    
    try:
        db.session.delete(vehicle)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Cette voiture ne peut pas etre supprimee car elle a un historique.'}), 400
    except Exception:
        db.session.rollback()
        return jsonify({'error': 'Erreur serveur lors de la suppression du vehicule.'}), 500
    
    # Log action in user history
    try:
        from app.models import UserHistory
        user_history = UserHistory(
            user_id=current_user.id,
            action='Véhicule supprimé',
            details=f'Véhicule {license_plate} - {owner_name}'
        )
        db.session.add(user_history)
        db.session.commit()
    except Exception as e:
        print(f'Error logging vehicle deletion: {e}')
    
    return jsonify({'message': 'Véhicule supprimé'})


# Exoneration routes
@vehicle_bp.route('/exonerated/list', methods=['GET'])
@login_required
def get_exonerated_vehicles():
    """Retourner la liste des véhicules exonérés"""
    from app.models import ExoneratedVehicle
    exonerated = ExoneratedVehicle.query.order_by(ExoneratedVehicle.created_at.desc()).all()
    return jsonify([e.to_dict() for e in exonerated])


@vehicle_bp.route('/exonerated/add', methods=['POST'])
@login_required
def add_exonerated_vehicle():
    """Ajouter un véhicule à la liste d'exonération"""
    from app.models import ExoneratedVehicle, VehicleHistory
    
    data = request.get_json() or request.form
    vehicle_id = data.get('vehicle_id')
    reason = data.get('reason')
    notes = data.get('notes', '')
    
    if not vehicle_id or not reason:
        return jsonify({'error': 'vehicle_id et reason requis'}), 400
    
    # Verify vehicle exists
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    
    # Check if already exonerated
    existing = ExoneratedVehicle.query.filter_by(vehicle_id=vehicle_id).first()
    if existing:
        return jsonify({'error': 'Ce véhicule est déjà exonéré'}), 400
    
    # Get current user
    try:
        from flask_login import current_user
        added_by = current_user.username if (current_user and getattr(current_user, 'is_authenticated', False)) else 'Système'
    except Exception:
        added_by = 'Système'
    
    # Create exoneration
    exonerated = ExoneratedVehicle(
        vehicle_id=vehicle_id,
        reason=reason,
        added_by=added_by,
        notes=notes
    )
    db.session.add(exonerated)
    
    # Add history entry
    hist = VehicleHistory(
        vehicle_id=vehicle_id,
        action=f"Véhicule ajouté à la liste d'exonération",
        officer=added_by,
        notes=f"Raison: {reason}"
    )
    db.session.add(hist)
    db.session.commit()
    
    return jsonify(exonerated.to_dict()), 201


@vehicle_bp.route('/exonerated/<int:exoneration_id>', methods=['DELETE'])
@login_required
def remove_exonerated_vehicle(exoneration_id):
    """Retirer un véhicule de la liste d'exonération"""
    from app.models import ExoneratedVehicle, VehicleHistory
    
    exonerated = ExoneratedVehicle.query.get_or_404(exoneration_id)
    vehicle_id = exonerated.vehicle_id
    
    # Get current user
    try:
        from flask_login import current_user
        removed_by = current_user.username if (current_user and getattr(current_user, 'is_authenticated', False)) else 'Système'
    except Exception:
        removed_by = 'Système'
    
    # Add history entry
    hist = VehicleHistory(
        vehicle_id=vehicle_id,
        action=f"Véhicule retiré de la liste d'exonération",
        officer=removed_by,
        notes=""
    )
    db.session.add(hist)
    
    # Remove exoneration
    db.session.delete(exonerated)
    db.session.commit()
    
    return jsonify({'message': 'Exonération supprimée'})


# ===== PHONES MANAGEMENT =====

@main_bp.route('/phones')
@roles_required('administrateur','policier')
def phones_page():
    """Display phones management page"""
    return render_template('phones.html')

@main_bp.route('/phone-usage')
@roles_required('administrateur','policier')
def phone_usage_page():
    """Display phone usage history page"""
    return render_template('phone_usage.html')


@main_bp.route('/phone/<int:phone_id>/history')
@roles_required('administrateur','policier')
def phone_history_page(phone_id):
    """Display usage history for a specific phone"""
    phone = Phone.query.get(phone_id)
    if not phone:
        abort(404)
    check_island_access(phone.island)
    return render_template('phone_history.html', phone_id=phone_id, return_to=request.args.get('return_to', '/phones'))


@main_bp.route('/photo-submissions')
@roles_required('administrateur','judiciaire')
def photo_submissions_page():
    """Display photo submissions page"""
    return render_template('photo_submissions.html')


# Insurance Management Routes
@vehicle_bp.route('/insurances', methods=['GET'])
@login_required
def get_insurances():
    """Get all insurance companies
    - Administrateur: voit toutes les compagnies
    - Judiciaire/Policier: voit seulement les compagnies de leur pays
    """
    query = Insurance.query
    
    # Apply island filter for judiciaire and policier users
    if current_user.role in ['judiciaire', 'policier'] and current_user.country:
        query = query.filter(
            (Insurance.island == current_user.country) | (Insurance.island == '') | (Insurance.island == None)
        )
    
    insurances = query.order_by(Insurance.company_name).all()
    return jsonify({
        "insurances": [ins.to_dict() for ins in insurances]
    })


@vehicle_bp.route('/insurances', methods=['POST'])
@login_required
def create_insurance():
    """Create a new insurance company
    - Administrateur: can add for any island
    - Judiciaire/Policier: can add only for their country
    """
    data = request.get_json() or {}
    company_name = data.get('company_name', '').strip()
    
    if not company_name:
        return jsonify({"error": "Company name is required"}), 400
    
    # Check if already exists
    existing = Insurance.query.filter_by(company_name=company_name).first()
    if existing:
        return jsonify({"error": "This insurance company already exists"}), 400
    
    # For judiciaire/policier, force island to their country
    island = data.get('island', '')
    if current_user.role in ['judiciaire', 'policier']:
        if not current_user.country:
            return jsonify({"error": "Your country must be set"}), 400
        island = current_user.country
    
    insurance = Insurance(
        company_name=company_name,
        phone=data.get('phone', '').strip(),
        island=island,
        address=data.get('address', '').strip()
    )
    
    db.session.add(insurance)
    db.session.commit()
    
    return jsonify(insurance.to_dict()), 201


@vehicle_bp.route('/insurances/<int:insurance_id>', methods=['PUT'])
@login_required
def update_insurance(insurance_id):
    """Update an insurance company
    - Administrateur: can update any insurance
    - Judiciaire/Policier: can update only insurances for their country
    """
    insurance = Insurance.query.get_or_404(insurance_id)
    
    # Check permissions for judiciaire/policier
    if current_user.role in ['judiciaire', 'policier']:
        if insurance.island != current_user.country:
            return jsonify({"error": "Forbidden"}), 403
    
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
    
    # Island can only be changed by admin
    if 'island' in data and current_user.role == 'administrateur':
        insurance.island = data.get('island', '')
    
    if 'address' in data:
        insurance.address = data.get('address', '').strip()
    
    db.session.commit()
    return jsonify(insurance.to_dict())


@vehicle_bp.route('/insurances/<int:insurance_id>', methods=['DELETE'])
@login_required
def delete_insurance(insurance_id):
    """Delete an insurance company
    - Administrateur: can delete any insurance
    - Judiciaire/Policier: can delete only insurances for their country
    """
    insurance = Insurance.query.get_or_404(insurance_id)
    
    # Check permissions for judiciaire/policier
    if current_user.role in ['judiciaire', 'policier']:
        if insurance.island != current_user.country:
            return jsonify({"error": "Forbidden"}), 403
    
    db.session.delete(insurance)
    db.session.commit()
    
    return jsonify({"message": "Insurance deleted successfully"})


# ==================== INSURANCE ACCOUNT MANAGEMENT ====================

@vehicle_bp.route('/insurance-accounts', methods=['GET'])
@login_required
def get_insurance_accounts():
    """Get all insurance accounts (admin only)"""
    # Check if user is an admin (regular User)
    if not hasattr(current_user, 'role') or current_user.role != 'administrateur':
        return jsonify({"error": "Forbidden"}), 403
    
    accounts = InsuranceAccount.query.order_by(InsuranceAccount.created_at.desc()).all()
    return jsonify({
        "accounts": [acc.to_dict() for acc in accounts]
    })


@vehicle_bp.route('/insurance-accounts', methods=['POST'])
@login_required
def create_insurance_account():
    """Create a new insurance account (admin only)"""
    if not hasattr(current_user, 'role') or current_user.role != 'administrateur':
        return jsonify({"error": "Forbidden"}), 403
    
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    insurance_id = data.get('insurance_id')
    
    if not username or not password or not insurance_id:
        return jsonify({"error": "Username, password, and insurance_id are required"}), 400
    
    # Check if username already exists
    existing = InsuranceAccount.query.filter_by(username=username).first()
    if existing:
        return jsonify({"error": "Username already exists"}), 400
    
    # Verify insurance exists
    insurance = Insurance.query.get(insurance_id)
    if not insurance:
        return jsonify({"error": "Insurance company not found"}), 404
    
    account = InsuranceAccount(
        insurance_id=insurance_id,
        username=username,
        contact_person=data.get('contact_person', '').strip(),
        contact_email=data.get('contact_email', '').strip(),
        contact_phone=data.get('contact_phone', '').strip(),
        is_active=data.get('is_active', True)
    )
    account.set_password(password)
    
    db.session.add(account)
    db.session.commit()
    
    return jsonify(account.to_dict()), 201


@vehicle_bp.route('/insurance-accounts/<int:account_id>', methods=['PUT'])
@login_required
def update_insurance_account(account_id):
    """Update an insurance account (admin only)"""
    if not hasattr(current_user, 'role') or current_user.role != 'administrateur':
        return jsonify({"error": "Forbidden"}), 403
    
    account = InsuranceAccount.query.get_or_404(account_id)
    data = request.get_json() or {}

    if 'username' in data:
        new_username = data.get('username', '').strip()
        if not new_username:
            return jsonify({"error": "Username is required"}), 400
        existing = InsuranceAccount.query.filter_by(username=new_username).first()
        if existing and existing.id != account_id:
            return jsonify({"error": "Username already exists"}), 400
        account.username = new_username

    if 'insurance_id' in data:
        insurance_id = data.get('insurance_id')
        insurance = Insurance.query.get(insurance_id)
        if not insurance:
            return jsonify({"error": "Insurance company not found"}), 404
        account.insurance_id = insurance_id
    
    if 'contact_person' in data:
        account.contact_person = data.get('contact_person', '').strip()
    if 'contact_email' in data:
        account.contact_email = data.get('contact_email', '').strip()
    if 'contact_phone' in data:
        account.contact_phone = data.get('contact_phone', '').strip()
    if 'is_active' in data:
        account.is_active = data.get('is_active')
    if 'password' in data and data.get('password'):
        account.set_password(data.get('password'))
    
    db.session.commit()
    return jsonify(account.to_dict())


@vehicle_bp.route('/insurance-accounts/<int:account_id>', methods=['DELETE'])
@login_required
def delete_insurance_account(account_id):
    """Delete an insurance account (admin only)"""
    if not hasattr(current_user, 'role') or current_user.role != 'administrateur':
        return jsonify({"error": "Forbidden"}), 403
    
    account = InsuranceAccount.query.get_or_404(account_id)
    
    # Delete associated assignments
    VehicleInsuranceAssignment.query.filter_by(insurance_account_id=account_id).delete()
    
    db.session.delete(account)
    db.session.commit()
    
    return jsonify({"message": "Insurance account deleted successfully"})


# ==================== INSURANCE DASHBOARD ====================

@vehicle_bp.route('/insurance-accounts/me', methods=['GET'])
@login_required
def get_current_insurance_account():
    """Get current insurance account info (insurance accounts only)"""
    if not isinstance(current_user, InsuranceAccount):
        return jsonify({"error": "Not an insurance account"}), 403
    
    data = current_user.to_dict()
    data['insurance_id']   = current_user.id
    data['insurance_year'] = current_user.created_at.strftime('%Y') if current_user.created_at else now_comoros().strftime('%Y')
    data['has_attestation_template'] = bool(current_user.attestation_template)
    return jsonify(data)


@vehicle_bp.route('/insurance-accounts/me', methods=['PUT'])
@login_required
def update_insurance_account_profile():
    """Update insurance account profile (insurance accounts only)"""
    if not isinstance(current_user, InsuranceAccount):
        return jsonify({"error": "Not an insurance account"}), 403
    
    data = request.get_json()
    
    # Update allowed fields
    if 'contact_person' in data:
        current_user.contact_person = data['contact_person']
    if 'contact_email' in data:
        current_user.contact_email = data['contact_email']
    if 'contact_phone' in data:
        current_user.contact_phone = data['contact_phone']
    
    try:
        db.session.commit()
        return jsonify({
            "message": "Profile updated successfully",
            "account": current_user.to_dict()
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400


@vehicle_bp.route('/insurance-accounts/me/attestation-template', methods=['GET'])
@login_required
def get_attestation_template():
    if not isinstance(current_user, InsuranceAccount):
        return jsonify({"error": "Forbidden"}), 403
    tpl = {}
    if current_user.attestation_template:
        try:
            tpl = json.loads(current_user.attestation_template)
        except Exception:
            tpl = {}
    return jsonify(tpl)


@vehicle_bp.route('/insurance-accounts/me/attestation-template', methods=['PUT'])
@login_required
def save_attestation_template():
    if not isinstance(current_user, InsuranceAccount):
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json() or {}
    current_user.attestation_template = json.dumps(data)
    db.session.commit()
    return jsonify({"message": "Maquette enregistrée"}), 200


@vehicle_bp.route('/insurance-accounts/me/attestation-logo', methods=['POST'])
@login_required
def upload_attestation_logo():
    import uuid
    from werkzeug.utils import secure_filename
    if not isinstance(current_user, InsuranceAccount):
        return jsonify({"error": "Forbidden"}), 403
    file = request.files.get('logo')
    if not file or not file.filename:
        return jsonify({"error": "Aucun fichier reçu"}), 400
    ext = os.path.splitext(secure_filename(file.filename))[1].lower()
    if ext not in {'.jpg', '.jpeg', '.png', '.webp', '.gif'}:
        return jsonify({"error": "Format non autorisé (jpg, png, webp, gif)"}), 400
    from app.cloudinary_utils import is_cloudinary_enabled, upload_file as cloud_upload, delete_file as cloud_delete, file_url as cloud_file_url
    # Delete old logo if exists — use logo_stored (raw value) or fallback to logo_url
    if current_user.attestation_template:
        try:
            tpl = json.loads(current_user.attestation_template)
            old_stored = tpl.get('logo_stored') or tpl.get('logo_url')
            if old_stored:
                cloud_delete(old_stored, local_folder='insurance_logos')
        except Exception:
            pass
    if is_cloudinary_enabled():
        logo_stored = cloud_upload(file, 'insurance_logos')  # full https:// URL
        logo_url = logo_stored
    else:
        upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'insurance_logos')
        os.makedirs(upload_dir, exist_ok=True)
        filename = f"{uuid.uuid4().hex}{ext}"
        file.save(os.path.join(upload_dir, filename))
        logo_stored = filename                              # raw filename for deletion
        logo_url = cloud_file_url(filename, 'insurance_logos')  # display URL
    return jsonify({"logo_url": logo_url, "logo_stored": logo_stored}), 200


@vehicle_bp.route('/insurance-accounts/me/attestation-template', methods=['DELETE'])
@login_required
def delete_attestation_template():
    if not isinstance(current_user, InsuranceAccount):
        return jsonify({"error": "Forbidden"}), 403
    # Delete logo file — use logo_stored (raw value) or fallback to logo_url
    if current_user.attestation_template:
        try:
            tpl = json.loads(current_user.attestation_template)
            old_stored = tpl.get('logo_stored') or tpl.get('logo_url')
            if old_stored:
                from app.cloudinary_utils import delete_file as cloud_delete
                cloud_delete(old_stored, local_folder='insurance_logos')
        except Exception:
            pass
    current_user.attestation_template = None
    db.session.commit()
    return jsonify({"message": "Maquette supprimée"}), 200


@main_bp.route('/insurance-attestation/<int:vehicle_id>/print')
@login_required
def insurance_attestation_print(vehicle_id):
    if not isinstance(current_user, InsuranceAccount) or not current_user.is_active:
        abort(403)
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    tpl = {}
    if current_user.attestation_template:
        try:
            tpl = json.loads(current_user.attestation_template)
        except Exception:
            tpl = {}
    # Strip logo_b64 from the embedded JSON — it can be hundreds of KB and slows the
    # initial page load. The print page fetches it separately via a lightweight JS call.
    tpl_without_logo = {k: v for k, v in tpl.items() if k != 'logo_b64'}
    created_year = current_user.created_at.strftime('%Y') if current_user.created_at else now_comoros().strftime('%Y')
    vehicle_data = {
        'id': vehicle.id,
        'license_plate': vehicle.license_plate,
        'owner_name': vehicle.owner_name,
        'owner_address': vehicle.owner_address or vehicle.owner_island or '',
        'vehicle_type': vehicle.vehicle_type,
        'model': vehicle.model or '',
        'insurance_expiry': vehicle.insurance_expiry.strftime('%d/%m/%Y') if vehicle.insurance_expiry else '—',
        'today': now_comoros().strftime('%d/%m/%Y'),
        'insurance_id': current_user.id,
        'insurance_year': created_year,
    }
    return render_template('insurance_attestation_print.html',
                           vehicle_json=json.dumps(vehicle_data),
                           tpl_json=json.dumps(tpl_without_logo))


@vehicle_bp.route('/insurance-accounts/me/password', methods=['PUT'])
@login_required
def update_insurance_account_password():
    """Update insurance account password (insurance accounts only)"""
    if not isinstance(current_user, InsuranceAccount):
        return jsonify({"error": "Not an insurance account"}), 403
    
    data = request.get_json()
    
    if not data.get('current_password'):
        return jsonify({"error": "Current password is required"}), 400
    
    if not data.get('new_password'):
        return jsonify({"error": "New password is required"}), 400
    
    # Verify current password
    if not current_user.check_password(data['current_password']):
        return jsonify({"error": "Current password is incorrect"}), 400
    
    # Check password length
    if len(data['new_password']) < 6:
        return jsonify({"error": "New password must be at least 6 characters"}), 400
    
    # Set new password
    current_user.set_password(data['new_password'])
    
    try:
        db.session.commit()
        return jsonify({"message": "Password updated successfully"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400


@vehicle_bp.route('/insurance-vehicles', methods=['GET'])
@login_required
def get_insurance_vehicles():
    """Get vehicles assigned to current insurance account (insurance accounts only)"""
    if not isinstance(current_user, InsuranceAccount):
        return jsonify({"error": "Not an insurance account"}), 403
    
    # Get the insurance company name for this account
    insurance_company_name = current_user.insurance.company_name if current_user.insurance else None
    
    vehicles = []
    
    # Method 1: Get assignments for this account (new vehicles)
    assignments = VehicleInsuranceAssignment.query.filter_by(insurance_account_id=current_user.id).all()
    vehicle_ids = [a.vehicle_id for a in assignments]
    
    if vehicle_ids:
        assigned_vehicles = Vehicle.query.filter(
            Vehicle.id.in_(vehicle_ids),
            Vehicle.qr_pending_approval == False
        ).order_by(Vehicle.license_plate).all()
        vehicles.extend(assigned_vehicles)

    # Method 2: Also get vehicles that have this insurance company in insurance_company field (for backward compatibility)
    # This handles existing vehicles that haven't been formally assigned yet
    if insurance_company_name:
        legacy_vehicles = Vehicle.query.filter_by(
            insurance_company=insurance_company_name
        ).filter(Vehicle.qr_pending_approval == False).order_by(Vehicle.license_plate).all()
        # Avoid duplicates
        existing_ids = set(v.id for v in vehicles)
        for v in legacy_vehicles:
            if v.id not in existing_ids:
                vehicles.append(v)

    from app.models import QRCodePayment
    # Most recent QR payment per vehicle (for sort order)
    vehicle_ids_all = [v.id for v in vehicles]
    last_payments = {}
    if vehicle_ids_all:
        rows = QRCodePayment.query.filter(
            QRCodePayment.vehicle_id.in_(vehicle_ids_all),
            QRCodePayment.status == 'paid',
        ).order_by(QRCodePayment.paid_at.desc()).all()
        for p in rows:
            if p.vehicle_id not in last_payments:
                last_payments[p.vehicle_id] = p.paid_at

    assignment_map = {a.vehicle_id: a for a in assignments}

    vehicles_payload = []
    for vehicle in vehicles:
        vehicle_data = vehicle.to_dict()
        vehicle_data['has_unpaid_fines'] = vehicle_has_unpaid_fines(vehicle.id)
        vehicle_data['block_reason'] = get_vehicle_block_reason_for_insurance(vehicle)
        vehicle_data['unpaid_fine'] = fine_to_block_payload(get_first_unpaid_fine(vehicle.id))
        lp = last_payments.get(vehicle.id)
        vehicle_data['last_payment_at'] = lp.isoformat() if lp else None
        a = assignment_map.get(vehicle.id)
        vehicle_data['driver_license_numbers'] = json.loads(a.driver_license_numbers) if (a and a.driver_license_numbers) else []
        # Sort key: most recent among assigned_at and vehicle updated_at
        assigned_at = a.assigned_at.isoformat() if (a and a.assigned_at) else '0000'
        updated_at  = vehicle.updated_at.isoformat() if vehicle.updated_at else '0000'
        vehicle_data['_sort_key'] = max(assigned_at, updated_at)
        vehicles_payload.append(vehicle_data)

    # Sort: most recently added or renewed first
    vehicles_payload.sort(key=lambda v: v['_sort_key'], reverse=True)

    return jsonify({
        "vehicles": vehicles_payload
    })


@vehicle_bp.route('/insurance-alerts', methods=['GET'])
@login_required
def get_insurance_alerts():
    """Return alerts linked to vehicles assigned to current insurance account."""
    if not isinstance(current_user, InsuranceAccount):
        return jsonify({"error": "Not an insurance account"}), 403

    from app.models import Alert, alert_vehicles as alert_vehicles_table

    insurance_company_name = current_user.insurance.company_name if current_user.insurance else None

    # Collect vehicle IDs for this account
    assigned_ids = {
        a.vehicle_id
        for a in VehicleInsuranceAssignment.query.filter_by(insurance_account_id=current_user.id).all()
    }
    if insurance_company_name:
        legacy_ids = {
            v.id for v in Vehicle.query.filter_by(insurance_company=insurance_company_name).all()
        }
        assigned_ids |= legacy_ids

    if not assigned_ids:
        return jsonify({"alerts": []})

    # Find alert IDs that link to any of those vehicles
    from sqlalchemy import select as sa_select
    rows = db.session.execute(
        sa_select(alert_vehicles_table.c.alert_id)
        .where(alert_vehicles_table.c.vehicle_id.in_(assigned_ids))
    ).fetchall()
    alert_ids = list({r[0] for r in rows})

    if not alert_ids:
        return jsonify({"alerts": []})

    alerts = Alert.query.filter(Alert.id.in_(alert_ids)).order_by(Alert.starts_at.desc()).all()

    result = []
    for alert in alerts:
        d = alert.to_dict()
        # Only keep vehicles that belong to this account
        d['vehicles'] = [v for v in d['vehicles'] if v['id'] in assigned_ids]
        result.append(d)

    return jsonify({"alerts": result})


@vehicle_bp.route('/vignette-vehicles', methods=['GET'])
@login_required
@roles_required('agent_impot', 'mobile_money_agent')
def get_vignette_vehicles():
    """Get vehicles with vignettes for tax agents"""
    # Get country/region filter from current user
    user_country = getattr(current_user, 'country', None)

    # Mobile Money agents should be able to see transactions across all islands
    # (do not apply the country filter for this role)
    if getattr(current_user, 'role', None) == 'mobile_money_agent':
        user_country = None
    
    # Base query: vehicles with an active vignette or a pending payment request
    query = Vehicle.query.filter(
        Vehicle.qr_pending_approval == False,
        (Vehicle.vignette_expiry.isnot(None)) | (Vehicle.vignette_payment_requested_at.isnot(None))
    )
    # Exclude vehicles missing required attributes (treat them as if they don't have a vignette)
    query = query.filter(
        Vehicle.fuel_type.isnot(None), Vehicle.fuel_type != '',
        Vehicle.fiscal_class.isnot(None), Vehicle.fiscal_class != '',
        Vehicle.cv_class.isnot(None), Vehicle.cv_class != '',
        Vehicle.vin.isnot(None), Vehicle.vin != ''
    )
    
    # Filter by user's country if set (regional agent)
    # Super admin agents without country see all vignettes
    if user_country:
        query = query.filter(Vehicle.owner_island == user_country)
    
    vehicles = query.order_by(Vehicle.license_plate).all()
    
    vehicles_payload = []
    now = ensure_comoros(now_comoros())
    
    for vehicle in vehicles:
        vehicle_data = vehicle.to_dict()
        
        # Calculate vignette status
        vignette_expiry = vehicle.vignette_expiry or vehicle.vignette_payment_requested_expiry
        if isinstance(vignette_expiry, str):
            try:
                vignette_expiry = datetime.fromisoformat(vignette_expiry)
            except Exception:
                vignette_expiry = None
        if vignette_expiry:
            try:
                vignette_expiry = ensure_comoros(vignette_expiry)
            except Exception:
                vignette_expiry = None

        pending_request_expiry = get_pending_vignette_request_expiry(vehicle)
        if pending_request_expiry:
            try:
                pending_request_expiry = ensure_comoros(pending_request_expiry)
            except Exception:
                pass
        has_pending_vignette_request = bool(
            pending_request_expiry
            and not getattr(vehicle, 'vignette_payment_approved', False)
        )
        if not vehicle.vignette_expiry and has_pending_vignette_request:
            vignette_status = 'pending'
        else:
            if vignette_expiry:
                if vignette_expiry < now:
                    vignette_status = 'expired'
                elif vignette_expiry < now + timedelta(days=30):
                    vignette_status = 'expiring'
                else:
                    vignette_status = 'active'
            else:
                vignette_status = 'no_vignette'
        
        vehicle_data['vignette_status'] = vignette_status

        vehicle_data['vignette_payment_request_pending'] = bool(
            pending_request_expiry
            and not getattr(vehicle, 'vignette_payment_approved', False)
            and vignette_status in ('expired', 'no_vignette')
        )
        if vignette_status == 'pending':
            vehicle_data['vignette_payment_request_pending'] = True
        vehicle_data['vignette_requested_expiry'] = pending_request_expiry.isoformat() if pending_request_expiry else None

        # Calculate vignette price based on vehicle attributes
        vignette_price = calculate_vignette_price(vehicle)
        vehicle_data['vignette_price'] = vignette_price
        
        payment_approved = bool(getattr(vehicle, 'vignette_payment_approved', False))

        # Determine renewal period status
        renewal_opening = get_renewal_opening_datetime()
        in_renewal_period = (
            renewal_opening is not None
            and now >= renewal_opening
            and (not vignette_expiry or vignette_expiry >= now)
            and not payment_approved
        )
        vehicle_data['renewal_period_open'] = bool(renewal_opening)
        vehicle_data['renewal_needed'] = in_renewal_period

        # Calculate penalty amount based on days late unless payment has already been approved,
        # in which case we keep the approved amount frozen for display.
        #
        # Penalties apply ONLY when the vignette has expired (March 31st has passed).
        # Aux Comores: Les pénalités s'appliquent uniquement après le 31 mars (date d'expiration).
        if payment_approved:
            vehicle_data['penalty_amount'] = float(getattr(vehicle, 'vignette_last_paid_penalty_amount', 0.0) or 0.0)
        elif vignette_expiry and vignette_expiry < now:
            # Vignette is expired: calculate current penalty based on days overdue
            days_late = (now - vignette_expiry).days
            penalty_amount = calculate_penalty_amount(days_late)
            vehicle_data['penalty_amount'] = penalty_amount
        else:
            # Vignette still valid (renewal window or active): no current penalty
            vehicle_data['penalty_amount'] = 0.0

        # Add fines amount
        unpaid_fines = Fine.query.filter_by(vehicle_id=vehicle.id, paid=False).all()
        total_fines_amount = sum(float(f.amount) if f.amount else 0 for f in unpaid_fines)
        if payment_approved:
            # Payment approved: freeze what was included in the approved payment
            vehicle_data['unpaid_fines_amount'] = float(getattr(vehicle, 'vignette_last_paid_fines_amount', 0.0) or 0.0)
            vehicle_data['unpaid_fines_count'] = 0
        elif total_fines_amount > 0:
            # Current unpaid fines exist: show them
            vehicle_data['unpaid_fines_amount'] = total_fines_amount
            vehicle_data['unpaid_fines_count'] = len(unpaid_fines)
        else:
            # No current unpaid fines: show 0 (old paid amounts are historical, not due)
            vehicle_data['unpaid_fines_amount'] = 0.0
            vehicle_data['unpaid_fines_count'] = 0
        
        vehicles_payload.append(vehicle_data)
    
    return jsonify({
        "vehicles": vehicles_payload,
        "total": len(vehicles_payload)
    })


@vehicle_bp.route('/<int:vehicle_id>/vignette/payment-approve', methods=['POST'])
@login_required
@roles_required('mobile_money_agent')
def approve_vignette_payment(vehicle_id):
    """Approve a manual payment for an expired vignette renewal."""
    from app.models import VehicleHistory

    # Normalize vignette expiry to a timezone-aware Comoros datetime before comparing
    from app.timezone_utils import ensure_comoros

    vehicle = Vehicle.query.get_or_404(vehicle_id)
    requested_expiry = ensure_comoros(get_pending_vignette_request_expiry(vehicle))
    current_expiry = ensure_comoros(vehicle.vignette_expiry) if vehicle.vignette_expiry else None
    if not current_expiry and not requested_expiry:
        return jsonify({'error': "Ce vehicule n'a pas de vignette a confirmer."}), 400

    now_time = now_comoros()
    expiry = current_expiry or requested_expiry
    renewal_opening = get_renewal_opening_datetime()
    in_renewal_period = renewal_opening is not None and now_time >= renewal_opening
    if current_expiry and expiry >= now_time and not in_renewal_period:
        return jsonify({'error': "La periode de renouvellement n'est pas encore ouverte."}), 400

    # Early renewal: vignette is still active but the renewal window is open.
    # Approving the payment also extends the vignette to next year's cycle right away.
    early_renewal = bool(current_expiry and current_expiry >= now_time and in_renewal_period)

    if getattr(vehicle, 'vignette_payment_approved', False):
        return jsonify({'error': 'Le paiement de cette vignette est déjà approuvé.'}), 400

    data = request.get_json() or request.form
    payment_method = (data.get('payment_method') or 'mobile_money_manual').strip()

    vehicle.vignette_payment_approved = True
    vehicle.vignette_payment_approved_at = now_time
    agent_display_name = (getattr(current_user, 'full_name', None) or getattr(current_user, 'username', None)) if getattr(current_user, 'is_authenticated', False) else 'Système'
    vehicle.vignette_payment_approved_by = agent_display_name or 'Système'
    vehicle.vignette_payment_method = payment_method

    # Finalize the requested expiry date when this was a payment request for a vehicle
    # without vignette. For expired renewals, keep the renewal date equal to the approved date.
    if requested_expiry and not current_expiry:
        vehicle.vignette_expiry = requested_expiry
    elif early_renewal:
        # Citizen paid ahead of expiry during the open renewal window: extend the
        # vignette to next year's cycle (same day/month, one year later) right away.
        vehicle.vignette_expiry = ensure_comoros(datetime(
            current_expiry.year + 1, current_expiry.month, current_expiry.day, 23, 59, 59
        ))

    vignette_price = calculate_vignette_price(vehicle)
    penalty_amount = 0.0
    days_late = (now_time - expiry).days if expiry else 0
    if days_late > 0:
        penalty_amount = calculate_penalty_amount(days_late)
    unpaid_fines = Fine.query.filter_by(vehicle_id=vehicle.id, paid=False).all()
    unpaid_fines_amount = sum(float(f.amount) if f.amount else 0 for f in unpaid_fines)
    total_amount = vignette_price + penalty_amount + unpaid_fines_amount

    # Persist last paid breakdown so tax dashboard can still display paid components after renewal.
    vehicle.vignette_last_paid_at = now_time
    vehicle.vignette_last_paid_by = vehicle.vignette_payment_approved_by
    vehicle.vignette_last_paid_vignette_amount = float(vignette_price or 0.0)
    vehicle.vignette_last_paid_penalty_amount = float(penalty_amount or 0.0)
    vehicle.vignette_last_paid_fines_amount = float(unpaid_fines_amount or 0.0)
    vehicle.vignette_last_paid_total_amount = float(total_amount or 0.0)
    vehicle.vignette_payment_requested_at = None
    vehicle.vignette_payment_requested_by = None
    vehicle.vignette_payment_requested_expiry = None

    unpaid_fines_count = len(unpaid_fines)

    # Mark bundled fines as paid
    paid_fine_ids = []
    if unpaid_fines_count > 0:
        receipt_ref = f"VIGN-{vehicle.id}-{now_time.strftime('%Y%m%d%H%M%S')}"
        for f in unpaid_fines:
            f.paid = True
            f.paid_at = now_time
            f.paid_by = vehicle.vignette_payment_approved_by
            f.receipt_number = receipt_ref
            db.session.add(f)
            paid_fine_ids.append(f.id)

    # Always create a payment record in vignette payload format so the citizen app
    # can display the receipt in "Retelecharger un recu".
    from app.models import Payment
    vignette_payload = {
        'type': 'vignette_request',
        'vehicle_id': vehicle.id,
        'vignette_price': float(vignette_price or 0.0),
        'annual_ds_amount': 0.0,
        'penalty_amount': float(penalty_amount or 0.0),
        'fines_amount': float(unpaid_fines_amount or 0.0),
        'total_amount': float(total_amount or 0.0),
        'requested_expiry': vehicle.vignette_expiry.isoformat() if vehicle.vignette_expiry else None,
        'fine_ids': paid_fine_ids,
    }
    payment_record = Payment(
        amount=total_amount,
        currency='KMF',
        status='paid',
        license_plate=vehicle.license_plate,
        owner_name=vehicle.owner_name,
        payer_name=vehicle.vignette_payment_approved_by,
        payer_email=None,
        paid_at=now_time,
        fines=json.dumps(vignette_payload)
    )
    db.session.add(payment_record)

    db.session.add(VehicleHistory(
        vehicle_id=vehicle.id,
        action='Paiement vignette approuvé',
        officer=vehicle.vignette_payment_approved_by,
        notes=f"Mode: {payment_method} | Montant total: {round(total_amount, 2)} KMF | Amendes payées: {unpaid_fines_count}"
    ))
    db.session.commit()

    success_message = 'Paiement vignette approuvé avec succès.'
    if early_renewal and vehicle.vignette_expiry:
        success_message += f" Vignette renouvelée jusqu'au {vehicle.vignette_expiry.strftime('%d/%m/%Y')}."

    return jsonify({
        'ok': True,
        'vehicle': vehicle.to_dict(),
        'message': success_message,
        'vignette_price': round(vignette_price, 2),
        'penalty_amount': round(penalty_amount, 2),
        'unpaid_fines_amount': round(unpaid_fines_amount, 2),
        'total_amount': round(total_amount, 2)
    })


@vehicle_bp.route('/<int:vehicle_id>/vignette/payment-request', methods=['POST'])
@login_required
@roles_required('agent_impot')
def request_vignette_payment(vehicle_id):
    """Create a pending vignette payment request for a vehicle without vignette.

    The expiry date is only applied after Mobile Money approval.
    """
    from app.models import VehicleHistory

    vehicle = Vehicle.query.get_or_404(vehicle_id)

    if vehicle.qr_pending_approval:
        return jsonify({'error': 'Ce véhicule est en attente de validation SmartTech. Aucune vignette ne peut être ajoutée pour l\'instant.'}), 403

    # Validation: VIN is required to add a vignette
    if not vehicle.vin or not str(vehicle.vin).strip():
        return jsonify({'error': 'Impossible d\'ajouter une vignette: le véhicule n\'a pas de VIN (Numéro de série) enregistré. Veuillez d\'abord ajouter le VIN du véhicule.'}), 400

    data = request.get_json() or request.form
    requested_expiry_value = data.get('vignette_expiry')

    if not requested_expiry_value:
        return jsonify({'error': "La date d'expiration est requise."}), 400

    try:
        requested_expiry = datetime.fromisoformat(requested_expiry_value)
    except Exception:
        return jsonify({'error': 'Format de date invalide.'}), 400

    if vehicle.vignette_expiry:
        return jsonify({'error': 'Ce véhicule a déjà une vignette. Utilisez le renouvellement.'}), 400

    vignette_price = float(calculate_vignette_price(vehicle) or 0.0)
    if vignette_price <= 0:
        return jsonify({
            'error': "Impossible d'ajouter une vignette: aucun tarif n'est disponible pour cette combinaison."
        }), 400

    now_time = now_comoros()
    vehicle.vignette_payment_requested_at = now_time
    vehicle.vignette_payment_requested_by = current_user.username if getattr(current_user, 'is_authenticated', False) else 'agent_impot'
    vehicle.vignette_payment_requested_expiry = requested_expiry
    vehicle.vignette_payment_approved = False
    vehicle.vignette_payment_approved_at = None
    vehicle.vignette_payment_approved_by = None
    vehicle.vignette_payment_method = None

    db.session.add(VehicleHistory(
        vehicle_id=vehicle.id,
        action='Demande de paiement vignette créée',
        officer=vehicle.vignette_payment_requested_by,
        notes=f"Date souhaitée: {requested_expiry.strftime('%Y-%m-%d')}"
    ))

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        from app.models import Payment

        pending_payload = {
            'type': 'vignette_request',
            'vehicle_id': vehicle.id,
            'requested_expiry': requested_expiry.isoformat(),
            'vignette_price': vignette_price
        }
        db.session.add(Payment(
            amount=vignette_price,
            currency='KMF',
            status='pending',
            license_plate=vehicle.license_plate,
            owner_name=vehicle.owner_name,
            payer_name=vehicle.vignette_payment_requested_by,
            payer_email=None,
            fines=json.dumps(pending_payload)
        ))
        db.session.commit()

        return jsonify({
            'ok': True,
            'message': 'Demande de paiement envoyée à Mobile Money (file de secours).',
            'vehicle': vehicle.to_dict(),
            'warning': str(exc)
        })

    return jsonify({
        'ok': True,
        'message': 'Demande de paiement envoyée à Mobile Money.',
        'vehicle': vehicle.to_dict()
    })


@vehicle_bp.route('/vignette-vehicles-without', methods=['GET'])
@login_required
@roles_required('agent_impot')
def get_vignette_vehicles_without():
    """Get vehicles without vignette for tax agents"""
    user_country = getattr(current_user, 'country', None)

    # Include vehicles that either have no vignette expiry OR are missing required fields
    query = Vehicle.query.filter(
        Vehicle.qr_pending_approval == False
    ).filter(or_(
        Vehicle.vignette_expiry.is_(None),
        Vehicle.fuel_type.is_(None), Vehicle.fuel_type == '',
        Vehicle.fiscal_class.is_(None), Vehicle.fiscal_class == '',
        Vehicle.cv_class.is_(None), Vehicle.cv_class == '',
        Vehicle.vin.is_(None), Vehicle.vin == ''
    ))

    if user_country:
        query = query.filter(Vehicle.owner_island == user_country)

    vehicles = query.order_by(Vehicle.license_plate).all()
    vehicles_payload = []
    
    for vehicle in vehicles:
        vehicle_data = vehicle.to_dict()
        payment_request_pending = bool(get_pending_vignette_request_expiry(vehicle) and not getattr(vehicle, 'vignette_payment_approved', False))
        vehicle_data['vignette_payment_request_pending'] = payment_request_pending
        pending_expiry = get_pending_vignette_request_expiry(vehicle)
        vehicle_data['vignette_payment_requested_expiry'] = pending_expiry.isoformat() if pending_expiry else None
        vehicle_data['vignette_status'] = 'pending' if payment_request_pending and not vehicle.vignette_expiry else 'no_vignette'
        
        # Calculate vignette price based on vehicle attributes
        vignette_price = calculate_vignette_price(vehicle)
        vehicle_data['vignette_price'] = vignette_price
        
        # Add unpaid fines amount
        unpaid_fines = Fine.query.filter_by(vehicle_id=vehicle.id, paid=False).all()
        total_fines_amount = sum(float(f.amount) if f.amount else 0 for f in unpaid_fines)
        vehicle_data['unpaid_fines_amount'] = total_fines_amount
        vehicle_data['unpaid_fines_count'] = len(unpaid_fines)
        
        vehicles_payload.append(vehicle_data)

    return jsonify({
        "vehicles": vehicles_payload,
        "total": len(vehicles_payload)
    })


@vehicle_bp.route('/vignette-finance-stats', methods=['GET'])
@login_required
@roles_required('agent_impot', 'administrateur')
def get_vignette_finance_stats():
    """Get finance statistics for vignettes"""
    # Get date range from query parameters
    start_date_str = request.args.get('start_date', '')
    end_date_str = request.args.get('end_date', '')
    
    now = now_comoros()
    
    # Default to last 30 days if no dates provided
    if not start_date_str:
        start_date = now - timedelta(days=30)
    else:
        try:
            start_date = datetime.fromisoformat(start_date_str)
        except:
            start_date = now - timedelta(days=30)
    start_date = ensure_comoros(start_date)
    
    if not end_date_str:
        end_date = now
    else:
        try:
            end_date = datetime.fromisoformat(end_date_str)
        except:
            end_date = now

    # Adjust end_date to include the entire day and ensure timezone
    end_date = end_date.replace(hour=23, minute=59, second=59)
    end_date = ensure_comoros(end_date)
    
    # Get user country filter
    user_country = getattr(current_user, 'country', None)
    
    # Count total active vignettes
    query_active = Vehicle.query.filter(Vehicle.vignette_expiry.isnot(None))
    if user_country:
        query_active = query_active.filter(Vehicle.owner_island == user_country)
    total_active_vignettes = query_active.count()
    
    # Count paid/renewed vignettes in selected period.
    # Prefer explicit vignette payment timestamp when available.
    query_renewed = Vehicle.query.filter(
        Vehicle.vignette_expiry.isnot(None),
        Vehicle.vignette_last_paid_at.isnot(None),
        Vehicle.vignette_last_paid_at >= start_date,
        Vehicle.vignette_last_paid_at <= end_date
    )
    if user_country:
        query_renewed = query_renewed.filter(Vehicle.owner_island == user_country)
    renewed_count = query_renewed.count()
    
    # Get all vehicles with vignettes to calculate revenue breakdown
    query_vehicles = Vehicle.query.filter(Vehicle.vignette_expiry.isnot(None))
    if user_country:
        query_vehicles = query_vehicles.filter(Vehicle.owner_island == user_country)
    vehicles = query_vehicles.all()
    
    # Calculate total penalties in date range
    total_penalties = 0.0
    total_vignette_revenue = 0.0
    total_fines = 0.0
    
    for vehicle in vehicles:
        paid_at = getattr(vehicle, 'vignette_last_paid_at', None)
        if paid_at:
            try:
                paid_at = ensure_comoros(paid_at)
            except Exception:
                pass
        paid_in_range = bool(paid_at and start_date <= paid_at <= end_date)

        # Fallback for legacy rows that don't have last_paid fields populated yet
        if not paid_in_range and not paid_at and vehicle.updated_at:
            try:
                updated_at = ensure_comoros(vehicle.updated_at)
            except Exception:
                updated_at = vehicle.updated_at
            paid_in_range = start_date <= updated_at <= end_date

        if not paid_in_range:
            continue

        stored_vignette = float(getattr(vehicle, 'vignette_last_paid_vignette_amount', 0.0) or 0.0)
        stored_penalty = float(getattr(vehicle, 'vignette_last_paid_penalty_amount', 0.0) or 0.0)
        stored_fines = float(getattr(vehicle, 'vignette_last_paid_fines_amount', 0.0) or 0.0)

        if stored_vignette == 0.0 and stored_penalty == 0.0 and stored_fines == 0.0:
            # Legacy fallback calculation
            stored_vignette = float(calculate_vignette_price(vehicle) or 0.0)
            if vehicle.vignette_expiry:
                try:
                    expiry = ensure_comoros(vehicle.vignette_expiry)
                except Exception:
                    expiry = vehicle.vignette_expiry
                if expiry < now:
                    days_late = (now - expiry).days
                    stored_penalty = float(calculate_penalty_amount(days_late) or 0.0)
                else:
                    stored_penalty = 0.0
            else:
                stored_penalty = 0.0

        total_vignette_revenue += stored_vignette
        total_penalties += stored_penalty
        total_fines += stored_fines
    
    # Calculate total revenue
    total_revenue = total_vignette_revenue + total_penalties + total_fines
    
    return jsonify({
        'total_active_vignettes': total_active_vignettes,
        'renewed_vignettes': renewed_count,
        'total_penalties': round(total_penalties, 2),
        'total_vignette_revenue': round(total_vignette_revenue, 2),
        'total_fines': round(total_fines, 2),
        'total_revenue': round(total_revenue, 2),
        'date_range': {
            'start': start_date.isoformat(),
            'end': end_date.isoformat()
        }
    })


@vehicle_bp.route('/vignette-finance-vehicles', methods=['GET'])
@login_required
@roles_required('agent_impot', 'administrateur')
def get_vignette_finance_vehicles():
    """Get vehicles with finance details filtered by date range"""
    # Get date range from query parameters
    start_date_str = request.args.get('start_date', '')
    end_date_str = request.args.get('end_date', '')
    
    now = now_comoros()
    
    # Default to last 30 days if no dates provided
    if not start_date_str:
        start_date = now - timedelta(days=30)
    else:
        try:
            start_date = datetime.fromisoformat(start_date_str)
        except:
            start_date = now - timedelta(days=30)
    start_date = ensure_comoros(start_date)
    
    if not end_date_str:
        end_date = now
    else:
        try:
            end_date = datetime.fromisoformat(end_date_str)
        except:
            end_date = now

    # Adjust end_date to include the entire day and ensure timezone
    end_date = end_date.replace(hour=23, minute=59, second=59)
    end_date = ensure_comoros(end_date)
    
    # Get user country filter
    user_country = getattr(current_user, 'country', None)
    
    # Get all vehicles with vignettes
    query = Vehicle.query.filter(Vehicle.vignette_expiry.isnot(None))
    if user_country:
        query = query.filter(Vehicle.owner_island == user_country)
    
    vehicles = query.all()
    
    vehicles_data = []
    
    for vehicle in vehicles:
        paid_at = getattr(vehicle, 'vignette_last_paid_at', None)
        if paid_at:
            try:
                paid_at = ensure_comoros(paid_at)
            except Exception:
                pass
        paid_in_range = bool(paid_at and start_date <= paid_at <= end_date)

        # Fallback for legacy rows
        if not paid_in_range and not paid_at and vehicle.updated_at:
            try:
                updated_at = ensure_comoros(vehicle.updated_at)
            except Exception:
                updated_at = vehicle.updated_at
            paid_in_range = start_date <= updated_at <= end_date

        if not paid_in_range:
            continue

        vignette_price = float(getattr(vehicle, 'vignette_last_paid_vignette_amount', 0.0) or 0.0)
        penalty_amount = float(getattr(vehicle, 'vignette_last_paid_penalty_amount', 0.0) or 0.0)
        fines_amount = float(getattr(vehicle, 'vignette_last_paid_fines_amount', 0.0) or 0.0)

        if vignette_price == 0.0 and penalty_amount == 0.0 and fines_amount == 0.0:
            vignette_price = float(calculate_vignette_price(vehicle) or 0.0)
            if vehicle.vignette_expiry:
                try:
                    expiry = ensure_comoros(vehicle.vignette_expiry)
                except Exception:
                    expiry = vehicle.vignette_expiry
                if expiry < now:
                    days_late = (now - expiry).days
                    penalty_amount = float(calculate_penalty_amount(days_late) or 0.0)

        payment_date_dt = paid_at or vehicle.updated_at
        try:
            if payment_date_dt:
                payment_date_dt = ensure_comoros(payment_date_dt)
                payment_date = payment_date_dt.strftime('%Y-%m-%d')
            else:
                payment_date = '-'
        except Exception:
            payment_date = payment_date_dt.strftime('%Y-%m-%d') if payment_date_dt else '-'

        total = vignette_price + penalty_amount + fines_amount

        vehicles_data.append({
            'license_plate': vehicle.license_plate,
            'payment_date': payment_date,
            'vignette_price': round(vignette_price, 2),
            'penalty_amount': round(penalty_amount, 2),
            'fines_amount': round(fines_amount, 2),
            'total': round(total, 2),
            'updated_at': payment_date_dt.strftime('%Y-%m-%d %H:%M:%S') if payment_date_dt else None
        })
    
    return jsonify(vehicles_data)


@vehicle_bp.route('/vignette-daily-report', methods=['GET'])
@login_required
@roles_required('agent_impot', 'administrateur')
def get_vignette_daily_report():
    """Get daily report for vignettes with printable format"""
    # Get date from query parameter
    date_str = request.args.get('date', '')
    
    if not date_str:
        return jsonify({'error': 'Date parameter required'}), 400
    
    try:
        report_date = datetime.fromisoformat(date_str)
    except:
        return jsonify({'error': 'Invalid date format'}), 400

    # Set date range for the entire day and ensure Comoros timezone
    start_date = ensure_comoros(report_date.replace(hour=0, minute=0, second=0))
    end_date = ensure_comoros(report_date.replace(hour=23, minute=59, second=59))
    
    # Get user country filter
    user_country = getattr(current_user, 'country', None)
    
    # Get all vehicles with vignettes
    query = Vehicle.query.filter(Vehicle.vignette_expiry.isnot(None))
    if user_country:
        query = query.filter(Vehicle.owner_island == user_country)
    
    vehicles = query.all()
    
    vehicles_data = []
    total_paid = 0
    total_revenue = 0.0
    total_penalties = 0.0
    total_fines = 0.0
    
    now = now_comoros()
    
    for vehicle in vehicles:
        paid_at = getattr(vehicle, 'vignette_last_paid_at', None)
        if paid_at:
            try:
                paid_at = ensure_comoros(paid_at)
            except Exception:
                pass
        paid_in_range = bool(paid_at and start_date <= paid_at <= end_date)

        # Fallback for legacy rows
        if not paid_in_range and not paid_at and vehicle.updated_at:
            try:
                updated_at = ensure_comoros(vehicle.updated_at)
            except Exception:
                updated_at = vehicle.updated_at
            paid_in_range = start_date <= updated_at <= end_date

        if not paid_in_range:
            continue

        vignette_price = float(getattr(vehicle, 'vignette_last_paid_vignette_amount', 0.0) or 0.0)
        penalty_amount = float(getattr(vehicle, 'vignette_last_paid_penalty_amount', 0.0) or 0.0)
        fines_amount = float(getattr(vehicle, 'vignette_last_paid_fines_amount', 0.0) or 0.0)

        if vignette_price == 0.0 and penalty_amount == 0.0 and fines_amount == 0.0:
            vignette_price = float(calculate_vignette_price(vehicle) or 0.0)
            if vehicle.vignette_expiry:
                try:
                    expiry = ensure_comoros(vehicle.vignette_expiry)
                except Exception:
                    expiry = vehicle.vignette_expiry
                if expiry < now:
                    days_late = (now - expiry).days
                    penalty_amount = float(calculate_penalty_amount(days_late) or 0.0)

        payment_date_dt = paid_at or vehicle.updated_at
        try:
            if payment_date_dt:
                payment_date_dt = ensure_comoros(payment_date_dt)
                payment_date = payment_date_dt.strftime('%Y-%m-%d')
            else:
                payment_date = '-'
        except Exception:
            payment_date = payment_date_dt.strftime('%Y-%m-%d') if payment_date_dt else '-'

        total = vignette_price + penalty_amount + fines_amount

        vehicles_data.append({
            'license_plate': vehicle.license_plate,
            'payment_date': payment_date,
            'vignette_price': round(vignette_price, 2),
            'penalty_amount': round(penalty_amount, 2),
            'fines_amount': round(fines_amount, 2),
            'total': round(total, 2),
            'updated_at': payment_date_dt.strftime('%Y-%m-%d %H:%M:%S') if payment_date_dt else None
        })

        total_paid += 1
        total_revenue += vignette_price
        total_penalties += penalty_amount
        total_fines += fines_amount
    
    return jsonify({
        'date': date_str,
        'total_paid': total_paid,
        'total_revenue': round(total_revenue, 2),
        'total_penalties': round(total_penalties, 2),
        'total_fines': round(total_fines, 2),
        'vehicles': vehicles_data
    })


@vehicle_bp.route('/mobile-money-archive', methods=['GET'])
@login_required
@roles_required('mobile_money_agent')
def get_mobile_money_archive():
    """Return archived paid fines and paid vignettes for Mobile Money agents.

    Paid fines that were already included in a vignette payment are kept only in the
    vignette archive section, not in the direct fines archive.
    """
    start_date_str = request.args.get('start_date', '')
    end_date_str = request.args.get('end_date', '')
    show_all = request.args.get('all', '').lower() == 'true'

    now = datetime.utcnow()
    if show_all:
        start_date = None
        end_date = None
    else:
        if start_date_str:
            try:
                start_date = datetime.fromisoformat(start_date_str)
            except Exception:
                start_date = now - timedelta(days=30)
        else:
            start_date = now - timedelta(days=30)

        if end_date_str:
            try:
                end_date = datetime.fromisoformat(end_date_str)
            except Exception:
                end_date = now
        else:
            end_date = now

        end_date = end_date.replace(hour=23, minute=59, second=59)
    user_country = getattr(current_user, 'country', None)

    # Mobile Money agents should be able to see transactions across all islands
    # (do not apply the country filter for this role)
    if getattr(current_user, 'role', None) == 'mobile_money_agent':
        user_country = None

    # Show transactions made by mobile_money_agent accounts OR from the citizen app (Huri Money).
    # Exclude only payments made by other system roles (admin, policier, judiciaire, etc.).
    mobile_agent_usernames = [
        u.username for u in User.query.filter_by(role='mobile_money_agent').all()
    ]
    other_system_usernames = [
        u.username for u in User.query.filter(
            User.role.notin_(['mobile_money_agent'])
        ).all()
    ]

    # Direct paid fines: mobile agent OR citizen app (paid_by not a system user).
    fines_filters = [
        Fine.paid == True,
        Fine.paid_at.isnot(None),
    ]
    if start_date:
        fines_filters.append(Fine.paid_at >= start_date)
    if end_date:
        fines_filters.append(Fine.paid_at <= end_date)
    if other_system_usernames:
        fines_filters.append(db.or_(
            Fine.paid_by.in_(mobile_agent_usernames),
            Fine.paid_by.notin_(other_system_usernames),
        ))
    else:
        fines_filters.append(Fine.paid_by.isnot(None))
    fines_query = Fine.query.filter(*fines_filters)
    if user_country:
        fines_query = fines_query.join(Vehicle).filter(Vehicle.owner_island == user_country)

    direct_paid_fines = []
    direct_fines_total = 0.0
    for fine in fines_query.order_by(Fine.paid_at.desc()).all():
        if fine.receipt_number and str(fine.receipt_number).startswith('VIGN-'):
            continue
        raw_paid_by = fine.paid_by or '-'
        if raw_paid_by not in mobile_agent_usernames and not raw_paid_by.startswith('App Citoyen /'):
            paid_by_display = f'App Citoyen / {raw_paid_by}'
        else:
            paid_by_display = raw_paid_by
        direct_paid_fines.append({
            'id': fine.id,
            'license_plate': fine.vehicle.license_plate if fine.vehicle else '-',
            'owner_name': fine.vehicle.owner_name if fine.vehicle else '-',
            'amount': float(fine.amount or 0.0),
            'reason': fine.reason,
            'receipt_number': fine.receipt_number,
            'paid_at': fine.paid_at.isoformat() if fine.paid_at else None,
            'paid_by': paid_by_display,
        })
        direct_fines_total += float(fine.amount or 0.0)

    # Vignettes: mobile agent OR citizen app (vignette_last_paid_by not a system user).
    vignette_filters = [Vehicle.vignette_last_paid_at.isnot(None)]
    if start_date:
        vignette_filters.append(Vehicle.vignette_last_paid_at >= start_date)
    if end_date:
        vignette_filters.append(Vehicle.vignette_last_paid_at <= end_date)
    if other_system_usernames:
        vignette_filters.append(db.or_(
            Vehicle.vignette_last_paid_by.in_(mobile_agent_usernames),
            Vehicle.vignette_last_paid_by.notin_(other_system_usernames),
        ))
    else:
        vignette_filters.append(Vehicle.vignette_last_paid_by.isnot(None))
    vignette_query = Vehicle.query.filter(*vignette_filters)
    if user_country:
        vignette_query = vignette_query.filter(Vehicle.owner_island == user_country)

    vignette_archive = []
    vignette_total = 0.0
    vignette_penalties = 0.0
    vignette_included_fines = 0.0
    for vehicle in vignette_query.order_by(Vehicle.vignette_last_paid_at.desc()).all():
        vignette_price = float(getattr(vehicle, 'vignette_last_paid_vignette_amount', 0.0) or 0.0)
        penalty_amount = float(getattr(vehicle, 'vignette_last_paid_penalty_amount', 0.0) or 0.0)
        fines_amount = float(getattr(vehicle, 'vignette_last_paid_fines_amount', 0.0) or 0.0)
        total_amount = float(getattr(vehicle, 'vignette_last_paid_total_amount', 0.0) or (vignette_price + penalty_amount + fines_amount))

        vignette_archive.append({
            'vehicle_id': vehicle.id,
            'license_plate': vehicle.license_plate,
            'owner_name': vehicle.owner_name,
            'owner_island': vehicle.owner_island,
            'paid_at': vehicle.vignette_last_paid_at.isoformat() if vehicle.vignette_last_paid_at else None,
            'vignette_price': vignette_price,
            'penalty_amount': penalty_amount,
            'fines_amount': fines_amount,
            'total_amount': total_amount,
            'approved_by': (lambda raw: f'App Citoyen / {raw}' if raw and raw not in mobile_agent_usernames and not raw.startswith('App Citoyen /') else (raw or '-'))(vehicle.vignette_last_paid_by or vehicle.vignette_payment_approved_by),
            'payment_method': vehicle.vignette_payment_method,
            'receipt_number': f"VIGN-{vehicle.id}-{int(vehicle.vignette_last_paid_at.timestamp())}" if vehicle.vignette_last_paid_at else None,
            'included_fines': float(fines_amount),
        })
        vignette_total += vignette_price
        vignette_penalties += penalty_amount
        vignette_included_fines += fines_amount

    # QR code renewals archive — mobile agents OR citizen app (recorded_by not a system user)
    from app.models import QRCodePayment
    qr_filters = [
        QRCodePayment.payment_type == 'renewal',
        QRCodePayment.status == 'paid',
        QRCodePayment.paid_at.isnot(None),
    ]
    if start_date:
        qr_filters.append(QRCodePayment.paid_at >= start_date)
    if end_date:
        qr_filters.append(QRCodePayment.paid_at <= end_date)
    if other_system_usernames:
        qr_filters.append(db.or_(
            QRCodePayment.recorded_by.in_(mobile_agent_usernames),
            QRCodePayment.recorded_by.notin_(other_system_usernames),
        ))
    else:
        qr_filters.append(QRCodePayment.recorded_by.isnot(None))
    qr_query = QRCodePayment.query.filter(*qr_filters)
    if user_country:
        qr_query = qr_query.join(Vehicle, QRCodePayment.vehicle_id == Vehicle.id)\
                           .filter(Vehicle.owner_island == user_country)

    qr_archive = []
    qr_total = 0.0
    for p in qr_query.order_by(QRCodePayment.paid_at.desc()).all():
        v = p.vehicle
        raw = p.recorded_by or '-'
        # Format display: citizen payments may have old raw format (phone/name/HuriMoney)
        if raw.startswith('App Citoyen /'):
            recorded_by_display = raw
        elif raw in mobile_agent_usernames:
            recorded_by_display = raw
        else:
            # Old citizen record without prefix — add it
            recorded_by_display = f'App Citoyen / {raw}'
        qr_archive.append({
            'id': p.id,
            'license_plate': v.license_plate if v else '-',
            'owner_name': v.owner_name if v else '-',
            'owner_island': v.owner_island if v else '-',
            'amount': float(p.amount or 0.0),
            'paid_at': p.paid_at.isoformat() if p.paid_at else None,
            'recorded_by': recorded_by_display,
            'new_expiry': v.qr_code_expiry.strftime('%d/%m/%Y') if v and v.qr_code_expiry else '-',
        })
        qr_total += float(p.amount or 0.0)

    return jsonify({
        'start_date': start_date.isoformat() if start_date else None,
        'end_date': end_date.isoformat() if end_date else None,
        'totals': {
            'direct_fines_count': len(direct_paid_fines),
            'direct_fines_total': round(direct_fines_total, 2),
            'vignettes_count': len(vignette_archive),
            'vignette_total': round(vignette_total, 2),
            'vignette_penalties_total': round(vignette_penalties, 2),
            'vignette_included_fines_total': round(vignette_included_fines, 2),
            'qr_renewals_count': len(qr_archive),
            'qr_renewals_total': round(qr_total, 2),
            'overall_total': round(direct_fines_total + vignette_total + vignette_penalties + vignette_included_fines + qr_total, 2),
        },
        'direct_paid_fines': direct_paid_fines,
        'vignette_archive': vignette_archive,
        'qr_archive': qr_archive,
    })


@login_required
@roles_required('administrateur')
def init_vignettes():
    """Initialize vignette expiry dates for vehicles without them"""
    # List of license plates to initialize
    license_plates = ['106CA73', '361AA73', '097AC73', '514AC73', '516AC73', '929BA73']
    
    # Get all vehicles matching these plates
    vehicles = Vehicle.query.filter(Vehicle.license_plate.in_(license_plates)).all()
    
    updated = 0
    skipped = 0
    results = []
    
    # Set different expiry dates based on status (some expired, some active, some expiring)
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    
    # Mix of expired, expiring, and active dates
    expiry_dates = [
        now - timedelta(days=60),    # 106CA73 - expired 60 days ago
        now - timedelta(days=10),    # 361AA73 - expired 10 days ago
        now + timedelta(days=15),    # 097AC73 - expiring in 15 days
        now + timedelta(days=25),    # 514AC73 - expiring in 25 days
        now + timedelta(days=120),   # 516AC73 - active (4 months)
        now + timedelta(days=200),   # 929BA73 - active (6+ months)
    ]
    
    for i, vehicle in enumerate(vehicles):
        if vehicle.vignette_expiry is None:
            vehicle.vignette_expiry = expiry_dates[i]
            db.session.add(vehicle)
            updated += 1
            results.append({
                'license_plate': vehicle.license_plate,
                'vignette_expiry': vehicle.vignette_expiry.strftime('%Y-%m-%d'),
                'status': 'updated'
            })
        else:
            skipped += 1
            results.append({
                'license_plate': vehicle.license_plate,
                'vignette_expiry': vehicle.vignette_expiry.strftime('%Y-%m-%d'),
                'status': 'already_has_vignette'
            })
    
    # Save changes
    if updated > 0:
        db.session.commit()
    
    return jsonify({
        "updated": updated,
        "skipped": skipped,
        "total": len(vehicles),
        "results": results
    })


@vehicle_bp.route('/search-by-license-plate', methods=['GET'])
@login_required
def search_vehicle_by_license_plate():
    """Search for a vehicle by license plate"""
    license_plate = request.args.get('license_plate', '').strip()
    
    if not license_plate:
        return jsonify({"error": "license_plate required"}), 400
    
    vehicle = Vehicle.query.filter_by(license_plate=license_plate).first()
    
    if not vehicle:
        return jsonify({"error": "Vehicle not found"}), 404
    
    # For insurance accounts, only return if vehicle is from their island
    if isinstance(current_user, InsuranceAccount):
        if vehicle.owner_island != current_user.insurance.island:
            return jsonify({"error": "Vehicle is not from your insurance island"}), 403

    has_unpaid_fines = vehicle_has_unpaid_fines(vehicle.id)
    block_reason = get_vehicle_block_reason_for_insurance(vehicle)
    has_active_insurance = bool(block_reason and not has_unpaid_fines and vehicle.insurance_company)
    unpaid_fine = fine_to_block_payload(get_first_unpaid_fine(vehicle.id))
    
    return jsonify({
        "vehicle": vehicle.to_dict(),
        "has_active_insurance": has_active_insurance,
        "has_unpaid_fines": has_unpaid_fines,
        "can_add_to_insurance": block_reason is None,
        "active_insurance_company": vehicle.insurance_company if has_active_insurance else None,
        "block_reason": block_reason,
        "unpaid_fine": unpaid_fine,
        "message": block_reason or ""
    }), 200




@vehicle_bp.route('/reports/expired', methods=['GET'])
@login_required
def get_expired_insurance_report():
    """Get report of vehicles with expired insurance (insurance accounts only)"""
    if not isinstance(current_user, InsuranceAccount):
        return jsonify({"error": "Not an insurance account"}), 403
    
    from datetime import datetime
    now_dt = now_comoros()
    today = now_dt.date() if hasattr(now_dt, 'date') else now_dt.replace(tzinfo=None).date()
    
    # Get vehicles with expired insurance assigned to this account
    vehicles = Vehicle.query.filter(
        Vehicle.insurance_company == current_user.insurance.company_name,
        Vehicle.owner_island == current_user.insurance.island,
        Vehicle.insurance_expiry < today
    ).all()
    
    result = {
        "report_type": "Assurances Expirées",
        "generated_at": datetime.now().isoformat(),
        "insurance_company": current_user.insurance.company_name,
        "count": len(vehicles),
        "vehicles": [v.to_dict() for v in vehicles]
    }
    
    return jsonify(result), 200


@vehicle_bp.route('/reports/expiring-soon', methods=['GET'])
@login_required
def get_expiring_soon_report():
    """Get report of vehicles with insurance expiring in 30 days (insurance accounts only)"""
    if not isinstance(current_user, InsuranceAccount):
        return jsonify({"error": "Not an insurance account"}), 403
    
    from datetime import datetime, timedelta
    now_dt = now_comoros()
    today = now_dt.date() if hasattr(now_dt, 'date') else now_dt.replace(tzinfo=None).date()
    thirty_days = today + timedelta(days=30)
    
    # Get vehicles with insurance expiring in next 30 days
    vehicles = Vehicle.query.filter(
        Vehicle.insurance_company == current_user.insurance.company_name,
        Vehicle.owner_island == current_user.insurance.island,
        Vehicle.insurance_expiry >= today,
        Vehicle.insurance_expiry <= thirty_days
    ).order_by(Vehicle.insurance_expiry).all()
    
    result = {
        "report_type": "Assurances Expirant Bientôt (30 jours)",
        "generated_at": datetime.now().isoformat(),
        "insurance_company": current_user.insurance.company_name,
        "count": len(vehicles),
        "vehicles": [v.to_dict() for v in vehicles]
    }
    
    return jsonify(result), 200


@vehicle_bp.route('/reports/all-vehicles', methods=['GET'])
@login_required
def get_all_vehicles_report():
    """Get comprehensive report of all vehicles (insurance accounts only)"""
    if not isinstance(current_user, InsuranceAccount):
        return jsonify({"error": "Not an insurance account"}), 403
    
    # Get all vehicles assigned to this account
    vehicles = Vehicle.query.filter(
        Vehicle.insurance_company == current_user.insurance.company_name,
        Vehicle.owner_island == current_user.insurance.island
    ).order_by(Vehicle.license_plate).all()
    
    result = {
        "report_type": "Tous les Véhicules",
        "generated_at": datetime.now().isoformat(),
        "insurance_company": current_user.insurance.company_name,
        "count": len(vehicles),
        "vehicles": [v.to_dict() for v in vehicles]
    }
    
    return jsonify(result), 200


@vehicle_bp.route('/reports/activity', methods=['GET'])
@login_required
def get_activity_report():
    """Activity report by month: QR activations and renewals for insurance account vehicles."""
    if not isinstance(current_user, InsuranceAccount):
        return jsonify({"error": "Not an insurance account"}), 403

    import calendar as _cal
    from datetime import datetime
    from app.timezone_utils import COMOROS_TZ
    from app.models import QRCodePayment

    month_param = request.args.get('month')
    if not month_param:
        from app.timezone_utils import now_comoros
        month_param = now_comoros().strftime('%Y-%m')

    try:
        year, month = map(int, month_param.split('-'))
    except (ValueError, AttributeError):
        return jsonify({"error": "Invalid month format. Use YYYY-MM"}), 400

    last_day = _cal.monthrange(year, month)[1]
    start_dt = datetime(year, month, 1, 0, 0, 0, tzinfo=COMOROS_TZ)
    end_dt   = datetime(year, month, last_day, 23, 59, 59, tzinfo=COMOROS_TZ)

    # Vehicles belonging to this insurance account
    assignments = VehicleInsuranceAssignment.query.filter_by(
        insurance_account_id=current_user.id
    ).all()
    vehicle_ids = [a.vehicle_id for a in assignments]

    if not vehicle_ids:
        payments = []
    else:
        payments = QRCodePayment.query.filter(
            QRCodePayment.vehicle_id.in_(vehicle_ids),
            QRCodePayment.status == 'paid',
            QRCodePayment.paid_at >= start_dt,
            QRCodePayment.paid_at <= end_dt,
        ).order_by(QRCodePayment.paid_at.desc()).all()

    # Deduplicate: keep only the most recent payment per vehicle (payments already sorted desc)
    seen = set()
    vehicles_data = []
    for p in payments:
        if p.vehicle_id in seen or not p.vehicle:
            continue
        seen.add(p.vehicle_id)
        v = p.vehicle
        vehicles_data.append({
            'license_plate': v.license_plate,
            'owner_name':    v.owner_name or '—',
            'vehicle_type':  v.vehicle_type or '—',
            'owner_island':  v.owner_island or '—',
            'owner_phone':   v.owner_phone or '—',
            'usage_type':    v.usage_type or '—',
            'payment_type':  p.payment_type,
            'paid_at':       p.paid_at.strftime('%d/%m/%Y %H:%M') if p.paid_at else '—',
        })

    activation_count = sum(1 for v in vehicles_data if v['payment_type'] == 'activation')
    renewal_count    = sum(1 for v in vehicles_data if v['payment_type'] == 'renewal')

    from app.timezone_utils import now_comoros
    return jsonify({
        "report_type":       "Rapport d'Activité",
        "generated_at":      now_comoros().isoformat(),
        "insurance_company": current_user.insurance.company_name,
        "month":             month_param,
        "activation_count":  activation_count,
        "renewal_count":     renewal_count,
        "count":             len(vehicles_data),
        "vehicles":          vehicles_data,
    }), 200


@vehicle_bp.route('/reports/statistics', methods=['GET'])
@login_required
def get_statistics_report():
    """Get statistics report (insurance accounts only)"""
    if not isinstance(current_user, InsuranceAccount):
        return jsonify({"error": "Not an insurance account"}), 403
    
    from datetime import datetime, timedelta
    today = datetime.now().date()
    
    # Total vehicles
    total = Vehicle.query.filter(
        Vehicle.insurance_company == current_user.insurance.company_name,
        Vehicle.owner_island == current_user.insurance.island
    ).count()
    
    # Expired
    expired = Vehicle.query.filter(
        Vehicle.insurance_company == current_user.insurance.company_name,
        Vehicle.owner_island == current_user.insurance.island,
        Vehicle.insurance_expiry < today
    ).count()
    
    # Expiring in 30 days
    thirty_days = today + timedelta(days=30)
    expiring_soon = Vehicle.query.filter(
        Vehicle.insurance_company == current_user.insurance.company_name,
        Vehicle.owner_island == current_user.insurance.island,
        Vehicle.insurance_expiry >= today,
        Vehicle.insurance_expiry <= thirty_days
    ).count()
    
    # Active (not expired and not expiring soon)
    active = Vehicle.query.filter(
        Vehicle.insurance_company == current_user.insurance.company_name,
        Vehicle.owner_island == current_user.insurance.island,
        Vehicle.insurance_expiry > thirty_days
    ).count()
    
    # By vehicle type
    by_type = {}
    types = Vehicle.query.filter(
        Vehicle.insurance_company == current_user.insurance.company_name,
        Vehicle.owner_island == current_user.insurance.island
    ).with_entities(Vehicle.vehicle_type).distinct().all()
    
    for (vtype,) in types:
        count = Vehicle.query.filter(
            Vehicle.insurance_company == current_user.insurance.company_name,
            Vehicle.owner_island == current_user.insurance.island,
            Vehicle.vehicle_type == vtype
        ).count()
        by_type[vtype] = count
    
    result = {
        "report_type": "Statistiques",
        "generated_at": datetime.now().isoformat(),
        "insurance_company": current_user.insurance.company_name,
        "statistics": {
            "total_vehicles": total,
            "expired": expired,
            "expiring_soon": expiring_soon,
            "active": active,
            "by_type": by_type
        }
    }
    
    return jsonify(result), 200


@vehicle_bp.route('/uninsured', methods=['GET'])
@login_required
def get_uninsured_vehicles():
    """Get all vehicles without insurance or with expired insurance on the same island (insurance accounts only)"""
    if not isinstance(current_user, InsuranceAccount):
        return jsonify({"error": "Not an insurance account"}), 403
    
    # Get the island from the insurance company
    insurance_island = current_user.insurance.island
    now_dt = now_comoros()
    now_dt_naive = now_dt.replace(tzinfo=None) if getattr(now_dt, 'tzinfo', None) else now_dt
    
    # Get all vehicles with NO insurance company OR expired insurance on the same island
    uninsured = Vehicle.query.filter(
        Vehicle.qr_pending_approval == False,
        ((Vehicle.insurance_company == None) | (Vehicle.insurance_company == '') | (Vehicle.insurance_expiry < now_dt_naive)) &
        (Vehicle.owner_island == insurance_island)
    ).order_by(Vehicle.license_plate).all()
    
    uninsured_payload = []
    for vehicle in uninsured:
        vehicle_data = vehicle.to_dict()
        vehicle_data['has_unpaid_fines'] = vehicle_has_unpaid_fines(vehicle.id)
        vehicle_data['block_reason'] = get_vehicle_block_reason_for_insurance(vehicle)
        vehicle_data['unpaid_fine'] = fine_to_block_payload(get_first_unpaid_fine(vehicle.id))
        uninsured_payload.append(vehicle_data)

    return jsonify({
        "vehicles": uninsured_payload
    })


@vehicle_bp.route('/assign-to-insurance', methods=['POST'])
@login_required
def assign_vehicle_to_insurance():
    """Assign an uninsured vehicle to the current insurance account"""
    if not isinstance(current_user, InsuranceAccount):
        return jsonify({"error": "Not an insurance account"}), 403
    
    data = request.get_json()
    vehicle_id = data.get('vehicle_id')
    insurance_expiry = data.get('insurance_expiry')
    usage_type = (data.get('usage_type') or '').strip() or None
    driver_license_numbers = [n.strip().upper() for n in (data.get('driver_license_numbers') or []) if n and n.strip()]

    if not vehicle_id:
        return jsonify({"error": "vehicle_id required"}), 400
    if not driver_license_numbers:
        return jsonify({"error": "Au moins un numéro de permis conducteur est requis"}), 400
    
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    
    # Check if vehicle is on the same island as insurance company
    if vehicle.owner_island != current_user.insurance.island:
        return jsonify({"error": "Vehicle must be on the same island as your insurance company"}), 400

    try:
        qr_expired = vehicle.is_qr_code_expired()
    except Exception:
        qr_expired = False
    if vehicle.status == 'inactive' or qr_expired:
        return jsonify({"error": "Impossible d'ajouter ce véhicule: il est inactif ou son QR code est expiré."}), 400
    
    # Allow reassignment when existing insurance is expired.
    now_dt = now_comoros()
    now_dt_naive = now_dt.replace(tzinfo=None) if getattr(now_dt, 'tzinfo', None) else now_dt
    has_insurance_company = bool(vehicle.insurance_company and vehicle.insurance_company.strip())
    expiry_dt = vehicle.insurance_expiry
    expiry_dt_naive = expiry_dt.replace(tzinfo=None) if (expiry_dt and getattr(expiry_dt, 'tzinfo', None)) else expiry_dt
    insurance_is_expired = bool(expiry_dt_naive and expiry_dt_naive < now_dt_naive)
    if has_insurance_company and not insurance_is_expired:
        return jsonify({"error": "Vehicle already has an active insurance assigned"}), 400
    
    try:
        # Update vehicle with insurance company name
        vehicle.insurance_company = current_user.insurance.company_name

        # Update usage type if provided
        old_usage = vehicle.usage_type
        if usage_type:
            vehicle.usage_type = usage_type

        # Update insurance expiry if provided
        if insurance_expiry:
            try:
                from datetime import datetime
                vehicle.insurance_expiry = datetime.fromisoformat(insurance_expiry)
            except Exception:
                pass
        
        # Transfer ownership to the current insurance account.
        VehicleInsuranceAssignment.query.filter_by(vehicle_id=vehicle.id).delete()
        assignment = VehicleInsuranceAssignment(
            vehicle_id=vehicle.id,
            insurance_account_id=current_user.id,
            assigned_by=current_user.username,
            notes='Assigned by insurance account',
            driver_license_numbers=json.dumps(driver_license_numbers)
        )
        db.session.add(assignment)

        # Historique usage si modifié
        if usage_type and usage_type != old_usage:
            from app.models import VehicleHistory
            db.session.add(VehicleHistory(
                vehicle_id=vehicle.id,
                action='Usage modifié',
                officer=current_user.username,
                notes=f"Usage: {old_usage or '—'} → {usage_type}"
            ))

        db.session.commit()
        return jsonify({
            "success": True,
            "message": "Vehicle assigned successfully",
            "vehicle": vehicle.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@vehicle_bp.route('/<int:vehicle_id>/assignment-licenses', methods=['PATCH'])
@login_required
def update_assignment_licenses(vehicle_id):
    """Update driver license numbers on an insurance assignment (insurance accounts only)."""
    if not isinstance(current_user, InsuranceAccount):
        return jsonify({"error": "Not an insurance account"}), 403
    assignment = VehicleInsuranceAssignment.query.filter_by(
        vehicle_id=vehicle_id, insurance_account_id=current_user.id
    ).first_or_404()
    data = request.get_json() or {}
    nums = [n.strip().upper() for n in (data.get('driver_license_numbers') or []) if n and n.strip()]
    if not nums:
        return jsonify({"error": "Au moins un numéro de permis conducteur est requis"}), 400
    assignment.driver_license_numbers = json.dumps(nums)
    db.session.commit()
    return jsonify({"success": True, "driver_license_numbers": nums})


@vehicle_bp.route('/check-driver-license', methods=['GET'])
@login_required
def check_driver_license():
    """Check whether a driver license number exists. Used by insurance account forms."""
    if not isinstance(current_user, InsuranceAccount):
        return jsonify({"error": "Forbidden"}), 403
    num = (request.args.get('number') or '').strip().upper()
    if not num:
        return jsonify({"exists": False}), 200
    from app.models import DriverLicense
    lic = DriverLicense.query.filter_by(license_number=num).first()
    if lic:
        return jsonify({
            "exists": True,
            "holder": f"{lic.holder_firstname or ''} {lic.holder_name}".strip(),
            "status": lic.status,
            "is_expired": lic.is_expired
        })
    return jsonify({"exists": False})


@vehicle_bp.route('/driver-license-preview', methods=['GET'])
@login_required
def driver_license_preview():
    """Return license data for the Côté A preview modal (insurance accounts only)."""
    if not isinstance(current_user, InsuranceAccount):
        return jsonify({"error": "Forbidden"}), 403
    num = (request.args.get('number') or '').strip().upper()
    if not num:
        return jsonify({"error": "number required"}), 400
    # Security: number must be registered on one of this account's vehicles
    assignments = VehicleInsuranceAssignment.query.filter_by(insurance_account_id=current_user.id).all()
    allowed = set()
    for a in assignments:
        if a.driver_license_numbers:
            try:
                allowed.update(json.loads(a.driver_license_numbers))
            except Exception:
                pass
    if num not in allowed:
        return jsonify({"error": "Permis non autorisé"}), 403
    from app.models import DriverLicense, LicenseSetting
    from dateutil.relativedelta import relativedelta
    lic = DriverLicense.query.filter_by(license_number=num).first()
    if not lic:
        return jsonify({"error": "Permis introuvable"}), 404
    settings = LicenseSetting.get()
    computed_expiry = None
    if lic.type_permis == 'temporaire' and not lic.expiry_date and lic.issue_date:
        computed_expiry = lic.issue_date + relativedelta(months=(settings.temp_validity_months or 12))
    category_details = parse_category_details(lic)
    holder_cats = [c.strip() for c in lic.categories.split(',') if c.strip()] if lic.categories else []
    display_cats = [c for c in holder_cats if c != 'P']
    expiry = lic.expiry_date or computed_expiry
    return jsonify({
        "license_number":        lic.license_number,
        "holder_name":           lic.holder_name or '',
        "holder_firstname":      lic.holder_firstname or '',
        "holder_island":         lic.holder_island or '',
        "centre_immatriculation":lic.centre_immatriculation or '',
        "type_permis":           lic.type_permis or '',
        "issue_date":            lic.issue_date.strftime('%d/%m/%Y') if lic.issue_date else None,
        "expiry_date":           expiry.strftime('%d/%m/%Y') if expiry else None,
        "status":                lic.status,
        "is_expired":            lic.is_expired,
        "is_pro":                'P' in holder_cats,
        "categories":            display_cats,
        "category_details":      category_details,
        "photo_url":             _cloud_url(lic.photo_filename, 'license_photos'),
    })


# ==================== VEHICLE INSURANCE ASSIGNMENT ====================

@vehicle_bp.route('/assignments', methods=['GET'])
@login_required
def get_vehicle_assignments():
    """Get vehicle assignments
    - Administrateur: see all assignments
    - Insurance accounts: see only their assignments
    """
    if hasattr(current_user, 'role') and current_user.role == 'administrateur':
        assignments = VehicleInsuranceAssignment.query.order_by(VehicleInsuranceAssignment.assigned_at.desc()).all()
    elif isinstance(current_user, InsuranceAccount):
        assignments = VehicleInsuranceAssignment.query.filter_by(insurance_account_id=current_user.id).all()
    else:
        return jsonify({"error": "Forbidden"}), 403
    
    return jsonify({
        "assignments": [a.to_dict() for a in assignments]
    })


@vehicle_bp.route('/assignments', methods=['POST'])
@login_required
def create_vehicle_assignment():
    """Assign a vehicle to an insurance account (admin or the insurance account itself)"""
    is_admin = hasattr(current_user, 'role') and current_user.role == 'administrateur'
    is_insurance = isinstance(current_user, InsuranceAccount)
    if not is_admin and not is_insurance:
        return jsonify({"error": "Forbidden"}), 403

    data = request.get_json() or {}
    vehicle_id = data.get('vehicle_id')
    insurance_account_id = data.get('insurance_account_id')

    if not vehicle_id or not insurance_account_id:
        return jsonify({"error": "vehicle_id and insurance_account_id are required"}), 400

    # Insurance accounts can only create assignments for themselves
    if is_insurance and insurance_account_id != current_user.id:
        return jsonify({"error": "Forbidden"}), 403

    vehicle = Vehicle.query.get_or_404(vehicle_id)
    account = InsuranceAccount.query.get_or_404(insurance_account_id)

    driver_nums = [n.strip().upper() for n in (data.get('driver_license_numbers') or []) if n and n.strip()]
    if not driver_nums:
        return jsonify({"error": "Au moins un numéro de permis conducteur est requis"}), 400

    # Update existing assignment if one already exists
    existing = VehicleInsuranceAssignment.query.filter_by(
        vehicle_id=vehicle_id,
        insurance_account_id=insurance_account_id
    ).first()
    if existing:
        existing.driver_license_numbers = json.dumps(driver_nums)
        existing.notes = data.get('notes', existing.notes or '')
        db.session.commit()
        return jsonify(existing.to_dict()), 200

    assignment = VehicleInsuranceAssignment(
        vehicle_id=vehicle_id,
        insurance_account_id=insurance_account_id,
        assigned_by=current_user.username,
        notes=data.get('notes', ''),
        driver_license_numbers=json.dumps(driver_nums)
    )
    db.session.add(assignment)
    db.session.commit()
    return jsonify(assignment.to_dict()), 201


@vehicle_bp.route('/assignments/<int:assignment_id>', methods=['DELETE'])
@login_required
def delete_vehicle_assignment(assignment_id):
    """Delete a vehicle assignment (admin only)"""
    if not hasattr(current_user, 'role') or current_user.role != 'administrateur':
        return jsonify({"error": "Forbidden"}), 403
    
    assignment = VehicleInsuranceAssignment.query.get_or_404(assignment_id)
    db.session.delete(assignment)
    db.session.commit()
    
    return jsonify({"message": "Assignment deleted successfully"})


# ============= VIGNETTE SETTINGS ROUTES =============

@main_bp.route('/vignette-settings')
@login_required
@roles_required('agent_impot', 'administrateur')
def vignette_settings():
    """Page for managing vignette rates and penalties (tax agents only)"""
    return render_template('vignette_settings.html')


@main_bp.route('/vignette-finance')
@login_required
@roles_required('agent_impot', 'administrateur')
def vignette_finance():
    """Finance page showing vignette statistics"""
    return render_template('vignette_finance.html')


@main_bp.route('/vignette-daily-report')
@login_required
@roles_required('agent_impot', 'administrateur')
def vignette_daily_report():
    """Daily report page for printable vignette report"""
    return render_template('vignette_daily_report.html')


@main_bp.route('/vignette-daily-report-print')
@login_required
@roles_required('agent_impot', 'administrateur')
def vignette_daily_report_print():
    """Clean print version of daily report without base.html"""
    return render_template('vignette_daily_report_print.html')


@vehicle_bp.route('/vehicle-options', methods=['GET'])
@login_required
@roles_required('agent_impot', 'administrateur')
def get_vehicle_options():
    """Get available vehicle types, usage types, and fuel types"""
    # Get unique values from vehicles table
    vehicle_types = db.session.query(Vehicle.vehicle_type).distinct().filter(
        Vehicle.vehicle_type.isnot(None)
    ).order_by(Vehicle.vehicle_type).all()
    
    usage_types = db.session.query(Vehicle.usage_type).distinct().filter(
        Vehicle.usage_type.isnot(None)
    ).order_by(Vehicle.usage_type).all()
    
    fuel_types = db.session.query(Vehicle.fuel_type).distinct().filter(
        Vehicle.fuel_type.isnot(None)
    ).order_by(Vehicle.fuel_type).all()
    
    return jsonify({
        'vehicle_types': [v[0] for v in vehicle_types],
        'usage_types': [u[0] for u in usage_types],
        'fuel_types': [f[0] for f in fuel_types]
    })


@vehicle_bp.route('/vignette-rates', methods=['GET'])
@login_required
@roles_required('agent_impot', 'administrateur')
def get_vignette_rates():
    """Get all vignette rates"""
    from app.models import VignetteRate
    rates = VignetteRate.query.filter_by(is_active=True).all()
    return jsonify({
        'rates': [r.to_dict() for r in rates],
        'total': len(rates)
    })


@vehicle_bp.route('/vignette-rates', methods=['POST'])
@login_required
@roles_required('agent_impot', 'administrateur')
def create_vignette_rate():
    """Create a new vignette rate"""
    from app.models import VignetteRate
    data = request.get_json() or {}
    
    rate = VignetteRate(
        fiscal_class=data.get('fiscal_class'),
        cv_class=data.get('cv_class'),
        fuel_type=data.get('fuel_type'),
        vehicle_age_min=data.get('vehicle_age_min', 0),
        vehicle_age_max=data.get('vehicle_age_max'),
        price_kmf=data.get('price_kmf'),
        annual_ds=data.get('annual_ds', 1000),
        description=data.get('description'),
        is_active=True
    )
    db.session.add(rate)
    db.session.commit()
    
    return jsonify(rate.to_dict()), 201


@vehicle_bp.route('/vignette-rates/<int:rate_id>', methods=['PUT'])
@login_required
@roles_required('agent_impot', 'administrateur')
def update_vignette_rate(rate_id):
    """Update a vignette rate"""
    from app.models import VignetteRate
    rate = VignetteRate.query.get_or_404(rate_id)
    data = request.get_json() or {}
    
    if 'fiscal_class' in data:
        rate.fiscal_class = data.get('fiscal_class')
    if 'cv_class' in data:
        rate.cv_class = data.get('cv_class')
    if 'fuel_type' in data:
        rate.fuel_type = data.get('fuel_type')
    if 'vehicle_age_min' in data:
        rate.vehicle_age_min = data.get('vehicle_age_min')
    if 'vehicle_age_max' in data:
        rate.vehicle_age_max = data.get('vehicle_age_max')
    if 'price_kmf' in data:
        rate.price_kmf = data.get('price_kmf')
    if 'annual_ds' in data:
        rate.annual_ds = data.get('annual_ds')
    if 'description' in data:
        rate.description = data.get('description')
    if 'is_active' in data:
        rate.is_active = data.get('is_active')
    
    db.session.commit()
    return jsonify(rate.to_dict())


@vehicle_bp.route('/vignette-rates/<int:rate_id>', methods=['DELETE'])
@login_required
@roles_required('agent_impot', 'administrateur')
def delete_vignette_rate(rate_id):
    """Delete (deactivate) a vignette rate"""
    from app.models import VignetteRate
    rate = VignetteRate.query.get_or_404(rate_id)
    rate.is_active = False
    db.session.commit()
    
    return jsonify({"message": "Rate deleted successfully"})


# Penalty Rates

@vehicle_bp.route('/penalty-rates', methods=['GET'])
@login_required
@roles_required('agent_impot', 'administrateur')
def get_penalty_rates():
    """Get all penalty rates"""
    from app.models import PenaltyRate
    rates = PenaltyRate.query.filter_by(is_active=True).order_by(PenaltyRate.days_late_min).all()
    return jsonify({
        'rates': [r.to_dict() for r in rates],
        'total': len(rates)
    })


@vehicle_bp.route('/penalty-rates', methods=['POST'])
@login_required
@roles_required('agent_impot', 'administrateur')
def create_penalty_rate():
    """Create a new penalty rate"""
    from app.models import PenaltyRate
    data = request.get_json() or {}
    
    rate = PenaltyRate(
        days_late_min=data.get('days_late_min'),
        days_late_max=data.get('days_late_max'),
        penalty_per_day=data.get('penalty_per_day'),
        description=data.get('description'),
        is_active=True
    )
    db.session.add(rate)
    db.session.commit()
    
    return jsonify(rate.to_dict()), 201


@vehicle_bp.route('/penalty-rates/<int:rate_id>', methods=['PUT'])
@login_required
@roles_required('agent_impot', 'administrateur')
def update_penalty_rate(rate_id):
    """Update a penalty rate"""
    from app.models import PenaltyRate
    rate = PenaltyRate.query.get_or_404(rate_id)
    data = request.get_json() or {}
    
    if 'days_late_min' in data:
        rate.days_late_min = data.get('days_late_min')
    if 'days_late_max' in data:
        rate.days_late_max = data.get('days_late_max')
    if 'penalty_per_day' in data:
        rate.penalty_per_day = data.get('penalty_per_day')
    if 'description' in data:
        rate.description = data.get('description')
    if 'is_active' in data:
        rate.is_active = data.get('is_active')
    
    db.session.commit()
    return jsonify(rate.to_dict())


@vehicle_bp.route('/penalty-rates/<int:rate_id>', methods=['DELETE'])
@login_required
@roles_required('agent_impot', 'administrateur')
def delete_penalty_rate(rate_id):
    """Delete (deactivate) a penalty rate"""
    from app.models import PenaltyRate
    rate = PenaltyRate.query.get_or_404(rate_id)
    rate.is_active = False
    db.session.commit()
    
    return jsonify({"message": "Penalty rate deleted successfully"})


@vehicle_bp.route('/vignette-settings', methods=['GET'])
@login_required
@roles_required('agent_impot', 'administrateur')
def get_vignette_settings():
    """Get global vignette settings."""
    from app.models import VignetteSetting
    setting = VignetteSetting.get()
    return jsonify(setting.to_dict())


@vehicle_bp.route('/vignette-settings', methods=['PUT'])
@login_required
@roles_required('agent_impot', 'administrateur')
def update_vignette_settings():
    """Update global vignette settings."""
    from app.models import VignetteSetting
    from datetime import date
    data = request.get_json() or {}
    setting = VignetteSetting.get()

    raw_date = data.get('renewal_opening_date')
    if raw_date:
        try:
            setting.renewal_opening_date = date.fromisoformat(raw_date)
        except ValueError:
            return jsonify({'error': 'Format de date invalide. Utilisez YYYY-MM-DD.'}), 400
    else:
        setting.renewal_opening_date = None

    setting.updated_by = current_user.username if current_user.is_authenticated else None
    db.session.commit()
    return jsonify({'message': 'Paramètres mis à jour.', **setting.to_dict()})


# ============= HURI MONEY DESTINATION SETTINGS =============

@main_bp.route('/payment-settings')
@login_required
@roles_required('administrateur')
def payment_settings():
    """Page for configuring which Huri Money account receives each payment type's revenue."""
    return render_template('payment_settings.html')


@vehicle_bp.route('/payment-settings', methods=['GET'])
@login_required
@roles_required('administrateur')
def get_payment_settings():
    from app.models import HuriDestinationSetting
    setting = HuriDestinationSetting.get()
    return jsonify(setting.to_dict())


_PAYMENT_PHONE_FIELD_LABELS = {'fine_phone': 'Amendes', 'vignette_phone': 'Vignette'}


@vehicle_bp.route('/payment-settings', methods=['PUT'])
@login_required
@roles_required('administrateur')
def update_payment_settings():
    """Request a change to a destination phone number. The change is NOT applied here —
    a confirmation code is emailed to a fixed, server-side-only address
    (PAYMENT_CHANGE_APPROVAL_EMAIL env var, not editable via the web app), and must be
    confirmed via /payment-settings/confirm before it takes effect. This keeps the
    approval channel outside the in-app account system, so a single compromised or
    malicious admin account cannot redirect payment revenue on its own."""
    from app.models import HuriDestinationSetting, PendingPhoneChange
    from app.email_service import send_approval_email
    import random

    data = request.get_json() or {}
    setting = HuriDestinationSetting.get()
    username = current_user.username if current_user.is_authenticated else None

    if 'fine_phone' in data:
        field = 'fine_phone'
        new_value = (data.get('fine_phone') or '').strip() or None
        current_value = setting.fine_phone
    elif 'vignette_phone' in data:
        field = 'vignette_phone'
        new_value = (data.get('vignette_phone') or '').strip() or None
        current_value = setting.vignette_phone
    else:
        return jsonify({'error': 'Aucun champ à modifier.'}), 400

    if new_value == current_value:
        return jsonify({'message': 'Aucun changement.', **setting.to_dict()})

    code = f"{random.randint(0, 999999):06d}"
    pending = PendingPhoneChange(
        field=field,
        old_value=current_value,
        new_value=new_value,
        requested_by=username,
        expires_at=now_comoros() + timedelta(minutes=15),
    )
    pending.set_code(code)

    label = _PAYMENT_PHONE_FIELD_LABELS[field]
    subject = f"Confirmation requise : changement numéro {label}"
    body = (
        f"{username or 'Un administrateur'} demande de changer le numéro Huri Money « {label} » :\n\n"
        f"  Ancien numéro : {current_value or '—'}\n"
        f"  Nouveau numéro : {new_value or '—'}\n\n"
        f"Code de confirmation : {code}\n\n"
        f"Ce code expire dans 15 minutes. Si vous n'êtes pas à l'origine de cette demande, "
        f"ne communiquez pas ce code et vérifiez le compte administrateur concerné."
    )
    email_result = send_approval_email(subject, body)
    if not email_result.get('success'):
        return jsonify({'error': f"Impossible d'envoyer le code de confirmation : {email_result.get('message')}"}), 503

    db.session.add(pending)
    db.session.commit()

    return jsonify({
        'pending': True,
        'change_id': pending.id,
        'message': 'Un code de confirmation a été envoyé. Saisissez-le pour valider le changement.',
    })


@vehicle_bp.route('/payment-settings/confirm', methods=['POST'])
@login_required
@roles_required('administrateur')
def confirm_payment_settings_change():
    """Apply a pending phone number change once the emailed confirmation code is verified."""
    from app.models import HuriDestinationSetting, HuriDestinationPhoneHistory, PendingPhoneChange

    data = request.get_json() or {}
    try:
        change_id = int(data.get('change_id'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Demande de changement invalide.'}), 400
    code = str(data.get('code') or '').strip()

    pending = PendingPhoneChange.query.get(change_id)
    if not pending or pending.consumed:
        return jsonify({'error': 'Demande de changement introuvable ou déjà traitée.'}), 404

    if pending.is_expired:
        return jsonify({'error': 'Ce code a expiré. Veuillez recommencer.'}), 400

    if pending.attempts >= PendingPhoneChange.MAX_ATTEMPTS:
        return jsonify({'error': 'Trop de tentatives. Veuillez recommencer.'}), 400

    if not code or not pending.check_code(code):
        pending.attempts += 1
        db.session.commit()
        remaining = max(PendingPhoneChange.MAX_ATTEMPTS - pending.attempts, 0)
        return jsonify({'error': f'Code incorrect. {remaining} tentative(s) restante(s).'}), 400

    setting = HuriDestinationSetting.get()
    db.session.add(HuriDestinationPhoneHistory(
        field=pending.field, old_value=pending.old_value, new_value=pending.new_value, changed_by=pending.requested_by
    ))
    setattr(setting, pending.field, pending.new_value)
    setattr(setting, f'{pending.field}_updated_at', now_comoros())
    setattr(setting, f'{pending.field}_updated_by', pending.requested_by)

    pending.consumed = True
    db.session.commit()

    return jsonify({'message': 'Changement confirmé et appliqué.', **setting.to_dict()})


@vehicle_bp.route('/payment-settings/history', methods=['GET'])
@login_required
@roles_required('administrateur')
def get_payment_settings_history():
    from app.models import HuriDestinationPhoneHistory
    field = request.args.get('field', '').strip()
    if field not in ('fine_phone', 'vignette_phone', 'qr_renewal_phone'):
        return jsonify({'error': 'Champ invalide'}), 400
    entries = (HuriDestinationPhoneHistory.query
               .filter_by(field=field)
               .order_by(HuriDestinationPhoneHistory.changed_at.desc())
               .all())
    return jsonify([e.to_dict() for e in entries])


# Vehicle Transfers - Citizen API

@main_bp.route('/api/vehicle-transfers', methods=['POST'])
@jwt_required()
def submit_vehicle_transfer():
    """Submit a vehicle transfer request (citizen endpoint)"""
    from app.models import VehicleTransfer
    import os
    from werkzeug.utils import secure_filename
    
    try:
        # Get vehicle ID from JWT (identity is stored as str(vehicle.id))
        vehicle_id = get_jwt_identity()
        if not vehicle_id:
            return jsonify({'error': 'Invalid token: missing vehicle_id'}), 401
        try:
            vehicle_id = int(vehicle_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid token: vehicle_id must be an integer'}), 401

        # Verify vehicle exists
        vehicle = Vehicle.query.get(vehicle_id)
        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404
        
        # Get form data
        transfer_type = (request.form.get('transfer_type') or '').strip()
        new_owner_phone = (request.form.get('new_owner_phone') or '').strip()
        new_owner_name = (request.form.get('new_owner_name') or '').strip()
        transfer_reason = (request.form.get('transfer_reason') or '').strip()
        
        # Validate required fields
        if not transfer_type or not new_owner_phone or not new_owner_name:
            return jsonify({'error': 'Missing required fields: transfer_type, new_owner_phone, new_owner_name'}), 400
        
        # Validate transfer_type
        if transfer_type not in ['sale', 'gift', 'inheritance', 'other']:
            return jsonify({'error': 'Invalid transfer_type'}), 400
        
        # Validate required reason for 'other' type
        if transfer_type == 'other' and not transfer_reason:
            return jsonify({'error': 'Reason required for transfer type "other"'}), 400
        
        # Check for existing pending transfer
        existing_transfer = VehicleTransfer.query.filter_by(
            vehicle_id=vehicle_id,
            status='pending'
        ).first()

        if existing_transfer:
            return jsonify({'error': 'A transfer request is already pending for this vehicle'}), 409

        # Handle optional identity document
        identity_document_path = None
        if 'identity_document' in request.files:
            file = request.files['identity_document']
            if file and file.filename:
                allowed_extensions = {'pdf', 'jpg', 'jpeg', 'png', 'gif'}
                if not ('.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in allowed_extensions):
                    return jsonify({'error': 'Invalid file type. Allowed: PDF, JPG, PNG, GIF'}), 400

                from app.cloudinary_utils import is_cloudinary_enabled, upload_file as cloud_upload
                if is_cloudinary_enabled():
                    identity_document_path = cloud_upload(file, 'vehicle_transfers')
                else:
                    upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'vehicle_transfers')
                    os.makedirs(upload_dir, exist_ok=True)
                    filename = secure_filename(f"{vehicle_id}_{datetime.now().timestamp()}_{file.filename}")
                    file.save(os.path.join(upload_dir, filename))
                    identity_document_path = os.path.join('vehicle_transfers', filename)

        # Create transfer record
        transfer = VehicleTransfer(
            vehicle_id=vehicle_id,
            current_owner_phone=vehicle.owner_phone or '',
            new_owner_phone=new_owner_phone,
            new_owner_name=new_owner_name,
            transfer_type=transfer_type,
            reason=transfer_reason or None,
            identity_document_path=identity_document_path,
            status='pending',
            created_at=now_comoros()
        )

        db.session.add(transfer)
        db.session.commit()

        return jsonify({
            'message': 'Transfer request submitted successfully',
            'transfer': transfer.to_dict()
        }), 201
        
    except Exception as e:
        print(f'Error submitting transfer: {str(e)}')
        return jsonify({'error': f'Server error: {str(e)}'}), 500


# Route removed — handled by api_bp in api.py (supports both session and JWT auth)


# ─────────────────────────────────────────────────────────────
#  DGRTR — Gestion des comptes
# ─────────────────────────────────────────────────────────────

def _is_dgrtr_director():
    """True if the current user is admin OR dgrtr directeur_general."""
    if current_user.role == 'administrateur':
        return True
    if current_user.role == 'dgrtr' and getattr(current_user, 'dgrtr_type', None) == 'directeur_general':
        return True
    return False


@main_bp.route('/dgrtr/comptes')
@roles_required('administrateur', 'dgrtr')
def dgrtr_comptes():
    if not _is_dgrtr_director():
        abort(403)
    return render_template('dgrtr_comptes.html')


@main_bp.route('/api/dgrtr-users')
@roles_required('administrateur', 'dgrtr')
def api_dgrtr_users():
    if not _is_dgrtr_director():
        return jsonify({'error': 'Accès refusé'}), 403
    users = User.query.filter(
        User.role.in_(['dgrtr', 'judiciaire'])
    ).order_by(User.created_at.desc()).all()
    out = []
    for u in users:
        out.append({
            'id': u.id,
            'username': u.username,
            'full_name': u.full_name or '',
            'role': u.role,
            'dgrtr_type': u.dgrtr_type or 'employe',
            'country': u.country or '',
            'is_active': bool(u.is_active),
            'created_at': u.created_at.strftime('%d/%m/%Y'),
        })
    return jsonify(out)


# ─────────────────────────────────────────────────────────────
#  DGRTR — Cartes Grises
# ─────────────────────────────────────────────────────────────

def _require_cg_access():
    """Block dgrtr users who are not directeur_regional from cartes-grises pages."""
    if current_user.role == 'dgrtr' and getattr(current_user, 'dgrtr_type', None) != 'directeur_regional':
        abort(403)


def _require_dr_only():
    """Block dgrtr users who are not directeur_regional from police-style pages."""
    if current_user.role == 'dgrtr' and getattr(current_user, 'dgrtr_type', None) != 'directeur_regional':
        abort(403)


def _require_dgrtr_staff():
    """Block directeur_regional from DGRTR-internal pages (dashboard, licences, stats, etc.)."""
    if current_user.role == 'dgrtr' and getattr(current_user, 'dgrtr_type', None) == 'directeur_regional':
        abort(403)

@main_bp.route('/dgrtr/cartes-grises')
@roles_required('administrateur', 'judiciaire', 'dgrtr')
def dgrtr_cartes_grises():
    _require_cg_access()
    return render_template('dgrtr_cartes_grises.html')


@main_bp.route('/dgrtr/cartes-grises/<int:vehicle_id>/print')
@roles_required('administrateur', 'judiciaire', 'dgrtr')
def dgrtr_carte_grise_print(vehicle_id):
    _require_cg_access()
    from app.models import Vehicle, CarteGrise, CarteGriseSetting
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    cg = CarteGrise.query.filter_by(vehicle_id=vehicle_id).first()
    if not cg or cg.status != 'signee':
        from flask import abort
        abort(403)
    island = vehicle.owner_island or 'Grande Comore'
    cg_settings = CarteGriseSetting.get(island)

    # Generate vehicle QR code as base64 PNG
    vehicle_qr_data_uri = None
    if vehicle.track_token:
        try:
            import qrcode, io, base64 as _b64
            _qr = qrcode.QRCode(box_size=5, border=2)
            _qr.add_data(f'VEHICLE_TRACK:{vehicle.track_token}')
            _qr.make(fit=True)
            _img = _qr.make_image(fill_color='black', back_color='white')
            _buf = io.BytesIO()
            _img.save(_buf, format='PNG')
            vehicle_qr_data_uri = 'data:image/png;base64,' + _b64.b64encode(_buf.getvalue()).decode()
        except Exception:
            pass

    from datetime import timedelta
    date_expiration = None
    if cg.date_emission and cg_settings.duree_validite:
        date_expiration = cg.date_emission + timedelta(days=cg_settings.duree_validite)

    return render_template('dgrtr_carte_grise_print.html',
                           vehicle=vehicle, cg=cg,
                           cg_settings=cg_settings,
                           vehicle_qr_data_uri=vehicle_qr_data_uri,
                           date_expiration=date_expiration)


@main_bp.route('/dgrtr/parametres-cg')
@roles_required('administrateur', 'dgrtr')
def dgrtr_parametres_cg():
    if current_user.role == 'dgrtr' and getattr(current_user, 'dgrtr_type', None) != 'directeur_technique':
        abort(403)
    return render_template('dgrtr_parametres_cg.html')


@main_bp.route('/api/dgrtr/cartes-grises/search')
@roles_required('administrateur', 'judiciaire', 'dgrtr')
def dgrtr_cg_search():
    _require_cg_access()
    from app.models import Vehicle, CarteGrise
    q = request.args.get('q', '').strip()
    query = Vehicle.query.filter(Vehicle.qr_pending_approval == False)
    if q:
        query = query.filter(
            db.or_(
                Vehicle.license_plate.ilike(f'%{q}%'),
                Vehicle.owner_name.ilike(f'%{q}%'),
                Vehicle.owner_phone.ilike(f'%{q}%'),
            )
        )
    query = apply_island_filter(query, Vehicle.owner_island)
    limit = int(request.args.get('limit', 200))
    vehicles = query.order_by(Vehicle.created_at.desc()).limit(limit).all()
    results = []
    for v in vehicles:
        d = {
            'id': v.id,
            'license_plate': v.license_plate,
            'owner_name': v.owner_name,
            'owner_phone': v.owner_phone or '',
            'owner_address': v.owner_address or '',
            'vehicle_type': v.vehicle_type or '',
            'make': v.make or '',
            'model': v.model or '',
            'year': v.year or '',
            'fuel_type': v.fuel_type or '',
            'cv_class': v.cv_class or '',
            'vin': v.vin or '',
            'has_carte_grise': v.carte_grise is not None,
            'carte_grise': v.carte_grise.to_dict() if v.carte_grise else None,
        }
        results.append(d)
    return jsonify(results)


@main_bp.route('/api/dgrtr/cartes-grises/<int:vehicle_id>', methods=['GET', 'POST', 'PUT'])
@roles_required('administrateur', 'judiciaire', 'dgrtr')
def dgrtr_cg_vehicle(vehicle_id):
    _require_cg_access()
    from app.models import Vehicle, CarteGrise
    from datetime import date
    vehicle = Vehicle.query.get_or_404(vehicle_id)

    if request.method == 'GET':
        cg = vehicle.carte_grise
        return jsonify(cg.to_dict() if cg else {})

    data = request.get_json() or {}
    cg = vehicle.carte_grise
    if cg is None:
        cg = CarteGrise(vehicle_id=vehicle_id, created_by=current_user.username)
        db.session.add(cg)

    # date_emission, prix and civilite are editable from the CG page modal
    raw_civilite = (data.get('civilite') or '').strip()
    if raw_civilite in ('Mr', 'Mme', 'Mlle'):
        cg.civilite = raw_civilite
    if 'date_emission' in data:
        raw_date = (data.get('date_emission') or '').strip()
        if raw_date:
            try:
                cg.date_emission = date.fromisoformat(raw_date)
            except ValueError:
                cg.date_emission = None
        else:
            cg.date_emission = None

    raw_prix = data.get('prix')
    if raw_prix is not None and raw_prix != '':
        try:
            cg.prix = float(str(raw_prix).replace(',', '.'))
        except (ValueError, TypeError):
            pass
    else:
        cg.prix = None

    cg.updated_at = now_comoros()
    db.session.commit()
    return jsonify({'success': True, 'carte_grise': cg.to_dict()})


@main_bp.route('/api/dgrtr/cartes-grises/<int:vehicle_id>/request-signature', methods=['POST'])
@roles_required('administrateur', 'judiciaire', 'dgrtr')
def dgrtr_cg_request_signature(vehicle_id):
    _require_cg_access()
    from app.models import CarteGrise, Vehicle
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    cg = vehicle.carte_grise
    if not cg:
        return jsonify({'error': 'Carte grise non trouvée'}), 404
    if cg.status == 'signee':
        return jsonify({'error': 'Déjà signée'}), 400
    cg.status = 'en_attente'
    cg.signature_requested_at = now_comoros()
    cg.signature_requested_by = current_user.username
    db.session.commit()
    return jsonify({'success': True, 'carte_grise': cg.to_dict()})


@main_bp.route('/api/dgrtr/cartes-grises/<int:vehicle_id>/sign', methods=['POST'])
@roles_required('administrateur', 'dgrtr')
def dgrtr_cg_sign(vehicle_id):
    # Only DG, DT, DR can sign — not employe
    if current_user.role == 'dgrtr' and getattr(current_user, 'dgrtr_type', None) == 'employe':
        return jsonify({'error': 'Accès refusé'}), 403
    from app.models import CarteGrise, Vehicle
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    cg = vehicle.carte_grise
    if not cg:
        return jsonify({'error': 'Carte grise non trouvée'}), 404
    cg.status = 'signee'
    cg.signed_at = now_comoros()
    cg.signed_by = current_user.username
    db.session.commit()
    return jsonify({'success': True, 'carte_grise': cg.to_dict()})


@main_bp.route('/api/dgrtr/cartes-grises/stats')
@roles_required('administrateur', 'judiciaire', 'dgrtr')
def dgrtr_cg_stats():
    _require_cg_access()
    from app.models import CarteGrise, Vehicle
    from sqlalchemy import func
    base_q = CarteGrise.query.join(Vehicle)
    base_q = apply_island_filter(base_q, Vehicle.owner_island)
    total    = base_q.count()
    pending  = base_q.filter(CarteGrise.status == 'en_attente').count()
    signed   = base_q.filter(CarteGrise.status == 'signee').count()
    draft    = base_q.filter(CarteGrise.status == 'brouillon').count()
    return jsonify({'total': total, 'en_attente': pending, 'signee': signed, 'brouillon': draft})


@main_bp.route('/api/dgrtr/rapport-cg')
@roles_required('administrateur', 'judiciaire', 'dgrtr')
def dgrtr_rapport_cg_api():
    _require_cg_access()
    from app.models import CarteGrise, Vehicle
    from collections import defaultdict
    from datetime import date, timedelta
    base_q = CarteGrise.query.join(Vehicle)
    base_q = apply_island_filter(base_q, Vehicle.owner_island)
    cgs = base_q.all()

    monthly = defaultdict(lambda: {'crees': 0, 'signees': 0})
    vehicle_types = defaultdict(int)

    for cg in cgs:
        if cg.created_at:
            monthly[cg.created_at.strftime('%Y-%m')]['crees'] += 1
        if cg.signed_at:
            monthly[cg.signed_at.strftime('%Y-%m')]['signees'] += 1
        if cg.vehicle:
            vehicle_types[cg.vehicle.vehicle_type or 'Autre'] += 1

    today = date.today()
    months_out = []
    for i in range(17, -1, -1):
        d = today.replace(day=1)
        for _ in range(i):
            d = (d - timedelta(days=1)).replace(day=1)
        key = d.strftime('%Y-%m')
        months_out.append({
            'key': key,
            'label': d.strftime('%m/%Y'),
            'crees':   monthly[key]['crees'],
            'signees': monthly[key]['signees'],
        })

    this_month = today.strftime('%Y-%m')
    last_month = ((today.replace(day=1)) - timedelta(days=1)).strftime('%Y-%m')

    total        = len(cgs)
    total_signed = sum(1 for cg in cgs if cg.status == 'signee')
    total_pending= sum(1 for cg in cgs if cg.status == 'en_attente')

    return jsonify({
        'monthly': months_out,
        'vehicle_types': [{'type': k, 'count': v} for k, v in sorted(vehicle_types.items(), key=lambda x: -x[1])],
        'totals': {'total': total, 'signee': total_signed, 'en_attente': total_pending},
        'this_month': monthly[this_month],
        'last_month': monthly[last_month],
    })


@main_bp.route('/dgrtr/rapport-cg')
@roles_required('administrateur', 'judiciaire', 'dgrtr')
def dgrtr_rapport_cg():
    _require_cg_access()
    return render_template('dgrtr_rapport_cg.html')


@main_bp.route('/dgrtr/recettes-cg')
@roles_required('administrateur', 'dgrtr')
def dgrtr_recettes_cg():
    _require_cg_access()
    return render_template('dgrtr_recettes_cg.html')


@main_bp.route('/api/dgrtr/recettes-cg')
@roles_required('administrateur', 'dgrtr')
def dgrtr_recettes_cg_api():
    _require_cg_access()
    from app.models import CarteGrise, Vehicle
    from sqlalchemy import func
    from datetime import date
    date_from = request.args.get('date_from')
    date_to   = request.args.get('date_to')

    q = CarteGrise.query.filter_by(status='signee').join(Vehicle)
    q = apply_island_filter(q, Vehicle.owner_island)
    if date_from:
        try:
            from datetime import datetime
            q = q.filter(CarteGrise.signed_at >= datetime.combine(date.fromisoformat(date_from), datetime.min.time()))
        except ValueError:
            pass
    if date_to:
        try:
            from datetime import datetime, timedelta
            q = q.filter(CarteGrise.signed_at < datetime.combine(date.fromisoformat(date_to) + timedelta(days=1), datetime.min.time()))
        except ValueError:
            pass

    cgs = q.order_by(CarteGrise.signed_at.desc()).all()
    total_montant = sum(c.prix for c in cgs if c.prix is not None)
    nb_avec_prix  = sum(1 for c in cgs if c.prix is not None)

    rows = []
    for c in cgs:
        v = c.vehicle
        rows.append({
            'id': c.id,
            'vehicle_id': v.id,
            'license_plate': v.license_plate,
            'owner_name': v.owner_name or '',
            'civilite': c.civilite or '',
            'signed_at': c.signed_at.strftime('%d/%m/%Y') if c.signed_at else '',
            'date_emission': c.date_emission.strftime('%d/%m/%Y') if c.date_emission else '',
            'prix': c.prix if c.prix is not None else None,
        })
    return jsonify({
        'count': len(cgs),
        'nb_avec_prix': nb_avec_prix,
        'total_montant': total_montant,
        'rows': rows,
    })


@main_bp.route('/api/dgrtr/cartes-grises/stream')
@roles_required('administrateur', 'judiciaire', 'dgrtr')
def dgrtr_cg_stream():
    """SSE stream: pushes events when a new en_attente or signee carte grise appears."""
    _require_cg_access()
    from flask import Response, stream_with_context
    from app.models import CarteGrise, Vehicle
    import time, json as _json

    user_country = getattr(current_user, 'country', None) if current_user.role != 'administrateur' else None

    def _q_base(status):
        q = CarteGrise.query.filter_by(status=status).join(Vehicle)
        if user_country:
            q = q.filter(Vehicle.owner_island == user_country)
        return q

    def _newest_pending_id():
        latest = _q_base('en_attente').order_by(CarteGrise.signature_requested_at.desc()).first()
        return latest.id if latest else 0

    def _signed_count():
        return _q_base('signee').count()

    def generate():
        last_pending_id = _newest_pending_id()
        last_signed_count = _signed_count()
        yield 'data: ' + _json.dumps({'type': 'connected'}) + '\n\n'
        while True:
            time.sleep(3)
            try:
                db.session.expire_all()
                events = []

                current_pending_id = _newest_pending_id()
                if current_pending_id != last_pending_id:
                    count = _q_base('en_attente').count()
                    events.append(_json.dumps({'type': 'new_request', 'count': count}))
                    last_pending_id = current_pending_id

                current_signed_count = _signed_count()
                if current_signed_count != last_signed_count:
                    events.append(_json.dumps({'type': 'signed', 'count': current_signed_count}))
                    last_signed_count = current_signed_count

                if events:
                    for ev in events:
                        yield 'data: ' + ev + '\n\n'
                else:
                    yield 'data: {"type":"ping"}\n\n'
            except GeneratorExit:
                break
            except Exception:
                yield 'data: {"type":"ping"}\n\n'

    resp = Response(stream_with_context(generate()), mimetype='text/event-stream')
    resp.headers['Cache-Control'] = 'no-cache'
    resp.headers['X-Accel-Buffering'] = 'no'
    return resp


@main_bp.route('/api/dgrtr/cartes-grises/pending')
@roles_required('administrateur', 'dgrtr')
def dgrtr_cg_pending():
    _require_cg_access()
    from app.models import CarteGrise, Vehicle
    query = CarteGrise.query.filter_by(status='en_attente').join(Vehicle)
    query = apply_island_filter(query, Vehicle.owner_island)
    cgs = query.order_by(CarteGrise.signature_requested_at).all()
    results = []
    for cg in cgs:
        v = cg.vehicle
        results.append({
            'vehicle_id': v.id,
            'license_plate': v.license_plate,
            'owner_name': v.owner_name,
            'make': v.make or '',
            'model': v.model or '',
            'requested_at': cg.signature_requested_at.strftime('%d/%m/%Y %H:%M') if cg.signature_requested_at else '',
            'requested_by': cg.signature_requested_by or '',
        })
    return jsonify(results)


def _require_cg_settings_access():
    """Allow DR, DT, judiciaire, and admin to manage cartes grises settings."""
    if current_user.role == 'dgrtr':
        dt = getattr(current_user, 'dgrtr_type', None)
        if dt not in ('directeur_regional', 'directeur_technique'):
            abort(403)


ISLANDS = ('Grande Comore', 'Anjouan', 'Moheli')


@main_bp.route('/api/dgrtr/cartes-grises/settings', methods=['GET', 'POST'])
@roles_required('administrateur', 'judiciaire', 'dgrtr')
def dgrtr_cg_settings():
    _require_cg_settings_access()
    from app.models import CarteGriseSetting
    island = request.args.get('island') or (request.get_json() or {}).get('island') or 'Grande Comore'
    if island not in ISLANDS:
        return jsonify({'error': 'Île invalide'}), 400
    s = CarteGriseSetting.get(island)
    if request.method == 'GET':
        return jsonify({
            'island':           s.island,
            'directeur_nom':    s.directeur_nom or '',
            'signature_url':    s.signature_url,
            'duree_validite':   s.duree_validite or 90,
            'footer_telephone': s.footer_telephone or '',
            'footer_adresse':   s.footer_adresse or '',
        })
    data = request.get_json() or {}
    if 'directeur_nom' in data:
        s.directeur_nom    = (data['directeur_nom'] or '').strip() or None
    if 'duree_validite' in data:
        try:
            s.duree_validite = int(data['duree_validite'])
        except (ValueError, TypeError):
            pass
    if 'footer_telephone' in data:
        s.footer_telephone = (data['footer_telephone'] or '').strip() or None
    if 'footer_adresse' in data:
        s.footer_adresse   = (data['footer_adresse'] or '').strip() or None
    db.session.commit()
    return jsonify({'success': True})


@main_bp.route('/api/dgrtr/cartes-grises/settings/signature', methods=['POST'])
@roles_required('administrateur', 'judiciaire', 'dgrtr')
def dgrtr_cg_settings_signature_upload():
    _require_cg_settings_access()
    import os, uuid
    from werkzeug.utils import secure_filename
    from app.models import CarteGriseSetting
    from app.cloudinary_utils import is_cloudinary_enabled, upload_file as cloud_upload, delete_file as cloud_delete
    island = request.form.get('island') or 'Grande Comore'
    if island not in ISLANDS:
        return jsonify({'error': 'Île invalide'}), 400
    file = request.files.get('signature')
    if not file or not file.filename:
        return jsonify({'error': 'Aucun fichier reçu'}), 400
    ext = os.path.splitext(secure_filename(file.filename))[1].lower()
    if ext not in {'.jpg', '.jpeg', '.png', '.webp'}:
        return jsonify({'error': 'Format non autorisé (jpg, png, webp)'}), 400
    s = CarteGriseSetting.get(island)
    if s.signature_filename:
        cloud_delete(s.signature_filename, local_folder='signatures')
    if is_cloudinary_enabled():
        filename = cloud_upload(file, 'signatures')
    else:
        upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'signatures')
        os.makedirs(upload_dir, exist_ok=True)
        filename = f'{uuid.uuid4().hex}{ext}'
        file.save(os.path.join(upload_dir, filename))
    s.signature_filename = filename
    db.session.commit()
    return jsonify({'success': True, 'signature_url': s.signature_url})


@main_bp.route('/api/dgrtr/cartes-grises/settings/signature', methods=['DELETE'])
@roles_required('administrateur', 'judiciaire', 'dgrtr')
def dgrtr_cg_settings_signature_delete():
    _require_cg_settings_access()
    from app.models import CarteGriseSetting
    from app.cloudinary_utils import delete_file as cloud_delete
    island = request.args.get('island') or 'Grande Comore'
    if island not in ISLANDS:
        return jsonify({'error': 'Île invalide'}), 400
    s = CarteGriseSetting.get(island)
    if s.signature_filename:
        cloud_delete(s.signature_filename, local_folder='signatures')
        s.signature_filename = None
        db.session.commit()
    return jsonify({'success': True})







