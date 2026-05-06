"""Generates everything the agent needs from workflows.py — automatically.

Provides:
- WORKFLOW_TOOLS  : OpenAI tool schemas (just append to TOOLS in agent.py)
- WORKFLOW_FUNCS  : dict mapping name -> callable (just merge into TOOL_MAP)
"""
import json
import requests
from workflows import WORKFLOWS


def _interpolate(template, args: dict):
    """Recursively replace {arg_name} in strings inside the template."""
    if isinstance(template, str):
        try:
            return template.format(**args)
        except KeyError:
            return template
    if isinstance(template, dict):
        return {k: _interpolate(v, args) for k, v in template.items()}
    if isinstance(template, list):
        return [_interpolate(v, args) for v in template]
    return template


def _make_function(workflow: dict):
    """Build a callable that POSTs to the workflow's webhook."""
    url = workflow["url"]
    template = workflow.get("payload_template")
    success_msg = workflow.get("success_message", "Workflow triggered.")

    def runner(**kwargs):
        payload = _interpolate(template, kwargs) if template else kwargs

        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code >= 400:
                return {"success": False, "error": f"n8n returned {response.status_code}: {response.text[:200]}"}

            # Try to return the n8n response body if it's JSON, otherwise the success message
            try:
                body = response.json()
                if isinstance(body, dict) and body:
                    return {"success": True, **body}
            except Exception:
                pass

            return {"success": True, "message": success_msg.format(**kwargs)}

        except requests.Timeout:
            # Fire-and-forget workflows often time out — that's fine
            return {"success": True, "message": success_msg.format(**kwargs)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    runner.__name__ = workflow["name"]
    return runner


def _make_schema(workflow: dict) -> dict:
    """Build the OpenAI tool definition from the workflow config."""
    properties = {}
    required = []
    for inp in workflow.get("inputs", []):
        properties[inp["name"]] = {
            "type": inp.get("type", "string"),
            "description": inp.get("description", ""),
        }
        if inp.get("required", True):
            required.append(inp["name"])

    return {
        "type": "function",
        "function": {
            "name": workflow["name"],
            "description": workflow["description"],
            "parameters": {
                "type": "object",
                "required": required,
                "properties": properties,
            },
        },
    }


# Generated outputs — import these in agent.py
WORKFLOW_TOOLS = [_make_schema(wf) for wf in WORKFLOWS]
WORKFLOW_FUNCS = {wf["name"]: _make_function(wf) for wf in WORKFLOWS}
