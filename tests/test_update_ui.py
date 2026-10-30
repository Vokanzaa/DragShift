import threading,time

from PySide6.QtCore import QCoreApplication,QEvent

from dragshift import i18n,update_install,updates
from dragshift.settings import DEFAULTS,SettingsWindow
from dragshift.update_tools import UpdateController,UpdateWindow,INTERVAL,REMINDER
from test_updates import release_data


class MemorySettings:
    def __init__(self,**values):self.values=dict(DEFAULTS,**values)
    def get(self,key):return self.values[key]
    def set(self,key,value):self.values[key]=value


def wait(app,predicate):
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        app.processEvents()
        if predicate():return
        time.sleep(.005)
    assert predicate()


def info():return updates.parse_release(release_data(),'1.1.0+files.13',system='win32')


def controller(app,**kwargs):
    shown=[]
    c=UpdateController(kwargs.pop('settings',MemorySettings()),kwargs.pop('is_busy',lambda:False),
                       lambda w:(shown.append(w),w.show()),lambda:None,current='1.1.0+files.13',
                       clock=kwargs.pop('clock',lambda:100000),**kwargs)
    return c,shown


def test_background_current_offline_disabled_and_interval_are_quiet(qt_session):
    for outcome in (None,OSError('offline')):
        calls=[]
        def fetch(_):
            calls.append(1)
            if isinstance(outcome,Exception):raise outcome
            return outcome
        c,shown=controller(qt_session,fetcher=fetch)
        c.tick()
        wait(qt_session,lambda:not c.checking)
        c.tick()
        assert calls==[1] and not shown
        c.stop()
    c,shown=controller(qt_session,settings=MemorySettings(check_updates=False),fetcher=lambda _:info())
    c.tick()
    assert not c.checking and not shown
    c.open()
    wait(qt_session,lambda:not c.checking)
    assert len(shown)==1 and shown[0].info.version==info().version
    c.stop()


def test_background_notification_waits_for_idle_and_does_not_open_a_window(qt_session):
    busy=[True]
    now=[100000]
    messages=[]
    c,shown=controller(qt_session,is_busy=lambda:busy[0],clock=lambda:now[0],fetcher=lambda _:info(),notifier=messages.append)
    c.tick()
    wait(qt_session,lambda:not c.checking)
    assert not messages and not shown
    busy[0]=False
    c.tick()
    assert len(messages)==1 and not shown
    c.tick()
    assert len(messages)==1
    assert c.settings.get('update_snooze_until')==now[0]+REMINDER
    c.stop()


def test_skip_and_later_persist_but_manual_checks_can_find_skipped_release(qt_session):
    c,shown=controller(qt_session,fetcher=lambda _:info())
    c.open()
    wait(qt_session,lambda:not c.checking)
    shown[-1].skip.click()
    assert c.settings.get('update_skipped')==info().version and c.window is None
    c.open()
    wait(qt_session,lambda:not c.checking)
    assert shown[-1].info.version==info().version
    shown[-1].later.click()
    assert c.settings.get('update_snooze_until')==100000+REMINDER
    c.stop()


def test_close_reopen_and_repeated_check_do_not_duplicate_requests(qt_session):
    gate=threading.Event()
    calls=[]
    def fetch(_):
        calls.append(1)
        gate.wait(5)
        return info()
    c,shown=controller(qt_session,fetcher=fetch)
    try:
        c.open()
        c.open()
        assert len(shown)==1
        shown[-1].close()
        c.open()
        assert len(shown)==2
        gate.set()
        wait(qt_session,lambda:not c.checking)
        assert len(calls)==1 and c.window.info.version==info().version
    finally:
        gate.set()
        c.stop()


def test_closing_manual_check_does_not_reopen_window_after_network_reply(qt_session):
    gate=threading.Event()
    c,shown=controller(qt_session,fetcher=lambda _:(gate.wait(5),info())[1])
    c.open()
    c.window.close()
    gate.set()
    wait(qt_session,lambda:not c.checking)
    assert c.window is None and len(shown)==1 and c.pending is None
    c.stop()


