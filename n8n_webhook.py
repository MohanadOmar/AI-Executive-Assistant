"""Inbound webhooks from n8n."""
import os
from fastapi import APIRouter, Request, Header, HTTPException

from tools import send_sms_to_mohanad, MOHANAD_PHONE
from agent import run_agent
from system_prompts import get_sms_system_prompt

router = APIRouter()


def _check_auth(api_key: str):
    expected = os.environ.get("N8N_INCOMING_SECRET", "")
    if not expected or api_key != expected:
        raise HTTPException(401, "Unauthorized")


@router.post("/notify")
async def n8n_notify(request: Request, x_api_key: str = Header(None)):
    """n8n sends a pre-formatted SMS. Body: { "message": "..." }"""
    _check_auth(x_api_key)
    data = await request.json()
    message = (data.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "Missing 'message' field")
    print(f"[n8n notify] {message[:120]}...")
    result = send_sms_to_mohanad(message)
    return {"success": True, "sid": result.get("sid")}


@router.post("/dodo")
async def n8n_via_dodo(request: Request, x_api_key: str = Header(None)):
    """n8n hands Dodo raw data, Dodo writes the SMS. Body: { "context": "..." }"""
    _check_auth(x_api_key)
    data = await request.json()
    context = (data.get("context") or "").strip()
    if not context:
        raise HTTPException(400, "Missing 'context' field")

    print(f"[n8n dodo] Context: {context[:200]}...")
    instruction = (
        f"The following data just came in from an n8n workflow. "
        f"Send Mohanad a short, natural SMS summary using send_sms. "
        f"Do not paste the raw data verbatim.\n\nDATA:\n{context}"
    )

    try:
        reply = run_agent(
            user_message=instruction,
            system_prompt=get_sms_system_prompt(),
            phone_number=MOHANAD_PHONE,
        )
        return {"success": True, "dodo_reply": reply}
    except Exception as e:
        print(f"[n8n dodo error] {e}")
        send_sms_to_mohanad(context[:1000])
        return {"success": False, "error": str(e), "fallback": "raw context sent"}
