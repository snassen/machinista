"""Draw NORNS mode on the MK3 displays (runs in the renderer process).

Each side shows one norns framebuffer scaled 3x (384x192) with the norns
key labels above (under the display buttons) and encoder labels below
(above the knobs). On a MIDI layer the labels show the layer instead: the
toggle keys' CCs (lit while on) and the knobs' CCs with their values. A frame that is missing or only partly written keeps
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


def _tempo(c, tempo):
    # Machinista's TEMPO is selected: show the tempo in the free top slot.
    if tempo is not None:
        c.rect(3 * 120 + 3, 3, 114, 24, ACCENT, radius=3)
        c.text(3 * 120 + 60, 6, tempo + ' BPM', 12, True, PANEL, width=106, center=True)
    return c.image


def _loop(c, loop):
    # One-button loop recording (app/norns_loop.py) in the bottom-right slot:
    # outlined while waiting for the bar, filled while recording, plain for a
    # moment after the bars or tail changed.
    if not loop or not loop.get('show'):
        return False
    state = loop.get('state')
    if state == 'RECORDING':
        c.rect(3 * 120 + 3, 238, 114, 22, ACCENT, radius=3)
    elif state == 'WAITING':
        c.rect(3 * 120 + 3, 238, 114, 22, None, ACCENT, 3)
    c.text(3 * 120 + 60, 244, loop.get('text', ''), 12, True, PANEL if state == 'RECORDING' else ACCENT,
           width=106, center=True)
    return True


def _side(side, tempo=None, loop=None):
    c = Canvas()
    if side.get('name') is None:
        # The selected Sound has no Norns Instrument (left) or Norns Effect (right).
        c.text(240, 120, 'NO NORNS ' + side.get('role', ''), 16, True, MUTED, width=440, center=True)
        _loop(c, loop)
        return _tempo(c, tempo)
    layer = side.get('layer') or 0
    values = side.get('values') or ()
    first = side.get('first_cc')
    labels = side.get('labels') or ()

    def named(i, on):
        # The norns' name for this control, else its CC number.
        if len(labels) == 6:
            text = labels[i][1 if on else 0]
            if text:
                return text
        return None
    if layer and len(values) == 6 and first is not None:
        for i in range(3):
            on = values[i] > 0
            c.rect(i * 120 + 3, 3, 114, 24, ACCENT if on else PANEL, radius=3)
            text = named(i, on) or f'CC{first + i} ' + ('ON' if on else 'OFF')
            c.text(i * 120 + 60, 6, text, 12, True, PANEL if on else INK, width=106, center=True)
        c.rect(3 * 120 + 3, 3, 114, 24, None, ACCENT, 3)
        c.text(3 * 120 + 60, 6, f'MIDI {layer}', 12, True, ACCENT, width=106, center=True)
    else:
        for i, label in enumerate(('K1', 'K2', 'K3', 'NATIVE')):
            c.rect(i * 120 + 3, 3, 114, 24, PANEL, radius=3)
            c.text(i * 120 + 60, 6, label, 12, True, INK if i < 3 else MUTED, width=106, center=True)
    c.rect(FRAME_X - 4, FRAME_Y - 4, 128 * SCALE + 8, 64 * SCALE + 8, None, LINE, 3)
    image = _frame(side)
    if image is None:
        c.text(240, 120, 'NORNS ' + side['name'] + ' OFFLINE', 16, True, MUTED, width=380, center=True)
    else:
        c.image.paste(image, (FRAME_X, FRAME_Y))
    if layer and len(values) == 6 and first is not None:
        for i in range(3):
            value = values[3 + i]
            name = named(3 + i, False) or f'CC{first + 3 + i}'
            c.text(i * 120 + 60, 240, f'{name} {value}', 12, True, INK, width=106, center=True)
            c.rect(i * 120 + 13, 260, 94, 6, PANEL, radius=2)
            if value:
                c.rect(i * 120 + 13, 260, max(2, round(94 * value / 127)), 6, ACCENT, radius=2)
    else:
        for i, label in enumerate(('E1', 'E2', 'E3')):
            c.text(i * 120 + 60, 244, label, 12, True, MUTED, width=106, center=True)
    if not _loop(c, loop):
        role = {'INSTRUMENT': 'INSTR', 'EFFECT': 'EFFECT'}.get(side.get('role'), 'NORNS')
        c.text(3 * 120 + 60, 244, role + ' ' + side['name'], 12, True, ACCENT, width=106, center=True)
    return _tempo(c, tempo)


def images(state):
    sides = tuple(state.get('norns', ()))
    while len(sides) < 2:
        sides += ({'name': None, 'role': ('INSTRUMENT', 'EFFECT')[len(sides)], 'frame': '', 'mtime': None},)
    loop = state.get('loop')
    return _side(sides[0], state.get('tempo'), loop), _side(sides[1], None, loop)
