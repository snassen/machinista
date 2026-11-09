"""Static, cached monochrome branding; no I/O or image work in the audio loop."""
import base64
import time
import zlib
from functools import lru_cache
from app.branding_bitmaps import BITMAPS

NAME = 'Machinista'
VERSION = '0.1.0-beta.19'

@lru_cache(maxsize=2)
def logo_mask(width):
    height, encoded = BITMAPS[width]
    return height, zlib.decompress(base64.b85decode(encoded))

def paint_logo(pixels, screen_width, x, y, width):
    """Draw only the approved ink; all former white shapes remain cutouts."""
    height, mask = logo_mask(width)
    ink = 0 if screen_width == 128 else 1
    for yy in range(height):
        for xx in range(width):
            if mask[yy*width+xx] and 0 < x+xx < screen_width-1 and 0 < y+yy < 63:
                pixels[(y+yy)*screen_width+x+xx] = ink

@lru_cache(maxsize=2)
def boot_frame(width):
    from app.fokus import Canvas
    c = Canvas(width)
    size = 120 if width == 128 else 236
    height, _ = logo_mask(size)
    paint_logo(c.p, width, (width-size)//2, (64-height)//2-4, size)
    c.text(2, 51, 'STARTING', width-4, center=width//2)
    return bytes(c.finish())

class BootSplash:
    """A view-only deadline. Input dismisses it; no sleeps or engine changes."""
    def __init__(self):
        self.until = None

    def start(self, now=None):
        self.until = (time.monotonic() if now is None else now) + 2.0

    def active(self, now=None):
        return self.until is not None and (time.monotonic() if now is None else now) < self.until

    def dismiss(self):
        self.until = None

    def expired(self, now):
        if self.until is not None and now >= self.until:
            self.dismiss()
            return True
        return False
