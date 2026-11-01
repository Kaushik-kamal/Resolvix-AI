"""Authentication and authorization."""
import hmac
from dataclasses import dataclass
from typing import Optional

import bcrypt
from fastapi import Depends, Header, Cookie, HTTPException, status
from fastapi.security import HTTPBearer
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlalchemy.orm import Session

from .config import Settings
from .orm import User as UserDB


security = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    """Authenticated principal (service or user)."""
    kind: str  # "service" or "user"
    email: Optional[str] = None
    role: Optional[str] = None
    department: Optional[str] = None


def verify_service_key(x_service_key: Optional[str], settings: Settings) -> bool:
    """Verify X-Service-Key header against SERVICE_KEY."""
    if not x_service_key:
        return False
    return hmac.compare_digest(x_service_key, settings.service_key)


def decode_session_cookie(cookie_value: str, settings: Settings) -> Optional[dict]:
    """Decode and verify session cookie."""
    try:
        serializer = URLSafeTimedSerializer(settings.session_secret)
        data = serializer.loads(cookie_value, max_age=43200)  # 12 hours
        return data
    except (BadSignature, SignatureExpired):
        return None


def get_principal(
    x_service_key: Optional[str] = Header(None, alias="X-Service-Key"),
    resolvix_session: Optional[str] = Cookie(None),
    settings: Settings = Depends(lambda: None)  # Will be injected by app
) -> Principal:
    """Extract and verify authentication (service key or session cookie)."""
    # This will be replaced by the app factory with actual settings
    if settings is None:
        raise HTTPException(status_code=500, detail="Settings not configured")
    
    # Try service key first
    if verify_service_key(x_service_key, settings):
        return Principal(kind="service")
    
    # Try session cookie
    if resolvix_session:
        session_data = decode_session_cookie(resolvix_session, settings)
        if session_data:
            return Principal(
                kind="user",
                email=session_data.get("email"),
                role=session_data.get("role"),
                department=session_data.get("department")
            )
    
    # No valid auth
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required"
    )


def require_admin(principal: Principal = Depends(get_principal)) -> Principal:
    """Require admin role."""
    if principal.kind != "user" or principal.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,  # Using 403; will map to "unauthorized" in error handler
            detail="Admin access required"
        )
    return principal


def hash_password(password: str) -> str:
    """Hash a password with bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash."""
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_session_cookie(email: str, role: str, department: Optional[str], settings: Settings,
                          session_version: int = 0) -> str:
    """Create a signed session cookie. `sv` must match users.session_version on every request (logout revokes)."""
    serializer = URLSafeTimedSerializer(settings.session_secret)
    data = {"email": email, "role": role, "department": department, "sv": session_version}
    return serializer.dumps(data)
