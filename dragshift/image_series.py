"""Shared image settings on complete selections, with proportional geometry."""
import math
from PIL import Image
from . import video


def oriented_size(path):
    with Image.open(path) as image:
        size=image.size
        return size[::-1] if image.getexif().get(0x0112,1) in (5,6,7,8) else size


def apply(paths,operation):
    """Publish a complete series or roll back new results on error/cancel."""
    def one(path):
        result=operation(path)
        return [result]
    return video.batch(list(paths),one)


def crop_box(box,reference,size,ratio=None):
    if size==reference:
        return box
    rw,rh=reference
    width,height=size
    left,top,right,bottom=box
    cx=(left+right)/2/rw*width
    cy=(top+bottom)/2/rh*height
    w=(right-left)/rw*width
    h=(bottom-top)/rh*height
    if ratio:
        w=min(w,h*ratio)
        h=w/ratio
    w=max(1,min(width,round(w)))
    h=max(1,min(height,round(h)))
    x=max(0,min(width-w,round(cx-w/2)))
    y=max(0,min(height-h,round(cy-h/2)))
    return x,y,x+w,y+h


def region(box,reference,size):
    """Cover the entire proportional redaction region, including edge pixels."""
    if size==reference:
        return box
    rw,rh=reference
    w,h=size
    left,top,right,bottom=box
    x=max(0,min(w-1,math.floor(left/rw*w)))
    y=max(0,min(h-1,math.floor(top/rh*h)))
    return x,y,max(x+1,min(w,math.ceil(right/rw*w))),max(y+1,min(h,math.ceil(bottom/rh*h)))
