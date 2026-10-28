"""Direct video keyframes with absolute Liquid Rescale strength values."""

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from .i18n import tr
from .media_controls import StrengthCurve
from .theme import BORDER, HOVER, MUTED, PANEL, TEXT


MAX_STRENGTH = 95.


def _finite(value, fallback=0.):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    return number if math.isfinite(number) else fallback


class _DistortionTimeline(StrengthCurve):
    """Share the point interaction model; present strength in its actual units."""

    playheadMoved = Signal(float)

    def __init__(self, parent=None):
        super().__init__()
        self.setParent(parent)
        self.duration = 1.
        self.playhead = 0.
        self.scrubbing = False
        self.setMinimumHeight(190)
        self.setAccessibleName(tr('Distortion keyframe timeline'))
        self.setToolTip(tr('Click the graph to add a keyframe. Drag to change time and strength. '
                           'Drag the top ruler to seek. Arrow keys adjust the selected keyframe; '
                           'Delete removes it.'))

    def area(self):
        return QRectF(38, 28, max(1, self.width()-56), max(1, self.height()-55))

    def _gap(self):
        return min(.001, .001/self.duration)

    def set_point(self, x, y):
        i = self.index
        gap = (min(self._gap(), (self.points[i+1][0]-self.points[i-1][0])/3)
               if 0 < i < len(self.points)-1 else self._gap())
        x = (0. if i == 0 else 1. if i == len(self.points)-1 else
             max(self.points[i-1][0]+gap, min(x, self.points[i+1][0]-gap)))
        point = (x, max(0., min(1., y)))
        if point != self.points[i]:
            self.points[i] = point
            self.update()
            self.changed.emit(list(self.points))

    def insert(self, pos):
        self.setFocus()
        if len(self.points) >= 64 or not self.area().contains(pos):
            return
        r = self.area()
        gap = self._gap()
        x = max(gap, min(1.-gap, (pos.x()-r.left())/r.width()))
        if any(abs(x-p[0]) < gap for p in self.points):
            return
        point = (x, max(0., min(1., (r.bottom()-pos.y())/r.height())))
        self.points.append(point)
        self.points.sort()
        self.index = self.points.index(point)
        self.selected.emit(self.index)
        self.changed.emit(list(self.points))
        self.update()

    def _seek(self, pos):
        r = self.area()
        seconds = max(0., min(self.duration, (pos.x()-r.left())/r.width()*self.duration))
        self.playheadMoved.emit(seconds)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and event.position().y() < self.area().top():
            self.setFocus()
            self.scrubbing = True
            self._seek(event.position())
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.scrubbing:
            self._seek(event.position())
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.scrubbing = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        # Qt sends a press before a double click. Selecting the newly inserted
        # point must not create a second point or move the nearest old point.
        if event.position().y() >= self.area().top():
            super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            x, y = self.points[self.index]
            scale = 10 if event.modifiers() & Qt.ShiftModifier else 1
            dx = .01*scale/self.duration
            dy = scale/MAX_STRENGTH
            self.set_point(x + (dx if event.key() == Qt.Key_Right else -dx if event.key() == Qt.Key_Left else 0),
                           y + (dy if event.key() == Qt.Key_Up else -dy if event.key() == Qt.Key_Down else 0))
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.area()
        p.setPen(QPen(QColor(BORDER), 1))
        p.setBrush(QColor(PANEL))
        p.drawRoundedRect(r, 3, 3)
        for strength in (0, 40, 95):
            y = r.bottom()-strength/MAX_STRENGTH*r.height()
            p.setPen(QPen(QColor(BORDER), 1))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(0, y-9, 30, 18), Qt.AlignRight | Qt.AlignVCenter, str(strength))
        # A separate ruler is a pointer-only seek target, so graph clicks keep
        # their simple add/select meaning even directly beneath the playhead.
        p.fillRect(QRectF(r.left(), 3, r.width(), r.top()-7), QColor(HOVER))
        for fraction in (0., .25, .5, .75, 1.):
            x = r.left()+fraction*r.width()
            p.setPen(QPen(QColor(BORDER), 1, Qt.DotLine))
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            p.setPen(QColor(MUTED))
            p.drawLine(QPointF(x, r.top()-7), QPointF(x, r.top()-3))
            # Only draw quarter labels when the timeline has room for them.
            if fraction in (0., .5, 1.) or r.width() >= 440:
                left = x if fraction == 0 else x-74 if fraction == 1 else x-37
                align = Qt.AlignLeft if fraction == 0 else Qt.AlignRight if fraction == 1 else Qt.AlignCenter
                p.drawText(QRectF(left, r.bottom()+5, 74, 20), align, tr(f'{fraction*self.duration:.2f} s'))
        path = QPainterPath(self.position(self.points[0]))
        for point in self.points[1:]:
            path.lineTo(self.position(point))
        p.setPen(QPen(QColor(TEXT), 2))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        playhead_x = r.left()+self.playhead/self.duration*r.width()
        p.setPen(QPen(QColor(MUTED), 1, Qt.DashLine))
        p.drawLine(QPointF(playhead_x, r.top()-5), QPointF(playhead_x, r.bottom()))
        p.setPen(QPen(QColor(TEXT), 1))
        p.setBrush(QColor(TEXT))
        p.drawPolygon(QPolygonF([QPointF(playhead_x-5, 5), QPointF(playhead_x+5, 5),
                                QPointF(playhead_x+5, 13), QPointF(playhead_x, 18),
                                QPointF(playhead_x-5, 13)]))
        for i, point in enumerate(self.points):
            p.setPen(QPen(QColor(TEXT), 2 if i == self.index else 1))
            p.setBrush(QColor(TEXT if i == self.index else 'white'))
            p.drawEllipse(self.position(point), 5, 5)
            if i == self.index and self.hasFocus():
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(self.position(point), 9, 9)


