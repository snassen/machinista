"""Discover supported USB/HAT PCM and USB raw-MIDI without fixed card numbers."""
from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class AudioDevice:
    key: str
    name: str
    playback: str
    capture: str | None
    output_channels: int = 2
    input_channels: int = 2
    transport: str = "USB"


@dataclass(frozen=True)
class MidiDevice:
    key: str
    name: str
    path: str


def usb_identity(device):
    for parent in (device.resolve(), *device.resolve().parents):
        if (parent/'idVendor').exists() and (parent/'idProduct').exists():
            vendor = (parent/'idVendor').read_text().strip()
            product = (parent/'idProduct').read_text().strip()
            serial = (parent/'serial').read_text().strip() if (parent/'serial').exists() else ''
            # No serial: physical USB topology distinguishes identical units.
            identity = f'{vendor}:{product}:{serial or parent.name}'
            name = (parent/'product').read_text().strip() if (parent/'product').exists() else identity
            return identity, name
    return None


def usb_channels(card, endpoint=None):
    """Read actual USB alternate-setting channel counts, not plughw conversion limits."""
    result={'Playback':0,'Capture':0}
    streams=card.glob('stream*') if endpoint is None else (card/f'stream{endpoint}',)
    for stream in streams:
        section=None
        try:lines=stream.read_text().splitlines()
        except OSError:continue
        for line in lines:
            if line.strip() in ('Playback:','Capture:'):section=line.strip()[:-1]
            match=re.fullmatch(r'\s*Channels:\s*(\d+)\s*',line)
            if match and section:result[section]=max(result[section],min(64,int(match[1])))
    return result['Playback'] or 2,result['Capture'] or 2


def hat_identity(card):
    from app.hat_audio import identity
    return identity(card)


def discover(sound=Path('/sys/class/sound'), proc=Path('/proc/asound'), dev=Path('/dev/snd')):
    audio, midi = [], []
    for card in sorted(sound.glob('card*')):
        match = re.fullmatch(r'card(\d+)', card.name)
        if not match:
            continue
        number = int(match[1])
        identity = usb_identity(card/'device')
        transport='USB'
        if identity is None:
            identity=hat_identity(proc/card.name);transport='HAT'
        if identity is None:continue
        key, name = identity
        for pcm in sorted((proc/card.name).glob('pcm*p')):
            match = re.fullmatch(r'pcm(\d+)p', pcm.name)
            if not match:
                continue
            endpoint = int(match[1])
            capture = f'plughw:{number},{endpoint}' if (proc/card.name/f'pcm{endpoint}c').exists() else None
            outputs,inputs=usb_channels(proc/card.name,endpoint) if transport=='USB' else (2,2)
            audio.append(AudioDevice(f'{key}:pcm{endpoint}', f'{name} OUT {endpoint+1}',
                                     f'plughw:{number},{endpoint}', capture, outputs, inputs if capture else 0,transport))
        for raw in sorted(dev.glob(f'midiC{number}D*')) if transport=='USB' else ():
            endpoint = raw.name.split('D')[-1]
            midi.append(MidiDevice(f'{key}:midi{endpoint}', f'{name} MIDI {int(endpoint)+1}', str(raw)))
    from app.ble_midi_bridge import discover_ble
    midi.extend(discover_ble(proc,dev))
    from app.mk1_midi import discover_mk1
    midi.extend(discover_mk1())
    from app.norns_midi import discover_bus  # norns-mode fork hook
    midi.extend(discover_bus(proc,dev))  # norns-mode fork hook
    return sorted(audio, key=lambda d: d.key), sorted(midi, key=lambda d: d.key)


def choose_audio(devices, preference, current_key=None):
    """Explicit choice stays sticky; AUTO prefers USB, then supported HAT."""
    if preference != 'AUTO':
        return next((device for device in devices if device.key == preference), None)
    preferred=[device for device in devices if device.transport=='USB']
    if not preferred:preferred=[device for device in devices if device.transport=='HAT']
    return next((device for device in preferred if device.key==current_key),preferred[0] if preferred else None)
