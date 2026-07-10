from typing import Any, Dict, Optional


class BrowserAdapter:
    """
    Handles communication with browser extensions via WebSocketBridge
    to resolve element data at logical desktop coordinates.
    """
    def __init__(self, ws_bridge: Any = None) -> None:
        self.ws_bridge = ws_bridge

    def is_browser_active(self, exe_name: str) -> bool:
        """Helper to verify if the active foreground process is a supported web browser."""
        from arrow.context.highlight_resolver import _is_browser
        return bool(_is_browser(exe_name))

    def inspect_element(self, x: int, y: int) -> Optional[Dict[str, Any]]:
        """Queries browser extension to inspect DOM element at (x, y)."""
        if not self.ws_bridge or not getattr(self.ws_bridge, "connected", False):
            return None
        try:
            result = self.ws_bridge.inspect(x, y, timeout=3.0)
            if result and result.get("status") == "ok":
                # Standardize return payload
                element = result.get("element")
                if isinstance(element, dict):
                    return element
                return result
        except Exception:
            pass
        return None
