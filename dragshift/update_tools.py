"""Quiet release notifications and a single cancellable native update window."""
import sys
import threading
import time

from PySide6.QtCore import QObject,QRunnable,QStandardPaths,QThreadPool,QTimer,Qt,Signal,Slot,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout,QLabel,QProgressBar,QPushButton,QTextBrowser

from . import __version__,update_install,updates
from .i18n import language,tr
from .util import keep,release
from .video_tools import _Lookup
from .window import GlassWindow

INTERVAL=6*60*60
REMINDER=24*60*60


class _Notes(QTextBrowser):
    def loadResource(self,kind,url):
        return None  # Release text cannot fetch remote images or local files.


class _Signals(QObject):
    progress=Signal(int,int)
    done=Signal(object)
    failed=Signal(str)
    finished=Signal(object)


class _Download(QRunnable):
    def __init__(self,release_info,cancel,downloader,preparer,ui_language):
        super().__init__()
        self.info,self.cancel,self.downloader,self.preparer,self.ui_language=release_info,cancel,downloader,preparer,ui_language
        self.sig=_Signals()

    def run(self):
        try:
            folder=QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)+'/updates'
            path=self.downloader(self.info,folder,cancel=self.cancel,progress=self.sig.progress.emit)
            if self.cancel.is_set():raise updates.Cancelled()
            handoff=self.preparer(path,self.info,self.ui_language)
            if self.cancel.is_set():raise updates.Cancelled()
            self.sig.done.emit(handoff)
        except updates.Cancelled:self.sig.failed.emit('Update download cancelled.')
        except Exception as error:self.sig.failed.emit(str(error))
        finally:self.sig.finished.emit(self)


