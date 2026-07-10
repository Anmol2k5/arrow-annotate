"""
Source-code mapping (Phase 7).

Maps a visual webpage element to the likely repository file(s) and component.

Mapping priority (highest confidence first):
  1. ``data-arrow-id``            — explicit developer instrumentation
  2. development instrumentation  — React ``__source`` (file + line)
  3. source-map information       — bundler source map (file + line)
  4. framework component metadata — component name → definition file
  5. route information            — route → route/page file
  6. repository search            — visible text search
  7. visible text                 — short-text heuristic search
  8. selector / structural        — last-resort structural candidates

Hard rule: never fabricate a file or line. Every ``source_file`` / ``source_line``
returned is verified against the repository on disk before it is reported.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

from pydantic import BaseModel, Field

log = logging.getLogger("bluely.source_mapper")

# Directories that never contain the user's source of interest.
_SKIP_DIRS = {
    ".git", "node_modules", "dist", "build", ".next", "out", "coverage",
    ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".turbo", ".cache", "vendor", ".svelte-kit",
}

# Extensions worth searching for component/markup source.
_SOURCE_EXTS = {
    ".tsx", ".ts", ".jsx", ".js", ".vue", ".svelte", ".astro", ".mjs", ".cjs",
    ".html", ".htm",
}

_RESOLVE_THRESHOLD = 0.7
_MAX_SCAN_FILES = 4000
_MAX_FILE_BYTES = 1_000_000


class ElementContext(BaseModel):
    """Normalized element facts consumed by the mapper.

    Typically built from the browser-extension inspection result.
    """

    arrow_id: Optional[str] = None
    test_id: Optional[str] = None
    react_source: Optional[dict] = None  # {"fileName": str, "lineNumber": int, "columnNumber": int}
    source_map: Optional[dict] = None    # {"fileName": str, "lineNumber": int}
    component: Optional[str] = None
    route: Optional[str] = None
    text: Optional[str] = None
    selector: Optional[str] = None
    tag: Optional[str] = None
    element_id: Optional[str] = None
    class_name: Optional[str] = None


class SourceCandidate(BaseModel):
    component: Optional[str] = None
    source_file: str
    source_line: Optional[int] = None
    confidence: float
    evidence: list[str] = Field(default_factory=list)


class SourceMappingResult(BaseModel):
    resolved: bool = False
    method: Optional[str] = None
    component: Optional[str] = None
    source_file: Optional[str] = None
    source_line: Optional[int] = None
    confidence: float = 0.0
    evidence: list[str] = Field(default_factory=list)
    candidates: list[SourceCandidate] = Field(default_factory=list)

    def to_dict(self) -> dict:
        return self.model_dump()


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------

def _iter_source_files(root: str):
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in _SOURCE_EXTS:
                continue
            scanned += 1
            if scanned > _MAX_SCAN_FILES:
                log.debug("Source scan hit file limit (%d)", _MAX_SCAN_FILES)
                return
            yield os.path.join(dirpath, filename)


def _read_lines(path: str) -> Optional[list[str]]:
    try:
        if os.path.getsize(path) > _MAX_FILE_BYTES:
            return None
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.readlines()
    except OSError as e:
        log.debug("Could not read %s: %s", path, e)
        return None


def _rel(root: str, path: str) -> str:
    try:
        return os.path.relpath(path, root).replace(os.sep, "/")
    except ValueError:
        return path.replace(os.sep, "/")


def _resolve_existing(root: str, file_name: str) -> Optional[str]:
    """Resolve a (possibly relative) file name to an existing path under root."""
    if not file_name:
        return None
    candidate = file_name.replace("/", os.sep)
    paths = []
    if os.path.isabs(candidate):
        paths.append(candidate)
    else:
        paths.append(os.path.join(root, candidate))
        paths.append(os.path.join(root, "src", candidate))
    for p in paths:
        p = os.path.normpath(p)
        if os.path.isfile(p):
            return p
    # Fall back to basename search within the repo.
    base = os.path.basename(candidate)
    for src in _iter_source_files(root):
        if os.path.basename(src) == base:
            return src
    return None


# ---------------------------------------------------------------------------
# Search helpers
# ---------------------------------------------------------------------------

def _grep(root: str, pattern: re.Pattern[str], limit: int = 25) -> list[tuple[str, int, str]]:
    matches: list[tuple[str, int, str]] = []
    for src in _iter_source_files(root):
        lines = _read_lines(src)
        if lines is None:
            continue
        for i, line in enumerate(lines, start=1):
            if pattern.search(line):
                matches.append((src, i, line.strip()))
                if len(matches) >= limit:
                    return matches
    return matches


# ---------------------------------------------------------------------------
# SourceMapper
# ---------------------------------------------------------------------------

class SourceMapper:
    """Maps element context to repository source files.

    Args:
        repository_root: Absolute path to the repository root. Mapping tiers that
            require repository access are skipped when this is missing or invalid.
    """

    def __init__(self, repository_root: Optional[str]):
        self.root = os.path.normpath(repository_root) if repository_root and os.path.isdir(repository_root) else None

    def map(self, element: ElementContext) -> SourceMappingResult:
        if self.root is None:
            return SourceMappingResult(resolved=False, evidence=["No repository root available."])

        # 1. data-arrow-id
        result = self._by_arrow_id(element)
        if result and result.resolved:
            return result

        # 2. development instrumentation (React __source)
        result = self._by_dev_instrumentation(element)
        if result and result.resolved:
            return result

        # 3. source-map information
        result = self._by_source_map(element)
        if result and result.resolved:
            return result

        candidates: list[SourceCandidate] = []

        # 4. framework component metadata
        component_result = self._by_component(element)
        if component_result:
            if component_result.resolved:
                return component_result
            candidates.extend(component_result.candidates)

        # 5. route information
        route_result = self._by_route(element)
        if route_result:
            candidates.extend(route_result.candidates)

        # 6/7. repository search on visible text
        text_result = self._by_text(element)
        if text_result:
            candidates.extend(text_result.candidates)

        # 8. selector / structural heuristics
        selector_result = self._by_selector(element)
        if selector_result:
            candidates.extend(selector_result.candidates)

        return self._finalize(candidates)

    # --- Tier 1: data-arrow-id -------------------------------------------

    def _by_arrow_id(self, element: ElementContext) -> Optional[SourceMappingResult]:
        for attr, value in (("data-arrow-id", element.arrow_id), ("data-testid", element.test_id)):
            if not value:
                continue
            pattern = re.compile(rf'{re.escape(attr)}\s*=\s*["\']{re.escape(value)}["\']')
            matches = _grep(self.root, pattern, limit=10)
            if len(matches) == 1:
                src, line, _ = matches[0]
                confidence = 0.95 if attr == "data-arrow-id" else 0.9
                return SourceMappingResult(
                    resolved=True,
                    method="data_arrow_id" if attr == "data-arrow-id" else "test_id",
                    component=_component_from_path(src),
                    source_file=_rel(self.root, src),
                    source_line=line,
                    confidence=confidence,
                    evidence=[f'{attr}="{value}" matched a single element.'],
                )
            if len(matches) > 1:
                candidates = [
                    SourceCandidate(
                        component=_component_from_path(src),
                        source_file=_rel(self.root, src),
                        source_line=line,
                        confidence=0.6,
                        evidence=[f'{attr}="{value}" match (multiple).'],
                    )
                    for src, line, _ in matches
                ]
                return SourceMappingResult(
                    resolved=False,
                    method="data_arrow_id",
                    candidates=candidates,
                )
        return None

    # --- Tier 2: development instrumentation -----------------------------

    def _by_dev_instrumentation(self, element: ElementContext) -> Optional[SourceMappingResult]:
        src = element.react_source
        if not src:
            return None
        file_name = src.get("fileName") or src.get("file")
        line_number = src.get("lineNumber") or src.get("line")
        if not file_name:
            return None
        resolved = _resolve_existing(self.root, str(file_name))
        if not resolved:
            return None
        verified_line = _verify_line(resolved, line_number)
        return SourceMappingResult(
            resolved=True,
            method="dev_instrumentation",
            component=element.component or _component_from_path(resolved),
            source_file=_rel(self.root, resolved),
            source_line=verified_line,
            confidence=0.9,
            evidence=["React __source development metadata resolved to an existing file."],
        )

    # --- Tier 3: source map ----------------------------------------------

    def _by_source_map(self, element: ElementContext) -> Optional[SourceMappingResult]:
        src = element.source_map
        if not src:
            return None
        file_name = src.get("fileName") or src.get("file")
        line_number = src.get("lineNumber") or src.get("line")
        if not file_name:
            return None
        resolved = _resolve_existing(self.root, str(file_name))
        if not resolved:
            return None
        verified_line = _verify_line(resolved, line_number)
        return SourceMappingResult(
            resolved=True,
            method="source_map",
            component=element.component or _component_from_path(resolved),
            source_file=_rel(self.root, resolved),
            source_line=verified_line,
            confidence=0.85,
            evidence=["Bundler source-map information resolved to an existing file."],
        )

    # --- Tier 4: framework component metadata ----------------------------

    def _by_component(self, element: ElementContext) -> Optional[SourceMappingResult]:
        component = _leaf_component(element.component)
        if not component or not re.match(r"^[A-Z][A-Za-z0-9_]*$", component):
            return None

        # Prefer a file named after the component.
        name_matches = [
            src for src in _iter_source_files(self.root)
            if os.path.splitext(os.path.basename(src))[0] == component
        ]

        def_pattern = re.compile(
            rf'(?:function|class|const|let|var)\s+{re.escape(component)}\b'
            rf'|export\s+default\s+(?:function|class)\s+{re.escape(component)}\b'
        )
        def_matches = _grep(self.root, def_pattern, limit=25)

        results: dict[str, tuple[Optional[int], list[str]]] = {}
        for src in name_matches:
            results.setdefault(src, (None, []))[1].append(f'File named after component "{component}".')
        for src, line, _ in def_matches:
            existing = results.get(src)
            if existing:
                results[src] = (line, existing[1] + [f'"{component}" definition found.'])
            else:
                results[src] = (line, [f'"{component}" definition found.'])

        if not results:
            return None

        if len(results) == 1:
            src, (line, evidence) = next(iter(results.items()))
            return SourceMappingResult(
                resolved=True,
                method="framework_component",
                component=component,
                source_file=_rel(self.root, src),
                source_line=line,
                confidence=0.8,
                evidence=evidence,
            )

        candidates = [
            SourceCandidate(
                component=component,
                source_file=_rel(self.root, src),
                source_line=line,
                confidence=0.55,
                evidence=evidence,
            )
            for src, (line, evidence) in results.items()
        ]
        return SourceMappingResult(resolved=False, method="framework_component", candidates=candidates)

    # --- Tier 5: route ---------------------------------------------------

    def _by_route(self, element: ElementContext) -> Optional[SourceMappingResult]:
        route = element.route
        if not route or route == "/":
            return None
        segments = [s for s in route.strip("/").split("/") if s]
        if not segments:
            return None
        last = segments[-1]
        safe = re.escape(last)
        route_names = {last, "index", "page", "route"}
        matches: list[SourceCandidate] = []
        for src in _iter_source_files(self.root):
            rel = _rel(self.root, src)
            base = os.path.splitext(os.path.basename(src))[0]
            parent = os.path.basename(os.path.dirname(src))
            if base in route_names and (last in rel or parent == last) or base == last:
                if not re.search(safe, rel):
                    continue
                matches.append(
                    SourceCandidate(
                        component=_component_from_path(src),
                        source_file=rel,
                        source_line=None,
                        confidence=0.55,
                        evidence=[f'Route "{route}" matches file location.'],
                    )
                )
        if not matches:
            return None
        return SourceMappingResult(resolved=False, method="route", candidates=matches[:10])

    # --- Tier 6/7: visible text ------------------------------------------

    def _by_text(self, element: ElementContext) -> Optional[SourceMappingResult]:
        text = (element.text or "").strip()
        if not text or len(text) < 3 or len(text) > 60:
            return None
        pattern = re.compile(re.escape(text))
        matches = _grep(self.root, pattern, limit=10)
        if not matches:
            return None
        confidence = 0.55 if len(matches) == 1 else 0.4
        candidates = [
            SourceCandidate(
                component=_component_from_path(src),
                source_file=_rel(self.root, src),
                source_line=line,
                confidence=confidence,
                evidence=[f'Visible text "{text}" found in source.'],
            )
            for src, line, _ in matches
        ]
        if len(candidates) == 1 and confidence >= _RESOLVE_THRESHOLD:
            c = candidates[0]
            return SourceMappingResult(
                resolved=True,
                method="text_search",
                component=c.component,
                source_file=c.source_file,
                source_line=c.source_line,
                confidence=c.confidence,
                evidence=c.evidence,
            )
        return SourceMappingResult(resolved=False, method="text_search", candidates=candidates)

    # --- Tier 8: selector / structural -----------------------------------

    def _by_selector(self, element: ElementContext) -> Optional[SourceMappingResult]:
        token = element.element_id
        if not token:
            classes = (element.class_name or "").split()
            token = next((c for c in classes if not _looks_like_utility_class(c)), None)
        if not token:
            return None
        pattern = re.compile(rf'(?:id|className|class)\s*=\s*["\'][^"\']*\b{re.escape(token)}\b')
        matches = _grep(self.root, pattern, limit=8)
        if not matches:
            return None
        candidates = [
            SourceCandidate(
                component=_component_from_path(src),
                source_file=_rel(self.root, src),
                source_line=line,
                confidence=0.3,
                evidence=[f'Structural token "{token}" found (low confidence heuristic).'],
            )
            for src, line, _ in matches
        ]
        return SourceMappingResult(resolved=False, method="selector_heuristic", candidates=candidates)

    # --- Finalization ----------------------------------------------------

    def _finalize(self, candidates: list[SourceCandidate]) -> SourceMappingResult:
        if not candidates:
            return SourceMappingResult(resolved=False, evidence=["No source mapping could be determined."])
        # Deduplicate by (file, line), keeping highest confidence.
        best: dict[tuple[str, Optional[int]], SourceCandidate] = {}
        for c in candidates:
            key = (c.source_file, c.source_line)
            if key not in best or c.confidence > best[key].confidence:
                best[key] = c
        ordered = sorted(best.values(), key=lambda c: c.confidence, reverse=True)
        top = ordered[0]
        if len(ordered) == 1 and top.confidence >= _RESOLVE_THRESHOLD:
            return SourceMappingResult(
                resolved=True,
                method="candidate",
                component=top.component,
                source_file=top.source_file,
                source_line=top.source_line,
                confidence=top.confidence,
                evidence=top.evidence,
            )
        return SourceMappingResult(resolved=False, method="candidates", candidates=ordered)


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------

def _leaf_component(component: Optional[str]) -> Optional[str]:
    if not component:
        return None
    # "App > Pricing > PricingCTA" -> "PricingCTA"
    parts = [p.strip() for p in re.split(r"[>/]", component) if p.strip()]
    return parts[-1] if parts else None


def _component_from_path(path: str) -> Optional[str]:
    base = os.path.splitext(os.path.basename(path))[0]
    if base in ("index", "page", "route", "layout"):
        parent = os.path.basename(os.path.dirname(path))
        if parent:
            base = parent
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", base):
        return base
    return None


def _verify_line(path: str, line_number: object) -> Optional[int]:
    """Return the line number only if it exists within the file, else None."""
    if not isinstance(line_number, int) or line_number < 1:
        try:
            line_number = int(line_number)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
    lines = _read_lines(path)
    if lines is None:
        return line_number if isinstance(line_number, int) and line_number >= 1 else None
    if 1 <= line_number <= len(lines):
        return line_number
    return None


def _looks_like_utility_class(cls: str) -> bool:
    # Tailwind-style utility classes and dynamic hashes are unreliable selectors.
    if re.search(r"[:\[\]/]", cls):
        return True
    if re.match(r"^(?:sm|md|lg|xl|2xl|hover|focus|active|dark)$", cls):
        return True
    if re.match(r"^(?:p|m|px|py|pt|pb|pl|pr|mx|my|mt|mb|ml|mr|w|h|gap|flex|grid|text|bg|border|rounded|shadow|font)-", cls):
        return True
    if re.search(r"[a-z]+_[A-Za-z0-9]{5,}$", cls):  # css-modules hash e.g. button_a1b2c
        return True
    return False


def element_context_from_browser(result: dict) -> ElementContext:
    """Build an :class:`ElementContext` from a browser-extension inspection result."""
    react_components = result.get("reactComponents") or ""
    component = None
    if react_components:
        parts = [p.strip() for p in react_components.split(">") if p.strip()]
        if parts:
            component = parts[-1]
    return ElementContext(
        arrow_id=result.get("arrowId") or None,
        test_id=result.get("testId") or None,
        react_source=result.get("reactSource") or None,
        source_map=result.get("sourceMap") or None,
        component=component,
        route=result.get("route") or None,
        text=result.get("text") or None,
        selector=result.get("selector") or None,
        tag=result.get("tagName") or None,
        element_id=result.get("id") or None,
        class_name=result.get("className") or None,
    )


__all__ = [
    "ElementContext",
    "SourceCandidate",
    "SourceMappingResult",
    "SourceMapper",
    "element_context_from_browser",
]
