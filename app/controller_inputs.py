"""Source-owned physical inputs, shared application, exact live voice releases.

The runtime dispatches controller_hit/controller_off actions in its normal queue.
No audio, USB or filesystem operations occur in this adapter.
"""
import copy
from app.live_timing import LiveTiming
from app.controller_settings import controller_context


class ControllerInputs:
    def __init__(self,app):
        self.app=app;self.timing=LiveTiming()
        self.buttons={}
        self.pads={}
        self.serial=1<<60  # MIDI owns bit61; sequencer owns bit63.
        self.generation=app.project_generation

    def sync(self):
        if self.generation!=self.app.project_generation:
            # Project changes already panic the engine. Physical modifiers remain
            # owned until release, but old note bindings cannot enter a new project.
            self.pads.clear();self.timing.clear()
            self.generation=self.app.project_generation

    def button(self,source,name,pressed):
        self.sync()
        owners=self.buttons.setdefault(name,set())
        if pressed:
            if source in owners:return
            first=not owners;owners.add(source)
            if first:
                with controller_context(self.app,source):self.app.button(name,True)
        else:
            if source not in owners:return
            owners.remove(source)
            if not owners:
                self.buttons.pop(name,None)
                with controller_context(self.app,source):self.app.button(name,False)

    def pad_on(self,source,slot,velocity):
        if getattr(self.app,'autosampling',False):return
        self.sync()
        key=(source,slot)
        if key in self.pads:return
        app=self.app;start=len(app.actions)
        tracing=app.recording or bool(app.count_remaining)
        app.pad_on(slot,velocity,owner=source)
        if tracing:
            app.record_diagnostics.append(dict(source=source,pad=slot+1,page=app.page,
                stamp=getattr(app,'input_timestamp',None),phase=app.clock_phase,count=app.count_remaining,
                clock=app.clock_last,interval=app.clock_interval(),
                downbeat=app.count_downbeat,recorded=getattr(app,'last_recorded',None)))
        targets=[];actions=[]
        for action,value in app.actions[start:]:
            if action not in ('hit','event_hit','midi_note','chord_note'):
                actions.append((action,value));continue
            delay=0
            if action in ('midi_note','chord_note'):
                group,original=app.group,app.pad;note,velocity,_=value[:3]
                if action=='chord_note':delay=value[3]
            else:
                group,original,velocity=value[:3]
                note=value[3] if action=='event_hit' else app.project['groups'][group]['pads'][original].get('note',36+original)
            track=app.project['groups'][group]['pads'][original]
            semitones=note-track.get('note',36+original)
            self.serial+=1;token=self.serial
            for slot_target in app.linked_sounds(group,original):
                target=app.project['groups'][group]['pads'][slot_target]
                target_note=max(0,min(127,target.get('note',36+slot_target)+semitones))
                external=target.get('source')=='MIDI' or bool(target.get('routing',{}).get('midi_send'))
                targets.append((group,slot_target,target_note,target['channel'],external,token))
                actions.append(('controller_hit',(group,slot_target,velocity,semitones,token,copy.deepcopy(target),target_note,external,delay)))
        app.actions[start:]=actions
        self.pads[key]=tuple(targets)

    def pad_pressure(self,source,slot,velocity):
        self.sync()
        if (source,slot) not in self.pads:return
        if self.app.live_fx_pad_pressure(slot,velocity,source):return
        if slot in self.app.repeat_pads:self.app.repeat_velocities[slot]=velocity

    def pad_off(self,source,slot):
        self.sync();key=(source,slot)
        if key not in self.pads:return
        targets=self.pads.pop(key);app=self.app;start=len(app.actions)
        app.release_pad(slot,owner=source,still_held=any(s==slot for _,s in self.pads))
        # Legacy note_off resolves current focus/links and has token0. Replace
        # only this release's actions with its captured attack destinations.
        app.actions[start:]=[(a,v) for a,v in app.actions[start:] if a!='note_off']
        app.actions.extend(('controller_off',target) for target in targets)

    def disconnect(self,source):
        for owner,slot in list(self.pads):
            if owner==source:self.pad_off(source,slot)
        for name,owners in list(self.buttons.items()):
            if source in owners:self.button(source,name,False)

    def dispatch(self,action,value,audio,midi):
        if action=='panic':self.timing.clear()
        if action=='note_off':
            group,slot,note=value;matched=False
            for key,targets in list(self.pads.items()):
                if targets and targets[0][:2]==(group,slot) and (note is None or targets[0][2]==note):
                    for target in targets:self.dispatch('controller_off',target,audio,midi)
                    self.pads[key]=();matched=True
            if matched and note is not None:return True
        if action=='controller_hit':
            group,slot,velocity,semitones,token,track,note,external=value[:8]
            delay=value[8] if len(value)>8 else 0
            def attack():
                if external:midi.hit(slot,velocity,note,track['channel'],duration=None,voice_token=token)
                if track.get('source')!='MIDI' or track.get('sample') or track.get('plugins') or track.get('routing',{}).get('midi_target','NONE')!='NONE':
                    audio.hit(group,slot,velocity,dict(track,gain=100),semitones,token)
            if not self.timing.add(delay,token,attack):self.app.message='CHORD VOICE LIMIT'
            return True
        if action=='controller_off':
            group,slot,note,channel,external,token=value
            self.timing.cancel(token)
            audio.note_off(group,slot,note,token)
            if external:midi.note_off(note,channel,token)
            return True
        return False
