from flask import Blueprint, render_template, jsonify, request, redirect, url_for, flash, abort, send_file
from flask_login import login_required, current_user
from flask_jwt_extended import jwt_required, get_jwt_identity
from functools import wraps
from sqlalchemy import func
from app import db
from app.models import Vehicle, User, Phone
from decimal import Decimal
import qrcode
import io
import csv
from datetime import datetime, timedelta
import os
from app.timezone_utils import now_comoros
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

# Helper function to apply island filter for judiciaire and policier users
def apply_island_filter(query, island_field):
    """Apply island/country filter for judiciaire and policier users with assigned country.
    Judiciaire and policier users can only see data for their assigned island/country."""
    if current_user.role in ['judiciaire', 'policier'] and current_user.country:
        query = query.filter(island_field == current_user.country)
    return query

def check_island_access(island):
    """Check if current user has access to data from a specific island.
    Raises 403 Forbidden if judiciaire or policier user doesn't have access."""
    if current_user.role in ['judiciaire', 'policier'] and current_user.country:
        if island != current_user.country:
            abort(403)
    return True

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


@main_bp.route('/')
def index():
    """Page d'accueil du dashboard"""
    # Require login before showing the public index/welcome page
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login', next=url_for('main.index')))
    return render_template('index.html')


@main_bp.route('/dashboard')
@roles_required('administrateur','policier','judiciaire')
def dashboard():
    """Page du dashboard avec statistiques des véhicules (protected)"""
    query = Vehicle.query
    if current_user.role == 'judiciaire' and current_user.country:
        query = query.filter(Vehicle.owner_island == current_user.country)
    recent = query.order_by(Vehicle.created_at.desc()).limit(10).all()
    initial_vehicles = [v.to_dict() for v in recent]
    return render_template('dashboard.html', initial_vehicles=initial_vehicles)


@main_bp.route('/vehicles')
@roles_required('administrateur','policier','judiciaire')
def vehicles_page():
    """Page de gestion des véhicules"""
    return render_template('vehicles.html')


@main_bp.route('/reports')
@roles_required('administrateur','policier','judiciaire')
def reports_page():
    """Page de rapports (placeholder)"""
    return render_template('reports.html')


@main_bp.route('/fines')
@roles_required('policier','judiciaire')
def fines_page():
    """Page d'administration des amandes/fines"""
    return render_template('fines.html')


@main_bp.route('/fines/stats')
@roles_required('policier','judiciaire')
def fines_stats_page():
    """Page de statistiques des amandes"""
    return render_template('fines_stats.html')


@main_bp.route('/exoneration')
@roles_required('administrateur','policier')
def exoneration_page():
    """Page de gestion des véhicules exonérés"""
    return render_template('exoneration.html')


@vehicle_bp.route('/stats', methods=['GET'])
@login_required
def get_vehicle_stats():
    """Retourner les statistiques des véhicules en JSON"""
    query = db.session.query(Vehicle)
    query = apply_island_filter(query, Vehicle.owner_island)
    
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
    query = Vehicle.query
    query = apply_island_filter(query, Vehicle.owner_island)
    vehicles = query.order_by(Vehicle.created_at.desc()).all()
    return jsonify([v.to_dict() for v in vehicles])


