"""Frame-aware image exports. Pillow composites GIF disposal before each edit."""
from pathlib import Path

from PIL import Image, ImageOps

from .util import UserError, sibling

ANIMATED_TARGETS = {'GIF', 'WEBP', 'PNG', 'TIFF', 'AVIF'}


def is_animated(src):
    with Image.open(src) as image:
        return getattr(image, 'is_animated', False)


def transform_image(src, label, transform=lambda image: image, *, target=None, quality=90):
    from .convert import PIL_FORMAT, atomic_save, open_image, save_image
    from .video import check_cancel

    target = (target or Path(src).suffix[1:]).upper()
    target = {'JPEG': 'JPG', 'TIF': 'TIFF', 'HEIF': 'HEIC'}.get(target, target)
    out = sibling(src, label, '.' + target.lower())
    with Image.open(src) as source:
        animated = getattr(source, 'is_animated', False) and target in ANIMATED_TARGETS
        if not animated:
            save_image(transform(open_image(src)), out, target, quality=quality)
            return out
        frames, durations = [], []
        loop = source.info.get('loop')
        pixels = 0
        for i in range(source.n_frames):
            check_cancel()
            source.seek(i)
            # seek sequentially so disposal/partial frame rectangles are composited.
            frame = transform(ImageOps.exif_transpose(source.convert('RGBA')))
            pixels += frame.width * frame.height
            if pixels > 250_000_000:
                raise UserError('This animation is too large for image editing. Convert it to video first.')
            frames.append(frame)
            durations.append(max(10, int(source.info.get('duration', 100))))
    options = dict(save_all=True, append_images=frames[1:], duration=durations)
    if loop is not None:
        options['loop'] = loop
    if target == 'GIF':
        # Full RGBA frames + restore-background disposal preserve transparent holes.
        options.update(disposal=2, optimize=False)
    elif target == 'WEBP':
        options.update(quality=quality, method=4)
    atomic_save(lambda dst: frames[0].save(dst, PIL_FORMAT[target], **options), out)
    return out
