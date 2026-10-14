import pytest

from arrow.providers.agentation import AgentationClient, AgentationError


def test_agentation_reuses_only_active_matching_session(monkeypatch):
    client = AgentationClient()
    monkeypatch.setattr(client, 'list_sessions', lambda: [
        {'id': 'other', 'url': 'https://other.example', 'status': 'active'},
        {'id': 'closed', 'url': 'bluely://desktop', 'status': 'closed'},
        {'id': 'matching', 'url': 'bluely://desktop', 'status': 'active'},
    ])
    assert client.get_or_create_session('bluely://desktop')['id'] == 'matching'


def test_agentation_does_not_treat_a_session_id_as_an_annotation_id():
    with pytest.raises(AgentationError, match='does not expose'):
        AgentationClient().close_session('session-id')
