"""Compile immutable pattern snapshots; audio owns note times and gate releases."""
import math
import json
from collections import OrderedDict
import hashlib
import time
from app.audio import AudioBackend
from app.audio_ports import cue_sound
from app.note_tokens import NoteTokens
from app.audio_loop import is_audio_sound


def sequence_commands(app,notes=True,metronome=True,payload_cache=None):
    commands=['sequence_begin']
    encoder=object.__new__(AudioBackend);encoder.command=commands.append
    encoder.tempo=app.project['tempo'];encoder.instrument_tokens=NoteTokens()
    payload_cache=payload_cache if payload_cache is not None else OrderedDict()
    track_keys={}
    def hit_commands(group,slot,velocity,track,semitones):
        address=(group,slot)
        if address not in track_keys:
            track_keys[address]=json.dumps(track,sort_keys=True,separators=(',',':'))
        key=(encoder.tempo,address,track_keys[address],velocity,semitones)
        cached=payload_cache.get(key)
        if cached is not None:
            payload_cache.move_to_end(key)
            commands.extend(cached)
            return
        start=len(commands)
        encoder.hit(group,slot,velocity,dict(track,gain=100),semitones)
        payload_cache[key]=tuple(commands[start:])
        if len(payload_cache)>2048:payload_cache.popitem(last=False)

    group_solo=any(g.get('solo',False) for g in app.project['groups'])
    total=0
    def voices(event):
        yield {k:v for k,v in event.items() if k!='poly'}
        yield from event.get('poly',{}).values()
    if getattr(app,'clip_transport',False):
        contexts=[(c['group'],c['pattern'],c) for c in app.project.get('arrangement',{}).get('clips',[])]
    else:contexts=[(g,p,None) for g,p in enumerate(app.active_patterns)]
    for group,pattern,clip in contexts:
        bank=app.project['groups'][group];length=app.pattern_ticks(group,pattern)
        commands.append(f'sequence_lane {length}')
        if clip:
            identity=int(hashlib.sha256((clip['id']+':'+str(pattern)).encode()).hexdigest()[:16],16) or 1
            commands.append(f'sequence_window {clip["start"]} {clip["start"]+clip["length"]} {clip["offset"]} {identity}')
        elif not app.active_clips[group]:continue
        group_muted=bank.get('mute',False) or group_solo and not bank.get('solo',False)
        solo=any(t['solo'] for t in bank['pads'])
        for pad,source in enumerate(bank['pads']):
            muted=group_muted or source['mute'] or solo and not source['solo']
            if is_audio_sound(source) and (not muted or cue_sound(app.project,group,pad)):
                cfg=source.get('audio_loop',{})
                commands.append(f'sequence_audio {group*16+pad} {cfg.get("bars",1)*384} {int(cfg.get("stretch",True))} {2**(cfg.get("tune",0)/12):.9f}')
        for identity,event in sorted(app.event_notes(group,pattern).items()):
            if not notes:continue
            pad,tick=identity[:2];source=bank['pads'][pad]
            if is_audio_sound(source):continue
            event_muted=group_muted or source['mute'] or solo and not source['solo']
            if event_muted and not cue_sound(app.project,group,pad):continue
            tick=app.groove_position(group,pad,tick,length)
            skip=(group,pattern,pad,event.get('_id',identity[1]))
            not_before=((max(0,app.clock_phase)+1 if clip else max(0,app.clock_phase)//length*length+tick+1) if skip in app.record_live_skip else 0)
            for voice in voices(event):
                commands.append(f'sequence_event {tick} {voice.get("length",app.grid_ticks())} {voice["probability"]} {not_before}')
                pitches=voice.get('chord') or [voice.get('note',source.get('note',36+pad))]
                for note in pitches:
                    semitones=note-source.get('note',36+pad)
                    for slot in app.linked_sounds(group,pad):
                        if event_muted and not cue_sound(app.project,group,slot):continue
                        track=bank['pads'][slot];target_note=max(0,min(127,track.get('note',36+slot)+semitones))
                        if is_audio_sound(track):continue
                        if not event_muted and (track.get('source')=='MIDI' or track.get('routing',{}).get('midi_send')):
                            commands.append(f'external_note {track["channel"]-1} {target_note} {voice["velocity"]} 0 {group*16+slot}')
                        if track.get('source')!='MIDI' or track['sample'] or track.get('plugins') or track.get('routing',{}).get('midi_target','NONE')!='NONE':
                            hit_commands(group,slot,voice['velocity'],track,semitones)
                        total+=1
                        if total>16384:raise ValueError('native sequence exceeds note capacity')
    if notes and metronome and app.timing()['metro']:
        commands.append('sequence_lane 384')
        if getattr(app,'clip_transport',False):
            from app.clip_arranger import length
            commands.append(f'sequence_window 0 {length(app.project)} 0')
        for tick in (0,96,192,288):
            commands.extend((f'sequence_event {tick} 1 100 0',f'click {int(tick==0)} {app.timing()["metro_level"]/100:.6f}'))
    if sum(c.startswith(('hit ','plugin_note ','plugin_note_ch ','external_note ','click ')) for c in commands)>16384:raise ValueError('native sequence exceeds hit capacity')
    commands.append('sequence_commit')
    return commands


class NativeSequence:
    def __init__(self):
        self.payload_cache=OrderedDict()
        self.key=None;self.rejected_key=None;self.transport=None;self.reset_pending=True;self.status_due=0
        self.clock=None;self.overflow=0;self.epoch=time.monotonic_ns();self.last_scene=None;self.seek_position=None;self.stopped_position=None;self.scene_transport_revision=0
    def reset(self,position=None):self.reset_pending=True;self.clock=None;self.seek_position=position
    def invalidate(self):self.key=None
    def update(self,app,audio,midi,now,next_tick):
        if not getattr(app,'clip_transport',False) and self.last_scene is not None and app.scene!=self.last_scene and app.settings['scene_retrigger']=='ON':self.reset(max(0,app.clock_phase))
        self.last_scene=app.scene
        revision=getattr(app,'native_transport_revision',0)
        if revision!=self.scene_transport_revision:self.reset(max(0,app.clock_phase));self.scene_transport_revision=revision
        seek=getattr(app,'native_arranger_seek',None)
        if seek is not None:self.reset(seek);app.native_arranger_seek=None
        enabled=app.settings['midi_sync']!='IN' and not app.count_remaining
        audio_only=not enabled and not app.count_remaining and any(is_audio_sound(p) for g in app.project['groups'] for p in g['pads'])
        app.native_clock_enabled=True
        app.native_sequence=enabled
        running=bool((enabled or audio_only) and app.playing)
        # The UI clock may advance before this update on PLAY. Remember the
        # stopped cursor, and consume an explicit seek only when audio starts.
        if not app.playing:self.stopped_position=max(0,app.clock_phase)
        elif not running:self.stopped_position=None;self.seek_position=None
        audio.loop_transport_running=running
        # Revision covers pattern edits; explicit runtime switches cover clip/mute changes.
        clip_mode=getattr(app,'clip_transport',False)
        key=(clip_mode,enabled,audio_only,app.project_generation,app.revision,app.project['tempo'],getattr(app,'native_sequence_serial',0),(() if clip_mode else tuple(app.active_patterns)),(() if clip_mode else tuple(app.active_clips)),
             tuple((g.get('mute',False),g.get('solo',False),tuple((p['mute'],p['solo']) for p in g['pads'])) for g in app.project['groups']),app.timing()['metro'],app.timing()['metro_level'])
        if (enabled or audio_only) and key!=self.key and key!=self.rejected_key:
            try:commands=sequence_commands(app,notes=enabled,payload_cache=self.payload_cache)
            except ValueError:
                self.rejected_key=key;app.playing=app.recording=False;app.message='SEQUENCE CAPACITY ERROR';audio.command('panic');self.reset();return
            # One control write prevents interleaving a half plan with live actions.
            audio.command('\n'.join(commands));self.key=key
        transport=(running,app.project['tempo'],app.settings['midi_sync']=='OUT',app.settings['midi_offset'])
        if transport!=self.transport or self.reset_pending:
            if self.transport and self.transport[1]!=transport[1]:self.clock=None
            if self.transport and self.transport[0] and not running:audio.command('panic')
            if running and (self.reset_pending or not self.transport or not self.transport[0]):
                fraction=max(0,min(1,1-(next_tick-now)/app.clock_interval()))
                tick=self.seek_position if self.seek_position is not None else self.stopped_position if self.stopped_position is not None else app.clock_phase+fraction if app.clock_phase>0 else 0
                self.epoch+=1;self.clock=None
                audio.command(f'sequence_seek {tick:.9f} {self.epoch}')
            audio.command(f'sequence_transport {app.project["tempo"]} {int(running)} {int(transport[2])} {transport[3]/1000:.6f}')
            self.transport=transport;self.reset_pending=False
            if running:self.seek_position=None;self.stopped_position=None
        if running and now>=self.status_due:audio.command(f'sequence_status {app.group}');self.status_due=now+.05
    def deadline(self,app,now,fallback):
        pending={action for action,value in app.actions}
        if getattr(app,'native_sequence',False) and pending.intersection(('restart','panic')):
            self.reset(0 if 'restart' in pending else max(0,app.clock_phase))
            return now+app.clock_interval()
        if not (getattr(app,'native_sequence',False) and app.playing and self.clock and self.transport and self.transport[0]):return fallback
        c=self.clock
        return c['stamp']+(app.clock_phase+1-c['tick'])*app.clock_interval()

    def receive(self,app,event):
        if event['kind'] not in ('sequence','sequence_clock'):return False
        if event['kind']=='sequence_clock':
            if event.get('epoch')!=self.epoch or self.reset_pending:return True
            self.clock=event
            if event.get('group')==app.group:
                for pad in range(16):
                    if event.get('pads',0)&(1<<pad):app.flash_until[pad]=time.monotonic()+.08
            if event.get('overflow',0)>self.overflow or event.get('midi_errors',0):app.message='SEQUENCE CAPACITY ERROR'
            self.overflow=event.get('overflow',0)
        elif event['status']!='ready':
            app.message='SEQUENCE '+event['status'].upper();app.playing=app.recording=False
            self.rejected_key=self.key;self.key=None;app.actions.append(('panic',None));self.reset()
        return True
