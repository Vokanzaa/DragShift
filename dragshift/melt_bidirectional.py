"""Experimental forward/reverse Melt, handing off only corrupted macroblocks.

No clean-video dissolve: a binary mask selects one of two real FFglitch results.
Reversals operate on bounded local chunks, never a whole timeline in RAM.
"""
from contextlib import contextmanager
from pathlib import Path
import tempfile

from . import video
from .util import UserError

REVERSE_MEMORY = 96 * 1024 * 1024


@contextmanager
def _progress(offset, span):
    parent=video._control.get()
    if parent is None:
        yield
    else:
        control=video.Control(cancel=parent.cancel,
            progress=lambda value,message:parent.progress(offset+span*value,message))
        with video.job_context(control):
            yield


def reverse_range(source, start, count, *, fps, width, height, folder, name):
    """Lossless, bounded frame reversal of one selected local excerpt."""
    folder=Path(folder)
    per_chunk=max(1,REVERSE_MEMORY//(width*height*4))
    parts=[]
    end=count
    while end:
        video.check_cancel()
        begin=max(0,end-per_chunk)
        length=end-begin
        part=folder/f'{name}-{len(parts):05d}.mkv'
        vf=(video.square_pixels_filter()+f',fps={fps},'
            f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
            f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p,'
            f'tpad=stop_mode=clone:stop_duration=0.2,trim=end_frame={length},reverse,setpts=N/({fps}*TB)')
        args=video.ffmpeg_args()+['-ss',f'{start+begin/fps:.10f}',
            *video.input_options(source),'-i',str(video.local_file(source)),
            '-map','0:v:0','-an','-vf',vf,'-frames:v',str(length),'-c:v','ffv1',
            '-threads','2',str(part)]
        video.run_process(args,length/fps,'Preparing reverse Melt excerpt…',parse_progress=True)
        parts.append(part)
        end=begin
    manifest=folder/f'{name}.ffconcat'
    manifest.write_text('ffconcat version 1.0\n'+''.join(f"file '{part.name}'\n" for part in parts),encoding='ascii')
    result=folder/f'{name}.mkv'
    video.run_process(video.ffmpeg_args()+['-f','concat','-safe','0','-i',str(manifest),
        '-map','0:v:0','-an','-c:v','copy',str(result)],count/fps,'Joining reverse excerpt…')
    return result


def _mask(width,height,fps,count):
    duration=count/fps
    rank='mod(floor(X/16)*37+floor(Y/16)*73+floor(X/16)*floor(Y/16)*11,101)/101'
    phase=f'clip((T/{duration:.10f}-.1)/.8,0,1)'
    value=f'if(lte(T,0),0,if(gte(T,{(count-1)/fps:.10f}),255,if(lt({rank},{phase}),255,0)))'
    return f"nullsrc=s={width}x{height}:r={fps}:d={duration:.10f},format=gray,geq=lum='{value}'[mask]"


def render(timeline, *, max_side=720, fps=30, audio=True, directory=None):
    from .melt_timeline import Timeline, render as classic_render
    counts=timeline.validate(fps)
    first=video.probe(timeline.clips[0].path)
    scale=min(1.,max_side/max(first.display_width,first.display_height))
    width,height=[max(2,round(side*scale/2)*2) for side in (first.display_width,first.display_height)]
    boundaries=[]
    position=0
    for index,count in enumerate(counts[:-1]):
        position+=count
        cut=timeline.cut(index)
        if cut.enabled and cut.smooth:
            boundaries.append((index,position,round(cut.lead*fps),round(cut.duration*fps)))
    total=sum(counts)
    with video.export_path(timeline.clips[0].path,'Datamosh Melt',directory=directory) as (output,outs):
        with tempfile.TemporaryDirectory(prefix='.~melt-two-way-',dir=output.parent) as temporary:
            folder=Path(temporary)
            # Reverse scratch space is lossless; reject early rather than fill
            # a disk half way through a long/high-resolution transition.
            import shutil
            estimate=sum((lead+recovery+2*max(3,round(.25*fps)))*width*height*6
                         for _,_,lead,recovery in boundaries)+100_000_000
            if shutil.disk_usage(folder).free<estimate:
                raise UserError('Not enough space for reverse Melt. Shorten the effect or reduce its resolution.')
            base_model=timeline.snapshot()
            for index in range(len(base_model.clips)-1):base_model.cut(index).smooth=False
            with _progress(0,.4):
                base=classic_render(base_model,max_side=max_side,fps=fps,audio=audio,directory=folder)[0]
            replacements=[]
            for serial,(index,boundary,lead,recovery) in enumerate(boundaries):
                part_folder=folder/f'cut-{serial:02d}'
                part_folder.mkdir()
                left,right=timeline.clips[index:index+2]
                pad=max(3,round(.25*fps))
                left_count=min(counts[index],lead+pad)
                right_count=min(counts[index+1],recovery+pad)
                with _progress(.4+.45*serial/len(boundaries),.45/len(boundaries)):
                    rev_b=reverse_range(right.path,right.start,right_count,fps=fps,width=width,height=height,folder=part_folder,name='reverse-b')
                    rev_a=reverse_range(left.path,left.end-left_count/fps,left_count,fps=fps,width=width,height=height,folder=part_folder,name='reverse-a')
                    reverse_model=Timeline()
                    reverse_model.add(rev_b,right_count/fps)
                    reverse_model.add(rev_a,left_count/fps)
                    reverse_cut=reverse_model.cut(0)
                    reverse_cut.duration=lead/fps
                    reverse_cut.lead=recovery/fps
                    reverse_cut.strength=timeline.cut(index).strength
                    backward=classic_render(reverse_model,max_side=max_side,fps=fps,audio=False,directory=part_folder)[0]
                    restored=reverse_range(backward,0,left_count+right_count,fps=fps,width=width,height=height,folder=part_folder,name='restored')
                    count=lead+recovery
                    segment=part_folder/'handoff.mkv'
                    graph=(f'[0:v]trim=start_frame={boundary-lead}:end_frame={boundary+recovery},setpts=N/({fps}*TB)[forward];'
                           f'[1:v]trim=start_frame={left_count-lead}:end_frame={left_count+recovery},setpts=N/({fps}*TB)[backward];'
                           +_mask(width,height,fps,count)+';[forward][backward][mask]maskedmerge,format=yuv420p[v]')
                    video.run_process(video.ffmpeg_args()+['-i',str(base),'-i',str(restored),
                        '-filter_complex_threads','2','-filter_complex',graph,'-map','[v]','-an',
                        '-frames:v',str(count),'-c:v','ffv1','-threads','2',str(segment)],count/fps,'Combining forward and reverse Melt…')
                    replacements.append((boundary-lead,boundary+recovery,segment))
            inputs=['-i',str(base)]
            for _,_,path in replacements:inputs+=['-i',str(path)]
            graph=[];labels=[];position=0
            for index,(begin,end,_) in enumerate(replacements):
                if begin>position:
                    label=f'clean{index}'
                    graph.append(f'[0:v]trim=start_frame={position}:end_frame={begin},setpts=N/({fps}*TB)[{label}]')
                    labels.append(f'[{label}]')
                label=f'melt{index}'
                graph.append(f'[{index+1}:v]trim=end_frame={end-begin},setpts=N/({fps}*TB)[{label}]')
                labels.append(f'[{label}]')
                position=end
            if position<total:
                graph.append(f'[0:v]trim=start_frame={position}:end_frame={total},setpts=N/({fps}*TB)[tail]')
                labels.append('[tail]')
            graph.append(''.join(labels)+f'concat=n={len(labels)}:v=1:a=0[v]')
            args=video.ffmpeg_args()+inputs+['-filter_complex_threads','2','-filter_complex',';'.join(graph),'-map','[v]']
            args+=['-map','0:a:0?'] if audio else ['-an']
            args+=video._video_codec('MP4')+['-c:a','copy','-t',str(total/fps),str(output)]
            with _progress(.85,.15):
                video.run_process(args,total/fps,'Exporting smooth Melt…')
    return outs
