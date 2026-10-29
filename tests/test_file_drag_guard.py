"""A global modifier gesture is not evidence of a dragged file."""
from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent


@pytest.fixture
def gate(qt_session):
    from dragshift.file_drag import FileDragGate
    state = [True, True, False]
    receiver = FileDragGate(lambda: tuple(state))
    receiver.enabled = lambda: True
    events = []
    receiver.ready.connect(lambda pos, paths: events.append((pos, paths)))
    yield receiver, state, events
    receiver.cancel()
    receiver.close()


def enter(receiver, mime):
    event = QDragEnterEvent(QPoint(2, 2), Qt.CopyAction | Qt.MoveAction,
                            mime, Qt.LeftButton, Qt.ShiftModifier)
    receiver.dragEnterEvent(event)
    return event


def test_candidate_has_no_menu_keyboard_focus_or_mouse_grab(gate, qt_session):
    receiver, _, events = gate
    receiver.request(QPoint(320, 240))
    qt_session.processEvents()
    assert not events
    assert receiver.testAttribute(Qt.WA_ShowWithoutActivating)
    assert receiver.windowFlags() & Qt.WindowDoesNotAcceptFocus
    assert receiver.mouseGrabber() is not receiver
    assert receiver.width() <= 16 and receiver.height() <= 16


@pytest.mark.parametrize('kind', ['text', 'remote', 'missing', 'empty'])
def test_non_file_drag_never_opens_tools(gate, kind, tmp_path, qt_session):
    receiver, _, events = gate
    receiver.request(QPoint(320, 240))
    mime = QMimeData()
    if kind == 'text':
        mime.setText('selected text in another application')
    elif kind == 'remote':
        mime.setUrls([QUrl('https://example.org/image.png')])
    elif kind == 'missing':
        mime.setUrls([QUrl.fromLocalFile(str(tmp_path / 'missing.png'))])
    event = enter(receiver, mime)
    qt_session.processEvents()
    assert not event.isAccepted() and not events and not receiver.isVisible()


def test_real_file_payload_opens_once_and_forces_copy(gate, tmp_path, qt_session):
    receiver, _, events = gate
    chosen = tmp_path / 'chosen.png'
    chosen.touch()
    receiver.request(QPoint(320, 240))
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(chosen))])
    event = enter(receiver, mime)
    qt_session.processEvents()
    assert event.isAccepted() and event.dropAction() == Qt.CopyAction
    assert len(events) == 1 and events[0][0] == QPoint(320, 240)
    assert [Path(p) for p in events[0][1]] == [chosen]
    assert not receiver.isVisible()
    enter(receiver, mime)
    qt_session.processEvents()
    assert len(events) == 1


@pytest.mark.parametrize('reason', ['release', 'escape', 'disabled', 'cancel', 'timeout'])
def test_late_payload_after_cancel_does_not_open_tools(gate, reason, tmp_path, qt_session):
    receiver, state, events = gate
    chosen = tmp_path / 'chosen.png'
    chosen.touch()
    receiver.request(QPoint(320, 240))
    if reason == 'release':
        state[0] = False
    elif reason == 'escape':
        state[2] = True
    elif reason == 'disabled':
        receiver.enabled = lambda: False
    elif reason == 'cancel':
        receiver.cancel()
    else:
        receiver._deadline = 0
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(chosen))])
    enter(receiver, mime)
    qt_session.processEvents()
    assert not events and not receiver.isVisible()


def test_mac_fast_path_requires_fresh_gesture_payload(gate, monkeypatch, tmp_path):
    receiver, _, events = gate
    chosen = tmp_path / 'chosen.png'
    chosen.touch()
    from dragshift import file_drag
    from types import SimpleNamespace
    generation = [10]
    mac = SimpleNamespace(drag_generation=lambda: generation[0], drag_files=lambda: [str(chosen)])
    monkeypatch.setattr(file_drag, 'sys', SimpleNamespace(platform='darwin'))
    monkeypatch.setattr(file_drag, '_mac_backend', lambda: mac)
    receiver.begin_gesture()
    receiver.request(QPoint(320, 240))
    assert not events  # A previous drag's still-populated pasteboard is insufficient.
    receiver.cancel()
    generation[0] = 11
    receiver.request(QPoint(320, 240))
    assert len(events) == 1
    receiver.cancel()
    receiver.begin_gesture()
    receiver.request(QPoint(320, 240))
    assert len(events) == 1


def test_queued_previous_drag_cannot_replace_new_drag(gate, tmp_path, qt_session):
    receiver, _, events = gate
    first, second = tmp_path / 'old.png', tmp_path / 'new.png'
    first.touch()
    second.touch()
    mime_a, mime_b = QMimeData(), QMimeData()
    mime_a.setUrls([QUrl.fromLocalFile(str(first))])
    mime_b.setUrls([QUrl.fromLocalFile(str(second))])
    receiver.request(QPoint(320, 240))
    enter(receiver, mime_a)
    receiver.cancel()
    receiver.request(QPoint(400, 300))
    enter(receiver, mime_b)
    qt_session.processEvents()
    assert len(events) == 1 and events[0][0] == QPoint(400, 300)
    assert [Path(p) for p in events[0][1]] == [second]


def test_validated_payload_keeps_radial_in_drag_mode(qt_session,tmp_path,monkeypatch):
    from dragshift.radial import RadialMenu,Item
    chosen=tmp_path/'chosen.png'
    chosen.touch()
    ring=RadialMenu(lambda _: {'Tools':[Item('Crop',key='tool:Crop')]},lambda _:'1 file')
    monkeypatch.setattr(ring,'_capture',lambda *args:None)
    try:
        ring.popup(QPoint(320,240),drag_paths=[str(chosen)])
        assert ring.isVisible() and ring.got_drag and not ring.click_mode
        assert [Path(p) for p in ring.paths]==[chosen]
        assert ring.mouseGrabber() is not ring
    finally:
        ring.close_menu()
