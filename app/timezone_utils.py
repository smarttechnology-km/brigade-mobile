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


def ensure_comoros(dt):
    """Ensure a datetime is timezone-aware in Comoros timezone.

    - If dt is None: returns None
    - If dt.tzinfo is None: assume the datetime is already in Comoros local time
      and attach the Comoros timezone to it.
    - Otherwise convert to Comoros timezone.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Treat naive datetimes as local Comoros time and attach tzinfo
        return dt.replace(tzinfo=COMOROS_TZ)
    return dt.astimezone(COMOROS_TZ)
