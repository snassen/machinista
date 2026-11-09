import tempfile,unittest
from app.model import Application,validate_project
from app.native_sequence import sequence_commands

class RecordStartTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.a=Application(self.tmp.name);self.a.fixed_velocity=False
 def arm_play(self):
  self.a.button('REC',True);self.a.button('REC',False);self.a.button('PLAY',True);self.a.button('PLAY',False)
 def test_first_kick_before_first_clock_is_saved_and_not_echoed(self):
  a=self.a;self.arm_play();self.assertEqual(a.step,-1)
  a.pad_on(0,107);self.assertIn((0,0),a.notes());self.assertEqual(a.notes()[(0,0)]['velocity'],107)
  self.assertEqual(sum(k=='hit' for k,v in a.actions),1)
  a.actions=[];a.clock_tick(10)
  self.assertFalse(any(k in ('hit','event_hit') for k,v in a.actions))
  for tick in range(1,a.pattern_ticks()+1):a.clock_tick(10+tick*a.clock_interval())
  self.assertEqual(sum(k=='hit' for k,v in a.actions),1)
  validate_project(a.project)
 def test_initial_timestamp_ignores_stale_stopped_clock_and_clamps_negative_start(self):
  a=self.a;self.arm_play();a.timing()['record_quantize']=False;a.clock_last=1;a.input_timestamp=100
  a.pad_on(1,99);self.assertIn((1,0),a.notes())
  a.step=0;a.clock_phase=0;a.clock_last=101;a.input_timestamp=101-a.clock_interval()
  a.input_timestamp=20+384*a.clock_interval();a.pad_on(2,100);self.assertIn((2,0),a.notes());self.assertNotIn((2,a.pattern_ticks()-1),a.notes())
 def test_first_keyboard_note_and_native_plan_do_not_skip_downbeat(self):
  a=self.a;a.keyboard_enabled=True;a.keyboard_root=60;self.arm_play();a.pad_on(0,100)
  self.assertTrue(any(key[:2]==(0,0) and event.get('note')==60 for key,event in a.event_notes().items()))
  commands=sequence_commands(a)
  self.assertTrue(any(c.startswith('sequence_event 0 ') and c.split()[-1]=='1' for c in commands))
 def test_count_in_rejects_early_pads_but_accepts_first_note_after_completion(self):
  a=self.a;a.start_count_in();a.pad_on(2,100);self.assertFalse(a.notes())
  for tick in range(384):a.clock_tick(20+tick*a.clock_interval())
  self.assertEqual(a.step,-1);self.assertTrue(a.playing and a.recording)
  a.input_timestamp=20+384*a.clock_interval();a.pad_on(2,100);self.assertIn((2,0),a.notes())
 def test_no_record_without_rec_or_while_only_armed_and_restart_is_safe(self):
  a=self.a;a.button('PLAY',True);a.pad_on(0,100);self.assertFalse(a.notes())
  a.button('PLAY',True);a.button('REC',True);a.pad_on(1,100);self.assertFalse(a.notes())
  a.button('PLAY',True);a.clock_tick(30);a.button('RESTART',True);a.pad_on(2,100)
  self.assertIn((2,0),a.notes())
 def test_regular_unquantized_loop_boundary_stays_at_end_of_previous_loop(self):
  a=self.a;self.arm_play();a.step=16;a.clock_phase=384;a.clock_last=12;a.input_timestamp=12-a.clock_interval()
  a.timing()['record_quantize']=False;a.pad_on(3,100)
  self.assertIn((3,383),a.notes())

 def test_count_boundary_uses_hardware_time_before_ui_clock_catches_up(self):
  from app.sequencer_clock import advance_clock
  a=self.a;a.start_count_in();interval=a.clock_interval()
  for tick in range(383):a.clock_tick(10+tick*interval)
  self.assertEqual(a.count_remaining,1)
  boundary=12
  a.input_timestamp=boundary-.061;a.pad_on(0,100)
  self.assertFalse(a.notes())
  a.input_timestamp=boundary;a.pad_on(1,109)
  self.assertIn((1,0),a.notes());self.assertEqual(a.notes()[(1,0)]['velocity'],109)
  a.actions=[];advance_clock(a,10+383*interval,boundary)
  self.assertTrue(a.playing and a.recording);self.assertEqual(a.clock_phase,0)
  self.assertFalse(any(k in ('hit','event_hit') for k,v in a.actions))
 def test_count_in_captures_slightly_early_downbeat_without_echo(self):
  for drained in (False,True):
   with self.subTest(drained=drained):
    a=Application(self.tmp.name);a.fixed_velocity=False;a.start_count_in()
    interval=a.clock_interval()
    for tick in range(384 if drained else 383):a.clock_tick(20+tick*interval)
    a.actions=[]
    boundary=20+384*interval
    a.input_timestamp=boundary-.052
    a.pad_on(0,111)
    self.assertEqual(a.notes()[(0,0)]['velocity'],111)
    self.assertEqual(sum(action=='hit' for action,_ in a.actions),1)
    a.actions=[]
    if not drained:a.clock_tick(boundary-interval)
    a.clock_tick(boundary)
    self.assertFalse(any(action in ('hit','event_hit') for action,_ in a.actions))

 def test_count_in_not_yet_anchored_does_not_use_a_stale_previous_clock(self):
  a=self.a;a.clock_last=1;a.input_timestamp=100;a.start_count_in();a.pad_on(0,100)
  self.assertFalse(a.notes())

 def test_native_initial_skip_survives_ui_tick_until_plan_publication(self):
  a=self.a;a.native_sequence=True;self.arm_play();a.pad_on(0,100);a.clock_tick(10)
  self.assertEqual(a.clock_phase,0)
  self.assertTrue(any(c.startswith('sequence_event 0 ') and c.split()[-1]=='1' for c in sequence_commands(a)))
  for tick in range(1,385):a.clock_tick(10+tick*a.clock_interval())
  self.assertFalse(a.record_live_skip)
 def test_native_pad_at_initial_tick_zero_also_avoids_a_double_attack(self):
  a=self.a;a.native_sequence=True;self.arm_play();a.clock_tick(10);a.input_timestamp=10;a.pad_on(0,100)
  self.assertIn((0,0),a.notes())
  self.assertTrue(any(c.startswith('sequence_event 0 ') and c.split()[-1]=='1' for c in sequence_commands(a)))

 def test_first_bar_uses_count_in_time_for_multiple_pads_despite_clock_handoff(self):
  a=self.a;a.project['tempo']=110;a.start_count_in();interval=a.clock_interval()
  downbeat=20
  for tick in range(384):a.clock_tick(downbeat+(tick-384)*interval)
  # Replay the offsets observed on the MK3. The UI phase lagged the count.
  for pad,seconds,phase,expected in ((1,.48658655,81,96),(2,.50043193,82,96),
                                     (2,.76707241,130,144),(2,1.03776965,178,192),
                                     (0,1.04572831,179,192)):
   a.clock_phase=phase;a.clock_last=downbeat+seconds-.002
   a.input_timestamp=downbeat+seconds
   a.pad_on(pad,100)
   self.assertEqual(a.last_recorded[3],expected)

 def test_live_quantization_rounds_only_at_grid_boundary(self):
  a=self.a;self.arm_play();a.clock_phase=11;a.clock_last=20
  a.input_timestamp=20+.75*a.clock_interval()
  a.pad_on(0,100)
  self.assertIn((0,0),a.notes())
  self.assertNotIn((0,24),a.notes())
