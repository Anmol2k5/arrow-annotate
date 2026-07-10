# Current Architecture

## Application Startup Flow
The application starts in `main.py`. A PyQt6 `QApplication` is initialized.
It spawns a background daemon thread running a Flask server (`AgentServer` in `server.py`).
It then instantiates several PyQt widgets/objects:
- `DynamicNotch` (notch UI)
- `SelectionOverlay` (the transparent drawing overlay)
- `VoiceInput` (speech recognition thread)
- `CaptureStore` (JSON-based local storage)

A global hotkey (`ctrl+shift+space`) or the notch triggers `toggle_annotation()`.

## Event Loop & Threading
- The Qt Event Loop runs on the main thread.
- Flask server runs in a daemon thread.
- WebSocket bridge (for browser extension) runs its own asyncio loop in a thread.
- Screenshots and network uploads (`_capture_task` and `_send_to_agentation`) are offloaded to ad-hoc `threading.Thread` instances.

## Current Capture Flow
User hotkey → `SelectionOverlay` shown → User draws → `mouseRelease` triggers bounding box calculation → `selection_complete` signal emitted → `main.py` receives signal, grabs primary monitor via `mss`, crops it, reads current voice transcript → Saves to `CaptureRecord` → Refreshes notch → Spawns thread to upload to Agentation MCP via HTTP.

## Identified Failure Points & Context Loss
- **Annotation marks in screenshots**: `SelectionOverlay` points fade out after 2 seconds. They are NOT baked into the saved screenshots.
- **Monitor Capture**: `main.py` hardcodes `sct.monitors[1]`, capturing only the primary monitor.
- **Strokes**: New strokes replace previous ones because `SelectionOverlay._points` handles a single continuous line.
- **Source and Destination**: Not represented separately; the overlay only emits a single bounding box (`rect`).
- **Browser Context**: Not integrated into the primary capture flow; it exists in `server.py` but isn't called during normal captures in `main.py`.
- **Empty Context Fields**: `CaptureRecord` fields like `element_selector` and `computed_styles` are mostly empty because the resolver isn't actively used in the main screenshot pipeline.
- **Voice Results**: Race conditions exist. Voice results update `current_voice_text` and can arrive after the capture logic has already executed or been cancelled.
- **Agentation**: Selects the first available session indiscriminately (`sessions[0]["id"]`).
- **Timestamp Collisions**: Capture IDs use `strftime("%Y%m%d_%H%M%S")`, which can collide.
- **Hardcoded Data**: The Notch UI relies on hardcoded strings (e.g., "App" badges) and demo integrations.
