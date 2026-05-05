"""Inbound webhooks from n8n."""
import os
from openai import OpenAI
from fastapi import APIRouter, Request, Header, HTTPException

from tools import send_sms_to_mohanad

router = APIRouter()


def _check_auth(api_key: str):
    expected = os.environ.get("N8N_INCOMING_SECRET", "")
    if not expected or api_key != expected:
        raise HTTPException(401, "Unauthorized")


@router.post("/notify")
async def n8n_notify(request: Request, x_api_key: str = Header(None)):
    """Pre-formatted SMS — n8n writes the message, Dodo just sends it.
    Body: { "message": "..." }
    """
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
    """Dodo summarizes raw data into a natural SMS, then sends it. No confirmation.
    Body: { "context": "..." }
    """
    _check_auth(x_api_key)
    data = await request.json()
    context = (data.get("context") or "").strip()
    if not context:
        raise HTTPException(400, "Missing 'context' field")

    print(f"[n8n dodo] Context: {context[:200]}...")

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    summary_prompt = (
        "You are Dodo, an AI assistant for Mohanad. You just received data from an "
        "automated workflow. Write a SHORT, natural SMS to Mohanad summarizing what "
        "matters. Plain text only — no markdown, no lists, no 'Subject:' patterns. "
        "Under 320 characters. Just the message text, nothing else (no preamble, "
        "no 'Here's the SMS:', no quotes around it)."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": summary_prompt},
                {"role": "user", "content": f"DATA FROM WORKFLOW:\n{context}"},
            ],
        )
        sms_text = (response.choices[0].message.content or "").strip()
        if sms_text.startswith('"') and sms_text.endswith('"'):
            sms_text = sms_text[1:-1]

        print(f"[n8n dodo] Composed SMS: {sms_text}")
        sms_result = send_sms_to_mohanad(sms_text)
        return {"success": True, "sms_text": sms_text, "sid": sms_result.get("sid")}

    except Exception as e:
        print(f"[n8n dodo error] {e}")
        fallback = context[:300]
        try:
            send_sms_to_mohanad(fallback)
            return {"success": False, "error": str(e), "fallback_sent": True}
        except Exception as e2:
            return {"success": False, "error": str(e), "fallback_error": str(e2)}
