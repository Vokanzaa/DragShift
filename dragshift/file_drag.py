"""Validate native file drags before exposing any radial tools.

Global button/modifier state also describes drawing and text selection. A tiny
nonactivating drop receiver obtains the real drag payload without displaying a
menu, reading the clipboard, or borrowing another window's selected files.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget


def _mac_backend():
    from . import platform_mac
    return platform_mac


def existing_paths(paths):
    return [str(p) for p in paths if p and Path(p).exists()]


class FileDragGate(QWidget):
    ready = Signal(QPoint, list)

    def __init__(self, input_state, parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                         Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAcceptDrops(True)
        self.resize(16, 16)
        self.input_state = input_state
        self.enabled = lambda: True
        self._armed = False
        self._queued = False
        self._serial = 0
        self._deadline = 0.
        self._generation = None
        self._backdrop = None
        self._pos = QPoint()
        self.timer = QTimer(self, interval=15, timeout=self._follow)

    def begin_gesture(self):
        self.cancel()
        self._generation = _mac_backend().drag_generation() if sys.platform == 'darwin' else None

    def _active(self):
        left, _, escape = self.input_state()
        return self.enabled() and left and not escape

    def request(self, pos):
        self.cancel()
        if not self._active():
            return
        self._pos = QPoint(pos)
        # The drag pasteboard persists after release. Only a change during this
        # mouse gesture may use the stationary Finder handoff.
        if sys.platform == 'darwin' and self._generation is not None:
            mac = _mac_backend()
            generation = mac.drag_generation()
            if generation is not None and generation != self._generation:
                paths = existing_paths(mac.drag_files())
                if paths:
                    print(f'menu: {len(paths)} file(s) from the drag pasteboard', flush=True)
                    self.ready.emit(QPoint(pos), paths)
                    return
        self._armed = True
        self._deadline = time.monotonic() + .9
        self._place(pos)
        self.show()
        self.raise_()
        self.timer.start()

    def cancel(self):
        self._serial += 1
        self._armed = self._queued = False
        self.timer.stop()
        self.hide()

    def _place(self, pos):
        self._pos = QPoint(pos)
        top_left = pos - QPoint(8, 8)
        # Without X11 compositing, alpha is unavailable. Repaint the exact tiny
        # background tile instead of displaying a black or coloured rectangle.
        if sys.platform.startswith('linux'):
            from . import glass
            if glass.no_compositor():
                screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
                if screen is not None:
                    self._backdrop = screen.grabWindow(0, top_left.x(), top_left.y(), 16, 16)
        self.move(top_left)

    def _valid(self):
        return self._armed and self._active() and time.monotonic() < self._deadline

    def _follow(self):
        if not self._valid():
            self.cancel()
        elif not self._queued:
            pos = QCursor.pos()
            if pos != self._pos:
                self._place(pos)

    def paintEvent(self, event):
        painter = QPainter(self)
        if self._backdrop is not None and not self._backdrop.isNull():
            painter.drawPixmap(0, 0, self._backdrop)
        else:
            # Alpha must be nonzero for native drag hit testing. No visible UI
            # is painted until a local file payload is received.
            painter.fillRect(self.rect(), QColor(0, 0, 0, 1))

    def dragEnterEvent(self, event):
        if not self._valid() or self._queued:
            event.ignore()
            if not self._queued:
                self.cancel()
            return
        mime = event.mimeData()
        paths = existing_paths([url.toLocalFile() for url in mime.urls() if url.isLocalFile()]) if mime.hasUrls() else []
        if not paths:
            event.ignore()
            self.cancel()
            return
        event.setDropAction(Qt.CopyAction)
        event.accept()
        self._queued = True
        # Return to the source's native drag loop before replacing its target.
        serial = self._serial
        QTimer.singleShot(0, lambda: self._handoff(serial, paths))

    def _handoff(self, serial, paths):
        if serial != self._serial:
            return
        valid = self._queued and self._valid()
        pos = QPoint(self._pos)
        self.cancel()
        if valid:
            self.ready.emit(pos, paths)

    def closeEvent(self, event):
        self.cancel()
        super().closeEvent(event)