def test_manual_open_then_close_during_background_check_suppresses_notification(qt_session):
    gate=threading.Event()
    messages=[]
    c,shown=controller(qt_session,fetcher=lambda _:(gate.wait(5),info())[1],notifier=messages.append)
    c.tick()
    c.open()
    c.window.close()
    gate.set()
    wait(qt_session,lambda:not c.checking)
    assert not messages and c.pending is None
    c.stop()


def test_disabling_or_stopping_during_background_request_never_notifies(qt_session):
    for mode in ('disable','stop'):
        gate=threading.Event()
        messages=[]
        c,shown=controller(qt_session,fetcher=lambda _:(gate.wait(5),info())[1],notifier=messages.append)
        c.tick()
        if mode=='disable':c.settings.set('check_updates',False)
        else:c.stop()
        gate.set()
        wait(qt_session,lambda:not c.checking)
        assert not messages and not shown
        c.stop()


def test_busy_tools_block_install_even_if_they_open_during_download(qt_session):
    busy=[True]
    calls=[]
    downloads=[]
    def download(*a,**kw):
        downloads.append(1)
        if len(downloads)==1:busy[0]=True
        return 'verified'
    w=UpdateWindow('1.1.0+files.13',lambda:busy[0],lambda:calls.append('quit'),
        downloader=download,preparer=lambda *a:'handoff',launcher=lambda h:(calls.append(h),True)[1])
    w.show_result(info())
    w.show()
    assert not w.primary.isEnabled()
    w._primary()
    assert not downloads
    busy[0]=False
    w.refresh_busy()
    w._primary()
    wait(qt_session,lambda:not w.working)
    assert not calls and len(downloads)==1 and w._alive
    assert w.later.text()==i18n.tr('Later') and w.skip.isEnabled()
    busy[0]=False
    w.refresh_busy()
    w._primary()
    wait(qt_session,lambda:'quit' in calls)
    assert calls==['handoff','quit']


def test_close_cancels_download_and_never_launches_installer(qt_session):
    gate=threading.Event()
    stopped=threading.Event()
    calls=[]
    def download(*a,cancel,**kw):
        gate.set()
        assert cancel.wait(5)
        stopped.set()
        raise updates.Cancelled()
    w=UpdateWindow('1.1.0',lambda:False,lambda:calls.append('quit'),downloader=download,
                   preparer=lambda *a:calls.append('prepare'),launcher=lambda *a:calls.append('launch'))
    w.show_result(info())
    w._primary()
    wait(qt_session,gate.is_set)
    w.close()
    wait(qt_session,stopped.is_set)
    assert not calls


def test_installer_error_keeps_application_open_and_allows_retry(qt_session):
    calls=[]
    def fail(_):raise updates.UpdateError('Could not open the installer. Open the release page or try again.')
    w=UpdateWindow('1.1.0',lambda:False,lambda:calls.append('quit'),downloader=lambda *a,**k:'verified',
                   preparer=lambda *a:'handoff',launcher=fail)
    w.show_result(info())
    w._primary()
    wait(qt_session,lambda:not w.working)
    assert w._alive and not calls and 'Could not open' in w.status.text() and w.primary.isEnabled()
    w.close()


def test_russian_update_controls_settings_and_notes_are_visible(qt_session):
    previous=i18n.language()
    try:
        i18n.set_language('ru')
        w=UpdateWindow('1.1.0+files.13',lambda:False,lambda:None)
        w.show_result(info())
        w.show()
        qt_session.processEvents()
        assert w.title_label.text()=='Обновления DragShift'
        assert w.later.text()=='Позже' and w.skip.text()=='Пропустить версию'
        assert w.primary.text() in ('Загрузить обновление','Обновить и перезапустить')
        assert not w.grab().isNull() and 'Changes in 14' in w.notes.toPlainText()
        assert not w.notes.openExternalLinks() and w.notes.loadResource(2,None) is None
        s=MemorySettings()
        settings=SettingsWindow(s)
        clicks=[]
        settings.check_updates_requested.connect(lambda:clicks.append(1))
        settings.check_updates_button.click()
        settings.updates.setChecked(False)
        assert clicks==[1] and not s.get('check_updates')
        settings.close()
        w.close()
    finally:i18n.set_language(previous)


def test_bundled_update_smokecheck_is_offline_and_noninstalling(qt_session,tmp_path):
    from dragshift.file_check import _check_updates
    _check_updates(tmp_path)
