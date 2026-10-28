import io,time
import pytest
from PIL import Image
from PySide6.QtCore import QPoint,QPointF,Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QScrollArea

from dragshift.app import DragShiftApp
from dragshift.distortion_tools import DistortionWindow


@pytest.fixture(autouse=True)
def drain_workers(qt_session):
    yield
    from dragshift.util import ALIVE
    wait(lambda:not ALIVE)


def wait(predicate):
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        QApplication.processEvents()
        if predicate():
            return
        time.sleep(.01)
    assert predicate()


def source(tmp_path):
    path=tmp_path/'first.gif'
    Image.new('RGB',(100,80),'red').save(path,save_all=True,
        append_images=[Image.new('RGB',(100,80),'blue')],duration=[200,300],loop=0)
    return path


def ready(tmp_path):
    window=DistortionWindow([source(tmp_path)],lambda *_:None)
    wait(lambda:window.info is not None and not window._preview_busy and not window.preview.pixmap().isNull())
    return window


def test_radial_routing_and_keyboard_parameters(qt_session,tmp_path):
    for filename in ('file.gif','file.mp4','file.png'):
        rings=DragShiftApp.build_rings(None,[filename])
        assert 'tool:Distort' in {item.key for item in rings['Tools']}
    window=ready(tmp_path)
    window.show()
    window.curve.level.setFocus()
    window.curve.level.selectAll()
    QTest.keyClicks(window.curve.level,'73')
    QTest.keyClick(window.curve.level,Qt.Key_Return)
    assert window.curve.points()[0][1]==73
    assert window.isVisible()
    window.at.setValue(.25)
    window.target.setCurrentText('PNG')
    submissions=[]
    window.submit=lambda *args:submissions.append(args)
    window.save()
    assert submissions[0][0]=='tool:Distort'
    outputs=submissions[0][2]()
    with Image.open(outputs[0]) as frame:
        assert frame.getpixel((50,40))[:3]==(0,0,255)
    wait(lambda:not window._callbacks)


def test_drop_replaces_actual_source_and_preserves_tool(qt_session,tmp_path):
    window=ready(tmp_path)
    replacement=tmp_path/'chosen.png'
    Image.new('RGB',(90,70),'green').save(replacement)
    assert window.accepts_sources([replacement]) and not window.accepts_sources([tmp_path/'audio.mp3'])
    window.receive_files([str(replacement)])
    other=window._replacement
    wait(lambda:other.info is not None)
    assert other.path==replacement and other.target.currentText()=='PNG'
    other.close()
    wait(lambda:not other._callbacks)


def test_preview_coalesces_and_ignores_old_result(qt_session,tmp_path,monkeypatch):
    window=ready(tmp_path)
    calls=[]
    monkeypatch.setattr(window,'lookup',lambda fn,done,failure=None:calls.append((fn,done,failure)))
    window.curve.set_strength(20)
    window.load_frame()
    assert len(calls)==1
    window.curve.set_strength(80)
    window.load_frame()
    assert len(calls)==1
    calls[0][1]((Image.new('RGBA',(20,20)),b'old invalid image'))
    wait(lambda:len(calls)==2)
    assert window.preview.text()!='Frame preview unavailable'
    data=io.BytesIO()
    Image.new('RGB',(20,20),'red').save(data,'PNG')
    calls[1][1]((Image.new('RGBA',(20,20)),data.getvalue()))
    assert not window._preview_busy and not window.preview.pixmap().isNull()
    window.close()


def test_strength_preview_reuses_decoded_source(qt_session,tmp_path,monkeypatch):
    from dragshift import distortion
    window=ready(tmp_path)
    reads=[]
    original=distortion.source_frame
    def read(*args,**kwargs):
        reads.append(args)
        return original(*args,**kwargs)
    monkeypatch.setattr(distortion,'source_frame',read)
    window.curve.set_strength(85)
    window.load_frame()
    wait(lambda:not window._preview_busy)
    assert not reads
    window.at.setValue(.25)
    window.load_frame()
    wait(lambda:not window._preview_busy)
    assert len(reads)==1
    window.close()


