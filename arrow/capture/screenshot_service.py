import math
import os
import time
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import mss
from PIL import Image, ImageColor, ImageDraw, ImageFont

from arrow.capture.coordinate_mapper import CoordinateMapper, ScreenInfo
from arrow.capture.session import Annotation
from arrow.core.paths import data_dir

ROOT_DIR = str(data_dir())
SCREENSHOTS_DIR = os.path.join(ROOT_DIR, "screenshots")

# Claude vision pricing: ~width*height/750 tokens. At 1568px long edge a
# Retina frame costs ~2100 tokens instead of the 232K a raw capture costs.
MAX_AGENT_EDGE = 1568


@lru_cache(maxsize=32)
def _annotation_font(size: int) -> Any:
    """Use a scalable font on both Windows and non-Windows capture hosts."""
    for path in ("C:\\Windows\\Fonts\\arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Older Pillow releases only provide a fixed default font.
        return ImageFont.load_default()


def find_mss_monitor(sct: Any, screen: ScreenInfo) -> Dict[str, Any]:
    """Finds the mss monitor dict matching ScreenInfo's layout."""
    for m in sct.monitors[1:]:
        if abs(m["left"] - screen.x) < 10 and abs(m["top"] - screen.y) < 10:
            return m
    return sct.monitors[1]


class ScreenshotService:
    """
    Handles capturing raw screenshots, rendering spatial annotations,
    and generating targeted crops.
    """
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def capture_raw(self, overlay_widget: Optional[Any] = None) -> Tuple[Image.Image, ScreenInfo, CoordinateMapper]:
        """
        Captures a clean virtual-desktop screenshot without the drawing overlay.
        Processes Qt events and waits for the OS window manager to hide the overlay.
        """
        mapper = CoordinateMapper.from_qt()

        # Hide overlay before taking screenshot
        if overlay_widget is not None:
            overlay_widget.hide()
            from PyQt6.QtWidgets import QApplication
            QApplication.processEvents()
            # Brief pause for OS compositor to remove transparency overlay from screen buffers
            time.sleep(0.08)

        if not mapper.screens:
            raise RuntimeError("No displays available for capture")
        left = min(s.x for s in mapper.screens)
        top = min(s.y for s in mapper.screens)
        right = max(s.x + s.w for s in mapper.screens)
        bottom = max(s.y + s.h for s in mapper.screens)
        scale = max(s.scale for s in mapper.screens)
        screen_info = ScreenInfo("virtual_desktop", (left, top, right - left, bottom - top), scale)
        raw_img = Image.new("RGB", (round(screen_info.w * scale), round(screen_info.h * scale)))
        try:
            with mss.mss() as sct:
                for screen in mapper.screens:
                    monitor = find_mss_monitor(sct, screen)
                    captured = sct.grab(monitor)
                    image = Image.frombytes("RGB", captured.size, captured.bgra, "raw", "BGRX")
                    size = (round(screen.w * scale), round(screen.h * scale))
                    if image.size != size:
                        image = image.resize(size, Image.Resampling.LANCZOS)
                    raw_img.paste(image, (round((screen.x - left) * scale), round((screen.y - top) * scale)))
        finally:
            if overlay_widget is not None and getattr(overlay_widget, "_active", False):
                overlay_widget.show()
                overlay_widget.raise_()

        # All annotations must use the composed image's origin and common scale.
        return raw_img, screen_info, CoordinateMapper([screen_info])

    @staticmethod
    def downscale_for_agent(img: Image.Image, max_edge: int = MAX_AGENT_EDGE) -> Image.Image:
        """Resize so the long edge is at most *max_edge* pixels.

        Returns the original image untouched when it already fits.
        """
        w, h = img.size
        long = max(w, h)
        if long <= max_edge:
            return img
        ratio = max_edge / long
        return img.resize((max(1, int(w * ratio)), max(1, int(h * ratio))), Image.Resampling.LANCZOS)

    def capture_headless(self, region: Optional[Dict[str, int]] = None) -> Image.Image:
        """Capture the screen without touching any overlay widget.

        Used by the agent verification loop (``arrow_look`` MCP tool) so the
        agent can check its own work without user interaction.

        Args:
            region: Optional ``{"x", "y", "width", "height"}`` in virtual
                desktop coords. When omitted, captures the primary monitor.
        """
        with mss.mss() as sct:
            if region:
                monitor = {
                    "left": region["x"],
                    "top": region["y"],
                    "width": region["width"],
                    "height": region["height"],
                }
            else:
                monitor = sct.monitors[1]  # primary
            sct_img = sct.grab(monitor)
            return Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

    def render_annotations(self, raw_img: Image.Image, annotations: List[Annotation], mapper: CoordinateMapper) -> Image.Image:
        """
        Renders multiple spatial annotations (highlights, rectangles, arrows, freehand)
        offscreen onto a copy of the raw screenshot.
        """
        annotated_img = raw_img.copy().convert("RGBA")
        
        # Transparent overlay for highlight drawing
        overlay = Image.new("RGBA", annotated_img.size, (0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(overlay)
        draw_static = ImageDraw.Draw(annotated_img)

        for ann in sorted(annotations, key=lambda a: a.order):
            # Select role colors
            role_color = {
                "source": (239, 68, 68),       # Red
                "destination": (34, 197, 94),   # Green
                "supporting": (59, 130, 246),    # Blue
                "informational": (167, 139, 250) # Purple
            }.get(ann.role, (167, 139, 250))
            if isinstance(ann.style.get("color"), str):
                try:
                    role_color = ImageColor.getrgb(ann.style["color"])[:3]
                except ValueError:
                    pass

            geom = ann.geometry
            if not geom:
                continue

            if ann.type == "highlight":
                # Draw transparent highlight rectangle on overlay
                screen, rect = mapper.virtual_rect_to_physical_rect(
                    geom.get("x", 0.0), geom.get("y", 0.0),
                    geom.get("width", 0.0), geom.get("height", 0.0)
                )
                rx1, ry1 = rect["x"], rect["y"]
                rx2, ry2 = rx1 + rect["width"], ry1 + rect["height"]
                
                # Translucent fill + solid outline
                fill_color = role_color + (40,)  # 15% opacity
                border_color = role_color + (255,)
                draw_overlay.rectangle([rx1, ry1, rx2, ry2], fill=fill_color, outline=border_color,
                                       width=max(1, round(3 * screen.scale)))

            elif ann.type == "rectangle":
                screen, rect = mapper.virtual_rect_to_physical_rect(
                    geom.get("x", 0.0), geom.get("y", 0.0),
                    geom.get("width", 0.0), geom.get("height", 0.0)
                )
                rx1, ry1 = rect["x"], rect["y"]
                rx2, ry2 = rx1 + rect["width"], ry1 + rect["height"]
                border_color = role_color + (255,)
                draw_static.rectangle([rx1, ry1, rx2, ry2], outline=border_color,
                                      width=max(1, round(4 * screen.scale)))

            elif ann.type == "pointer":
                screen, px, py = mapper.virtual_to_physical(geom.get("x", 0.0), geom.get("y", 0.0))
                pr = max(1, round(12 * screen.scale))
                
                fill_color = role_color + (100,)
                border_color = role_color + (255,)
                draw_overlay.ellipse([px - pr, py - pr, px + pr, py + pr], fill=fill_color, outline=border_color,
                                     width=max(1, round(3 * screen.scale)))
                center_radius = max(1, round(3 * screen.scale))
                draw_static.ellipse([px - center_radius, py - center_radius, px + center_radius, py + center_radius],
                                    fill=role_color + (255,))

            elif ann.type == "arrow":
                screen = mapper.find_screen(geom.get("x1", 0.0), geom.get("y1", 0.0))
                _, px1, py1 = mapper.virtual_to_physical(geom.get("x1", 0.0), geom.get("y1", 0.0))
                _, px2, py2 = mapper.virtual_to_physical(geom.get("x2", 0.0), geom.get("y2", 0.0))
                
                arrow_color = role_color + (255,)
                # Neon glow simulation for arrow line
                draw_overlay.line([(px1, py1), (px2, py2)], fill=role_color + (30,),
                                  width=max(1, round(14 * screen.scale)), joint="round")
                draw_static.line([(px1, py1), (px2, py2)], fill=arrow_color,
                                 width=max(1, round(4 * screen.scale)), joint="round")
                
                # Draw arrowhead
                angle = math.atan2(py2 - py1, px2 - px1)
                arrow_len = max(1, round(16 * screen.scale))
                arrow_angle = math.pi / 6
                p1 = (px2 - arrow_len * math.cos(angle - arrow_angle), py2 - arrow_len * math.sin(angle - arrow_angle))
                p2 = (px2 - arrow_len * math.cos(angle + arrow_angle), py2 - arrow_len * math.sin(angle + arrow_angle))
                draw_static.polygon([(px2, py2), p1, p2], fill=arrow_color)

            elif ann.type == "freehand":
                points = geom.get("points", [])
                if len(points) == 1:
                    point = points[0]
                    screen, px, py = mapper.virtual_to_physical(point.get("x", 0.0), point.get("y", 0.0))
                    radius = max(3, round(4 * screen.scale))
                    draw_static.ellipse((px - radius, py - radius, px + radius, py + radius),
                                        fill=role_color + (255,))
                elif len(points) >= 2:
                    screen = mapper.find_screen(points[0].get("x", 0.0), points[0].get("y", 0.0))
                    phys_points = []
                    for pt in points:
                        _, px, py = mapper.virtual_to_physical(pt.get("x", 0.0), pt.get("y", 0.0))
                        phys_points.append((px, py))
                    
                    # Simulated neon stroke
                    draw_overlay.line(phys_points, fill=role_color + (25,),
                                      width=max(1, round(16 * screen.scale)), joint="round")
                    draw_overlay.line(phys_points, fill=role_color + (80,),
                                      width=max(1, round(8 * screen.scale)), joint="round")
                    core_color = role_color if ann.style.get("color") else (230, 220, 255)
                    draw_static.line(phys_points, fill=core_color + (255,),
                                     width=max(1, round(3 * screen.scale)), joint="round")

            # Draw Label if present
            if ann.label:
                lx, ly = geom.get("x", 0.0), geom.get("y", 0.0)
                screen, px, py = mapper.virtual_to_physical(lx, ly)
                font_size = max(1, round(15 * screen.scale))
                font = _annotation_font(font_size)
                padding = max(1, round(4 * screen.scale))
                tbbox = draw_static.textbbox((0, 0), ann.label, font=font)
                tw, th = tbbox[2] - tbbox[0], tbbox[3] - tbbox[1]
                # Long labels also fit when the screenshot is unusually narrow.
                available_w = max(1, annotated_img.width - 2 * padding)
                available_h = max(1, annotated_img.height - 2 * padding)
                if tw > available_w or th > available_h:
                    ratio = min(available_w / max(1, tw), available_h / max(1, th))
                    font = _annotation_font(max(1, int(font_size * ratio)))
                    tbbox = draw_static.textbbox((0, 0), ann.label, font=font)
                    tw, th = tbbox[2] - tbbox[0], tbbox[3] - tbbox[1]
                box_width, box_height = tw + 2 * padding, th + 2 * padding
                if ann.type == "pointer":
                    px += round(15 * screen.scale)
                label_x = max(0, min(px, annotated_img.width - box_width))
                label_y = max(0, min(py - box_height - padding, annotated_img.height - box_height))
                draw_static.rectangle([label_x, label_y, label_x + box_width - 1, label_y + box_height - 1],
                                      fill=(0, 0, 0, 220))
                draw_static.text((label_x + padding - tbbox[0], label_y + padding - tbbox[1]), ann.label,
                                 fill=(255, 255, 255, 255), font=font)

        # Composite translucent annotations onto base raw image
        final_img = Image.alpha_composite(annotated_img, overlay)
        return final_img.convert("RGB")

    def generate_crops(
        self, raw_img: Image.Image, annotations: List[Annotation], mapper: CoordinateMapper
    ) -> Tuple[Optional[Image.Image], Optional[Image.Image], Image.Image]:
        """
        Generates tight source-crop, destination-crop, and a padded context-crop.
        Ensures crops are safely bounded inside the screenshot space.
        """
        source_ann = next((a for a in annotations if a.role == "source"), None)
        dest_ann = next((a for a in annotations if a.role == "destination"), None)

        source_crop = None
        dest_crop = None

        def crop_annotation(ann: Annotation) -> Optional[Image.Image]:
            geom = ann.geometry
            if not geom:
                return None
            
            x, y = geom.get("x", 0.0), geom.get("y", 0.0)
            w = geom.get("width") or geom.get("w") or 0.0
            h = geom.get("height") or geom.get("h") or 0.0
            
            if w <= 0 or h <= 0:
                # If pointer/freehand, crop a 150x150 region around it
                w, h = 150.0, 150.0
                x -= 75.0
                y -= 75.0

            screen, rect = mapper.virtual_rect_to_physical_rect(x, y, w, h)
            rx1 = max(0, rect["x"])
            ry1 = max(0, rect["y"])
            rx2 = min(raw_img.width, rect["x"] + rect["width"])
            ry2 = min(raw_img.height, rect["y"] + rect["height"])

            if rx2 > rx1 and ry2 > ry1:
                return raw_img.crop((rx1, ry1, rx2, ry2))
            return None

        if source_ann:
            source_crop = crop_annotation(source_ann)
        if dest_ann:
            dest_crop = crop_annotation(dest_ann)

        # Generate padded context crop around all annotations combined
        if annotations:
            xs, ys = [], []
            for a in annotations:
                geom = a.geometry
                if not geom:
                    continue
                if a.type in ("rectangle", "highlight"):
                    xs.extend([geom["x"], geom["x"] + geom.get("width", 0.0)])
                    ys.extend([geom["y"], geom["y"] + geom.get("height", 0.0)])
                elif a.type == "arrow":
                    xs.extend([geom["x1"], geom["x2"]])
                    ys.extend([geom["y1"], geom["y2"]])
                elif a.type == "freehand":
                    for pt in geom.get("points", []):
                        xs.append(pt["x"])
                        ys.append(pt["y"])
                else:
                    xs.append(geom.get("x", 0.0))
                    ys.append(geom.get("y", 0.0))

            if xs and ys:
                min_vx, max_vx = min(xs), max(xs)
                min_vy, max_vy = min(ys), max(ys)
                
                # Apply 100px virtual padding
                pad = 100.0
                cx1 = min_vx - pad
                cy1 = min_vy - pad
                cx2 = max_vx + pad
                cy2 = max_vy + pad

                screen = mapper.find_screen((min_vx + max_vx)/2, (min_vy + max_vy)/2)
                
                # Convert virtual context boundaries to monitor physical bounds
                px1 = max(0, int(round((cx1 - screen.x) * screen.scale)))
                py1 = max(0, int(round((cy1 - screen.y) * screen.scale)))
                px2 = min(raw_img.width, int(round((cx2 - screen.x) * screen.scale)))
                py2 = min(raw_img.height, int(round((cy2 - screen.y) * screen.scale)))

                if px2 > px1 and py2 > py1:
                    context_crop = raw_img.crop((px1, py1, px2, py2))
                else:
                    context_crop = raw_img
            else:
                context_crop = raw_img
        else:
            context_crop = raw_img

        return source_crop, dest_crop, context_crop
