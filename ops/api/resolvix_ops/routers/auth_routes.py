"""Authentication routes."""
from fastapi import APIRouter, Depends, HTTPException, Request, status, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import hash_password, verify_password, create_session_cookie
from ..audit import write_audit
from ..config import Settings
from ..deps import get_db, get_settings, get_principal, Principal
from ..orm import User

router = APIRouter(prefix="/v1/auth", tags=["auth"])

SESSION_MAX_AGE_S = 12 * 3600
_DUMMY_HASH = hash_password("not-a-real-password")  # compared against when the email is unknown


class LoginRequest(BaseModel):
    """Login request (not in contracts, local model). Length caps keep audit rows and bcrypt input bounded."""
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


class LoginResponse(BaseModel):
    """Login response (not in contracts, local model)."""
    success: bool
    email: str


class MeResponse(BaseModel):
    """Current user response (additive extension)."""
    email: str
    role: str
    department: str | None


@router.post("/login", response_model=LoginResponse)
def login(
    http_request: Request,
    request: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    """Authenticate user and set session cookie.

    A plain def (threadpool): bcrypt and SQLite must not block the event loop that serves the SSE streams.
    Rate limit (429 rate_limited): FAILED attempts per (client IP, email), plus a looser cap on all attempts per IP.
    """
    client_ip = http_request.client.host if http_request.client else "unknown"
    pair_key = f"{client_ip}|{request.email.strip().lower()}"
    limiter = http_request.app.state.login_limiter
    ip_limiter = http_request.app.state.login_ip_limiter
    if not limiter.peek(pair_key) or not ip_limiter.allow(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts; try again in a minute",
            headers={"Retry-After": str(max(limiter.retry_after(pair_key), 1))},
        )
    user = db.query(User).filter(User.email == request.email).first()

    # always run one bcrypt comparison so an unknown email costs the same as a wrong password
    password_ok = verify_password(request.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not password_ok:
        limiter.hit(pair_key)
        write_audit(db, request.email[:254], "login_failed", "user", request.email[:254])
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )

    cookie_value = create_session_cookie(user.email, user.role, user.department, settings, user.session_version)
    response.set_cookie(
        key="resolvix_session",
        value=cookie_value,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=SESSION_MAX_AGE_S,
        path="/"
    )

    write_audit(db, user.email, "login_success", "user", user.email)

    return LoginResponse(success=True, email=user.email)


@router.get("/me", response_model=MeResponse)
async def get_current_user(principal: Principal = Depends(get_principal)):
    """Get current user info (additive extension)."""
    if principal.kind != "user":
        raise HTTPException(status_code=401, detail="User session required")
    
    return MeResponse(
        email=principal.email or "",
        role=principal.role or "",
        department=principal.department
    )


@router.post("/logout")
def logout(response: Response, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """End the session (additive extension): the cookie is cleared AND invalidated server side, so a copied
    cookie stops working (the session_version of the user is bumped; other devices of that user are logged out too)."""
    if principal.kind == "user":
        user = db.query(User).filter(User.email == principal.email).first()
        if user is not None:
            user.session_version = (user.session_version or 0) + 1
            write_audit(db, user.email, "logout", "user", user.email, commit=False)
            db.commit()
    response.delete_cookie(key="resolvix_session", path="/")
    return {"success": True}
