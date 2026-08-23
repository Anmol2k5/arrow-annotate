"""
Arrow MCP resources (Phase 12).

Exposes capture screenshot assets as MCP resources under the ``arrow://`` scheme:

    arrow://captures/{capture_id}/raw
    arrow://captures/{capture_id}/annotated
    arrow://captures/{capture_id}/context-crop
    arrow://captures/{capture_id}/source-crop
    arrow://captures/{capture_id}/destination-crop
"""

from __future__ import annotations

import base64
import os
import re
from typing import Optional

from arrow.storage.repository import Repository

# Resource asset key -> stored asset type.
_ASSET_KEYS = {
    "raw": "raw",
    "annotated": "annotated",
    "context-crop": "context-crop",
    "source-crop": "source-crop",
    "destination-crop": "destination-crop",
    "agent-annotated": "agent-annotated",
    "agent-crop": "agent-crop",
}

_URI_RE = re.compile(r"^arrow://captures/(?P<cid>[^/]+)/(?P<asset>[a-z-]+)$")

_MIME = "image/png"


class ResourceProvider:
    def __init__(self, repository: Repository):
        self.repo = repository

    def uri_for(self, capture_id: str, asset_key: str) -> str:
        return f"arrow://captures/{capture_id}/{asset_key}"

    def list_resources(self) -> list[dict]:
        resources: list[dict] = []
        for cap in self.repo.list_captures(limit=100):
            for asset_key in cap.get("assets", {}):
                if asset_key in _ASSET_KEYS:
                    resources.append({
                        "uri": self.uri_for(cap["capture_id"], asset_key),
                        "name": f"{cap['capture_id']} {asset_key}",
                        "mimeType": _MIME,
                    })
        return resources

    def resolve_path(self, uri: str) -> Optional[str]:
        m = _URI_RE.match(uri)
        if not m:
            return None
        asset_key = m.group("asset")
        asset_type = _ASSET_KEYS.get(asset_key)
        if not asset_type:
            return None
        path = self.repo.get_asset_path(m.group("cid"), asset_type)
        if path and os.path.isfile(path):
            return path
        return None

    def read_resource(self, uri: str) -> dict:
        """Return an MCP resource-content dict with base64 blob."""
        path = self.resolve_path(uri)
        if path is None:
            raise FileNotFoundError(f"Resource not found: {uri}")
        with open(path, "rb") as f:
            blob = base64.b64encode(f.read()).decode("ascii")
        return {"uri": uri, "mimeType": _MIME, "blob": blob}


__all__ = ["ResourceProvider"]