class DistortionCurve(QWidget):
    """Store the curve used by both preview and export; randomize only on demand.

    Public points are JSON-safe ``[normalized_time, absolute_strength]`` pairs.
    The inherited canvas uses normalized coordinates only as a drawing detail.
    """

    changed = Signal(object)
    selectedStrengthChanged = Signal(float)
    playheadMoved = Signal(float)

    def __init__(self, duration=1., strength=40., parent=None):
        super().__init__(parent)
        self.duration = 1.
        self._default_strength = max(0., min(MAX_STRENGTH, _finite(strength, 40.)))
        self._rng = random.Random()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        heading = QHBoxLayout()
        title = QLabel(tr('Distortion over time'))
        title.setObjectName('section')
        heading.addWidget(title)
        heading.addStretch()
        self.playhead_label = QLabel()
        self.playhead_label.setObjectName('dim')
        heading.addWidget(self.playhead_label)
        layout.addLayout(heading)
        self.curve = _DistortionTimeline(self)
        self.curve.points = [(0., self._default_strength/MAX_STRENGTH),
                             (1., self._default_strength/MAX_STRENGTH)]
        layout.addWidget(self.curve)
        inspector = QHBoxLayout()
        self.selection_label = QLabel()
        inspector.addWidget(self.selection_label)
        inspector.addStretch()
        self.time, self.level = QDoubleSpinBox(), QDoubleSpinBox()
        for spin in (self.time, self.level):
            spin.setKeyboardTracking(False)
            spin.setMinimumWidth(92)
        self.time.setDecimals(2)
        self.time.setSingleStep(.01)
        self.time.setSuffix(tr(' s'))
        self.time.setAccessibleName(tr('Selected keyframe time in seconds'))
        self.level.setRange(0, MAX_STRENGTH)
        self.level.setDecimals(1)
        self.level.setSingleStep(1)
        self.level.setAccessibleName(tr('Selected keyframe distortion strength, 0 to 95'))
        for text, control in (('Time', self.time), ('Strength (0–95)', self.level)):
            label = QLabel(tr(text))
            label.setBuddy(control)
            inspector.addWidget(label)
            inspector.addWidget(control)
        layout.addLayout(inspector)
        actions = QHBoxLayout()
        self.previous = QPushButton(tr('Previous'))
        self.next = QPushButton(tr('Next'))
        self.add_keyframe = QPushButton(tr('Add keyframe'))
        self.remove_keyframe = QPushButton(tr('Remove'))
        self.reset_button = QPushButton(tr('Reset curve'))
        for button in (self.previous, self.next, self.add_keyframe, self.remove_keyframe, self.reset_button):
            button.setAutoDefault(False)
            actions.addWidget(button)
        self.previous.setAccessibleName(tr('Select previous keyframe'))
        self.next.setAccessibleName(tr('Select next keyframe'))
        self.add_keyframe.setToolTip(tr('Add a keyframe at the playhead, then edit its strength.'))
        layout.addLayout(actions)
        variation = QHBoxLayout()
        self.randomize = QCheckBox(tr('Randomize'))
        self.randomize.setToolTip(tr('Generate editable keyframes once. Unchecking keeps the current curve.'))
        self.variation = QPushButton(tr('Another variation'))
        self.variation.setAutoDefault(False)
        self.variation.setEnabled(False)
        variation.addWidget(self.randomize)
        variation.addWidget(self.variation)
        variation.addStretch()
        layout.addLayout(variation)
        hint = QLabel(tr('Click to add a keyframe; drag to change time and strength. '
                         '0 = original · 95 = strongest.'))
        hint.setObjectName('dim')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.curve.changed.connect(self._changed)
        self.curve.selected.connect(self.select)
        self.curve.playheadMoved.connect(self._seek)
        self.time.valueChanged.connect(self._typed_time)
        self.level.valueChanged.connect(self.set_strength)
        self.previous.clicked.connect(lambda: self.select(self.curve.index-1))
        self.next.clicked.connect(lambda: self.select(self.curve.index+1))
        self.add_keyframe.clicked.connect(self.add_at_playhead)
        self.remove_keyframe.clicked.connect(self.curve.remove)
        self.reset_button.clicked.connect(self.reset)
        self.randomize.toggled.connect(self._randomize_toggled)
        self.variation.clicked.connect(self.another_variation)
        self.set_duration(duration)
        self.set_playhead(0)
        self.sync()

    def points(self):
        return [[float(x), float(y*MAX_STRENGTH)] for x, y in self.curve.points]

    def set_points(self, points):
        values = {}
        for point in points or []:
            try:
                x, strength = map(float, point)
            except (TypeError, ValueError, OverflowError):
                continue
            if math.isfinite(x) and math.isfinite(strength):
                values[max(0., min(1., x))] = max(0., min(MAX_STRENGTH, strength))/MAX_STRENGTH
        if not values:
            values = {0.: self._default_strength/MAX_STRENGTH, 1.: self._default_strength/MAX_STRENGTH}
        ordered = sorted(values.items())
        if ordered[0][0] != 0.:
            ordered.insert(0, (0., ordered[0][1]))
        if ordered[-1][0] != 1.:
            ordered.append((1., ordered[-1][1]))
        self.curve.points = ordered[:63]+[ordered[-1]] if len(ordered) > 64 else ordered
        self.curve.index = min(self.curve.index, len(self.curve.points)-1)
        self.curve.update()
        self._changed()

    def set_duration(self, seconds):
        self.duration = max(.001, _finite(seconds, 1.))
        self.curve.duration = self.duration
        self.time.blockSignals(True)
        self.time.setRange(0, self.duration)
        self.time.blockSignals(False)
        self.set_playhead(self.curve.playhead)
        self.sync()
        self.curve.update()

    def set_playhead(self, seconds):
        self.curve.playhead = max(0., min(self.duration, _finite(seconds)))
        self.playhead_label.setText(tr(f'Playhead {self.curve.playhead:.2f} s'))
        self.curve.update()

    def _seek(self, seconds):
        previous = self.curve.playhead
        self.set_playhead(seconds)
        if self.curve.playhead != previous:
            self.playheadMoved.emit(self.curve.playhead)

    def selected_strength(self):
        return self.curve.points[self.curve.index][1]*MAX_STRENGTH

    def set_strength(self, strength):
        x, _ = self.curve.points[self.curve.index]
        self.curve.set_point(x, max(0., min(MAX_STRENGTH, _finite(strength)))/MAX_STRENGTH)

    def select(self, index):
        self.curve.index = max(0, min(len(self.curve.points)-1, index))
        self.sync()
        self._seek(self.curve.points[self.curve.index][0]*self.duration)
        self.curve.update()

    def sync(self, *_):
        x, y = self.curve.points[self.curve.index]
        for spin, value in ((self.time, x*self.duration), (self.level, y*MAX_STRENGTH)):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        interior = 0 < self.curve.index < len(self.curve.points)-1
        self.time.setEnabled(interior)
        self.remove_keyframe.setEnabled(interior)
        self.previous.setEnabled(self.curve.index > 0)
        self.next.setEnabled(self.curve.index < len(self.curve.points)-1)
        self.selection_label.setText(tr(f'Keyframe {self.curve.index+1} of {len(self.curve.points)}'))
        self.selectedStrengthChanged.emit(y*MAX_STRENGTH)

    def _typed_time(self, seconds):
        self.curve.set_point(seconds/self.duration, self.curve.points[self.curve.index][1])
        # Clamp the inspector back to a neighboring keyframe when times collide.
        self.sync()

    def _changed(self, *canvas_points):
        self.sync()
        if canvas_points:
            self._seek(self.curve.points[self.curve.index][0]*self.duration)
        self.changed.emit(self.points())

    def add_at_playhead(self):
        x = self.curve.playhead/self.duration
        for i, (time, _) in enumerate(self.curve.points):
            if abs(time-x) < self.curve._gap():
                self.select(i)
                return
        for (left, low), (right, high) in zip(self.curve.points, self.curve.points[1:]):
            if left < x < right:
                y = low+(high-low)*(x-left)/(right-left)
                self.curve.insert(self.curve.position((x, y)))
                return

    def reset(self):
        self.randomize.blockSignals(True)
        self.randomize.setChecked(False)
        self.randomize.blockSignals(False)
        self.variation.setEnabled(False)
        self.curve.index = 0
        self.set_points([[0., self._default_strength], [1., self._default_strength]])

    def _randomize_toggled(self, enabled):
        self.variation.setEnabled(enabled)
        if enabled:
            self.another_variation()

    def another_variation(self):
        # Randomness is materialized here, once per explicit action. Reading,
        # seeking, previewing and exporting never change these stored keyframes.
        intervals = [self._rng.uniform(.45, 1.7) for _ in range(self._rng.randint(7, 10))]
        total = sum(intervals)
        times, elapsed = [0.], 0.
        for interval in intervals[:-1]:
            elapsed += interval
            times.append(elapsed/total)
        times.append(1.)
        points = []
        for x in times:
            strength = self._rng.uniform(5., 92.)
            if points and abs(strength-points[-1][1]) < 12.:
                strength = (self._rng.uniform(5., 32.) if points[-1][1] > 48. else
                            self._rng.uniform(64., 92.))
            points.append([x, round(strength, 1)])
        self.curve.index = 0
        self.set_points(points)
