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
- Active gesture uses Catmull–Rom interpolation and sparse blue particles.
- Three Qt painter passes (42 / 26 / 14 px) approximate the reference's halo, bloom and saturated marker core.
- Qt opacity buckets use **flat caps** to avoid bead-like junctions common with round-capped independent segments. Curved input geometry is preserved using spline subdivision.
- Committed gesture: full opacity for 1.6 seconds after release, then fades over 7 seconds while the overlay remains open. Finishing the capture closes the overlay immediately to keep it out of the screenshot. A later readback of the screenshot should show persistent source/destination semantics rather than the transient glow.
- Source/destination focus regions gain a subtle pulsing rounded outline and corner brackets (red and green semantic roles retained).
- The live/committed glow buffer is capped to 220 raw samples for rendering; all raw points remain available to the gesture/capture pipeline.
- The 60fps animation timer runs only while the overlay is visible.

## Verification

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_trail_fade.py tests/test_overlay_math.py
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy arrow
```

Manual acceptance: draw a long curved gesture, release the mouse, confirm a soft electric-blue highlighter fades slowly; source/destination marks and focus brackets remain visible until the capture is completed. Verify that screenshot content and multi-monitor geometry remain correct.

**Limitation:** Visual fidelity, actual frame rate and anti-aliasing on the Windows desktop require manual testing. CI verifies deterministic rendering math and that the painter does not crash in offscreen tests.
