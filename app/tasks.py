from app import db
from app.models import Fine, ExoneratedVehicle, Phone, VehicleHistory, PhoneUsage, Vehicle
from app.timezone_utils import now_comoros
from datetime import timedelta
import logging
from flask import current_app

logger = logging.getLogger(__name__)

# Global reference to app instance
_app = None

def set_app(app):
    """Set the app instance for use in background tasks"""
    global _app
    _app = app

def get_app():
    """Get the app instance, preferring current_app if in context, otherwise global"""
    try:
        return current_app._get_current_object()
    except RuntimeError:
        return _app

def process_exonerated_fines():
    """
    Delete fines for exonerated vehicles that are older than 60 minutes.
    Removes all traces from the system - no history, no record, completely deleted.
    """
    app = get_app()
    with app.app_context():
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
    app = get_app()
    with app.app_context():
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


def check_vehicle_qr_code_expiry():
    """
    Check for vehicles with expired QR codes and mark them as inactive.
    Runs daily (at 02:00 AM).
    
    This task:
    - Finds all vehicles with expired QR codes
    - Changes their status to 'inactive'
    - Logs the action in vehicle history
    """
    app = get_app()
    with app.app_context():
        try:
            current_time = now_comoros()
            
            # Find all active vehicles with expired QR codes
            expired_vehicles = Vehicle.query.filter(
                Vehicle.status == 'active',
                Vehicle.qr_code_expiry.isnot(None),
                Vehicle.qr_code_expiry <= current_time
            ).all()
            
            deactivated_count = 0
            
            for vehicle in expired_vehicles:
                old_status = vehicle.status
                vehicle.status = 'inactive'
                
                # Log the status change in vehicle history
                history = VehicleHistory(
                    vehicle_id=vehicle.id,
                    action=f"QR Code Expired - Auto-deactivated vehicle (QR cost expiry: {vehicle.qr_code_expiry.strftime('%Y-%m-%d %H:%M')})",
                    officer="SYSTEM",
                    notes=f"Vehicle automatically marked as inactive due to expired QR code"
                )
                db.session.add(history)
                
                deactivated_count += 1
                logger.info(f"Vehicle {vehicle.license_plate} marked as inactive due to expired QR code (expiry: {vehicle.qr_code_expiry.strftime('%Y-%m-%d')})")
            
            if deactivated_count > 0:
                db.session.commit()
                logger.info(f"Checked vehicle QR code expiry: Deactivated {deactivated_count} vehicles with expired QR codes")
            else:
                logger.info("No vehicles with expired QR codes found")
        
        except Exception as e:
            logger.error(f"Error checking vehicle QR code expiry: {str(e)}")
            db.session.rollback()


