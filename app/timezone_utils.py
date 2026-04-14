from datetime import datetime, timezone, timedelta

# Fuseau horaire des Comores (UTC+3)
COMOROS_TZ = timezone(timedelta(hours=3))

def now_comoros():
    """Retourne l'heure actuelle au fuseau horaire des Comores (UTC+3)"""
    return datetime.now(COMOROS_TZ)

def utc_to_comoros(dt):
    """Convertit un datetime UTC en fuseau horaire des Comores"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Si pas de timezone, assume UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(COMOROS_TZ)