class UpdateWindow(GlassWindow):
    retry=Signal()
    deferred=Signal(str)
    skipped=Signal(str)
    closed=Signal()

    def __init__(self,current,is_busy,quit_app,*,downloader=None,preparer=None,launcher=None):
        super().__init__('DragShift updates',size=(720,590))
        self.current,self.is_busy,self.quit_app=current,is_busy,quit_app
        self.downloader,self.preparer,self.launcher=downloader or updates.download,preparer or update_install.prepare,launcher or update_install.launch
        self.info=None
        self.working=False
        self.checking=False
        self._alive=True
        self._dismissed=False
        self.cancel=threading.Event()
        self.status=QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        self.body.addWidget(self.status)
        self.details=QLabel(tr(f'Installed version: {current}'))
        self.details.setTextFormat(Qt.PlainText)
        self.body.addWidget(self.details)
        self.notes=_Notes()
        self.notes.setOpenLinks(False)
        self.notes.setOpenExternalLinks(False)
        self.notes.setAccessibleName(tr('What changed'))
        self.notes.anchorClicked.connect(self._link)
        self.body.addWidget(self.notes,1)
        self.progress=QProgressBar()
        self.progress.setAccessibleName(tr('Update download progress'))
        self.body.addWidget(self.progress)
        self.notice=QLabel()
        self.notice.setWordWrap(True)
        self.body.addWidget(self.notice)
        self.busy_notice=QLabel(tr('Close tool windows and wait for file processing to finish before updating.'))
        self.busy_notice.setWordWrap(True)
        self.body.addWidget(self.busy_notice)
        row=QHBoxLayout()
        self.view_release=QPushButton(tr('View on GitHub'))
        self.view_release.clicked.connect(lambda:QDesktopServices.openUrl(QUrl(self.info.url if self.info else updates.REPOSITORY+'/releases/latest')))
        row.addWidget(self.view_release)
        row.addStretch()
        self.skip=QPushButton(tr('Skip this version'))
        self.skip.clicked.connect(self._skip)
        row.addWidget(self.skip)
        self.later=QPushButton(tr('Later'))
        self.later.clicked.connect(self.close)
        row.addWidget(self.later)
        self.primary=QPushButton(tr('Check again'))
        self.primary.setObjectName('primary')
        self.primary.clicked.connect(self._primary)
        row.addWidget(self.primary)
        self.body.addLayout(row)
        self.refresh_timer=QTimer(self,interval=500,timeout=self.refresh_busy)
        self.refresh_timer.start()
        self.set_checking()

    def _link(self,url):
        if url.scheme()=='https' and url.host()=='github.com':QDesktopServices.openUrl(url)

    def set_checking(self):
        self.checking=True
        self.status.setText(tr('Checking for updates…'))
        self.progress.setRange(0,0)
        self.progress.show()
        self.skip.setEnabled(False)
        self.primary.setEnabled(False)
        self.busy_notice.hide()

    def show_result(self,info):
        self.checking=False
        self.info=info
        self.progress.hide()
        if info is None:
            self.status.setText(tr('You have the latest version.'))
            self.notes.setPlainText(tr('New complete releases from your DragShift fork will appear here.'))
            self.notice.clear()
            self.primary.setText(tr('Check again'))
        else:
            self.status.setText(tr(f'Update available: {info.version}'))
            self.details.setText(tr(f'{self.current} → {info.version} · {info.asset.size/1024**2:.1f} MB'))
            self.notes.setMarkdown(info.notes)
            if sys.platform=='win32' and update_install.installed_windows():
                notice='The update installs and restarts DragShift. Your settings and files are kept.'
                action='Update and restart'
            elif sys.platform=='win32' and info.asset.name=='DragShift.exe':
                notice='The new portable file will be shown in its folder. DragShift will close so you can replace the old EXE.'
                action='Download portable update'
            else:
                notice='The verified package opens in the system installer. Finish installation there, then start DragShift again.'
                action='Download update'
            notice=tr(notice)
            if not info.history_complete:notice+=' '+tr('Full release history is available on GitHub.')
            self.notice.setText(notice)
            self.primary.setText(tr(action))
        self.skip.setEnabled(info is not None)
        self.refresh_busy()

    @Slot(str)
    def show_error(self,message):
        if not self._alive:return
        self.checking=self.working=False
        self.progress.hide()
        self.status.setText(tr(message))
        self.later.setText(tr('Later'))
        self.primary.setText(tr('Try again'))
        self.skip.setEnabled(self.info is not None)
        self.refresh_busy()

    def refresh_busy(self):
        if not self._alive:return
        busy=bool(self.info and self.is_busy())
        self.busy_notice.setVisible(busy)
        self.primary.setEnabled(not (self.working or self.checking or busy))

    def _primary(self):
        if self.working or self.checking:return
        if self.info is None:
            self.retry.emit()
            return
        if self.is_busy():
            self.refresh_busy()
            return
        self.working=True
        self.cancel.clear()
        self.primary.setEnabled(False)
        self.skip.setEnabled(False)
        self.status.setText(tr('Downloading and verifying the update…'))
        self.later.setText(tr('Cancel download'))
        self.progress.setRange(0,1000)
        self.progress.setValue(0)
        self.progress.show()
        job=_Download(self.info,self.cancel,self.downloader,self.preparer,language())
        job.sig.progress.connect(self._progress)
        job.sig.done.connect(self._downloaded)
        job.sig.failed.connect(self.show_error)
        job.sig.finished.connect(release)
        QThreadPool.globalInstance().start(keep(job))

    @Slot(int,int)
    def _progress(self,done,total):
        if self._alive:
            self.progress.setValue(round(1000*done/max(1,total)))
            self.progress.setFormat(tr(f'{done/1024**2:.1f} / {total/1024**2:.1f} MB'))

    @Slot(object)
    def _downloaded(self,handoff):
        if not self._alive or self.cancel.is_set():return
        self.working=False
        self.later.setText(tr('Later'))
        self.skip.setEnabled(True)
        if self.is_busy():
            self.status.setText(tr('Update downloaded. Close the tools, then click Update again.'))
            self.progress.hide()
            self.refresh_busy()
            return
        try:should_quit=self.launcher(handoff)
        except Exception as error:
            self.show_error(str(error))
            return
        self._dismissed=True
        self.close()
        if should_quit:self.quit_app()

    def _skip(self):
        if self.info:
            self._dismissed=True
            self.skipped.emit(self.info.version)
            self.close()

    def closeEvent(self,event):
        self._alive=False
        self.cancel.set()
        self.refresh_timer.stop()
        if self.info and not self._dismissed:self.deferred.emit(self.info.version)
        self.closed.emit()
        super().closeEvent(event)