def send_expiry_notifications():
    """
    Daily job (08:00 AM) that sends push notifications to citizens for:
    - Vignette expiring in 30, 7, 1 day(s) or expired today
    - Vignette renewal period just opened (sent once on opening day)
    - Insurance expiring in 30, 7, 1 day(s) or today

    Only vehicles linked to a VehicleOwner (citizen app account) receive notifications.
    Thresholds are checked by exact day count to avoid duplicate notifications.
    """
    app = get_app()
    with app.app_context():
        try:
            from app.models import VehicleOwner
            from app.push_notifications import (
                send_vignette_expiry_notification,
                send_vignette_renewal_notification,
                send_insurance_expiry_notification,
            )
            from app.timezone_utils import ensure_comoros

            # Only consider vehicles that have a registered citizen account with a push token
            owners_with_token = VehicleOwner.query.filter(
                VehicleOwner.expo_push_token.isnot(None),
                VehicleOwner.expo_push_token != ''
            ).all()

            vehicle_ids = {o.vehicle_id for o in owners_with_token}
            if not vehicle_ids:
                logger.info("No vehicles with push tokens — skipping expiry notifications")
                return

            vehicles = Vehicle.query.filter(Vehicle.id.in_(vehicle_ids)).all()
            now = ensure_comoros(now_comoros())
            today = now.date()

            # Check if renewal period opened today
            try:
                from app.routes import get_renewal_opening_datetime
                renewal_opening = get_renewal_opening_datetime()
                renewal_opened_today = (
                    renewal_opening is not None
                    and ensure_comoros(renewal_opening).date() == today
                )
            except Exception:
                renewal_opened_today = False

            VIGNETTE_THRESHOLDS = {30, 7, 1, 0}
            INSURANCE_THRESHOLDS = {30, 7, 1, 0}

            notified = 0
            for vehicle in vehicles:
                # --- Vignette notifications ---
                if vehicle.vignette_expiry:
                    try:
                        expiry_date = ensure_comoros(vehicle.vignette_expiry).date()
                        days_until = (expiry_date - today).days
                        if days_until in VIGNETTE_THRESHOLDS or days_until < 0:
                            send_vignette_expiry_notification(vehicle, days_until)
                            notified += 1
                            logger.info(f"Vignette expiry notif → {vehicle.license_plate} (days={days_until})")
                    except Exception as e:
                        logger.warning(f"Vignette expiry notif failed for {vehicle.license_plate}: {e}")

                # --- Vignette renewal period opened today ---
                if renewal_opened_today and vehicle.vignette_expiry:
                    try:
                        send_vignette_renewal_notification(vehicle)
                        notified += 1
                        logger.info(f"Vignette renewal notif → {vehicle.license_plate}")
                    except Exception as e:
                        logger.warning(f"Vignette renewal notif failed for {vehicle.license_plate}: {e}")

                # --- Insurance notifications ---
                if vehicle.insurance_expiry:
                    try:
                        expiry_date = ensure_comoros(vehicle.insurance_expiry).date()
                        days_until = (expiry_date - today).days
                        if days_until in INSURANCE_THRESHOLDS:
                            send_insurance_expiry_notification(vehicle, days_until)
                            notified += 1
                            logger.info(f"Insurance expiry notif → {vehicle.license_plate} (days={days_until})")
                    except Exception as e:
                        logger.warning(f"Insurance expiry notif failed for {vehicle.license_plate}: {e}")

            logger.info(f"Expiry notifications job complete — {notified} notification(s) sent")

        except Exception as e:
            logger.error(f"Error in send_expiry_notifications: {e}")
            import traceback
            traceback.print_exc()


def apply_fine_late_rates():
    """
    Daily job (09:00) — for every unpaid fine, check how many full months have
    elapsed since issue and apply the matching FineLateRate percentage to the
    base_amount.  Only the highest matching rule is applied (not cumulative).
    """
    app = get_app()
    with app.app_context():
        try:
            from app.models import FineLateRate
            from app.timezone_utils import ensure_comoros

            rates = FineLateRate.query.order_by(FineLateRate.months.desc()).all()
            if not rates:
                logger.info("No FineLateRate rules configured — skipping")
                return

            unpaid_fines = Fine.query.filter_by(paid=False).all()
            now = ensure_comoros(now_comoros())
            updated = 0

            for fine in unpaid_fines:
                if not fine.issued_at:
                    continue

                issued = ensure_comoros(fine.issued_at)
                # Full months elapsed (approximate: 30 days = 1 month)
                months_elapsed = int((now - issued).days // 30)
                if months_elapsed < 1:
                    continue

                # Ensure base_amount is set (backfill guard)
                if not fine.base_amount:
                    fine.base_amount = fine.amount

                # Find the highest matching rule
                applicable = next(
                    (r for r in rates if r.months <= months_elapsed), None
                )
                if not applicable:
                    continue

                # Cumulative: +Y% per month elapsed (e.g. 50%/month × 2 months = +100%)
                new_amount = round(float(fine.base_amount) * (1 + float(applicable.percentage) / 100 * months_elapsed), 2)
                if abs(float(fine.amount) - new_amount) >= 0.01:
                    fine.amount = new_amount
                    updated += 1

            db.session.commit()
            logger.info(f"apply_fine_late_rates: updated {updated} fine(s)")

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error in apply_fine_late_rates: {e}")