@vehicle_bp.route('/query', methods=['GET'])
@login_required
def query_vehicles():
    """Retourner une liste filtrée de véhicules selon query params"""
    q = request.args.get('q', type=str)
    vtype = request.args.get('type', type=str)
    status = request.args.get('status', type=str)
    start = request.args.get('start_date', type=str)
    end = request.args.get('end_date', type=str)

    expired = request.args.get('expired', type=str)
    query = Vehicle.query
    query = apply_island_filter(query, Vehicle.owner_island)
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
    # filter by expired registration (vignette) if requested
    if expired is not None:
        try:
            if expired.lower() in ('1','true','yes'):
                # include vehicles with registration_expiry set and before now
                query = query.filter(Vehicle.registration_expiry != None).filter(Vehicle.registration_expiry <= now_comoros())
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

    expired = request.args.get('expired', type=str)
    query = Vehicle.query
    query = apply_island_filter(query, Vehicle.owner_island)
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
    writer.writerow(['id','license_plate','owner_name','vehicle_type','status','make','model','year','vin','color','owner_phone','owner_address','Expiration Vignette','created_at'])
    for v in vehicles:
        writer.writerow([
            v.id,
            v.license_plate,
            v.owner_name,
            v.vehicle_type,
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
    owner_address = data.get('owner_address')
    registration_expiry = data.get('registration_expiry')
    insurance_company = data.get('insurance_company')
    insurance_expiry = data.get('insurance_expiry')

    if not license_plate or not owner_name or not vehicle_type:
        return jsonify({'error': 'license_plate, owner_name et vehicle_type requis'}), 400

    # Vérifier unicité immatriculation
    if Vehicle.query.filter_by(license_plate=license_plate).first():
        return jsonify({'error': 'Véhicule avec cette immatriculation existe déjà'}), 400

    vehicle = Vehicle(
        license_plate=license_plate,
        owner_name=owner_name,
        owner_phone=data.get('owner_phone'),
        owner_island=data.get('owner_island'),
        vehicle_type=vehicle_type,
        usage_type=usage_type,
        color=data.get('color'),
        status=data.get('status') or 'active',
        make=make,
        model=model,
        year=year,
        vin=vin,
        owner_address=owner_address,
        insurance_company=insurance_company
    )
    # parse registration_expiry if provided
    if registration_expiry:
        try:
            from datetime import datetime
            vehicle.registration_expiry = datetime.fromisoformat(registration_expiry)
        except Exception:
            pass
    # parse insurance_expiry if provided
    if insurance_expiry:
        try:
            from datetime import datetime
            vehicle.insurance_expiry = datetime.fromisoformat(insurance_expiry)
        except Exception:
            pass
    db.session.add(vehicle)
    db.session.commit()
    return jsonify(vehicle.to_dict()), 201
@vehicle_bp.route('/<int:vehicle_id>', methods=['GET'])
@login_required
def get_vehicle(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    check_island_access(vehicle.owner_island)
    return jsonify(vehicle.to_dict())


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
    
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    check_island_access(vehicle.owner_island)
    data = request.get_json() or request.form
    try:
        amount = float(data.get('amount'))
    except Exception:
        return jsonify({'error':'Montant invalide'}), 400
    reason = data.get('reason')
    # Use the authenticated user's username as the officer to prevent spoofing
    try:
        from flask_login import current_user
        officer = current_user.username if (current_user and getattr(current_user, 'is_authenticated', False)) else (data.get('officer') or '')
    except Exception:
        officer = data.get('officer')
    notes = data.get('notes')
    if not reason or amount <= 0:
        return jsonify({'error':'reason et amount requis'}), 400
    
    # Check if vehicle is exonerated
    exonerated = ExoneratedVehicle.query.filter_by(vehicle_id=vehicle.id).first()
    is_exonerated = exonerated is not None
    
    fine = Fine(vehicle_id=vehicle.id, amount=amount, reason=reason, officer=officer, notes=notes)
    
    # If vehicle is exonerated, mark it for automatic payment after 24 hours
    # (don't mark as paid immediately - will be handled by background task)
    if is_exonerated:
        # Add a note indicating this fine will be auto-paid after 24h
        if notes:
            fine.notes = f"{notes}\n[EXONÉRÉ - Paiement automatique dans 24h]"
        else:
            fine.notes = "[EXONÉRÉ - Paiement automatique dans 24h]"
    
    db.session.add(fine)
    
    # also add a history entry
    action_text = f"Amande émise: {reason} ({amount})"
    hist = VehicleHistory(vehicle_id=vehicle.id, action=action_text, officer=officer, notes=notes)
    db.session.add(hist)
    db.session.commit()
    
    # Send SMS notification to vehicle owner
    try:
        sms_result = sms_service.send_fine_notification(vehicle, fine)
        print(f"✉️  SMS Notification Result: {sms_result}")
    except Exception as e:
        print(f"❌ SMS Notification Error: {str(e)}")
        sms_result = {'success': False, 'message': str(e)}
    
    return jsonify({
        'fine': fine.to_dict(), 
        'history': hist.to_dict(),
        'is_exonerated': is_exonerated,
        'sms_sent': sms_result.get('success', False),
        'sms_message': sms_result.get('message', '')
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
            d['track_token'] = f.vehicle.track_token
        except Exception:
            d['license_plate'] = None
            d['track_token'] = None
        result.append(d)
    return jsonify(result)


@vehicle_bp.route('/fines/all', methods=['GET'])
@login_required
def list_all_fines():
    from app.models import Fine, Vehicle
    # optional filters
    q = request.args.get('q', type=str)
    paid = request.args.get('paid', type=str)
    export = request.args.get('export', type=str)
    start_date = request.args.get('start_date', type=str)
    end_date = request.args.get('end_date', type=str)
    
    # Debug logging
    print(f"[FINES EXPORT] Received params - start_date: {start_date}, end_date: {end_date}, paid: {paid}, export: {export}")

    query = Fine.query.join(Vehicle)
    query = apply_island_filter(query, Vehicle.owner_island)
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
        except Exception:
            d['license_plate'] = None
            d['track_token'] = None
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
        
        # Add total row
        rows.append(['', '', '', '', '', ''])
        rows.append(['', '', f"TOTAL: {int(total_amount):,} KMF".replace(',', ' '), '', '', ''])

        # Use the same professional PDF builder
        buffer = io.BytesIO()
        
        # Build title with date range if provided
        title_text = 'Rapport des Amendes Payées'
        if start_date and end_date:
            try:
                start_formatted = datetime.strptime(start_date, '%Y-%m-%d').strftime('%d/%m/%Y')
                end_formatted = datetime.strptime(end_date, '%Y-%m-%d').strftime('%d/%m/%Y')
                title_text = f'Rapport des Amendes Payées<br/><font size="12">Période: {start_formatted} - {end_formatted}</font>'
            except:
                pass
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
    if not label or not amount:
        return jsonify({'error': 'label et amount requis'}), 400
    try:
        amt = Decimal(str(amount))
    except Exception:
        return jsonify({'error': 'Montant invalide'}), 400
    ft = FineType(label=label, amount=amt, code=code)
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
    db.session.commit()
    return jsonify(ft.to_dict())


# Mark a fine as paid and create a receipt + history entry
@vehicle_bp.route('/fines/<int:fine_id>/pay', methods=['POST'])
@login_required
def pay_fine(fine_id):
    from app.models import Fine, VehicleHistory
    fine = Fine.query.get_or_404(fine_id)
    if fine.paid:
        return jsonify({'error': 'Amande déjà payée'}), 400
    data = request.get_json() or request.form
    # optional: payment_method, paid_by
    payment_method = data.get('payment_method')
    paid_by = data.get('paid_by') or current_user.username if current_user and current_user.is_authenticated else None

    # mark paid
    from datetime import datetime
    fine.paid = True
    fine.paid_at = now_comoros()
    # generate a simple receipt number
    fine.receipt_number = f"REC-{fine.id}-{int(fine.paid_at.timestamp())}"
    db.session.add(fine)

    # add history entry
    hist = VehicleHistory(vehicle_id=fine.vehicle_id, action=f"Amande payée ({fine.receipt_number}) - {float(fine.amount)} MAD", officer=paid_by, notes=(payment_method or ''))
    db.session.add(hist)
    db.session.commit()

    # return updated fine and history
    resp = {'fine': fine.to_dict(), 'history': hist.to_dict()}
    return jsonify(resp), 200


@vehicle_bp.route('/fines/stats', methods=['GET'])
@login_required
def get_fines_stats():
    """Retourner les statistiques des amendes en JSON"""
    from app.models import Fine
    from sqlalchemy import func, extract
    from datetime import datetime, timedelta

    try:
        # Build base query with island filter for judiciaire users
        base_query = db.session.query(Fine).join(Vehicle)
        base_query = apply_island_filter(base_query, Vehicle.owner_island)
        
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
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    # URL publique de suivi
    track_url = f"{request.host_url.rstrip('/')}/track/{vehicle.track_token}"
    # Générer QR code PNG
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(track_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png', download_name=f'{vehicle.license_plate}_qrcode.png')


@main_bp.route('/track/<token>')
def public_track(token):
    # page sécurisée - accessible seulement aux utilisateurs connectés
    if not current_user.is_authenticated:
        abort(403)
    vehicle = Vehicle.query.filter_by(track_token=token).first_or_404()
    # collect history entries and fines
    history_items = []
    unpaid_count = 0
    # vehicle history
    try:
        from app.models import VehicleHistory, Fine
        hist = VehicleHistory.query.filter_by(vehicle_id=vehicle.id).order_by(VehicleHistory.created_at.desc()).all()
        for h in hist:
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
    
    # Pass datetime.now for expiry calculations in template
    from datetime import datetime
    return render_template('track.html', vehicle=vehicle, history=history_items, unpaid_count=unpaid_count, now=datetime.now)


@main_bp.route('/payments')
@main_bp.route('/payments')
@roles_required('judiciaire')
def payments_page():
    """Page de gestion des paiements des amandes"""
    return render_template('payments.html')


@main_bp.route('/fines/receipt/<int:fine_id>')
@login_required
def fine_receipt(fine_id):
    from app.models import Fine, Vehicle
    fine = Fine.query.get_or_404(fine_id)
    vehicle = Vehicle.query.get(fine.vehicle_id)
    # receipts are part of payments area: show but ensure access control
    # allow admin, judiciaire and policier to view receipt
    role = getattr(current_user, 'role', None)
    if not role and getattr(current_user, 'is_admin', False):
        role = 'administrateur'
    if role not in ('administrateur','judiciaire','policier'):
        abort(403)
    return render_template('receipt.html', fine=fine, vehicle=vehicle)


@main_bp.route('/users')
@roles_required('administrateur')
def users_page():
    return render_template('users.html')


@main_bp.route('/api/users/list')
@roles_required('administrateur')
def api_users_list():
    users = User.query.order_by(User.created_at.desc()).all()
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
            'is_active': bool(getattr(u, 'is_active', True)),
            'created_at': u.created_at.strftime('%Y-%m-%d %H:%M')
        })
    return jsonify(out)


@main_bp.route('/api/users/create', methods=['POST'])
@roles_required('administrateur')
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
    u.is_active = bool(is_active)
    u.set_password(password)
    # if role is administrateur mark is_admin True for backwards compatibility
    if role == 'administrateur':
        u.is_admin = True
    db.session.add(u)
    db.session.commit()
    return jsonify({'ok': True, 'id': u.id})


@main_bp.route('/api/users/<int:user_id>/update', methods=['POST'])
@roles_required('administrateur')
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
    if 'password' in data and data.get('password'):
        u.set_password(data.get('password'))

    db.session.commit()
    return jsonify({'ok': True})


@main_bp.route('/api/users/<int:user_id>/delete', methods=['POST'])
@roles_required('administrateur')
def api_users_delete(user_id):
    if current_user.id == user_id:
        return jsonify({'error':'cannot delete yourself'}), 400
    u = User.query.get_or_404(user_id)
    db.session.delete(u)
    db.session.commit()
    return jsonify({'ok': True})


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
    # point the QR to the public tracking page itself
    track_url = f"{request.host_url.rstrip('/')}/track/{vehicle.track_token}"
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(track_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')


@vehicle_bp.route('/<int:vehicle_id>', methods=['PUT'])
@login_required
def update_vehicle(vehicle_id):
    from app.models import VehicleHistory
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    check_island_access(vehicle.owner_island)
    data = request.get_json() or request.form
    
    # Track status change for history
    old_status = vehicle.status
    status_changed = False
    
    # Mettre à jour les champs autorisés
    for field in ['license_plate', 'owner_name', 'owner_phone', 'owner_island', 'vehicle_type', 'usage_type', 'color', 'status', 'make', 'model', 'year', 'vin', 'owner_address', 'registration_expiry', 'insurance_company', 'insurance_expiry']:
        if field in data and data.get(field) is not None:
            if field == 'status' and data.get(field) != old_status:
                status_changed = True
            setattr(vehicle, field, data.get(field))
    # parse registration_expiry if present
    if 'registration_expiry' in data and data.get('registration_expiry'):
        try:
            from datetime import datetime
            vehicle.registration_expiry = datetime.fromisoformat(data.get('registration_expiry'))
        except Exception:
            pass
    # parse insurance_expiry if present
    if 'insurance_expiry' in data and data.get('insurance_expiry'):
        try:
            from datetime import datetime
            vehicle.insurance_expiry = datetime.fromisoformat(data.get('insurance_expiry'))
        except Exception:
            pass
    
    # Add history entry if status changed
    if status_changed:
        new_status = vehicle.status
        status_labels = {
            'active': 'Actif',
            'inactive': 'Inactif',
            'suspended': 'Suspendu'
        }
        old_status_label = status_labels.get(old_status, old_status)
        new_status_label = status_labels.get(new_status, new_status)
        
        try:
            from flask_login import current_user
            officer = current_user.username if (current_user and getattr(current_user, 'is_authenticated', False)) else 'Système'
        except Exception:
            officer = 'Système'
        
        hist = VehicleHistory(
            vehicle_id=vehicle.id,
            action=f"Changement de statut: {old_status_label} → {new_status_label}",
            officer=officer,
            notes=f"Statut modifié de '{old_status_label}' à '{new_status_label}'"
        )
        db.session.add(hist)
    
    db.session.commit()
    return jsonify(vehicle.to_dict())


@vehicle_bp.route('/<int:vehicle_id>', methods=['DELETE'])
@login_required
def delete_vehicle(vehicle_id):
    vehicle = Vehicle.query.get_or_404(vehicle_id)
    db.session.delete(vehicle)
    db.session.commit()
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
@roles_required('administrateur','policier','judiciaire')
def phones_page():
    """Display phones management page"""
    return render_template('phones.html')

@main_bp.route('/phone-usage')
@roles_required('administrateur','policier','judiciaire')
def phone_usage_page():
    """Display phone usage history page"""
    return render_template('phone_usage.html')


@main_bp.route('/phone/<int:phone_id>/history')
@roles_required('administrateur','policier','judiciaire')
def phone_history_page(phone_id):
    """Display usage history for a specific phone"""
    phone = Phone.query.get(phone_id)
    if not phone:
        abort(404)
    check_island_access(phone.island)
    return render_template('phone_history.html', phone_id=phone_id, return_to=request.args.get('return_to', '/phones'))


@main_bp.route('/photo-submissions')
@roles_required('administrateur','policier','judiciaire')
def photo_submissions_page():
    """Display photo submissions page"""
    return render_template('photo_submissions.html')




