"""One-button loop recording in NORNS mode (agreed 2026-11-09).

SHIFT + REC records the selected Sound (its whole chain, so its Norns
Instrument or Norns Effect) onto the first empty pad, as an audio loop that
plays in a pattern. It uses Machinista's own bounce capture (app/audio_loop.py):
the recording starts on the next bar line (the transport starts if it is
stopped) and runs a fixed number of bars at the project tempo. SHIFT + REC
again, while waiting or recording, cancels it and discards the take.

The master encoder chooses the bars (1, 2, 4, 8, 16; default 4) and its push
switches the tail mode; both are remembered in config/norns-loop.json:
  FOLD  record one bar more and mix that bar onto the loop's start, so a
        reverb or delay tail rings on across the loop point. For drones and
        sounds that fade; a sequence that keeps playing would double its
        first bar.
  CUT   exactly the chosen bars; whatever rings past the end is cut.
"""
import array
import copy
import json
import os
import sys
import time
import wave
from pathlib import Path

BAR_CHOICES = (1, 2, 4, 8, 16)
TAILS = ('FOLD', 'CUT')
DEFAULTS = {'bars': 4, 'tail': 'FOLD'}
SHOW_S = 2.0  # how long a changed setting stays on the display


def settings_path(root):
    return Path(root) / 'config/norns-loop.json'


def load_settings(root):
    try:
        data = json.loads(settings_path(root).read_text())
    except (OSError, ValueError):
        data = {}
    bars = data.get('bars') if data.get('bars') in BAR_CHOICES else DEFAULTS['bars']
    tail = data.get('tail') if data.get('tail') in TAILS else DEFAULTS['tail']
    return {'bars': bars, 'tail': tail}


def bar_frames(bars, tempo, rate):
    return round(bars * 4 * 60 / tempo * rate)


def fold_tail(path, bars, tempo):
    """Mix everything past `bars` onto the start of the file and cut the file
    to `bars`. Returns True when the file was changed. Machinista's recorder
    writes 16-bit stereo; anything else is left alone."""
    path = Path(path)
    with wave.open(str(path), 'rb') as wav:
        params = wav.getparams()
        if params.sampwidth != 2 or params.comptype != 'NONE':
            return False
        data = array.array('h', wav.readframes(params.nframes))
    if sys.byteorder != 'little':
        data.byteswap()
    keep = bar_frames(bars, tempo, params.framerate)
    if params.nframes <= keep:
        return False  # stopped early: nothing past the loop to fold
    channels = params.nchannels
    head, tail = data[:keep * channels], data[keep * channels:]
    for i in range(min(len(tail), len(head))):
        value = head[i] + tail[i]
        head[i] = 32767 if value > 32767 else -32768 if value < -32768 else value
    if sys.byteorder != 'little':
        head.byteswap()
    temporary = path.with_suffix('.fold.tmp')
    with wave.open(str(temporary), 'wb') as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(params.framerate)
        out.writeframes(head.tobytes())
    os.replace(temporary, path)
    return True


class NornsLoop:
    def __init__(self, root, app):
        """app() returns Machinista's app (the session's current one)."""
        self.root = root
        self.app = app
        self.settings = load_settings(root)
        self.mine = False  # the capture running now was started here
        self.changed = float('-inf')  # when bars or tail last changed (shown a while)

    def save(self):
        path = settings_path(self.root)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.settings) + '\n')
            os.replace(temporary, path)
        except OSError:
            pass

    def state(self):
        app = self.app()
        busy = bool(getattr(app, 'capture_armed', False)) or getattr(app, 'capture_started', None) is not None
        if not busy:
            self.mine = False
            return 'IDLE'
        if not self.mine:
            return 'BUSY'  # a recording Machinista started itself
        return 'RECORDING' if app.capture_started is not None else 'WAITING'

    def change_bars(self, delta):
        if self.state() != 'IDLE' or not delta:
            return
        index = BAR_CHOICES.index(self.settings['bars'])
        index = max(0, min(len(BAR_CHOICES) - 1, index + (1 if delta > 0 else -1)))
        if BAR_CHOICES[index] != self.settings['bars']:
            self.settings['bars'] = BAR_CHOICES[index]
            self.save()
        self.changed = time.monotonic()

    def toggle_tail(self):
        if self.state() != 'IDLE':
            return
        self.settings['tail'] = 'CUT' if self.settings['tail'] == 'FOLD' else 'FOLD'
        self.save()
        self.changed = time.monotonic()

    def toggle(self):
        state = self.state()
        app = self.app()
        if state in ('WAITING', 'RECORDING'):
            app.actions.append(('capture_cancel', None))
            app.capture_armed = False
            app.message = 'LOOP RECORDING CANCELLED'
            return
        if state == 'BUSY':
            app.message = 'STOP RECORDING FIRST'
            return
        self.start(app)

    def start(self, app):
        if getattr(app, 'recording', False):
            app.message = 'STOP MIDI REC FIRST'
            return
        source = (app.group, app.pad)
        target = next(((app.group, p) for p in range(16) if p != app.pad and app.bounce_empty(app.group, p)), None)
        if target is None:
            target = next(((g, p) for g in range(len(app.project['groups'])) for p in range(16)
                           if (g, p) != source and app.bounce_empty(g, p)), None)
        if target is None:
            app.message = 'NO EMPTY PAD'
            return
        bars, fold = self.settings['bars'], self.settings['tail'] == 'FOLD'
        options = dict(source='INTERNAL', input=f'SOUND {source[0]} {source[1]}', mode='SYNC',
                       bars=bars + (1 if fold else 0), threshold=-24, monitor=False)
        job = dict(target=target, options=options, result='AUDIO', bounce=dict(mute_source=False),
                   expected=copy.deepcopy(app.project['groups'][target[0]]['pads'][target[1]]),
                   norns_loop=True, fold_bars=bars if fold else None)
        app.actions.append(('capture_to', job))
        app.capture_armed = True
        self.mine = True
        app.message = f'LOOP {bars} BARS TO {app.group_name(target[0])}:{target[1] + 1:02}'
        if not app.playing:
            app.clock_phase = 0
            app.step = 0
            app.playing = True
            app.actions.append(('restart', None))

    def status(self):
        """What NORNS mode shows: the state, the bars and the tail mode."""
        state = self.state()
        bars, tail = self.settings['bars'], self.settings['tail']
        word = {'WAITING': 'WAIT', 'RECORDING': 'REC'}.get(state, 'LOOP')
        show = state in ('WAITING', 'RECORDING') or time.monotonic() - self.changed < SHOW_S
        return {'state': state, 'bars': bars, 'tail': tail, 'text': f'{word} {bars} {tail}', 'show': show}


def finish_hook(context, path, tempo):
    """Called by finish_sample_recording before the take is loaded: folds the
    tail of a loop recorded here and restores the loop's length in bars."""
    bars = context.get('fold_bars')
    if not bars:
        return
    try:
        fold_tail(path, bars, tempo)
    except (OSError, EOFError, wave.Error) as error:
        print('NORNS loop fold failed: ' + str(error), flush=True)
        return
    context.setdefault('options', {})['bars'] = bars
