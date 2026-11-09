"""Audio-loop Sounds and non-destructive real-time bounce-to-pad setup."""
import copy
import math
from pathlib import Path
import wave

LOOP_PAGES=('AUDIO LOOP','BOUNCE TO PAD')
BAR_VALUES=(.25,.5,1,2,4,8,16)


def is_audio_sound(track):
    chain=track.get('plugins',[])
    return bool(track.get('playback_mode')=='AUDIO' and track.get('sample') and track.get('source')!='MIDI' and track.get('routing',{}).get('midi_target','NONE')=='NONE' and not (chain and chain[0].get('kind')=='INSTRUMENT'))


def validate_audio_loop(track):
    if track.get('playback_mode','SAMPLER') not in ('SAMPLER','AUDIO'):raise ValueError('invalid Sound playback mode')
    loop=track.get('audio_loop',{})
    if not isinstance(loop,dict):raise ValueError('invalid audio loop')
    for key,default,lo,hi in (('bars',1,.0625,256),('tempo',120,20,999),('tune',0,-24,24)):
        value=loop.get(key,default)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not lo<=value<=hi:raise ValueError('invalid audio loop '+key)
    if type(loop.get('stretch',True)) is not bool:raise ValueError('invalid audio loop stretch')


class AudioLoops:
    def init_audio_loops(self):
        self.audio_tool_field=0;self.audio_tool_origin='SAMPLING';self.capture_job=None;self.capture_jobs={}
        self.bounce_config=dict(source_group=0,source_pad=0,input='SOUND',target_group=0,target_pad=1,bars=1,result='AUDIO',mute_source=False)

    def audio_loop_setup(self):
        self.audio_tool_field=0;self.audio_tool_origin=self.page;self.page='AUDIO LOOP'

    def bounce_setup(self):
        if self.capture_armed or self.capture_started is not None:self.message='STOP RECORDING FIRST';return
        target=next(((self.group,p) for p in range(16) if p!=self.pad and self.bounce_empty(self.group,p)),None)
        if target is None:target=next(((g,p) for g in range(len(self.project['groups'])) for p in range(16) if self.bounce_empty(g,p)),(self.group,self.pad))
        self.bounce_config=dict(source_group=self.group,source_pad=self.pad,input='SOUND',target_group=target[0],target_pad=target[1],bars=1,result='AUDIO',mute_source=False)
        self.audio_tool_origin=self.page;self.audio_tool_field=0;self.page='BOUNCE TO PAD'

    def bounce_empty(self,group,pad):
        t=self.project['groups'][group]['pads'][pad]
        return not (t.get('sample') or t.get('zones') or t.get('plugins') or t.get('source')=='MIDI' or t.get('routing',{}).get('midi_target','NONE')!='NONE' or any(k[0]==pad for k in self.event_notes(group,self.active_patterns[group])))

    def audio_tool_fields(self):
        if self.page=='BOUNCE TO PAD':
            c=self.bounce_config
            return [('SOURCE G',self.group_name(c['source_group'])),('SOURCE PAD',str(c['source_pad']+1)),('INPUT',c['input']),('TARGET G',self.group_name(c['target_group'])),('TARGET PAD',str(c['target_pad']+1)),('BARS',str(c['bars'])),('RESULT',c['result']),('MUTE SRC','ON' if c['mute_source'] else 'OFF')]
        t=self.track();c=t.get('audio_loop',{})
        mode='AUDIO' if is_audio_sound(t) else 'LV2' if t.get('plugins') and t['plugins'][0].get('kind')=='INSTRUMENT' else 'MIDI' if t.get('source')=='MIDI' or t.get('routing',{}).get('midi_target','NONE')!='NONE' else 'SAMPLER'
        return [('MODE',mode),('BARS',str(c.get('bars',1))),('STRETCH','ON' if c.get('stretch',True) else 'OFF'),('TUNE',str(c.get('tune',0))) ]

    def audio_tool_rotate(self,delta):
        if self.page not in LOOP_PAGES:return False
        if self.page=='BOUNCE TO PAD' and (self.capture_armed or self.capture_started is not None):self.message='STOP RECORDING FIRST';return True
        i=self.audio_tool_field
        def choice(current,values):
            index=values.index(current) if current in values else 0
            return values[max(0,min(len(values)-1,index+delta))]
        if self.page=='BOUNCE TO PAD':
            c=self.bounce_config;key=tuple(c)[i]
            if key.endswith('group'):c[key]=max(0,min(len(self.project['groups'])-1,c[key]+delta))
            elif key.endswith('pad'):c[key]=max(0,min(15,c[key]+delta))
            elif key=='input':
                c[key]=choice(c[key],('SOUND','EXT 1/2','EXT 1 L','EXT 1 R'))
            elif key=='bars':c[key]=choice(c[key],(1,2,4,8,16))
            elif key=='result':c[key]=choice(c[key],('AUDIO','SAMPLER'))
            else:c[key]=delta>0
        else:
            t=self.track();self.remember();c=t.setdefault('audio_loop',dict(bars=1,tempo=self.project['tempo'],stretch=True,tune=0))
            if i==0:
                mode=choice(t.get('playback_mode','SAMPLER'),('SAMPLER','AUDIO'))
                if mode=='AUDIO':
                    if t.get('plugins') and t['plugins'][0].get('kind')=='INSTRUMENT':self.message='BOUNCE INSTRUMENT FIRST';return True
                    if not t.get('sample'):self.message='LOAD A SAMPLE FIRST';return True
                    if len(t.get('zones',[]))>1:self.message='BOUNCE MULTISAMPLE FIRST';return True
                t['playback_mode']=mode
                if t['playback_mode']=='AUDIO':
                    t['source']='SAMPLE';t.setdefault('routing',{}).update(midi_send=False,midi_target='NONE')
                self.actions.append(('sound_reset',(self.group,self.pad,t.get('channel',1))))
            elif i==1:c['bars']=choice(c.get('bars',1),BAR_VALUES)
            elif i==2:c['stretch']=delta>0
            else:c['tune']=max(-24,min(24,c.get('tune',0)+delta))
            self.actions.append(('load',(self.group,self.pad,copy.deepcopy(t))))
        return True

    def audio_tool_button(self,name,pressed):
        if not pressed:return False
        if self.page=='SAMPLING' and self.shift and name in ('F1','F2'):
            self.bounce_setup() if name=='F1' else self.audio_loop_setup();return True
        if self.page not in LOOP_PAGES:return False
        if name=='F2' and (self.capture_armed or self.capture_started is not None):
            self.actions.append(('capture_cancel',None));self.capture_armed=False;return True
        if name in ('F1','SAMPLING','MAIN'):
            self.page=self.audio_tool_origin;return True
        if name in ('NAV LEFT','NAV RIGHT'):
            self.audio_tool_field=max(0,min(len(self.audio_tool_fields())-1,self.audio_tool_field+(-1 if name=='NAV LEFT' else 1)));return True
        if name in ('F3','ENTER','ENCODER PUSH') and self.page=='BOUNCE TO PAD':
            if self.capture_started is not None:self.actions.append(('capture_stop',None))
            elif not self.capture_armed:self.start_bounce()
            return True
        return name not in ('PLAY','REC','RESTART','SHIFT','MUTE')

    def start_bounce(self):
        if self.recording:self.message='STOP MIDI REC FIRST';return
        if self.capture_armed or self.capture_started is not None:self.message='STOP RECORDING FIRST';return
        c=copy.deepcopy(self.bounce_config);src=(c['source_group'],c['source_pad']);dst=(c['target_group'],c['target_pad'])
        if src==dst or not self.bounce_empty(*dst):self.message='CHOOSE AN EMPTY TARGET';return
        if not self.active_clips[src[0]]:self.message='SOURCE GROUP HAS NO ACTIVE CLIP';return
        options=dict(source='INTERNAL',input=f'SOUND {src[0]} {src[1]}',mode='SYNC',bars=c['bars'],threshold=-24,monitor=False)
        if c['input']!='SOUND':options.update(source='EXT STEREO' if c['input']=='EXT 1/2' else 'EXT MONO',input='IN 1' if c['input']=='EXT 1/2' else 'IN 1 L' if c['input']=='EXT 1 L' else 'IN 1 R')
        self.actions.append(('capture_to',dict(target=dst,options=options,result=c['result'],bounce=c,expected=copy.deepcopy(self.project['groups'][dst[0]]['pads'][dst[1]]))))
        self.capture_armed=True;self.message='BOUNCE: WAIT FOR NEXT BAR'
        if not self.playing:self.clock_phase=0;self.step=0;self.playing=True;self.actions.append(('restart',None))

    def finish_sample_recording(self,target,path,generation):
        context=self.capture_jobs.pop(str(path),None) or self.capture_job or {}
        if self.capture_job is context:self.capture_job=None
        if generation!=self.project_generation:self.message='RECORDING KEPT IN SAMPLES';return False
        group,pad=target;track=self.project['groups'][group]['pads'][pad]
        if context.get('expected') is not None and track!=context['expected']:
            self.message='TARGET CHANGED: RECORDING KEPT';return False
        if context.get('norns_loop'):  # norns-mode fork hook
            from app.norns_loop import finish_hook;finish_hook(context,path,context.get('tempo',self.project['tempo']))
        with wave.open(str(path),'rb') as wav:end=wav.getnframes();rate=wav.getframerate()
        if not end:return False
        self.remember()
        needs_clip=False
        from app.sampler import default_zone
        track.update(sample=str(path),start=0,end=end,zones=[default_zone(dict(track,sample=str(path),start=0,end=end))])
        for key in ('slices','slice_source','slice_mode','slice_committed','slice_manual'):track.pop(key,None)
        track.setdefault('routing',{})['midi_target']='NONE'
        result=context.get('result','SAMPLER');track['playback_mode']=result
        if result=='AUDIO':
            track['source']='SAMPLE';track['routing'].update(input='NONE',midi_send=False);track['plugins']=[p for p in track.get('plugins',[]) if p.get('kind')!='INSTRUMENT']
            tempo=context.get('tempo',self.project['tempo']);bars=context.get('options',{}).get('bars',1)
            actual=end/rate*tempo/240
            if bars=='FREE':bars=max(.0625,actual)
            elif abs(actual-bars)>.03:
                nearest=round(actual*4)/4;bars=max(.0625,nearest if abs(actual-nearest)<.03 else actual)
            track['audio_loop']=dict(bars=bars,tempo=tempo,stretch=True,tune=0)
            self.actions.append(('sound_reset',(group,pad,track.get('channel',1))))
            self.actions.append(('plugins',(group*16+pad,copy.deepcopy(track.get('plugins',[])))))
            if not self.active_clips[group]:
                bank=self.project['groups'][group]
                pattern=next((i for i in range(len(bank['patterns'])) if not self.event_notes(group,i) and not any(k.startswith(str(i)+':') for k in bank.get('automation',{}))),None)
                if pattern is None:needs_clip=True
                else:
                    steps=max(self.pattern_steps(group,pattern),math.ceil(track['audio_loop']['bars']*16))
                    bank['patterns'][pattern]=[[False]*steps for _ in range(16)]
                    bank.setdefault('pattern_lengths',{})[str(pattern)]=steps
                    self.active_patterns[group]=pattern;self.active_clips[group]=True
                    self.project['scenes'][self.scene][group]=pattern
                    if group==self.group:self.pattern=pattern
        c=context.get('bounce')
        if c:
            track['gain']=100
        if c and c['mute_source']:self.project['groups'][c['source_group']]['pads'][c['source_pad']]['mute']=True
        history=self.record_history.setdefault((group,pad),[]);history.append(copy.deepcopy(track));self.record_cursor[(group,pad)]=len(history)-1
        self.actions.append(('load',(group,pad,copy.deepcopy(track))))
        self.message='LOOP READY: SELECT TARGET PATTERN' if needs_clip else ('AUDIO LOOP' if result=='AUDIO' else 'SAMPLE')+f' READY {self.group_name(group)}:{pad+1:02}'
        return True
