"""Shared helpers for MCP Google handlers."""

import json


def _ok(data: dict) -> str:
    return json.dumps({"success": True, **data}, ensure_ascii=False)


def _err(msg: str) -> str:
    return json.dumps(
        {"success": False, "error": "api_error", "message": msg}, ensure_ascii=False
    )


def _not_authorized() -> str:
    return json.dumps(
        {
            "success": False,
            "error": "not_authorized",
            "message": "User is not authorized in Google. Ask user to run /auth command.",
        },
        ensure_ascii=False,
    )
