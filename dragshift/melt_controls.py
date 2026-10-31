"""Effect-phase controls and a private, genuinely rendered Melt preview."""
from pathlib import Path
import tempfile
import threading

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QVBoxLayout, QWidget)

from . import video
from .i18n import tr
from .media_controls import TrimRange
from .theme import MUTED, TEXT


class PhaseRange(TrimRange):
    phaseChanged=Signal(float,float)

    def __init__(self):
        super().__init__()
        self.left=self.right=1.
        self.setMinimumHeight(66)
        self.setAccessibleName(tr('Melt effect range · start of A breakdown and first clear B frame'))
        self.setToolTip(tr('Left handle: when A starts breaking. Right handle: when B is clear. The cut stays fixed. Arrow keys adjust the selected handle.'))
        self.changed.connect(lambda start,end:self.phaseChanged.emit(self.left-start,end-self.left))

    def set_phase(self,left,right,lead,recovery):
        self.left,self.right=max(.2,left),max(.2,right)
        self.set_values(self.left-lead,self.left+recovery,self.left+self.right)

    def _change(self,value):
        if self.active==0:
            self.start=max(.1,min(value,self.left))
        else:
            self.end=min(self.duration-.1,max(value,self.left+.1))
        self.update()
        self.changed.emit(self.start,self.end)

    def paintEvent(self,event):
        super().paintEvent(event)
        painter=QPainter(self)
        painter.setPen(QPen(QColor(MUTED),1,Qt.DashLine))
        x=self._x(self.left)
        painter.drawLine(QPointF(x,8),QPointF(x,self.height()-8))
        painter.setPen(QColor(TEXT))
        painter.drawText(14,13,'A')
        painter.drawText(self.width()-25,13,'B')
        painter.drawText(round(x)+5,13,tr('Cut'))


class MeltPhase(QWidget):
    changed=Signal()

    def __init__(self,recovery):
        super().__init__()
        from .video_tools import _seconds
        self._syncing=False
        self.left=self.right=1.
        self.source_end=self.source_start=0.
        layout=QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        self.strip=PhaseRange()
        layout.addWidget(self.strip)
        form=QFormLayout()
        self.lead=_seconds()
        self.lead.setRange(0,60)
        self.lead.setAccessibleName(tr('Start breaking A before the cut'))
        self.recovery=recovery
        self.recovery.setAccessibleName(tr('B becomes clear after the cut'))
        form.addRow(tr('Start breaking A before the cut'),self.lead)
        form.addRow(tr('B becomes clear after the cut'),self.recovery)
        layout.addLayout(form)
        self.smooth=QCheckBox(tr('Reverse Melt recovery · experimental'))
        self.smooth.setToolTip(tr('Combines forward and reverse motion-vector corruption. No clean-video dissolve. Compare the rendered preview with classic Melt.'))
        layout.addWidget(self.smooth)
        self.summary=QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.lead.valueChanged.connect(self._edited)
        self.recovery.valueChanged.connect(self._edited)
        self.smooth.toggled.connect(self._smooth_changed)
        self.strip.phaseChanged.connect(self._dragged)

    def set_times(self,left,right,lead,recovery,smooth=False,*,source_end=None,source_start=0.):
        self._syncing=True
        self.left,self.right=left,right
        self.source_end=left if source_end is None else source_end
        self.source_start=source_start
        self.lead.setValue(lead)
        self.recovery.setValue(recovery)
        self.smooth.setChecked(smooth)
        self._syncing=False
        self._update()

    def _update(self):
        self.strip.set_phase(self.left,self.right,self.lead.value(),self.recovery.value())
        self.summary.setText(tr('A begins to break at {0} · cut A {1} / B {2} · B is clear at {3}').format(
            video.time_text(max(0,self.source_end-self.lead.value())),video.time_text(self.source_end),
            video.time_text(self.source_start),video.time_text(self.source_start+self.recovery.value())))

    def _edited(self,*_):
        if self._syncing:return
        self._update()
        self.changed.emit()

    def _smooth_changed(self,enabled):
        if self._syncing:return
        if enabled and self.lead.value()<.1:
            self.lead.blockSignals(True)
            self.lead.setValue(min(1.,max(.1,self.left-.125)))
            self.lead.blockSignals(False)
        self._edited()

    def _dragged(self,lead,recovery):
        self._syncing=True
        self.lead.setValue(lead)
        self.recovery.setValue(recovery)
        self._syncing=False
        self._edited()


