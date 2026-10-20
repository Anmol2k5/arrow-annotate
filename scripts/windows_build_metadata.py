"""Generate Windows release resources from the project and installed wheels."""

import argparse
import importlib.metadata
import json
import re
import shutil
from pathlib import Path

import tomllib


def project_version(manifest: Path) -> str:
    version = tomllib.loads(manifest.read_text(encoding="utf-8"))["project"]["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version) or any(int(part) > 65535 for part in version.split(".")):
        raise ValueError("Windows releases require three numeric version components, each <= 65535")
    return version


def collect_notices(output: Path, search_path=None) -> None:
    output.mkdir(parents=True, exist_ok=True)
    records = []
    missing = []
    distributions = importlib.metadata.distributions(**({"path": search_path} if search_path is not None else {}))
    for distribution in sorted(distributions, key=lambda dist: dist.metadata["Name"].lower()):
        name = distribution.metadata["Name"]
        folder = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{name}-{distribution.version}")
        target = output / folder
        target.mkdir(exist_ok=True)
        (target / "METADATA.txt").write_text(distribution.read_text("METADATA") or "", encoding="utf-8")
        files = []
        for entry in distribution.files or []:
            if not entry.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE")) and not any(
                part.lower() == "licenses" for part in entry.parts
            ):
                continue
            source = distribution.locate_file(entry)
            if source.is_file():
                filename = "__".join(part for part in entry.parts if part not in ("..", "."))
                destination = target / filename
                shutil.copyfile(source, destination)
                files.append(destination.relative_to(output).as_posix())
        records.append({
            "name": name,
            "version": distribution.version,
            "homepage": distribution.metadata.get("Home-page", ""),
            "project_urls": distribution.metadata.get_all("Project-URL", []),
            "license": distribution.metadata.get("License-Expression") or distribution.metadata.get("License", ""),
            "license_files": files,
        })
        if not files:
            missing.append(f"{name}=={distribution.version}")
    (output / "manifest.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    (output / "MISSING-LICENSE-FILES.txt").write_text(
        "Installed distributions without a separate license file; inspect their METADATA.txt before redistribution.\n"
        + "\n".join(missing) + "\n", encoding="utf-8"
    )
    (output / "README.txt").write_text(
        "Third-party provenance from the build environment. This inventory includes build tools as well as runtime packages.\n"
        "Original license/notice files and wheel metadata are retained without changes.\n"
        "PyInstaller also collects Qt/native-library licenses shipped inside their packages.\n"
        "This inventory does not grant any license; review applicable notices before redistribution.\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("build/windows/resources"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    version = project_version(root / "pyproject.toml")
    if args.version:
        print(version)
        return
    args.output.mkdir(parents=True, exist_ok=True)
    numeric = tuple(int(part) for part in version.split(".")) + (0,)
    (args.output / "version-info.txt").write_text(
        "VSVersionInfo(\n"
        f"  ffi=FixedFileInfo(filevers={numeric!r}, prodvers={numeric!r}, mask=0x3f, flags=0x0, OS=0x40004, "
        "fileType=0x1, subtype=0x0, date=(0, 0)),\n"
        "  kids=[StringFileInfo([StringTable('040904B0', [\n"
        "    StringStruct('CompanyName', 'Arrow Annotate'),\n"
        "    StringStruct('FileDescription', 'Arrow Annotate'),\n"
        f"    StringStruct('FileVersion', '{version}'),\n"
        "    StringStruct('ProductName', 'Arrow Annotate'),\n"
        f"    StringStruct('ProductVersion', '{version}')\n"
        "  ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])]\n)\n", encoding="utf-8"
    )
    collect_notices(args.output / "THIRD-PARTY-NOTICES")


if __name__ == "__main__":
    main()
