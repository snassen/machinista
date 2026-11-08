"""MK3 optional session: separate input process, renderer process and USB output."""
import os,sys,subprocess,time
from pathlib import Path
from app.mk2_session import Mk2Session
from app.mk3_surface import Mk3Surface
from app.mk3_pads import Mk3PadTrigger
from app.mk3_protocol import open_device,feature,led_reports,LED_NAMES,PAD_SLOTS,COLOUR_SLOTS
from app.mk3_output import Mk3Output
from app.controller_renderer import ProcessRenderer
from app.mk2_display import leds
from app.mk3_state import snapshot
from app.mk2_protocol import LED_BUTTONS,TRANSPORT
from app.connection_health import ReaderWatch
from app.norns_mode import NornsMode, sound_norns  # norns-mode fork hook
from app.norns_midi import Patchbay  # norns-mode fork hook


def strip_leds(app,surface):
    # Touch feedback takes priority only for the duration of contact. Otherwise
    # follow the selected pattern, including its held transport position at STOP.
    if surface.strip_value:
        position=round((surface.strip_value-1)*24/1023)
    else:
        length=max(1,app.pattern_ticks())
        phase=app.pattern_phase() if hasattr(app,'pattern_phase') else max(0,app.clock_phase)
        position=min(24,int(phase%length*25/length))
    return tuple(127 if i==position else 0 for i in range(25))

