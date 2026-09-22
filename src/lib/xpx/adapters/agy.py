from __future__ import annotations

import json
import os
import shutil
import subprocess
from contextlib import suppress
from pathlib import Path

from lib.common.common_store import atomic_write_bytes, ensure_private_dir
from lib.common.constants import SECRET_FILE_MODE
from lib.common.errors import SwitchError
from lib.common.jwt_helper import parse_jwt_claims
from lib.xpx.adapters.base import MergedProviderSpec, TargetAdapter, TargetStatus
from lib.xpx.store.account_store import AccountSpec


def get_agy_cli_dir() -> Path:
    override = os.environ.get("AGY_CLI_DIR")
    if override:
        return Path(override)
    override_home = os.environ.get("AGY_HOME")
    if override_home:
        return Path(override_home) / ".gemini" / "antigravity-cli"
    return Path.home() / ".gemini" / "antigravity-cli"


class AgyAdapter(TargetAdapter):
    name = "agy"
    display_name = "Antigravity CLI"
    supported_protocols = ["google-oauth"]
    binary_name = "agy"
    install_guide = (
        "Please install Antigravity CLI (AGY) according to your "
        "organization's setup guide."
    )

    def __init__(self, cli_dir: Path | None = None) -> None:
        self._cli_dir = cli_dir

    @property
    def cli_dir_path(self) -> Path:
        return self._cli_dir or get_agy_cli_dir()

    @property
    def token_path(self) -> Path:
        return self.cli_dir_path / "antigravity-oauth-token"

    @property
    def standalone_token_path(self) -> Path:
        return self.cli_dir_path / "jetski-standalone-oauth-token"

    def detect(self) -> bool:
        return self.cli_dir_path.is_dir() or shutil.which("agy") is not None

    def get_status(self) -> TargetStatus:
        ver = self.get_cli_version()
        bin_p = self.get_binary_path()
        if not self.token_path.is_file():
            return TargetStatus(
                installed=self.detect(),
                active_type="none",
                active_name="-",
                config_path=str(self.token_path),
                cli_version=ver,
                binary_path=bin_p,
            )
        try:
            raw = self.token_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            email = ""
            if isinstance(data, dict):
                id_token = data.get("id_token")
                if id_token:
                    claims = parse_jwt_claims(id_token)
                    email = claims.get("email", "")
            return TargetStatus(
                installed=True,
                active_type="account",
                active_name=email or "google-oauth",
                config_path=str(self.token_path),
                extra_summary=f"Identity: {email}" if email else "",
                cli_version=ver,
                binary_path=bin_p,
            )
        except Exception as exc:
            return TargetStatus(
                installed=True,
                active_type="error",
                active_name=f"read error: {exc}",
                config_path=str(self.token_path),
                cli_version=ver,
                binary_path=bin_p,
            )

    def apply(self, spec: MergedProviderSpec) -> None:
        raise SwitchError(
            "Antigravity uses Google OAuth accounts. "
            "Use 'xpx apply agy --account <name>' instead."
        )

    def apply_account(self, account: AccountSpec) -> None:
        ensure_private_dir(self.cli_dir_path)
        payload = (
            json.dumps(account.token_data, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        atomic_write_bytes(
            self.token_path,
            payload,
            secret=True,
            mode=SECRET_FILE_MODE,
        )
        atomic_write_bytes(
            self.standalone_token_path,
            payload,
            secret=True,
            mode=SECRET_FILE_MODE,
        )

    def clear(self) -> None:
        if self.token_path.is_file():
            try:
                self.token_path.unlink()
            except OSError as exc:
                raise SwitchError(f"unable to remove {self.token_path}: {exc}") from exc
        if self.standalone_token_path.is_file():
            with suppress(OSError):
                self.standalone_token_path.unlink()

    def ping(
        self, prompt: str, timeout: int, spec: MergedProviderSpec | None = None
    ) -> tuple[bool, str]:
        cmd = ["agy", "--version"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            out = proc.stdout.strip() or proc.stderr.strip()
            return proc.returncode == 0, out
        except Exception as exc:
            return False, str(exc)
