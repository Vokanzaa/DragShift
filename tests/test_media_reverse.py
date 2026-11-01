import json
import threading

import numpy as np
from PIL import Image
import pytest

from dragshift import video


@pytest.mark.parametrize('suffix',['gif','webp','png'])
def test_reverse_animation_keeps_frame_colours_durations_loop_and_original(tmp_path,suffix):
    from dragshift import media_reverse
    source=tmp_path/('frames.'+suffix)
    frames=[Image.new('RGBA',(24,20),colour) for colour in ('red','blue','green')]
    frames[0].save(source,save_all=True,append_images=frames[1:],duration=[70,120,250],loop=2,
                   **({'lossless':True} if suffix=='webp' else {}))
    before=source.read_bytes()
    output=media_reverse.reverse(source)[0]
    assert output.suffix==source.suffix
    with Image.open(output) as image:
        assert image.n_frames==3 and image.info.get('loop')==2
        colours=[];delays=[]
        for index in range(image.n_frames):
            image.seek(index);frame=image.convert('RGBA')
            colours.append(frame.getpixel((10,10))[:3]);delays.append(round(image.info['duration']))
    assert colours==[(0,128,0),(0,0,255),(255,0,0)]
    assert delays==[250,120,70]
    assert before==source.read_bytes()


def frame_info(path):
    data=json.loads(video.capture([video.executable('ffprobe'),'-v','error','-select_streams','v:0',
        '-show_frames','-show_entries','frame=best_effort_timestamp_time,duration_time','-of','json',str(path)]))
    frames=data['frames']
    pts=[float(frame['best_effort_timestamp_time']) for frame in frames]
    return pts,[float(frame.get('duration_time',0)) for frame in frames]


def test_apng_reverse_keeps_sub_centisecond_delays(tmp_path):
    from dragshift import media_reverse
    source=tmp_path/'quick.png'
    Image.new('RGBA',(24,20),'red').save(source,save_all=True,
        append_images=[Image.new('RGBA',(24,20),'blue')],duration=[2.5,7.5],loop=0)
    output=media_reverse.reverse(source)[0]
    with Image.open(output) as image:
        assert image.info['duration']==pytest.approx(7.5)
        image.seek(1);assert image.info['duration']==pytest.approx(2.5)


def test_reverse_variable_frame_durations_and_audio_in_video(tmp_path,media_engines):
    from dragshift import media_reverse
    for index,colour in enumerate(('red','blue','green')):Image.new('RGB',(96,64),colour).save(tmp_path/f'{index}.png')
    manifest=tmp_path/'frames.ffconcat'
    manifest.write_text("ffconcat version 1.0\nfile '0.png'\noption framerate 1000000\nduration 0.07\nfile '1.png'\noption framerate 1000000\nduration 0.12\nfile '2.png'\noption framerate 1000000\nduration 0.25\nfile '2.png'\noption framerate 1000000\n",encoding='ascii')
    source=tmp_path/'variable.mp4'
    video.capture(video.ffmpeg_args()+['-f','concat','-safe','0','-i',str(manifest),'-f','lavfi','-i',
        'aevalsrc=0.5*t:s=48000:d=0.44','-t','0.44','-fps_mode','passthrough','-enc_time_base:v','1:1000000',
        '-c:v','libx264','-bf','0','-pix_fmt','yuv420p','-c:a','aac',
        '-bsf:v',"setts=duration='if(eq(N,0),70000,if(eq(N,1),120000,250000))'",str(source)])
    assert frame_info(source)[1]==pytest.approx([.07,.12,.25],abs=.002)
    output=media_reverse.reverse(source)[0]
    pts,durations=frame_info(output)
    assert pts==pytest.approx([0,.25,.37],abs=.002)
    assert durations==pytest.approx([.25,.12,.07],abs=.002)
    assert video.probe(output).duration==pytest.approx(.44,abs=.002)
    decoded=video.capture([video.executable('ffmpeg'),'-v','error','-i',str(output),'-map','0:v:0',
        '-fps_mode','passthrough','-f','rawvideo','-pix_fmt','rgb24','pipe:1'])
    frames=np.frombuffer(decoded,dtype=np.uint8).reshape(3,64,96,3)
    for frame,wanted in zip(frames,((0,128,0),(0,0,255),(255,0,0))):
        actual=frame[10,10].astype(float)
        assert np.max(np.abs(actual-np.array(wanted)))<10
    def samples(path):
        return np.frombuffer(video.capture([video.executable('ffmpeg'),'-v','error','-i',str(path),
            '-map','0:a:0','-f','f32le','pipe:1']),dtype='<f4')
    dry,wet=samples(source),samples(output)
    assert len(dry)==len(wet)
    assert np.mean(wet[:2000])>np.mean(wet[-2000:])+.1


def test_reverse_cancellation_leaves_only_sources(tmp_path,media_engines):
    from dragshift import media_reverse
    source=tmp_path/'source.mp4'
    video.capture(video.ffmpeg_args()+['-f','lavfi','-i','testsrc2=size=160x120:rate=30:duration=1',
        '-c:v','libx264',str(source)])
    before=set(tmp_path.iterdir());cancel=threading.Event()
    with video.job_context(video.Control(cancel=cancel,progress=lambda value,message:cancel.set() if value>.05 else None)):
        with pytest.raises(video.Cancelled):media_reverse.reverse(source)
    assert set(tmp_path.iterdir())==before


@pytest.mark.parametrize('rate',['24','30000/1001','60'])
def test_constant_rate_reverse_preserves_every_frame(tmp_path,media_engines,rate):
    from dragshift import media_reverse
    source=tmp_path/'constant.mp4'
    video.capture(video.ffmpeg_args()+['-f','lavfi','-i',f'testsrc2=size=160x120:rate={rate}',
        '-frames:v','40','-c:v','libx264','-pix_fmt','yuv420p',str(source)])
    output=media_reverse.reverse(source)[0]
    def pixels(path):
        data=video.capture([video.executable('ffmpeg'),'-v','error','-i',str(path),'-map','0:v:0',
            '-fps_mode','passthrough','-f','rawvideo','-pix_fmt','rgb24','pipe:1'])
        return np.frombuffer(data,dtype=np.uint8).reshape(-1,120,160,3).astype(float)
    a,b=pixels(source),pixels(output)
    assert len(a)==len(b)==40
    assert np.mean(np.abs(a[::-1]-b))<8
    assert video.probe(output).duration==pytest.approx(video.probe(source).duration,abs=.002)


def test_reverse_action_is_exposed_and_routes_directly_to_background_work(tmp_path):
    from dragshift.app import DragShiftApp
    from dragshift.radial import Item
    source=tmp_path/'animation.gif'
    Image.new('RGB',(12,10),'red').save(source,save_all=True,
        append_images=[Image.new('RGB',(12,10),'blue')],duration=[80,170])
    rings=DragShiftApp.build_rings(None,[str(source)])
    assert 'tool:Reverse' in {item.key for item in rings['Tools']}
    calls=[]
    class App:
        submit=lambda self,*args:calls.append(args)
    DragShiftApp.run_item(App(),Item('Reverse',key='tool:Reverse'),[str(source)])
    assert calls[0][0]=='tool:Reverse'
    output=calls[0][2]()[0]
    with Image.open(output) as image:assert image.convert('RGB').getpixel((0,0))==(0,0,255)
