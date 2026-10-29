"""Ordered image sequences, encoded one GIF frame at a time with Pillow."""
from dataclasses import dataclass
from pathlib import Path
import math
import re
import tempfile
import unicodedata

from PIL import GifImagePlugin, Image, ImageOps

from . import video
from .util import UserError, output_dir, sibling


def name_key(path):
    path=Path(path)
    name=unicodedata.normalize('NFC',path.name).casefold()
    parts=tuple((1,int(part)) if part.isdecimal() else (0,part)
                for part in re.split(r'(\d+)',name))
    return parts,name,path.as_posix().casefold(),path.as_posix()


def ordered_paths(paths,mode='name'):
    paths=list(map(Path,paths))
    if mode in ('manual','added'):
        return paths
    if mode=='name':
        return sorted(paths,key=name_key)
    if mode=='date':
        return sorted(paths,key=lambda p:(p.stat().st_mtime_ns,name_key(p)))
    raise ValueError('Unknown frame order')


@dataclass(frozen=True)
class FrameInfo:
    path: Path
    count: int
    size: tuple[int,int]


def inspect_frames(paths):
    infos=[]
    for path in map(Path,paths):
        video.check_cancel()
        with Image.open(path) as image:
            size=image.size[::-1] if image.getexif().get(274,1) in (5,6,7,8) else image.size
            count=image.n_frames if getattr(image,'is_animated',False) else 1
            if min(size)<1 or max(size)>65535 or size[0]*size[1]>100_000_000:
                raise UserError('A GIF frame must fit within 65535 pixels per side and 100 million pixels.')
            infos.append(FrameInfo(path,count,size))
    if not infos:
        raise UserError('Add images to create a GIF animation.')
    return infos


def number_notice(paths):
    """Inform about gaps/duplicate numbers; never invent or discard selected frames."""
    matches=[re.fullmatch(r'(.*?)(\d+)(\D*)',Path(p).stem) for p in paths]
    if len(matches)<2 or not all(matches):
        return ''
    if len({(m[1].casefold(),m[3].casefold()) for m in matches})!=1:
        return ''
    values=[int(m[2]) for m in matches]
    if len(set(values))!=len(values):
        return 'Some frame numbers repeat. Check the list; every selected entry will be kept.'
    values=sorted(values)
    if any(b-a>1 for a,b in zip(values,values[1:])):
        return 'Some frame numbers are missing. Only selected files will be animated.'
    return ''


def _palette(frame,size):
    if frame.size!=size:
        fitted=ImageOps.contain(frame,size,Image.Resampling.LANCZOS)
        canvas=Image.new('RGBA',size,(0,0,0,0))
        canvas.paste(fitted,((size[0]-fitted.width)//2,(size[1]-fitted.height)//2))
        frame=canvas
    # Reserve a fixed transparent index for every local palette. Disposal=2
    # then clears each full canvas, without carrying a previous frame's pixels.
    paletted=frame.convert('RGB').quantize(colors=255,method=Image.Quantize.MEDIANCUT)
    palette=paletted.getpalette() or []
    paletted.putpalette((palette+[0]*768)[:768])
    paletted.paste(255,mask=frame.getchannel('A').point(lambda a:255 if a<128 else 0))
    paletted.info.clear()
    paletted.info['transparency']=255
    return paletted


def export(paths,*,fps=10,loop=True):
    """Consume the supplied order exactly; publish one result after all frames."""
    paths=list(map(Path,paths))
    if not math.isfinite(fps) or not 1<=fps<=100:
        raise UserError('GIF frame rate must be between 1 and 100 fps.')
    infos=inspect_frames(paths)
    total=sum(info.count for info in infos)
    size=infos[0].size
    folder=output_dir(paths[0])
    video.progress(0,'Encoding GIF frames…')
    with tempfile.TemporaryDirectory(prefix='.~gif-',dir=folder) as temporary:
        staged=Path(temporary)/'animation.gif'
        index=0
        with staged.open('wb') as target:
            for info in infos:
                with Image.open(info.path) as source:
                    for number in range(info.count):
                        video.check_cancel()
                        source.seek(number)
                        frame=ImageOps.exif_transpose(source.convert('RGBA'))
                        paletted=_palette(frame,size)
                        if index==0:
                            header={'background':255,'transparency':255,'optimize':False}
                            if loop:header['loop']=0
                            for block in GifImagePlugin.getheader(paletted,info=header)[0]:
                                target.write(block)
                        delay=(round((index+1)*100/fps)-round(index*100/fps))*10
                        for block in GifImagePlugin.getdata(paletted,duration=delay,disposal=2,
                                transparency=255,include_color_table=index>0,optimize=False):
                            target.write(block)
                        index+=1
                        video.progress(.98*index/total,'Encoding GIF frames…')
            target.write(b';')
        with Image.open(staged) as check:
            if check.n_frames!=total or check.size!=size:
                raise UserError('The GIF frame count did not match the selected sequence.')
        with video._publish_lock:
            video.check_cancel()
            out=sibling(paths[0],'Animation','.gif')
            staged.replace(out)
    return [out]
