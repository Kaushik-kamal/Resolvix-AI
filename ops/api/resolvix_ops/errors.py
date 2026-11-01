"""Error handling and ErrorEnvelope generation."""
from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from resolvix_contracts import ErrorEnvelope, ErrorBody


def validation_error_handler(request: Request, exc: RequestValidationError):
    """Handle Pydantic validation errors -> 422 validation_error envelope."""
    details = {str(i): str(err) for i, err in enumerate(exc.errors())}
    envelope = ErrorEnvelope(
        error=ErrorBody(
            code="validation_error",
            message="Request validation failed",
            retryable=False,
            details=details
        )
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=envelope.model_dump(mode="json")
    )


def http_exception_handler(request: Request, exc: Exception):
    """Handle HTTPException -> ErrorEnvelope."""
    from fastapi import HTTPException
    from starlette.exceptions import HTTPException as StarletteHTTPException
    
    if not isinstance(exc, (HTTPException, StarletteHTTPException)):
        return general_exception_handler(request, exc)
    
    # Map status codes to error codes per ErrorBody Literal
    # Allowed: "validation_error", "not_found", "conflict", "unauthorized", "rate_limited", "upstream_error", "timeout", "internal"
    code_map = {
        400: "validation_error",
        422: "validation_error",
        401: "unauthorized",
        403: "unauthorized",  # Contract has no "forbidden", use "unauthorized"
        404: "not_found",
        405: "not_found",  # Method not allowed -> not_found (closest match)
        409: "conflict",
        429: "rate_limited",
        502: "upstream_error",
        504: "timeout",
    }
    
    error_code = code_map.get(exc.status_code, "internal")
    retryable = exc.status_code in {429, 502, 504}
    
    envelope = ErrorEnvelope(
        error=ErrorBody(
            code=error_code,  # type: ignore
            message=str(exc.detail) if exc.detail else "An error occurred",
            retryable=retryable
        )
    )
    
    return JSONResponse(
        status_code=exc.status_code,
        content=envelope.model_dump(mode="json"),
        headers=getattr(exc, "headers", None),  # e.g. Retry-After on 429
    )


def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions -> 500 internal envelope (no stack trace)."""
    envelope = ErrorEnvelope(
        error=ErrorBody(
            code="internal",
            message="An internal error occurred",
            retryable=False
        )
    )
    
    # Log the exception for debugging, but don't expose it in the response
    import logging
    import traceback
    # type and frames only: the message of a database error can contain bound parameters (numbers, SMS text)
    logging.getLogger("resolvix_ops.errors").error(
        "Unhandled %s on %s %s\n%s", type(exc).__name__, request.method, request.url.path,
        "".join(traceback.format_tb(exc.__traceback__)))
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=envelope.model_dump(mode="json")
    )
