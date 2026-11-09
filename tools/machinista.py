#!/usr/bin/env python3
"""Headless Machinista: hardware UI, project editor, sampler, ALSA and MIDI."""
import argparse
import copy
import fcntl
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time
import wave
import heapq
import uuid
import threading
import queue

ROOT = Path(__file__).resolve().parent.parent
managed_lv2_path='/var/lib/machinista/lv2/plugins'
os.environ['LV2_PATH']=managed_lv2_path+':'+os.environ.get('LV2_PATH',str(Path.home()/'.lv2')+':/usr/local/lib/lv2:/usr/lib/lv2')
sys.path.insert(0, str(ROOT))
from app.layout import SOUNDS,GROUP_BASE,MASTER,PREVIEW,CLICK,ZONE_BASE,bus_targets
from app.model import Application
from app.step_display import StepDisplay
from app.devices import discover
from app.audio import AudioBackend
from app.midi import MidiBackend
from app.midi_sync import MidiClock
from app.midi_performance import MidiPerformance
from app.waveform import Waveforms
from app.browser import mounted_sources
from app.display import graphics
from app.sample_edit import process_sample
from app.slicing import detect_slices
from app.plugins import copy_plugin_state
from app.presets import write_preset,read_preset,prepare_preset_state
from app.export_audio import render_export
from app.export_midi import render_midi_export
from app.relink import missing_samples,find_replacements,validate_replacement
from app.browser import Source
from app.runtime_audio import RuntimeAudio
from app.native_sequence import NativeSequence
from app.live_display import ASYNC_PAGES,live_state
from app.sampler import default_zone
from app.sample_jobs import SampleJobs
from app.plugin_refresh import PluginRefresh
from app.stretch_preview import StretchPreview
from app.wave_playback import WavePlayback
from app.sound_runtime import SoundRuntime
from app.chord_library import ChordCatalog
from app.audio_import import AudioImports
from app.system_info import SystemMonitor
from app.power_client import PowerControl
from app.autosave import Autosave
from app.connection_health import RetryGate,LoopWatch,surface_status
from app.input_streams import ready_streams,bounded_lines
from app.sequencer_clock import advance_clock
from app.controller_output import ControllerOutput
from app.controller_inputs import ControllerInputs
from app.mk2_session import Mk2Session
from app.mk1_session import Mk1Session
from app.mk3_session import Mk3Session
from app.plus_session import PlusSession
from app.mikro_session import MikroSession
from app.device_monitor import DeviceMonitor
from app.display_budget import DisplayBudget
from app.assets import collect_project,resolve_assets
from app.ni_display import frame as original_frame
from app.leds import led_report
from mikro_feedback import open_mk1, frame_reports, text, send
from mikro_leds import load_pad_channels, orange_idle_report
from mikro_settings import configure_display

GROUP_SLOTS = [12, 13, 14, 15, 8, 9, 10, 11]


def controller_path():
    for hid in sorted(Path('/sys/class/hidraw').glob('hidraw*')):
        try:
            if 'HID_ID=0003:000017CC:00001110' in (hid/'device/uevent').read_text():
                return str(Path('/dev')/hid.name)
        except OSError:
            continue
    raise OSError('Mikro MK1 is not connected')


def display_pixels(app, envelope=None):
    return original_frame(app, envelope)


