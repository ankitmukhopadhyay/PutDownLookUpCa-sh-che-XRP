import math
import time


def haversine_feet(lat1, lon1, lat2, lon2):
    """Calculate distance between two GPS coordinates in feet."""
    R_feet = 20925524.9  # Earth mean radius in feet
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R_feet * math.asin(math.sqrt(a))


def validate_checkin(user_lat, user_lon, event_lat, event_lon, scheduled_time,
                     radius_feet=300, window_minutes=31):
    """
    Validate a GPS check-in against event location and scheduled time window.

    The 31-minute window opens at scheduled_time (not creation time).

    Returns:
        (valid: bool, reason: str, distance_ft: int, elapsed_min: float)
    """
    distance_ft = haversine_feet(user_lat, user_lon, event_lat, event_lon)
    elapsed_min = (time.time() - scheduled_time) / 60

    if elapsed_min < 0:
        mins_until = round(-elapsed_min, 1)
        return False, f"Event hasn't started yet ({mins_until} min to go)", round(distance_ft), round(elapsed_min, 1)

    if elapsed_min > window_minutes:
        return False, f"Check-in window closed ({window_minutes}-min window has expired)", round(distance_ft), round(elapsed_min, 1)

    if distance_ft > radius_feet:
        return False, f"Too far from venue ({round(distance_ft)}ft away, max {radius_feet}ft)", round(distance_ft), round(elapsed_min, 1)

    return True, f"Valid! {round(distance_ft)}ft from venue, {round(elapsed_min, 1)} min into window", round(distance_ft), round(elapsed_min, 1)
