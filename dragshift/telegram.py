"""Export Telegram custom emoji as a static WebP or VP9 video.

Official requirements: https://core.telegram.org/stickers/webm-vp9-encoding
100×100, WebM/VP9, no audio stream, at most 3 seconds / 30 fps / 256 KB.
"""
import json
import math

from . import video
from .util import UserError

MAX_BYTES=256_000


def emoji_format(kind, suffix, animated=False):
    if kind == 'video' or kind == 'image' and suffix.lower().lstrip('.') == 'gif':
        return 'WEBM'
    if kind == 'image' and not animated:
        return 'WEBP'
    return None


def square_box(size, framing):
    """Map relative position and side length to an in-bounds pixel square."""
    horizontal, vertical, fraction = framing
    if (not all(math.isfinite(value) for value in framing)
            or not 0 <= horizontal <= 1 or not 0 <= vertical <= 1
            or not 0 < fraction <= 1):
        raise UserError('Choose a square inside the image.')
    width, height = size
    side = max(1, round(min(size) * fraction))
    left = round((width - side) * horizontal)
    top = round((height - side) * vertical)
    return left, top, left + side, top + side


def export_static_emoji(src, framing=(.5, .5, 1.)):
    from PIL.Image import Resampling
    from .animation import is_animated
    from .convert import open_image

    video.check_cancel()
    if is_animated(src):
        raise UserError('Choose a still image for a static Telegram emoji.')
    with open_image(src) as image:
        box = square_box(image.size, framing)
        emoji = image.crop(box).convert('RGBA').resize((100, 100), Resampling.LANCZOS)
    with video.export_path(src, 'Telegram emoji', '.webp') as (temporary, outputs):
        emoji.save(temporary, 'WEBP', lossless=True)
    return outputs


def validate_export(path):
    info=video.probe(path)
    data=json.loads(video.capture([video.executable('ffprobe'),'-v','error','-show_streams','-of','json',str(path)]))
    if ((info.width,info.height)!=(100,100) or info.codec!='vp9' or info.has_audio
            or info.duration>3.001 or info.fps>30.001 or path.stat().st_size>MAX_BYTES
            or any(s.get('codec_type')!='video' for s in data.get('streams',[]))):
        raise UserError('The encoded file did not meet Telegram emoji requirements. Try a shorter segment.')
    return info


def export_emoji(src, *, start=0., duration=None, fit='fit'):
    info=video.probe(src)
    duration=min(3.,info.duration-start) if duration is None else duration
    if (not all(math.isfinite(v) for v in (start,duration)) or not 0<duration<=3
            or start<0 or start+duration>info.duration+.001 or fit not in ('fit','crop')):
        raise UserError('Choose a segment within the source, no longer than 3 seconds.')
    source=video.local_file(src)
    decoder=['-c:v','libvpx-vp9'] if source.suffix.lower()=='.webm' and info.codec=='vp9' else []
    vf=video.square_pixels_filter()+',fps=30,format=rgba,'
    if fit=='crop':
        vf+='scale=100:100:force_original_aspect_ratio=increase:flags=lanczos,crop=100:100'
    else:
        vf+='scale=100:100:force_original_aspect_ratio=decrease:flags=lanczos,format=rgba,'
        vf+='pad=100:100:(ow-iw)/2:(oh-ih)/2:color=0x00000000'
    vf+=',setsar=1,format=yuva420p'
    with video.export_path(src,'Telegram emoji','.webm') as (tmp,outs):
        for attempt,quality in enumerate((32,42,52,63)):
            args=video.ffmpeg_args()+['-ss',str(start),*video.input_options(source),*decoder,'-i',str(source),'-t',str(duration),
                '-map',f'0:{info.video_index}','-an','-sn','-dn','-map_metadata','-1','-map_chapters','-1',
                '-vf',vf,'-c:v','libvpx-vp9','-pix_fmt','yuva420p','-b:v','0','-crf',str(quality),
                '-deadline','good','-cpu-used','4','-auto-alt-ref','0','-threads','4',str(tmp)]
            video.run_process(args,duration,'Encoding Telegram emoji…',attempt/4,1/4)
            if tmp.stat().st_size<=MAX_BYTES:
                validate_export(tmp)
                break
        else:
            raise UserError('This segment could not fit within 256 KB. Choose a shorter segment.')
    return outs
