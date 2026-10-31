"""Persist explicit capture corrections without rewriting original evidence/assets."""
from copy import deepcopy

from arrow.intent.compiler import recompile_change_request
from arrow.storage.capture_store import CaptureStore


def save_review(capture_id, instruction, window_texts, include_window_text=True, *, store=None):
    instruction = instruction.strip()
    if not instruction:
        raise ValueError('Enter an instruction before saving the review.')
    store = store or CaptureStore()
    record = store.get(capture_id)
    if record is None:
        raise ValueError('This capture was deleted. Make a new capture.')
    request = recompile_change_request(record.change_request or {'capture_id': capture_id}, instruction)
    if request is None:
        raise ValueError('Capture request could not be updated.')
    context = deepcopy(record.capture_context)
    for role, window in context.get('window_context', {}).items():
        changed = not include_window_text or window_texts.get(role, window.get('text', '')) != window.get('text', '')
        if include_window_text:
            new_text = window_texts.get(role, window.get('text', ''))
            if new_text != window.get('text', ''):
                window['status'] = 'edited_by_user'
            window['text'] = new_text
        else:
            window['text'] = ''
            window['status'] = 'excluded_by_user'
        window['included'] = bool(include_window_text)
        if changed:
            # Names/text may have been duplicated into the selected element and
            # its compiled label. Keep geometry/IDs; don't export superseded text.
            window.pop('element', None)
            anchor = getattr(request, role, None)
            if anchor is not None:
                anchor.label = 'selected region'
                anchor.element = _without_observed_text(anchor.element)
            observed = context.get(role)
            if isinstance(observed, dict):
                context[role] = _without_observed_text(observed)
    # Optional legacy AX trees can duplicate the document text without role IDs.
    if not include_window_text or any(w.get('status') == 'edited_by_user' for w in context.get('window_context', {}).values()):
        context.pop('ax_tree', None)
        context.pop('change_request', None)
        # Rebuild generated summaries/criteria from the scrubbed anchors too.
        request = recompile_change_request(request.to_dict(), instruction)
    record_request = request.to_dict()
    context['review'] = {'instruction_reviewed': True, 'window_text_included': bool(include_window_text)}
    store.update_change_request(capture_id, record_request, annotation_text=instruction, capture_context=context)
    from arrow.capture.context_file import refresh_latest_if_current
    from arrow.context.capture_bundle import build_capture_bundle
    bundle = build_capture_bundle(capture_id, store._db_path)
    refresh_latest_if_current(bundle.annotated_path or '', bundle.prompt_text, capture_id, bundle.assets)
    return store.get(capture_id)


def _without_observed_text(value):
    if isinstance(value, dict):
        return {key: _without_observed_text(item) for key, item in value.items()
                if key not in {'name', 'text', 'selected_text', 'innerHtml', 'outerHtml', 'accessibility', 'label'}}
    if isinstance(value, list):
        return [_without_observed_text(item) for item in value]
    return value
