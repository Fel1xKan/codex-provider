from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import time
from pathlib import Path
from typing import Any

import tomlkit

from lib.common.common_store import atomic_write_bytes, ensure_private_dir
from lib.common.constants import SECRET_FILE_MODE
from lib.common.errors import SwitchError
from lib.xpx.adapters.base import (
    MergedProviderSpec,
    TargetAdapter,
    TargetStatus,
    count_active_cli_instances,
    run_probe_command,
)
from lib.xpx.models.catalog import get_consolidated_provider_models
from lib.xpx.store.catalog_store import ModelMetadata

# Codex persists a provider key per thread and refuses to resume when that key
# no longer matches the active top-level ``model_provider``. Writing one fixed
# runtime key lets xpx change endpoints without invalidating saved sessions.
RUNTIME_PROVIDER_KEY = "xpx"

# Codex writes this format into daemon.pid; ps pads single-digit days with an
# extra space, so callers normalize whitespace before parsing.
_DAEMON_START_FORMAT = "%a %b %d %H:%M:%S %Y"

# auth.json is written moments before/after a daemon start during apply; ignore
# sub-second ordering noise instead of flapping the daemon on every command.
_DAEMON_START_TOLERANCE = 1.0

_FALLBACK_REASONING_LEVELS: tuple[str, ...] = (
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)

_LEVEL_DESCRIPTIONS = {
    "none": "Model does not reason",
    "minimal": "Fastest responses with minimal reasoning",
    "low": "Fast responses with lighter reasoning",
    "medium": "Balances speed and reasoning depth for everyday tasks",
    "high": "Greater reasoning depth for complex problems",
    "xhigh": "Extra high reasoning depth for complex problems",
    "max": "Maximum reasoning depth for the hardest problems",
    "ultra": "Maximum reasoning with automatic task delegation",
}

_PREFERRED_DEFAULT_LEVELS: tuple[str, ...] = (
    "medium",
    "high",
    "low",
    "minimal",
    "xhigh",
    "max",
    "ultra",
    "none",
)


def _pid_alive(pid: int) -> bool:
    """Return False for missing and zombie pids so a stale pid file is never fatal."""
    if pid <= 0:
        return False
    if Path("/proc").is_dir():
        stat_path = Path(f"/proc/{pid}/stat")
        if not stat_path.exists():
            return False
        with contextlib.suppress(OSError, IndexError):
            state = stat_path.read_text(encoding="utf-8", errors="replace")
            state = state.rsplit(")", 1)[1].split()[0]
            if state == "Z":
                return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _proc_cmdline(pid: int) -> str | None:
    """Read a Linux process command line; None when the platform has no /proc."""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except FileNotFoundError:
        return None if not Path("/proc").is_dir() else ""
    except OSError:
        return None
    return raw.replace(b"\0", b" ").decode("utf-8", "replace").strip()


def _pick_default_reasoning_level(
    levels: list[str], configured_default: str | None
) -> str:
    if configured_default and configured_default in levels:
        return configured_default
    for cand in _PREFERRED_DEFAULT_LEVELS:
        if cand in levels:
            return cand
    return levels[0] if levels else "medium"


def _build_codex_model_entry(meta: ModelMetadata) -> dict[str, Any]:
    levels = meta.supported_reasoning_levels or list(_FALLBACK_REASONING_LEVELS)
    def_level = _pick_default_reasoning_level(levels, meta.default_reasoning_level)
    supported_levels = [
        {"effort": eff, "description": _LEVEL_DESCRIPTIONS.get(eff, eff)}
        for eff in levels
    ]
    input_modalities = [
        m for m in meta.input_modalities if m in ("text", "image", "audio")
    ]
    if not input_modalities:
        input_modalities = ["text"]
    elif "text" not in input_modalities:
        input_modalities.insert(0, "text")

    ctx = meta.context_window or 1048576
    max_tokens = meta.max_output_tokens or 8192

    return {
        "slug": meta.id,
        "display_name": meta.display_name or meta.id,
        "description": f"Synced from provider /models: {meta.id}",
        "default_reasoning_level": def_level,
        "supported_reasoning_levels": supported_levels,
        "shell_type": "shell_command",
        "visibility": "list",
        "supported_in_api": True,
        "priority": 0,
        "base_instructions": "",
        "supports_reasoning_summaries": True,
        "default_reasoning_summary": "none",
        "support_verbosity": False,
        "apply_patch_tool_type": "freeform",
        "truncation_policy": {"mode": "bytes", "limit": 10000},
        "context_window": ctx,
        "max_context_window": ctx,
        "effective_context_window_percent": 95,
        "supports_parallel_tool_calls": True,
        "experimental_supported_tools": [],
        "input_modalities": input_modalities,
        "max_output_tokens": max_tokens,
    }


