import pytest
import re
from arrow.capture.session import SessionManager, CaptureState, generate_uuidv7

def test_uuidv7_format():
    uid = generate_uuidv7()
    # Check standard UUID regex: 8-4-4-4-12 hex chars
    assert re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", uid)

def test_session_manager_lifecycle():
    manager = SessionManager()
    assert manager.active_session is None
    
    # Start session
    session = manager.start_session()
    assert manager.active_session is not None
    assert session.state == CaptureState.STARTING
    assert session.capture_id is not None
    
    # Move through states
    manager.transition_to(CaptureState.ANNOTATING)
    assert session.state == CaptureState.ANNOTATING
    
    manager.transition_to(CaptureState.COLLECTING_CONTEXT)
    assert session.state == CaptureState.COLLECTING_CONTEXT

    manager.transition_to(CaptureState.PROCESSING)
    assert session.state == CaptureState.PROCESSING

    manager.transition_to(CaptureState.PREVIEW)
    assert session.state == CaptureState.PREVIEW
    
    manager.transition_to(CaptureState.READY)
    assert session.state == CaptureState.READY
    
    manager.transition_to(CaptureState.SENDING)
    assert session.state == CaptureState.SENDING

    manager.transition_to(CaptureState.RUNNING)
    assert session.state == CaptureState.RUNNING

    manager.transition_to(CaptureState.COMPLETED)
    assert session.state == CaptureState.COMPLETED

def test_invalid_transitions():
    manager = SessionManager()
    session = manager.start_session()
    
    # Try transitioning to an invalid state directly (e.g. from STARTING to COMPLETED)
    with pytest.raises(ValueError) as excinfo:
        manager.transition_to(CaptureState.COMPLETED)
    assert "Invalid state transition" in str(excinfo.value)
    
    # Verify current state remains unchanged
    assert session.state == CaptureState.STARTING

def test_cancellation():
    manager = SessionManager()
    session = manager.start_session()
    
    # Transition to ANNOTATING
    manager.transition_to(CaptureState.ANNOTATING)
    
    # Cancel session
    manager.transition_to(CaptureState.CANCELLED)
    assert session.state == CaptureState.CANCELLED
    
    # Cannot transition to an active state once cancelled
    with pytest.raises(ValueError):
        manager.transition_to(CaptureState.PROCESSING)

def test_auto_cancellation_of_previous_session():
    manager = SessionManager()
    
    first_session = manager.start_session()
    manager.transition_to(CaptureState.ANNOTATING)
    
    # Starting a new session should cancel the first one
    second_session = manager.start_session()
    assert first_session.state == CaptureState.CANCELLED
    assert second_session.state == CaptureState.STARTING
    assert manager.active_session.capture_id == second_session.capture_id
