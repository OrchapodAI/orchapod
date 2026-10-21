"""
apps/api/services/email.py

Thin wrapper around the Resend email API.
https://resend.com/docs/api-reference/emails/send-email

Required env vars (set in .env):
  RESEND_API_KEY       — your Resend API key
  ORCHAPOD_FROM_EMAIL  — sender address (must be a verified domain in Resend)
  ORCHAPOD_ALERT_EMAIL — recipient for system alerts (endpoint expiry, etc.)

If RESEND_API_KEY is not set, all sends are silently skipped — safe for local dev.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from api import config

log = logging.getLogger(__name__)

_RESEND_API_KEY    = config.env("RESEND_API_KEY")
_FROM_EMAIL        = config.env("ORCHAPOD_FROM_EMAIL")
_ALERT_EMAIL       = config.env("ORCHAPOD_ALERT_EMAIL")
_RESEND_SEND_URL   = "https://api.resend.com/emails"


def _enabled() -> bool:
    return bool(_RESEND_API_KEY and _ALERT_EMAIL)


async def send_endpoint_expiry_warning(
    run_id:       str,
    model:        str,
    endpoint_url: str,
    minutes_remaining: int,
) -> None:
    """
    Send a T-10min endpoint expiry warning email.
    Silently skipped if RESEND_API_KEY or ORCHAPOD_ALERT_EMAIL are not set.
    """
    if not _enabled():
        log.info("Email not configured — skipping endpoint expiry warning for run %s", run_id)
        return

    control_url = config.env("ORCHAPOD_CONTROL_URL")
    run_url     = f"{control_url}/runs/{run_id}"
    now_str     = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    subject = f"⚠️ Endpoint expiring in {minutes_remaining} min — {model}"
    html = f"""
    <p>Your <strong>orchapod</strong> endpoint is expiring soon.</p>
    <table style="border-collapse:collapse;font-family:monospace;font-size:13px">
      <tr><td style="padding:4px 12px 4px 0;color:#6b7280">Model</td>      <td>{model}</td></tr>
      <tr><td style="padding:4px 12px 4px 0;color:#6b7280">Endpoint</td>   <td><a href="{endpoint_url}">{endpoint_url}</a></td></tr>
      <tr><td style="padding:4px 12px 4px 0;color:#6b7280">Expires in</td> <td><strong>{minutes_remaining} minutes</strong> ({now_str})</td></tr>
      <tr><td style="padding:4px 12px 4px 0;color:#6b7280">Run</td>        <td><a href="{run_url}">{run_id[:8]}…</a></td></tr>
    </table>
    <p style="margin-top:16px">
      <a href="{run_url}" style="background:#2563eb;color:#fff;padding:8px 16px;border-radius:6px;text-decoration:none;font-size:13px">
        Extend endpoint →
      </a>
    </p>
    <p style="color:#9ca3af;font-size:12px;margin-top:24px">
      If you don't extend, the pod will be terminated automatically and the endpoint will stop responding.
    </p>
    """

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                _RESEND_SEND_URL,
                headers={
                    "Authorization": f"Bearer {_RESEND_API_KEY}",
                    "Content-Type":  "application/json",
                },
                json={
                    "from":    _FROM_EMAIL,
                    "to":      [_ALERT_EMAIL],
                    "subject": subject,
                    "html":    html,
                },
            )
            if resp.status_code >= 400:
                log.warning("Resend returned %s: %s", resp.status_code, resp.text)
            else:
                log.info("Expiry warning email sent for run %s", run_id)
    except Exception as exc:
        log.warning("Failed to send expiry warning email: %s", exc)
