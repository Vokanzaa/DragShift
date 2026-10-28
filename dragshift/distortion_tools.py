"""Content-aware distortion inside the existing Shift+drag workflow."""

from .i18n import tr, tr_items
import io
from PySide6.QtCore import QEvent,QObject,Qt,QTimer
from PySide6.QtWidgets import (QAbstractScrollArea,QApplication,QCheckBox,QComboBox,QFormLayout,
    QHBoxLayout,QLabel,QPushButton,QSlider,QSpinBox,QWidget)

from . import distortion,distortion_audio,video
from .distortion_curve import DistortionCurve
from .media_controls import TrimRange,value_editor
from .util import category
from .video_tools import _AsyncTools,_field,_preview_label,_scroll_panel,_seconds,_show_frame


class _ScrollWheelGuard(QObject):
    """Wheel gestures scroll the settings panel instead of silently editing it."""
    def eventFilter(self,watched,event):
        if event.type()==QEvent.Wheel:
            parent=watched.parentWidget()
            while parent is not None and not isinstance(parent,QAbstractScrollArea):
                parent=parent.parentWidget()
            if parent is not None:
                QApplication.sendEvent(parent.viewport(),event)
            event.ignore()
            return True
        return super().eventFilter(watched,event)


class DistortionWindow(_AsyncTools):
    tool_name='Distort'

    def __init__(self,paths,notify):
        super().__init__('Distort',paths,notify,(700,900))
        self.info=None
        self._request=0
        self._preview_busy=False
        self._source_cache=None
        self.details=QLabel(tr('Reading media…'))
        self.details.setObjectName('dim')
        self.body.addWidget(self.details)
        self.preview=_preview_label()
        self.preview.setAccessibleName(tr('Distorted frame preview'))
        self.body.addWidget(self.preview)
        self.scrub=QSlider(Qt.Horizontal)
        self.scrub.setRange(0,1000)
        self.scrub.setAccessibleName(tr('Frame position'))
        self.scrub.setEnabled(False)
        self.body.addWidget(self.scrub)
        self.original=QCheckBox(tr('Show original frame'))
        self.body.addWidget(self.original)
        form=QFormLayout()
        self.form=form
        form.setVerticalSpacing(10)
        self.strength=QSlider(Qt.Horizontal)
        self.strength.setRange(0,95)
        self.strength.setValue(40)
        self.strength.setAccessibleName(tr('Distortion intensity'))
        self.strength_number=value_editor(self.strength,'Distortion intensity')
        row=QHBoxLayout()
        row.addWidget(self.strength,1)
        row.addWidget(self.strength_number)
        self.static_strength=QWidget()
        self.static_strength.setLayout(row)
        form.addRow(tr('Image intensity'),self.static_strength)
        self.static_strength_label=form.labelForField(self.static_strength)
        self.curve=DistortionCurve()
        form.addRow(self.curve)
        self.audio_strength=QSlider(Qt.Horizontal)
        self.audio_strength.setRange(0,100)
        self.audio_strength.setValue(distortion_audio.DEFAULT_STRENGTH)
        self.audio_strength.setAccessibleName(tr('Audio distortion intensity'))
        self.audio_strength_number=value_editor(self.audio_strength,'Audio distortion intensity')
        row=QHBoxLayout()
        row.addWidget(self.audio_strength,1)
        row.addWidget(self.audio_strength_number)
        self.audio_controls=QWidget()
        self.audio_controls.setLayout(row)
        form.addRow(tr('Audio distortion'),self.audio_controls)
        self.audio_label=form.labelForField(self.audio_controls)
        self.keep_audio=QCheckBox(tr('Keep source audio'))
        self.keep_audio.setChecked(True)
        form.addRow(self.keep_audio)
        self.audio_note=QLabel(tr('Audio is distorted while saving MP4/WebM. 0 keeps the original sound.'))
        self.audio_note.setObjectName('dim')
        self.audio_note.setWordWrap(True)
        form.addRow(self.audio_note)
        self.max_side=QSpinBox()
        self.max_side.setRange(64,1920)
        self.max_side.setValue(640)
        self.max_side.setSuffix(tr(' px'))
        self.max_side.setToolTip(tr('Maximum longest side; keeps the aspect ratio and never enlarges. '
                                   'For example, 1424 × 1904 becomes 478 × 640 at 640 px.'))
        _field(form,'Maximum video/image size',self.max_side)
        self.target=QComboBox()
        self.target.addItems(tr_items(distortion.TARGETS))
        _field(form,'Save as',self.target)
        self.at=_seconds()
        _field(form,'Preview frame at',self.at)
        self.start,self.end=_seconds(),_seconds()
        self.trim_range=TrimRange()
        self.segment_widgets=[]
        for label,widget in [('Export start',self.start),('Export end',self.end)]:
            _field(form,label,widget)
            self.segment_widgets.extend((form.labelForField(widget),widget))
        form.addRow(tr(self.trim_range))
        self.segment_widgets.append(self.trim_range)
        self.output_duration=QLabel()
        _field(form,'Export duration',self.output_duration)
        self.whole_video=QPushButton(tr('Whole video'))
        form.addRow(self.whole_video)
        self.segment_widgets.extend((form.labelForField(self.output_duration),self.output_duration,self.whole_video))
        self.body.addWidget(_scroll_panel(form),1)
        self._wheel_guard=_ScrollWheelGuard(self)
        for control in (self.strength,self.strength_number,self.audio_strength,self.audio_strength_number,
                        self.max_side,self.at,self.start,self.end,self.curve.time,self.curve.level,self.target):
            control.installEventFilter(self._wheel_guard)
        note=QLabel(tr('Liquid Rescale · 0 = original, 95 = strongest. Keyframe strengths are absolute. '
                    'PNG saves the preview frame; MP4/WebM/GIF save the export range. Drop media here to replace it.'))
        note.setObjectName('dim')
        note.setWordWrap(True)
        self.body.addWidget(note)
        if len(self.paths)>1:
            batch=QLabel(tr(f'Settings apply to all {len(self.paths)} files. Preview shows the first. '
                        'An unchanged range processes each file in full.'))
            batch.setWordWrap(True)
            self.body.addWidget(batch)
        self.body.addWidget(self.error)
        self.body.addLayout(self.footer('Save',self.save))
        self.primary_btn.setEnabled(False)
        self._preview_timer=QTimer(self,interval=200,singleShot=True)
        self._preview_timer.timeout.connect(self.load_frame)
        for control in (self.strength,self.max_side):
            control.valueChanged.connect(self._schedule_preview)
        self.original.toggled.connect(self._schedule_preview)
        self.curve.changed.connect(self._schedule_preview)
        self.curve.playheadMoved.connect(self.at.setValue)
        self.keep_audio.toggled.connect(self._audio_changed)
        self.target.currentTextChanged.connect(self._target_changed)
        self.at.valueChanged.connect(self._time_changed)
        self.scrub.valueChanged.connect(self._scrub_changed)
        self.start.valueChanged.connect(self._sync_range)
        self.end.valueChanged.connect(self._sync_range)
        self.trim_range.changed.connect(self._range_changed)
        self.whole_video.clicked.connect(self._whole_video)
        path=self.path
        self.lookup(lambda:distortion.probe(path),self._loaded)

    def accepts_sources(self,paths):
        return bool(paths) and all(category(p) in ('image','video') for p in paths)

    def _loaded(self,info):
        self.info=info
        self.details.setText(tr(f'{info.width} × {info.height} · {video.time_text(info.duration)} · '
                             f'{info.fps:.2f} fps · {"Audio" if info.has_audio else "No audio"}' if info.animated else f'{info.width} × {info.height} · Still image'))
        self.curve.setVisible(info.animated)
        self.curve.set_duration(info.duration)
        self.static_strength.setVisible(not info.animated)
        self.static_strength_label.setVisible(not info.animated)
        self.end.setMaximum(info.duration)
        self.start.setMaximum(max(0,info.duration-.02))
        self.end.setValue(info.duration)
        self.at.setMaximum(max(0,info.duration-(.001 if info.image else 1/max(1,info.fps))))
        self.scrub.setEnabled(info.animated)
        self.at.setEnabled(info.animated)
        self.target.setCurrentText('GIF' if info.image and info.animated else 'PNG' if info.image else 'MP4')
        self._target_changed()
        self._sync_range()
        self.primary_btn.setEnabled(True)
        self._schedule_preview()

    def _target_changed(self,*_):
        segment=bool(self.info and self.info.animated and self.target.currentText()!='PNG')
        for widget in self.segment_widgets:
            widget.setVisible(segment)
        self.primary_btn.setText(tr('Save PNG frame' if self.target.currentText()=='PNG' else f'Save {self.target.currentText()}'))
        self._audio_changed()

    def _audio_changed(self,*_):
        available=bool(self.info and self.info.has_audio and self.target.currentText() in ('MP4','WEBM'))
        self.keep_audio.setEnabled(available)
        self.audio_controls.setEnabled(available and self.keep_audio.isChecked())
        self.audio_label.setEnabled(available and self.keep_audio.isChecked())
        self.audio_note.setText(tr('Audio is distorted while saving MP4/WebM. 0 keeps the original sound.' if available
                                  else 'This source has no audio.' if self.info and not self.info.has_audio
                                  else 'This format saves no audio.'))

    def _whole_video(self):
        if self.info:
            self.start.setValue(0)
            self.end.setValue(self.info.duration)
            self._sync_range()

    def _sync_range(self,*_):
        if self.info:
            self.trim_range.set_values(self.start.value(),self.end.value(),self.info.duration)
            self.output_duration.setText(tr(f'{max(0,self.end.value()-self.start.value()):.3f} s'))

    def _range_changed(self,start,end):
        for spin,value in ((self.start,start),(self.end,end)):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        if self.info:
            self._sync_range()
            self.at.setValue(start if self.trim_range.active==0 else max(start,end-1/max(1,self.info.fps)))

    def _scrub_changed(self,value):
        if self.info:
            self.at.setValue(value/1000*self.at.maximum())

    def _time_changed(self,value):
        self.scrub.blockSignals(True)
        self.scrub.setValue(round(1000*value/max(.001,self.at.maximum())))
        self.scrub.blockSignals(False)
        self.curve.set_playhead(value)
        self._schedule_preview()

    def _schedule_preview(self,*_):
        self._request+=1
        self._preview_timer.start()

    def load_frame(self):
        self._preview_timer.stop()
        if not self.info or self._preview_busy:
            return
        self._preview_busy=True
        request=self._request
        path,at=self.path,self.at.value()
        strength=(distortion.strength_at(self.curve.points(),distortion.source_timestamp(self.info,at),self.info.duration)
                  if self.info.animated else self.strength.value())
        if self.original.isChecked():
            strength=0
        size=self.max_side.value()
        def complete(data=None,error=None):
            self._preview_busy=False
            if request==self._request:
                if error:
                    self.preview.setText(tr(error))
                else:
                    _show_frame(self.preview,data)
            else:
                self._preview_timer.start(0)
        try:
            stat=path.stat()
        except OSError:
            self._preview_busy=False
            self.preview.setText(tr('The file was moved or deleted.'))
            return
        frame_at=distortion.source_timestamp(self.info,at)
        key=(frame_at,size,stat.st_mtime_ns,stat.st_size)
        cached=self._source_cache
        info=self.info
        def render():
            frame=cached[1] if cached and cached[0]==key else distortion.source_frame(path,frame_at,size,info=info)
            result=distortion.distort_frame(frame,strength=strength,max_side=size)
            data=io.BytesIO()
            result.save(data,'PNG',compress_level=1)
            return frame,data.getvalue()
        def rendered(value):
            frame,data=value
            self._source_cache=(key,frame)
            complete(data=data)
        self.lookup(render,rendered,lambda error:complete(error=error))

    def save(self):
        if not self.info:
            return
        start,end=self.start.value(),self.end.value()
        target=self.target.currentText()
        if target!='PNG' and end-start<.02:
            self.error.setText(tr('End must be after start.'))
            return
        # The default full range means each batch source's own complete duration.
        full=start==0 and abs(end-self.info.duration)<.001
        options=dict(strength=self.strength.value(),max_side=self.max_side.value(),target=target,
                     at=self.at.value(),start=0 if full or target=='PNG' else start,
                     end=None if full or target=='PNG' else end,
                     curve=self.curve.points() if self.info.animated else None,
                     audio_strength=self.audio_strength.value(),keep_audio=self.keep_audio.isChecked())
        paths=list(self.paths)
        fn=lambda:video.batch(paths,lambda path:distortion.export(path,**options))
        if self.submit:
            detail='Keyframe curve' if self.info.animated else f'Intensity {options["strength"]}'
            self.submit('tool:Distort',paths,fn,'Distorting frames…',tr(detail))
        else:
            try:
                self.notify('tool:Distort',paths,fn())
            except Exception as error:
                self.error.setText(tr(str(error)))
                return
        self.close()

    def closeEvent(self,event):
        self._preview_timer.stop()
        super().closeEvent(event)
