from typing import Any, Dict, Optional


class WindowsUIAAdapter:
    """
    Wraps native Windows UI Automation (UIA) to probe control details
    and accessibility tags at specific coordinates.
    """
    def __init__(self) -> None:
        pass

    def inspect_at_point(self, x: int, y: int) -> Optional[Dict[str, Any]]:
        """Probes the UIA tree at logical desktop coordinates (x, y)."""
        from arrow.context.highlight_resolver import _get_uia_info_at_point
        try:
            # Probe with pid=None to fetch whatever window is at that screen coordinate
            info = _get_uia_info_at_point(x, y, pid=None)
            if info:
                return {
                    "name": info.get("name", ""),
                    "type": info.get("type", ""),
                    "automation_id": info.get("automation_id", ""),
                }
        except Exception:
            pass
        return None
