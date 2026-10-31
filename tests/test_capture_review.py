from pathlib import Path

import pytest
from PIL import Image

from arrow.context.capture_bundle import build_capture_bundle
from arrow.intent.compiler import CompilerInput, IntentCompiler
from arrow.storage.capture_store import CaptureStore
from arrow.storage.schemas import CaptureRecord


def saved_capture(tmp_path):
    image = tmp_path / 'annotated.png'
    Image.new('RGB', (100, 80), 'red').save(image)
    request = IntentCompiler().compile(CompilerInput(capture_id='review', raw_instruction='Explain this',
        assets={'annotated': str(image)})).to_dict()
    store = CaptureStore(str(tmp_path / 'review.db'))
    store.add(CaptureRecord(id='review', timestamp='now', screenshot_path=str(image),
        annotation_text='Explain this', original_voice_transcript='Original speech',
        change_request=request, capture_context={'window_context': {
            'source': {'window_title': 'Editor', 'text': 'Secret document', 'status': 'complete', 'available': True}}}))
    return store


def test_review_edits_reach_mcp_bundle_without_changing_original_voice_or_assets(tmp_path, monkeypatch):
    from arrow.context.review import save_review
    monkeypatch.setenv('ARROW_HOME', str(tmp_path / 'home'))
    store = saved_capture(tmp_path)
    first = build_capture_bundle('review', store._db_path)
    save_review('review', 'Explain the red button', {'source': 'Reviewed document'}, True, store=store)
    second = build_capture_bundle('review', store._db_path)
    assert first.directory != second.directory
    assert second.metadata['current_instruction'] == 'Explain the red button'
    assert second.metadata['original_voice_transcript'] == 'Original speech'
    assert second.metadata['capture_context']['window_context']['source']['text'] == 'Reviewed document'
    assert 'Secret document' not in second.prompt_text
    assert 'Reviewed document' in second.prompt_text
    assert Image.open(second.annotated_path).size == (100, 80)
    assert 'Secret document' in Path(first.context_path).read_text()


def test_review_excludes_window_text_from_future_exports_and_rejects_empty_instruction(tmp_path, monkeypatch):
    from arrow.context.review import save_review
    monkeypatch.setenv('ARROW_HOME', str(tmp_path / 'home'))
    store = saved_capture(tmp_path)
    save_review('review', 'Explain this', {'source': 'Secret document'}, False, store=store)
    bundle = build_capture_bundle('review', store._db_path)
    assert 'Secret document' not in bundle.prompt_text
    assert bundle.metadata['capture_context']['window_context']['source']['status'] == 'excluded_by_user'
    with pytest.raises(ValueError, match='instruction'):
        save_review('review', '  ', {}, True, store=store)
    assert store.get('review').annotation_text == 'Explain this'


def test_clean_prompt_leads_with_instruction_and_only_records_real_markers():
    from arrow.intent.prompt_builder import format_prompt
    prompt = format_prompt({'raw_user_request': 'Move this here', 'normalized_intent': 'unknown', 'confidence': .2,
        'source': {'label': 'Buy', 'screenshot_marker': '1 Source'},
        'destination': {'label': 'Toolbar', 'screenshot_marker': '2 Destination'},
        'inferences': [{'field': 'likely_files', 'reason': 'No repository file'}]})
    assert prompt.index('Move this here') < prompt.index('1 Source') < prompt.index('2 Destination')
    assert 'unknown' not in prompt.lower() and 'confidence' not in prompt.lower()
    assert 'Inferences' not in prompt and 'No repository file' not in prompt


