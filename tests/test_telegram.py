import io
import json
import pytest
from PIL import Image

from dragshift import video


@pytest.mark.parametrize('kind',['gif','mp4'])
def test_telegram_emoji_profile_and_motion(tmp_path,media_engines,kind):
    from dragshift import telegram
    source=tmp_path/('animation.'+kind)
    if kind=='gif':
        frames=[Image.new('RGBA',(80,60),c) for c in ('red','blue')]
        frames[0].save(source,save_all=True,append_images=frames[1:],duration=[500,500],loop=0)
    else:
        video.capture([video.executable('ffmpeg'),'-v','error','-f','lavfi','-i',
                       'testsrc2=size=160x120:rate=60:duration=4','-f','lavfi','-i',
                       'sine=frequency=440:duration=4','-c:v','libx264','-c:a','aac','-y',str(source)])
    before=source.read_bytes()
    out=telegram.export_emoji(source)[0]
    assert out.suffix=='.webm' and out.stat().st_size<=256000
    info=video.probe(out)
    assert (info.width,info.height,info.codec)==(100,100,'vp9')
    assert info.duration<=3.001 and info.fps<=30 and not info.has_audio
    raw=json.loads(video.capture([video.executable('ffprobe'),'-v','error','-show_streams','-of','json',str(out)]))
    assert [s['codec_type'] for s in raw['streams']]==['video']
    a=video.preview_bytes(out,.1)
    b=video.preview_bytes(out,.7)
    assert a!=b
    assert source.read_bytes()==before


def test_invalid_emoji_range_publishes_nothing(tmp_path,media_engines):
    from dragshift import telegram
    from dragshift.util import UserError
    source=tmp_path/'clip.gif'
    Image.new('RGB',(100,100),'red').save(source,save_all=True,
        append_images=[Image.new('RGB',(100,100),'blue')],duration=500)
    before=set(tmp_path.iterdir())
    with pytest.raises(UserError):
        telegram.export_emoji(source,start=.9,duration=2)
    assert set(tmp_path.iterdir())==before


def test_still_emoji_uses_square_selected_in_editor(tmp_path, qt_session):
    from types import SimpleNamespace
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest
    from dragshift import app
    from dragshift.report import summarize

    path = tmp_path / 'wide.png'
    image = Image.new('RGBA', (300, 100), 'red')
    image.paste((0, 0, 255, 255), (200, 0, 275, 100))
    image.paste((0, 0, 0, 0), (275, 0, 300, 100))
    image.save(path)
    original = path.read_bytes()
    controller = getattr(app, 'Swipe4RestApp', None) or app.DragShiftApp
    items = controller.build_rings(None, [str(path)])['Convert']
    item = next(item for item in items if item.key == 'tool:Telegram emoji')
    opened, results = [], []
    host = SimpleNamespace(open_window=opened.append, notify=lambda *args: results.append(args))
    controller.run_item(host, item, [str(path)])
    window = opened[0]
    try:
        window.show()
        qt_session.processEvents()
        view = window.view
        QTest.mousePress(view, Qt.LeftButton, pos=view.to_widget(view.sel.center()).toPoint())
        target = view.to_widget(QPointF(290, 50)).toPoint()
        QTest.mouseMove(view, target)
        QTest.mouseRelease(view, Qt.LeftButton, pos=target)
        assert view.framing() == (1., .5, 1.)
        window.primary_btn.click()
        action, sources, outputs, _ = results[0]
        assert action == 'tool:Telegram emoji' and sources == [str(path)]
        assert len(outputs) == 1 and outputs[0].suffix == '.webp'
        with Image.open(outputs[0]) as emoji:
            assert emoji.format == 'WEBP' and emoji.size == (100, 100)
            assert emoji.getpixel((25, 50)) == (0, 0, 255, 255)
            assert emoji.getpixel((90, 50))[3] == 0
        assert 'WebP · 100×100' in summarize(action, sources, outputs).detail
        assert path.read_bytes() == original
    finally:
        window.close()


def test_emoji_handle_resizes_square_at_image_edges(tmp_path, qt_session):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtTest import QTest
    from dragshift.telegram_tools import StaticEmojiWindow

    path = tmp_path / 'wide.jpg'
    Image.new('RGB', (300, 100), 'red').save(path)
    window = StaticEmojiWindow([path], lambda *_: None)
    try:
        window.show()
        qt_session.processEvents()
        window.side.setValue(40.)
        view = window.view
        start = view.to_widget(view.sel.bottomRight()).toPoint()
        target = view.to_widget(QPointF(300, 100)).toPoint()
        QTest.mousePress(view, Qt.LeftButton, pos=start)
        QTest.mouseMove(view, target)
        QTest.mouseRelease(view, Qt.LeftButton, pos=target)
        assert view.sel.width() == view.sel.height() == 70
        assert view.sel.bottom() == 100 and view.sel.right() <= 300
        window.view.reset_sel()
        assert view.sel.width() == view.sel.height() == 100
    finally:
        window.close()
