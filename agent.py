import json
import os
from collections import defaultdict
from openai import OpenAI
from services.tools import (
    get_emails, create_draft, send_email, reply_to_email, add_label,
    get_calendar_events, create_calendar_event,
    get_notion_tasks, update_notion_task, create_notion_task,
    send_sms, search_knowledge_base,
)

MODEL = "gpt-4o-mini"

# ─── Tool definitions ────────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_emails",
            "description": "Read emails from Mohanad's Gmail inbox.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_results": {"type": "integer", "description": "Max emails to return (default 5)"},
                    "query": {"type": "string", "description": "Gmail search query (default: is:unread)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_draft",
            "description": "Create an email draft. Use for 'draft', 'write', 'compose' — never for 'send'.",
            "parameters": {
                "type": "object",
                "required": ["to", "subject", "body"],
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Send an email. ONLY use when user explicitly says 'send'.",
            "parameters": {
                "type": "object",
                "required": ["to", "subject", "body"],
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reply_to_email",
            "description": "Reply to an existing email thread. Requires the original message ID.",
            "parameters": {
                "type": "object",
                "required": ["message_id", "body"],
                "properties": {
                    "message_id": {"type": "string"},
                    "body": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_label",
            "description": "Add a label to a Gmail message.",
            "parameters": {
                "type": "object",
                "required": ["message_id", "label_name"],
                "properties": {
                    "message_id": {"type": "string"},
                    "label_name": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_calendar_events",
            "description": "Get upcoming events from Google Calendar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "time_min": {"type": "string", "description": "ISO datetime start"},
                    "time_max": {"type": "string", "description": "ISO datetime end"},
                    "max_results": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": "Create a new Google Calendar event.",
            "parameters": {
                "type": "object",
                "required": ["title", "start"],
                "properties": {
                    "title": {"type": "string"},
                    "start": {"type": "string", "description": "ISO datetime"},
                    "end": {"type": "string", "description": "ISO datetime (default: 30 min after start)"},
                    "description": {"type": "string"},
                    "location": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_notion_tasks",
            "description": "Get tasks from the EG23 Notion database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "return_all": {"type": "boolean"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_notion_task",
            "description": "Update an existing Notion task. Requires page ID.",
            "parameters": {
                "type": "object",
                "required": ["page_id"],
                "properties": {
                    "page_id": {"type": "string"},
                    "status": {"type": "string"},
                    "title": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_notion_task",
            "description": "Create a new task in Notion.",
            "parameters": {
                "type": "object",
                "required": ["title"],
                "properties": {
                    "title": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_sms",
            "description": "Send an SMS via Twilio.",
            "parameters": {
                "type": "object",
                "required": ["to", "message"],
                "properties": {
                    "to": {"type": "string", "description": "Phone number in E.164 format"},
                    "message": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "Search EG23's internal knowledge base in Supabase.",
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                },
            },
        },
    },
]

TOOL_MAP = {
    "get_emails": get_emails,
    "create_draft": create_draft,
    "send_email": send_email,
    "reply_to_email": reply_to_email,
    "add_label": add_label,
    "get_calendar_events": get_calendar_events,
    "create_calendar_event": create_calendar_event,
    "get_notion_tasks": get_notion_tasks,
    "update_notion_task": update_notion_task,
    "create_notion_task": create_notion_task,
    "send_sms": send_sms,
    "search_knowledge_base": search_knowledge_base,
}

# ─── In-memory session store (keyed by phone number) ─────────────────────────

_sessions: dict[str, list] = defaultdict(list)
MAX_HISTORY = 20


def run_agent(user_message: str, system_prompt: str, phone_number: str = None, tools: list = None) -> str:
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    history = _sessions[phone_number] if phone_number else []

    messages = [
        {"role": "system", "content": system_prompt},
        *history,
        {"role": "user", "content": user_message},
    ]

    active_tools = TOOLS if tools is None else tools

    while True:
        kwargs = {"model": MODEL, "messages": messages}
        if active_tools:
            kwargs["tools"] = active_tools
            kwargs["tool_choice"] = "auto"

        response = client.chat.completions.create(**kwargs)
        assistant_msg = response.choices[0].message
        messages.append(assistant_msg)

        if not assistant_msg.tool_calls:
            break

        for tool_call in assistant_msg.tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            print(f"[Tool] {name}({args})")

            try:
                fn = TOOL_MAP.get(name)
                if not fn:
                    raise ValueError(f"Unknown tool: {name}")
                result = fn(**args)
            except Exception as e:
                result = {"error": str(e)}
                print(f"[Tool Error] {name}: {e}")

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result),
            })

    output = assistant_msg.content or ""

    # Save to session memory
    if phone_number:
        session = _sessions[phone_number]
        session.append({"role": "user", "content": user_message})
        session.append({"role": "assistant", "content": output})
        if len(session) > MAX_HISTORY:
            _sessions[phone_number] = session[-MAX_HISTORY:]

    return output
