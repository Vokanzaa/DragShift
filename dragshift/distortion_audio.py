"""A synchronized audio effect for Distort, applied during its final encode.

Pitch follows a smooth source-time wave scaled by the visual effect envelope.
No intermediate audio file or additional media pass is needed. The public
OpenDistortBot sources describe image processing, so this is not presented as
an exact reproduction of the hosted bot's unpublished audio implementation.
"""
import math

from .util import UserError


# A moderate audible default in the UI. Programmatic video export defaults to
# zero so existing callers retain their original audio until they opt in.
DEFAULT_STRENGTH=40


def validate_strength(value):
    """Return an integer percentage, rejecting malformed export settings."""
    try:
        number=float(value)
    except (TypeError,ValueError,OverflowError):
        number=math.nan
    if isinstance(value,bool) or not math.isfinite(number) or not 0<=number<=100 or number!=int(number):
        raise UserError('Choose an audio distortion intensity from 0 to 100.')
    return int(number)


def pitch_at(strength, at, *, curve=None, duration=1.):
    """A deterministic pitch ratio; cuts keep their original source-time phase."""
    strength=validate_strength(strength)
    level=1.
    if curve is not None:
        from .distortion import strength_at
        level=strength_at(curve,at,duration)/95
    wave=.72*math.sin(2*math.pi*.75*at)+.28*math.sin(2*math.pi*1.9*at)
    semitones=12*(strength/100)**1.5*level*wave
    return 2**(semitones/12)


def filter_expression(strength):
    """Fixed safe graph; its numeric pitch commands live in the job's cwd."""
    if not validate_strength(strength):
        return ''
    return ("asetpts=PTS-STARTPTS,asendcmd=f=audio-pitch.cmd,"
            'rubberband@bend=tempo=1:pitch=1:channels=together,'
            'asoftclip=type=hard:threshold=0.95:output=1')


def prepare_filter(folder, strength, *, start=0., length, duration, curve=None):
    """Prepare bounded numeric automation in the existing private render folder."""
    from pathlib import Path
    from .distortion import validate_curve
    strength=validate_strength(strength)
    curve=validate_curve(curve)
    if (not all(math.isfinite(v) for v in (start,length,duration))
            or start<0 or length<=0 or duration<=0):
        raise UserError('Choose a valid audio distortion interval.')
    if not strength or (curve is not None and not any(y for _,y in curve)):
        return ''
    count=min(50_000,max(1,math.ceil(length/.04)))
    with (Path(folder)/'audio-pitch.cmd').open('w',encoding='ascii',newline='\n') as stream:
        for index in range(count):
            at=index*length/count
            ratio=pitch_at(strength,start+at,curve=curve,duration=duration)
            stream.write(f'{at:.8f} rubberband@bend pitch {ratio:.8f};\n')
    # Keep the exact selected sample interval even for a final partial block.
    return filter_expression(strength)+f',apad,atrim=duration={length:.8f}'
