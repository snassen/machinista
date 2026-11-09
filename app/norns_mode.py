"""NORNS mode: an MK3 takeover mode that hands controls to the selected Sound's norns.

Each norns instance runs in its own container (see docs/norns/README.md). The
container's `machinista_bridge` mod writes its native 128x64 framebuffer to
a PNG file, and matron listens for OSC /remote/key and /remote/enc on UDP.
This module lives in the controller process: it routes MK3 input to those
OSC ports and builds the display state. Rendering happens in
app/norns_display.py inside the existing renderer process.

Layout follows the selected Sound (docs/norns/DESIGN.md, "norns as instrument
and effect"):
  left display  = its Norns Instrument: K1-K3 = DISPLAY 1-3, E1-E3 = KNOB 1-3
  right display = its Norns Effect:     K1-K3 = DISPLAY 5-7, E1-E3 = KNOB 5-7
Each plug-in's "Norns" control picks the instance. A side without such a
plug-in shows that and ignores its controls.
SHIFT + PLUG-IN enters and leaves the mode. Transport and pads stay with
Machinista so the groovebox keeps running underneath.
"""
import json
import os
import socket
import struct
import time
from pathlib import Path

# Numbered instances started by norns/run-norns.sh <n>: RAM folder
# /dev/shm/norns/<n>, OSC on 10110 + n.
SHM_ROOT = '/dev/shm/norns'
MAX_INSTANCES = 8
INSTRUMENT_URI = 'https://github.com/snassen/machinista/norns#instrument'
EFFECT_URI = 'https://github.com/snassen/machinista/norns#effect'
# Side 0 (left) shows the Norns Instrument, side 1 (right) the Norns Effect.
# The defaults match the plug-ins' "Norns" control defaults.
SIDES = ((INSTRUMENT_URI, 1, 'INSTRUMENT'), (EFFECT_URI, 2, 'EFFECT'))
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
# Controls Machinista keeps while NORNS mode is active: the transport, and
# KEYBOARD and FIXED VEL so the pads can be switched to keyboard mode while
# they play a norns.
PASS_THROUGH = frozenset(('PLAY', 'STOP', 'REC', 'RESTART', 'KEYBOARD', 'FIXED VEL'))
# Tempo stays with Machinista in NORNS mode: TEMPO selects it, the master
# encoder (raw control 0) changes it while TEMPO is selected, and SHIFT +
# NOTE REPEAT taps it.
TEMPO_BUTTON = 'TEMPO'
TAP_BUTTON = 'NOTE REPEAT'
MASTER_ENCODER = 0
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


def instance_port(n):
    return 10110 + n


def instance_frame(n):
    return f'{SHM_ROOT}/{n}/screen.png'


def sound_norns(app):
    """(left, right): the norns numbers of the selected Sound's first Norns
    Instrument and first Norns Effect, or None where there is no such plug-in."""
    try:
        plugins = app.track().get('plugins', [])
    except (AttributeError, IndexError, KeyError, TypeError):
        return (None, None)
    numbers = []
    for uri, default, _ in SIDES:
        number = None
        for plugin in plugins:
            if isinstance(plugin, dict) and plugin.get('uri') == uri:
                try:
                    number = int(round(float(plugin.get('controls', {}).get('norns', default))))
                except (TypeError, ValueError):
                    number = default
                if not 1 <= number <= MAX_INSTANCES:
                    number = default
                break
        numbers.append(number)
    return tuple(numbers)


class NornsMode:
    def __init__(self, root, sides=None, sender=None, clock=time.monotonic, tempo=None):
        """sides() returns (left, right) norns numbers or None; see sound_norns().

        tempo() returns Machinista's tempo text while its TEMPO mode is
        selected, else None.
        """
        self.root = root
        self.sides = sides or (lambda: (1, 2))
        self.tempo = tempo or (lambda: None)
        self.passed = set()  # buttons whose press went to Machinista: so does their release
        self.config_mtime = config_mtime(root)
        config = load_config(root)
        self.knob_travel = load_knob_travel(config)
        self.held = {}  # display button -> (port, key) of a norns key still pressed
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

    def port(self, side):
        """OSC port of the norns on this side right now, or None."""
        number = self.sides()[side]
        return instance_port(number) if number else None

    def send(self, side, address, *values):
        port = self.port(side)
        if port:
            self.sender(port, osc_message(address, *values))

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
            if not pressed and name in self.passed:
                self.passed.discard(name)
                return False
            if not pressed and name in self.held:
                # A norns key is always released where it was pressed, even
                # after leaving the mode or selecting another Sound meanwhile.
                port, key = self.held.pop(name)
                self.sender(port, osc_message('/remote/key', key, 0))
                return True
            if name == 'PLUG-IN' and self.shift:
                if pressed:
                    self.active = not self.active
                    self.remainders.clear()
                    self.pending.clear()
                return True
            if not self.active:
                return False
            if pressed and (name == TEMPO_BUTTON or (name == TAP_BUTTON and self.shift)):
                self.passed.add(name)
                return False
            if name in KEY_BUTTONS:
                side, key = KEY_BUTTONS[name]
                port = self.port(side)
                if pressed and port:
                    self.held[name] = (port, key)
                    self.sender(port, osc_message('/remote/key', key, 1))
                return True
            return name not in PASS_THROUGH
        if kind == 'encoder' and self.active:
            index = event['raw_control']
            if index == MASTER_ENCODER and self.tempo() is not None:
                return False
            if index in KNOBS:
                side, enc = KNOBS[index]
                value = event['value']
                now = self.clock()
                idle = now - self.last_turn.get(index, float('-inf')) > KNOB_IDLE_S
                self.last_turn[index] = now
                travel = self.knob_travel
                remainder = self.remainders.get(index, 0)
                if idle:
                    remainder = travel // 2 if value > 0 else -(travel // 2)
                elif remainder * value < 0:
                    remainder = 0  # reversing answers at once (as on the Pi 4 add-on)
                if self.pending.get(index, 0) * value < 0:
                    self.pending.pop(index)  # don't send steps of the old direction
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
        for number, (_, _, role) in zip(self.sides(), SIDES):
            if not number:
                sides.append(dict(name=None, role=role, frame='', mtime=None))
                continue
            frame = instance_frame(number)
            try:
                mtime = os.stat(frame).st_mtime_ns
            except OSError:
                mtime = None
            sides.append(dict(name=str(number), role=role, frame=frame, mtime=mtime))
        return {'norns_mode': True, 'norns': tuple(sides), 'shift': self.shift, 'tempo': self.tempo()}

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None
