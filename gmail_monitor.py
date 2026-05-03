import os
from fastapi import APIRouter, Request, HTTPException
from gmail_poller import check_new_emails

router = APIRouter()


@router.post("/check")
async def manual_check(request: Request):
    secret = request.headers.get("x-api-secret", "")
    if secret != os.environ.get("API_SECRET", ""):
        raise HTTPException(status_code=401, detail="Unauthorized")

    await check_new_emails()
    return {"success": True, "message": "Email check triggered"}
