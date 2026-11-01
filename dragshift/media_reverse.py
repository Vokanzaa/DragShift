"""One-action frame reversal: preserve animation delays and video/audio order."""
import json
import math
from pathlib import Path
import shutil
import tempfile

import numpy as np

from . import animation,audio,video
from .util import UserError,category


def _timings(src,info,folder):
    output=Path(folder)/'timing.json'
    video.run_process([video.executable('ffprobe'),'-v','error','-select_streams',str(info.video_index),
        '-show_frames','-show_entries','frame=best_effort_timestamp_time,duration_time,pkt_duration_time',
        '-of','json','-o',str(output),str(video.local_file(src))],
        message='Reading frame timing…',offset=0,span=.05,parse_progress=False)
    frames=json.loads(output.read_text(encoding='utf-8'))['frames']
    if not frames:raise UserError('This file has no readable animation frames.')
    try:
        pts=[float(frame['best_effort_timestamp_time']) for frame in frames]
        durations=[b-a for a,b in zip(pts,pts[1:])]
        last=float(frames[-1].get('duration_time',frames[-1].get('pkt_duration_time',0)))
        durations.append(last if last>0 else 1/info.fps)
        if not all(math.isfinite(v) and v>0 for v in durations):raise ValueError
    except (KeyError,ValueError,TypeError,ZeroDivisionError):
        raise UserError('The frame timing is invalid. Convert this file before reversing it.') from None
    return durations


def _reverse_audio(src,folder,duration):
    info=audio.probe(src)
    channels=info.channels
    raw=Path(folder)/'audio.raw'
    output=Path(folder)/'audio-reversed.raw'
    video.run_process(video.ffmpeg_args()+['-i',str(video.local_file(src)),'-map','0:a:0','-vn',
        '-af',f'aresample=48000,apad,atrim=duration={duration:.10f}',
        '-ar','48000','-ac',str(channels),'-c:a','pcm_f32le','-f','f32le',str(raw)],
        duration,'Preparing reversed audio…',.45,.1)
    frame_bytes=4*channels
    if raw.stat().st_size%frame_bytes:raise UserError('The audio decoder wrote an incomplete sample.')
    end=raw.stat().st_size//frame_bytes
    block=max(1,8*1024*1024//frame_bytes)
    with raw.open('rb') as source,output.open('xb') as target:
        while end:
            video.check_cancel()
            begin=max(0,end-block)
            source.seek(begin*frame_bytes)
            values=np.frombuffer(source.read((end-begin)*frame_bytes),dtype='<f4').reshape(-1,channels)
            target.write(values[::-1].tobytes())
            end=begin
    return output,channels


def reverse(src,*,directory=None,keep_audio=True):
    src=video.local_file(src)
    if category(src)=='image':
        if not animation.is_animated(src):
            raise UserError('This image has only one frame. Select an animated file.')
        return [animation.transform_image(src,'Reversed',reverse_frames=True)]
    if category(src)!='video':raise UserError('Select an animated image or a video to reverse.')
    info=video.probe(src)
    video.require_precise_timing()
    alpha=info.codec=='vp9' and str(info.tags.get('alpha_mode','0'))=='1'
    target='WEBM' if alpha else 'MP4'
    with video.export_path(src,'Reversed','.'+target.lower(),directory=directory) as (result,outs):
        with tempfile.TemporaryDirectory(prefix='.~reverse-',dir=result.parent) as temporary:
            folder=Path(temporary)
            durations=_timings(src,info,folder)
            total=sum(durations)
            width,height=[max(2,round(side/2)*2) for side in (info.display_width,info.display_height)]
            cfr=not alpha and max(durations)-min(durations)<max(.000003,total/len(durations)*.001)
            # Conservatively reserve lossless scratch space before decoding.
            estimate=width*height*len(durations)*(3 if cfr else 5)+100_000_000
            if info.has_audio and keep_audio:estimate+=round(total*48000*audio.probe(src).channels*8)
            if shutil.disk_usage(folder).free<estimate:
                raise UserError('Not enough temporary disk space to reverse this file. Free space or shorten it first.')
            if cfr:
                from .melt_bidirectional import reverse_range,_progress
                rate=len(durations)/total
                with _progress(.05,.4):
                    frames=reverse_range(src,0,len(durations),fps=rate,width=width,height=height,folder=folder,name='video')
                inputs=['-i',str(frames)]
                vf='null'
            else:
                decoder=['-c:v','libvpx-vp9'] if alpha else []
                video.run_process(video.ffmpeg_args()+decoder+['-i',str(src),'-map',f'0:{info.video_index}','-an',
                    '-vf',video.square_pixels_filter()+f',scale={width}:{height},format=rgba',
                    '-fps_mode','passthrough','-c:v','png','-threads','1','-compression_level','1',str(folder/'frame-%08d.png')],
                    total,'Decoding variable-duration frames…',.05,.4)
                paths=sorted(folder.glob('frame-*.png'))
                if len(paths)!=len(durations):raise UserError('The decoder did not preserve every frame. No reversed file was saved.')
                paths.reverse();durations.reverse()
                manifest=folder/'reversed.ffconcat'
                lines=['ffconcat version 1.0']
                for path,duration in zip(paths,durations):
                    lines.extend([f"file '{path.name}'",'option framerate 1000000',f'duration {duration:.10f}'])
                lines.extend([f"file '{paths[-1].name}'",'option framerate 1000000'])
                manifest.write_text('\n'.join(lines)+'\n',encoding='ascii')
                inputs=['-f','concat','-safe','0','-i',str(manifest)]
                vf='null'
            sound=None
            if info.has_audio and keep_audio:sound,channels=_reverse_audio(src,folder,total)
            args=video.ffmpeg_args()+inputs
            if sound:args+=['-f','f32le','-ar','48000','-ac',str(channels),'-i',str(sound)]
            args+=['-map','0:v:0','-vf',vf]
            args+=['-map','1:a:0'] if sound else ['-an']
            args+=['-fps_mode','passthrough','-enc_time_base:v','1:1000000']+video._video_codec(target)
            if alpha and target=='WEBM':args+=['-pix_fmt','yuva420p','-auto-alt-ref','0']
            args+=['-bf','0','-bsf:v',f"setts=duration='if(eq(N,{len(durations)-1}),{round(durations[-1]*1_000_000)},DURATION)'",
                '-t',f'{total:.10f}',str(result)]
            video.run_process(args,total,'Saving reversed frames…',.65,.35)
    return outs
