# Refactoring Plan

## 1. Components That Can Be Kept
- **Hybrid Pointer**: The tier 1 (UIA) and tier 2 (OCR) resolver logic (`hybrid_pointer.py`).
- **Highlight Resolver Logic**: The heuristics in `highlight_resolver.py`.
- **Browser Extension**: The content script structure is good, but protocol needs strict schema.
- **Notch UI (Aesthetics)**: The visual design (animations, colors, PyQt layout) in `notch.py`.
- **Voice Input**: The SpeechRecognition wrapper, though threading needs safety.

## 2. Components Requiring Refactoring
- **`main.py`**: Currently handles business logic, event hooking, screenshotting, and API calls. Must be split into application lifecycle, orchestrator, and UI controllers.
- **`SelectionOverlay`**: Must be upgraded to support persistent scene states, multiple annotation types (Pointer, Rect, Highlight, Freehand), and separate Source/Destination anchors.
- **Coordinate System**: Needs a `CoordinateMapper` to correctly handle multi-monitor, negative coordinates, and mixed DPI instead of raw pixel math.
- **`server.py`**: Needs to be decoupled. The Flask routes should only handle MCP/HTTP API, moving orchestration to a dedicated core service.

## 3. Components Requiring Complete Replacement
- **Capture Storage**: `CaptureStore` (JSON files) must be replaced with SQLite for atomic transactions, relational integrity (assets, annotations), and querying.
- **Capture Pipeline**: The ad-hoc `threading.Thread` chains in `main.py` must be replaced by a formalized `CaptureSession` state machine.
- **Screenshotting**: The current approach of capturing only monitor 1 and relying on OS transparency must be replaced with a reliable off-screen renderer that explicitly composites the annotation scene onto the raw screenshot.
- **Agentation Client**: Hardcoded `sessions[0]` logic must be replaced with proper provider adapters (Codex, Claude, Agentation) and MCP.

## Proposed Architecture Structure
```text
arrow/
├── app/ (application.py, lifecycle.py)
├── capture/ (session.py, screenshot_service.py, annotation_scene.py)
├── context/ (orchestrator.py, browser_adapter.py, windows_uia_adapter.py)
├── intent/ (compiler.py, schemas.py)
├── storage/ (database.py, models.py)
├── providers/ (codex.py, claude.py)
├── mcp/ (server.py)
├── ui/ (notch, overlay)
└── browser_extension/
```
