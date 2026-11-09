import array
from collections import OrderedDict
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
from app.model import Application
from app.native_sequence import sequence_commands,NativeSequence
from app.audio import AudioBackend

ROOT=Path(__file__).resolve().parent.parent

class NativeSequenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.a=Application(self.temp.name)
    def test_compile_preserves_keyboard_zone_chord_groove_mute_and_midi(self):
        a=self.a;a.active_clips[0]=True;a.clock_phase=0
        a.track().update(sample='fixture.wav',start=0,end=1000,note=36)
        from app.sampler import default_zone
        z=default_zone(a.track());z.update(key_lo=38,key_hi=38,root=38,start=300,end=500)
        a.track()['zones']=[z];a.track()['routing']={'midi_send':True}
        a.timing()['swing']=50
        a.put_event((0,48,'x'),dict(_id='x',note=38,velocity=91,probability=73,length=29))
        commands=sequence_commands(a)
        self.assertIn('sequence_event 60 29 73 0',commands)
        self.assertTrue(any(c.startswith('hit 1027 ') and ' 38 0' in c for c in commands),commands)
        self.assertIn('range 1027 300 500',commands)
        self.assertIn('external_note 0 38 91 0 0',commands)
        a.track()['mute']=True
        self.assertFalse(any(c.startswith('hit ') for c in sequence_commands(a)))
    def test_cached_hit_payload_changes_when_sound_parameters_change(self):
        a=self.a
        a.active_clips[0]=True
        a.track().update(sample='fixture.wav',start=0,end=100)
        a.put_note(0,0,dict(velocity=100,probability=100))
        a.put_note(0,24,dict(velocity=100,probability=100))
        cache=OrderedDict()
        original=sequence_commands(a,payload_cache=cache)
        self.assertEqual(original,sequence_commands(a,payload_cache=cache))
        self.assertEqual(len(cache),1)
        a.track().setdefault('sampler',{})['vel_volume']=0
        updated=sequence_commands(a,payload_cache=cache)
        self.assertNotEqual(original,updated)
        self.assertEqual(updated,sequence_commands(a))

    def test_native_clock_suppresses_duplicate_tick_notes_but_keeps_live_pads(self):
        a=self.a;a.active_clips[0]=True;a.playing=True;a.native_sequence=True;a.timing()['metro']=True
        a.put_note(0,0,dict(velocity=100,probability=100));a.actions=[];a.clock_tick(0)
        self.assertFalse(any(k in ('hit','event_hit','click','note_gate') for k,v in a.actions))
        a.pad_on(0,100);self.assertTrue(any(k=='hit' for k,v in a.actions))
    def test_live_recording_timestamp_and_duration_ignore_processing_delay(self):
        a=self.a;a.playing=a.recording=True;a.native_sequence=True;a.clock_phase=100;a.step=4;a.clock_last=10
        a.timing()['record_quantize']=False;a.input_timestamp=9.9
        with patch('app.timing.time.monotonic',return_value=11):a.pad_on(0,100)
        tick=(100+round(-.1/a.clock_interval()))%a.pattern_ticks()
        self.assertIn((0,tick),a.notes())
        a.input_timestamp=10.1
        with patch('app.surface.time.monotonic',return_value=12):a.release_pad(0)
        self.assertEqual(a.notes()[(0,tick)]['length'],round(.2/a.clock_interval()))
    def test_audio_clock_catches_up_display_after_stall_without_burst_notes(self):
        from app.sequencer_clock import advance_clock
        a=self.a;a.active_clips[0]=True;a.playing=True;a.native_sequence=True;a.clock_phase=0;a.step=0
        a.put_note(0,0,dict(velocity=100,probability=100));a.actions=[]
        n=NativeSequence();n.transport=(True,120,False,0);n.reset_pending=False
        n.receive(a,dict(kind='sequence_clock',status='ready',epoch=n.epoch,tick=396,stamp=2))
        deadline=n.deadline(a,2,0);advance_clock(a,deadline,2)
        self.assertEqual(a.clock_phase,396)
        self.assertFalse(any(k in ('hit','event_hit','note_gate') for k,v in a.actions))
        self.assertEqual(a.pattern_position(),'1:1:1' if a.pattern_ticks()==384 else '2:1:1')

    def test_restart_and_seek_during_playback_cannot_reuse_old_audio_position(self):
        a=self.a;a.playing=True;a.native_sequence=True;a.clock_phase=900;a.step=37;a.actions=[]
        n=NativeSequence();n.transport=(True,120,False,0);n.reset_pending=False
        n.clock=dict(tick=900,stamp=10);commands=[];audio=type('Audio',(),{'command':commands.append})()
        a.button('RESTART',True)
        deadline=n.deadline(a,10,9)
        self.assertIsNone(n.clock);self.assertGreater(deadline,10);self.assertEqual(a.clock_phase,-1)
        a.actions=[];n.update(a,audio,None,10,deadline)
        self.assertTrue(any(c.startswith('sequence_seek 0.000000000 ') for c in commands))
        old_epoch=n.epoch;n.clock=dict(tick=900,stamp=10);a.clock_phase=384;a.step=16
        a.actions=[('panic',None)]
        deadline=n.deadline(a,10.1,9);a.actions=[];n.update(a,audio,None,10.1,deadline)
        self.assertTrue(any(c.startswith('sequence_seek 384.000000000 ') for c in commands))
        n.receive(a,dict(kind='sequence_clock',status='ready',epoch=old_epoch,tick=900,stamp=10.2))
        self.assertIsNone(n.clock)
        # Retriggering the same Scene also creates a new audio-clock epoch.
        a.native_transport_revision=1;a.clock_phase=0;a.step=0;before=n.epoch
        n.update(a,audio,None,11,11+a.clock_interval())
        self.assertGreater(n.epoch,before)
        self.assertIn(f'sequence_seek 0.000000000 {n.epoch}',commands)

    def test_bar_locate_with_short_scene_seeks_native_audio_to_displayed_previous_bar(self):
        a=self.a;a.set_pattern_length(64);a.project['scene_lengths'][str(a.scene)]=16
        a.playing=True;a.native_sequence=True;a.clock_phase=864;a.step=36;a.actions=[]
        n=NativeSequence();n.transport=(True,120,False,0);n.reset_pending=False;n.clock=dict(tick=864,stamp=10)
        commands=[];audio=type('Audio',(),{'command':commands.append})()
        a.button('TRANSPORT LEFT',True);a.button('TRANSPORT LEFT',False)
        deadline=n.deadline(a,10,9);self.assertEqual(a.pattern_position(),'2:2:1');self.assertIsNone(n.clock)
        a.actions=[];n.update(a,audio,None,10,deadline)
        self.assertTrue(any(c.startswith('sequence_seek 480.000000000 ') for c in commands))
        self.assertEqual(a.project['scene_lengths'][str(a.scene)],16)

    def test_controller_rebuilds_only_changed_plans_and_rejects_stale_clock(self):
        a=self.a;commands=[];audio=type('Audio',(),{'command':commands.append})();n=NativeSequence()
        n.update(a,audio,None,1,1);self.assertEqual(commands.count('sequence_begin'),0) # batches contain complete plan
        count=len(commands);n.update(a,audio,None,1.01,1);self.assertEqual(len(commands),count)
        a.playing=True;n.update(a,audio,None,2,2)
        n.receive(a,dict(kind='sequence_clock',status='ready',epoch=n.epoch-1,tick=900,stamp=2));self.assertIsNone(n.clock)
        n.receive(a,dict(kind='sequence_clock',status='ready',epoch=n.epoch,tick=96,stamp=2));self.assertAlmostEqual(n.deadline(a,2,5),2-96*a.clock_interval())
        a.remember();a.track()['mute']=True;n.update(a,audio,None,2.01,2.02)
        self.assertEqual(sum(c.startswith('sequence_begin') for c in commands),2)
        a.settings['midi_sync']='IN';n.update(a,audio,None,2.02,2.03)
        self.assertFalse(a.native_sequence);self.assertIn('panic',commands)

