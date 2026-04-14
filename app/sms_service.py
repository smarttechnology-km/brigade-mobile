"""
Enhanced SMS service with logging history
"""
from datetime import datetime
from app.timezone_utils import now_comoros

class SMSService:
    def __init__(self):
        # Configuration placeholders - replace with real credentials in production
        self.api_key = None  # e.g., Twilio Account SID
        self.api_secret = None  # e.g., Twilio Auth Token
        self.sender_number = None  # e.g., +269XXXXXXXX
        self.enabled = False  # Set to True when credentials are configured
        self.sms_history = []  # Store SMS history for debugging
    
    def send_sms(self, to_number, message):
        """
        Send SMS notification
        
        Args:
            to_number (str): Phone number in format +269XXXXXXXX
            message (str): SMS content
        
        Returns:
            dict: {'success': bool, 'message': str}
        """
        if not to_number:
            print(f"\n⚠️  SMS ERROR: No recipient phone number provided")
            return {'success': False, 'message': 'No phone number provided'}
        
        # Log to history
        sms_log = {
            'timestamp': now_comoros(),
            'to': to_number,
            'message': message,
            'status': 'simulated' if not self.enabled else 'sent'
        }
        self.sms_history.append(sms_log)
        
        # Keep only last 100 SMS in history
        if len(self.sms_history) > 100:
            self.sms_history = self.sms_history[-100:]
        
        if not self.enabled:
            # Log message instead of sending (development mode)
            print(f"\n{'='*70}")
            print(f"📱 SMS NOTIFICATION #{len(self.sms_history)} (MODE SIMULATION)")
            print(f"{'='*70}")
            print(f"Destinataire: {to_number}")
            print(f"Horodatage: {sms_log['timestamp'].strftime('%d/%m/%Y à %H:%M:%S')}")
            print(f"{'─'*70}")
            print(f"Message:")
            print(message)
            print(f"{'='*70}\n")
            return {'success': True, 'message': 'SMS simulé - message affiché dans les logs'}
        
        # TODO: Replace with real SMS API implementation
        # Example for Twilio:
        # from twilio.rest import Client
        # client = Client(self.api_key, self.api_secret)
        # try:
        #     msg = client.messages.create(
        #         body=message,
        #         from_=self.sender_number,
        #         to=to_number
        #     )
        #     sms_log['status'] = 'sent'
        #     sms_log['sid'] = msg.sid
        #     return {'success': True, 'message': f'SMS sent: {msg.sid}'}
        # except Exception as e:
        #     sms_log['status'] = 'failed'
        #     sms_log['error'] = str(e)
        #     return {'success': False, 'message': str(e)}
        
        print(f"\n⚠️  SMS API not configured - SMS would be sent to: {to_number}")
        return {'success': False, 'message': 'SMS API not configured'}
    
    def send_fine_notification(self, vehicle, fine):
        """
        Send SMS notification when a fine is issued
        
        Args:
            vehicle: Vehicle model instance
            fine: Fine model instance
        
        Returns:
            dict: {'success': bool, 'message': str}
        """
        # Check if vehicle has owner_phone
        if not hasattr(vehicle, 'owner_phone') or not vehicle.owner_phone:
            print(f"\n⚠️  SMS NOT SENT: No phone number registered for vehicle {vehicle.license_plate}")
            return {'success': False, 'message': 'No phone number registered for this vehicle'}
        
        # Format phone number if needed
        phone = vehicle.owner_phone.strip()
        if not phone:
            print(f"\n⚠️  SMS NOT SENT: Empty phone number for vehicle {vehicle.license_plate}")
            return {'success': False, 'message': 'Empty phone number'}
        
        message = (
            f"🚔 Police des Comores\n\n"
            f"Une nouvelle amende a été émise pour le véhicule {vehicle.license_plate}.\n\n"
            f"Raison: {fine.reason}\n"
            f"Montant: {fine.amount:,.0f} KMF\n"
            f"Date: {fine.issued_at.strftime('%d/%m/%Y à %H:%M')}\n\n"
            f"Pour payer, utilisez votre numéro d'immatriculation: {vehicle.license_plate}\n\n"
            f"Merci de régler cette amende rapidement."
        )
        
        return self.send_sms(phone, message)
    
    def get_sms_history(self, limit=20):
        """
        Get recent SMS history
        
        Args:
            limit (int): Number of recent SMS to return
        
        Returns:
            list: Recent SMS logs
        """
        return self.sms_history[-limit:]


# Create singleton instance
sms_service = SMSService()
