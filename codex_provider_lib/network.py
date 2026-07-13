from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse, urlunparse

from codex_provider_lib.constants import MAX_HTTP_BODY_BYTES, VERSION
from codex_provider_lib.errors import SwitchError


def normalize_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.hostname:
        raise SwitchError(
            "base_url must include scheme and host, for example: "
            "https://api.example.com"
        )
    if parsed.scheme.lower() not in {"http", "https"}:
        raise SwitchError("base_url scheme must be http or https")
    if parsed.username or parsed.password:
        raise SwitchError("base_url must not include user credentials")
    if parsed.query or parsed.fragment:
        raise SwitchError("base_url must not include query parameters or fragments")
    path = "/v1" if parsed.path in {"", "/"} else parsed.path.rstrip("/")
    return urlunparse(parsed._replace(scheme=parsed.scheme.lower(), path=path))


def models_url(base_url: str) -> str:
    normalized = normalize_base_url(base_url)
    parsed = urlparse(normalized)
    path = parsed.path.rstrip("/") + "/models"
    return urlunparse(parsed._replace(path=path))


def redact_secret(text: str, secret: str) -> str:
    return text.replace(secret, "[REDACTED]") if secret else text


def read_response_body(response: Any) -> bytes:
    body = response.read(MAX_HTTP_BODY_BYTES + 1)
    if len(body) > MAX_HTTP_BODY_BYTES:
        raise SwitchError(f"response body exceeds {MAX_HTTP_BODY_BYTES} bytes")
    return body


def summarize_response_error(payload: bytes, api_key: str) -> str:
    text = payload.decode(errors="replace").strip()
    if not text:
        return ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return redact_secret(text[:500], api_key)
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str):
                return redact_secret(message[:500], api_key)
        message = data.get("message")
        if isinstance(message, str):
            return redact_secret(message[:500], api_key)
    return redact_secret(json.dumps(data, ensure_ascii=False)[:500], api_key)


def run_models_test(
    label: str,
    base_url: str,
    api_key: str,
    timeout: float,
    current_provider: str | None,
) -> int:
    if timeout <= 0:
        raise SwitchError("timeout must be greater than 0")

    url = models_url(base_url)
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": f"codex-provider/{VERSION}",
        },
    )

    if current_provider is not None:
        print(f"current provider: {current_provider}")
    print(f"test provider: {label}")
    print(f"base_url: {base_url}")
    print(f"models url: {url}")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = read_response_body(response)
            status = response.status
    except urllib.error.HTTPError as exc:
        try:
            detail = summarize_response_error(read_response_body(exc), api_key)
        except SwitchError as body_exc:
            detail = str(body_exc)
        print("result: failed")
        print(f"http status: {exc.code} {exc.reason}")
        if detail:
            print(f"error: {detail}")
        return 1
    except urllib.error.URLError as exc:
        print("result: failed")
        print(f"error: {exc.reason}")
        return 1
    except TimeoutError:
        print("result: failed")
        print(f"error: request timed out after {timeout:g}s")
        return 1
    except SwitchError as exc:
        print("result: failed")
        print(f"error: {exc}")
        return 1

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        print("result: failed")
        print(f"http status: {status}")
        print(f"error: response is not valid JSON: {exc}")
        return 1

    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        print("result: failed")
        print(f"http status: {status}")
        print("error: response is not OpenAI-compatible: expected a data array")
        return 1

    models = []
    for item in payload["data"]:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            models.append(item["id"])

    print("result: ok")
    print(f"http status: {status}")
    print(f"models: {len(models)}")
    for model in models[:20]:
        print(f"- {model}")
    if len(models) > 20:
        print(f"... {len(models) - 20} more")
    return 0
