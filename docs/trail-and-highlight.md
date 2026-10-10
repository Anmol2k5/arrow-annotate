# Gesture trail and focus-highlight design

## Reference

Visual design and rendering approach inspired by [TipTour](https://github.com/milind-soni/tiptour-macos), specifically:

- [`TipTour/UI/OverlayWindow.swift`](https://github.com/milind-soni/tiptour-macos/blob/main/TipTour/UI/OverlayWindow.swift): `FocusHighlightTrailView`, `CursorStreakTrailView` and its continuous-path rendering principles.
- [`TipTour/UI/DetectionOverlayView.swift`](https://github.com/milind-soni/tiptour-macos/blob/main/TipTour/UI/DetectionOverlayView.swift): subtle glowing rounded target outlines and corner brackets.
- [`TipTour/Core/TipTourHighlightSourceResolver.swift`](https://github.com/milind-soni/tiptour-macos/blob/main/TipTour/Core/TipTourHighlightSourceResolver.swift): source-resolution fallback design (not copied or used in Arrow's Windows UIA/DOM/OCR resolution).

TipTour is under the MIT license, copyright (c) 2026 Milind Soni and portions copyright (c) 2025 Farza (Clicky). See the [upstream LICENSE](https://github.com/milind-soni/tiptour-macos/blob/main/LICENSE) for the full notice.

Arrow Annotate uses its **own PyQt6 drawing code**; no Swift/AppKit implementation is bundled.

## Windows/PyQt6 adaptation

- Screenwide Qt overlay, with freehand strokes captured in virtual-desktop coordinates.
- Active gesture uses Catmull–Rom interpolation into a densified sample stream (bounded to 220 raw points for rendering; all raw points remain available to the capture pipeline).
- **Continuous band rendering** (the TipTour anti-bead strategy): the densified trail is sliced into ordered tail→head opacity bands; each band is a single polyline sharing endpoints with its neighbours and is stroked once per glow layer with **flat caps**. This approximates TipTour's "one continuous path, trimmed into bands" approach — Qt has no path trimming — and avoids the stacked round-cap beads of per-segment rendering.
- Three glow layers match the reference proportions: outer halo 54 px @ 0.11, middle bloom 32 px @ 0.26, saturated core 18 px @ 0.72, using the electric-blue palette (`#4F8EF7` core, `#E2F3FF` leading tip).
- Opacity ramp: `progress ^ 1.8` (bright head, soft dissolving tail), monotonic along the path.
- Committed gesture: full opacity for 1.6 seconds after release, then fades over 7 seconds while the overlay remains open. Finishing the capture closes the overlay immediately to keep it out of the screenshot. Persistent source/destination semantics remain after the transient glow fades.
- Source/destination focus regions keep a subtle pulsing rounded outline (~0.35 Hz) and corner brackets (red/green semantic roles retained). Marker labels read "Current" / "Move here".
- The overlay backdrop is a mostly transparent veil (alpha 32) — the desktop stays fully legible while drawing; the guide pill uses the electric-blue accent. No full-screen dot grid (it cost thousands of `drawPoint` calls per frame).
- The 60 fps animation timer runs only while something is actually animating (live stroke or pulsing focus outline); an empty idle overlay skips repaints.
- Compact pointer head: white-blue core with a soft electric-blue halo (18 px), no oversized arrowhead.

## Verification

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_trail_fade.py tests/test_overlay_math.py
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy arrow
```

Manual acceptance: draw a long curved gesture, release the mouse, confirm a soft electric-blue highlighter fades slowly; the desktop remains clearly visible while drawing; source/destination marks and focus brackets remain visible until the capture is completed. Verify that screenshot content and multi-monitor geometry remain correct.

**Limitation:** Visual fidelity, actual frame rate and anti-aliasing on the Windows desktop require manual testing. CI verifies deterministic rendering math, band continuity along curves, and that the painter does not crash in offscreen tests.
