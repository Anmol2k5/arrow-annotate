"""
Provider interface and shared CLI plumbing (Phase 13).

Direct execution is an *optional* convenience on top of the MCP integration. All
providers share the interface:

    detect()        -> is the tool installed?
    validate()      -> can we run against this repository?
    start_run()     -> launch a run (confined to the repository)
    stream_events() -> iterate progress events
    cancel_run()    -> stop a run
    get_status()    -> current provider status

Execution rules enforced here:
  * Commands are never executed via a shell (no ``shell=True``); argument lists
    only.
  * Runs start in the selected repository working directory. This alone is not
    a sandbox; adapters must use the CLI's supported sandbox/permission controls.
  * ``confirm_command`` can guard commands explicitly submitted to it. A child
    CLI's internal tool calls are not intercepted by this subprocess adapter.
  * Authentication tokens are never read or stored.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Iterator, Optional

from pydantic import BaseModel, Field

log = logging.getLogger("arrow.providers")


class ProviderStatus(str, Enum):
    NOT_INSTALLED = "not_installed"
    IDLE = "idle"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SafetyCategory(str, Enum):
    DELETE_FILES = "delete_files"
    DESTRUCTIVE_COMMAND = "destructive_command"
    MODIFY_OUTSIDE_REPO = "modify_outside_repo"
    INSTALL_PACKAGES = "install_packages"
    COMMIT = "commit"
    PUSH = "push"
    ACCESS_UNRELATED = "access_unrelated"


# A confirmation callback returns True to allow the sensitive action.
ConfirmFn = Callable[[SafetyCategory, str], bool]


def default_deny(category: SafetyCategory, detail: str) -> bool:
    """Safe default: deny every sensitive action unless a real prompt overrides."""
    log.warning("Denying %s by default: %s", category.value, detail)
    return False


class ProviderEvent(BaseModel):
    type: str  # "status" | "log" | "output" | "error" | "done"
    message: str = ""
    data: dict = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ValidationResult(BaseModel):
    ok: bool
    reason: Optional[str] = None


class RunRequest(BaseModel):
    capture_id: str
    repository_path: str
    prompt: str
    assets: dict = Field(default_factory=dict)


class Provider(ABC):
    name: str = "provider"

    @abstractmethod
    def detect(self) -> bool: ...

    @abstractmethod
    def validate(self, repository_path: str) -> ValidationResult: ...

    @abstractmethod
    def start_run(self, request: RunRequest) -> None: ...

    @abstractmethod
    def stream_events(self) -> Iterator[ProviderEvent]: ...

    @abstractmethod
    def cancel_run(self) -> None: ...

    @abstractmethod
    def get_status(self) -> ProviderStatus: ...


# Patterns that indicate a destructive shell command an agent might attempt.
_DESTRUCTIVE_PATTERNS = {
    SafetyCategory.DELETE_FILES: ("rm -rf", "del /", "remove-item", "rmdir"),
    SafetyCategory.PUSH: ("git push",),
    SafetyCategory.COMMIT: ("git commit",),
    SafetyCategory.INSTALL_PACKAGES: ("npm install -g", "pip install", "choco install", "winget install"),
}


def classify_command(command: str) -> Optional[SafetyCategory]:
    """Classify a command string into a safety category, if it is sensitive."""
    lowered = command.lower()
    for category, patterns in _DESTRUCTIVE_PATTERNS.items():
        if any(p in lowered for p in patterns):
            return category
    return None


class BaseCLIProvider(Provider):
    """Shared subprocess plumbing for CLI-based providers.

    Args:
        cli_name: Executable to detect on PATH.
        confirm: Confirmation callback for sensitive actions.
        which_fn / popen_fn: Injected for testing.
    """

    cli_name: str = ""
    npm_package: str = ""

    def __init__(
        self,
        confirm: ConfirmFn = default_deny,
        which_fn: Callable[[str], Optional[str]] = shutil.which,
        popen_fn: Optional[Callable[..., subprocess.Popen]] = None,
    ):
        self._confirm = confirm
        self._which = which_fn
        self._popen = popen_fn or subprocess.Popen
        self._process: Optional[subprocess.Popen] = None
        self._stdin_payload: Optional[str] = None
        self._status = ProviderStatus.IDLE
        self._lock = threading.Lock()

    # -- interface -------------------------------------------------------

    def detect(self) -> bool:
        found = self._which(self.cli_name) is not None
        if not found:
            self._status = ProviderStatus.NOT_INSTALLED
        return found

    def validate(self, repository_path: str) -> ValidationResult:
        if not self.detect():
            return ValidationResult(ok=False, reason=f"{self.cli_name} not found on PATH.")
        if not repository_path or not os.path.isdir(repository_path):
            return ValidationResult(ok=False, reason="Repository path does not exist.")
        self._status = ProviderStatus.READY
        return ValidationResult(ok=True)

    def build_command(self, request: RunRequest) -> list[str]:  # pragma: no cover - overridden
        raise NotImplementedError

    def build_stdin(self, request: RunRequest) -> Optional[str]:
        """Return a one-shot stdin payload, or None for argv-only providers."""
        return None

    def _resolve_command(self, command: list[str]) -> list[str]:
        """Bypass Windows npm shell shims using their package's declared bin."""
        executable = self._which(command[0]) or command[0]
        shim = Path(executable)
        if shim.suffix.lower() not in {".cmd", ".bat"}:
            return [executable, *command[1:]]
        if not self.npm_package:
            raise RuntimeError("Cannot launch a shell wrapper as a provider executable")

        modules = shim.parent.parent if shim.parent.name == ".bin" else shim.parent / "node_modules"
        package = (modules / self.npm_package).resolve()
        try:
            manifest = json.loads((package / "package.json").read_text(encoding="utf-8"))
            declared_bin = manifest["bin"]
            entry = declared_bin[self.cli_name] if isinstance(declared_bin, dict) else declared_bin
            if not isinstance(entry, str):
                raise ValueError("bin entry is not a path")
            target = (package / entry).resolve()
            if not target.is_relative_to(package) or not target.is_file():
                raise ValueError("bin entry is missing or outside its package")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise RuntimeError(f"Cannot resolve {self.cli_name} npm installation: {exc}") from exc

        # New Claude npm releases declare a native executable; older releases
        # and Codex declare JavaScript. Neither path needs cmd.exe or shell=True.
        if target.suffix.lower() == ".exe":
            return [str(target), *command[1:]]
        if target.suffix.lower() not in {".js", ".cjs", ".mjs"}:
            raise RuntimeError(f"Unsupported {self.cli_name} npm executable: {target.name}")
        adjacent_node = shim.parent / "node.exe"
        node = str(adjacent_node) if adjacent_node.is_file() else self._which("node")
        if not node or Path(node).suffix.lower() in {".cmd", ".bat", ".ps1"}:
            raise RuntimeError(f"Node.js executable not found for {self.cli_name} npm installation")
        return [node, str(target), *command[1:]]

    def start_run(self, request: RunRequest) -> None:
        with self._lock:
            if self._status == ProviderStatus.RUNNING or (self._process and self._process.poll() is None):
                raise RuntimeError("Provider run is already running")
            validation = self.validate(request.repository_path)
            if not validation.ok:
                self._status = ProviderStatus.FAILED
                raise RuntimeError(validation.reason)

            try:
                command = self._resolve_command(self.build_command(request))
                self._stdin_payload = self.build_stdin(request)
                # Never use shell=True; confine cwd to the repository. Prevent
                # argv-only CLIs from accidentally consuming the parent's stdin.
                log.info("Starting %s run in %s", self.name, request.repository_path)
                self._process = self._popen(
                    command,
                    cwd=request.repository_path,
                    stdin=subprocess.PIPE if self._stdin_payload is not None else subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    # Python-backed integrations must agree with our UTF-8
                    # stream protocol even on Windows legacy code pages.
                    env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
                    bufsize=1,
                )
            except Exception:
                self._status = ProviderStatus.FAILED
                raise
            self._status = ProviderStatus.RUNNING

    def stream_events(self) -> Iterator[ProviderEvent]:
        process = self._process
        if process is None:
            return
        yield ProviderEvent(type="status", message="Sending context")
        payload = self._stdin_payload
        input_errors: list[Exception] = []
        writer = None
        if payload is not None:
            def send_input():
                try:
                    if process.stdin is None:
                        raise RuntimeError("Provider stdin is unavailable")
                    process.stdin.write(payload)
                except Exception as exc:
                    input_errors.append(exc)
                finally:
                    if process.stdin is not None:
                        try:
                            process.stdin.close()
                        except Exception as exc:
                            input_errors.append(exc)

            # Drain stdout concurrently: an image can exceed pipe capacity while
            # the child is still emitting startup output. Never hold _lock while
            # writing so cancel_run can terminate a child that is not reading.
            writer = threading.Thread(target=send_input, daemon=True)
            writer.start()
        stdout = process.stdout
        if stdout is not None:
            for line in stdout:
                line = line.rstrip("\n")
                if line:
                    yield ProviderEvent(type="log", message=line)
        return_code = process.wait()
        if writer is not None:
            writer.join()
        if self._status == ProviderStatus.CANCELLED:
            yield ProviderEvent(type="done", message="Cancelled")
            return
        if return_code == 0 and input_errors:
            self._status = ProviderStatus.FAILED
            yield ProviderEvent(type="error", message=f"Failed to send provider stdin: {input_errors[0]}")
        elif return_code == 0:
            self._status = ProviderStatus.COMPLETED
            yield ProviderEvent(type="done", message="Completed")
        else:
            self._status = ProviderStatus.FAILED
            yield ProviderEvent(type="error", message=f"Exited with code {return_code}")

    def cancel_run(self) -> None:
        with self._lock:
            if self._process and self._process.poll() is None:
                self._status = ProviderStatus.CANCELLED
                try:
                    self._process.terminate()
                except Exception as e:  # pragma: no cover
                    log.warning("terminate failed: %s", e)

    def get_status(self) -> ProviderStatus:
        return self._status

    def confirm_command(self, command: str) -> bool:
        category = classify_command(command)
        if category is None:
            return True
        return self._confirm(category, command)


__all__ = [
    "Provider",
    "BaseCLIProvider",
    "ProviderStatus",
    "ProviderEvent",
    "ValidationResult",
    "RunRequest",
    "SafetyCategory",
    "ConfirmFn",
    "default_deny",
    "classify_command",
]
