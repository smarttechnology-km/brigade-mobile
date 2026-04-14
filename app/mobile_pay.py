from flask import Blueprint, request, jsonify, current_app, url_for, render_template, send_file
from app import db
from app.models import Payment, Fine, Vehicle
from datetime import datetime
import io
import json
import hashlib
import hmac
import qrcode
from app.timezone_utils import now_comoros

mobile_pay_bp = Blueprint('mobile_pay', __name__, url_prefix='/pay')


@mobile_pay_bp.route('/lookup', methods=['GET'])
def lookup():
    """Public lookup endpoint: ?q=<track_token_or_plate>
    Returns outstanding fines for the provided token or plate. (Stubbed)
    """
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'error': 'Missing query parameter q'}), 400

    # Try track_token first
    vehicle = Vehicle.query.filter_by(track_token=q).first()
    if not vehicle:
        vehicle = Vehicle.query.filter(Vehicle.license_plate.ilike(f'%{q}%')).first()

    if not vehicle:
        return jsonify({'fines': [], 'vehicle': None})

    # Return unpaid fines only
    unpaid_fines = [f.to_dict() for f in vehicle.fines.filter_by(paid=False).order_by(Fine.issued_at.desc()).all()]

    return jsonify({'vehicle': vehicle.to_dict(), 'fines': unpaid_fines})


@mobile_pay_bp.route('/create', methods=['POST'])
def create_payment():
    """Create a payment session with Huri Money (stub).
    Expects JSON: { "fines": [id, ...], "payer_name": ..., "payer_email": ... }
    Returns a placeholder `checkout_url` until Huri credentials are provided.
    """
    data = request.get_json() or {}
    fines_ids = data.get('fines') or []
    payer_name = data.get('payer_name')
    payer_email = data.get('payer_email')

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
    
    license_plate = vehicle.license_plate
    owner_name = vehicle.owner_name

    total = sum([f.amount for f in fines])

    payment = Payment(amount=total, currency='USD', status='pending', license_plate=license_plate, owner_name=owner_name, payer_name=payer_name, payer_email=payer_email, fines=str(fines_ids))
    db.session.add(payment)
    db.session.commit()

    # Checkout URL pointing to the simulated payment page (HTML)
    checkout_url = url_for('mobile_pay.checkout_page', payment_id=payment.id, _external=True)

    return jsonify({
        'payment_id': payment.id, 
        'checkout_url': checkout_url,
        'amount': int(total * 100),  # Convert to cents for API consistency
        'currency': 'USD',
        'status': 'pending'
    })


