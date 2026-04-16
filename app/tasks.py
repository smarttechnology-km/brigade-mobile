from app import db
from app.models import Fine, ExoneratedVehicle, Phone, VehicleHistory, PhoneUsage
from app.timezone_utils import now_comoros
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)

def process_exonerated_fines():
    """
    Delete fines for exonerated vehicles that are older than 60 minutes.
    Removes all traces from the system - no history, no record, completely deleted.
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

        # Find unpaid fines for exonerated vehicles that are older than 60 minutes
        cutoff_time = current_time - timedelta(minutes=60)

        fines_to_delete = Fine.query.filter(
            Fine.vehicle_id.in_(exonerated_vehicle_ids),
            Fine.paid == False,
            Fine.issued_at <= cutoff_time
        ).all()

        deleted_count = 0
        for fine in fines_to_delete:
            fine_id = fine.id
            vehicle_id = fine.vehicle_id
            
            # Delete related history records to remove all traces
            VehicleHistory.query.filter(
                VehicleHistory.vehicle_id == vehicle_id,
                VehicleHistory.action.contains(f"Amende")
            ).delete()
            
            # Delete the fine itself
            db.session.delete(fine)
            deleted_count += 1
            logger.info(f"Deleted fine ID {fine_id} for exonerated vehicle {vehicle_id} (60+ minutes old)")

        if deleted_count > 0:
            db.session.commit()
            logger.info(f"Deleted {deleted_count} exonerated fines with all traces removed")
        else:
            logger.info("No fines to delete")

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