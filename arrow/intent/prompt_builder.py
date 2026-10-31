"""Readable prompts; structured inference diagnostics stay in the capture JSON."""
from __future__ import annotations

from arrow.intent.schemas import ChangeRequest


def anchor_label(anchor: dict) -> str:
    if not anchor:
        return ''
    label = anchor.get('label') or ''
    generic = {'source', 'destination', '1 source', '2 destination', 'selected region', 'current element', 'move here'}
    if label.strip().lower() not in generic and label:
        return label
    element = anchor.get('element') or {}
    return (element.get('name') or element.get('text') or element.get('selector') or anchor.get('selector')
            or ('selected region' if anchor.get('geometry') else label))


def format_prompt(request: dict | None) -> str:
    if not request:
        return ''
    lines = ['# Arrow change request', '', f"**Instruction:** {request.get('raw_user_request') or 'Explain the annotated screen.'}", '']
    for role, marker in (('source', '1 Source'), ('destination', '2 Destination')):
        anchor = request.get(role) or {}
        label = anchor_label(anchor)
        if label:
            lines.append(f'**{role.title()}:** {label}')
            if anchor.get('screenshot_marker') == marker:
                lines.append(f'**{role.title()} marker in annotated screenshot:** {marker}')
        elif role == 'destination' and request.get('normalized_intent') == 'move_element':
            lines.append('**Destination:** Not provided; ask where the element should go before implementation.')
    if request.get('clarification_required'):
        lines.extend(['', 'Ask for clarification before implementation if the instruction or target is unclear.'])
    files = request.get('likely_files') or []
    if files:
        lines.extend(['', '**Likely files:**'])
        for item in files:
            suffix = f":{item['source_line']}" if item.get('source_line') is not None else ''
            lines.append(f"- {item['source_file']}{suffix}")
    for title, key in (('Acceptance criteria', 'acceptance_criteria'), ('Constraints', 'constraints')):
        if request.get(key):
            lines.extend(['', f'**{title}:**', ''])
            lines.extend(f'- {item}' for item in request[key])
    return '\n'.join(lines).strip() + '\n'


def window_text_markdown(windows: dict) -> str:
    if not windows:
        return ''
    lines = ['\n## Window text\n']
    for role, window in windows.items():
        lines.append(f"### {role.title()} · {window.get('window_title', '')}")
        lines.append(f"Text status: {window.get('status', 'unavailable')}")
        if window.get('included', True) and window.get('text'):
            lines.extend(['', window['text'], ''])
    return '\n'.join(lines)


def build_markdown(req: ChangeRequest) -> str:
    return format_prompt(req.to_dict())


__all__ = ['build_markdown', 'format_prompt', 'anchor_label', 'window_text_markdown']
