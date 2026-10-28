"""Audio distortion is a single synchronized filter in the Distort encode."""
import numpy as np
import pytest

from dragshift import video
from dragshift.util import UserError


def filtered_samples(source, strength):
    from dragshift import distortion_audio
    expression=distortion_audio.filter_expression(strength)
    args=[video.executable('ffmpeg'),'-v','error','-i',str(source)]
    if expression:
        args+=['-af',expression]
    return np.frombuffer(video.capture(args+['-f','f32le','-c:a','pcm_f32le','pipe:1']),dtype='<f4').reshape(-1,2)


@pytest.fixture
def sound(tmp_path,media_engines):
    path=tmp_path/'stereo.wav'
    video.capture([video.executable('ffmpeg'),'-v','error','-f','lavfi','-i',
        'aevalsrc=0.7*sin(2*PI*997*t)|0.4*sin(2*PI*439*t):s=48000:d=1',
        '-c:a','pcm_s16le','-y',str(path)])
    return path


def test_audio_intensity_changes_timbre_without_changing_samples_or_channels(sound):
    before=sound.read_bytes()
    dry=filtered_samples(sound,0)
    low=filtered_samples(sound,20)
    high=filtered_samples(sound,100)
    assert dry.shape==low.shape==high.shape==(48000,2)
    gain=np.sum(high*dry)/np.sum(dry*dry)
    assert np.sqrt(np.mean((high-gain*dry)**2))>.05
    assert np.sqrt(np.mean((low-dry)**2))<np.sqrt(np.mean((high-dry)**2))
    assert np.max(np.abs(high))<=.950001
    assert sound.read_bytes()==before


def test_zero_is_dry_and_silence_stays_silent(tmp_path,media_engines):
    from dragshift import distortion_audio
    assert distortion_audio.filter_expression(0)==''
    source=tmp_path/'silent.wav'
    video.capture([video.executable('ffmpeg'),'-v','error','-f','lavfi','-i',
        'anullsrc=r=48000:cl=stereo','-t','0.2','-c:a','pcm_s16le','-y',str(source)])
    assert not np.any(filtered_samples(source,100))


def test_loud_audio_is_bounded_without_filter_delay(tmp_path,media_engines):
    source=tmp_path/'loud.wav'
    video.capture([video.executable('ffmpeg'),'-v','error','-f','lavfi','-i',
        'aevalsrc=2*sin(2*PI*997*t)|2*sin(2*PI*439*t):s=48000:d=0.2',
        '-c:a','pcm_f32le','-y',str(source)])
    result=filtered_samples(source,100)
    assert result.shape==(9600,2)
    assert np.max(np.abs(result))<=.950001
    assert np.any(result[:16])


@pytest.mark.parametrize('value',[True,False,None,'bad',float('inf'),float('nan'),-1,101,2.5])
def test_invalid_audio_intensity_is_rejected(value):
    from dragshift import distortion_audio
    with pytest.raises(UserError,match='audio distortion'):
        distortion_audio.filter_expression(value)


def test_audio_distortion_is_opt_in_and_applied_only_in_final_encode(tmp_path,media_engines,monkeypatch):
    import json
    from dragshift import distortion,distortion_audio
    source=tmp_path/'sound.mp4'
    video.capture([video.executable('ffmpeg'),'-v','error','-f','lavfi','-i',
        'testsrc2=size=96x64:rate=10:duration=1.2','-f','lavfi','-i',
        'sine=frequency=997:duration=1.2','-c:v','libx264','-c:a','aac','-y',str(source)])
    calls=[]
    run=video.run_process
    def record(args,*rest,**kwargs):
        calls.append(args)
        return run(args,*rest,**kwargs)
    monkeypatch.setattr(video,'run_process',record)
    dry=distortion.export(source,strength=0,start=.2,end=.8,target='MP4')[0]
    assert not any('-af' in args for args in calls)
    calls.clear()
    wet=distortion.export(source,strength=0,audio_strength=80,start=.2,end=.8,target='MP4')[0]
    filtered=[args for args in calls if '-af' in args]
    assert len(filtered)==1 and filtered[0][-1].endswith('.mp4')
    assert filtered[0][filtered[0].index('-af')+1]==distortion_audio.filter_expression(80)
    assert video.probe(wet).has_audio
    assert video.probe(wet).duration==pytest.approx(.6,abs=.002)
    details=json.loads(video.capture([video.executable('ffprobe'),'-v','error','-count_frames',
        '-show_streams','-of','json',str(wet)]))
    streams={stream['codec_type']:stream for stream in details['streams']}
    assert int(streams['video']['nb_read_frames'])==6
    assert float(streams['audio']['duration'])==pytest.approx(.6,abs=.002)
    def samples(path):
        return np.frombuffer(video.capture([video.executable('ffmpeg'),'-v','error','-i',str(path),
            '-map','0:a:0','-f','f32le','-c:a','pcm_f32le','pipe:1']),dtype='<f4')
    a,b=samples(dry),samples(wet)
    assert a.shape==b.shape and np.sqrt(np.mean((a-b)**2))>.005
    muted=distortion.export(source,strength=0,audio_strength=100,keep_audio=False,target='WEBM')[0]
    assert not video.probe(muted).has_audio


def test_audio_controls_tolerate_silent_video_and_validate_even_png(tmp_path,media_engines):
    from PIL import Image
    from dragshift import distortion
    source=tmp_path/'silent.mp4'
    video.capture([video.executable('ffmpeg'),'-v','error','-f','lavfi','-i',
        'testsrc2=size=96x64:rate=10:duration=0.4','-c:v','libx264','-y',str(source)])
    result=distortion.export(source,strength=0,audio_strength=100,target='MP4')[0]
    assert not video.probe(result).has_audio
    assert video.probe(result).duration==pytest.approx(.4,abs=.002)
    with pytest.raises(UserError,match='audio distortion'):
        distortion.export(source,target='PNG',audio_strength=101)
    image=tmp_path/'still.png'
    Image.new('RGB',(96,64),'red').save(image)
    assert distortion.export(image,strength=0,audio_strength=40,target='PNG')[0].is_file()
