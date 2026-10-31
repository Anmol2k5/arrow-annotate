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


def test_release_publication_is_tag_only_and_depends_on_native_checks():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/windows-installer.yml").read_text(encoding="utf-8")
    build, publish = workflow.split("  publish-release:", 1)
    assert "permissions:\n  contents: read" in build
    assert "needs: build-and-test" in publish
    assert "github.repository == 'Anmol2k5/arrow-annotate'" in publish
    assert "github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')" in publish
    assert "contents: write" not in build
    assert "contents: write" in publish
    assert "./scripts/test-windows-install.ps1" in build
    assert "sha256sum --check SHA256SUMS.txt" in publish
    assert "gh release create" in publish and "--verify-tag" in publish
    for name in ("SHA256SUMS.txt", "build-provenance.json", "build-requirements.txt", "third-party-manifest.json"):
        assert name in publish
    for line in build.splitlines():
        if "secrets.WINDOWS_SIGN_" in line:
            assert "github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')" in line
    assert "secrets." not in publish


def test_signing_precedes_archiving_and_hashing_and_requires_trusted_identity():
    root = Path(__file__).resolve().parents[1]
    build = (root / "scripts/build-windows.ps1").read_text(encoding="utf-8")
    sign = (root / "scripts/sign-windows.ps1").read_text(encoding="utf-8")
    app_sign = build.index("& ./scripts/sign-windows.ps1 -Paths @((Join-Path $Bundle")
    inno = build.index('Invoke-Checked $InnoCompiler @("/DAppVersion=')
    setup_sign = build.index("& ./scripts/sign-windows.ps1 -Paths @($Setup)")
    archive = build.index("Compress-Archive")
    hashes = build.index("Get-FileHash $File -Algorithm SHA256")
    assert app_sign < inno < setup_sign < archive < hashes
    assert '"unsigned"' in build
    assert "ARROW_SIGN_CERT_THUMBPRINT" in sign
    assert '$Signature.Status -ne "Valid"' in sign
    assert "$Signature.SignerCertificate.Thumbprint -ne $ExpectedThumbprint" in sign
    assert "$null -eq $Signature.TimeStamperCertificate" in sign
    assert "/fd SHA256 /tr $TimestampServer /td SHA256" in sign
    assert "verify /pa /all /tw" in sign
    assert "-DeleteKey" in sign
    assert "Remove-Item $TemporaryPfx -Force" in sign
    assert "/p $" not in sign  # Password must not appear in signing-tool process arguments.
    assert "New-SelfSignedCertificate" not in sign
