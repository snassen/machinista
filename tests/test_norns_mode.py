import json
import os
import struct
import tempfile
import unittest

from app.norns_mode import (NornsMode, osc_message, sound_norns, KNOB_TRAVEL, KNOB_IDLE_S, PACE_S,
                             CONFIG_CHECK_S, INSTRUMENT_URI, EFFECT_URI, LAYER_SAVE_S, layers_path)


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
        self.mode.handle_event(button('DISPLAY 7', 1))
        self.mode.handle_event(button('DISPLAY 7', 0))
        self.assertEqual(self.sent, [(10111, osc_message('/remote/key', 2, 1)), (10112, osc_message('/remote/key', 3, 1)),
                                     (10112, osc_message('/remote/key', 3, 0))])

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
        self.toggle()
        self.turn(2, 2)
        self.assertEqual(self.sent, [(10111, osc_message('/remote/enc', 2, 1))])

    def test_stop_releases_notes_on_every_norns(self):
        for active in (False, True):
            self.sent.clear()
            self.assertFalse(self.mode.handle_event(button('STOP', 1)))
            self.assertFalse(self.mode.handle_event(button('STOP', 0)))
            self.assertEqual(self.sent, [(10110 + n, osc_message('/machinista/notes_off')) for n in range(1, 9)])
            if not active:
                self.toggle()

    def test_transport_and_pads_stay_with_machinista(self):
        self.toggle()
        self.assertFalse(self.mode.handle_event(button('PLAY', 1)))
        self.assertFalse(self.mode.handle_event({'kind': 'pad_on', 'name': 'PAD_1', 'value': 100}))
        self.assertTrue(self.mode.handle_event(button('BROWSE', 1)))

    def test_keyboard_and_fixed_velocity_stay_with_machinista(self):
        self.toggle()
        for name in ('KEYBOARD', 'FIXED VEL'):
            self.assertFalse(self.mode.handle_event(button(name, 1)))
            self.assertFalse(self.mode.handle_event(button(name, 0)))
        self.assertTrue(self.mode.handle_event(button('CHORDS', 1)))
        self.assertEqual(self.sent, [])

    def test_keys_follow_the_selected_sound(self):
        sides = [(3, None)]
        self.mode = NornsMode(tempfile.mkdtemp(), sides=lambda: sides[0],
                              sender=lambda port, data: self.sent.append((port, data)), clock=lambda: self.now)
        self.toggle()
        self.assertTrue(self.mode.handle_event(button('DISPLAY 1', 1)))
        self.assertTrue(self.mode.handle_event(button('DISPLAY 1', 0)))
        # No Norns Effect on this Sound: the right side's keys go nowhere but stay consumed.
        self.assertTrue(self.mode.handle_event(button('DISPLAY 5', 1)))
        self.assertTrue(self.mode.handle_event(button('DISPLAY 5', 0)))
        self.assertEqual(self.sent, [(10113, osc_message('/remote/key', 1, 1)), (10113, osc_message('/remote/key', 1, 0))])
        self.sent.clear()
        sides[0] = (4, 6)  # another Sound selected
        self.turn(5, KNOB_TRAVEL)
        self.assertEqual(self.sent, [(10116, osc_message('/remote/enc', 1, 1))])

    def test_key_released_where_pressed(self):
        sides = [(1, 2)]
        self.mode = NornsMode(tempfile.mkdtemp(), sides=lambda: sides[0],
                              sender=lambda port, data: self.sent.append((port, data)), clock=lambda: self.now)
        self.toggle()
        self.mode.handle_event(button('DISPLAY 2', 1))
        sides[0] = (5, None)  # Sound changed while the key is held
        self.toggle()         # and the mode was left
        self.assertTrue(self.mode.handle_event(button('DISPLAY 2', 0)))
        self.assertEqual(self.sent, [(10111, osc_message('/remote/key', 2, 1)), (10111, osc_message('/remote/key', 2, 0))])
        # Not held any more: the next release belongs to Machinista again.
        self.assertFalse(self.mode.handle_event(button('DISPLAY 2', 0)))

    def test_reversing_a_knob_answers_at_once(self):
        self.toggle()
        half = KNOB_TRAVEL // 2
        self.turn(1, KNOB_TRAVEL - half + 2)   # one step up, a little left over
        self.assertEqual(self.sent, [(10111, osc_message('/remote/enc', 1, 1))])
        self.turn(1, -KNOB_TRAVEL, after=PACE_S)  # a full step back, without paying off the leftover
        self.assertEqual(self.sent[1:], [(10111, osc_message('/remote/enc', 1, -1))])

    def test_tempo_stays_with_machinista(self):
        tempo = [None]
        self.mode = NornsMode(tempfile.mkdtemp(), sender=lambda port, data: self.sent.append((port, data)),
                              clock=lambda: self.now, tempo=lambda: tempo[0])
        self.toggle()
        master = {'kind': 'encoder', 'raw_control': 0, 'value': 5}
        self.assertTrue(self.mode.handle_event(master))  # no TEMPO selected: nothing hidden changes
        self.assertFalse(self.mode.handle_event(button('TEMPO', 1)))
        self.assertFalse(self.mode.handle_event(button('TEMPO', 0)))
        tempo[0] = '120.00'
        self.assertFalse(self.mode.handle_event(master))
        self.assertEqual(self.mode.display_state()['tempo'], '120.00')
        self.assertEqual(self.sent, [])
        self.assertTrue(self.mode.handle_event({'kind': 'encoder', 'raw_control': 1, 'value': 5}))
        self.assertEqual(len(self.sent), 1)  # the knobs still play norns

    def test_tap_tempo_press_and_release_reach_machinista(self):
        self.toggle()
        self.assertTrue(self.mode.handle_event(button('NOTE REPEAT', 1)))  # without SHIFT: swallowed
        self.assertTrue(self.mode.handle_event(button('NOTE REPEAT', 0)))
        self.assertFalse(self.mode.handle_event(button('SHIFT', 1)))
        self.assertFalse(self.mode.handle_event(button('NOTE REPEAT', 1)))
        self.assertFalse(self.mode.handle_event(button('SHIFT', 0)))
        self.assertFalse(self.mode.handle_event(button('NOTE REPEAT', 0)))  # released after SHIFT

    def test_display_state_shows_missing_sides(self):
        self.mode = NornsMode(tempfile.mkdtemp(), sides=lambda: (None, 2), sender=lambda *a: None)
        left, right = self.mode.display_state()['norns']
        self.assertIsNone(left['name'])
        self.assertEqual(left['role'], 'INSTRUMENT')
        self.assertEqual((right['name'], right['role']), ('2', 'EFFECT'))
        self.assertTrue(right['frame'].endswith('/2/screen.png'))

    def test_knob_4_and_8_set_reverb_and_level(self):
        self.toggle()
        self.turn(4, KNOB_TRAVEL)
        self.turn(8, -KNOB_TRAVEL)
        self.assertEqual(self.sent, [(10111, osc_message('/machinista/param', 'rev_return_level', 1)),
                                     (10112, osc_message('/machinista/param', 'rev_return_level', -1))])
        self.sent.clear()
        self.mode.handle_event(button('SHIFT', 1))
        self.turn(4, KNOB_TRAVEL, after=PACE_S)
        self.assertEqual(self.sent, [(10111, osc_message('/machinista/param', 'output_level', 1))])

    def test_shift_mid_turn_drops_reverb_steps(self):
        self.toggle()
        self.turn(4, KNOB_TRAVEL)
        self.turn(4, KNOB_TRAVEL * 3, after=0.005)  # paced: waits
        self.mode.handle_event(button('SHIFT', 1))
        self.turn(4, KNOB_TRAVEL, after=0.005)
        self.now += PACE_S
        self.mode.flush()
        self.assertEqual(self.sent[1:], [(10111, osc_message('/machinista/param', 'output_level', 1))])

    def test_osc_string_argument(self):
        data = osc_message('/machinista/param', 'output_level', -2)
        self.assertEqual(len(data) % 4, 0)
        self.assertIn(b',si\0', data)
        self.assertIn(b'output_level\0', data)
        self.assertEqual(data[-4:], struct.pack('>i', -2))

    def cc(self, port, number, value):
        return (port, osc_message('/machinista/midi', 0xB0, number, value))

    def test_layer_key_cycles_layers(self):
        self.toggle()
        for expected in (1, 2, 3, 0):
            self.assertTrue(self.mode.handle_event(button('DISPLAY 4', 1)))
            self.assertTrue(self.mode.handle_event(button('DISPLAY 4', 0)))
            self.assertEqual(self.mode.display_state()['norns'][0]['layer'], expected)
        self.assertEqual(self.mode.display_state()['norns'][1]['layer'], 0)
        self.assertEqual(self.sent, [])

    def test_layer_keys_toggle_ccs_and_light(self):
        self.toggle()
        self.mode.handle_event(button('DISPLAY 8', 1))
        self.mode.handle_event(button('DISPLAY 8', 1))  # right side on layer 2
        self.mode.handle_event(button('DISPLAY 6', 1))
        self.mode.handle_event(button('DISPLAY 6', 0))
        self.assertEqual(self.mode.leds()['DISPLAY 6'], 85)
        self.assertEqual(self.mode.leds()['DISPLAY 8'], 85)
        self.assertEqual(self.mode.leds()['DISPLAY 4'], 8)
        self.mode.handle_event(button('DISPLAY 6', 1))
        self.assertEqual(self.sent, [self.cc(10112, 109, 127), self.cc(10112, 109, 0)])
        self.assertEqual(self.mode.leds()['DISPLAY 6'], 8)

    def test_layer_knobs_send_cc_values(self):
        self.toggle()
        self.mode.handle_event(button('DISPLAY 4', 1))  # left side on layer 1
        self.turn(2, KNOB_TRAVEL * 2)
        self.assertEqual(self.sent, [self.cc(10111, 106, 2)])
        self.turn(2, -KNOB_TRAVEL * 10, after=PACE_S)
        self.assertEqual(self.sent[1:], [self.cc(10111, 106, 0)])  # clamped at 0
        self.sent.clear()
        self.turn(2, -KNOB_TRAVEL, after=PACE_S)
        self.assertEqual(self.sent, [])  # already at 0: nothing to send
        side = self.mode.display_state()['norns'][0]
        self.assertEqual((side['first_cc'], side['values']), (102, (0, 0, 0, 0, 0, 0)))

    def test_native_layer_and_system_knobs_unchanged_on_a_layer(self):
        self.toggle()
        self.mode.handle_event(button('DISPLAY 4', 1))
        self.turn(4, KNOB_TRAVEL)
        self.assertEqual(self.sent, [(10111, osc_message('/machinista/param', 'rev_return_level', 1))])
        self.sent.clear()
        self.mode.handle_event(button('DISPLAY 4', 1))
        self.mode.handle_event(button('DISPLAY 4', 1))
        self.mode.handle_event(button('DISPLAY 4', 1))  # back to native
        self.turn(1, KNOB_TRAVEL, after=PACE_S)
        self.mode.handle_event(button('DISPLAY 1', 1))
        self.assertEqual(self.sent, [(10111, osc_message('/remote/enc', 1, 1)), (10111, osc_message('/remote/key', 1, 1))])

    def test_layers_belong_to_the_norns_and_are_kept(self):
        root = tempfile.mkdtemp()
        sides = [(3, None)]
        mode = NornsMode(root, sides=lambda: sides[0], sender=lambda port, data: self.sent.append((port, data)),
                         clock=lambda: self.now)
        self.mode = mode
        self.toggle()
        mode.handle_event(button('DISPLAY 4', 1))
        mode.handle_event(button('DISPLAY 1', 1))
        sides[0] = (4, None)  # another Sound on norns 4: its own layer state
        self.assertEqual(mode.display_state()['norns'][0]['layer'], 0)
        self.now += LAYER_SAVE_S
        mode.flush()
        self.assertTrue(layers_path(root).exists())
        again = NornsMode(root, sides=lambda: (3, None), sender=lambda *a: None)
        side = again.display_state()['norns'][0]
        self.assertEqual((side['layer'], side['values'][0]), (1, 127))

    def test_layer_labels_come_from_the_norns(self):
        import app.norns_mode as nm
        shm = tempfile.mkdtemp()
        old = nm.SHM_ROOT
        nm.SHM_ROOT = shm
        try:
            os.makedirs(os.path.join(shm, '1'))
            with open(os.path.join(shm, '1', 'layers.txt'), 'w') as f:
                f.write('1\t1\tLF 200HZ\tLF 1KHZ\n1\t4\tMID TIME\tMID TIME\nbroken line\n')
            self.toggle()
            self.mode.handle_event(button('DISPLAY 4', 1))
            labels = self.mode.display_state()['norns'][0]['labels']
            self.assertEqual(labels[0], ('LF 200HZ', 'LF 1KHZ'))
            self.assertEqual(labels[3], ('MID TIME', 'MID TIME'))
            self.assertEqual(labels[1], ('', ''))
            self.assertEqual(self.mode.display_state()['norns'][1]['labels'], ())  # native layer
        finally:
            nm.SHM_ROOT = old

    def test_corrupt_layer_file_is_ignored(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, 'config'))
        with open(layers_path(root), 'w') as f:
            f.write('{"1": {"layer": 9, "values": [["x"]]}, "2": 5}')
        mode = NornsMode(root, sides=lambda: (1, 2), sender=lambda *a: None)
        self.assertEqual([s['layer'] for s in mode.display_state()['norns']], [0, 0])

    def test_osc_encoding(self):
        data = osc_message('/remote/enc', 1, -3)
        self.assertEqual(len(data) % 4, 0)
        self.assertEqual(data[-4:], struct.pack('>i', -3))


