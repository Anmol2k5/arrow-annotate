"""Immutable handoff snapshots built from a specific persisted capture."""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from arrow.intent.prompt_builder import format_prompt, window_text_markdown


@dataclass(frozen=True)
class CaptureBundle:
    directory: str
    prompt_text: str
    prompt_path: str
    context_path: str
    annotated_path: Optional[str]
    assets: dict[str, str]
    metadata: dict


def build_capture_bundle(capture_id: str, db_path=None) -> CaptureBundle:
    from arrow.core.paths import application_home
    from arrow.storage.capture_store import CaptureStore
    from arrow.storage.database import get_db_connection
    from arrow.storage.repository import Repository
    capture = Repository(db_path).get_capture(capture_id)
    if capture is None:
        raise LookupError(f"No capture found: {capture_id}")
    record = CaptureStore(db_path).get(capture_id)
    request = capture['change_request']
    metadata = {
        'capture_id': capture_id,
        'current_instruction': request.get('raw_user_request') or (record.annotation_text if record else ''),
        'original_voice_transcript': record.original_voice_transcript if record else None,
        'annotations': record.annotations if record else [],
        'capture_context': record.capture_context if record else {},
        'change_request': request,
        'repository_path': (request.get('project') or {}).get('repository_root'),
        'data_provenance': {'original_voice_transcript':
            'recorded' if record and record.original_voice_transcript is not None else 'not_recorded'},
    }
    images = {}
    digester = hashlib.sha256(json.dumps(metadata, sort_keys=True, ensure_ascii=False).encode())
    for key in ('raw', 'annotated', 'source-crop', 'destination-crop', 'context-crop', 'agent-annotated', 'agent-crop'):
        path = capture['assets'].get(key)
        if path and Path(path).is_file():
            content = Path(path).read_bytes()
            if content.startswith(b'\x89PNG'):
                images[key] = (path, content)
                digester.update(key.encode() + content)
    identity = hashlib.sha256(capture_id.encode()).hexdigest()[:20]
    directory = application_home() / 'handoffs' / identity / digester.hexdigest()[:20]
    directory.mkdir(parents=True, exist_ok=True)
    def write_atomic(target, content):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, delete=False) as stream:
                temporary = stream.name
                stream.write(content)
            os.replace(temporary, target)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
    assets = {}
    for key, (source, content) in images.items():
        target = directory / (key + '.png')
        # The bundle directory is content-addressed, but another app/client can
        # still alter its files. Never hand off stale or corrupted cached pixels.
        if not target.is_file() or target.read_bytes() != content:
            write_atomic(target, content)
        assets[key] = str(target)
    annotated = assets.get('agent-annotated') or assets.get('annotated')
    context = directory / 'capture.json'
    prompt = directory / 'prompt.md'
    text = (format_prompt({**request, 'raw_user_request': metadata['current_instruction']}) + '\n'
            f"Annotated image: {annotated or 'not recorded'}\n\n"
            f"MCP: call arrow_get_capture_bundle with capture_id={capture_id!r} to retrieve this exact capture and image.\n\n"
            f"Complete structured context: {context}\n"
            + window_text_markdown(metadata['capture_context'].get('window_context', {})))
    write_atomic(context, json.dumps(metadata, indent=2, ensure_ascii=False).encode('utf-8'))
    write_atomic(prompt, text.encode('utf-8'))
    with get_db_connection(db_path) as conn:
        for target in (context, prompt, *(Path(path) for path in assets.values())):
            if not conn.execute('SELECT 1 FROM assets WHERE capture_id=? AND path=?', (capture_id, str(target))).fetchone():
                conn.execute('INSERT INTO assets(capture_id,path,type) VALUES(?,?,?)',
                             (capture_id, str(target), 'handoff'))
        conn.commit()
    return CaptureBundle(str(directory), text, str(prompt), str(context), annotated, assets, metadata)