def render(fd, app, channels, envelope=None, pixels=None, leds=None):
    pixels = pixels if pixels is not None else display_pixels(app, envelope)
    send(fd, leds if leds is not None else led_report(app, channels))
    for report in frame_reports(pixels):
        send(fd, report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', nargs='?', help='default: discover verified MK1 automatically')
    parser.add_argument('--seconds', type=float, default=0)
    args = parser.parse_args()
    if args.seconds < 0:
        parser.error('seconds must be nonnegative')
    from app.storage import SettingsWriter
    app = Application(ROOT)
    channels = load_pad_channels(ROOT/'captures/mikro-mk1-pad-led-map.json')
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with (ROOT/'build/surface.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        input_process = audio = output = step_display = mk2 = mk1 = mk3 = plus = None
        controller_inputs=ControllerInputs(app)
        midi = MidiBackend();midi_clock=MidiClock()
        waveforms = Waveforms();wave_playback=WavePlayback()
        runtime_audio = RuntimeAudio();native_sequence=NativeSequence()
        plugin_refresh=PluginRefresh(ROOT)
        from app.codec_levels import CodecLevels
        codec_levels=CodecLevels()
        from app.hat_button import HatButton,apply_presses
        hat_button=HatButton()
        from app.interface_mixer import InterfaceMixer,context as mixer_context
        interface_mixer=InterfaceMixer()
        from app.bluetooth_midi import BluetoothMidi
        bluetooth=BluetoothMidi()
        bluetooth.submit('on' if app.settings.get('ble_midi',False) else 'off')
        sample_jobs=SampleJobs()
        export_pending=None;export_cancel=threading.Event();export_progress=queue.SimpleQueue()
        stretch_jobs=StretchPreview(ROOT/'cache')
        audio_imports=AudioImports(ROOT/'cache');chord_catalog=ChordCatalog(ROOT)
        gates=[];gate_counter=0;collect_pending=None;plugin_transfer_pending=None;preset_pending=None;midi_bindings={};routing_key=None;next_capture_status=0;next_meter_status=0;next_preview_status=0;next_pdc_status=0
        pid = ROOT/'build/machinista.pid'
        pid.write_text(str(os.getpid())+'\n')
        settings_writer=SettingsWriter(app.settings_path)
        live_banks=None
        try:
            from app.live_banks import LiveBanks
            live_banks=LiveBanks(ROOT)
            output=MikroSession(ROOT,app,controller_inputs,open_mk1,frame_reports,send,configure_display,args.path)
            mk2=Mk2Session(ROOT,app,controller_inputs,channels)
            mk1=Mk1Session(ROOT,app,controller_inputs,channels)
            mk3=Mk3Session(ROOT,app,controller_inputs,channels)
            plus=PlusSession(ROOT,app,controller_inputs,channels)
            step_display=StepDisplay()
            audio = AudioBackend(ROOT, lambda message: setattr(app, 'message', message),app.settings['sample_rate'],app.settings['audio_buffer'])
            midi_performance=MidiPerformance(app,audio,midi)
            sound_runtime=SoundRuntime(ROOT,app,audio,midi)
            audio.command(f"pdc {int(app.settings['plugin_delay'])}")
            audio.output_settings(app.settings)
            audio.device(None)
            midi.native_command=audio.command
            app.native_sequence=app.settings['midi_sync']!='IN'
            for group, bank in enumerate(app.project['groups']):
                for pad, track in enumerate(bank['pads']):
                    if track['sample']:
                        try:
                            audio.load(group, pad, track)
                        except (OSError, ValueError, wave.Error, EOFError) as error:
                            print(f'Sample unavailable: {error}', flush=True)
                            app.message = 'SAMPLE MISSING'
            for group,bank in enumerate(app.project['groups']):
                for pad,track in enumerate(bank['pads']):audio.plugins(group*16+pad,track.get('plugins',[]))
                audio.plugins(GROUP_BASE+group,bank.get('plugins',[]))
            audio.plugins(MASTER,app.project.get('plugins',[]))
            app.request_missing_check(False)
            streams = {audio.engine.stdout: b''}
            for stream in streams:
                os.set_blocking(stream.fileno(), False)
            system_monitor = SystemMonitor(ROOT)
            power_control = PowerControl()
            from app.updater import Control as UpdateControl
            update_control=UpdateControl(ROOT)
            from app.controller_stems import Control as StemControl
            stem_control=StemControl()
            autosaver = Autosave(ROOT)
            device_monitor = DeviceMonitor()
            started = time.monotonic()
            next_scan = next_frame = next_step = started
            last_frame = None
            display_budget=DisplayBudget();display_budget_page=app.page
            next_led=0;last_led_state=None;leds=led_report(app,channels)
            last_midi_config = None
            midi_retry=RetryGate();loop_watch=LoopWatch(diagnostics=True);next_health=0
            audio_retry = None;next_clock_report=0
            print('Machinista ready; MAIN opens settings', flush=True)
            while not stopped and (args.seconds == 0 or time.monotonic()-started < args.seconds):
                loop_watch.tick()
                if audio.engine.poll() is not None:
                    raise OSError('audio engine exited')
                now = time.monotonic()
                bluetooth_state=bluetooth.poll(now)
                if bluetooth_state is not None:app.bluetooth_status=bluetooth_state
                output.poll(now,streams)
                try:
                    active_stretch=stretch_jobs.active_key(app.track(),(app.project_generation,app.group,app.pad,app.zone_index)) if app.page=='STRETCH' and app.track().get('sample') else None
                except OSError:active_stretch=None
                if active_stretch is None and stretch_jobs.latest is not None:audio.command('preview_stop')
                stretch_result=stretch_jobs.poll(active_stretch)
                if stretch_result:
                    preview,velocity,error=stretch_result
                    if error:app.message='PREVIEW FAILED';print(str(error),flush=True)
                    else:audio.stretch_preview(preview,velocity)
                if app.page!='BROWSE' or not app.browser.prehear:audio_imports.cancel_preview()
                imported=audio_imports.poll()
                if imported:
                    kind,source,context,prepared,error,cancelled=imported
                    if not cancelled:
                        if error:app.message='PREVIEW FAILED' if kind=='kit_preview' else 'MP3 IMPORT FAILED';print(str(error),flush=True)
                        elif kind=='load':
                            app.browser_decoded[str(source)]=prepared['sample']
                            while len(app.browser_decoded)>16:app.browser_decoded.pop(next(iter(app.browser_decoded)))
                            app.finish_mp3_import(context,prepared)
                        elif app.page=='BROWSE' and app.browser.prehear and app.browser_preview_path()==source:
                            if kind=='preview':
                                app.browser_decoded[str(source)]=prepared['sample']
                                while len(app.browser_decoded)>16:app.browser_decoded.pop(next(iter(app.browser_decoded)))
                            audio.load(-1,0,prepared);audio.command(f'hit {PREVIEW} 0.5')
                sound_runtime.poll(now,bool(audio.recorder or audio.capture_pending or app.capture_armed or app.capture_started is not None or sample_jobs.pending or plugin_transfer_pending or preset_pending or collect_pending or export_pending or audio_imports.busy))
                plugin_refresh.poll(app,audio,now)
                live_banks.poll(app,now)
                stem_control.poll(app,now)
                system_monitor.update(app, now)
                processing=bool(sound_runtime.busy or app.recording or app.capture_armed or app.capture_started is not None or app.export_busy or sample_jobs.pending or audio_imports.busy or audio.recorder or audio.native_capture or audio.capture_pending)
                processing=processing or bool(app.stem_status.get('busy') or app.stem_command_pending)
                power_control.poll(app,now,processing)
                update_control.poll(app,now,processing)
                autosaver.poll(app,audio,now,processing or app.playing)
                sync_mode=app.settings['midi_sync']
                app.native_sequence=sync_mode!='IN' and not app.count_remaining
                if midi_clock.mode!=sync_mode:
                    if midi_clock.mode=='OUT' and midi_clock.output_running:midi.send(bytes([0xfc]))
                    midi_clock.configure(sync_mode)
                audio.tempo=app.project['tempo']
                sampling_visible=app.page=='SAMPLING' or app.page=='SAMPLING NAV' and app.sampling_nav==0
                sampling_input=audio.sampling_io(app.capture_options(),sampling_visible)
                if now>=next_pdc_status:audio.command('pdc');next_pdc_status=now+1
                from app import ducktor
                ducktor.poll(app,audio,now)
                if sampling_visible and now>=next_meter_status:audio.command('meter_status');next_meter_status=now+.1

                if audio.recorder and audio.recorder.poll() is not None:
                    audio.stop_capture()
                    app.capture_started = None
                    app.message = 'RECORDING ENDED'
                if audio_retry is not None and now >= audio_retry and app.audio:
                    audio.device(app.audio)
                    audio_retry = None
                try:
                    discovered=device_monitor.poll(now)
                    if discovered is not None:
                        devices,ports,sources=discovered
                        app.refresh_devices(devices,ports);app.browser.refresh(sources)
                        if app.relink_browser is not None:app.relink_browser.refresh([Source('PROJECT ASSETS',ROOT/'projects'),Source('PRESET ASSETS',ROOT/'presets')]+list(sources))
                except OSError as error:print(f'Device scan: {error}',flush=True)
                midi_config = (tuple(app.midi_devices), app.settings['midi_in'], app.settings['midi_out'], app.settings['midi_channel'])
                if midi_config != last_midi_config and midi_retry.ready(midi_config,now):
                    try:
                        midi_performance.panic();midi.configure(app.midi_devices, app.settings)
                        audio.command('midi_device '+json.dumps(midi.output or '-'))
                        last_midi_config = midi_config
                        midi_retry.reset()
                    except OSError as error:
                        midi_retry.failed(now)
                        midi.close_ports();midi_performance.panic()
                        audio.command('midi_device '+json.dumps('-'))
                        app.message = 'MIDI PORT ERROR'
                        print(str(error), flush=True)
                active_clock=app.playing or app.count_remaining
                timeout=min(0.005,max(0,next_step-time.monotonic())) if active_clock else 0.005
                selected,readable=ready_streams(streams,timeout)
                for stream in selected:
                    if stream in readable:
                        chunk = os.read(stream.fileno(), 65536)
                        if not chunk:
                            if stopped:break
                            if stream is not audio.engine.stdout:
                                output.lost(streams);continue
                            raise OSError('worker disconnected')
                        streams[stream] += chunk
                    if stream is not audio.engine.stdout and len(streams[stream])>1024*1024:
                        print('Mikro input backlog; reconnecting',flush=True)
                        output.lost(streams);continue
                    for line in bounded_lines(streams,stream):
                        event = json.loads(line)
                        if stream is audio.engine.stdout:
                            if wave_playback.receive(app,event,time.monotonic()):continue
                            if native_sequence.receive(app,event):continue
                            if ducktor.receive(app,event):continue
                            if runtime_audio.receive(app,event):continue
                            if event['kind'] not in ('input_meter','preview','pdc'):print(json.dumps(event),flush=True)
                            if event['kind']=='pdc':
                                if event['status'] in (1,2) and app.pdc_status.get('status')!=event['status']:
                                    app.message='PLUGIN DELAY LIMIT' if event['status']==1 else 'PDC ROUTING UNSUPPORTED'
                                app.pdc_status=event
                            if event['kind']=='sample_memory':
                                app.sample_memory=event
                                if event['status']=='purged':app.message=f"FREED {event.get('freed_bytes',0)/1048576:.1f} MB"
                                elif event['status']=='busy':app.message='STOP RECORD/PLAY FIRST'
                                elif event['status']=='live_input':app.message='DISABLE LIVE INPUT FIRST'
                            if event['kind']=='audio':
                                app.audio_status=event
                                if event['status'] in ('ready','idle'):native_sequence.reset()
                                else:native_sequence.clock=None
                            if event['kind']=='preview':app.live_chop_event(event)
                            if event['kind']=='input_meter':
                                app.capture_peak=event.get('peak',0);app.capture_stereo_peak=(event.get('left',0),event.get('right',0))
                            if sound_runtime.event(event,time.monotonic()):continue
                            if event['kind']=='native_record' and audio.native_capture:
                                result=audio.native_record_event(event)
                                if event['status']=='recording':
                                    if app.capture_started is None:app.capture_started=time.monotonic()
                                    app.capture_armed=False
                                elif event['status'] in ('finished','error'):
                                    app.capture_started=None;app.capture_armed=False
                                    if result:app.actions.append(('record_result',(*result,audio.record_generation)))
                            if event['kind']=='state_barrier' and plugin_transfer_pending is not None:
                                request=plugin_transfer_pending;plugin_transfer_pending=None
                                required=[p for chain in request['chains'].values() for p in chain] if request['operation']=='DELETE_GROUP' else request['chain'][request['slot']:request['slot']+1] if request['operation']=='COPY' else request['chain']
                                if all(Path(p['state']).is_file() for p in required):
                                    if request['operation']=='DELETE_GROUP':
                                        if app.finish_group_delete(request):
                                            gates.clear();midi_performance.panic();audio.command('panic');midi.panic()
                                    else:app.finish_plugin_transfer(request)
                                else:app.message='PLUGIN STATE FAILED'
                            if event['kind']=='state_barrier' and export_pending is not None:
                                request=export_pending;export_pending=None
                                if not sample_jobs.submit('EXPORT',None,{},render_export,request,ROOT,export_cancel,export_progress):
                                    app.export_busy=False;app.message='PROCESS BUSY'
                            if event['kind']=='state_barrier' and preset_pending is not None:
                                request=preset_pending;preset_pending=None
                                if request.get('operation')=='LOAD':
                                    if not all(Path(p['state']).is_file() for chain in request['previous'].values() for p in chain):app.message='PLUGIN STATE FAILED'
                                    elif not sample_jobs.submit('PRESET_LOAD',None,request,read_preset,request['path'],request['kind'],ROOT):app.message='PROCESS BUSY'
                                elif not sample_jobs.submit('PRESET_SAVE',None,{},write_preset,request,ROOT):app.message='PROCESS BUSY'
                            if event['kind']=='state_barrier'  and collect_pending is not None:
                                revision,generation,project,folder=collect_pending;collect_pending=None
                                if not sample_jobs.submit('COLLECT',None,{'revision':revision,'_generation':generation},collect_project,project,folder):app.message='PROCESS BUSY'
                            if event['kind']=='capture' and event['status']=='ready':
                                audio.begin_capture()
                                if audio.recorder:app.capture_started=time.monotonic()
                                app.capture_armed=False
                            if event['status'] in ('error', 'disconnected', 'queue_full', 'memory_limit'):
                                app.message=event['kind'].upper()+' '+event['status'].upper()
                            if event['kind']=='audio' and event['status'] in ('error','disconnected'):
                                audio_retry = time.monotonic()+3
                            elif event['kind']=='audio' and event['status']=='ready':
                                audio_retry = None
                            continue
                        if output.reader_watch.receive(event,time.monotonic()):continue
                        kind = event['kind']
                        if kind in ('button','encoder','pad_on'):output.dismiss_boot()
                        stamp=event.get('monotonic_ns',0)/1e9
                        app.input_timestamp=stamp if stamp>0 else None
                        try:
                            if kind == 'button':
                                controller_inputs.button('mikro',event['name'], bool(event['value']))
                            elif kind == 'encoder':
                                app.rotate(event['value'])
                            elif kind == 'pad_on':
                                slot = int(event['name'].split('_')[-1])-1
                                controller_inputs.pad_on('mikro',slot,app.pad_velocity(event['value']))
                                if app.playing or app.recording:
                                    print(json.dumps({'kind':'record_pad','page':app.page,'pad':slot+1,'playing':app.playing,'recording':app.recording,'phase':app.clock_phase,'group':app.group,'pattern':app.pattern,'length':app.pattern_steps(),'active':app.active_patterns[app.group],'clip':app.active_clips[app.group],'recorded':app.last_recorded,'held':sorted(app.held_buttons)}),flush=True)
                            elif kind == 'pad_pressure':
                                slot=int(event['name'].split('_')[-1])-1
                                controller_inputs.pad_pressure('mikro',slot,app.pad_velocity(event['value']))
                            elif kind == 'pad_off':
                                slot = int(event['name'].split('_')[-1])-1
                                controller_inputs.pad_off('mikro',slot)
                        except (ValueError, OSError, wave.Error, EOFError) as error:
                            app.message = 'ACTION FAILED'
                            print(str(error), flush=True)
                        finally:app.input_timestamp=None
                mk2.poll(time.monotonic())
                mk1.poll(time.monotonic())
                mk3.poll(time.monotonic())
                plus.poll(time.monotonic())
                if now>=next_health:
                    next_health=now+1
                    loop_watch.publish(dict(page=app.page,group=app.group,pad=app.pad,
                        playing=app.playing,recording=app.recording,held=sorted(app.held_buttons),
                        record_events=list(app.record_diagnostics),
                        mikro=surface_status(output,now),mk2=surface_status(mk2,now),mk1=surface_status(mk1,now),mk3=surface_status(mk3,now),plus=surface_status(plus,now)))
                if stopped:
                    break
                try:
                    midi.poll()
                    for status,data in midi.take_events():
                        if status>=0xf0:
                            change=midi_clock.receive(status,data,time.monotonic(),app.settings['midi_offset'])
                            if change:
                                command,value=change
                                if command in ('start','continue','locate'):
                                    if command!='locate':app.playing=True
                                    if command=='start':app.clock_phase=-1;app.step=-1;app.actions.append(('panic',None))
                                    else:app.clock_phase=value-1;app.step=(value-1)//24
                                elif command=='stop':app.playing=app.recording=False;app.actions.append(('panic',None))
                                elif command=='tempo':app.project['tempo']=max(40,min(240,round(value,3)))
                            continue
                        midi_performance.event(status,data)
                except OSError as error:
                    midi.close_ports();midi_performance.panic()
                    audio.command('midi_device '+json.dumps('-'))
                    last_midi_config = None;midi_retry.reset()
                    app.message = 'MIDI DISCONNECTED'
                    print(str(error), flush=True)
                now = time.monotonic()
                if sync_mode=='IN':
                    for deadline,position in midi_clock.ticks(now):
                        if app.playing:
                            app.clock_phase=position-1;app.step=(position-1)//24;app.clock_tick(deadline)
                    if not midi_clock.running and app.playing and midi_clock.last is not None:
                        app.playing=app.recording=False;app.actions.append(('panic',None));app.message='MIDI CLOCK LOST'
                elif not (app.playing or app.count_remaining):
                    next_step = now
                else:
                    next_step=native_sequence.deadline(app,now,next_step)
                if sync_mode!='IN' and (app.playing or app.count_remaining) and now >= next_step:
                    next_step,overrun=advance_clock(app,next_step,now)
                    if overrun and not app.native_sequence:app.message='TIMING OVERRUN'
                    if now>=next_clock_report:
                        print(json.dumps(dict(kind='clock_health',step_display_frames=step_display.frames,**app.clock_stats)),flush=True);next_clock_report=now+10
                for message in midi_clock.output(now,app.playing,app.clock_phase,app.project['tempo'],app.settings['midi_offset']):
                    if message!=b'\xf8' or not app.native_sequence:midi.send(message)
                while not export_progress.empty():app.export_status=export_progress.get()
                for kind,target,old,result,error in sample_jobs.poll():
                    if kind=='EXPORT':
                        app.export_busy=False
                        app.export_status=str(error).upper()[:40] if error else 'EXPORT DONE'
                        app.message=app.export_status
                        if result is not None:
                            app.export_result=str(result)
                            if app.page=='EXPORT':app.page='EXPORT DONE';app.message=''
                            print('Export saved: '+str(result),flush=True)
                        continue

                    if error:
                        if kind.startswith('RELINK') or kind=='MISSING':app.relink_busy=False
                        app.message=str(error).upper()[:40] if kind.startswith(('PRESET_','RELINK')) else 'PROCESS FAILED';print(str(error),flush=True);continue
                    if kind in ('MISSING','RELINK_SEARCH','RELINK_APPLY'):
                        try:
                            if kind=='MISSING':app.finish_missing_check(old,result)
                            elif kind=='RELINK_SEARCH':app.finish_relink_search(old,result)
                            else:app.finish_relink_apply(old,old['row'],result)
                        except (OSError,ValueError,KeyError,TypeError,wave.Error,EOFError) as exc:app.relink_busy=False;app.message='RELINK FAILED';print(str(exc),flush=True)
                        continue
                    if kind=='PRESET_SAVE':app.message='PRESET SAVED';continue
                    if kind=='PRESET_LOAD':
                        try:app.finish_preset_load(old,result)
                        except (ValueError,KeyError,TypeError,IndexError) as exc:app.message='INVALID PRESET';print(str(exc),flush=True)
                        continue
                    if kind=='PLUGIN_PASTE':app.finish_plugin_paste(result);continue
                    if kind=='COLLECT':
                        if old['revision']==app.revision and old['_generation']==app.project_generation:
                            app.project=resolve_assets(json.loads(result.read_text()),result.parent);app.dirty=True;app.save();app.actions.append(('reload',None));app.message='PROJECT SAMPLES COLLECTED'
                        else:app.message='COLLECTED COPY SAVED'
                        continue
                    group,pad=target
                    if old.get('_generation')!=app.project_generation or group>=len(app.project['groups']):continue
                    track=app.project['groups'][group]['pads'][pad]
                    if old.get('_generation')!=app.project_generation or track.get('sample')!=old.get('sample') or track.get('start')!=old.get('start') or track.get('end')!=old.get('end'):
                        app.message='SAMPLE CHANGED: RESULT KEPT';continue
                    if kind=='ANALYSIS':
                        key=(old['sample'],old['start'],old['end'],old['_sensitivity'],old['_zero'])
                        app.slice_transients[key]=[a for a,b in result];app.message='TRANSIENTS READY';continue
                    if kind=='DETECT' and (app.slice_mode!='DETECT' or old.get('_sensitivity')!=app.slice_sensitivity or old.get('_zero')!=app.slice_zero):continue
                    if kind=='DETECT':app.remember()
                    if kind=='DETECT':
                        track['slices']=result;app.slice_count=len(result);app.slice_index=min(app.slice_index,len(result)-1);app.message='SLICES DETECTED'
                    else:
                        operation=kind;path,frames=result
                        if operation=='COPY':app.message='SELECTION COPIED';continue
                        if app.finish_sample_process(track,old,operation,path,frames):audio.load(group,pad,copy.deepcopy(track))
                while gates and gates[0][0]<=now:
                    _,_,group,pad,note,token=heapq.heappop(gates)
                    source=app.project['groups'][group]['pads'][pad]
                    for slot in app.linked_sounds(group,pad):
                        track=app.project['groups'][group]['pads'][slot];target_note=note-source.get('note',36+pad)+track.get('note',36+slot)
                        audio.note_off(group,slot,target_note,token)
                        if track.get('source')=='MIDI' or track.get('routing',{}).get('midi_send'):midi.note_off(target_note,track['channel'],token)
                if not app.playing and app.automation_bases:app.automation_restore()
                app.transport_repeat_tick(now)
                app.record_prepare_tick(now)
                app.chord_presets=chord_catalog.rows
                controller_inputs.sync()
                if not getattr(app,'autosampling',False):controller_inputs.timing.tick(now)
                midi_performance.tick(now)
                app.repeat_tick(now)
                app.browser_preview_tick(now)
                runtime_audio.update(app,audio,now,None if sync_mode=='IN' else next_step)
                if audio.native_capture and audio.native_capture.get('stop_requested') is not None and (not app.playing or app.clock_phase!=audio.native_capture['stop_requested'] and app.clock_phase%384<4):
                    audio.native_capture.pop('stop_requested');audio.stop_capture();app.capture_started=None
                wave_playback.update(app,audio,now)
                if app.live_chop_started is not None and now>=next_preview_status:
                    audio.command('preview_status');next_preview_status=now+1/30
                if audio.native_capture and not audio.native_capture.get('autosampler') and now>=next_capture_status:
                    audio.command('record_status');next_capture_status=now+.1
                audio.external_capture_tick(app)
                route_key=(id(app.project),app.revision,id(audio.desired),bool(audio.recorder),bool(audio.capture_pending),bool(audio.native_capture),sampling_input)
                if routing_key!=route_key:
                    audio.routing(app.project);routing_key=route_key
                interface_mixer.update(app.audio,now,app.page=='INTERFACE MIXER')
                if app.interface_mixer_context!=mixer_context(app.audio):
                    app.interface_mixer_context=mixer_context(app.audio);app.interface_mixer_controls=[];app.interface_mixer_index=0;app.interface_mixer_error=''
                mixer_result=interface_mixer.poll()
                if mixer_result and not any(action=='interface_mixer' for action,_ in app.actions):
                    selected=app.interface_control();identifier=selected['id'] if selected else None
                    app.interface_mixer_controls=mixer_result[2];app.interface_mixer_error=mixer_result[3] or ('NO MIXER CONTROLS' if not mixer_result[2] else '')
                    app.interface_mixer_index=next((i for i,c in enumerate(mixer_result[2]) if c['id']==identifier),0)
                hat_button.update(app.audio)
                apply_presses(app,hat_button.poll())
                codec_result=codec_levels.poll()
                if codec_result and app.audio and codec_result[0]==app.audio.key and codec_result[1]:app.message=codec_result[1]
                actions, app.actions = app.actions, []
                current_voice_token=0
                for action, value in actions:
                    try:
                        if app.page!='STRETCH' and stretch_jobs.latest is not None:
                            stretch_jobs.cancel();audio.command('preview_stop')
                        if action == 'stems':
                            stem_control.submit(value)
                        elif action == 'update':
                            update_control.submit(value)
                        elif action == 'power':
                            power_control.submit(value)
                        elif action == 'bluetooth':
                            bluetooth.submit(*value)
                        elif action == 'display_settings':
                            output.apply_settings()
                        elif action == 'controller_display_settings':
                            if value=='mk2':mk2.display_settings()
                            elif value=='mk1':mk1.display_settings()
                            elif value=='mk3':mk3.display_settings()
                            elif value=='plus':plus.display_settings()
                        elif action == 'controller_midi':midi_performance.event(*value)
                        elif action == 'click':
                            audio.click(*value)
                        elif action == 'sample_memory':audio.command('sample_memory')
                        elif action == 'sample_purge':
                            if app.playing or app.recording or app.capture_started is not None or app.capture_armed or app.export_busy or sample_jobs.pending or audio.recorder or audio.native_capture or audio.capture_pending:
                                app.message='STOP RECORD/PROCESS FIRST';continue
                            audio.command('sample_purge')
                        elif action == 'routing_refresh':routing_key=None
                        elif action == 'plugin_delay':audio.command(f'pdc {int(value)}')
                        elif action == 'live_fx':audio.command('live_fx '+' '.join(map(str,value)))
                        elif action == 'interface_mixer':
                            if value[0]==mixer_context(app.audio):interface_mixer.submit(app.audio,value[1],value[2])
                        elif action == 'codec_levels':codec_levels.submit(app.audio,app.settings)
                        elif action == 'audio_outputs':audio.output_settings(app.settings)
                        elif action == 'audio_buffer':
                            audio.device(app.audio,buffer_frames=value)
                            app.actions.append(('panic',None))
                        elif action == 'audio_rate':
                            audio.device(app.audio,value);app.actions.append(('reload',None))
                        elif action == 'audio':
                            audio.device(value)
                            app.capture_started = None
                        elif action in ('missing_check','relink_search','relink_validate'):
                            context=value[0]
                            if action=='missing_check':kind='MISSING';function=missing_samples;arguments=(value[1],)
                            elif action=='relink_search':kind='RELINK_SEARCH';function=find_replacements;arguments=(value[1],value[2])
                            else:kind='RELINK_APPLY';function=validate_replacement;arguments=(value[1],value[2]);context=dict(context,row=value[1])
                            if not sample_jobs.submit(kind,None,context,function,*arguments):app.relink_busy=False;app.message='PROCESS BUSY: RETRY'
                        elif action=='export_cancel':export_cancel.set()
                        elif action=='midi_export':
                            if plugin_transfer_pending is not None or collect_pending is not None or preset_pending is not None or export_pending is not None or sample_jobs.pending or audio.recorder or audio.native_capture:
                                app.export_busy=False;app.message='STATE BUSY';continue
                            export_cancel.clear()
                            if not sample_jobs.submit('EXPORT',None,{},render_midi_export,value,ROOT,export_cancel,export_progress):app.export_busy=False;app.message='PROCESS BUSY'
                        elif action=='audio_export':
                            if plugin_transfer_pending is not None or collect_pending is not None or preset_pending is not None or export_pending is not None or sample_jobs.pending or audio.recorder or audio.native_capture:
                                app.export_busy=False;app.message='STATE BUSY';continue
                            export_cancel.clear();request=value;request['metadata']=copy.deepcopy(audio.plugin_metadata)
                            directory=ROOT/'cache'/'export-state'/uuid.uuid4().hex;request['state_dir']=str(directory)
                            for bus,(_,chain) in request.pop('chains').items():
                                for index,plugin in enumerate(chain):
                                    folder=directory/str(bus)/str(index);plugin['state']=str(folder/'state.ttl')
                                    audio.command(f'plugin_save {bus} {index} '+json.dumps(str(folder)))
                            export_pending=request;audio.command('state_barrier')
                        elif action=='preset_save':
                            if app.playing or app.recording or audio.recorder or audio.native_capture:app.message='STOP RECORD/PLAY FIRST';continue
                            if plugin_transfer_pending is not None or collect_pending is not None or preset_pending is not None or export_pending is not None or sample_jobs.pending:app.message='STATE BUSY';continue
                            preset_pending=value;prepare_preset_state(audio,value,ROOT)
                        elif action=='preset_load':
                            if plugin_transfer_pending is not None or collect_pending is not None or preset_pending is not None or export_pending is not None:app.message='STATE BUSY';continue
                            if app.playing or app.recording or audio.recorder or audio.native_capture:app.message='STOP RECORD/PLAY FIRST';continue
                            if sample_jobs.pending:app.message='PROCESS BUSY';continue
                            request=value;group,pad=request['group'],request['pad']
                            buses=[group*16+i for i in range(16)]+[GROUP_BASE+group] if request['kind']=='GROUP' else [group*16+pad]
                            targets=bus_targets(app.project);request['previous']={bus:copy.deepcopy(targets[bus].get('plugins',[])) for bus in buses}
                            request['chains']={bus:(bus,chain) for bus,chain in request['previous'].items()}
                            request['operation']='LOAD';preset_pending=request;prepare_preset_state(audio,request,ROOT)
                        elif action=='collect_project':
                            if plugin_transfer_pending is not None or collect_pending is not None or preset_pending is not None or export_pending is not None:app.message='STATE BUSY';continue
                            revision,project=value;folder=ROOT/'projects'/((project.get('file_id') or 'CURRENT')+'.assets')
                            collect_pending=(revision,app.project_generation,project,folder);audio.save_plugin_state(project);audio.command('state_barrier')
                        elif action=='group_delete':
                            if plugin_transfer_pending is not None or collect_pending is not None or preset_pending is not None or export_pending is not None or audio.recorder or audio.native_capture:app.message='STATE BUSY';continue
                            request=value;request['chains']={bus:copy.deepcopy(target['plugins']) for bus,target in bus_targets(app.project).items() if target.get('plugins')}
                            directory=ROOT/'cache'/'group-delete'/uuid.uuid4().hex
                            for bus,chain in request['chains'].items():
                                for index,plugin in enumerate(chain):
                                    folder=directory/str(bus)/str(index);plugin['state']=str(folder/'state.ttl')
                                    audio.command(f'plugin_save {bus} {index} '+json.dumps(str(folder)))
                            plugin_transfer_pending=request;audio.command('state_barrier')
                        elif action=='plugin_transfer':
                            if plugin_transfer_pending is not None or collect_pending is not None or preset_pending is not None or export_pending is not None:app.message='STATE BUSY';continue
                            request=value;directory=ROOT/'cache'/'plugin-clipboard'/uuid.uuid4().hex
                            indices=[request['slot']] if request['operation']=='COPY' else range(len(request['chain']))
                            for index in indices:
                                folder=directory/str(index);request['chain'][index]['state']=str(folder/'state.ttl')
                                audio.command(f'plugin_save {request["bus"]} {index} '+json.dumps(str(folder)))
                            plugin_transfer_pending=request;audio.command('state_barrier')
                        elif action=='plugin_paste':
                            if not sample_jobs.submit('PLUGIN_PASTE',None,{},copy_plugin_state,value,ROOT):app.message='PROCESS BUSY'
                        elif action=='save_plugin_state':audio.save_plugin_state(value)
                        elif action == 'plugin_controls':audio.plugins(*value)
                        elif action == 'plugins':
                            native_sequence.invalidate()
                            audio.plugins(*value)
                        elif controller_inputs.dispatch(action,value,audio,midi):pass
                        elif action=='voice_token':current_voice_token=value
                        elif action=='note_gate':
                            group,pad,note,length=value[:4];token=value[4] if len(value)>4 else 0
                            gate_counter+=1;heapq.heappush(gates,(time.monotonic()+length*app.clock_interval(),gate_counter,group,pad,note,token))
                        elif action == 'note_off':
                            group,pad,note=value;source=app.project['groups'][group]['pads'][pad]
                            for slot in app.linked_sounds(group,pad):
                                track=app.project['groups'][group]['pads'][slot];target_note=None if note is None else note-source.get('note',36+pad)+track.get('note',36+slot);audio.note_off(group,slot,target_note,0 if target_note is not None else None)
                                if target_note is not None and (track.get('source')=='MIDI' or track.get('routing',{}).get('midi_send')):midi.note_off(target_note,track['channel'],0)
                        elif action in ('detect_slices','analyze_slices'):
                            group,pad,track,sensitivity,zero=value
                            track.update(_generation=app.project_generation,_sensitivity=sensitivity,_zero=zero)
                            kind='ANALYSIS' if action=='analyze_slices' else 'DETECT'
                            if sample_jobs.submit(kind,(group,pad),track,detect_slices,track,sensitivity,zero):app.message='DETECTING'
                            else:app.message='PROCESS BUSY'
                        elif action=='slice_live_play':
                            track,token=value
                            if token!=app.live_chop_token:continue
                            audio.slice_preview(track,token)
                            if token==app.live_chop_token:app.live_chop_started=time.monotonic()
                        elif action == 'slice_play':
                            audio.slice_preview(value)
                        elif action == 'load':
                            native_sequence.invalidate()
                            audio.load(*value)
                        elif action=='import_mp3':
                            source,context=value
                            if not audio_imports.request('load',source,context):app.message='IMPORT BUSY: RETRY'
                        elif action == 'preview' and Path(value).name=='.preview.wav':
                            audio_imports.request('kit_preview',value,None)
                        elif action == 'preview' and Path(value).suffix.lower()=='.mp3':
                            audio.command('preview_stop')
                            audio_imports.request('preview',value,None)
                        elif action == 'preview':
                            audio_imports.cancel_preview()
                            with wave.open(str(value), 'rb') as wav:
                                track = {'sample': str(value), 'start': 0, 'end': wav.getnframes()}
                            audio.load(-1,0,track)
                            audio.command(f'hit {PREVIEW} 0.5')
                        elif action == 'preview_stop':
                            audio_imports.cancel_preview()
                            stretch_jobs.cancel()
                            audio.command('preview_stop')
                        elif action in ('hit','event_hit'):
                            group,original,velocity=value[:3];source=app.project['groups'][group]['pads'][original]
                            semitones=value[3]-source.get('note',36+original) if action=='event_hit' else 0
                            for slot in app.linked_sounds(group,original):
                                track=app.project['groups'][group]['pads'][slot];note=track.get('note',36+slot)+semitones
                                if track.get('source')=='MIDI' or track.get('routing',{}).get('midi_send'):midi.hit(slot,velocity,note,track['channel'],duration=None,voice_token=current_voice_token)
                                if track.get('source')!='MIDI' or track['sample'] or track.get('plugins'):audio.hit(group,slot,velocity,dict(track,gain=100),semitones,current_voice_token)
                            current_voice_token=0
                        elif action=='midi_note':
                            note,velocity,channel=value;source=app.track();semitones=note-source.get('note',36+app.pad)
                            for slot in app.linked_sounds(app.group,app.pad):
                                track=app.project['groups'][app.group]['pads'][slot];target_note=track.get('note',36+slot)+semitones
                                if track.get('source')=='MIDI' or track.get('routing',{}).get('midi_send'):midi.hit(slot,velocity,max(0,min(127,target_note)),track['channel'],duration=None)
                                if track.get('source')!='MIDI':audio.hit(app.group,slot,velocity,dict(track,gain=100),semitones)
                        elif action=='process':
                            track,processing=app.sample_process_request(value)
                            if sample_jobs.submit(value,(app.group,app.pad),track,process_sample,processing,value,ROOT/'samples/edited',ROOT/'cache/clipboard.wav'):app.message='NORMALIZE SAMPLE' if value=='NORMALIZE' else 'PROCESSING'
                            else:app.message='PROCESS BUSY'
                        elif action=='stretch_preview':
                            track,context,velocity=value
                            audio.command('preview_stop')
                            preview=stretch_jobs.request(track,context,velocity)
                            if preview:
                                rendered,velocity=preview;audio.stretch_preview(rendered,velocity)
                            else:app.message='PREPARING PREVIEW'
                        elif action == 'slice_preview':
                            track, index, count = value
                            size, start = track['end']-track['start'], track['start']
                            track['start'], track['end'] = start+size*index//count, start+size*(index+1)//count
                            audio.load(-1,0,track)
                            audio.command(f'hit {PREVIEW} 0.5')
                        elif action=='sound_reset':
                            group,pad,channel=value;audio.command(f'kill_bus {group*16+pad}')
                            for gate in gates:
                                if gate[2:4]==(group,pad):midi.note_off(gate[4],channel)
                            gates[:]=[gate for gate in gates if gate[2:4]!=(group,pad)];heapq.heapify(gates)
                            for bindings,recorded,started in app.live_notes.values():
                                for g,p,note in bindings:
                                    if (g,p)==(group,pad):midi.note_off(note,channel)
                        elif action == 'panic':
                            native_sequence.reset(max(0,app.clock_phase))
                            gates.clear();midi_performance.panic()
                            audio.command('panic')
                            midi.panic()
                        elif action == 'restart':
                            native_sequence.reset(0)
                            audio.command('panic')
                            next_step = time.monotonic()+app.clock_interval()
                        elif action in ('capture','capture_to'):
                            if audio.recorder or audio.native_capture or audio.capture_pending:app.message='ALREADY RECORDING';continue
                            audio.record_generation=app.project_generation
                            job=copy.deepcopy(value) if action=='capture_to' else dict(target=(app.group,app.pad),options=copy.deepcopy(app.capture_options()),result='AUDIO' if app.capture_options()['mode']=='LOOP' else 'SAMPLER')
                            device=(app.audio.capture if app.audio else None) if action=='capture_to' else value
                            if job['options']['source']!='INTERNAL' and not device:
                                app.capture_armed=False;app.message='NO AUDIO INPUT';continue
                            job['tempo']=app.project['tempo'];app.capture_job=job
                            audio.start_native_capture(device,tuple(job['target']),job['options'],app.project['tempo'])
                            if audio.native_capture:app.capture_jobs[str(audio.native_capture['path'])]=job
                            if audio.recorder and app.capture_started is None:
                                app.capture_started = time.monotonic()
                        elif action=='capture_trigger':audio.command('record_trigger')
                        elif action == 'capture_cancel':
                            if audio.native_capture and 'path' in audio.native_capture:app.capture_jobs.pop(str(audio.native_capture['path']),None)
                            app.capture_job=None
                            audio.native_cancel=True;audio.stop_capture()
                            app.capture_started = None
                            app.message = 'RECORDING CANCELLED'
                        elif action == 'capture_stop':
                            if audio.native_capture and audio.native_capture['mode']=='SYNC' and app.playing:
                                audio.native_capture['stop_requested']=app.clock_phase;app.message='STOP AT NEXT BAR';continue
                            result = audio.stop_capture()
                            app.capture_started = None
                            if result:app.actions.append(('record_result',(*result,audio.record_generation)))
                        elif action=='record_result':
                            target,path,generation=value
                            app.finish_sample_recording(target,path,generation)
                        elif action == 'reload':
                            app.capture_job=None;app.capture_jobs.clear()
                            native_sequence.invalidate();native_sequence.reset()
                            if audio.recorder or audio.native_capture:
                                audio.native_cancel=True;audio.stop_capture();app.capture_started=None;app.capture_armed=False
                            gates.clear();midi_performance.panic();audio.command('panic')
                            active_buses=bus_targets(app.project)
                            for bus in list(audio.plugin_chains):
                                if bus not in active_buses:audio.command(f'plugins {bus}')
                            audio.plugin_chains.clear()
                            for group, bank in enumerate(app.project['groups']):
                                for pad, track in enumerate(bank['pads']):
                                    audio.load(group,pad,track);audio.plugins(group*16+pad,track.get('plugins',[]))
                                audio.plugins(GROUP_BASE+group,bank.get('plugins',[]))
                            audio.plugins(MASTER,app.project.get('plugins',[]))
                    except (OSError, ValueError, wave.Error, EOFError) as error:
                        app.message = 'ACTION FAILED'
                        print(str(error), flush=True)
                led_now=time.monotonic()
                led_state=(app.playing,app.recording,app.shift,app.page,bool(app.count_remaining),app.record_prepare)
                if led_now>=next_led or led_state!=last_led_state:
                    leds=led_report(app,channels,led_now);output.submit_leds(leds)
                    next_led=led_now+.05;last_led_state=led_state
                native_sequence.update(app,audio,midi,time.monotonic(),next_step)
                frame_now=time.monotonic()
                if app.page!=display_budget_page:
                    display_budget=DisplayBudget();display_budget_page=app.page
                    step_display.invalidate()
                app.follow_step_view()
                app.follow_pattern_grid()
                mk2.update(frame_now)
                mk1.update(frame_now)
                mk3.update(frame_now)
                plus.update(frame_now)
                step_pixels=step_display.poll()
                if output.process and step_pixels is not None and app.page in ASYNC_PAGES:
                    output.submit(step_pixels,leds);last_frame=(step_pixels,bytes(leds))
                if output.process and app.page in ASYNC_PAGES and frame_now>=next_frame and not step_display.busy:
                    state=live_state(app)
                    if step_display.submit(state):next_frame=frame_now+.02
                frame_deadline=next_step if sync_mode!='IN' else (app.clock_last+app.clock_interval() if app.clock_last is not None else frame_now)
                if output.process and app.page not in ASYNC_PAGES and frame_now >= next_frame and display_budget.available(frame_now,frame_deadline,app.playing or bool(app.count_remaining)):
                    frame_started=time.monotonic()
                    envelope = None
                    if app.page in ('SAMPLE EDIT','CHOP','ZONE','STRETCH'):
                        with_path=(app.zone() or {}).get('sample') if app.page in ('ZONE','STRETCH') else app.track()['sample']
                        if with_path:
                            try:
                                with wave.open(with_path,'rb') as wav:bounds=(0,wav.getnframes()) if app.page in ('ZONE','STRETCH') else app.wave_bounds(wav.getnframes())
                                envelope=waveforms.envelope(with_path,*bounds)
                            except (OSError,EOFError,wave.Error):pass
                    pixels = display_pixels(app, envelope)
                    frame = (bytes(pixels), bytes(leds))
                    if frame != last_frame:
                        output.submit(pixels,leds)
                        last_frame = frame
                    display_budget.measured(time.monotonic()-frame_started)
                    next_frame = time.monotonic()+(0.02 if app.playing and app.page in ('PATTERN GRID','STEP') else 0.05)
            controller_inputs.disconnect('mikro');controller_inputs.disconnect('mk2');controller_inputs.disconnect('mk1');controller_inputs.disconnect('mk3');controller_inputs.disconnect('plus')
            autosaver.close()
            app.save();audio.save_plugin_state(app.project)
        finally:
            # Save edits also on disconnect; this version has one current project slot.
            try:
                controller_inputs.disconnect('mikro');controller_inputs.disconnect('mk2');controller_inputs.disconnect('mk1');controller_inputs.disconnect('mk3');controller_inputs.disconnect('plus')
                if app.dirty:
                    app.save()
                    if audio:audio.save_plugin_state(app.project)
            finally:
                if plus:plus.close()
                if mk3:mk3.close()
                if mk1:mk1.close()
                if mk2:mk2.close()
                if step_display:step_display.close()
                if 'stem_control' in locals():stem_control.close()
                if 'system_monitor' in locals():system_monitor.close()
                if 'power_control' in locals():power_control.close()
                if 'update_control' in locals():update_control.close()
                if 'autosaver' in locals():autosaver.close()
                if 'loop_watch' in locals():loop_watch.close()
                if 'device_monitor' in locals():device_monitor.close()
                if 'sound_runtime' in locals():sound_runtime.close()
                plugin_refresh.close()
                if live_banks:live_banks.close()
                waveforms.close()
                export_cancel.set()
                interface_mixer.close()
                hat_button.close()
                codec_levels.close()
                bluetooth.close()
                sample_jobs.close()
                audio_imports.close()
                chord_catalog.close()
                stretch_jobs.close()
                try:
                    midi.close()
                except OSError:
                    midi.close_ports()
                if audio:
                    audio.close()
                stretch_jobs.cleanup()
                if output:
                    output.close(locals().get('streams',{}))
                    print(f'Controller output: frames={output.frames}, max={output.max_ms:.2f}ms, avg={output.total_ms/max(1,output.frames):.2f}ms',flush=True)
                settings_writer.close()
                pid.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
