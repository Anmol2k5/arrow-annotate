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

import logging
import os
import shutil
import subprocess
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
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

    def start_run(self, request: RunRequest) -> None:
        with self._lock:
            if self._status == ProviderStatus.RUNNING or (self._process and self._process.poll() is None):
                raise RuntimeError("Provider run is already running")
            validation = self.validate(request.repository_path)
            if not validation.ok:
                self._status = ProviderStatus.FAILED
                raise RuntimeError(validation.reason)

            command = self.build_command(request)
            # Never use shell=True; confine cwd to the repository.
            log.info("Starting %s run in %s", self.name, request.repository_path)
            self._process = self._popen(
                command,
                cwd=request.repository_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            self._status = ProviderStatus.RUNNING

    def stream_events(self) -> Iterator[ProviderEvent]:
        if self._process is None:
            return
        yield ProviderEvent(type="status", message="Sending context")
        stdout = self._process.stdout
        if stdout is not None:
            for line in stdout:
                line = line.rstrip("\n")
                if line:
                    yield ProviderEvent(type="log", message=line)
        return_code = self._process.wait()
        if self._status == ProviderStatus.CANCELLED:
            yield ProviderEvent(type="done", message="Cancelled")
            return
        if return_code == 0:
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