@unittest.skipUnless((ROOT/'build/audio_engine').exists() and Path('/usr/share/alsa/alsa.conf').exists(),'Linux ALSA build required')
class NativeSequenceRenderTests(unittest.TestCase):
    def test_pcm_loops_and_gates_continue_without_ui_or_control_commands(self):
        for rate in (44100,48000):
            with self.subTest(rate=rate):self.render_rate(rate)

    def render_rate(self,rate):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);pcm=root/'sample.f32';pcm.write_bytes(array.array('f',[.5,.5]*8000).tobytes())
            output=root/'render.raw';config=root/'alsa.conf'
            config.write_text('</usr/share/alsa/alsa.conf>\n'+f'pcm.fixture {{ type file slave.pcm "null" file "{output}" format "raw" }}\n')
            p=subprocess.Popen([str(ROOT/'build/audio_engine')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=dict(os.environ,ALSA_CONFIG_PATH=str(config)))
            def send(c):p.stdin.write(c+'\n');p.stdin.flush()
            try:
                send(f'load 0 {rate} '+json.dumps(str(pcm)))
                encoder=AudioBackend.__new__(AudioBackend);commands=[];encoder.command=commands.append;encoder.tempo=240
                encoder._params(0,{'sampler':{'type':'ADSR','attack':0,'decay':0,'sustain':100,'release':0}})
                send('sequence_begin\nsequence_lane 24\nsequence_event 0 12 100 0\n'+commands[0]+'\nhit 0 1 1 36\nsequence_commit')
                self.assertEqual(json.loads(p.stdout.readline())['kind'],'sequence')
                send('sequence_seek 0 17\nsequence_transport 240 1\ndevice "fixture" '+str(rate))
                self.assertEqual(json.loads(p.stdout.readline())['status'],'ready')
                send('wave_watch 1 0 0')
                # Deliberately no UI ticks, hits, note-offs, clock or transport updates.
                time.sleep(.4)
                send('sequence_status');status=json.loads(p.stdout.readline())
                self.assertGreaterEqual(status['emitted'],4);self.assertEqual(status['overflow'],0)
                send('device "-"');self.assertEqual(json.loads(p.stdout.readline())['status'],'idle')
                values=array.array('h');values.frombytes(output.read_bytes());left=values[::2]
                starts=[i for i,v in enumerate(left) if v>1000 and (i==0 or left[i-1]<=1000)]
                ends=[i for i,v in enumerate(left) if v<=1000 and i and left[i-1]>1000]
                self.assertGreaterEqual(len(starts),4)
                period=rate/16
                for i,frame in enumerate(starts):self.assertLessEqual(abs(frame-i*period),1)
                # Existing ADSR emits the release-edge sample before reaching zero.
                for start,end in zip(starts,ends):self.assertLessEqual(abs(end-start-1-period/2),1)
                send('quit');_,error=p.communicate(timeout=5);self.assertEqual(p.returncode,0,error)
            finally:
                if p.poll() is None:p.kill();p.communicate()

    def test_native_midi_and_clock_continue_without_audio_interface(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'midi';path.touch()
            p=subprocess.Popen([str(ROOT/'build/audio_engine')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            def send(c):p.stdin.write(c+'\n');p.stdin.flush()
            try:
                send('midi_device '+json.dumps(str(path)))
                send('sequence_begin\nsequence_lane 24\nsequence_event 0 12 100 0\nexternal_note 2 60 100 0 7\nsequence_commit')
                self.assertEqual(json.loads(p.stdout.readline())['kind'],'sequence')
                send('sequence_seek 0 18\nsequence_transport 240 1 1 0\ndevice "-" 48000')
                self.assertEqual(json.loads(p.stdout.readline())['status'],'idle')
                time.sleep(.3) # no UI/clock/hit/off commands
                send('sequence_status');event=json.loads(p.stdout.readline())
                self.assertGreaterEqual(event['emitted'],4);self.assertEqual(event['overflow'],0);self.assertEqual(event['midi_errors'],0)
                send('panic');time.sleep(.03)
                send('quit');_,error=p.communicate(timeout=5);self.assertEqual(p.returncode,0,error)
                data=path.read_bytes();notes=[];clocks=0;i=0
                while i<len(data):
                    if data[i]==0xf8:clocks+=1;i+=1
                    else:notes.append(tuple(data[i:i+3]));i+=3
                ons=[msg for msg in notes if msg==(0x92,60,100)]
                offs=[msg for msg in notes if msg==(0x82,60,0)]
                self.assertGreaterEqual(len(ons),4);self.assertGreaterEqual(len(offs),4);self.assertGreaterEqual(clocks,20)
                self.assertIn((0xb2,123,0),notes)
            finally:
                if p.poll() is None:p.kill();p.communicate()

    def test_overlapping_native_midi_pitch_releases_after_last_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'midi';path.touch()
            p=subprocess.Popen([str(ROOT/'build/audio_engine')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            def send(c):p.stdin.write(c+'\n');p.stdin.flush()
            try:
                send('midi_device '+json.dumps(str(path)))
                send('sequence_begin\nsequence_lane 96\nsequence_event 0 36 100 0\nexternal_note 2 60 100\nsequence_event 12 36 100 0\nexternal_note 2 60 100\nsequence_commit')
                self.assertEqual(json.loads(p.stdout.readline())['status'],'ready')
                send('sequence_seek 0\nsequence_transport 240 1\ndevice "-" 48000');p.stdout.readline()
                time.sleep(.45)
                send('quit');_,error=p.communicate(timeout=5);self.assertEqual(p.returncode,0,error)
                data=path.read_bytes();notes=[tuple(data[i:i+3]) for i in range(0,len(data),3) if data[i] in (0x92,0x82)]
                self.assertEqual(notes[:6],[(0x92,60,100),(0x92,60,100),(0x82,60,0)]*2)
            finally:
                if p.poll() is None:p.kill();p.communicate()
