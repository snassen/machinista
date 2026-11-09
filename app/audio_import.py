"""Bounded MP3 decoding and latest-preview background jobs."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import wave
import struct
from contextlib import contextmanager
from app.wav_validation import validate_pcm

MAX_DECODED=64*1024**2


def decode_mp3(source,destination,cancel=None,pass_fds=()):
    decoder=shutil.which('ffmpeg')
    if not decoder:raise ValueError('MP3 decoder is not installed.')
    command=[decoder,'-nostdin','-hide_banner','-loglevel','error','-xerror','-y',
             '-threads','1','-filter_threads','1','-protocol_whitelist','file,pipe',
             '-f','mp3','-i',str(source),'-map','0:a:0','-map_metadata','-1',
             '-vn','-sn','-dn','-threads','1','-c:a','pcm_f32le',
             '-fs',str(MAX_DECODED+1024**2),'-f','wav',str(destination)]
    with tempfile.TemporaryFile() as errors:
        process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=errors,pass_fds=pass_fds)
        try:
            # Decoder work has lower CPU/I/O priority than live audio.
            if hasattr(os,'setpriority'):
                try:os.setpriority(os.PRIO_PROCESS,process.pid,15)
                except (OSError,ProcessLookupError):pass
            start=time.monotonic()
            while process.poll() is None:
                if cancel is not None and cancel.wait(.025):raise ValueError('MP3 import cancelled.')
                if cancel is None:time.sleep(.025)
                if time.monotonic()-start>120:raise ValueError('MP3 decoding timed out.')
            if process.returncode:raise ValueError('Invalid or unsupported MP3 file.')
        finally:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=2)
                except subprocess.TimeoutExpired:process.kill();process.wait()
    with wave_header(destination) as wav:
        if wav[0]>MAX_DECODED or wav[1] not in (1,2):raise ValueError('MP3 is too long (64 MiB decoded sample limit).')
    details={}
    with open(destination,'r+b') as stream:validate_pcm(stream,details);stream.flush();os.fsync(stream.fileno())
    details['converted']='PCM WAV from MP3'
    return details


@contextmanager
def wave_header(path):
    # Python wave cannot inspect IEEE float before conversion. Read just the
    # bounded RIFF chunk headers needed for the decoded-size limit.
    with open(path,'rb') as stream:
        stream.seek(0,2);size=stream.tell();stream.seek(0)
        header=stream.read(12)
        if len(header)!=12 or header[:4]!=b'RIFF' or header[8:]!=b'WAVE':raise ValueError('Invalid decoded MP3.')
        pos=12;channels=width=None;frames=None
        for _ in range(4096):
            if pos+8>size:break
            stream.seek(pos);kind,length=struct.unpack('<4sI',stream.read(8))
            if pos+8+length>size:raise ValueError('Incomplete decoded MP3.')
            if kind==b'fmt ':
                if length<16:raise ValueError('Invalid decoded MP3 format.')
                fmt=struct.unpack('<HHIIHH',stream.read(16));channels=fmt[1];width=fmt[5]//8
            if kind==b'data':
                if not channels or not width:raise ValueError('Invalid decoded MP3 format.')
                frames=length//(channels*width);break
            pos+=8+length+(length&1)
        if frames is None:raise ValueError('MP3 contains no audio.')
        yield frames*8,channels


def prepare_mp3(path,cache,cancel=None):
    path=Path(path).resolve();before=path.stat()
    signature=(str(path),before.st_size,before.st_mtime_ns)
    key=hashlib.sha256(json.dumps(signature).encode()).hexdigest()[:24]
    folder=Path(cache).resolve()/'decoded-audio'/key;folder.mkdir(parents=True,exist_ok=True)
    (folder/'source.json').write_text(json.dumps({'source':str(path)}))
    target=folder/(path.stem[:80]+'.wav');pcm=folder/'sampler.f32'
    if not target.exists():
        fd,temporary=tempfile.mkstemp(prefix='.decode-',suffix='.wav',dir=folder);os.close(fd)
        try:
            decode_mp3(path,temporary,cancel)
            after=path.stat()
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('MP3 changed while decoding. Retry.')
            os.replace(temporary,target)
        finally:Path(temporary).unlink(missing_ok=True)
    with wave.open(str(target),'rb') as wav:rate=wav.getframerate();frames=wav.getnframes()
    if not pcm.exists():
        if cancel is not None and cancel.is_set():raise ValueError('MP3 import cancelled.')
        from app.audio import convert_sample
        fd,temporary=tempfile.mkstemp(prefix='.pcm-',dir=folder);os.close(fd)
        try:convert_sample(dict(sample=str(target),start=0,end=frames),temporary);os.replace(temporary,pcm)
        finally:Path(temporary).unlink(missing_ok=True)
    stamp=target.stat();ready=((str(target.resolve()),stamp.st_mtime_ns,stamp.st_size),str(pcm),rate)
    return dict(sample=str(target),start=0,end=frames,_ready_pcm=ready)


def browse_origin(sample,cache):
    """Quick Browse should return to the MP3, not its private decoding cache."""
    if not sample:return sample
    path=Path(sample).resolve()
    if not path.is_relative_to((Path(cache)/'decoded-audio').resolve()):return sample
    try:
        with (path.parent/'source.json').open() as stream:metadata=json.loads(stream.read(4096))
        original=Path(metadata['source'])
        return str(original) if original.is_file() else sample
    except (OSError,ValueError,KeyError,TypeError):return sample


def prepare_kit_preview(path,cache,cancel):
    path=Path(path).resolve()
    stamp=path.stat()
    with wave.open(str(path),'rb') as wav:
        frames,rate=wav.getnframes(),wav.getframerate()
    if not 0<frames*8<=MAX_DECODED:raise ValueError('Invalid kit preview length.')
    decoder=shutil.which('ffmpeg')
    if not decoder:raise ValueError('Audio converter is not installed.')
    pcm=Path(cache)/'kit-preview.f32'
    fd,temporary=tempfile.mkstemp(prefix='.kit-preview-',dir=pcm.parent);os.close(fd)
    try:
        command=[decoder,'-nostdin','-v','error','-y','-threads','1','-f','wav','-i',str(path),
                 '-map','0:a:0','-ac','2','-c:a','pcm_f32le','-f','f32le','-fs',str(MAX_DECODED),temporary]
        with subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL) as process:
            try:
                if hasattr(os,'setpriority'):
                    try:os.setpriority(os.PRIO_PROCESS,process.pid,12)
                    except OSError:pass
                deadline=time.monotonic()+15
                while process.poll() is None:
                    if cancel.wait(.025) or time.monotonic()>=deadline:
                        raise ValueError('Kit preview cancelled or timed out.')
                if process.returncode:raise ValueError('Could not decode kit preview.')
            finally:
                if process.poll() is None:
                    process.kill()
        if cancel.is_set():raise ValueError('Kit preview cancelled.')
        if Path(temporary).stat().st_size!=frames*8:raise ValueError('Incomplete kit preview.')
        os.replace(temporary,pcm)
    finally:Path(temporary).unlink(missing_ok=True)
    return dict(sample=str(path),start=0,end=frames,_ready_pcm=((str(path),stamp.st_mtime_ns,stamp.st_size),str(pcm),rate))


class AudioImports:
    def __init__(self,cache,prepare=prepare_mp3):
        self.cache=cache;self.prepare=prepare;self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='mp3-import')
        self.pending=None;self.queued=[]
    @property
    def busy(self):return self.pending is not None or bool(self.queued)
    def request(self,kind,path,context):
        if kind not in ('load','preview','kit_preview'):raise ValueError('Invalid audio import action.')
        request=(kind,path,context)
        if kind!='load':self.cancel_preview()
        if len(self.queued)>=8:return False
        if kind=='load':
            self.cancel_preview();self.queued.insert(0,request)
        else:self.queued.append(request)
        self.start();return True
    def cancel_preview(self):
        self.queued=[r for r in self.queued if r[0]=='load']
        if self.pending and self.pending[0][0]!='load':self.pending[2].set()
    def start(self):
        if self.pending is None and self.queued:
            request=self.queued.pop(0);cancel=threading.Event()
            prepare=prepare_kit_preview if request[0]=='kit_preview' else self.prepare
            self.pending=(request,self.pool.submit(prepare,request[1],self.cache,cancel),cancel)
    def poll(self):
        if not self.pending or not self.pending[1].done():return None
        request,future,cancel=self.pending;self.pending=None
        try:result=future.result();error=None
        except Exception as exc:result=None;error=exc
        self.start()
        return (*request,result,error,cancel.is_set())
    def close(self):
        self.queued=[]
        if self.pending:self.pending[2].set()
        self.pool.shutdown(wait=True,cancel_futures=True)
