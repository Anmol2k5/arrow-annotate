"""Exercise a frozen MCP executable's default stdio entry point."""

import argparse
import json
import subprocess
from pathlib import Path


def check_mcp(command: list[str], report_path: Path) -> int:
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "arrow-installer-smoke", "version": "1"},
        }},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    report = {"command": command, "success": False}
    try:
        # EOF terminates the real server after its requests; timeout also bounds startup failures.
        process = subprocess.run(
            command, input="".join(json.dumps(request) + "\n" for request in requests),
            capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
        )
        report.update(returncode=process.returncode, stdout=process.stdout, stderr=process.stderr)
        if process.returncode:
            raise RuntimeError(f"MCP process exited with {process.returncode}")
        # Parse every line: any startup banner or other stdout contamination must fail.
        responses = [json.loads(line) for line in process.stdout.splitlines()]
        report["responses"] = responses
        if len(responses) != 2 or any(
            not isinstance(response, dict) or response.get("jsonrpc") != "2.0" or response.get("id") != index
            or "error" in response for index, response in enumerate(responses, start=1)
        ):
            raise RuntimeError("Expected initialize and tools/list JSON-RPC responses only")
        initialized = responses[0].get("result", {})
        if initialized.get("serverInfo", {}).get("name") != "arrow-mcp" or not initialized.get("protocolVersion"):
            raise RuntimeError("MCP initialization did not identify Arrow's server")
        tools = responses[1].get("result", {}).get("tools")
        if not isinstance(tools, list) or not tools:
            raise RuntimeError("MCP tools/list returned no tools")
        report["success"] = True
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    # Deliberately pass no --mcp: ArrowMCP.exe must select MCP mode by its filename.
    raise SystemExit(check_mcp([str(args.executable.resolve())], args.report))
