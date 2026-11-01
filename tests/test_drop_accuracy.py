from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication

from dragshift.radial import Item, RadialMenu


def test_final_drop_payload_wins_over_stale_drag_entry(tmp_path):
    app = QApplication.instance() or QApplication([])
    first, chosen = tmp_path / 'neighbor.mp4', tmp_path / 'chosen.mp4'
    first.touch()
    chosen.touch()
    ring = RadialMenu(lambda paths: {'Convert': [Item('WEBM', key='convert:WEBM')]}, lambda paths: paths[0])
    ring._load([str(first)])
    got = []
    ring.activated.connect(lambda item, paths: got.append(paths))
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(chosen))])
    event = QDropEvent(QPointF(200, 90), Qt.CopyAction | Qt.MoveAction, mime, Qt.LeftButton, Qt.ShiftModifier)
    ring.dropEvent(event)
    app.processEvents()
    assert len(got) == 1 and [__import__('pathlib').Path(p) for p in got[0]] == [chosen]
    assert event.dropAction() == Qt.CopyAction
    ring.close()


def test_missing_payload_never_runs_cached_file():
    app = QApplication.instance() or QApplication([])
    ring = RadialMenu(lambda paths: {'Convert': [Item('WEBM', key='convert:WEBM')]}, lambda paths: '')
    ring._load(['neighbor.mp4'])
    got = []
    ring.activated.connect(lambda *args: got.append(args))
    mime = QMimeData()  # QDropEvent borrows it; retain until dispatch completes.
    event = QDropEvent(QPointF(200, 90), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    ring.dropEvent(event)
    app.processEvents()
    assert not got and not event.isAccepted()
    ring.close()


def test_rename_uses_the_selected_shortcut_while_conversion_resolves_it(qt_session,tmp_path,monkeypatch):
    from dragshift import radial
    target=tmp_path/'target.png';target.touch()
    shortcut=tmp_path/'selected.lnk';shortcut.touch()
    monkeypatch.setattr(radial,'resolve_shortcuts',lambda paths:[str(target)])
    for key,expected in [('tool:Rename',shortcut),('convert:PNG',target)]:
        ring=RadialMenu(lambda paths:{'Tools':[Item('Action',key=key)]},lambda paths:'')
        ring._load([str(shortcut)])
        got=[];ring.activated.connect(lambda item,paths:got.append(paths))
        mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(shortcut))])
        event=QDropEvent(QPointF(200,90),Qt.CopyAction,mime,Qt.LeftButton,Qt.ShiftModifier)
        ring.dropEvent(event);qt_session.processEvents()
        assert got and [__import__('pathlib').Path(p) for p in got[0]]==[expected]
        ring.close()