class Mk3Session(Mk2Session):
    source='mk3';surface_type=Mk3Surface;product=0x1600;display_interface=5;device_name='Maschine MK3'
    norns=None  # norns-mode fork hook
    patchbay=None  # norns-mode fork hook
    def __init__(self,*args):
        super().__init__(*args);self.reader_watch=ReaderWatch();self.palette=[];self.pad_trigger=Mk3PadTrigger()
        self.norns=NornsMode(self.root,sides=lambda:sound_norns(self.app))  # norns-mode fork hook
        self.patchbay=Patchbay() if Path('/proc/asound').exists() else None  # norns-mode fork hook
    def connect(self,now):
        self.next_scan=now+2;self.cleanup=[t for t in self.cleanup if t.is_alive()]
        if self.cleanup:return
        for hid in sorted(Path('/sys/class/hidraw').glob('hidraw*')):
            try:
                if f'HID_ID=0003:000017CC:{self.product:08X}' not in (hid/'device/uevent').read_text():continue
                path='/dev/'+hid.name;self.fd=open_device(path,product=self.product)
                palette=feature(self.fd,0xfe,208)
                self.palette=[tuple(palette[1+i*12+6:1+i*12+9]) for i in range(17)]
                self.renderer=ProcessRenderer(kind='mk3')
                self.output=Mk3Output(self.fd,self.renderer,self.app.settings['controllers'][self.source],self.product,self.display_interface)
                self.pad_trigger=Mk3PadTrigger()
                self.process=subprocess.Popen([sys.executable,str(self.root/'tools/mk3_monitor.py'),path,str(self.product)],stdout=subprocess.PIPE)
                os.set_blocking(self.process.stdout.fileno(),False);self.reader_watch.start(now)
                self.next_frame=self.next_led=0
                print(self.device_name+' connected: '+path,flush=True);return
            except Exception as error:print('MK3 connect: '+str(error),flush=True);self.disconnect()
    def poll(self,*args):
        super().poll(*args)
        if self.norns and self.norns.active:self.norns.flush()  # norns-mode fork hook
        if self.patchbay:self.patchbay.tick(time.monotonic())  # norns-mode fork hook
    def handle_event(self,event):
        if self.norns and self.norns.handle_event(event):return True  # norns-mode fork hook
        if event['kind'].startswith('pad_'):
            a=self.app
            for pad in self.pad_trigger.process(event,a.settings['controllers'][self.source]['pad_sensitivity']):
                slot=int(pad['name'].split('_')[-1])-1;kind=pad['kind']
                if kind=='pad_on':
                    self.inputs.pad_on(self.source,slot,a.pad_velocity(pad['value'],self.source))
                    if a.input_timestamp:self.input_lags.append(max(0,(time.monotonic()-a.input_timestamp)*1000))
                elif kind=='pad_off':self.inputs.pad_off(self.source,slot)
                elif kind=='pad_pressure':self.inputs.pad_pressure(self.source,slot,a.pad_velocity(pad['value'],self.source))
            return True
        if event['kind']=='strip':self.surface.strip(event['value']);return True
        # Pedal sensor packets are not MIDI. Do not guess polarity/calibration.
        if event['kind']=='pedal':return True
        return False
    def display_settings(self):
        if self.output:self.output.display_settings(self.app.settings['controllers'][self.source])
    def colour(self,rgb):
        maximum=max(rgb)
        if not maximum:return 0
        normal=tuple(v*127/maximum for v in rgb)
        index=min(range(1,len(self.palette)),key=lambda i:sum((self.palette[i][c]-normal[c])**2 for c in range(3)))
        return index*4+(3 if maximum>=60 else 2 if maximum>=20 else 1)
    def reports(self,now):
        mono,groups,pads=leds(self.surface,self.channels,now);a=self.app
        values={n:mono[i+1] for i,n in enumerate(LED_BUTTONS)}
        values.update({n:groups[i+49] for i,n in enumerate(TRANSPORT)})
        for name,pages in {'BROWSE':('BROWSE',),'SAMPLING':('SAMPLING','SAMPLE EDIT','CHOP','ZONE','STRETCH','AUTOSAMPLER','SLICE TARGET'),'PAD MODE':('PAD CONFIG',),'STEP':('STEP',),'SCENE':('SCENE',),'PATTERN':('PATTERN',),'SELECT':('SELECT',),'DUPLICATE':('DUPLICATE',),'MUTE':('MUTE',),'SOLO':('SOLO',)}.items():
            values[name]=85 if a.page in pages or name in self.surface.held else 8
        values.update(CHANNEL=85 if a.page in ('INPUT','CHANNEL','PAD','GROOVE','MACRO') else 8)
        values['PLUG-IN']=85 if a.page in ('PLUGIN','SAMPLER','PLUGIN BROWSE') else 8
        values['LOCK']=85 if getattr(self.surface,'lock_state',None) else 8
        values['MIXER']=85 if a.page=='MIXER' else 8
        values['ARRANGER']=85 if a.page in ('SONG','CLIP ARRANGER','CLIP MENU') else 8
        values['KEYBOARD']=85 if a.keyboard_enabled else 8
        values['CHORDS']=85 if a.keyboard_enabled and a.keyboard_chord_mode()!='OFF' else 8
        values['FIXED VEL']=85 if a.fixed_velocity else 8
        values['EVENTS']=85 if a.page in ('PATTERN GRID','GRID EDIT') else 8
        values['FOLLOW']=85 if (a.grid_follow if a.page in ('PATTERN GRID','GRID EDIT') else a.follow) else 8
        values['PERFORM']=85 if a.page=='LIVE FX' else 8
        for name in ('PITCH','MOD','NOTES'):values[name]=85 if self.surface.strip_mode==name else 8
        for name in ('FILE','SETTINGS','MACRO','VARIATION','TAP','STOP'):values[name]=85 if name in self.surface.held else 8
        if a.shift:values['TAP']=85 if a.timing()['metro'] else 8
        if self.norns and self.norns.active:values['PLUG-IN']=85  # norns-mode fork hook
        report=[]
        for i,name in enumerate(LED_NAMES):
            value=127 if name in self.surface.held else values.get(name,8)
            if name.startswith('GROUP '):
                j=ord(name[-1])-65;value=self.colour(groups[1+j*6:4+j*6])
            elif i in COLOUR_SLOTS:value=self.colour((0,value,0) if name=='PLAY' else (value,0,0) if name=='REC' else (value,value//2,0))
            if i not in COLOUR_SLOTS:value=127 if value>=60 else 48 if value else 0
            report.append(value)
        report.extend(strip_leds(a,self.surface))
        for raw,slot in enumerate(PAD_SLOTS):report.append(self.colour(pads[1+raw*3:4+raw*3]))
        return led_reports(report)
    def update(self,now):
        if not self.output:return
        try:
            if now>=self.next_led:self.output.submit_leds(self.reports(now));self.next_led=now+.05
            if now>=self.next_frame:
                if self.norns and self.norns.active:state=self.norns.display_state()  # norns-mode fork hook
                else:
                    state=snapshot(self.surface);state['touches']=tuple(sorted(self.surface.touched))
                self.output.submit(state);self.next_frame=now+1/30
        except Exception as error:print('MK3 snapshot: '+str(error),flush=True);self.disconnect();self.next_scan=now+2
