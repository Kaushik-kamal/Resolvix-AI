"""SMS routes: POST /v1/notifications/sms (contract) and POST /v1/notifications/sms/status (additive Twilio callback)."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status as http_status
from resolvix_contracts import SmsRequest
from starlette.concurrency import run_in_threadpool
from twilio.request_validator import RequestValidator

from ..deps import Principal, get_principal, system_principal

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/notifications", tags=["notifications"])

STATUS_CALLBACK_PATH = "/v1/notifications/sms/status"


@router.post("/sms", status_code=202)
def queue_sms(
    request: Request,
    response: Response,
    body: SmsRequest,
    principal: Principal = Depends(system_principal),
):
    """Queue an SMS (A). 202 + SmsResult for a new request (also when policy suppresses it),
    200 + the stored SmsResult for a repeated idempotency_key (nothing is sent again)."""
    result, is_new = request.app.state.sms.submit(body)
    if not is_new:
        response.status_code = http_status.HTTP_200_OK
    return result.model_dump(mode="json")


@router.post("/sms/status")
async def twilio_status_callback(request: Request):
    """Twilio delivery-status webhook. Public (Twilio has no service key) but only accepted with a valid
    X-Twilio-Signature computed with our auth token over the configured public URL; otherwise 403."""
    settings = request.app.state.settings
    signature = request.headers.get("X-Twilio-Signature", "")
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}
    url = f"{settings.ops_public_url.rstrip('/')}{STATUS_CALLBACK_PATH}"

    valid = (
        settings.sms_mode == "twilio"
        and bool(settings.twilio_auth_token)
        and bool(signature)
        and RequestValidator(settings.twilio_auth_token).validate(url, params, signature)
    )
    if not valid:
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="Invalid Twilio signature")

    sid = params.get("MessageSid") or params.get("SmsSid")
    message_status = params.get("MessageStatus") or params.get("SmsStatus")
    if sid and message_status:
        await run_in_threadpool(
            request.app.state.sms.apply_provider_status, sid, message_status, params.get("ErrorCode"))
    return {"status": "ok"}
