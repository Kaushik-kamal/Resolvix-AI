"""Privacy utilities for masking sensitive data."""


def mask_number(number: str | None) -> str | None:
    """Mask a phone number for privacy.
    
    Format: first 3 characters + "•••••" + last 4 characters
    Example: "+919876540002" -> "+91•••••0002"
    
    Returns "•••" for anything shorter than 8 characters.
    Returns None for None input.
    """
    if number is None:
        return None
    
    if len(number) < 8:
        return "•••"
    
    return number[:3] + "•••••" + number[-4:]
