"""Exercise release metadata and license collection without a Windows host."""

import importlib.util
import json
import sys
from pathlib import Path


def load_build_helper():
    path = Path(__file__).resolve().parents[1] / "scripts" / "windows_build_metadata.py"
    spec = importlib.util.spec_from_file_location("windows_build_metadata", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_version_comes_from_project_and_rejects_invalid_windows_version(tmp_path):
    helper = load_build_helper()
    manifest = tmp_path / "pyproject.toml"
    manifest.write_text('[project]\nversion = "2.4.9"\n', encoding="utf-8")
    assert helper.project_version(manifest) == "2.4.9"
    manifest.write_text('[project]\nversion = "2.4"\n', encoding="utf-8")
    import pytest

    with pytest.raises(ValueError, match="three numeric"):
        helper.project_version(manifest)


def test_notices_keep_original_license_text_and_record_provenance(tmp_path):
    helper = load_build_helper()
    # A real on-disk distribution, as importlib.metadata sees in site-packages.
    metadata = tmp_path / "example_lib-1.2.3.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: example-lib\nVersion: 1.2.3\n"
        "Home-page: https://example.test/library\nLicense: MIT\n", encoding="utf-8"
    )
    (metadata / "LICENSE").write_text("Original copyright\nPermission is granted.\n", encoding="utf-8")
    (metadata / "RECORD").write_text("example_lib-1.2.3.dist-info/LICENSE,,\n", encoding="utf-8")
    output = tmp_path / "notices"
    helper.collect_notices(output, search_path=[str(tmp_path)])
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    package = manifest[0]
    assert package["name"] == "example-lib"
    assert package["version"] == "1.2.3"
    assert package["homepage"] == "https://example.test/library"
    assert (output / package["license_files"][0]).read_text(encoding="utf-8") == (
        "Original copyright\nPermission is granted.\n"
    )


def test_notices_explicitly_report_packages_without_license_files(tmp_path):
    helper = load_build_helper()
    metadata = tmp_path / "no_license-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: no-license\nVersion: 1.0\n", encoding="utf-8"
    )
    output = tmp_path / "notices"
    helper.collect_notices(output, search_path=[str(tmp_path)])
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest[0]["license_files"] == []
    assert "no-license" in (output / "MISSING-LICENSE-FILES.txt").read_text(encoding="utf-8")


def test_protocol_smoke_exercises_real_server_and_records_clean_json_stdout(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("windows_mcp_smoke", root / "scripts" / "windows_mcp_smoke.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    monkeypatch.setenv("ARROW_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("ARROW_DB_PATH", raising=False)
    report = tmp_path / "protocol.json"
    assert helper.check_mcp([sys.executable, str(root / "main.py"), "--mcp"], report) == 0
    result = json.loads(report.read_text(encoding="utf-8"))
    assert result["success"]
    assert result["responses"][0]["result"]["serverInfo"]["name"] == "arrow-mcp"
    assert result["responses"][1]["result"]["tools"]


def test_protocol_smoke_rejects_startup_banners_and_saves_diagnostics(tmp_path):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("windows_mcp_smoke", root / "scripts" / "windows_mcp_smoke.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    report = tmp_path / "invalid-protocol.json"
    assert helper.check_mcp([sys.executable, "-c", "print('unexpected startup banner')"], report) == 1
    result = json.loads(report.read_text(encoding="utf-8"))
    assert not result["success"]
    assert "unexpected startup banner" in result["stdout"]
    assert "JSONDecodeError" in result["error"]
