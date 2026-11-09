import json
import os
from pathlib import Path
import tempfile
import unittest
import wave
from unittest.mock import patch

from app.devices import AudioDevice, choose_audio, discover
from app.model import Application
from app.audio import convert_sample


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = Application(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_main_navigation_and_remembered_audio_preference(self):
        a = AudioDevice('usb-a', 'Interface A', 'plughw:3,0', 'plughw:3,0')
        b = AudioDevice('usb-b', 'Interface B', 'plughw:4,0', None)
        self.app.refresh_devices([a, b], [])
        self.assertEqual(self.app.audio, a)
        self.app.button('SHIFT', True);self.app.button('MAIN', True);self.app.button('SHIFT', False)
        self.assertEqual(self.app.page, 'SETTINGS')
        self.app.button('ENTER', True)
        self.assertEqual(self.app.page, 'AUDIO')
        self.app.rotate(2)
        self.assertEqual(self.app.audio, b)
        self.app.refresh_devices([a], [])
        self.assertIsNone(self.app.audio)
        restored = Application(self.root)
        restored.refresh_devices([b, a], [])
        self.assertEqual(restored.audio, b)

    def test_auto_hotplug_retains_current_and_survives_card_renumbering(self):
        a = AudioDevice('usb-a', 'A', 'plughw:3,0', None)
        b = AudioDevice('usb-b', 'B', 'plughw:4,0', None)
        self.assertIsNone(choose_audio([], 'AUTO'))
        self.assertEqual(choose_audio([a, b], 'AUTO', 'usb-b'), b)
        self.assertEqual(choose_audio([a], 'AUTO', 'usb-b'), a)
        moved = AudioDevice('usb-b', 'B', 'plughw:7,0', None)
        self.assertEqual(choose_audio([moved], 'usb-b'), moved)

    def test_discovery_ignores_builtin_and_identifies_usb_by_serial(self):
        sound, proc, dev = self.root/'sys', self.root/'proc', self.root/'dev'
        for path in (sound, proc, dev):
            path.mkdir()
        usb = self.root/'usb-device'
        usb.mkdir()
        for key, value in [('idVendor', '1234'), ('idProduct', '5678'), ('serial', 'serial-a'), ('product', 'Test Audio')]:
            (usb/key).write_text(value)
        (sound/'card3').mkdir()
        (sound/'card3/device').symlink_to(usb, target_is_directory=True)
        (sound/'card0/device').mkdir(parents=True)
        (proc/'card3/pcm2p').mkdir(parents=True)
        (proc/'card3/pcm2c').mkdir()
        (proc/'card0/pcm0p').mkdir(parents=True)
        (dev/'midiC3D0').touch()
        audio, midi = discover(sound, proc, dev)
        self.assertEqual(len(audio), 1)
        self.assertEqual(audio[0].key, '1234:5678:serial-a:pcm2')
        self.assertEqual(audio[0].capture, 'plughw:3,2')
        self.assertEqual(len(midi), 1)

    def test_step_edit_copy_undo_and_atomic_project_roundtrip(self):
        self.app.button('SHIFT', True)
        self.app.button('NOTE REPEAT', True)
        self.app.button('SHIFT', False)
        self.assertEqual(self.app.page, 'STEP')
        self.app.pad_on(3)
        self.assertTrue(self.app.lane()[3])
        self.app.page = 'PATTERN'
        self.app.button('F2', True)
        self.assertEqual(self.app.pattern, 1)
        self.app.page = 'STEP'
        self.app.pad_on(3)
        self.assertFalse(self.app.lane()[3])
        self.assertTrue(self.app.project['groups'][0]['patterns'][0][0][3])
        self.app.button('SHIFT', True)
        self.app.pad_on(0)
        self.app.button('SHIFT', False)
        self.app.page = 'PROJECT'
        self.app.button('F1', True)
        self.assertFalse(self.app.dirty)
        restored = Application(self.root)
        self.assertTrue(restored.project['groups'][0]['patterns'][1][0][3])
        self.assertFalse(self.app.project_path.with_suffix('.json.tmp').exists())

    def test_blue_group_pad_layout(self):
        self.app.button('GROUP', True)
        self.app.pad_on(8)
        self.assertEqual(self.app.group, 4)
        self.app.pad_on(0)
        self.assertEqual(self.app.group, 4)
        self.app.pad_on(12)
        self.assertEqual(self.app.group, 0)
        self.app.pad_on(15)
        self.assertEqual(self.app.group, 3)

    def test_sequencer_plays_multiple_groups_and_respects_mute_solo(self):
        self.app.project['groups'][0]['patterns'][0][0][0] = True
        self.app.project['groups'][1]['patterns'][0][2][0] = True
        self.app.project['groups'][1]['pads'][2]['mute'] = True
        self.app.playing = True
        self.app.tick()
        self.assertEqual(self.app.actions, [('hit', (0, 0, 100))])
        self.app.actions.clear()
        self.app.step = -1
        self.app.project['groups'][1]['pads'][2]['mute'] = False
        self.app.tick()
        self.assertIn(('hit', (1, 2, 100)), self.app.actions)

    def test_browser_assigns_pcm_and_blocks_external_symlinks(self):
        wav_path = self.app.samples/'kick.wav'
        with wave.open(str(wav_path), 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(44100)
            wav.writeframes(b'\x00\x40'*100)
        (self.root/'outside.wav').write_bytes(wav_path.read_bytes())
        (self.app.samples/'escape.wav').symlink_to(self.root/'outside.wav')
        self.assertEqual(self.app.entries(), [wav_path])
        self.app.button('BROWSE', True)
        self.app.button('ENTER', True)  # SD CARD source
        self.app.button('ENTER', True)
        track = self.app.track()
        self.assertEqual(track['end'], 100)
        track['start'], track['end'] = 10, 20
        cache = self.root/'sample.f32'
        self.assertEqual(convert_sample(track, cache), 44100)
        self.assertEqual(cache.stat().st_size, 10*2*4)
        import struct
        self.assertEqual(struct.unpack('<f', cache.read_bytes()[:4])[0], 0.5)

    def test_kit_scroll_updates_selection_before_debounced_preview(self):
        app=self.app
        folder=self.root/'presets/Groups/Test Expansion'
        for name in ('A','B','C'):
            kit=folder/name;kit.mkdir(parents=True)
            (kit/'Set.json').write_text(json.dumps(dict(name=name)))
            (kit/'.preview.wav').touch()
        app.page='BROWSE';app.browser.directory=folder;app.browser.prehear=True;app.audio=True
        with patch('app.model.time.monotonic',return_value=10):
            app._rotate(1)
        self.assertEqual(app.browser.selected().name,'B')
        app.browser_preview_tick(10.49)
        self.assertEqual(app.actions,[])
        with patch('app.model.time.monotonic',return_value=10.25):
            app._rotate(1)
        app.browser_preview_tick(10.5)
        self.assertEqual(app.actions,[])
        app.browser_preview_tick(10.75)
        self.assertEqual(app.actions,[('preview',folder/'C'/'.preview.wav')])

    def test_single_bank_kit_loads_on_first_enter(self):
        app=self.app
        folder=self.root/'presets/Groups'
        kit=folder/'Test Kit'
        bank=kit/'bank-001'
        bank.mkdir(parents=True)
        (kit/'Set.json').write_text(json.dumps(dict(name='Test Kit')))
        (bank/'Preset.json').touch()
        app.page='BROWSE';app.browser.directory=folder
        app.enter()
        self.assertEqual(app.browser.directory,folder)
        self.assertEqual(app.actions[-1][0],'preset_load')
        self.assertEqual(app.actions[-1][1]['path'],str(bank/'Preset.json'))
        other=kit/'bank-002';other.mkdir();(other/'Preset.json').touch()
        app.actions.clear()
        app.enter()
        self.assertEqual(app.browser.directory,kit)
        self.assertFalse(any(action=='preset_load' for action,_ in app.actions))

    def test_no_input_does_not_start_sampling_and_tap_tempo(self):
        self.app.button('SAMPLING', True)
        self.app.button('F1', True)
        self.assertEqual(self.app.message, 'NO AUDIO INPUT')
        self.assertEqual(self.app.actions, [])
        self.app.button('SHIFT', True)
        for now in (10,10.5,11):
            with patch('app.model.time.monotonic', return_value=now):
                self.app.button('ENTER', True)
        self.assertEqual(self.app.project['tempo'], 120)

    def test_corrupt_project_is_not_silently_overwritten(self):
        self.app.project_path.parent.mkdir()
        self.app.project_path.write_text('{broken')
        with self.assertRaises(json.JSONDecodeError):
            Application(self.root)
        self.assertEqual(self.app.project_path.read_text(), '{broken')


if __name__ == '__main__':
    unittest.main()
