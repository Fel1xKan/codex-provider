from __future__ import annotations

import shutil
import subprocess
import sys

from lib.common.errors import SwitchError
from lib.opencode.store import (
    load_state,
    provider_models,
)


def ping_provider(
    provider: str | None,
    timeout: float,
    model: str | None,
    prompt: str,
) -> int:
    mod = sys.modules.get("cli.opencode_provider") or sys.modules.get(
        "opencode_provider"
    )
    shutil_mod = getattr(mod, "shutil", None) if mod else None
    subprocess_mod = getattr(mod, "subprocess", None) if mod else None

    which_fn = (
        shutil_mod.which
        if shutil_mod and hasattr(shutil_mod, "which")
        else shutil.which
    )
    run_fn = (
        subprocess_mod.run
        if subprocess_mod and hasattr(subprocess_mod, "run")
        else subprocess.run
    )
    devnull = (
        getattr(subprocess_mod, "DEVNULL", subprocess.DEVNULL)
        if subprocess_mod
        else subprocess.DEVNULL
    )

    state = load_state()
    target = provider or state.current_provider
    if not target:
        raise SwitchError("no current provider; pass a provider name")
    config = state.providers.get(target)
    if config is None:
        raise SwitchError(f"unknown provider '{target}'")

    models = provider_models(state, target)
    selected_model = model or (next(iter(models)) if models else None)
    if not selected_model:
        raise SwitchError(f"provider '{target}' has no configured models")
    if "/" not in selected_model:
        selected_model = f"{target}/{selected_model}"

    print(f"pinging provider '{target}' with prompt: {prompt}...")
    binary = which_fn("opencode")
    if not binary:
        raise SwitchError("'opencode' binary not found on PATH")

    cmd_list = [binary, "run", "--model", selected_model, prompt]
    proc = run_fn(cmd_list, stdin=devnull, timeout=timeout)
    rc = getattr(proc, "returncode", 0)
    if rc != 0:
        print("ping result: failed")
        return 1
    print("ping result: ok")
    return 0


def ping_all_providers(timeout: float, model: str | None, prompt: str) -> int:
    state = load_state()
    if not state.providers:
        raise SwitchError("no providers configured")

    results: list[tuple[str, int]] = []
    for index, provider in enumerate(sorted(state.providers)):
        if index:
            print("")
        try:
            mod = sys.modules.get("cli.opencode_provider") or sys.modules.get(
                "opencode_provider"
            )
            ping_fn = (
                getattr(mod, "ping_provider", ping_provider) if mod else ping_provider
            )
            result = ping_fn(provider, timeout, model, prompt)
        except SwitchError as exc:
            print(f"pinging provider '{provider}' with prompt: {prompt}...")
            print("ping result: failed")
            print(f"error: {exc}")
            result = 1
        results.append((provider, result))

    available = sum(result == 0 for _, result in results)
    print("")
    print("provider ping summary:")
    for provider, result in results:
        print(f"- {provider}: {'ok' if result == 0 else 'failed'}")
    print(f"available: {available}/{len(results)}")
    return 0 if available == len(results) else 1
