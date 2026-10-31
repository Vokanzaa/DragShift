"""Tester regressions: gentle low settings and pitch tied to video strengths."""
import math
import subprocess

import numpy as np
import pytest

from dragshift import distortion_audio, video


def test_pitch_moves_both_ways_and_scales_with_the_source_envelope():
    values=[distortion_audio.pitch_at(100,t/20) for t in range(100)]
    assert min(values)<.8 and max(values)>1.25
    assert max(abs(distortion_audio.pitch_at(1,t/20)-1) for t in range(100))<.002
    curve=[(0,0),(.4,0),(.6,95),(1,95)]
    assert distortion_audio.pitch_at(100,.5,curve=curve,duration=5)==1
    assert distortion_audio.pitch_at(100,3.5,curve=curve,duration=5)==pytest.approx(distortion_audio.pitch_at(100,3.5))


def samples(tmp_path,strength,*,curve=None,start=0,length=2.4,level=.001):
    folder=tmp_path/('filter-'+str(strength)+'-'+str(start));folder.mkdir()
    expression=distortion_audio.prepare_filter(folder,strength,start=start,length=length,
                                              duration=5,curve=curve)
    args=[video.executable('ffmpeg'),'-v','error','-f','lavfi','-i',
          f'aevalsrc={level}*sin(2*PI*997*t)|{level}*sin(2*PI*439*t):s=48000:d={length}']
    if expression:args+=['-af',expression]
    result=subprocess.run(args+['-f','f32le','-c:a','pcm_f32le','pipe:1'],cwd=folder,
                          capture_output=True,check=True,timeout=30,creationflags=video.CREATION_FLAGS)
    return np.frombuffer(result.stdout,dtype='<f4').reshape(-1,2)


def frequencies(channel):
    result=[]
    for left in np.arange(.4,2.,.12):
        segment=channel[round(left*48000):round((left+.08)*48000)]
        spectrum=np.abs(np.fft.rfft(segment*np.hanning(len(segment))))
        result.append(np.argmax(spectrum)*48000/len(segment))
    return np.array(result)


def test_one_percent_has_no_quantization_noise_floor_and_preserves_length(tmp_path,media_engines):
    output=samples(tmp_path,1)
    assert output.shape==(115200,2)
    assert np.isfinite(output).all()
    rms=np.sqrt(np.mean(output[12000:]**2))
    assert .0005<rms<.0008
    assert np.max(np.abs(output))<.0013
    assert np.max(np.abs(frequencies(output[:,0])-997))<25


def test_real_sound_bends_pitch_up_and_down_without_swapping_stereo(tmp_path,media_engines):
    output=samples(tmp_path,100,level=.4)
    assert output.shape==(115200,2)
    left,right=frequencies(output[:,0]),frequencies(output[:,1])
    assert left.min()<850 and left.max()>1150
    assert right.min()<390 and right.max()>500
    assert np.max(np.abs(output))<=.950001


def test_zero_envelope_bypasses_sound_and_commands_follow_trimmed_source_time(tmp_path,media_engines):
    assert distortion_audio.prepare_filter(tmp_path,100,start=1,length=1,duration=5,curve=[(0,0),(1,0)])==''
    expression=distortion_audio.prepare_filter(tmp_path,80,start=2,length=.4,duration=5,curve=[(0,0),(.4,0),(1,95)])
    assert 'acrusher' not in expression
    commands=(tmp_path/'audio-pitch.cmd').read_text(encoding='ascii').splitlines()
    for line in commands:
        at=float(line.split()[0]);pitch=float(line.split()[-1].rstrip(';'))
        assert pitch==pytest.approx(distortion_audio.pitch_at(80,2+at,curve=[(0,0),(.4,0),(1,95)],duration=5),abs=1e-7)
