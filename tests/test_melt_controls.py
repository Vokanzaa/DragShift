import time

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from dragshift import i18n,video
from dragshift.melt_controls import MeltPhase
from dragshift.video_tools import DatamoshWindow,_seconds


def wait(app,predicate):
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        app.processEvents()
        if predicate():return
        time.sleep(.01)
    assert predicate()


def test_phase_handles_stay_on_opposite_sides_of_a_fixed_cut(qt_session):
    phase=MeltPhase(_seconds(.8))
    phase.set_times(2,3,.5,.8,source_end=12,source_start=7)
    phase.resize(640,240);phase.show();qt_session.processEvents()
    strip=phase.strip
    cut=strip._x(strip.left)
    left=QPoint(round(strip._x(strip.start)),strip.height()//2)
    QTest.mousePress(strip,Qt.LeftButton,pos=left)
    QTest.mouseMove(strip,QPoint(round(cut+30),left.y()))
    QTest.mouseRelease(strip,Qt.LeftButton,pos=QPoint(round(cut+30),left.y()))
    assert phase.lead.value()==0 and phase.recovery.value()==.8
    assert strip._x(strip.left)==cut
    phase.smooth.click()
    assert phase.smooth.isChecked() and phase.lead.value()>=.1
    assert '12.000' in phase.summary.text() and '07.800' in phase.summary.text()
    phase.close()


@pytest.mark.parametrize('language',['en','ru'])
def test_two_clip_editor_previews_real_effect_privately_and_marks_edits_stale(tmp_path,qt_session,media_engines,language):
    i18n.set_language(language)
    paths=[]
    for index,kind in enumerate(('testsrc2','testsrc')):
        path=tmp_path/f'input-{index}.mp4'
        video.capture([video.executable('ffmpeg'),'-v','error','-f','lavfi','-i',
            f'{kind}=size=160x120:rate=30:duration=2','-c:v','libx264','-pix_fmt','yuv420p','-y',str(path)])
        paths.append(path)
    window=DatamoshWindow(paths,lambda *_:None)
    window.show()
    wait(qt_session,lambda:window.first_info is not None and window.second_info is not None)
    window.phase.lead.setValue(.4)
    window.duration.setValue(.6)
    window.phase.smooth.setChecked(True)
    before=set(tmp_path.iterdir())
    window.save(preview=True)
    preview=window.effect_preview
    wait(qt_session,lambda:not preview.busy)
    assert preview.frames and not preview.image.pixmap().isNull(),preview.status.text()
    assert set(tmp_path.iterdir())==before
    assert window.effect_model().cut(0).smooth and window.effect_model().cut(0).lead==.4
    preview.scrub.setValue(len(preview.frames)//2)
    assert preview.position.text()==video.time_text(preview.frames[preview.scrub.value()][0])
    window.strength.setValue(80)
    assert not preview.play.isEnabled() and not preview.scrub.isEnabled()
    assert preview.status.text()==i18n.tr('Settings changed · render a new effect preview.')
    window.save(preview=True)
    window.close()
    from dragshift.util import ALIVE
    wait(qt_session,lambda:not ALIVE)
    i18n.set_language('en')