def preview_frames(model,*,fps,max_side=360,cancel=None):
    """Return bounded JPEGs of the actual renderer; temporary media is private."""
    from .melt_timeline import render
    duration=sum(model.validate(fps))/fps
    with tempfile.TemporaryDirectory(prefix='melt-preview-') as directory:
        folder=Path(directory)
        with video.job_context(video.Control(cancel=cancel if cancel is not None else threading.Event())):
            path=render(model,max_side=max_side,fps=fps,audio=False,directory=folder)[0]
            rate=min(fps,12,600/max(.01,duration))
            video.run_process(video.ffmpeg_args()+['-i',str(path),'-map','0:v:0','-an',
                '-vf',f'fps={rate:.10f}','-frames:v','600','-q:v','4',str(folder/'frame-%06d.jpg')],
                duration,'Reading rendered Melt preview…')
            frames=[(min(index/rate,duration-1/fps),frame.read_bytes())
                    for index,frame in enumerate(sorted(folder.glob('frame-*.jpg')))]
            last=max(0,duration-1/fps)
            if not frames or frames[-1][0]<last-.001:
                frames.append((last,video.preview_bytes(path,last,max_side=360)))
            return frames,rate


class MeltPreview(QWidget):
    """Explicit build, cancellation, scrub/play and unambiguous stale feedback."""
    def __init__(self,owner):
        super().__init__()
        self.owner=owner
        self.frames=[]
        self.rate=12
        self.revision=0
        self.busy=False
        self.cancel=threading.Event()
        layout=QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        self.status=QLabel(tr('Render the effect preview to judge breakdown and recovery.'))
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.image=QLabel()
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumHeight(110)
        self.image.setMaximumHeight(160)
        self.image.setAccessibleName(tr('Rendered Melt effect preview'))
        layout.addWidget(self.image)
        row=QHBoxLayout()
        self.play=QPushButton(tr('Play'))
        self.play.setEnabled(False)
        self.play.clicked.connect(self.toggle_play)
        row.addWidget(self.play)
        self.scrub=QSlider(Qt.Horizontal)
        self.scrub.setRange(0,0)
        self.scrub.setAccessibleName(tr('Rendered effect position'))
        self.scrub.setEnabled(False)
        self.scrub.valueChanged.connect(self.show_frame)
        row.addWidget(self.scrub,1)
        self.position=QLabel()
        row.addWidget(self.position)
        self.stop=QPushButton(tr('Cancel preview'))
        self.stop.clicked.connect(lambda:self.cancel.set())
        self.stop.hide()
        row.addWidget(self.stop)
        layout.addLayout(row)
        self.timer=QTimer(self,timeout=self.advance)
        self.hide()

    def invalidate(self,*_):
        self.revision+=1
        self.timer.stop()
        self.play.setText(tr('Play'))
        self.play.setEnabled(False)
        self.scrub.setEnabled(False)
        if self.busy:self.cancel.set()
        if self.frames or self.busy:
            self.status.setText(tr('Settings changed · render a new effect preview.'))

    def close_preview(self):
        self.cancel.set()
        self.timer.stop()

    def build(self,model,*,fps):
        if self.busy:
            self.cancel.set()
            return
        self.show()
        from PySide6.QtWidgets import QScrollArea
        ancestor=self.parentWidget()
        while ancestor is not None and not isinstance(ancestor,QScrollArea):ancestor=ancestor.parentWidget()
        if ancestor is not None:QTimer.singleShot(0,self,lambda:ancestor.ensureWidgetVisible(self))
        self.busy=True
        self.cancel=threading.Event()
        cancel=self.cancel
        revision=self.revision
        self.timer.stop()
        self.play.setEnabled(False)
        self.scrub.setEnabled(False)
        self.stop.show()
        self.status.setText(tr('Rendering the actual Melt effect…'))
        def finish(value=None,error=None):
            self.busy=False
            self.stop.hide()
            if revision!=self.revision:
                self.status.setText(tr('Settings changed · render a new effect preview.'))
                return
            if error:
                self.status.setText(tr('Preview cancelled.' if cancel.is_set() else error))
                return
            self.frames,self.rate=value
            self.scrub.setRange(0,max(0,len(self.frames)-1))
            self.scrub.setValue(0)
            self.scrub.setEnabled(bool(self.frames))
            self.play.setEnabled(bool(self.frames))
            self.status.setText(tr('Rendered effect · silent preview · {0} fps. Readability depends on source motion.').format(round(self.rate,2)))
            self.show_frame(0)
        self.owner.lookup(lambda:preview_frames(model.snapshot(),fps=fps,cancel=cancel),finish,lambda error:finish(error=error))

    def show_frame(self,index):
        if not self.frames:return
        at,data=self.frames[min(index,len(self.frames)-1)]
        pixmap=QPixmap()
        if pixmap.loadFromData(data):
            self.image.setPixmap(pixmap.scaled(max(120,self.image.width()-10),150,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        self.position.setText(video.time_text(at))

    def toggle_play(self):
        if self.timer.isActive():
            self.timer.stop()
            self.play.setText(tr('Play'))
        else:
            if self.scrub.value()==self.scrub.maximum():self.scrub.setValue(0)
            self.timer.start(max(16,round(1000/self.rate)))
            self.play.setText(tr('Pause'))

    def advance(self):
        if self.scrub.value()>=self.scrub.maximum():
            self.timer.stop()
            self.play.setText(tr('Play'))
        else:self.scrub.setValue(self.scrub.value()+1)
