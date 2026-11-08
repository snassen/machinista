"""NORNS mode: an MK3 takeover mode that hands controls to up to two norns.

Each norns instance runs in its own container (see norns/README.md). The
container's `machinista_bridge` mod writes its native 128x64 framebuffer to
a PNG file, and matron listens for OSC /remote/key and /remote/enc on UDP.
This module lives in the controller process: it routes MK3 input to those
OSC ports and builds the display state. Rendering happens in
app/norns_display.py inside the existing renderer process.

Layout: norns A on the left display, norns B on the right.
  K1-K3 = DISPLAY 1-3 (A) and DISPLAY 5-7 (B)
  E1-E3 = KNOB 1-3 (A) and KNOB 5-7 (B)
SHIFT + PLUG-IN enters and leaves the mode. Transport and pads stay with
Machinista so the groovebox keeps running underneath.
"""
import json
import os
import socket
import struct
from pathlib import Path

DEFAULT_INSTANCES = (
    {'name': 'A', 'frame': '/home/machinista/norns/A/screen.png', 'port': 10111},
    {'name': 'B', 'frame': '/home/machinista/norns/B/screen.png', 'port': 10112},
)
# Raw MK3 knob counts per norns encoder step. Placeholder value: calibrate on
# hardware (the MK3 knobs report 0..999 per revolution).
KNOB_TRAVEL = 25
# Controls Machinista keeps while NORNS mode is active.
PASS_THROUGH = frozenset(('PLAY', 'STOP', 'REC', 'RESTART'))
KEY_BUTTONS = {f'DISPLAY {i + 1}': (0, i + 1) for i in range(3)}
KEY_BUTTONS.update({f'DISPLAY {i + 5}': (1, i + 1) for i in range(3)})
KNOBS = {i + 1: (0, i + 1) for i in range(3)}
KNOBS.update({i + 5: (1, i + 1) for i in range(3)})


def osc_message(address, *values):
    """Encode a minimal OSC message with int32 arguments."""
    def pad(data):
        return data + b'\0' * (4 - len(data) % 4)
    tags = ',' + 'i' * len(values)
    return pad(address.encode()) + pad(tags.encode()) + b''.join(struct.pack('>i', int(v)) for v in values)


def load_instances(root):
    path = Path(root) / 'config' / 'norns.json'
    try:
        data = json.loads(path.read_text())
        instances = tuple(dict(name=str(i['name']), frame=str(i['frame']), port=int(i['port'])) for i in data['instances'][:2])
        if instances:
            return instances
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return DEFAULT_INSTANCES


class NornsMode:
    def __init__(self, root, sender=None):
        self.instances = load_instances(root)
        self.active = False
        self.shift = False
        self.remainders = {}
        self.sock = None
        self.sender = sender or self._send

    def _send(self, port, data):
        if self.sock is None:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setblocking(False)
        try:
            self.sock.sendto(data, ('127.0.0.1', port))
        except OSError:
            pass  # norns not running: input is dropped, Machinista carries on

    def send(self, side, address, *values):
        if side < len(self.instances):
            self.sender(self.instances[side]['port'], osc_message(address, *values))

    def handle_event(self, event):
        """Return True when NORNS mode consumed the event."""
        kind = event.get('kind')
        if kind == 'button':
            name, pressed = event['name'], bool(event['value'])
            if name == 'SHIFT':
                # Always let Machinista see SHIFT so its own shift state never
                # sticks after leaving NORNS mode.
                self.shift = pressed
                return False
            if name == 'PLUG-IN' and self.shift:
                if pressed:
                    self.active = not self.active
                    self.remainders.clear()
                return True
            if not self.active:
                return False
            if name in KEY_BUTTONS:
                side, key = KEY_BUTTONS[name]
                self.send(side, '/remote/key', key, 1 if pressed else 0)
                return True
            return name not in PASS_THROUGH
        if kind == 'encoder' and self.active:
            index = event['raw_control']
            if index in KNOBS:
                side, enc = KNOBS[index]
                total = self.remainders.get(index, 0) + event['value']
                steps = int(total / KNOB_TRAVEL)
                self.remainders[index] = total - steps * KNOB_TRAVEL
                if steps:
                    self.send(side, '/remote/enc', enc, steps)
            return True
        return False

    def display_state(self):
        sides = []
        for instance in self.instances:
            try:
                mtime = os.stat(instance['frame']).st_mtime_ns
            except OSError:
                mtime = None
            sides.append(dict(name=instance['name'], frame=instance['frame'], mtime=mtime))
        return {'norns_mode': True, 'norns': tuple(sides), 'shift': self.shift}

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None
