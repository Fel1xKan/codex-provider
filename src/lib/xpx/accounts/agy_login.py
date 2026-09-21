from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from lib.common.errors import SwitchError


def login() -> dict[str, Any]:
    """Initiate an interactive Antigravity CLI login session.

    Returns extracted token data.
    """
    agy_binary = shutil.which("agy") or shutil.which("antigravity")
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
            proc = subprocess.run(
                [agy_binary, "--dangerously-skip-permissions"],
                env=env,
                check=False,
            )
        except Exception as exc:
            raise SwitchError(f"failed to launch login process: {exc}") from exc

        if proc.returncode != 0:
            raise SwitchError("login session was cancelled or failed")

        token_path = (
            Path(temp_dir) / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
        )
        if not token_path.exists():
            token_path = (
                Path(temp_dir)
                / ".gemini"
                / "antigravity-cli"
                / "jetski-standalone-oauth-token"
            )
        if not token_path.exists():
            token_path = Path(temp_dir) / "antigravity-oauth-token"

        if not token_path.exists():
            raise SwitchError("no OAuth token was generated during login session")

        try:
            return json.loads(token_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SwitchError(f"invalid token generated: {exc}") from exc