def get_codex_home() -> Path:
    override = os.environ.get("CODEX_HOME")
    if override:
        return Path(override)
    return Path.home() / ".codex"


def resolve_active_provider_name(doc: Any) -> str:
    """Return the real provider name behind Codex's configured provider key."""
    key = str(doc.get("model_provider", "") or "")
    if key != RUNTIME_PROVIDER_KEY:
        return key
    providers = doc.get("model_providers")
    if isinstance(providers, dict):
        block = providers.get(key)
        if isinstance(block, dict):
            name = block.get("name")
            if name:
                return str(name)
    return key


class CodexAdapter(TargetAdapter):
    name = "codex"
    display_name = "Codex CLI"
    supported_protocols = ["openai"]
    binary_name = "codex"
    package_name = "@openai/codex"
    supports_fast = True
    supports_web_search = True
    supports_wire_api = True

    def __init__(self, home: Path | None = None) -> None:
        self._home = home

    @property
    def home_dir(self) -> Path:
        return self._home or get_codex_home()

    @property
    def config_path(self) -> Path:
        return self.home_dir / "config.toml"

    @property
    def auth_path(self) -> Path:
        return self.home_dir / "auth.json"

    @property
    def models_path(self) -> Path:
        return self.home_dir / "models.json"

    def detect(self) -> bool:
        return self.home_dir.is_dir() or shutil.which("codex") is not None

    def get_status(self) -> TargetStatus:
        ver = self.get_cli_version()
        bin_p = self.get_binary_path()
        if not self.config_path.is_file():
            return TargetStatus(
                installed=self.detect(),
                active_type="none",
                active_name="-",
                config_path=str(self.config_path),
                cli_version=ver,
                binary_path=bin_p,
            )
        try:
            doc = tomlkit.parse(self.config_path.read_text(encoding="utf-8"))
            active_key = str(doc.get("model_provider", "") or "")
            active_provider = resolve_active_provider_name(doc)
            active_model = doc.get("model")
            if active_model is not None:
                active_model = str(active_model)
            fast_mode = doc.get("service_tier") == "priority"
            extra = "fast" if fast_mode else ""
            if not active_key or active_key == "openai":
                return TargetStatus(
                    installed=True,
                    active_type="official" if active_key == "openai" else "none",
                    active_name="openai" if active_key == "openai" else "-",
                    active_model=active_model,
                    config_path=str(self.config_path),
                    extra_summary=extra,
                    cli_version=ver,
                    binary_path=bin_p,
                )
            return TargetStatus(
                installed=True,
                active_type="provider",
                active_name=active_provider,
                active_model=active_model,
                config_path=str(self.config_path),
                extra_summary=extra,
                cli_version=ver,
                binary_path=bin_p,
            )
        except Exception as exc:
            return TargetStatus(
                installed=True,
                active_type="error",
                active_name=f"parse error: {exc}",
                config_path=str(self.config_path),
                cli_version=ver,
                binary_path=bin_p,
            )

    def _generate_codex_models(
        self,
        provider_name: str,
        applied_model: str | None = None,
        previous_model: str | None = None,
    ) -> list[dict[str, Any]]:
        models_map = get_consolidated_provider_models(
            provider_name=provider_name,
            applied_model=applied_model,
            previous_model=previous_model,
        )
        codex_models = [_build_codex_model_entry(meta) for meta in models_map.values()]
        codex_models.sort(key=lambda x: str(x.get("slug", "")).lower())
        return codex_models

    def refresh_catalog(self, provider_name: str | None = None) -> bool:
        if not self.config_path.is_file():
            return False
        try:
            doc = tomlkit.parse(self.config_path.read_text(encoding="utf-8"))
            active_key = str(doc.get("model_provider", "") or "")
            active_pv = resolve_active_provider_name(doc)
            if not active_key or active_key == "openai":
                return False
            if provider_name and provider_name != active_pv:
                return False

            current_model = doc.get("model")
            if current_model is not None:
                current_model = str(current_model)

            codex_models = self._generate_codex_models(
                provider_name=active_pv,
                applied_model=current_model,
                previous_model=None,
            )

            payload = (
                json.dumps({"models": codex_models}, indent=2, ensure_ascii=False)
                + "\n"
            ).encode("utf-8")
            atomic_write_bytes(self.models_path, payload)

            models_path_str = str(self.models_path)
            if doc.get("model_catalog_json") != models_path_str:
                doc["model_catalog_json"] = models_path_str
                atomic_write_bytes(self.config_path, tomlkit.dumps(doc).encode("utf-8"))
            return True
        except Exception:
            return False

    def apply(self, spec: MergedProviderSpec) -> None:
        ensure_private_dir(self.home_dir)
        doc = tomlkit.document()
        previous_model: str | None = None
        if self.config_path.is_file():
            try:
                doc = tomlkit.parse(self.config_path.read_text(encoding="utf-8"))
                raw_prev = doc.get("model")
                if raw_prev is not None:
                    previous_model = str(raw_prev)
            except Exception as exc:
                raise SwitchError(f"unable to parse {self.config_path}: {exc}") from exc

        # Ensure model_providers table exists
        if "model_providers" not in doc or not isinstance(doc["model_providers"], dict):
            doc["model_providers"] = tomlkit.table()
        providers_table = doc["model_providers"]

        pv_table = tomlkit.table()
        pv_table["name"] = spec.name
        pv_table["base_url"] = spec.base_url
        pv_table["wire_api"] = spec.wire_api or "responses"
        pv_table["requires_openai_auth"] = True

        if spec.headers:
            headers_table = tomlkit.inline_table()
            for k, v in sorted(spec.headers.items()):
                headers_table.add(k, v)
            pv_table["http_headers"] = headers_table

        providers_table[RUNTIME_PROVIDER_KEY] = pv_table

        # Top-level settings. The key is fixed so saved Codex sessions keep
        # matching regardless of which provider xpx applies next.
        doc["model_provider"] = RUNTIME_PROVIDER_KEY
        if spec.model:
            doc["model"] = spec.model

        if "model_reasoning_effort" in doc:
            del doc["model_reasoning_effort"]

        if spec.fast is True:
            doc["service_tier"] = "priority"
        elif spec.fast is False and "service_tier" in doc:
            del doc["service_tier"]

        if spec.web_search is True:
            doc["web_search"] = "live"
        elif spec.web_search is False and "web_search" in doc:
            del doc["web_search"]

        # Generate models.json catalog for Codex
        codex_models = self._generate_codex_models(
            provider_name=spec.name,
            applied_model=spec.model,
            previous_model=previous_model,
        )
        catalog_payload = (
            json.dumps({"models": codex_models}, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        atomic_write_bytes(self.models_path, catalog_payload)

        doc["model_catalog_json"] = str(self.models_path)

        atomic_write_bytes(self.config_path, tomlkit.dumps(doc).encode("utf-8"))

        # Write auth
        auth_data = {}
        if self.auth_path.is_file():
            try:
                auth_data = json.loads(self.auth_path.read_text(encoding="utf-8"))
                if not isinstance(auth_data, dict):
                    auth_data = {}
            except Exception:
                auth_data = {}
        auth_data["OPENAI_API_KEY"] = spec.api_key
        atomic_write_bytes(
            self.auth_path,
            (json.dumps(auth_data, indent=2) + "\n").encode("utf-8"),
            secret=True,
            mode=SECRET_FILE_MODE,
        )

    def clear(self) -> None:
        if self.config_path.is_file():
            try:
                doc = tomlkit.parse(self.config_path.read_text(encoding="utf-8"))
                doc["model_provider"] = "openai"
                if "service_tier" in doc:
                    del doc["service_tier"]
                if "web_search" in doc:
                    del doc["web_search"]
                if "model_reasoning_effort" in doc:
                    del doc["model_reasoning_effort"]
                if "model_catalog_json" in doc:
                    del doc["model_catalog_json"]
                atomic_write_bytes(self.config_path, tomlkit.dumps(doc).encode("utf-8"))
            except Exception as exc:
                raise SwitchError(f"unable to reset {self.config_path}: {exc}") from exc
        if self.models_path.is_file():
            with contextlib.suppress(OSError):
                self.models_path.unlink()

    def ping(
        self, prompt: str, timeout: int, spec: MergedProviderSpec | None = None
    ) -> tuple[bool, str]:
        # `--ephemeral` keeps a probe from writing a session file under
        # ~/.codex/sessions, and `--skip-git-repo-check` lets the probe run in a
        # directory that is not a trusted git repo (where `codex exec` would
        # otherwise refuse with "Not inside a trusted directory").
        if spec is not None:
            return False, (
                "provider-scoped deep test is not supported for codex; "
                f"run 'xpx apply codex {spec.name}' first, then "
                "'xpx test --deep --target codex'"
            )
        cmd = ["codex", "exec", "--ephemeral", "--skip-git-repo-check", prompt]
        return run_probe_command(cmd, timeout)

    @property
    def daemon_sock_path(self) -> Path:
        return self.home_dir / "app-server-control" / "app-server-control.sock"

    @property
    def daemon_pid_path(self) -> Path:
        return self.home_dir / "app-server-daemon" / "daemon.pid"

    def _read_daemon_pid(self) -> tuple[int, float | None] | None:
        """Return (pid, start_epoch) for the managed app-server daemon."""
        try:
            data = json.loads(self.daemon_pid_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        try:
            pid = int(data.get("pid") or 0)
        except (TypeError, ValueError):
            return None
        if pid <= 0:
            return None
        started: float | None = None
        raw = data.get("processStartTime")
        if isinstance(raw, str) and raw.strip():
            with contextlib.suppress(ValueError, OverflowError):
                started = time.mktime(
                    time.strptime(" ".join(raw.split()), _DAEMON_START_FORMAT)
                )
        if started is None:
            # Older Codex builds omit processStartTime; the pid file is rewritten
            # on every start, so its mtime is a usable lower bound.
            with contextlib.suppress(OSError):
                started = self.daemon_pid_path.stat().st_mtime
        return pid, started

    def _credentials_changed_since(self, since: float | None) -> bool:
        """True when credentials/config were written after the daemon started.

        Codex caches the API key in the app-server process at start-up while it
        reloads ``config.toml`` per thread. A daemon older than the last apply
        therefore sends the new base_url with the previous provider's key, and
        the endpoint answers ``401 INVALID_API_KEY``.
        """
        if since is None:
            return True
        newest = 0.0
        for path in (self.auth_path, self.config_path):
            with contextlib.suppress(OSError):
                newest = max(newest, path.stat().st_mtime)
        return newest > since + _DAEMON_START_TOLERANCE

    def _drop_stale_pid_file(self, pid: int) -> None:
        info = self._read_daemon_pid()
        if info is not None and info[0] != pid:
            return  # a fresh daemon already rewrote it
        with contextlib.suppress(OSError):
            self.daemon_pid_path.unlink()

    def _stop_daemon(self, pid: int) -> tuple[bool, str]:
        """Terminate the managed app-server directly.

        ``codex app-server daemon restart`` is not usable here: it asks the old
        daemon to drain and blocks while any client is still attached (measured
        >60s), so a short timeout would leave the exchange half-done. Signalling
        the pid lets the next Codex launch bootstrap a daemon that reads the
        freshly applied auth.json.
        """
        if not _pid_alive(pid):
            return True, ""
        cmdline = _proc_cmdline(pid)
        if cmdline is not None and "app-server" not in cmdline:
            return False, f"pid {pid} is not a Codex app-server"

        ladder: list[tuple[int, float]] = [(signal.SIGTERM, 3.0)]
        sigkill = getattr(signal, "SIGKILL", None)
        if sigkill is not None:
            ladder.append((sigkill, 2.0))

        for sig, budget in ladder:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                return True, ""
            except PermissionError as exc:
                return False, f"permission denied signalling pid {pid}: {exc}"
            except OSError as exc:
                return False, f"{exc}"
            deadline = time.monotonic() + budget
            while time.monotonic() < deadline:
                if not _pid_alive(pid):
                    return True, ""
                time.sleep(0.1)

        return False, f"daemon (pid {pid}) ignored SIGTERM and SIGKILL"

    def refresh_daemon(self, force: bool = False) -> tuple[bool, str]:
        """Stop a daemon whose cached credentials predate the applied config."""
        info = self._read_daemon_pid()
        if info is None:
            if self.daemon_sock_path.exists():
                return False, (
                    "a Codex app-server is running but its pid file is missing, "
                    "so it keeps the previous credentials: restart Codex to load "
                    "the applied key."
                )
            return False, ""

        pid, started = info
        if not _pid_alive(pid):
            # Daemon already exited; the next launch reads auth.json anyway.
            self._drop_stale_pid_file(pid)
            return False, ""

        if not force:
            if not self._credentials_changed_since(started):
                return False, ""
            active_count = count_active_cli_instances(
                self.binary_name,
                daemon_patterns=["app-server", "pid-update-loop"],
            )
            if active_count > 0:
                return False, (
                    f"Codex daemon (pid {pid}) still holds credentials from before "
                    f"this apply, so {active_count} running Codex session(s) keep "
                    "failing with 401 until they are restarted; re-run with "
                    "--restart-daemon to stop the daemon now."
                )

        stopped, reason = self._stop_daemon(pid)
        if not stopped:
            return False, (
                f"could not stop the Codex daemon (pid {pid}), so it keeps the old "
                f"credentials and will keep failing with 401: {reason}"
            )

        self._drop_stale_pid_file(pid)
        return True, (
            f"Stopped the stale Codex daemon (pid {pid}); the next Codex launch "
            "starts a fresh daemon that reads the applied credentials."
        )
