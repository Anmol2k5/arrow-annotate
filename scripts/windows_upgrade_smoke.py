"""Seed and verify isolated, synthetic v0.4.1 data across an installed upgrade.

This is a storage/MCP check, not an authenticated Codex or Claude session.
Only seed a new empty test directory; never point it at a person's Arrow home.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sqlite3
import struct
import subprocess
import sys
import zlib
from pathlib import Path

CAPTURE_ID = "upgrade-0.4.1-सिंथेटिक"
TIMESTAMP = "2026-10-01T12:34:56+00:00"
MARKER = "upgrade-fixture.json"
BASELINE_SQL = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "upgrade_0_4_1.sql"


def png_bytes() -> bytes:
    """A real deterministic 2x2 RGB PNG, generated without image dependencies."""
    def chunk(name: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data))

    pixels = b"\x00\xff\x00\x00\x00\xff\x00\x00\x00\x00\xff\xff\xff\xff"
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


def expected_fixture(home: Path) -> dict:
    repository = str(home / "चयनित repository")
    screenshot = str(home / "screenshots" / "सिंथेटिक annotated.png")
    instruction = "नीला बटन नीचे ले जाएँ — edited synthetic instruction"
    voice = "नीला बटन नीचे करो — original synthetic speech"
    annotations = [{"type": "rectangle", "x": 10, "y": 20, "width": 100, "height": 40,
                    "label": "स्रोत बटन", "role": "source"}]
    capture_context = {"window_context": {"source": {
        "window_title": "Synthetic editor — नमस्ते", "status": "available", "included": True,
        "text": "Synthetic window text: बटन and destination heading",
    }}, "cursor": {"x": 30, "y": 40}}
    request = {
        "capture_id": CAPTURE_ID, "summary": "Move synthetic button — नमस्ते",
        "raw_user_request": instruction, "normalized_intent": "move_element", "application_mode": "web",
        "project": {"repository_root": repository, "name": "चयनित repository"},
        "source": {"label": "स्रोत बटन", "selector": "#synthetic-button"},
        "destination": {"label": "Synthetic heading"},
        "assets": {"raw": screenshot, "annotated": screenshot},
    }
    context = {
        "current_instruction": instruction, "original_voice_transcript": voice,
        "annotations": annotations, "capture_context": capture_context,
        "cursor_x": 30, "cursor_y": 40, "element_selector": "#synthetic-button",
        "element_path": "body > button", "react_components": "SyntheticButton",
        "computed_styles": '{"color":"blue"}', "accessibility": '{"role":"button"}',
        "selected_text": "नमस्ते", "bounding_box": {"x": 10, "y": 20, "width": 100, "height": 40},
        "agentation_status": "resolved", "window_title": "Synthetic editor — नमस्ते",
        # v0.4.1 CaptureStore embeds this as a JSON string inside contexts.data.
        "change_request": json.dumps(request),
    }
    return {
        "fixture_version": "0.4.1", "synthetic": True, "capture_id": CAPTURE_ID,
        "preferences": {"capture_shortcut": "ctrl+shift", "speech_language": "hi-IN",
                        "clipboard_mode": "combined", "auto_expand_capture": False,
                        "keep_notch_open": True, "selected_project_dir": repository},
        "session": {"capture_id": CAPTURE_ID, "created_at": TIMESTAMP, "updated_at": TIMESTAMP,
                    "state": "COMPLETED", "mode": "desktop", "project_id": None,
                    "raw_instruction": "", "voice_transcript": instruction, "provider": None, "error": None},
        "context": context, "change_request": request, "screenshot_path": screenshot,
        "screenshot_sha256": hashlib.sha256(png_bytes()).hexdigest(),
    }


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def seed(home: Path) -> dict:
    home = home.expanduser().resolve()
    if home.exists() and any(home.iterdir()):
        raise ValueError("Seed requires a new or empty isolated test directory; refusing existing data")
    home.mkdir(parents=True, exist_ok=True)
    expected = expected_fixture(home)
    Path(expected["preferences"]["selected_project_dir"]).mkdir()
    image = Path(expected["screenshot_path"])
    image.parent.mkdir()
    image.write_bytes(png_bytes())
    write_json(home / "config.json", expected["preferences"])
    # Deliberately no imports from the current application's schema or CaptureStore.
    with sqlite3.connect(home / "arrow.db") as conn:
        conn.executescript(BASELINE_SQL.read_text(encoding="utf-8"))
        session = expected["session"]
        columns = ", ".join(session)
        conn.execute(f"INSERT INTO sessions ({columns}) VALUES ({', '.join('?' for _ in session)})",
                     tuple(session.values()))
        conn.execute("INSERT INTO contexts(capture_id, data) VALUES (?, ?)",
                     (CAPTURE_ID, json.dumps(expected["context"])))
        for annotation in expected["context"]["annotations"]:
            conn.execute("INSERT INTO annotations(capture_id, data) VALUES (?, ?)",
                         (CAPTURE_ID, json.dumps(annotation)))
        conn.execute("INSERT INTO change_requests VALUES (?, ?, ?, NULL, 'ready', ?)",
                     (CAPTURE_ID, TIMESTAMP, TIMESTAMP, json.dumps(expected["change_request"])))
        for asset_type in ("screenshot", "raw", "annotated"):
            conn.execute("INSERT INTO assets(capture_id, path, type) VALUES (?, ?, ?)",
                         (CAPTURE_ID, str(image), asset_type))
    write_json(home / MARKER, expected)
    return {"success": True, "operation": "seed", "home": str(home), "expected": expected,
            "schema_version": 3, "scope": "synthetic storage and MCP only"}


def require_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise ValueError(f"{label} changed: expected {expected!r}, received {actual!r}")


def verify_storage(home: Path, expected: dict) -> int:
    require_equal(json.loads((home / "config.json").read_text(encoding="utf-8")),
                  expected["preferences"], "Saved preferences")
    if not Path(expected["preferences"]["selected_project_dir"]).is_dir():
        raise ValueError("Selected repository directory is missing")
    image = Path(expected["screenshot_path"])
    require_equal(hashlib.sha256(image.read_bytes()).hexdigest(), expected["screenshot_sha256"], "Saved PNG SHA-256")
    # URI mode=ro prevents accidentally creating a missing database or applying current migrations.
    with sqlite3.connect((home / "arrow.db").as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        require_equal(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok", "SQLite integrity")
        require_equal(conn.execute("PRAGMA foreign_key_check").fetchall(), [], "SQLite foreign keys")
        schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
        if schema_version < 3:
            raise ValueError("Released v0.4.1 schema version regressed")
        session = conn.execute("SELECT * FROM sessions WHERE capture_id=?", (CAPTURE_ID,)).fetchone()
        if session is None:
            raise ValueError("Saved capture is missing")
        # Additional columns are allowed in future migrations; seeded semantic fields must survive.
        require_equal({key: session[key] for key in expected["session"]}, expected["session"], "Capture session")
        context = conn.execute("SELECT data FROM contexts WHERE capture_id=?", (CAPTURE_ID,)).fetchone()
        require_equal(json.loads(context[0]) if context else None, expected["context"], "Capture context")
        annotations = [json.loads(row[0]) for row in conn.execute(
            "SELECT data FROM annotations WHERE capture_id=? ORDER BY id", (CAPTURE_ID,))]
        require_equal(annotations, expected["context"]["annotations"], "Annotations")
        request = conn.execute("SELECT * FROM change_requests WHERE capture_id=?", (CAPTURE_ID,)).fetchone()
        if request is None:
            raise ValueError("MCP change request is missing")
        require_equal(json.loads(request["data"]), expected["change_request"], "MCP change request")
        require_equal(request["status"], "ready", "Capture status")
        for asset_type in ("screenshot", "raw", "annotated"):
            paths = [row[0] for row in conn.execute(
                "SELECT path FROM assets WHERE capture_id=? AND type=?", (CAPTURE_ID, asset_type))]
            require_equal(paths, [str(image)], f"Saved {asset_type} asset")
    return schema_version


def verify_mcp(home: Path, expected: dict, command: list[str], expected_version: str,
               version_command: list[str] | None = None) -> dict:
    environment = os.environ.copy()
    environment.update(ARROW_HOME=str(home), ARROW_DB_PATH=str(home / "arrow.db"), PYTHONIOENCODING="utf-8")
    version = subprocess.run(version_command or [*command, "--version"], env=environment,
                             capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
    require_equal(version.returncode, 0, "MCP --version exit code")
    require_equal(version.stdout.strip(), f"Arrow Annotate {expected_version}", "Installed MCP version")
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "arrow-upgrade-smoke", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "arrow_get_capture_bundle", "arguments": {"capture_id": CAPTURE_ID}}},
    ]
    process = subprocess.run(command, env=environment, capture_output=True, text=True, encoding="utf-8",
                             input="".join(json.dumps(request) + "\n" for request in requests), timeout=45, check=False)
    require_equal(process.returncode, 0, "MCP stdio exit code")
    responses = [json.loads(line) for line in process.stdout.splitlines()]
    require_equal(len(responses), 2, "MCP response count")
    for index, response in enumerate(responses, start=1):
        require_equal(response.get("jsonrpc"), "2.0", "MCP JSON-RPC version")
        require_equal(response.get("id"), index, "MCP response id")
        if "error" in response or response.get("result", {}).get("isError"):
            raise ValueError(f"MCP request failed: {response}")
    initialized = responses[0]["result"]
    require_equal(initialized["serverInfo"]["name"], "arrow-mcp", "MCP server identity")
    require_equal(initialized["protocolVersion"], "2024-11-05", "MCP protocol negotiation")
    content = responses[1]["result"]["content"]
    texts = [block["text"] for block in content if block.get("type") == "text"]
    require_equal(len(texts), 1, "MCP bundle text block count")
    bundle = json.loads(texts[0])
    metadata = bundle["metadata"]
    for key in ("current_instruction", "original_voice_transcript", "annotations", "capture_context"):
        require_equal(metadata[key], expected["context"][key], f"MCP {key}")
    require_equal(metadata["capture_id"], CAPTURE_ID, "MCP capture id")
    require_equal(metadata["change_request"], expected["change_request"], "MCP change request")
    require_equal(metadata["repository_path"], expected["preferences"]["selected_project_dir"], "MCP repository")
    require_equal(json.loads(Path(bundle["context_path"]).read_text(encoding="utf-8")), metadata, "MCP context file")
    images = [block for block in content if block.get("type") == "image"]
    require_equal(len(images), 1, "MCP image block count")
    require_equal(images[0]["mimeType"], "image/png", "MCP image MIME type")
    image_sha = hashlib.sha256(base64.b64decode(images[0]["data"], validate=True)).hexdigest()
    require_equal(image_sha, expected["screenshot_sha256"], "MCP image SHA-256")
    require_equal(hashlib.sha256(Path(bundle["annotated_path"]).read_bytes()).hexdigest(), image_sha, "MCP bundle PNG")
    return {"success": True, "command": command, "version": expected_version,
            "server_info": initialized["serverInfo"], "capture_id": CAPTURE_ID,
            "image_sha256": image_sha, "metadata": metadata,
            "scope": "real MCP stdio storage roundtrip; no authenticated agent session"}


def check(home: Path, command: list[str], expected_version: str, version_command: list[str] | None = None) -> dict:
    home = home.expanduser().resolve()
    expected = expected_fixture(home)
    require_equal(json.loads((home / MARKER).read_text(encoding="utf-8")), expected, "Synthetic fixture marker")
    schema_version = verify_storage(home, expected)
    mcp = verify_mcp(home, expected, command, expected_version, version_command)
    # Bundle building legitimately adds assets: verify semantic data again, not a DB file hash.
    verify_storage(home, expected)
    return {"success": True, "operation": "check", "home": str(home),
            "schema_version": schema_version, "preferences": expected["preferences"], "mcp": mcp}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    seed_parser = commands.add_parser("seed", help="Create synthetic v0.4.1 data in an EMPTY isolated home")
    check_parser = commands.add_parser("check", help="Verify preservation and the installed real MCP server")
    for subparser in (seed_parser, check_parser):
        subparser.add_argument("home", type=Path)
        subparser.add_argument("--report", type=Path, required=True)
    check_parser.add_argument("--mcp-executable", type=Path, required=True)
    check_parser.add_argument("--expected-version", required=True)
    args = parser.parse_args(argv)
    if args.report.resolve().is_relative_to(args.home.expanduser().resolve()):
        print("The report must be outside the isolated Arrow home to protect fixture/user data", file=sys.stderr)
        return 1
    try:
        report = seed(args.home) if args.operation == "seed" else check(
            args.home, [str(args.mcp_executable.resolve())], args.expected_version)
    except Exception as exc:
        report = {"success": False, "operation": args.operation, "error": f"{type(exc).__name__}: {exc}",
                  "scope": "synthetic storage and MCP only"}
    write_json(args.report, report)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
