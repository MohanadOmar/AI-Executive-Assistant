import os
import base64
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from notion_client import Client as NotionClient
from twilio.rest import Client as TwilioClient
from supabase import create_client
from openai import OpenAI

# ─── Clients ────────────────────────────────────────────────────────────────

NOTION_DATABASE_ID = "17e3ff1d-c591-458f-9bf5-fb6d3448e130"
TWILIO_FROM = "+18663288127"
MOHANAD_PHONE = "+12107219295"
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "mohanadomark@gmail.com")


def get_google_creds():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=[
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/calendar",
        ],
    )
    creds.refresh(Request())
    return creds


def get_gmail():
    return build("gmail", "v1", credentials=get_google_creds())


def get_calendar():
    return build("calendar", "v3", credentials=get_google_creds())


def get_notion():
    return NotionClient(auth=os.environ["NOTION_API_KEY"])


def get_twilio():
    return TwilioClient(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])


def get_supabase():
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def get_openai():
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])


# ─── Gmail ──────────────────────────────────────────────────────────────────

def get_emails(max_results: int = 5, query: str = "is:unread") -> list:
    service = get_gmail()
    result = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    messages = result.get("messages", [])

    emails = []
    for msg in messages:
        detail = service.users().messages().get(
            userId="me", id=msg["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"]
        ).execute()
        headers = {h["name"]: h["value"] for h in detail["payload"]["headers"]}
        emails.append({
            "id": msg["id"],
            "from": headers.get("From", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "snippet": detail.get("snippet", ""),
        })
    return emails


def _make_raw(to: str, subject: str, body: str, reply_headers: dict = None) -> str:
    msg = MIMEMultipart()
    msg["To"] = to
    msg["Subject"] = subject
    if reply_headers:
        msg["In-Reply-To"] = reply_headers.get("message_id", "")
        msg["References"] = reply_headers.get("references", "")
    msg.attach(MIMEText(body, "plain"))
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def create_draft(to: str, subject: str, body: str) -> dict:
    service = get_gmail()
    raw = _make_raw(to, subject, body)
    draft = service.users().drafts().create(
        userId="me", body={"message": {"raw": raw}}
    ).execute()
    return {"draft_id": draft["id"]}


def send_email(to: str, subject: str, body: str) -> dict:
    service = get_gmail()
    raw = _make_raw(to, subject, body)
    msg = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return {"message_id": msg["id"]}


def reply_to_email(message_id: str, body: str) -> dict:
    service = get_gmail()
    detail = service.users().messages().get(
        userId="me", id=message_id, format="metadata",
        metadataHeaders=["From", "Subject", "Message-ID", "References"]
    ).execute()
    headers = {h["name"]: h["value"] for h in detail["payload"]["headers"]}
    thread_id = detail["threadId"]

    subject = headers.get("Subject", "")
    if not subject.startswith("Re:"):
        subject = f"Re: {subject}"

    raw = _make_raw(
        to=headers.get("From", ""),
        subject=subject,
        body=body,
        reply_headers={
            "message_id": headers.get("Message-ID", ""),
            "references": f"{headers.get('References', '')} {headers.get('Message-ID', '')}".strip(),
        },
    )
    msg = service.users().messages().send(
        userId="me", body={"raw": raw, "threadId": thread_id}
    ).execute()
    return {"message_id": msg["id"]}


def add_label(message_id: str, label_name: str) -> dict:
    service = get_gmail()
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    match = next((l for l in labels if l["name"].lower() == label_name.lower()), None)
    if not match:
        raise ValueError(f'Label "{label_name}" not found')
    service.users().messages().modify(
        userId="me", id=message_id, body={"addLabelIds": [match["id"]]}
    ).execute()
    return {"success": True, "label": label_name}


# ─── Google Calendar ─────────────────────────────────────────────────────────

def get_calendar_events(time_min: str = None, time_max: str = None, max_results: int = 20) -> list:
    from datetime import datetime, timedelta, timezone
    service = get_calendar()
    now = datetime.now(timezone.utc)
    start = time_min or now.isoformat()
    end = time_max or (now + timedelta(days=7)).isoformat()

    result = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=start, timeMax=end,
        maxResults=max_results,
        singleEvents=True, orderBy="startTime"
    ).execute()

    return [
        {
            "id": e["id"],
            "title": e.get("summary", ""),
            "start": e["start"].get("dateTime", e["start"].get("date")),
            "end": e["end"].get("dateTime", e["end"].get("date")),
            "location": e.get("location", ""),
            "description": e.get("description", ""),
        }
        for e in result.get("items", [])
    ]


def create_calendar_event(title: str, start: str, end: str = None, description: str = "", location: str = "") -> dict:
    from datetime import datetime, timedelta, timezone
    service = get_calendar()
    if not end:
        end = (datetime.fromisoformat(start) + timedelta(minutes=30)).isoformat()
    event = service.events().insert(
        calendarId=CALENDAR_ID,
        body={
            "summary": title,
            "start": {"dateTime": start},
            "end": {"dateTime": end},
            "description": description,
            "location": location,
        },
    ).execute()
    return {"event_id": event["id"], "link": event.get("htmlLink", "")}


# ─── Notion ──────────────────────────────────────────────────────────────────

def get_notion_tasks(return_all: bool = True) -> list:
    notion = get_notion()
    result = notion.databases.query(
        database_id=NOTION_DATABASE_ID,
        page_size=100 if return_all else 10
    )
    tasks = []
    for page in result["results"]:
        props = page["properties"]
        title = (
            props.get("Name", props.get("Task", {}))
            .get("title", [{}])[0]
            .get("plain_text", "Untitled")
        )
        status = (
            props.get("Status", {}).get("select", {}) or
            props.get("Status", {}).get("status", {})
        ).get("name", "Unknown")
        tasks.append({"id": page["id"], "title": title, "status": status})
    return tasks


def update_notion_task(page_id: str, status: str = None, title: str = None) -> dict:
    notion = get_notion()
    properties = {}
    if status:
        properties["Status"] = {"select": {"name": status}}
    if title:
        properties["Name"] = {"title": [{"text": {"content": title}}]}
    notion.pages.update(page_id=page_id, properties=properties)
    return {"success": True, "page_id": page_id}


def create_notion_task(title: str) -> dict:
    notion = get_notion()
    page = notion.pages.create(
        parent={"database_id": NOTION_DATABASE_ID},
        properties={"Name": {"title": [{"text": {"content": title}}]}},
    )
    return {"page_id": page["id"], "title": title}


# ─── Twilio ──────────────────────────────────────────────────────────────────

def send_sms(to: str, message: str) -> dict:
    client = get_twilio()
    msg = client.messages.create(from_=TWILIO_FROM, to=to, body=message)
    return {"sid": msg.sid}


def send_sms_to_mohanad(message: str) -> dict:
    return send_sms(to=MOHANAD_PHONE, message=message)


# ─── Supabase Knowledge Base ─────────────────────────────────────────────────

def search_knowledge_base(query: str) -> list:
    client = get_openai()
    supabase = get_supabase()

    embedding_res = client.embeddings.create(
        model="text-embedding-3-small", input=query
    )
    embedding = embedding_res.data[0].embedding

    result = supabase.rpc("match_documents", {
        "query_embedding": embedding,
        "match_threshold": 0.7,
        "match_count": 5,
    }).execute()

    return result.data or []