class UpdateController(QObject):
    def __init__(self,settings,is_busy,show_window,quit_app,parent=None,*,current=__version__,fetcher=None,notifier=None,clock=time.time,window_factory=UpdateWindow):
        super().__init__(parent)
        self.settings,self.is_busy,self.show_window,self.quit_app=settings,is_busy,show_window,quit_app
        self.current,self.clock,self.window_factory=current,clock,window_factory
        self.fetcher=fetcher or (lambda current:updates.fetch_update(current,portable=update_install.portable_windows()))
        self.notifier=notifier
        self.window=None
        self.pending=None
        self.checking=False
        self._stopped=False
        self._serial=0
        self.startup_timer=QTimer(self,singleShot=True,timeout=self.tick)
        self.timer=QTimer(self,interval=30000,timeout=self.tick)

    def start(self):
        self._stopped=False
        self.startup_timer.start(30000)
        self.timer.start()

    def stop(self):
        self._stopped=True
        self.startup_timer.stop()
        self.timer.stop()
        if self.window:self.window.close()

    def open(self):
        if self.window:
            self.window.present()
            return
        self.window=self.window_factory(self.current,self.is_busy,self.quit_app)
        self.window.retry.connect(self.check_manual)
        self.window.deferred.connect(lambda _:self.settings.set('update_snooze_until',int(self.clock())+REMINDER))
        self.window.skipped.connect(self.skip)
        self.window.closed.connect(self._closed)
        self.show_window(self.window)
        self.check_manual()

    def _closed(self):self.window=None

    def skip(self,version):
        self.settings.set('update_skipped',version)
        self.pending=None

    def check_manual(self):
        if self.window:self.window.set_checking()
        self.check(manual=True)

    def tick(self):
        if not self.settings.get('check_updates'):return
        self._offer()
        if int(self.clock())-self.settings.get('update_last_check')>=INTERVAL:self.check()

    def _offer(self):
        if not self.settings.get('check_updates') or self._stopped or not self.pending or self.window or self.is_busy():return
        if self.settings.get('update_skipped')==self.pending.version or self.settings.get('update_snooze_until')>int(self.clock()):return
        if self.notifier:
            self.notifier(self.pending)
            self.settings.set('update_snooze_until',int(self.clock())+REMINDER)
        else:
            self.open()

    def check(self,manual=False):
        if self._stopped or self.window and self.window.working:return
        if self.checking:
            self._manual=self._manual or manual
            return
        self.checking=True
        self._manual=manual
        self.settings.set('update_last_check',int(self.clock()))
        self._serial+=1
        job=_Lookup(self._serial,lambda:self.fetcher(self.current))
        job.sig.done.connect(self._checked)
        job.sig.failed.connect(self._failed)
        job.sig.finished.connect(release)
        QThreadPool.globalInstance().start(keep(job))

    @Slot(int,object)
    def _checked(self,serial,info):
        self.checking=False
        if self._stopped:return
        if self.window:
            self.window.show_result(info)
        elif not self._manual:
            self.pending=info
            self._offer()

    @Slot(int,str)
    def _failed(self,serial,message):
        self.checking=False
        if self._stopped:return
        if self.window:self.window.show_error(message)
