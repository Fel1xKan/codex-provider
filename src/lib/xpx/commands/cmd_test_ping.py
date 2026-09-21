from __future__ import annotations

import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from lib.common.errors import SwitchError
from lib.xpx.adapters.registry import detect_installed_adapters, get_adapter
from lib.xpx.models.sync import build_models_request, fetch_remote_models
from lib.xpx.store.provider_store import ProviderStore


def run_test(args: Any) -> int:
    provider = getattr(args, "provider", None)
    test_all = getattr(args, "all", False)
    store = ProviderStore()

    if test_all or not provider:
        providers = store.list_all()
        if not providers:
            print("No providers configured.")
            return 0
    else:
        providers = [store.require(provider)]

    header = (
        f"{'PROVIDER':<16} {'STATUS':<10} {'LATENCY':<12} {'MODELS':<8} {'ENDPOINT'}"
    )
    print(header)
    print("-" * 75)

    failures = 0
    for p in providers:
        req = build_models_request(p.base_url, p.api_key, protocol=p.protocol)
        start = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                elapsed_ms = int((time.perf_counter() - start) * 1000)
                code = resp.status
                models = fetch_remote_models(
                    p.base_url, p.api_key, protocol=p.protocol, timeout=10
                )
                print(
                    f"{p.name:<16} {code:<10} {f'{elapsed_ms}ms':<12} "
                    f"{len(models):<8} {p.base_url}"
                )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            failures += 1
            print(f"{p.name:<16} {'FAILED':<10} {f'{elapsed_ms}ms':<12} {'-':<8} {exc}")

    return 1 if failures > 0 else 0


def _ping_target(
    target_name: str,
    prompt: str,
    timeout: int,
) -> tuple[str, bool, str]:
    try:
        adp = get_adapter(target_name)
        start = time.perf_counter()
        ok, out = adp.ping(prompt, timeout)
        duration = time.perf_counter() - start
        summary = f"{out[:60]}..." if len(out) > 60 else out
        return target_name, ok, f"{summary} ({duration:.2f}s)"
    except Exception as exc:
        return target_name, False, str(exc)


def run_ping(args: Any) -> int:
    target_arg = getattr(args, "target", None)
    ping_all = getattr(args, "all", False)
    prompt = getattr(args, "prompt", "say hi") or "say hi"
    timeout = int(getattr(args, "timeout", 60) or 60)

    if ping_all:
        installed = detect_installed_adapters()
        if not installed:
            print("No supported target clients detected.")
            return 0
        targets = sorted(installed.keys())
    elif target_arg:
        targets = [t.strip().lower() for t in target_arg.split(",") if t.strip()]
    else:
        raise SwitchError(
            "target client required (e.g. 'xpx ping codex' or 'xpx ping --all')"
        )

    print(
        f"Pinging {len(targets)} target(s) with prompt: "
        f"{prompt!r} (timeout: {timeout}s)...\n"
    )

    results: list[tuple[str, bool, str]] = []
    max_workers = min(len(targets), 5)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_ping_target, t, prompt, timeout): t for t in targets
        }
        for fut in as_completed(futures):
            target_name, ok, message = fut.result()
            symbol = "✔" if ok else "✖"
            status_word = "OK" if ok else "FAILED"
            print(f"  {symbol} [{target_name:<10}] {status_word}: {message}")
            results.append((target_name, ok, message))

    failures = sum(1 for _, ok, _ in results if not ok)
    return 1 if failures > 0 else 0
