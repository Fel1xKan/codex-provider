from __future__ import annotations

import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from lib.common.errors import SwitchError
from lib.xpx.adapters.base import MergedProviderSpec
from lib.xpx.adapters.registry import detect_installed_adapters, get_adapter
from lib.xpx.models.sync import build_models_request, fetch_remote_models
from lib.xpx.store.provider_store import ProviderStore


def run_test(args: Any) -> int:
    """Single entry point for connectivity testing.

    Shallow (default): one HTTP GET against each provider's /models endpoint.
    Deep (`--deep`): spawn each target client and send a real prompt, proving
    the whole client -> provider path works.

    The deep variant used to be a separate `ping` command, which implied an
    ICMP-style liveness check while actually performing a full model request.
    Keeping one command with an explicit depth flag makes the cost obvious and
    leaves a single mental model: "test the thing, optionally end to end".
    """
    if getattr(args, "deep", False):
        return _run_deep_test(args)
    return _run_shallow_test(args)


def _run_shallow_test(args: Any) -> int:
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


def _run_deep_target(
    target_name: str,
    prompt: str,
    timeout: int,
    spec: MergedProviderSpec | None = None,
) -> tuple[str, bool, str]:
    try:
        adp = get_adapter(target_name)
        start = time.perf_counter()
        ok, out = adp.ping(prompt, timeout, spec)
        duration = time.perf_counter() - start
        # Success output is model prose and is safe to clip; a failure usually
        # carries the actionable next step, so keep it readable in full.
        text = out if not ok or len(out) <= 60 else f"{out[:60]}..."
        return target_name, ok, f"{text} ({duration:.2f}s)"
    except Exception as exc:
        return target_name, False, str(exc)


def _resolve_deep_targets(
    target_arg: str | None,
    deep_all: bool,
) -> list[str]:
    """Resolve which target clients to probe.

    `--all` means every installed client; an explicit target list always wins.
    Passing both used to silently drop the target list.
    """
    if target_arg:
        targets = [t.strip().lower() for t in target_arg.split(",") if t.strip()]
        if deep_all:
            # Union: never silently discard an explicitly named target.
            installed = detect_installed_adapters()
            targets = sorted(set(targets) | set(installed))
        return targets

    if deep_all:
        installed = detect_installed_adapters()
        if not installed:
            raise SwitchError("no supported target clients detected")
        return sorted(installed)

    raise SwitchError("target client required (e.g. 'xpx test --deep --target codex')")


def _build_deep_spec(
    provider_name: str | None,
    model: str | None,
    target: str,
) -> MergedProviderSpec | None:
    """Build the provider spec to probe, failing loudly on an unknown name.

    Any provider string used to be accepted while the client's own configured
    provider was probed, so a typo produced a green result for a provider that
    was never actually tested.
    """
    if not provider_name:
        return None

    pv = ProviderStore().require(provider_name)
    overrides = pv.targets.get(target)

    headers = dict(pv.headers)
    if overrides and overrides.headers:
        headers.update(overrides.headers)

    return MergedProviderSpec(
        name=pv.name,
        base_url=pv.base_url,
        api_key=pv.api_key,
        protocol=pv.protocol,
        model=model or pv.default_model,
        headers=headers,
        options=dict(overrides.options) if (overrides and overrides.options) else {},
    )


def _run_deep_test(args: Any) -> int:
    """Send a real prompt through target clients (`xpx test --deep`)."""
    target_arg = getattr(args, "target", None)
    provider_arg = getattr(args, "provider", None)
    deep_all = getattr(args, "all", False)
    prompt = getattr(args, "prompt", "say hi") or "say hi"
    timeout = int(getattr(args, "timeout", 60) or 60)
    model = getattr(args, "model", None)

    # Default to every installed client when no target is named, so
    # `xpx test --deep` is a complete end-to-end sweep.
    if not target_arg and not deep_all:
        deep_all = True
    targets = _resolve_deep_targets(target_arg, deep_all)

    # Validate every target name before spawning, so a typo fails fast instead
    # of surfacing as an opaque per-target error line.
    for name in targets:
        get_adapter(name)

    provider_name = provider_arg.strip() if provider_arg else None
    if provider_name and ProviderStore().get(provider_name) is None:
        raise SwitchError(
            f"unknown provider: '{provider_name}'. "
            "Run 'xpx list' to see configured providers."
        )

    label = provider_name or "client default"
    print(
        f"Deep-testing {len(targets)} target(s) against {label} with prompt: "
        f"{prompt!r} (timeout: {timeout}s)...\n"
    )

    results: list[tuple[str, bool, str]] = []
    max_workers = min(len(targets), 5)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _run_deep_target,
                t,
                prompt,
                timeout,
                _build_deep_spec(provider_name, model, t),
            ): t
            for t in targets
        }
        for fut in as_completed(futures):
            target_name, ok, message = fut.result()
            symbol = "✔" if ok else "✖"
            status_word = "OK" if ok else "FAILED"
            print(f"  {symbol} [{target_name:<10}] {status_word}: {message}")
            results.append((target_name, ok, message))

    failures = sum(1 for _, ok, _ in results if not ok)
    return 1 if failures > 0 else 0
