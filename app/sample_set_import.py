"""Sample-only expansion import. No vendor code, installers or synth execution.

MPC XML mapping is read directly; native Maschine kit parameters are not decoded.
Installed Maschine audio folders are converted and grouped by their sample folders.
"""
from pathlib import Path
import math
import os
import re
import shutil
import subprocess
import tempfile
import wave
import xml.etree.ElementTree as ET

AUDIO={'.wav','.aif','.aiff','.flac','.mp3','.ogg'}
METADATA={'.ttl','.xml','.xpm','.mxgrp','.mxsnd','.mxinst','.nksf','.nksn','.nki','.ncw','.nkx','.json','.txt','.png','.jpg','.jpeg','.sxq','.mid','.midi','.ds_store'}
MAX_BANKS=128
MAX_DECODED=1024**3


def title(value,fallback='Sample Kit'):
    value=''.join(c for c in str(value) if ord(c)>=32 and c not in '/\\').strip()
    return value[:80] or fallback


def xml(path):
    raw=Path(path).read_bytes()
    if len(raw)>4*1024**2 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('Unsupported expansion XML.')
    try:root=ET.fromstring(raw)
    except ET.ParseError as error:raise ValueError('Invalid expansion XML: '+Path(path).name) from error
    for node in root.iter():node.tag=node.tag.rsplit('}',1)[-1]
    return root


def convert(source,target):
    """Decode audio in a single low-priority subprocess, bounded in time and size."""
    source,target=Path(source),Path(target)
    if source.suffix.lower()=='.wav':
        shutil.copyfile(source,target)
    else:
        formats={'.aif':'aiff','.aiff':'aiff','.flac':'flac','.mp3':'mp3','.ogg':'ogg'}
        decoder=shutil.which('ffmpeg')
        if not decoder:raise ValueError('Audio converter is not installed.')
        command=[decoder,'-nostdin','-v','error','-xerror','-y','-threads','1','-filter_threads','1',
                 '-protocol_whitelist','file,pipe','-f',formats[source.suffix.lower()],'-i',str(source),
                 '-map','0:a:0','-map_metadata','-1','-vn','-sn','-dn','-threads','1','-c:a','pcm_s24le',
                 '-fs',str(MAX_DECODED+1024),'-f','wav',str(target)]
        with tempfile.TemporaryFile() as errors:
            process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=errors)
            try:
                if hasattr(os,'setpriority'):
                    try:os.setpriority(os.PRIO_PROCESS,process.pid,15)
                    except OSError:pass
                if process.wait(timeout=120):raise ValueError('Cannot decode audio: '+source.name)
            except BaseException:
                if process.poll() is None:process.kill();process.wait()
                raise
    if target.stat().st_size>MAX_DECODED:raise ValueError('Decoded sample exceeds 1 GiB.')
    from app.wav_validation import validate_pcm
    with target.open('r+b') as stream:validate_pcm(stream,{})
    with wave.open(str(target),'rb') as wav:
        if wav.getnchannels() not in (1,2) or wav.getnframes()<1:raise ValueError('Use non-empty mono or stereo samples.')
        return dict(frames=wav.getnframes(),rate=wav.getframerate(),channels=wav.getnchannels())


