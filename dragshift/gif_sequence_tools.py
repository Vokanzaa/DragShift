"""One animation from an explicitly ordered, inspectable set of image frames."""
from pathlib import Path

from PySide6.QtCore import Qt,Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QCheckBox,QComboBox,QFormLayout,QHBoxLayout,QLabel,QPushButton,QSpinBox

from . import gif_sequence as sequence
from .convert import open_preview
from .glass import qimage_from_pil
from .i18n import tr
from .media_controls import FileSequence
from .util import category
from .video_tools import _AsyncTools,_field


class _Frames(FileSequence):
    added=Signal()
    manual=Signal()

    def __init__(self,paths):
        self._next_id=0
        super().__init__(paths,lambda p:category(p)=='image','Images (*.png *.jpg *.jpeg *.webp *.heic *.heif *.tif *.tiff *.avif *.bmp *.gif *.ico)')
        self.list.model().rowsAboutToBeMoved.connect(lambda *_:self.manual.emit())
        self.list.setAccessibleName(tr('Animation frame order'))
        self.list.setMaximumHeight(16777215)

    def add(self,paths):
        before=self.list.count()
        super().add(paths)
        for row in range(before,self.list.count()):
            self.list.item(row).setData(Qt.UserRole+1,self._next_id)
            self._next_id+=1
        self.added.emit()

    def move(self,delta):
        row=self.list.currentRow()
        if 0<=row+delta<self.list.count():
            self.manual.emit()
        super().move(delta)


class GifSequenceWindow(_AsyncTools):
    tool_name='GIF animation'

    def __init__(self,paths,notify):
        super().__init__('GIF from image frames',paths,notify,(850,650))
        self._generation=0
        self._preview_generation=0
        self.infos=[]
        self.details=QLabel()
        self.details.setWordWrap(True)
        self.body.addWidget(self.details)
        form=QFormLayout()
        self.order=QComboBox()
        for text,value in [('Name · numeric order (1, 2, 10)','name'),
                           ('Date modified · oldest first','date'),
                           ('Original addition order','added'),('Manual order','manual')]:
            self.order.addItem(tr(text),value)
        _field(form,'Frame order',self.order)
        self.fps=QSpinBox()
        self.fps.setRange(1,100)
        self.fps.setValue(10)
        self.fps.setKeyboardTracking(False)
        _field(form,'Frames per second',self.fps)
        self.loop=QCheckBox(tr('Loop animation'))
        self.loop.setChecked(True)
        form.addRow(self.loop)
        self.body.addLayout(form)
        self.sequence=_Frames(paths)
        row=QHBoxLayout()
        row.addWidget(self.sequence,3)
        self.preview=QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(220,180)
        self.preview.setAccessibleName(tr('Selected animation frame'))
        row.addWidget(self.preview,2)
        self.body.addLayout(row,1)
        reverse=QPushButton(tr('Reverse frame order'))
        reverse.clicked.connect(self.reverse)
        self.body.addWidget(reverse)
        self.note=QLabel(tr('The visible list is the exact export order. Different sizes fit inside the first frame without cropping.'))
        self.note.setWordWrap(True)
        self.body.addWidget(self.note)
        self.warning=QLabel()
        self.warning.setWordWrap(True)
        self.body.addWidget(self.warning)
        self.body.addWidget(self.error)
        self.body.addLayout(self.footer('Create GIF animation',self.save))
        self.sequence.changed.connect(self._changed)
        self.sequence.added.connect(self.apply_sort)
        self.sequence.manual.connect(self._manual)
        self.sequence.list.currentRowChanged.connect(self.show_frame)
        self.order.currentIndexChanged.connect(self.apply_sort)
        self.fps.valueChanged.connect(self.update_details)
        self.apply_sort()

    def _manual(self):
        self.order.blockSignals(True)
        self.order.setCurrentIndex(self.order.findData('manual'))
        self.order.blockSignals(False)

    def apply_sort(self,*_):
        mode=self.order.currentData()
        if mode=='manual':return
        items=[self.sequence.list.takeItem(0) for _ in range(self.sequence.list.count())]
        try:
            if mode=='added':
                items.sort(key=lambda item:item.data(Qt.UserRole+1))
            else:
                positions={p:i for i,p in enumerate(sequence.ordered_paths([item.data(Qt.UserRole) for item in items],mode))}
                items.sort(key=lambda item:positions[Path(item.data(Qt.UserRole))])
        except Exception as error:
            self.error.setText(tr(str(error)))
        for item in items:self.sequence.list.addItem(item)
        self._changed(self.sequence.paths())
        if items:self.sequence.list.setCurrentRow(0)

    def reverse(self):
        self._manual()
        items=[self.sequence.list.takeItem(0) for _ in range(self.sequence.list.count())]
        for item in reversed(items):self.sequence.list.addItem(item)
        self._changed(self.sequence.paths())
        if items:self.sequence.list.setCurrentRow(0)

    def _changed(self,paths):
        self.paths=list(paths)
        self._generation+=1
        generation=self._generation
        self.infos=[]
        self.primary_btn.setEnabled(False)
        self.error.clear()
        self.warning.setText(tr(sequence.number_notice(paths)))
        for row,path in enumerate(paths):
            self.sequence.list.item(row).setText(f'{row+1:03d}  {path.name}')
        if not paths:
            self.details.setText(tr('Add images to create a GIF animation.'))
            self.preview.clear()
            return
        self.path=paths[0]
        def ready(infos):
            if generation!=self._generation:return
            self.infos=infos
            self.primary_btn.setEnabled(len(paths)>=2)
            self.update_details()
        self.lookup(lambda:sequence.inspect_frames(paths),ready,
                    lambda message:self.error.setText(tr(message)) if generation==self._generation else None)

    def update_details(self,*_):
        if self.infos:
            count=sum(i.count for i in self.infos)
            w,h=self.infos[0].size
            self.details.setText(tr(f'{count} frames · {count/self.fps.value():.2f} s · {w}×{h} · one GIF'))

    def show_frame(self,row):
        self._preview_generation+=1
        generation=self._preview_generation
        paths=self.sequence.paths()
        if not 0<=row<len(paths):return
        path=paths[row]
        def ready(image):
            if generation==self._preview_generation:
                self.preview.setPixmap(QPixmap.fromImage(image).scaled(280,220,Qt.KeepAspectRatio,Qt.SmoothTransformation))
                self.preview.setToolTip(str(path))
        self.lookup(lambda:qimage_from_pil(open_preview(path,480)),ready,
                    lambda message:self.error.setText(tr(message)) if generation==self._preview_generation else None)

    def accepts_sources(self,paths):
        return bool(paths) and all(category(p)=='image' for p in paths)

    def receive_files(self,paths):
        self.sequence.add(paths)

    def save(self):
        paths=self.sequence.paths()
        if len(paths)<2:return
        fps,loop=self.fps.value(),self.loop.isChecked()
        self.paths=list(paths)
        count=sum(info.count for info in self.infos) or len(paths)
        self.run(lambda:sequence.export(paths,fps=fps,loop=loop),'Encoding GIF frames…',f'{count} frames · {fps} fps')
