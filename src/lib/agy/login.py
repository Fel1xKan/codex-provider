from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import lib.agy.store as st
from lib.agy.commands import add_account, switch_account
from lib.common.errors import SwitchError


def login_account(
    name: str | None = None,
    dry_run: bool = False,
) -> int:
    mod = sys.modules.get("cli.agy_provider") or sys.modules.get("agy_provider")
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

    agy_binary = which_fn("agy") or which_fn("antigravity")
    if not agy_binary:
        raise SwitchError(
            "'agy' or 'antigravity' binary not found on PATH; "
            "please install Antigravity CLI first"
        )

    with tempfile.TemporaryDirectory(prefix="agy_login_") as temp_dir:
        env = dict(os.environ)
        env["HOME"] = temp_dir

        print(f"initiating login session via {agy_binary}...")
        try:
            proc = run_fn(
                [agy_binary, "--dangerously-skip-permissions"],
                env=env,
                check=False,
            )
        except Exception as exc:
            raise SwitchError(f"failed to launch login process: {exc}") from exc

        if getattr(proc, "returncode", 0) != 0:
            print("login session cancelled or failed")
            return 1

        token_path = (
            Path(temp_dir) / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
        )
        if not token_path.exists():
            token_path = Path(temp_dir) / "antigravity-oauth-token"

        if not token_path.exists():
            raise SwitchError("no OAuth token was generated during login session")

        try:
            token_data = json.loads(token_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SwitchError(f"invalid token generated: {exc}") from exc

        email, _, _ = st.extract_account_info(token_data)

        if not name:
            if email and "@" in email:
                name = email.split("@")[0].replace(".", "_")
            else:
                name = f"account_{len(st.load_store().accounts) + 1}"

        rc = add_account(
            name=name,
            from_file=str(token_path),
            dry_run=dry_run,
        )
        if rc != 0:
            return rc

        if not dry_run:
            return switch_account(name, dry_run=False)
        return 0