def test_native_curve_edit_scrub_trim_and_whole_video(qt_session,tmp_path):
    window=ready(tmp_path)
    window.show()
    QApplication.processEvents()
    assert window.curve.isVisible() and not window.static_strength.isVisible()
    assert window.curve.points()==[[0.,40.],[1.,40.]]
    window.curve.level.setFocus()
    window.curve.level.selectAll()
    QTest.keyClicks(window.curve.level,'73')
    QTest.keyClick(window.curve.level,Qt.Key_Return)
    assert window.curve.points()[0][1]==73
    QTest.mouseClick(window.scrub,Qt.LeftButton,pos=QPoint(window.scrub.width()*3//4,window.scrub.height()//2))
    wait(lambda:not window._preview_busy)
    assert window.at.value()>0
    assert window.curve.curve.playhead==pytest.approx(window.at.value())
    window.start.setValue(.2)
    window.end.setValue(.4)
    assert window.output_duration.text()=='0.200 s'
    assert (window.trim_range.start,window.trim_range.end)==(.2,.4)
    window.trim_range.setFocus()
    window.trim_range.active=0
    QTest.keyClick(window.trim_range,Qt.Key_Right)
    assert window.start.value()==.21 and window.output_duration.text()=='0.190 s'
    QTest.mouseClick(window.whole_video,Qt.LeftButton)
    assert window.start.value()==0 and window.end.value()==.5
    assert window.output_duration.text()=='0.500 s'
    window.close()


def test_click_keyframe_seeks_real_preview_without_rerolling(qt_session,tmp_path):
    window=ready(tmp_path)
    window.show()
    window.curve.set_points([(0,20),(.4,80),(1,40)])
    points=window.curve.points()
    canvas=window.curve.curve
    QTest.mouseClick(canvas,Qt.LeftButton,pos=canvas.position(canvas.points[1]).toPoint())
    wait(lambda:not window._preview_busy and not window._preview_timer.isActive())
    assert window.at.value()==.2 and window.curve.level.value()==80
    assert window.curve.points()==points
    image=window.preview.pixmap().toImage()
    color=image.pixelColor(image.width()//2,image.height()//2)
    assert color.blue()>240 and color.red()<15
    window.at.setValue(.1)
    window.at.setValue(.35)
    assert window.curve.points()==points
    window.close()


def test_numeric_wheel_scroll_does_not_change_range_or_strength(qt_session,tmp_path):
    window=ready(tmp_path)
    window.resize(700,600)
    window.show()
    QApplication.processEvents()
    scroll=window.findChild(QScrollArea)
    scroll.verticalScrollBar().setValue(0)
    before=(window.end.value(),window.curve.level.value(),window.curve.time.value(),window.max_side.value())
    for widget in (window.end,window.curve.level,window.curve.time,window.max_side):
        widget.setFocus()
        wheel=QWheelEvent(QPointF(5,5),QPointF(widget.mapToGlobal(QPoint(5,5))),QPoint(),QPoint(0,-120),
                          Qt.NoButton,Qt.NoModifier,Qt.NoScrollPhase,False)
        QApplication.sendEvent(widget,wheel)
    assert (window.end.value(),window.curve.level.value(),window.curve.time.value(),window.max_side.value())==before
    assert scroll.verticalScrollBar().value()>0
    window.close()


def test_audio_availability_format_switch_and_saving_exact_curve(qt_session,tmp_path,media_engines,monkeypatch):
    from dragshift import distortion,video
    path=tmp_path/'with-audio.mp4'
    video.capture([video.executable('ffmpeg'),'-v','error','-f','lavfi','-i',
        'testsrc2=size=96x64:rate=10:duration=1.2','-f','lavfi','-i','sine=duration=1.2',
        '-c:v','libx264','-c:a','aac','-y',str(path)])
    window=DistortionWindow([path],lambda *_:None)
    window.show()
    wait(lambda:window.info is not None and not window._preview_busy and not window.preview.pixmap().isNull())
    assert window.audio_strength.value()==40 and window.audio_controls.isEnabled()
    QTest.mouseClick(window.keep_audio,Qt.LeftButton,pos=QPoint(8,window.keep_audio.height()//2))
    assert not window.audio_controls.isEnabled()
    QTest.mouseClick(window.keep_audio,Qt.LeftButton,pos=QPoint(8,window.keep_audio.height()//2))
    assert window.audio_controls.isEnabled()
    window.target.setCurrentText('GIF')
    assert not window.keep_audio.isEnabled() and not window.audio_controls.isEnabled()
    window.target.setCurrentText('MP4')
    window.audio_strength.setValue(81)
    window.curve.set_points([(0,20),(.5,90),(1,40)])
    window.start.setValue(.2)
    window.end.setValue(.8)
    window.at.setValue(.6)
    calls=[]
    monkeypatch.setattr(distortion,'export',lambda path,**options:calls.append((path,options)) or [])
    submissions=[]
    window.submit=lambda *args:submissions.append(args)
    window.save()
    submissions[0][2]()
    options=calls[0][1]
    assert options['curve']==[[0.,20.],[.5,90.],[1.,40.]]
    assert options['audio_strength']==81 and options['keep_audio']
    assert options['start']==.2 and options['end']==.8 and options['at']==.6


def test_still_image_has_ordinary_strength_and_no_audio(qt_session,tmp_path):
    path=tmp_path/'still.png'
    Image.new('RGBA',(96,64),(240,10,10,0)).save(path)
    window=DistortionWindow([path],lambda *_:None)
    window.show()
    wait(lambda:window.info is not None and not window._preview_busy)
    assert window.static_strength.isVisible() and not window.curve.isVisible()
    assert not window.keep_audio.isEnabled() and not window.audio_controls.isEnabled()
    assert not window.scrub.isEnabled() and not window.at.isEnabled()
    window.close()