@mobile_pay_bp.route('/check-balance', methods=['POST'])
def check_balance():
    """Check if Huri Money account has sufficient balance for payment.
    
    Expected JSON:
    {
        "phone_number": "3123456",
        "required_amount": 50000  // in cents (KMF)
    }
    """
    data = request.get_json() or {}
    phone_number = data.get('phone_number')
    required_amount = data.get('required_amount')

    if not phone_number or required_amount is None:
        return jsonify({'error': 'Missing phone_number or required_amount'}), 400

    # In production, this would call Huri Money API to check balance
    # For now, simulate different scenarios based on phone number
    
    # Simulate balance check: for demo purposes, some numbers have insufficient balance
    simulated_balances = {
        '3111111': 10000,     # Insufficient (10,000 KMF)
        '3122222': 200000,    # Sufficient (200,000 KMF)
        '3133333': 5000,      # Insufficient (5,000 KMF)
    }
    
    # Get balance or default to sufficient amount
    account_balance = simulated_balances.get(phone_number, 500000)
    
    # Convert cents to KMF for display
    required_amount_kmf = required_amount / 100 if required_amount > 100 else required_amount
    account_balance_kmf = account_balance / 100 if account_balance > 100 else account_balance
    
    has_sufficient_balance = account_balance >= required_amount
    
    console_output = {
        'phone_number': phone_number,
        'required_amount': int(required_amount_kmf),
        'account_balance': int(account_balance_kmf),
        'has_sufficient_balance': has_sufficient_balance,
    }
    
    print(f'💰 Balance Check: {console_output}')
    
    if has_sufficient_balance:
        return jsonify({
            'status': 'connected',
            'has_sufficient_balance': True,
            'balance': int(account_balance),
            'message': 'Balance is sufficient'
        }), 200
    else:
        return jsonify({
            'status': 'insufficient_balance',
            'has_sufficient_balance': False,
            'balance': int(account_balance),
            'required': int(required_amount),
            'message': f'Insufficient balance. Required: {required_amount}, Available: {account_balance}'
        }), 200  # Return 200 even for insufficient balance to allow client-side handling


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

    payment = Payment.query.get(int(local_payment_id))
    if not payment:
        return jsonify({'error': 'Payment not found'}), 404

    if status == 'paid':
        payment.status = 'paid'
        payment.huri_payment_id = huri_id
        payment.phone_number = phone_number
        payment.paid_at = now_comoros()
        db.session.commit()

        # Mark fines as paid
        try:
            import json
            fine_ids = json.loads(payment.fines)
        except Exception:
            fine_ids = []

        for fid in fine_ids:
            f = Fine.query.get(int(fid))
            if f:
                f.paid = True
                f.paid_at = now_comoros()
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

    # Generate receipt number
    receipt_number = f'RCP-{p.id}-{p.created_at.timestamp()}'
    
    return jsonify({
        'payment_id': str(p.id),
        'receipt_number': receipt_number,
        'amount': int(p.amount * 100),  # Convert to cents for API consistency
        'currency': p.currency,
        'status': p.status,
        'payment_method': 'huri_money',
        'created_at': p.created_at.isoformat() if p.created_at else None,
        'paid_at': p.paid_at.isoformat() if p.paid_at else None,
        'license_plate': p.license_plate,
        'owner_name': p.owner_name,
        'payer_name': p.payer_name,
        'payer_email': p.payer_email,
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
    Query param: plate=<license_plate>
    Returns the most recent payment OR a generated receipt from paid fines.
    """
    plate = request.args.get('plate', '').strip()
    if not plate:
        return jsonify({'error': 'Missing plate parameter'}), 400
    
    # Find vehicle by license plate
    vehicle = Vehicle.query.filter(Vehicle.license_plate.ilike(f'%{plate}%')).first()
    if not vehicle:
        return jsonify({'error': 'Véhicule non trouvé'}), 404
    
    from sqlalchemy import or_, and_
    
    # First priority: try to get a paid/completed payment for this vehicle
    last_payment = Payment.query.filter(
        and_(
            Payment.license_plate.ilike(f'%{vehicle.license_plate}%'),
            Payment.status.in_(['paid', 'completed'])
        )
    ).order_by(
        Payment.paid_at.desc().nullslast(),
        Payment.created_at.desc()
    ).first()
    
    # Second priority: get the most recent payment of any status
    if not last_payment:
        last_payment = Payment.query.filter(
            Payment.license_plate.ilike(f'%{vehicle.license_plate}%')
        ).order_by(
            Payment.created_at.desc()
        ).first()
    
    # Third priority: try with the original plate input
    if not last_payment:
        last_payment = Payment.query.filter(
            Payment.license_plate.ilike(f'%{plate}%')
        ).order_by(
            Payment.created_at.desc()
        ).first()
    
    # Fourth priority: Generate receipt from most recent paid fine(s)
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


@mobile_pay_bp.route('/receipt/<payment_id>.pdf', methods=['GET'])
def download_receipt_pdf(payment_id):
    """Generate and download receipt as PDF."""
    # Try to find payment by ID - convert to int if possible
    payment = None
    try:
        payment = Payment.query.get(int(payment_id))
    except (ValueError, TypeError):
        pass
    
    if not payment:
        # Return 404 with error details
        return jsonify({'error': f'Payment not found: {payment_id}'}), 404
    
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib import colors
        from io import BytesIO
        from datetime import datetime
        
        # Create PDF in memory
        pdf_buffer = BytesIO()
        doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
        
        # Container for PDF elements
        elements = []
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=20,
            textColor=colors.black,
            spaceAfter=30,
            alignment=1  # Center
        )
        
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=12,
            textColor=colors.black,
            spaceAfter=12,
            spaceBefore=12
        )
        
        # Title
        elements.append(Paragraph("REÇU DE PAIEMENT", title_style))
        elements.append(Spacer(1, 0.2*inch))
        
        # Payment details table
        elements.append(Paragraph("Informations du Paiement", heading_style))
        
        payment_data = [
            ['Numéro de reçu:', f'REC_{payment.id}'],
            ['Montant:', f'{payment.amount} {payment.currency}'],
            ['Statut:', '✓ Payé' if payment.status == 'paid' else '⏳ En attente'],
            ['Date:', payment.created_at.strftime('%d/%m/%Y %H:%M') if payment.created_at else 'N/A'],
        ]
        
        payment_table = Table(payment_data, colWidths=[2*inch, 4*inch])
        payment_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.black),
            ('TEXTCOLOR', (1, 0), (1, -1), colors.HexColor('#0066cc')),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.HexColor('#f0f0f0')]),
        ]))
        elements.append(payment_table)
        elements.append(Spacer(1, 0.2*inch))
        
        # Vehicle information
        elements.append(Paragraph("Informations du Véhicule", heading_style))
        
        vehicle_data = [
            ['Immatriculation:', payment.license_plate],
            ['Propriétaire:', payment.owner_name],
        ]
        
        vehicle_table = Table(vehicle_data, colWidths=[2*inch, 4*inch])
        vehicle_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.black),
            ('TEXTCOLOR', (1, 0), (1, -1), colors.HexColor('#0066cc')),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.HexColor('#f0f0f0')]),
        ]))
        elements.append(vehicle_table)
        elements.append(Spacer(1, 0.2*inch))
        
        # Payer information
        elements.append(Paragraph("Informations du Payeur", heading_style))
        
        payer_data = [
            ['Nom:', payment.payer_name or 'N/A'],
        ]
        
        if payment.payer_email:
            payer_data.append(['Email:', payment.payer_email])
        if payment.phone_number:
            payer_data.append(['Téléphone:', payment.phone_number])
        
        payer_table = Table(payer_data, colWidths=[2*inch, 4*inch])
        payer_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.black),
            ('TEXTCOLOR', (1, 0), (1, -1), colors.HexColor('#0066cc')),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.HexColor('#f0f0f0')]),
        ]))
        elements.append(payer_table)
        elements.append(Spacer(1, 0.3*inch))
        
        # Generate QR code for verification
        try:
            import qrcode
            from io import BytesIO
            
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
                box_size=10,
                border=2,
            )
            qr.add_data(verify_url)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white")
            
            # Save QR code to BytesIO
            qr_buffer = BytesIO()
            qr_img.save(qr_buffer, format='PNG')
            qr_buffer.seek(0)
            
            # Add QR code section
            elements.append(Paragraph("Code de Vérification", heading_style))
            elements.append(Spacer(1, 0.1*inch))
            
            # Add QR code image (centered)
            from reportlab.platypus import Image
            
            qr_image = Image(qr_buffer, width=1.5*inch, height=1.5*inch)
            
            # Create a table to center the QR code
            qr_table = Table([[qr_image]], colWidths=[6*inch])
            qr_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            elements.append(qr_table)
            
            elements.append(Spacer(1, 0.1*inch))
            qr_note = ParagraphStyle(
                'QRNote',
                parent=styles['Normal'],
                fontSize=8,
                textColor=colors.grey,
                alignment=1  # Center
            )
            elements.append(Paragraph("Scannez ce code QR avec l'application policière pour vérifier l'authenticité de ce reçu", qr_note))
            elements.append(Spacer(1, 0.2*inch))
            
        except Exception as qr_error:
            print(f"QR code generation warning: {str(qr_error)}")
            # Continue without QR code if generation fails
            pass
        
        # Footer
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.grey,
            alignment=1  # Center
        )
        elements.append(Paragraph("Merci pour votre paiement!", footer_style))
        elements.append(Paragraph(f"Générée le {now_comoros().strftime('%d/%m/%Y à %H:%M')}", footer_style))
        
        # Build PDF
        doc.build(elements)
        pdf_buffer.seek(0)
        
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'recu_paiement_{payment.id}.pdf'
        )
        
    except Exception as e:
        print(f"PDF generation error: {str(e)}")
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

