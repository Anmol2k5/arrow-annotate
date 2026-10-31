from types import SimpleNamespace

from arrow.capture.coordinate_mapper import ScreenInfo


class Control:
    def __init__(self, name, children=(), password=False):
        self.Name, self.children, self.IsPassword = name, children, password
        self.ControlTypeName = 'TextControl'

    def GetChildren(self):
        return list(self.children)


def test_window_text_contains_the_whole_accessible_tree_but_not_passwords():
    from arrow.context.window_text import read_accessible_window
    root = Control('Editor', [Control('Save'), Control('document content'), Control('secret', password=True)])
    result = read_accessible_window(root)
    assert result['text'] == 'Editor\nSave\ndocument content'
    assert result['truncated'] is False
    assert result['available'] is True


def test_window_text_marks_bounded_extraction_as_partial():
    from arrow.context.window_text import read_accessible_window
    result = read_accessible_window(Control('a' * 100), max_chars=20)
    assert len(result['text']) == 20
    assert result['truncated'] is True


def test_window_owners_are_frozen_per_anchor_with_negative_origin_and_dpi():
    from arrow.context.window_text import freeze_window_targets
    points = []
    def locate(x, y):
        points.append((x, y))
        return {'handle': len(points), 'window_title': 'Window ' + str(len(points))}
    annotations = [SimpleNamespace(role='source', geometry={'x': -1900, 'y': 20, 'width': 20, 'height': 20}),
                   SimpleNamespace(role='destination', geometry={'x': 100, 'y': 100, 'width': 20, 'height': 20})]
    screens = [ScreenInfo('left', (-1920, 0, 1280, 720), 1.5), ScreenInfo('main', (0, 0, 1920, 1080), 1)]
    targets = freeze_window_targets(annotations, screens=screens, owner_lookup=locate)
    assert points == [(-1875, 45), (110, 110)]
    assert targets['source']['handle'] == 1 and targets['destination']['handle'] == 2


def test_unavailable_window_access_does_not_fabricate_text():
    from arrow.context.window_text import collect_window_contexts
    data = collect_window_contexts({'source': {'handle': 42, 'window_title': 'Known title'}},
                                   reader=lambda target: {'available': False, 'text': '', 'status': 'unavailable'})
    assert data['source']['window_title'] == 'Known title'
    assert data['source']['text'] == '' and data['source']['available'] is False


def test_document_pattern_failure_keeps_accessible_child_text_and_reports_partial():
    from arrow.context.window_text import read_accessible_window
    root = Control('Window', [Control('Visible document content')])
    root.ControlTypeName = 'DocumentControl'
    def unavailable_pattern():
        raise RuntimeError('Provider does not implement TextPattern')
    root.GetTextPattern = unavailable_pattern
    result = read_accessible_window(root)
    assert 'Visible document content' in result['text']
    assert result['status'] == 'partial'


def test_unknown_owner_is_retained_as_unavailable_instead_of_reusing_foreground():
    from arrow.context.window_text import collect_window_contexts, freeze_window_targets
    annotations = [SimpleNamespace(role='source', geometry={'x': 1, 'y': 2})]
    targets = freeze_window_targets(annotations, screens=[ScreenInfo('main', (0, 0, 100, 100), 1)],
                                    owner_lookup=lambda x, y: {})
    result = collect_window_contexts(targets)
    assert result['source']['available'] is False
    assert result['source']['text'] == ''
