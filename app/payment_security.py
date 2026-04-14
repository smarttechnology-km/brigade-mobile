"""
Secure Payment Configuration Module for Flask Backend
Implements server-side security measures for payment processing
"""

import hmac
import hashlib
import json
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify, current_app
import logging

# Configure logging for security events
security_logger = logging.getLogger('security')

class PaymentSecurityConfig:
    """Configuration for payment security"""
    
    # Request signing
    SIGNATURE_ALGORITHM = 'SHA256'
    SIGNATURE_HEADER = 'X-Signature'
    TIMESTAMP_HEADER = 'X-Timestamp'
    MAX_TIMESTAMP_DELTA = 300  # 5 minutes
    
    # Request validation
    REQUIRE_CONTENT_TYPE = 'application/json'
    MAX_PAYLOAD_SIZE = 102400  # 100KB
    
    # Rate limiting
    RATE_LIMIT_WINDOW = 60  # 1 minute
    RATE_LIMIT_MAX_REQUESTS = 10
    
    # Session tokens
    SESSION_TOKEN_EXPIRY = 3600  # 1 hour
    
    # Fraud detection
    MAX_AMOUNT_PER_TRANSACTION = 1000000  # 1M KMF
    MAX_AMOUNT_PER_DAY = 5000000  # 5M KMF
    MAX_ATTEMPTS_PER_HOUR = 5
    
    # CORS
    ALLOWED_ORIGINS = [
        'http://localhost:8081',
        'https://app.police-app.com',
    ]


class RequestValidator:
    """Validate incoming requests for security"""
    
    @staticmethod
    def validate_signature(request_data, signature, timestamp, secret=None):
        """
        Validate HMAC signature of request
        
        Args:
            request_data: Request body as string
            signature: Signature from X-Signature header
            timestamp: Timestamp from X-Timestamp header
            secret: Secret key for HMAC (from config)
        
        Returns:
            bool: True if signature is valid
        """
        if not secret:
            secret = current_app.config.get('PAYMENT_SECRET_KEY', 'default-secret')
        
        try:
            # Verify timestamp is recent
            request_timestamp = int(timestamp)
            current_timestamp = int(datetime.utcnow().timestamp())
            
            if abs(current_timestamp - request_timestamp) > PaymentSecurityConfig.MAX_TIMESTAMP_DELTA:
                security_logger.warning(f"Request timestamp too old: {request_timestamp}")
                return False
            
            # Generate expected signature
            message = f"{request_data}{timestamp}"
            expected_signature = hmac.new(
                secret.encode(),
                message.encode(),
                hashlib.sha256
            ).hexdigest()
            
            # Compare signatures (timing-safe comparison)
            return hmac.compare_digest(signature, expected_signature)
        
        except Exception as e:
            security_logger.error(f"Signature validation error: {str(e)}")
            return False
    
    @staticmethod
    def validate_content_type(request):
        """Validate Content-Type header"""
        content_type = request.headers.get('Content-Type', '')
        if not content_type.startswith(PaymentSecurityConfig.REQUIRE_CONTENT_TYPE):
            return False
        return True
    
    @staticmethod
    def validate_payload_size(request):
        """Validate request payload size"""
        content_length = request.content_length
        if content_length and content_length > PaymentSecurityConfig.MAX_PAYLOAD_SIZE:
            return False
        return True
    
    @staticmethod
    def validate_origin(request):
        """Validate request origin for CORS"""
        origin = request.headers.get('Origin', '')
        if origin and origin not in PaymentSecurityConfig.ALLOWED_ORIGINS:
            security_logger.warning(f"Request from unauthorized origin: {origin}")
            return False
        return True


