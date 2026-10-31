import time

from PySide6.QtCore import QMimeData,Qt,QUrl
from PySide6.QtTest import QTest

from dragshift import bulk_rename,rename_tools
from dragshift.rename_rules import Rule


def wait(app,predicate):
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        app.processEvents()
        if predicate():return
        time.sleep(.005)
    assert predicate()


def close(app,window):
    window.close()
    from dragshift.util import ALIVE
    wait(app,lambda:not ALIVE)


def ready(qt_session,tmp_path,monkeypatch):
    paths=[tmp_path/'one.txt',tmp_path/'two.txt']
    for path in paths:path.write_text(path.stem)
    calls=[]
    window=rename_tools.BulkRenameWindow(paths,lambda *args:calls.append(args),journal_dir=tmp_path/'profile/rename-journals')
    window.show()
    wait(qt_session,lambda:window.plan is not None and not window.preview_busy)
    return window,paths,calls


def test_bulk_editor_previews_applies_and_undoes_without_conversion_delete_undo(qt_session,tmp_path,monkeypatch):
    window,paths,calls=ready(qt_session,tmp_path,monkeypatch)
    window.set_rules([Rule('insert',{'text':'new_'})])
    wait(qt_session,lambda:not window.preview_busy and window.apply_button.isEnabled())
    assert all(path.exists() for path in paths)
    window.apply_button.click()
    wait(qt_session,lambda:not window.busy and window.last_journal is not None)
    assert all((tmp_path/('new_'+path.name)).read_text()==path.stem for path in paths)
    assert not calls and not window.apply_button.isEnabled()
    assert window.model.completed
    window.undo_button.click()
    wait(qt_session,lambda:not window.busy and all(path.exists() for path in paths))
    assert not window.undo_button.isEnabled() and not calls
    close(qt_session,window)


def test_rule_keyboard_manual_names_collision_and_selection(qt_session,tmp_path,monkeypatch):
    window,paths,_=ready(qt_session,tmp_path,monkeypatch)
    window.kind.setCurrentIndex(window.kind.findData('insert'));window.add_rule()
    text=window.fields['text'];text.setFocus();QTest.keyClicks(text,'shared_')
    wait(qt_session,lambda:window.plan is not None and not window.preview_busy and all(entry.target.name.startswith('shared_') for entry in window.plan.entries))
    window.model.setData(window.model.index(0,2),'two.txt',Qt.EditRole)
    window.model.setData(window.model.index(1,0),Qt.Unchecked.value,Qt.CheckStateRole)
    wait(qt_session,lambda:not window.preview_busy and len(window.plan.entries)==1)
    assert window.plan.errors and not window.apply_button.isEnabled()
    assert all(path.exists() for path in paths)
    link=tmp_path/'selected.lnk';link.write_bytes(b'own test shortcut bytes')
    mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(link))])
    assert window.drop.accepted(mime)==[link]
    close(qt_session,window)


def test_table_uses_virtual_rows_for_large_selections(qt_session,tmp_path):
    model=rename_tools.RenameTable()
    rows=[bulk_rename.Entry(tmp_path/f'{index}.txt',tmp_path/f'x{index}.txt',()) for index in range(50_000)]
    model.set_rows(rows,set())
    assert model.rowCount()==50_000
    assert model.data(model.index(49_999,2))=='x49999.txt'


def test_default_editor_uses_a_real_product_data_directory(qt_session,tmp_path):
    source=tmp_path/'selected.txt';source.write_text('selected file')
    window=rename_tools.BulkRenameWindow([source],lambda *_:None)
    assert window.journal_dir.is_absolute() and window.journal_dir.name=='rename-journals'
    window.show();wait(qt_session,lambda:window.plan is not None and not window.preview_busy)
    close(qt_session,window)


def test_history_is_reviewed_then_undone_in_a_new_window(qt_session,tmp_path,monkeypatch):
    window,paths,_=ready(qt_session,tmp_path,monkeypatch)
    window.set_rules([Rule('insert',{'text':'new_'})])
    wait(qt_session,lambda:not window.preview_busy and window.apply_button.isEnabled())
    window.apply_button.click()
    wait(qt_session,lambda:not window.busy and window.last_journal is not None)
    close(qt_session,window)
    window=rename_tools.BulkRenameWindow([tmp_path/('new_'+p.name) for p in paths],lambda *_:None,journal_dir=tmp_path/'profile/rename-journals')
    window.show();wait(qt_session,lambda:window.history.count()>1 and not window.preview_busy)
    window.history.setCurrentIndex(1)
    wait(qt_session,lambda:window.review_journal is not None and window.apply_button.isEnabled())
    assert [entry.target for entry in window.model.rows]==paths
    window.apply_button.click()
    wait(qt_session,lambda:not window.busy and all(p.exists() for p in paths))
    assert all(p.read_text()==p.stem for p in paths)
    close(qt_session,window)


def test_closing_during_rename_cancels_and_restores_names(qt_session,tmp_path,monkeypatch):
    import threading
    window,paths,_=ready(qt_session,tmp_path,monkeypatch)
    window.set_rules([Rule('insert',{'text':'new_'})])
    wait(qt_session,lambda:not window.preview_busy and window.apply_button.isEnabled())
    moved=threading.Event();release=threading.Event();native=bulk_rename.move_exclusive
    def delay(source,target):
        native(source,target)
        if not moved.is_set():
            moved.set();release.wait(10)
    monkeypatch.setattr(bulk_rename,'move_exclusive',delay)
    window.apply_button.click()
    try:
        wait(qt_session,moved.is_set)
        window.close();qt_session.processEvents()
        assert window.isVisible() and window.cancel.is_set()
    finally:release.set()
    wait(qt_session,lambda:not window.busy)
    assert all(p.exists() and p.read_text()==p.stem for p in paths)
    assert not list(tmp_path.glob('.~rename-*'))
    close(qt_session,window)
