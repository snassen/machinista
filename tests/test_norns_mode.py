import struct
import tempfile
import unittest

from app.norns_mode import NornsMode, osc_message, KNOB_TRAVEL


def button(name, value):
    return {'kind': 'button', 'name': name, 'value': value}


class NornsModeTest(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.mode = NornsMode(tempfile.mkdtemp(), sender=lambda port, data: self.sent.append((port, data)))

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
        self.mode.handle_event({'kind': 'encoder', 'raw_control': 5, 'value': KNOB_TRAVEL - 1})
        self.assertEqual(self.sent, [])
        self.mode.handle_event({'kind': 'encoder', 'raw_control': 5, 'value': 1 + KNOB_TRAVEL})
        self.assertEqual(self.sent, [(10112, osc_message('/remote/enc', 1, 2))])

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