def test_review_opens_inside_notch_before_agent_handoff_and_persists_corrections(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QApplication, QDialog

    from arrow.storage import database, settings
    from arrow.ui.notch import DynamicNotch
    monkeypatch.setenv('ARROW_HOME', str(tmp_path / 'home'))
    store = saved_capture(tmp_path)
    monkeypatch.setattr(database, 'DB_PATH', store._db_path)
    settings.set_project_dir(str(tmp_path))
    app = QApplication.instance() or QApplication([])
    notch = DynamicNotch()
    card = notch._screens_view._thumbnails[0]
    opened = []
    monkeypatch.setattr(card, '_run_provider_thread', lambda *args: opened.append(args))
    card._send_to_provider('Codex')
    assert opened == []
    review = notch._review_view
    assert notch._content_stack.currentWidget() is review
    assert not notch.findChildren(QDialog)
    assert review.image.size().width() == 100
    review.instruction.setPlainText('Use the reviewed instruction')
    review.window_editors['source'].setPlainText('Corrected context')
    assert review.save()
    # The callback starts only after the explicit Save and open button action.
    import time
    deadline = time.monotonic() + 1
    while not opened and time.monotonic() < deadline:
        app.processEvents()
    assert len(opened) == 1
    card._copy_request('text')
    assert 'Corrected context' in app.clipboard().text()
    assert 'Secret document' not in app.clipboard().text()
    assert 'Original speech' not in app.clipboard().text()
    bundle = build_capture_bundle('review', store._db_path)
    assert 'Corrected context' in bundle.prompt_text
    assert bundle.metadata['original_voice_transcript'] == 'Original speech'
    notch.close()
    app.processEvents()


def test_excluding_window_text_removes_duplicated_selected_text_and_refreshes_matching_mirror(tmp_path, monkeypatch):
    from arrow.capture.context_file import latest_dir, mirror_latest
    from arrow.context.review import save_review
    monkeypatch.setenv('ARROW_HOME', str(tmp_path / 'home'))
    store = saved_capture(tmp_path)
    cap = store.get('review')
    cap.capture_context['window_context']['source']['element'] = {'name': 'Secret document'}
    cap.capture_context['source'] = {'context': {'name': 'Secret document', 'text': 'Secret document'}}
    cap.change_request = IntentCompiler().compile(CompilerInput(capture_id='review', raw_instruction='Explain this',
        source_context={'name': 'Secret document', 'text': 'Secret document', 'source': 'windows_uia'},
        assets=cap.change_request['assets'])).to_dict()
    store.add(cap)
    mirror_latest(cap.screenshot_path, 'old instruction Secret document', 'review')
    save_review('review', 'Corrected instruction', {}, False, store=store)
    bundle = build_capture_bundle('review', store._db_path)
    assert 'Secret document' not in bundle.prompt_text
    assert 'Secret document' not in Path(bundle.context_path).read_text()
    mirrored = Path(latest_dir(), 'context.md').read_text()
    assert 'Corrected instruction' in mirrored and 'Secret document' not in mirrored
    assert store.get('review').original_voice_transcript == 'Original speech'


def test_missing_image_never_emits_review_completion(tmp_path):
    from PyQt6.QtWidgets import QApplication

    from arrow.ui.capture_review import CaptureReview
    app = QApplication.instance() or QApplication([])
    store = saved_capture(tmp_path)
    Path(store.get('review').screenshot_path).unlink()
    review = CaptureReview('review', store=store)
    sent = []
    review.saved.connect(sent.append)
    assert not review.save()
    assert sent == [] and 'missing' in review.status.text()
    review.close()
    app.processEvents()


def test_copy_in_the_notch_requires_review_once_and_then_supports_the_second_step(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QApplication

    from arrow.storage import database
    from arrow.ui.notch import DynamicNotch
    monkeypatch.setenv('ARROW_HOME', str(tmp_path / 'home'))
    store = saved_capture(tmp_path)
    monkeypatch.setattr(database, 'DB_PATH', store._db_path)
    app = QApplication.instance() or QApplication([])
    app.clipboard().setText('unchanged')
    notch = DynamicNotch()
    card = notch._screens_view._thumbnails[0]
    card._copy_request()
    assert app.clipboard().text() == 'unchanged'
    review = notch._review_view
    assert 'Save and copy' in review.save_button.text()
    assert review.save()
    assert app.clipboard().mimeData().hasImage()
    card._copy_request()
    assert 'Explain this' in app.clipboard().text()
    assert notch._content_stack.currentWidget() is notch._screens_view
    notch.close()
    app.processEvents()
