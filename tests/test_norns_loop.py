import array
import json
import tempfile
import unittest
import wave
from pathlib import Path

from app.model import Application
from app.norns_loop import NornsLoop, fold_tail, bar_frames, load_settings, settings_path
from app.norns_mode import NornsMode
from app.norns_display import images


def button(name, value):
    return {'kind': 'button', 'name': name, 'value': value}


def write_wav(path, frames, rate=48000):
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(array.array('h', frames).tobytes())


def read_wav(path):
    with wave.open(str(path), 'rb') as w:
        return w.getnframes(), array.array('h', w.readframes(w.getnframes()))


class FoldTailTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'take.wav'

    def test_tail_is_mixed_onto_the_start_and_cut(self):
        # 1 bar at 240 BPM and 8 Hz = 8 frames; record 1 bar + a 3-frame tail.
        keep = bar_frames(1, 240, 8)
        self.assertEqual(keep, 8)
        loop = [100] * (keep * 2)
        tail = [10, -10, 20, -20, 30, -30]
        write_wav(self.path, loop + tail, rate=8)
        self.assertTrue(fold_tail(self.path, 1, 240))
        frames, data = read_wav(self.path)
        self.assertEqual(frames, keep)
        self.assertEqual(list(data[:6]), [110, 90, 120, 80, 130, 70])
        self.assertEqual(list(data[6:]), [100] * (keep * 2 - 6))

    def test_mix_clips_instead_of_wrapping(self):
        write_wav(self.path, [32000, -32000] * 8 + [2000, -2000], rate=8)
        fold_tail(self.path, 1, 240)
        _, data = read_wav(self.path)
        self.assertEqual(list(data[:2]), [32767, -32768])

    def test_short_take_is_left_alone(self):
        write_wav(self.path, [5, 5] * 6, rate=8)
        self.assertFalse(fold_tail(self.path, 1, 240))
        self.assertEqual(read_wav(self.path)[0], 6)


class NornsLoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = Application(self.tmp.name)
        self.app.actions.clear()
        self.loop = NornsLoop(self.tmp.name, lambda: self.app)

    def test_defaults_and_remembered_settings(self):
        self.assertEqual(self.loop.settings, {'bars': 4, 'tail': 'FOLD'})
        self.loop.change_bars(1)
        self.loop.toggle_tail()
        self.assertEqual(load_settings(self.tmp.name), {'bars': 8, 'tail': 'CUT'})
        for _ in range(9):
            self.loop.change_bars(1)
        self.assertEqual(self.loop.settings['bars'], 16)
        settings_path(self.tmp.name).write_text('{"bars": 3, "tail": "X"}')
        self.assertEqual(load_settings(self.tmp.name), {'bars': 4, 'tail': 'FOLD'})

    def test_start_records_selected_sound_onto_first_empty_pad(self):
        self.app.group, self.app.pad = 0, 0
        self.loop.toggle()
        action, job = self.app.actions[0]
        self.assertEqual(action, 'capture_to')
        self.assertEqual(job['target'], (0, 1))
        self.assertEqual(job['options']['input'], 'SOUND 0 0')
        self.assertEqual(job['options']['mode'], 'SYNC')
        self.assertEqual(job['options']['bars'], 5)  # 4 bars plus one for the tail
        self.assertEqual(job['fold_bars'], 4)
        self.assertEqual(job['result'], 'AUDIO')
        self.assertTrue(self.app.capture_armed)
        self.assertTrue(self.app.playing)  # a stopped transport starts
        self.assertEqual(self.loop.state(), 'WAITING')

    def test_cut_records_exact_bars(self):
        self.loop.toggle_tail()
        self.loop.toggle()
        job = self.app.actions[0][1]
        self.assertEqual(job['options']['bars'], 4)
        self.assertIsNone(job['fold_bars'])

    def test_second_press_cancels(self):
        self.loop.toggle()
        self.app.capture_started = 1.0  # the bar came: recording
        self.assertEqual(self.loop.state(), 'RECORDING')
        self.loop.toggle()
        self.assertEqual(self.app.actions[-1], ('capture_cancel', None))
        self.app.capture_started = None
        self.assertEqual(self.loop.state(), 'IDLE')

    def test_settings_locked_while_busy_and_other_recordings_respected(self):
        self.loop.toggle()
        self.loop.change_bars(1)
        self.assertEqual(self.loop.settings['bars'], 4)
        self.app.capture_armed = False
        self.loop.state()
        self.app.capture_armed = True  # Machinista's own sampling, not ours
        self.assertEqual(self.loop.state(), 'BUSY')
        count = len(self.app.actions)
        self.loop.toggle()
        self.assertEqual(len(self.app.actions), count)

    def test_finished_take_is_folded_and_lands_as_four_bar_loop(self):
        self.loop.toggle()
        job = self.app.actions[0][1]
        job['tempo'] = self.app.project['tempo']
        rate = 48000
        keep = bar_frames(4, job['tempo'], rate)
        extra = bar_frames(1, job['tempo'], rate)
        path = Path(self.tmp.name) / 'samples/recordings/Sample 1.wav'
        path.parent.mkdir(parents=True, exist_ok=True)
        write_wav(path, [1, 1] * (keep + extra), rate)
        self.app.capture_jobs[str(path)] = job
        self.assertTrue(self.app.finish_sample_recording(job['target'], path, self.app.project_generation))
        self.assertEqual(read_wav(path)[0], keep)
        track = self.app.project['groups'][0]['pads'][1]
        self.assertEqual(track['playback_mode'], 'AUDIO')
        self.assertEqual(track['audio_loop']['bars'], 4)
        self.assertEqual(read_wav(path)[1][0], 2)  # the tail bar folded onto the start


class NornsModeLoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = Application(self.tmp.name)
        self.app.actions.clear()
        self.loop = NornsLoop(self.tmp.name, lambda: self.app)
        self.mode = NornsMode(self.tmp.name, sender=lambda port, data: None, loop=self.loop)
        for event in (button('SHIFT', 1), button('PLUG-IN', 1), button('PLUG-IN', 0), button('SHIFT', 0)):
            self.mode.handle_event(event)

    def test_shift_rec_arms_and_rec_alone_stays_with_machinista(self):
        self.assertFalse(self.mode.handle_event(button('REC', 1)))
        self.assertFalse(self.mode.handle_event(button('REC', 0)))
        self.assertEqual(self.app.actions, [])
        self.mode.handle_event(button('SHIFT', 1))
        self.assertTrue(self.mode.handle_event(button('REC', 1)))
        self.mode.handle_event(button('SHIFT', 0))
        self.assertTrue(self.mode.handle_event(button('REC', 0)))  # its release too
        self.assertEqual(self.app.actions[0][0], 'capture_to')

    def test_master_encoder_and_push_set_bars_and_tail(self):
        self.mode.handle_event({'kind': 'encoder', 'raw_control': 0, 'value': -1})
        self.assertTrue(self.mode.handle_event(button('MASTER PUSH', 1)))
        self.assertTrue(self.mode.handle_event(button('MASTER PUSH', 0)))
        self.assertEqual(self.loop.settings, {'bars': 2, 'tail': 'CUT'})
        state = self.mode.display_state()['loop']
        self.assertTrue(state['show'])
        self.assertEqual(state['text'], 'LOOP 2 CUT')

    def test_display_draws_with_loop_status(self):
        self.mode.handle_event(button('SHIFT', 1))
        self.mode.handle_event(button('REC', 1))
        state = self.mode.display_state()
        self.assertEqual(state['loop']['text'], 'WAIT 4 FOLD')
        left, right = images(state)
        self.assertEqual(left.size, right.size)


if __name__ == '__main__':
    unittest.main()
