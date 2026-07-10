import os

from arrow.context.source_mapper import (
    ElementContext,
    SourceMapper,
    element_context_from_browser,
)


def _write(root, rel, content):
    path = os.path.join(root, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def test_no_repository_root():
    mapper = SourceMapper(None)
    result = mapper.map(ElementContext(component="PricingCTA"))
    assert result.resolved is False
    assert result.source_file is None


def test_arrow_id_exact_match(tmp_path):
    root = str(tmp_path)
    _write(root, "src/components/PricingCTA.tsx",
           'export function PricingCTA() {\n  return <button data-arrow-id="pricing-primary-cta">Buy</button>;\n}\n')
    mapper = SourceMapper(root)
    result = mapper.map(ElementContext(arrow_id="pricing-primary-cta"))
    assert result.resolved is True
    assert result.method == "data_arrow_id"
    assert result.source_file == "src/components/PricingCTA.tsx"
    assert result.source_line == 2
    assert result.confidence >= 0.9


def test_arrow_id_takes_priority_over_component(tmp_path):
    root = str(tmp_path)
    _write(root, "src/A.tsx", 'const Widget = () => <div data-arrow-id="x1">hi</div>;\n')
    _write(root, "src/Widget.tsx", 'export function Widget() { return null; }\n')
    mapper = SourceMapper(root)
    result = mapper.map(ElementContext(arrow_id="x1", component="Widget"))
    assert result.resolved is True
    assert result.method == "data_arrow_id"
    assert result.source_file == "src/A.tsx"


def test_dev_instrumentation_verified_file(tmp_path):
    root = str(tmp_path)
    _write(root, "src/components/Card.tsx", "line1\nline2\nline3\n")
    mapper = SourceMapper(root)
    element = ElementContext(react_source={"fileName": "src/components/Card.tsx", "lineNumber": 2})
    result = mapper.map(element)
    assert result.resolved is True
    assert result.method == "dev_instrumentation"
    assert result.source_file == "src/components/Card.tsx"
    assert result.source_line == 2


def test_dev_instrumentation_absolute_path(tmp_path):
    root = str(tmp_path)
    abspath = _write(root, "src/Header.tsx", "a\nb\n")
    mapper = SourceMapper(root)
    element = ElementContext(react_source={"fileName": abspath, "lineNumber": 1})
    result = mapper.map(element)
    assert result.resolved is True
    assert result.source_file == "src/Header.tsx"


def test_never_fabricate_nonexistent_file(tmp_path):
    root = str(tmp_path)
    mapper = SourceMapper(root)
    element = ElementContext(react_source={"fileName": "src/DoesNotExist.tsx", "lineNumber": 5})
    result = mapper.map(element)
    assert result.resolved is False
    assert result.source_file is None


def test_line_out_of_range_is_dropped(tmp_path):
    root = str(tmp_path)
    _write(root, "src/Small.tsx", "only one line\n")
    mapper = SourceMapper(root)
    element = ElementContext(react_source={"fileName": "src/Small.tsx", "lineNumber": 999})
    result = mapper.map(element)
    assert result.resolved is True
    assert result.source_line is None


def test_component_single_definition(tmp_path):
    root = str(tmp_path)
    _write(root, "src/components/PricingCTA.tsx", "export function PricingCTA() { return null; }\n")
    mapper = SourceMapper(root)
    result = mapper.map(ElementContext(component="App > PricingCTA"))
    assert result.resolved is True
    assert result.method == "framework_component"
    assert result.source_file == "src/components/PricingCTA.tsx"
    assert result.component == "PricingCTA"


def test_component_multiple_returns_candidates(tmp_path):
    root = str(tmp_path)
    _write(root, "src/a/Button.tsx", "export function Button() { return null; }\n")
    _write(root, "src/b/Button.tsx", "export const Button = () => null;\n")
    mapper = SourceMapper(root)
    result = mapper.map(ElementContext(component="Button"))
    assert result.resolved is False
    assert len(result.candidates) == 2
    files = {c.source_file for c in result.candidates}
    assert files == {"src/a/Button.tsx", "src/b/Button.tsx"}


def test_text_search_fallback(tmp_path):
    root = str(tmp_path)
    _write(root, "src/Banner.jsx", 'export const Banner = () => <h1>Welcome Aboard</h1>;\n')
    mapper = SourceMapper(root)
    result = mapper.map(ElementContext(text="Welcome Aboard"))
    assert (result.resolved and result.source_file == "src/Banner.jsx") or any(
        c.source_file == "src/Banner.jsx" for c in result.candidates
    )


def test_no_mapping_returns_unresolved(tmp_path):
    root = str(tmp_path)
    _write(root, "src/Unrelated.tsx", "export const X = () => null;\n")
    mapper = SourceMapper(root)
    result = mapper.map(ElementContext(text="nothing matches here xyz"))
    assert result.resolved is False


def test_priority_dev_over_component(tmp_path):
    root = str(tmp_path)
    _write(root, "src/Real.tsx", "a\nb\nc\n")
    _write(root, "src/Widget.tsx", "export function Widget() { return null; }\n")
    mapper = SourceMapper(root)
    element = ElementContext(
        react_source={"fileName": "src/Real.tsx", "lineNumber": 2},
        component="Widget",
    )
    result = mapper.map(element)
    assert result.method == "dev_instrumentation"
    assert result.source_file == "src/Real.tsx"


def test_element_context_from_browser():
    result = {
        "arrowId": "cta",
        "testId": "buy",
        "reactComponents": "App > Pricing > PricingCTA",
        "reactSource": {"fileName": "src/x.tsx", "lineNumber": 3},
        "route": "/pricing",
        "text": "Buy now",
        "selector": "#buy",
        "tagName": "button",
        "id": "buy",
        "className": "btn primary",
    }
    element = element_context_from_browser(result)
    assert element.arrow_id == "cta"
    assert element.test_id == "buy"
    assert element.component == "PricingCTA"
    assert element.react_source == {"fileName": "src/x.tsx", "lineNumber": 3}
    assert element.route == "/pricing"
