from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any

import lib.agy.store as st
from lib.common.constants import MAX_HTTP_BODY_BYTES, VERSION
from lib.common.errors import SwitchError
from lib.common.jwt_helper import parse_jwt_claims

QUOTA_URL = (
    "https://daily-cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary"
)
LOAD_CODE_ASSIST_URL = (
    "https://daily-cloudcode-pa.googleapis.com/v1internal:loadCodeAssist"
)
TOKEN_URL = "https://oauth2.googleapis.com/token"
REQUEST_TIMEOUT = 15.0

# Antigravity is an installed application, so these OAuth client credentials are
# public identifiers embedded in the CLI. Select the client from the ID token so
# accounts imported from either supported Antigravity auth client can refresh.
OAUTH_CLIENTS = {
    "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com": (
        "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"
    ),
    "884354919052-36trc1jjb3tguiac32ov6cod268c5blh.apps.googleusercontent.com": (
        "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"
    ),
}


def _antigravity_user_agent() -> str:
    version = "1.1.8"
    agy_binary = shutil.which("agy")
    if agy_binary:
        try:
            result = subprocess.run(
                [agy_binary, "--version"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            match = re.search(r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", result.stdout)
            if result.returncode == 0 and match:
                version = match.group(0)
        except (OSError, subprocess.SubprocessError):
            pass

    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        machine = "amd64"
    elif machine in ("aarch64", "arm64"):
        machine = "arm64"
    return f"antigravity/{version} {system}/{machine}"


class _HTTPFailure(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _oauth_token(token_data: dict[str, Any]) -> dict[str, Any]:
    nested = token_data.get("token")
    if isinstance(nested, dict):
        return nested
    return token_data


def _token_expired(expiry: Any) -> bool:
    if not isinstance(expiry, str) or not expiry:
        return False
    try:
        parsed = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
    except ValueError:
        return True
    return parsed <= datetime.now(UTC) + timedelta(seconds=30)


def _response_error(raw_body: bytes) -> str:
    try:
        data = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return raw_body.decode("utf-8", errors="replace")[:200]
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
        if isinstance(error, str):
            description = data.get("error_description")
            if isinstance(description, str):
                return f"{error}: {description}"
            return error
    return "request failed"


def _request_json(request: urllib.request.Request) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            raw_body = response.read(MAX_HTTP_BODY_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raw_body = exc.read(MAX_HTTP_BODY_BYTES + 1)
        raise _HTTPFailure(exc.code, _response_error(raw_body)) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise SwitchError(f"Antigravity usage request failed: {reason}") from exc

    if len(raw_body) > MAX_HTTP_BODY_BYTES:
        raise SwitchError(
            f"Antigravity usage response exceeds {MAX_HTTP_BODY_BYTES} bytes"
        )
    try:
        data = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SwitchError("Antigravity usage response is not valid JSON") from exc
    if not isinstance(data, dict):
        raise SwitchError("Antigravity usage response must contain an object")
    return data


def _oauth_client(token_data: dict[str, Any]) -> tuple[str, str]:
    id_token = token_data.get("id_token")
    claims = parse_jwt_claims(id_token) if isinstance(id_token, str) else None
    audience = claims.get("aud") if claims else None
    if not isinstance(audience, str) or audience not in OAUTH_CLIENTS:
        raise SwitchError(
            "cannot refresh this account: unsupported Antigravity OAuth client; "
            "log in again with a current agy CLI"
        )
    return audience, OAUTH_CLIENTS[audience]


def _refresh_access_token(token_data: dict[str, Any]) -> str:
    oauth_token = _oauth_token(token_data)
    refresh_token = oauth_token.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise SwitchError(
            "Antigravity access token expired and no refresh token is available; "
            "log in again with `apx login`"
        )

    client_id, client_secret = _oauth_client(token_data)
    payload = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
    ).encode("ascii")
    request = urllib.request.Request(
        TOKEN_URL,
        data=payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": f"agy-provider/{VERSION}",
        },
        method="POST",
    )
    try:
        response = _request_json(request)
    except _HTTPFailure as exc:
        raise SwitchError(f"Antigravity token refresh failed: {exc}") from exc
    access_token = response.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise SwitchError("Antigravity token refresh returned no access token")
    return access_token


def _fetch_quota(token_data: dict[str, Any]) -> dict[str, Any]:
    oauth_token = _oauth_token(token_data)
    access_token = oauth_token.get("access_token")
    refreshed = False
    if (
        not isinstance(access_token, str)
        or not access_token
        or _token_expired(oauth_token.get("expiry"))
    ):
        access_token = _refresh_access_token(token_data)
        refreshed = True

    user_agent = _antigravity_user_agent()

    def request_quota(token: str) -> dict[str, Any]:
        load_request = urllib.request.Request(
            LOAD_CODE_ASSIST_URL,
            data=json.dumps(
                {
                    "metadata": {
                        "ideType": "IDE_UNSPECIFIED",
                        "platform": "PLATFORM_UNSPECIFIED",
                        "pluginType": "GEMINI",
                    }
                },
                separators=(",", ":"),
            ).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": user_agent,
            },
            method="POST",
        )
        load_response = _request_json(load_request)
        project = load_response.get("cloudaicompanionProject") or load_response.get(
            "cloudaicompanion_project"
        )
        if not isinstance(project, str) or not project:
            raise SwitchError(
                "Antigravity loadCodeAssist response contains no account project"
            )

        request = urllib.request.Request(
            QUOTA_URL,
            data=json.dumps({"project": project}, separators=(",", ":")).encode(
                "utf-8"
            ),
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": user_agent,
            },
            method="POST",
        )
        return _request_json(request)

    try:
        return request_quota(access_token)
    except _HTTPFailure as exc:
        if exc.status == 401 and not refreshed:
            try:
                return request_quota(_refresh_access_token(token_data))
            except _HTTPFailure as retry_exc:
                exc = retry_exc
        raise SwitchError(
            f"Antigravity usage request failed (HTTP {exc.status}): {exc}"
        ) from exc


def _bucket_order(bucket: dict[str, Any]) -> tuple[int, str]:
    window = str(bucket.get("window", "")).lower()
    bucket_id = str(bucket.get("bucketId", "")).lower()
    value = f"{window} {bucket_id}"
    if "5h" in value or "five" in value:
        return 0, value
    if "week" in value:
        return 1, value
    return 2, value


def _bucket_label(bucket: dict[str, Any]) -> str:
    window = str(bucket.get("window", "")).lower()
    bucket_id = str(bucket.get("bucketId", "")).lower()
    value = f"{window} {bucket_id}"
    if "5h" in value or "five" in value:
        return "5h limit"
    if "week" in value:
        return "weekly limit"
    display_name = bucket.get("displayName")
    return str(display_name) if display_name else "limit"


def _remaining_text(bucket: dict[str, Any]) -> str:
    if bucket.get("disabled") is True:
        return "unavailable"
    fraction = bucket.get("remainingFraction")
    if isinstance(fraction, (int, float)) and not isinstance(fraction, bool):
        percentage = min(max(float(fraction), 0.0), 1.0) * 100
        return f"{percentage:.2f}% remaining"
    amount = bucket.get("remainingAmount")
    if isinstance(amount, (int, float)) and not isinstance(amount, bool):
        return f"{amount:g} remaining"
    return "remaining amount unknown"


def _print_usage(account: st.AccountState, data: dict[str, Any]) -> None:
    groups = data.get("groups")
    if not isinstance(groups, list):
        raise SwitchError("Antigravity usage response is missing quota groups")

    print(f"Account: {account.name}")
    if account.email:
        print(f"Identity: {account.email}")

    printed = False
    for group in groups:
        if not isinstance(group, dict):
            continue
        buckets = group.get("buckets")
        if not isinstance(buckets, list):
            continue
        valid_buckets = [bucket for bucket in buckets if isinstance(bucket, dict)]
        if not valid_buckets:
            continue

        print("")
        print(str(group.get("displayName") or "Models"))
        for bucket in sorted(valid_buckets, key=_bucket_order):
            line = f"  {_bucket_label(bucket)}: {_remaining_text(bucket)}"
            reset_time = bucket.get("resetTime")
            if isinstance(reset_time, str) and reset_time:
                line += f" (resets at {reset_time})"
            print(line)
        printed = True

    if not printed:
        raise SwitchError("Antigravity usage response contains no quota buckets")


def usage_command(account_name: str | None) -> int:
    store = st.load_store()
    target = account_name or store.current
    if not target:
        raise SwitchError("no current account; pass an account name")
    if target not in store.accounts:
        raise SwitchError(f"account not found: {target}")

    account = store.accounts[target]
    _print_usage(account, _fetch_quota(account.token_data))
    return 0