class FraudDetection:
    """Detect fraudulent payment attempts"""
    
    @staticmethod
    def validate_transaction(amount, user_id, payment_history=None):
        """
        Validate transaction against fraud thresholds
        
        Returns:
            dict: {
                'valid': bool,
                'score': int (0-100),
                'errors': [str]
            }
        """
        errors = []
        
        # Check single transaction limit
        if amount > PaymentSecurityConfig.MAX_AMOUNT_PER_TRANSACTION:
            errors.append(f"Transaction exceeds maximum: {PaymentSecurityConfig.MAX_AMOUNT_PER_TRANSACTION} KMF")
        
        # Check daily limit
        if payment_history:
            today = datetime.utcnow().date()
            daily_total = sum(
                p['amount'] for p in payment_history 
                if p['created_at'].date() == today
            )
            if daily_total + amount > PaymentSecurityConfig.MAX_AMOUNT_PER_DAY:
                errors.append(f"Daily limit exceeded: {PaymentSecurityConfig.MAX_AMOUNT_PER_DAY} KMF")
        
        # Check hourly attempts
        if payment_history:
            one_hour_ago = datetime.utcnow() - timedelta(hours=1)
            recent_attempts = [
                p for p in payment_history 
                if p['created_at'] > one_hour_ago
            ]
            if len(recent_attempts) >= PaymentSecurityConfig.MAX_ATTEMPTS_PER_HOUR:
                errors.append(f"Too many attempts. Max {PaymentSecurityConfig.MAX_ATTEMPTS_PER_HOUR} per hour")
        
        # Calculate risk score
        risk_score = FraudDetection.calculate_risk_score(amount, payment_history)
        
        return {
            'valid': len(errors) == 0,
            'score': risk_score,
            'errors': errors
        }
    
    @staticmethod
    def calculate_risk_score(amount, payment_history=None):
        """
        Calculate fraud risk score (0-100)
        Higher score = higher risk
        """
        score = 0
        
        # Amount-based risk
        amount_ratio = amount / PaymentSecurityConfig.MAX_AMOUNT_PER_TRANSACTION
        score += min(amount_ratio * 30, 30)
        
        # Time-based risk (midnight-6am)
        hour = datetime.utcnow().hour
        if hour < 6 or hour > 23:
            score += 15
        
        # Velocity-based risk
        if payment_history:
            now = datetime.utcnow()
            last_hour = [p for p in payment_history 
                        if p['created_at'] > now - timedelta(hours=1)]
            
            if len(last_hour) > 2:
                score += 25
        
        return min(int(score), 100)


def require_secure_signature(f):
    """
    Decorator to require valid request signature
    Used on sensitive payment endpoints
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check Content-Type
        if not RequestValidator.validate_content_type(request):
            return jsonify({'error': 'Invalid Content-Type'}), 400
        
        # Check payload size
        if not RequestValidator.validate_payload_size(request):
            return jsonify({'error': 'Payload too large'}), 413
        
        # Check origin (if present)
        if request.origin and not RequestValidator.validate_origin(request):
            return jsonify({'error': 'Unauthorized origin'}), 403
        
        # Check signature for POST/PUT/PATCH
        if request.method in ['POST', 'PUT', 'PATCH']:
            signature = request.headers.get(PaymentSecurityConfig.SIGNATURE_HEADER)
            timestamp = request.headers.get(PaymentSecurityConfig.TIMESTAMP_HEADER)
            
            if not signature or not timestamp:
                security_logger.warning(f"Missing signature or timestamp from {request.remote_addr}")
                return jsonify({'error': 'Missing security headers'}), 401
            
            request_data = request.get_data(as_text=True)
            if not RequestValidator.validate_signature(request_data, signature, timestamp):
                security_logger.warning(f"Invalid signature from {request.remote_addr}")
                return jsonify({'error': 'Invalid signature'}), 401
        
        return f(*args, **kwargs)
    
    return decorated_function


def validate_payment_data(f):
    """
    Decorator to validate payment data
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not request.is_json:
            return jsonify({'error': 'Request must be JSON'}), 400
        
        data = request.get_json()
        errors = []
        
        # Validate fines
        if 'fines' not in data or not isinstance(data['fines'], list) or not data['fines']:
            errors.append('Invalid or missing fines')
        
        # Validate payer name
        if 'payer_name' not in data or not data['payer_name']:
            errors.append('Missing payer name')
        else:
            name = data['payer_name'].strip()
            if len(name) < 2 or len(name) > 100:
                errors.append('Payer name must be 2-100 characters')
        
        # Validate email if provided
        if 'payer_email' in data and data['payer_email']:
            email = data['payer_email']
            if '@' not in email or '.' not in email.split('@')[1]:
                errors.append('Invalid email format')
        
        if errors:
            return jsonify({'error': 'Validation failed', 'details': errors}), 400
        
        return f(*args, **kwargs)
    
    return decorated_function


