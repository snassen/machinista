import json
import os
import struct
import tempfile
import unittest

from app.norns_mode import NornsMode, osc_message, KNOB_TRAVEL, KNOB_IDLE_S, PACE_S, CONFIG_CHECK_S


def button(name, value):
    return {'kind': 'button', 'name': name, 'value': value}


class NornsModeTest(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.now = 100.0
        self.mode = self.make_mode(tempfile.mkdtemp())

    def make_mode(self, root):
        return NornsMode(root, sender=lambda port, data: self.sent.append((port, data)), clock=lambda: self.now)

    def turn(self, control, value, after=0.01):
        self.now += after
        self.mode.handle_event({'kind': 'encoder', 'raw_control': control, 'value': value})

    def toggle(self):
        self.assertFalse(self.mode.handle_event(button('SHIFT', 1)))
        self.assertTrue(self.mode.handle_event(button('PLUG-IN', 1)))
        self.assertTrue(self.mode.handle_event(button('PLUG-IN', 0)))
        self.assertFalse(self.mode.handle_event(button('SHIFT', 0)))

    def test_inactive_mode_passes_everything_through(self):
        self.assertFalse(self.mode.handle_event(button('DISPLAY 1', 1)))
        self.assertFalse(self.mode.handle_event({'kind': 'encoder', 'raw_control': 1, 'value': 100}))
        self.assertFalse(self.mode.handle_event(button('PLUG-IN', 1)))
        self.assertEqual(self.sent, [])

    def test_shift_plugin_toggles(self):
        self.toggle()
        self.assertTrue(self.mode.active)
        self.toggle()
        self.assertFalse(self.mode.active)

    def test_keys_route_to_sides(self):
        self.toggle()
        self.mode.handle_event(button('DISPLAY 2', 1))
        self.mode.handle_event(button('DISPLAY 7', 0))
        self.assertEqual(self.sent, [(10111, osc_message('/remote/key', 2, 1)), (10112, osc_message('/remote/key', 3, 0))])

    def test_knobs_accumulate_into_steps(self):
        self.toggle()
        half = KNOB_TRAVEL // 2
        # First movement after a rest starts half a step ahead.
        self.turn(5, KNOB_TRAVEL - half - 1)
        self.assertEqual(self.sent, [])
        self.turn(5, 1 + KNOB_TRAVEL)
        self.assertEqual(self.sent, [(10112, osc_message('/remote/enc', 1, 2))])

    def test_first_nudge_after_rest_answers_quickly(self):
        self.toggle()
        self.turn(1, -(KNOB_TRAVEL - KNOB_TRAVEL // 2))
        self.assertEqual(self.sent, [(10111, osc_message('/remote/enc', 1, -1))])
        self.sent.clear()
        # Continuous turning keeps the remainder: no head-start mid-gesture.
        self.turn(1, -(KNOB_TRAVEL - 1), after=PACE_S)
        self.assertEqual(self.sent, [])
        self.turn(1, -1, after=PACE_S)
        self.assertEqual(self.sent, [(10111, osc_message('/remote/enc', 1, -1))])
        self.sent.clear()
        self.turn(1, 1, after=KNOB_IDLE_S + 0.1)
        self.turn(1, KNOB_TRAVEL - KNOB_TRAVEL // 2 - 1)
        self.assertEqual(self.sent, [(10111, osc_message('/remote/enc', 1, 1))])

    def test_fast_turn_is_paced_into_one_message(self):
        self.toggle()
        self.turn(2, KNOB_TRAVEL * 2)  # first message goes out at once
        for _ in range(5):
            self.turn(2, KNOB_TRAVEL, after=0.005)
        self.assertEqual(self.sent, [(10111, osc_message('/remote/enc', 2, 2))])
        self.now += PACE_S
        self.mode.flush()
        self.assertEqual(self.sent[1:], [(10111, osc_message('/remote/enc', 2, 5))])
        self.now += PACE_S
        self.mode.flush()
        self.assertEqual(len(self.sent), 2)

    def test_leaving_mode_drops_pending_steps(self):
        self.toggle()
        self.turn(3, KNOB_TRAVEL)
        self.turn(3, KNOB_TRAVEL, after=0.005)
        self.toggle()
        self.now += 1
        self.mode.flush()
        self.assertEqual(len(self.sent), 1)

    def test_knob_travel_reloads_while_running(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, 'config'))
        self.mode = self.make_mode(root)
        self.assertEqual(self.mode.knob_travel, KNOB_TRAVEL)
        with open(os.path.join(root, 'config', 'norns.json'), 'w') as f:
            json.dump({'knob_travel': 3}, f)
        self.now += CONFIG_CHECK_S
        self.mode.flush()
        self.assertEqual(self.mode.knob_travel, 3)

    def test_knob_travel_from_config(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, 'config'))
        with open(os.path.join(root, 'config', 'norns.json'), 'w') as f:
            json.dump({'knob_travel': 4}, f)
        self.mode = self.make_mode(root)
        self.assertEqual(self.mode.knob_travel, 4)
        self.assertEqual(self.mode.instances[0]['port'], 10111)
        self.toggle()
        self.turn(2, 2)
        self.assertEqual(self.sent, [(10111, osc_message('/remote/enc', 2, 1))])

    def test_transport_and_pads_stay_with_machinista(self):
        self.toggle()
        self.assertFalse(self.mode.handle_event(button('PLAY', 1)))
        self.assertFalse(self.mode.handle_event({'kind': 'pad_on', 'name': 'PAD_1', 'value': 100}))
        self.assertTrue(self.mode.handle_event(button('BROWSE', 1)))

    def test_osc_encoding(self):
        data = osc_message('/remote/enc', 1, -3)
        self.assertEqual(len(data) % 4, 0)
        self.assertEqual(data[-4:], struct.pack('>i', -3))


if __name__ == '__main__':
    unittest.main()