def plan(folder,name):
    """Return title, banks with sparse slot assignments, and explicit import notes."""
    folder=Path(folder);files=sorted((p for p in folder.rglob('*') if p.is_file()),key=lambda p:str(p.relative_to(folder)).casefold())
    audio=[p for p in files if p.suffix.lower() in AUDIO]
    if not audio:raise ValueError('No readable audio found. Import an installed expansion folder or ZIP/XPN with WAV, AIFF, FLAC, MP3 or OGG samples. Installers and protected/NCW content cannot be converted.')
    name=title(name);notes=[];banks=[];used=set();skipped=0
    manifests=[p for p in files if p.name.lower()=='expansion.xml']
    if manifests:
        root=xml(manifests[0])
        for field in ('title','name','Name','Title'):
            found=next((n.text for n in root.iter(field) if n.text and n.text.strip()),None)
            if found:name=title(found);break
    programs=[p for p in files if p.suffix.lower()=='.xpm']
    full={str(p.relative_to(folder)).casefold():p for p in audio};leaves={}
    for p in audio:
        for key in {p.name.casefold(),p.stem.casefold()}:leaves.setdefault(key,[]).append(p)
    def resolve(ref,parent):
        ref=ref.replace('\\','/');candidate=parent/ref
        if candidate.is_file() and candidate.resolve().is_relative_to(folder.resolve()) and candidate in audio:return candidate
        direct=full.get(ref.casefold())
        if direct:return direct
        matches=leaves.get(Path(ref).name.casefold(),[]) or leaves.get(Path(ref).stem.casefold(),[])
        if len(matches)!=1:raise ValueError('Missing or ambiguous MPC sample: '+ref)
        return matches[0]
    for program in programs:
        root=xml(program);prog=root if root.tag=='Program' else root.find('Program')
        if prog is None:notes.append(program.name+': no readable program.');continue
        kind=prog.get('type','Drum').lower()
        if kind not in ('drum','keygroup'):
            skipped+=1;continue
        if kind=='keygroup':
            # Preserve samples, not a misleading incomplete keygroup instrument.
            notes.append(program.name+': sample-based keygroup audio is available in Unassigned samples; key mapping is not imported.')
            continue
        label=title(prog.findtext('ProgramName') or program.stem);mapped={}
        for inst in prog.findall('Instruments/Instrument'):
            try:slot=int(inst.get('number','0'))-1
            except ValueError:raise ValueError('Invalid MPC pad number.')
            if not 0<=slot<128:continue
            layers=[]
            for layer in inst.findall('Layers/Layer'):
                ref=(layer.findtext('SampleName') or layer.findtext('SampleFile') or '').strip()
                if not ref or (layer.findtext('Active') or 'true').strip().lower()=='false':continue
                p=resolve(ref,program.parent);used.add(p)
                try:lo=max(1,min(127,int(layer.findtext('VelStart') or '1')));hi=max(lo,min(127,int(layer.findtext('VelEnd') or '127')))
                except ValueError:raise ValueError('Invalid MPC velocity layer.')
                layers.append(dict(path=p,vel_lo=lo,vel_hi=hi))
            if not layers:continue
            if len(layers)>16:raise ValueError('More than 16 sample layers on an MPC pad.')
            mapped[slot]=dict(name=title(inst.findtext('Name') or layers[0]['path'].stem),layers=layers)
            if len(layers)>1 and (inst.findtext('ZonePlay') or '1')!='1':notes.append(label+': layered pad imported as velocity zones; round-robin/stack behaviour is not reproduced.')
        if mapped:
            for index in range(max(mapped)//16+1):
                banks.append(dict(name=title(label+(' · '+chr(65+index) if max(mapped)>=16 else '')),pads=[mapped.get(index*16+i) for i in range(16)]))
    remaining=[p for p in audio if p not in used]
    if remaining:
        grouped={}
        for p in remaining:grouped.setdefault(p.parent,[]).append(p)
        for directory,rows in grouped.items():
            label=title(directory.name if directory!=folder and len(grouped)>1 else ('Unassigned samples' if banks else 'Bank'))
            for start in range(0,len(rows),16):
                suffix=' '+str(start//16+1) if len(rows)>16 else ''
                banks.append(dict(name=label+suffix,pads=[dict(name=p.stem,layers=[dict(path=p,vel_lo=1,vel_hi=127)]) for p in rows[start:start+16]]+[None]*(16-len(rows[start:start+16]))))
    if not banks:raise ValueError('No sample pads found.')
    if len(banks)>MAX_BANKS:raise ValueError('Expansion exceeds 128 banks / 2,048 pads. Import smaller folders.')
    vendor=[p for p in files if p.suffix.lower() in ('.mxgrp','.mxsnd','.mxinst','.nksf','.nksn','.nki','.ncw','.nkx')]
    if vendor:notes.append('Maschine audio imported by sample folder. Native kit mappings, effects, synth presets and protected/NCW content were skipped.')
    if skipped:notes.append(str(skipped)+' non-sample MPC program(s) skipped.')
    notes.append('Audio and sample pad assignments only; patterns, vendor effects and synth settings are not converted.')
    return dict(name=name,banks=banks,notes=list(dict.fromkeys(notes)))
