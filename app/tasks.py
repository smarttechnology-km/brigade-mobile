from app import db
from app.models import Fine, ExoneratedVehicle, Phone
from app.timezone_utils import now_comoros
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)

def process_exonerated_fines():
    """
    Process fines for exonerated vehicles that are older than 24 hours.
    Marks them as paid automatically.
    """
    try:
        # Get current time
        current_time = now_comoros()

        # Find all exonerated vehicles
        exonerated_vehicles = ExoneratedVehicle.query.all()
        exonerated_vehicle_ids = [ev.vehicle_id for ev in exonerated_vehicles]

        if not exonerated_vehicle_ids:
            logger.info("No exonerated vehicles found")
            return

        # Find unpaid fines for exonerated vehicles that are older than 24 hours
        cutoff_time = current_time - timedelta(hours=24)

        fines_to_process = Fine.query.filter(
            Fine.vehicle_id.in_(exonerated_vehicle_ids),
            Fine.paid == False,
            Fine.issued_at <= cutoff_time
        ).all()

        processed_count = 0
        for fine in fines_to_process:
            # Mark as paid
            fine.paid = True
            fine.paid_at = current_time
            fine.receipt_number = f"REC-AUTO-{fine.vehicle_id}-{int(current_time.timestamp())}"

            # Update notes to indicate automatic payment
            if "[EXONÉRÉ - Paiement automatique dans 24h]" in (fine.notes or ""):
                fine.notes = (fine.notes or "").replace(
                    "[EXONÉRÉ - Paiement automatique dans 24h]",
                    "[EXONÉRÉ - Payé automatiquement après 24h]"
                )
            else:
                fine.notes = f"{fine.notes or ''}\n[EXONÉRÉ - Payé automatiquement après 24h]".strip()

            processed_count += 1
            logger.info(f"Auto-paid fine ID {fine.id} for vehicle {fine.vehicle_id}")

        if processed_count > 0:
            db.session.commit()
            logger.info(f"Processed {processed_count} exonerated fines")
        else:
            logger.info("No fines to process")

    except Exception as e:
        logger.error(f"Error processing exonerated fines: {str(e)}")
        db.session.rollback()


def regenerate_phone_qr_codes():
    """
    Regenerate QR codes for all active phones daily (at 01:00 AM).
    Only regenerate phones that are NOT currently checked out.
    This prevents officers from taking a photo of the QR code and reusing it.
    But allows officers who have a phone checked out to keep using the same QR code until they return it.
    """
    try:
        # Get all active phones
        phones = Phone.query.filter_by(status='active').all()
        
        regenerated_count = 0
        skipped_count = 0
        
        for phone in phones:
            # Check if phone is currently checked out (has active usage)
            active_usage = PhoneUsage.query.filter_by(phone_id=phone.id, checkin_at=None).first()
            
            if active_usage:
                # Phone is currently borrowed - skip regeneration
                logger.info(f"Skipped QR regeneration for {phone.phone_code}: Currently checked out by {active_usage.user.username}")
                skipped_count += 1
            else:
                # Phone is not checked out - regenerate QR code
                old_qr = phone.qr_code_data
                phone.generate_qr_code()
                regenerated_count += 1
                logger.info(f"QR code regenerated for phone {phone.phone_code}: {old_qr} -> {phone.qr_code_data}")
        
        if regenerated_count > 0 or skipped_count > 0:
            db.session.commit()
            logger.info(f"QR code regeneration summary: Regenerated {regenerated_count}, Skipped {skipped_count} (checked out)")
        else:
            logger.info("No active phones to regenerate QR codes for")
    
    except Exception as e:
        logger.error(f"Error regenerating phone QR codes: {str(e)}")
        db.session.rollback()