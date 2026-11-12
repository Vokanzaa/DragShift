"""Square framing for still Telegram emoji."""
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, QSignalBlocker, Qt
from PySide6.QtWidgets import QDoubleSpinBox, QGridLayout, QLabel

from . import telegram, video
from .convert import open_preview
from .glass import qimage_from_pil
from .i18n import tr
from .tools import CropView, ToolWindow
from .util import UserError, category


class SquareCropView(CropView):
    def mouseMoveEvent(self, event):
        if not self._mode or self._mode == 'move':
            return super().mouseMoveEvent(event)

        mode = self._mode
        original = self._orig
        anchor = self._start if mode == 'new' else QPointF(
            original.right() if 'l' in mode else original.left() if 'r' in mode else original.center().x(),
            original.bottom() if 't' in mode else original.top() if 'b' in mode else original.center().y(),
        )
        delta = self.clamp_image(self.to_image(event.position())) - anchor
        horizontal = mode == 'new' or 'l' in mode or 'r' in mode
        vertical = mode == 'new' or 't' in mode or 'b' in mode
        width, height = self.image.width(), self.image.height()

        def bounds(position, limit, distance, active):
            if not active:
                return 0, 2 * min(position, limit - position)
            return (-1, position) if distance < 0 else (1, limit - position)

        x_direction, x_limit = bounds(anchor.x(), width, delta.x(), horizontal)
        y_direction, y_limit = bounds(anchor.y(), height, delta.y(), vertical)
        requested = max(abs(delta.x()) if horizontal else 0, abs(delta.y()) if vertical else 0)
        side = min(max(requested, 1), x_limit, y_limit)
        if side < 1:
            return
        self.sel = QRectF(anchor.x() - (1 - x_direction) * side / 2,
                          anchor.y() - (1 - y_direction) * side / 2, side, side)
        self.update()
        self.changed.emit()

    def framing(self):
        width, height = self.image.width(), self.image.height()
        side = self.sel.width()

        def position(offset, travel):
            return min(1., max(0., offset / travel)) if travel > 0 else .5

        return (position(self.sel.left(), width - side),
                position(self.sel.top(), height - side), side / min(width, height))


class StaticEmojiWindow(ToolWindow):
    tool_name = 'Telegram emoji'

    def __init__(self, paths, notify):
        super().__init__('Telegram emoji', paths, notify, size=(720, 600))
        with Image.open(self.path) as source:
            if getattr(source, 'is_animated', False):
                raise UserError('Choose a still image for a static Telegram emoji.')
            short_side = min(source.size)
        preview = open_preview(self.path).convert('RGBA')
        self.view = SquareCropView(qimage_from_pil(preview), short_side / min(preview.size))
        self.view.setAccessibleName(tr('Square framing'))
        self.view.set_ratio(1.)
        self.body.addWidget(self.view, 1)

        tip = QLabel(tr('Drag the square to move it. Pull a handle to resize it.'))
        tip.setObjectName('dim')
        tip.setWordWrap(True)
        self.body.addWidget(tip)
        fields = QGridLayout()
        self.horizontal = self._percent(fields, 0, 'Horizontal position')
        self.vertical = self._percent(fields, 1, 'Vertical position')
        self.side = self._percent(fields, 2, 'Square size', minimum=.1)
        self.body.addLayout(fields)
        self.view.changed.connect(self._update_fields)
        self._update_fields()

        note = QLabel(tr('Static emoji · WebP · 100×100 · transparency preserved'))
        note.setObjectName('dim')
        self.body.addWidget(note)
        if len(self.paths) > 1:
            note = QLabel(tr('The same relative framing is applied to every selected image.'))
            note.setWordWrap(True)
            note.setObjectName('dim')
            self.body.addWidget(note)
        self.body.addLayout(self.footer('Save Telegram emoji', self.save, self.view.reset_sel))

    def _percent(self, layout, row, label, minimum=0.):
        field = QDoubleSpinBox()
        field.setRange(minimum, 100.)
        field.setDecimals(1)
        field.setSuffix(' %')
        field.setKeyboardTracking(False)
        field.setAccessibleName(tr(label))
        field.valueChanged.connect(self._update_square)
        name = QLabel(tr(label))
        name.setBuddy(field)
        layout.addWidget(name, row, 0)
        layout.addWidget(field, row, 1, Qt.AlignLeft)
        layout.setColumnStretch(2, 1)
        return field

    def _update_fields(self):
        for field, value in zip((self.horizontal, self.vertical, self.side), self.view.framing()):
            with QSignalBlocker(field):
                field.setValue(value * 100)

    def _update_square(self):
        width, height = self.view.image.width(), self.view.image.height()
        side = max(1., min(width, height) * self.side.value() / 100)
        left = (width - side) * self.horizontal.value() / 100
        top = (height - side) * self.vertical.value() / 100
        self.view.sel = QRectF(left, top, side, side)
        self.view.update()

    def accepts_sources(self, paths):
        return bool(paths) and all(category(p) == 'image' and Path(p).suffix.lower() != '.gif' for p in paths)

    def save(self):
        paths, framing = list(self.paths), self.view.framing()
        self.run(lambda: video.batch(paths, lambda path: telegram.export_static_emoji(path, framing)),
                 'Creating Telegram emoji…')


def emoji_window(paths, notify):
    formats = {telegram.emoji_format(category(path), Path(path).suffix) for path in paths}
    if formats == {'WEBP'}:
        return StaticEmojiWindow(paths, notify)
    if formats == {'WEBM'}:
        from .video_tools import TelegramEmojiWindow
        return TelegramEmojiWindow(paths, notify)
    raise UserError('Select still images separately from GIFs and videos.')
