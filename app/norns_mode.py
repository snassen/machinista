"""NORNS mode: an MK3 takeover mode that hands controls to up to two norns.

Each norns instance runs in its own container (see docs/norns/README.md). The
container's `machinista_bridge` mod writes its native 128x64 framebuffer to
a PNG file, and matron listens for OSC /remote/key and /remote/enc on UDP.
This module lives in the controller process: it routes MK3 input to those
OSC ports and builds the display state. Rendering happens in
app/norns_display.py inside the existing renderer process.

Layout: norns 1 on the left display, norns 2 on the right.
  K1-K3 = DISPLAY 1-3 (norns 1) and DISPLAY 5-7 (norns 2)
  E1-E3 = KNOB 1-3 (norns 1) and KNOB 5-7 (norns 2)
SHIFT + PLUG-IN enters and leaves the mode. Transport and pads stay with
Machinista so the groovebox keeps running underneath.
"""
import json
import os
import socket
import struct
import time
from pathlib import Path

# Numbered instances started by norns/run-norns.sh <n>: RAM folder /dev/shm/norns/<n>,
# OSC on 10110 + n. Until the displays follow the selected Sound's Norns
# Instrument and Norns Effect, the left display shows norns 1 and the right norns 2.
DEFAULT_INSTANCES = (
    {'name': '1', 'frame': '/dev/shm/norns/1/screen.png', 'port': 10111},
    {'name': '2', 'frame': '/dev/shm/norns/2/screen.png', 'port': 10112},
)
# Raw MK3 knob counts per norns encoder step (the MK3 knobs report 1000
# counts per revolution, so 10 = 100 steps per turn). 25 felt sluggish on
# hardware. Override with "knob_travel" in config/norns.json.
KNOB_TRAVEL = 10
# After a knob has rested this long, its next movement starts half a step
# ahead, so the first nudge answers quickly instead of needing a full step.
KNOB_IDLE_S = 0.3
# norns multiplies encoder deltas that arrive less than 30 ms apart by 2-6
# (encoders.process_with_accel). Sending at most one message per knob per
# PACE_S keeps that acceleration out, so Machinista alone decides the feel.
PACE_S = 0.04
# How often a running session looks for changes to config/norns.json.
CONFIG_CHECK_S = 1.0
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


def config_path(root):
    return Path(root) / 'config' / 'norns.json'


def config_mtime(root):
    try:
        return config_path(root).stat().st_mtime_ns
    except OSError:
        return None


def load_config(root):
    try:
        return json.loads(config_path(root).read_text())
    except (OSError, ValueError):
        return {}


def load_knob_travel(data):
    try:
        travel = int(data['knob_travel'])
        if travel >= 1:
            return travel
    except (KeyError, TypeError, ValueError):
        pass
    return KNOB_TRAVEL


def load_instances(data):
    try:
        instances = tuple(dict(name=str(i['name']), frame=str(i['frame']), port=int(i['port'])) for i in data['instances'][:2])
        if instances:
            return instances
    except (ValueError, KeyError, TypeError):
        pass
    return DEFAULT_INSTANCES


class NornsMode:
    def __init__(self, root, sender=None, clock=time.monotonic):
        self.root = root
        self.config_mtime = config_mtime(root)
        config = load_config(root)
        self.instances = load_instances(config)
        self.knob_travel = load_knob_travel(config)
        self.active = False
        self.shift = False
        self.remainders = {}
        self.last_turn = {}
        self.pending = {}
        self.last_sent = {}
        self.clock = clock
        self.next_config_check = clock() + CONFIG_CHECK_S
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
                    self.pending.clear()
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
                value = event['value']
                now = self.clock()
                idle = now - self.last_turn.get(index, float('-inf')) > KNOB_IDLE_S
                self.last_turn[index] = now
                travel = self.knob_travel
                if idle:
                    remainder = travel // 2 if value > 0 else -(travel // 2)
                else:
                    remainder = self.remainders.get(index, 0)
                total = remainder + value
                steps = int(total / travel)
                self.remainders[index] = total - steps * travel
                if steps:
                    self.pending[index] = self.pending.get(index, 0) + steps
                    self.flush(now)
            return True
        return False

    def flush(self, now=None):
        """Send collected knob steps, at most one message per knob per PACE_S.

        Called after each knob event and from the session's poll loop, so the
        last steps of a turn go out once the pacing window has passed.
        """
        now = self.clock() if now is None else now
        if now >= self.next_config_check:
            self.next_config_check = now + CONFIG_CHECK_S
            self.reload_config()
        for index, steps in list(self.pending.items()):
            if now - self.last_sent.get(index, float('-inf')) < PACE_S:
                continue
            del self.pending[index]
            if steps:
                side, enc = KNOBS[index]
                self.send(side, '/remote/enc', enc, steps)
                self.last_sent[index] = now

    def reload_config(self):
        """Pick up a changed knob_travel without restarting Machinista."""
        mtime = config_mtime(self.root)
        if mtime == self.config_mtime:
            return
        self.config_mtime = mtime
        travel = load_knob_travel(load_config(self.root))
        if travel != self.knob_travel:
            self.knob_travel = travel
            self.remainders.clear()
            print('NORNS knob_travel ' + str(travel), flush=True)

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