# Response security decorators
def add_security_headers(response):
    """Add security headers to all responses"""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = "default-src 'self'"
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    return response


def sanitize_response_data(data):
    """
    Remove sensitive data from responses
    Never expose internal IDs, system details, etc.
    """
    if isinstance(data, dict):
        # Remove sensitive fields
        sensitive_fields = ['password', 'secret', 'token', 'api_key', 'internal_id']
        return {
            k: sanitize_response_data(v) 
            for k, v in data.items() 
            if k not in sensitive_fields
        }
    elif isinstance(data, list):
        return [sanitize_response_data(item) for item in data]
    
    return data


# Database encryption
class EncryptedField:
    """SQLAlchemy field type for encrypted data"""
    
    def __init__(self, encryption_key=None):
        self.encryption_key = encryption_key or current_app.config.get('ENCRYPTION_KEY')
    
    def encrypt(self, data):
        """Encrypt data before storing"""
        # Implementation depends on chosen encryption library
        # Example: from cryptography.fernet import Fernet
        pass
    
    def decrypt(self, data):
        """Decrypt data when retrieving"""
        pass


# Session management
class SecureSession:
    """Manage secure session tokens for payments"""
    
    SESSION_STORAGE = {}  # In production: use Redis
    
    @staticmethod
    def create_session_token(user_id, payment_id):
        """Create a new session token"""
        import uuid
        import time
        
        token = str(uuid.uuid4())
        expiry = time.time() + PaymentSecurityConfig.SESSION_TOKEN_EXPIRY
        
        SecureSession.SESSION_STORAGE[token] = {
            'user_id': user_id,
            'payment_id': payment_id,
            'expires_at': expiry,
            'created_at': time.time()
        }
        
        return token
    
    @staticmethod
    def validate_session_token(token):
        """Validate session token"""
        import time
        
        if token not in SecureSession.SESSION_STORAGE:
            return False
        
        session = SecureSession.SESSION_STORAGE[token]
        
        if session['expires_at'] < time.time():
            del SecureSession.SESSION_STORAGE[token]
            return False
        
        return True
    
    @staticmethod
    def revoke_session_token(token):
        """Revoke a session token"""
        if token in SecureSession.SESSION_STORAGE:
            del SecureSession.SESSION_STORAGE[token]


# Audit logging
class PaymentAuditLog:
    """Log security-relevant events for payments"""
    
    @staticmethod
    def log_payment_attempt(payment_id, user_id, amount, status):
        """Log payment attempt"""
        security_logger.info(
            f"Payment attempt: payment_id={payment_id}, user_id={user_id}, "
            f"amount={amount}, status={status}"
        )
    
    @staticmethod
    def log_fraud_detection(payment_id, user_id, reason, risk_score):
        """Log suspected fraud"""
        security_logger.warning(
            f"Fraud detected: payment_id={payment_id}, user_id={user_id}, "
            f"reason={reason}, risk_score={risk_score}"
        )
    
    @staticmethod
    def log_failed_signature(remote_addr, endpoint):
        """Log failed signature validation"""
        security_logger.warning(
            f"Failed signature validation from {remote_addr} on {endpoint}"
        )