class FakeApp:
    def __init__(self, plugins):
        self.plugins = plugins

    def track(self):
        return {'plugins': self.plugins}


class SoundNornsTest(unittest.TestCase):
    def test_reads_first_instrument_and_effect(self):
        app = FakeApp([
            {'uri': INSTRUMENT_URI, 'controls': {'norns': 3.0}},
            {'uri': 'urn:other', 'controls': {}},
            {'uri': EFFECT_URI, 'controls': {'norns': 5}},
            {'uri': EFFECT_URI, 'controls': {'norns': 7}},
        ])
        self.assertEqual(sound_norns(app), (3, 5))

    def test_defaults_and_missing(self):
        self.assertEqual(sound_norns(FakeApp([{'uri': EFFECT_URI, 'controls': {}}])), (None, 2))
        self.assertEqual(sound_norns(FakeApp([{'uri': INSTRUMENT_URI, 'controls': {'norns': 42}}])), (1, None))
        self.assertEqual(sound_norns(FakeApp([])), (None, None))
        self.assertEqual(sound_norns(object()), (None, None))


class NornsDisplayTest(unittest.TestCase):
    def test_draws_empty_and_offline_sides(self):
        from app.norns_display import images
        left, right = images({'norns': ({'name': None, 'role': 'INSTRUMENT', 'frame': '', 'mtime': None},
                                        {'name': '2', 'role': 'EFFECT', 'frame': '/nonexistent', 'mtime': None})})
        self.assertEqual(left.size, (480, 272))
        self.assertEqual(right.size, (480, 272))

    def test_draws_a_midi_layer(self):
        from app.norns_display import images
        layer = {'name': '1', 'role': 'INSTRUMENT', 'frame': '/nonexistent', 'mtime': None, 'layer': 2,
                 'values': (127, 0, 0, 64, 0, 127), 'first_cc': 108}
        left, _ = images({'norns': (layer, {'name': None, 'role': 'EFFECT', 'frame': '', 'mtime': None})})
        self.assertEqual(left.size, (480, 272))


if __name__ == '__main__':
    unittest.main()
