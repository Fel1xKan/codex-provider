from __future__ import annotations

import enum
import json
import ssl
import sys
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from lib.common.constants import MAX_HTTP_BODY_BYTES
from lib.common.errors import SwitchError


class WireProtocol(enum.Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


def get_request_module() -> Any:
    for mod_name in ("opencode_provider", "codex_provider", "agy_provider"):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "urllib") and hasattr(mod.urllib, "request"):
            return mod.urllib.request
    return urllib.request


def normalize_base_url(url: str) -> str:
    url = url.strip()
    if "://" in url and not url.startswith(("http://", "https://")):
        raise SwitchError(f"invalid scheme: {url}")
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise SwitchError(f"invalid base_url scheme/host: {url}")
    if parsed.username or parsed.password:
        raise SwitchError("base_url must not contain credentials")
    if parsed.query or parsed.fragment:
        raise SwitchError("base_url must not contain query parameters or fragments")
    url = url.rstrip("/")
    if not parsed.path or parsed.path in ("", "/"):
        url = f"{url}/v1"
    return url


def models_url(base_url: str) -> str:
    url = base_url.strip().rstrip("/")
    parsed = urlparse(url)
    if not parsed.path or parsed.path == "":
        url = f"{url}/v1"
    return f"{url}/models"


def summarize_response_error(body: bytes, api_key: str = "") -> str:
    try:
        data = json.loads(body.decode("utf-8"))
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict):
                msg = err.get("message")
                if isinstance(msg, str):
                    if api_key and api_key in msg:
                        msg = msg.replace(api_key, "[REDACTED]")
                    return msg
    except Exception:
        pass
    text = body.decode("utf-8", errors="replace")
    if api_key and api_key in text:
        text = text.replace(api_key, "[REDACTED]")
    return text[:200]


def _request_headers(api_key: str, protocol: WireProtocol) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "codex-provider",
        "Accept": "application/json",
    }
    if protocol is WireProtocol.ANTHROPIC:
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    return headers


def fetch_provider_models(
    base_url: str,
    api_key: str,
    protocol: WireProtocol = WireProtocol.OPENAI,
) -> list[str]:
    base_url = normalize_base_url(base_url)
    models_url = f"{base_url}/models"
    req_mod = get_request_module()
    req = req_mod.Request(
        models_url,
        headers=_request_headers(api_key, protocol),
    )
    try:
        with req_mod.urlopen(req, timeout=10) as resp:
            raw_body = resp.read()
            data = json.loads(raw_body.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read()
        summary = summarize_response_error(body, api_key)
        detail = f": {summary}" if summary else ""
        raise SwitchError(
            f"failed to fetch models from {models_url}: HTTP {exc.code}{detail}"
        ) from exc
    except Exception as exc:
        raise SwitchError(f"failed to fetch models from {models_url}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise SwitchError(
            f"invalid models response from {models_url}: "
            "expected an object with a data list"
        )
    models = [
        m["id"]
        for m in data["data"]
        if isinstance(m, dict) and isinstance(m.get("id"), str)
    ]
    if not models:
        raise SwitchError(
            f"invalid models response from {models_url}: no model ids found"
        )
    return sorted(models)


def run_models_test(
    provider: str,
    base_url: str,
    api_key: str,
    timeout: float,
    current_provider: str | None = None,
    anthropic: bool = False,
) -> int:
    models_endpoint = models_url(base_url)

    req_mod = get_request_module()
    protocol = WireProtocol.ANTHROPIC if anthropic else WireProtocol.OPENAI
    req = req_mod.Request(
        models_endpoint,
        headers=_request_headers(api_key, protocol),
    )

    ctx = ssl.create_default_context()

    print(f"test provider: {provider}")
    print(f"base_url: {base_url}")
    print(f"models url: {models_endpoint}")

    try:
        try:
            resp_cm = req_mod.urlopen(req, timeout=timeout, context=ctx)
        except TypeError:
            resp_cm = req_mod.urlopen(req, timeout=timeout)

        with resp_cm as resp:
            status = getattr(resp, "status", 200)
            raw_body = resp.read()
            if len(raw_body) > MAX_HTTP_BODY_BYTES:
                print(f"http status: {status}")
                print("result: failed")
                print(f"error: response body exceeds {MAX_HTTP_BODY_BYTES} bytes limit")
                return 1

            try:
                text = raw_body.decode("utf-8")
            except UnicodeDecodeError:
                print(f"http status: {status}")
                print("result: failed")
                print("error: response body is not valid JSON / UTF-8")
                return 1

            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                print(f"http status: {status}")
                print("result: failed")
                print("error: response body is not valid JSON")
                return 1

            if not isinstance(data, dict) or not isinstance(data.get("data"), list):
                print(f"http status: {status}")
                print("result: failed")
                print("error: response is not OpenAI-compatible (missing data array)")
                return 1

            models_count = len(data["data"])
            print(f"http status: {status}")
            print(f"models returned: {models_count}")
            print("result: ok")
            return 0
    except urllib.error.HTTPError as exc:
        print(f"http status: {exc.code}")
        print("result: failed")
        return 1
    except Exception as exc:
        print("result: failed")
        print(f"error: {exc}")
        return 1
