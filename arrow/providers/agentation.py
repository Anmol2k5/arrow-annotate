import logging
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

DEFAULT_BASE = "http://127.0.0.1:4747"
DEFAULT_SOURCE_URL = "bluely://desktop"


class AgentationError(Exception):
    pass


def pick_session_id(sessions: Optional[list]) -> Optional[str]:
    """Return the first usable session id from a list response.

    Skips entries that are not objects or have no id, so a single malformed
    session can never break the handoff.
    """
    for item in sessions or []:
        if isinstance(item, dict) and item.get("id"):
            return str(item["id"])
    return None


def send_capture_annotation(
    client: "AgentationClient",
    record: Any,
    image_url: str,
    source_url: str = DEFAULT_SOURCE_URL,
) -> str:
    """Hand one capture to Agentation; returns the session id used.

    Reuses an existing Agentation session when one exists (picking the first
    entry with a valid id instead of blindly trusting ``sessions[0]``),
    otherwise creates one. Raises :class:`AgentationError` when Agentation is
    unreachable or rejects the call — callers degrade (fail the capture
    session and surface a status message) instead of crashing.
    """
    sessions = client.list_sessions()
    session_id = pick_session_id(sessions)
    if not session_id:
        created = client.create_session(source_url)
        session_id = str(created.get("id") or "")
        if not session_id:
            raise AgentationError("Agentation create_session returned no session id")

    client.add_annotation(
        session_id,
        {
            "comment": getattr(record, "annotation_text", "") or "Visual highlight",
            "element": "desktop_screen",
            "elementPath": "desktop",
            "imagePath": image_url,
        },
    )
    return session_id


class AgentationClient:
    """HTTP client for the Agentation MCP API.

    See https://github.com/benjitaylor/agentation/tree/main/mcp
    """

    def __init__(self, base_url: str = DEFAULT_BASE):
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def create_session(self, url: str, project_id: Optional[str] = None) -> dict:
        payload: dict[str, Any] = {"url": url}
        if project_id:
            payload["projectId"] = project_id
        return self._post("/sessions", payload, expected=201)

    def list_sessions(self) -> list[dict]:
        return self._get("/sessions")

    def get_session(self, session_id: str) -> dict:
        return self._get(f"/sessions/{session_id}")

    def close_session(self, session_id: str) -> dict:
        return self._patch(f"/annotations/{session_id}", {"status": "closed"})

    # ------------------------------------------------------------------
    # Annotations
    # ------------------------------------------------------------------

    def add_annotation(self, session_id: str, data: dict) -> dict:
        required = ("comment", "element", "elementPath")
        missing = [k for k in required if k not in data]
        if missing:
            raise AgentationError(f"Missing required annotation fields: {missing}")
        return self._post(f"/sessions/{session_id}/annotations", data, expected=201)

    def update_annotation(self, annotation_id: str, data: dict) -> dict:
        return self._patch(f"/annotations/{annotation_id}", data)

    def get_annotation(self, annotation_id: str) -> dict:
        return self._get(f"/annotations/{annotation_id}")

    # ------------------------------------------------------------------
    # Pending / Status
    # ------------------------------------------------------------------

    def get_pending(self, session_id: str) -> list[dict]:
        resp = self._get(f"/sessions/{session_id}/pending")
        return resp.get("annotations", [])

    def get_all_pending(self) -> list[dict]:
        resp = self._get("/pending")
        return resp.get("annotations", [])

    # ------------------------------------------------------------------
    # Action
    # ------------------------------------------------------------------

    def request_action(self, session_id: str, output: str = "") -> dict:
        return self._post(f"/sessions/{session_id}/action", {"output": output})

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> dict:
        return self._get("/health")

    def status(self) -> dict:
        return self._get("/status")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        try:
            resp = self._session.get(url, timeout=5)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            raise AgentationError(f"GET {path} failed: {e}") from e

    def _post(self, path: str, data: dict, expected: int = 200) -> Any:
        url = f"{self.base_url}{path}"
        try:
            resp = self._session.post(url, json=data, timeout=5)
            if resp.status_code != expected:
                logger.warning("POST %s -> %s (expected %s): %s", path, resp.status_code, expected, resp.text)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            raise AgentationError(f"POST {path} failed: {e}") from e

    def _patch(self, path: str, data: dict) -> Any:
        url = f"{self.base_url}{path}"
        try:
            resp = self._session.patch(url, json=data, timeout=5)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            raise AgentationError(f"PATCH {path} failed: {e}") from e


def client_from_config() -> AgentationClient:
    """Build a client from validated config (``ARROW_AGENTATION_URL``)."""
    from arrow.core.config import get_config

    return AgentationClient(base_url=get_config().agentation_url)
