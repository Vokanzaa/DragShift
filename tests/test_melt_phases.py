import json
import threading

import pytest

from dragshift import video
from dragshift.melt_timeline import Timeline, render
from dragshift.util import UserError


@pytest.fixture
def clips(tmp_path,media_engines):
    result=[]
    for index,kind in enumerate(('testsrc2','testsrc')):
        path=tmp_path/f'clip-{index}.mp4'
        video.capture([video.executable('ffmpeg'),'-v','error','-f','lavfi','-i',
            f'{kind}=size=160x120:rate=30:duration=2','-f','lavfi','-i',
            f'sine=frequency={440+index*220}:duration=2','-c:v','libx264','-pix_fmt','yuv420p',
            '-c:a','aac','-y',str(path)])
        result.append(path)
    return result


def test_pre_cut_onset_does_not_move_cut_or_delete_the_clean_anchor(clips,monkeypatch):
    model=Timeline()
    for path in clips:model.add(path,2)
    model.cut(0).lead=.5
    model.cut(0).duration=.7
    calls=[];run=video.run_process
    def record(args,*rest,**kwargs):
        calls.append(args)
        return run(args,*rest,**kwargs)
    monkeypatch.setattr(video,'run_process',record)
    output=render(model,max_side=160)[0]
    params=json.loads(calls[1][calls[1].index('-sp')+1])
    assert params['ranges']==[dict(start=45,cut=60,end=81,strength=65)]
    assert video.probe(output).duration==pytest.approx(4,abs=.002)
    assert not any('blend=' in str(arg) for call in calls for arg in call)


def test_phase_preview_keeps_full_requested_effect_and_rejects_overlapping_cuts():
    model=Timeline()
    for name in ('A','B','C'):model.add(name+'.mp4',20)
    cut=model.cut(0);cut.lead=4;cut.duration=8;cut.smooth=True
    preview=model.preview(0)
    assert preview.cut(0).lead==4 and preview.cut(0).duration==8 and preview.cut(0).smooth
    assert preview.clips[0].duration==4.25
    model.cut(1).lead=13
    with pytest.raises(UserError,match='overlap'):model.validate()


def hashes(path):
    data=video.capture([video.executable('ffmpeg'),'-v','error','-i',str(path),'-map','0:v:0','-f','framemd5','pipe:1'])
    return [line.rsplit(',',1)[-1].strip() for line in data.decode().splitlines() if line and not line.startswith('#')]


def test_chunked_reverse_is_lossless_in_exact_reverse_order(clips,tmp_path,monkeypatch):
    from dragshift import melt_bidirectional as module
    monkeypatch.setattr(module,'REVERSE_MEMORY',160*120*4*7)
    output=module.reverse_range(clips[0],0,60,fps=30,width=160,height=120,folder=tmp_path,name='reversed')
    assert hashes(output)==list(reversed(hashes(clips[0])))
    assert len(list(tmp_path.glob('reversed-*.mkv')))==9


def test_bidirectional_render_preserves_duration_audio_and_uses_only_binary_wet_handoff(clips,monkeypatch):
    model=Timeline()
    for path in clips:model.add(path,2)
    model.cut(0).lead=.6;model.cut(0).duration=.8;model.cut(0).smooth=True
    before=[path.read_bytes() for path in clips]
    calls=[];run=video.run_process
    def record(args,*rest,**kwargs):
        calls.append(args)
        return run(args,*rest,**kwargs)
    monkeypatch.setattr(video,'run_process',record)
    output=render(model,max_side=160)[0]
    info=video.probe(output)
    assert info.duration==pytest.approx(4,abs=.002) and info.has_audio
    assert len(hashes(output))==120
    assert len([call for call in calls if '-sp' in call])==2
    graphs=[call[call.index('-filter_complex')+1] for call in calls if '-filter_complex' in call]
    assert any('maskedmerge' in graph and '255,0' in graph for graph in graphs)
    assert not any('blend=' in graph or 'xfade=' in graph for graph in graphs)
    assert before==[path.read_bytes() for path in clips]


def test_smooth_melt_cancel_cleans_every_private_stage(clips):
    model=Timeline()
    for path in clips:model.add(path,2)
    model.cut(0).lead=.5;model.cut(0).duration=.8;model.cut(0).smooth=True
    before=set(clips[0].parent.iterdir())
    cancel=threading.Event()
    with video.job_context(video.Control(cancel=cancel,progress=lambda value,message:cancel.set() if value>.41 else None)):
        with pytest.raises(video.Cancelled):render(model,max_side=160)
    assert set(clips[0].parent.iterdir())==before
