"""A synchronized audio effect for Distort, applied during its final encode.

The bit reduction and sample hold reuse the app's digital audio glitch sound.
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


def filter_expression(strength):
    """Return the in-encode audio filter, or no filter for completely dry sound.

    acrusher blends sample hold / bit crushing with the original samples.
    Hard clipping bounds wet output peaks without lookahead or filter latency;
    silence, channel count, sample rate and sample count remain unchanged.
    """
    strength=validate_strength(strength)
    if not strength:
        return ''
    return (f'acrusher=bits=4:samples=16:aa=0:mix={strength/100:.8f},'
            'asoftclip=type=hard:threshold=0.95:output=1')
