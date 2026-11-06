# discord.py - Discord webhook relay (default channel, ADR 0062).
#
# One webhook per project (_flux_setup/collab.json); a recipient is pinged with
# <@discord_id> so the Discord app rings the phone. allowed_mentions limits the ping
# to the recipients: a message can never ping @everyone or a role.

from __future__ import annotations

from features.notify.channels import SendResult, classify, post_json

MAX_CHARS = 2000


def build_payload(text: str, user_ids: list[str]) -> dict:
    ids = [str(i).strip() for i in user_ids if str(i).strip().isdigit()]
    prefix = " ".join(f"<@{i}>" for i in ids)
    content = f"{prefix} {text}".strip() if prefix else text
    if len(content) > MAX_CHARS:
        content = content[: MAX_CHARS - 3] + "..."
    return {"content": content, "allowed_mentions": {"parse": [], "users": ids}}


def send(webhook_url: str, text: str, user_ids: list[str] | None = None) -> SendResult:
    if not webhook_url:
        return SendResult(False, 0, 0.0, permanent=True)
    status, headers, body = post_json(webhook_url, build_payload(text, user_ids or []))
    return classify(status, headers, body)
