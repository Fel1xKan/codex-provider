from __future__ import annotations

import shutil
import subprocess
import sys

import lib.claude.store as st
from lib.common.errors import SwitchError


def ping_provider(
    provider: str | None,
    timeout: float,
    model: str | None,
    prompt: str,
) -> int:
    mod = sys.modules.get("cli.claude_provider") or sys.modules.get("claude_provider")
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

    state = st.ensure_provider_state(read_only=True)
    target = provider or state.active_provider
    if not target:
        raise SwitchError("no active provider; switch to a provider first")
    if target not in state.providers:
        raise SwitchError(f"unknown provider '{target}'")

    print(f"pinging provider '{target}' with prompt: {prompt}...")
    binary = which_fn("claude")
    if not binary:
        raise SwitchError("'claude' binary not found on PATH")

    cmd_list = [binary, "-p", prompt]
    if model:
        cmd_list.extend(["--model", model])
    proc = run_fn(cmd_list, stdin=devnull, timeout=timeout)
    rc = getattr(proc, "returncode", 0)
    if rc != 0:
        print("ping result: failed")
        return 1
    print("ping result: ok")
    return 0
