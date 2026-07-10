from typing import Dict, List, Tuple


class ScreenInfo:
    def __init__(self, name: str, geometry: Tuple[int, int, int, int], scale: float):
        self.name = name
        self.x, self.y, self.w, self.h = geometry
        self.scale = scale

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x < self.x + self.w and self.y <= y < self.y + self.h


class CoordinateMapper:
    """
    Maps coordinates between:
      - Virtual desktop coordinates (Qt logical coordinates, might be negative)
      - Monitor-local logical coordinates
      - Physical monitor pixels (using devicePixelRatio/scale)
    """
    def __init__(self, screens: List[ScreenInfo]):
        self.screens = screens

    @classmethod
    def from_qt(cls) -> "CoordinateMapper":
        """Construct from active PyQt screens."""
        from PyQt6.QtWidgets import QApplication
        screens_info = []
        for i, s in enumerate(QApplication.screens()):
            geom = s.geometry()
            screens_info.append(ScreenInfo(
                name=s.name() or f"Screen_{i}",
                geometry=(geom.x(), geom.y(), geom.width(), geom.height()),
                scale=s.devicePixelRatio()
            ))
        return cls(screens_info)

    def find_screen(self, x: float, y: float) -> ScreenInfo:
        """Finds the screen containing virtual coordinate (x, y)."""
        for s in self.screens:
            if s.contains(x, y):
                return s
        # Fallback: find the closest screen
        if not self.screens:
            raise ValueError("No screens configured in CoordinateMapper")
        
        closest = self.screens[0]
        min_dist = float("inf")
        for s in self.screens:
            # calculate distance to center of screen bounds
            cx = s.x + s.w / 2
            cy = s.y + s.h / 2
            dist = (x - cx) ** 2 + (y - cy) ** 2
            if dist < min_dist:
                min_dist = dist
                closest = s
        return closest

    def virtual_to_monitor_local(self, x: float, y: float) -> Tuple[ScreenInfo, float, float]:
        """Convert virtual coordinates to local monitor coordinates."""
        screen = self.find_screen(x, y)
        local_x = x - screen.x
        local_y = y - screen.y
        return screen, local_x, local_y

    def virtual_to_physical(self, x: float, y: float) -> Tuple[ScreenInfo, int, int]:
        """Convert virtual coordinates to physical pixels on its containing monitor."""
        screen, lx, ly = self.virtual_to_monitor_local(x, y)
        px = int(round(lx * screen.scale))
        py = int(round(ly * screen.scale))
        return screen, px, py

    def physical_to_virtual(self, screen_name: str, px: int, py: int) -> Tuple[float, float]:
        """Convert physical screen pixels back to virtual coordinates."""
        for s in self.screens:
            if s.name == screen_name:
                lx = px / s.scale
                ly = py / s.scale
                return lx + s.x, ly + s.y
        raise ValueError(f"Screen name '{screen_name}' not found")

    def virtual_rect_to_physical_rect(self, x: float, y: float, w: float, h: float) -> Tuple[ScreenInfo, Dict[str, int]]:
        """Converts a virtual rect to physical monitor-local pixel coordinates."""
        # Locate the screen containing the center of the rectangle
        cx = x + w / 2
        cy = y + h / 2
        screen = self.find_screen(cx, cy)
        
        # Local monitor coordinates
        lx = x - screen.x
        ly = y - screen.y
        
        px = int(round(lx * screen.scale))
        py = int(round(ly * screen.scale))
        pw = int(round(w * screen.scale))
        ph = int(round(h * screen.scale))
        
        return screen, {"x": px, "y": py, "width": pw, "height": ph}
