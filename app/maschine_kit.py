"""Read sample references from supported Maschine Group archives."""
from pathlib import PurePosixPath
import re

MAX_KIT_BYTES = 8 * 1024**2
_RECORD = rb'(?:\x00{3}(?:\xff\x01\x00|\x01\x01\x00)\x00|\x00{6})(?:\x02..){4}'
_SOUND = re.compile(
    rb'(?:' + _RECORD + rb'\x00{6}(?:\x01\x01\x00\x02..\x00\x00|\x02..)\x02..'
    rb'|\x00{6}(?:\x01.){4}\x00{6}\x01\x01\x00\x01.\x00\x00\x01.)\x00\x01(.)',
    re.DOTALL,
)
_GROUP = re.compile(
    rb'\x02..\x01[\x01\x09](?:\x00|\x01[\x00\x01])(?:\x02..){4}'
    + _RECORD + rb'\x00(?:\x00|\x01.){3}\x00{2}(?:\x02..){2}\x00\x01',
    re.DOTALL,
)
_WAV = re.compile(rb'Samples/[^\x00-\x1f\\]+?\.wav(?=[\x00\x01])', re.IGNORECASE)


def read_kit(data):
    if (len(data) > MAX_KIT_BYTES or data[12:16] != b'hsin'
            or b'serialization::archive' not in data):
        raise ValueError('Unsupported Maschine Group archive.')
    groups = list(_GROUP.finditer(data))
    if len(groups) != 1:
        raise ValueError('This Maschine Group layout is not supported.')
    end = groups[0]
    sounds = list(_SOUND.finditer(data, 0, end.start()))
    if not 1 <= len(sounds) <= 16 or _WAV.search(data, 0, sounds[0].start()):
        raise ValueError('Could not identify the pad records in this Maschine Group.')
    pads = []
    extra = 0
    for index, sound in enumerate(sounds):
        name_end = sound.end() + sound[1][0]
        stop = sounds[index + 1].start() if index + 1 < len(sounds) else end.start()
        if name_end >= stop or data[name_end] not in (1, 2):
            raise ValueError('Invalid sound record in Maschine Group.')
        name = data[sound.end():name_end].decode('utf-8', errors='replace')
        paths = {}
        for match in _WAV.finditer(data, name_end, stop):
            if data[match.start() - 1] != len(match[0]):
                continue
            path = match[0].decode('utf-8')
            if any(part in ('', '.', '..') or part.startswith('.') for part in path.split('/')):
                raise ValueError('Invalid sample path in Maschine Group.')
            paths.setdefault(path.casefold(), path)
        if paths:
            path = next(iter(paths.values()))
            pads.append(dict(name=name.strip() or PurePosixPath(path).stem, path=path))
            extra += len(paths) - 1
    if not pads:
        raise ValueError('No supported WAV sample pads found in this Maschine Group.')
    notes = []
    skipped = len(sounds) - len(pads)
    if skipped:
        notes.append(f'Skipped {skipped} sound(s) without WAV samples.')
    if extra:
        notes.append('Multi-sample pads use their first WAV. Layers and slices are skipped.')
    return pads, notes
