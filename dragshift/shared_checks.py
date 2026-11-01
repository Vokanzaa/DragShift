"""Real bundled-engine checks for shared media and safe naming features."""
import time
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication

from . import bulk_rename,distortion,imaging,media_reverse,video
from .rename_rules import Rule,apply_rules,preset_json,read_preset


def _wait(predicate,seconds=45):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        QApplication.processEvents()
        if predicate():return
        time.sleep(.01)
    raise AssertionError('Shared feature UI did not finish its worker job.')


def check(base):
    base=Path(base)/'shared-feedback';base.mkdir()
    gif=base/'frames.gif'
    Image.new('RGB',(32,24),'red').save(gif,save_all=True,
        append_images=[Image.new('RGB',(32,24),'blue')],duration=[80,170],loop=2)
    inverted=imaging.edit_image(gif,imaging.Adjust(invert=True))
    with Image.open(inverted) as image:
        assert image.n_frames==2 and image.getpixel((10,10)) is not None
        assert image.convert('RGB').getpixel((10,10))==(0,255,255)
    reversed_gif=media_reverse.reverse(gif)[0]
    with Image.open(reversed_gif) as image:
        assert image.n_frames==2 and image.info['duration']==170 and image.info['loop']==2
        assert image.convert('RGB').getpixel((10,10))==(0,0,255)
        image.seek(1);assert image.info['duration']==80

    # Real extension modules and AnyAscii tables must survive freezing.
    files=[]
    for number in (10,2,1):
        path=base/f'кадр{number}.txt';path.write_text(str(number),encoding='utf-8');files.append(path)
    rules=[Rule('translit'),Rule('regex',{'find':r'(\d+)','replace':r'\1'}),
           Rule('number',{'where':'prefix','pad':3,'separator':'_'})]
    assert read_preset(preset_json(rules))==rules
    assert apply_rules(files[0],0,[Rule('translit')])=='kadr10.txt'
    plan=bulk_rename.preview(files,rules)
    assert not plan.errors and [e.target.name for e in plan.entries]==['001_kadr1.txt','002_kadr2.txt','003_kadr10.txt']
    result=bulk_rename.execute(plan,base/'journals')
    assert [new.read_text() for _,new in result.pairs]==['1','2','10']
    bulk_rename.undo(result.journal,base/'journals')
    assert all(p.exists() for p in files)
    occupied=base/'occupied.txt';occupied.write_text('unrelated')
    assert bulk_rename.preview([files[0]],[],overrides={str(files[0]):occupied.name}).errors
    try:bulk_rename.move_exclusive(files[0],occupied)
    except OSError:pass
    else:raise AssertionError('Native no-replace rename overwrote an occupied name.')
    assert occupied.read_text()=='unrelated'

    from .rename_tools import BulkRenameWindow
    window=BulkRenameWindow(files,lambda *_:None,journal_dir=base/'ui-journals')
    try:
        window.show()
        _wait(lambda:window.plan is not None and not window.preview_busy)
        window.set_rules([Rule('insert',{'text':'ui_'})])
        _wait(lambda:window.apply_button.isEnabled() and not window.preview_busy)
        window.apply_button.click()
        _wait(lambda:not window.busy and window.last_journal is not None)
        assert all((p.parent/('ui_'+p.name)).exists() for p in files)
        window.undo_button.click();_wait(lambda:not window.busy and all(p.exists() for p in files))
    finally:window.close();QApplication.processEvents()

    clips=[]
    for index,kind in enumerate(('testsrc2','testsrc')):
        source=base/f'clip-{index}.mp4'
        video.capture(video.ffmpeg_args()+['-f','lavfi','-i',f'{kind}=size=80x60:rate=30:duration=2.4',
            '-f','lavfi','-i','aevalsrc=0.001*sin(2*PI*997*t):s=48000:d=2.4',
            '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)])
        clips.append(source)
    wet=distortion.export(clips[0],strength=25,max_side=80,audio_strength=1,target='MP4')[0]
    assert abs(video.probe(wet).duration-2.4)<.002
    samples=np.frombuffer(video.capture([video.executable('ffmpeg'),'-v','error','-i',str(wet),
        '-map','0:a:0','-f','f32le','pipe:1']),dtype='<f4')
    assert np.isfinite(samples).all() and .0004<float(np.sqrt(np.mean(samples[12000:]**2)))<.001
    backwards=media_reverse.reverse(clips[0])[0]
    assert abs(video.probe(backwards).duration-2.4)<.002 and video.probe(backwards).has_audio
    def frames(path):
        raw=video.capture([video.executable('ffmpeg'),'-v','error','-i',str(path),'-map','0:v:0',
            '-fps_mode','passthrough','-f','rawvideo','-pix_fmt','rgb24','pipe:1'])
        return np.frombuffer(raw,dtype=np.uint8).reshape(-1,60,80,3).astype(float)
    a,b=frames(clips[0]),frames(backwards)
    assert len(a)==len(b)==72 and np.mean(np.abs(a[::-1]-b))<8

    from .melt_timeline import Timeline,render
    model=Timeline()
    for path in clips:model.add(path,2.4)
    model.cut(0).lead=.4;model.cut(0).duration=.6;model.cut(0).smooth=True
    output=render(model,max_side=80)[0]
    assert abs(video.probe(output).duration-4.8)<.002 and video.probe(output).has_audio
    assert len(frames(output))==144
    from .video_tools import DatamoshWindow
    window=DatamoshWindow(clips,lambda *_:None)
    try:
        window.show();_wait(lambda:window.first_info is not None and window.second_info is not None)
        window.phase.lead.setValue(.4);window.duration.setValue(.6);window.phase.smooth.setChecked(True)
        window.save(preview=True)
        _wait(lambda:not window.effect_preview.busy)
        assert window.effect_preview.frames and not window.effect_preview.image.pixmap().isNull(),window.effect_preview.status.text()
        window.strength.setValue(80);assert not window.effect_preview.scrub.isEnabled()
    finally:window.close();QApplication.processEvents()
    print('SHARED FEATURES OK · safe rename/undo/native no-replace · inversion · frame reversal · gentle pitch · real two-way Melt preview',flush=True)
