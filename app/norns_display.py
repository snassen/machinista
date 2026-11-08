"""Draw NORNS mode on the MK3 displays (runs in the renderer process).

Each side shows one norns framebuffer scaled 3x (384x192) with the norns
key labels above (under the display buttons) and encoder labels below
(above the knobs). A frame that is missing or only partly written keeps
the last good image for that side.
"""
from PIL import Image
from app.mk3_graphics import Canvas, PANEL, INK, MUTED, ACCENT, LINE

SCALE = 3
FRAME_X, FRAME_Y = 48, 40
_cache = {}


def _frame(side):
    key = side['frame']
    mtime = side.get('mtime')
    cached = _cache.get(key)
    if mtime is None:
        return None
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        with Image.open(key) as source:
            source.load()
            image = source.convert('L').resize((128 * SCALE, 64 * SCALE), Image.NEAREST).convert('RGB')
    except (OSError, ValueError):
        return cached[1] if cached else None
    _cache[key] = (mtime, image)
    return image


def _side(side):
    c = Canvas()
    if side.get('name') is None:
        # The selected Sound has no Norns Instrument (left) or Norns Effect (right).
        c.text(240, 120, 'NO NORNS ' + side.get('role', ''), 16, True, MUTED, width=440, center=True)
        return c.image
    labels = ('K1', 'K2', 'K3', '')
    for i, label in enumerate(labels):
        c.rect(i * 120 + 3, 3, 114, 24, PANEL, radius=3)
        c.text(i * 120 + 60, 6, label, 12, True, INK, width=106, center=True)
    c.rect(FRAME_X - 4, FRAME_Y - 4, 128 * SCALE + 8, 64 * SCALE + 8, None, LINE, 3)
    image = _frame(side)
    if image is None:
        c.text(240, 120, 'NORNS ' + side['name'] + ' OFFLINE', 16, True, MUTED, width=380, center=True)
    else:
        c.image.paste(image, (FRAME_X, FRAME_Y))
    for i, label in enumerate(('E1', 'E2', 'E3', '')):
        if label:
            c.text(i * 120 + 60, 244, label, 12, True, MUTED, width=106, center=True)
    role = {'INSTRUMENT': 'INSTR', 'EFFECT': 'EFFECT'}.get(side.get('role'), 'NORNS')
    c.text(3 * 120 + 60, 244, role + ' ' + side['name'], 12, True, ACCENT, width=106, center=True)
    return c.image


def images(state):
    sides = tuple(state.get('norns', ()))
    while len(sides) < 2:
        sides += ({'name': None, 'role': ('INSTRUMENT', 'EFFECT')[len(sides)], 'frame': '', 'mtime': None},)
    return _side(sides[0]), _side(sides[1])
