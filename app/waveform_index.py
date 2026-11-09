"""Reusable, bounded PCM display index; scrolling never rereads a WAV.

Display renderers query this index. File loading and construction
run in a separate worker; the audio/input dispatcher never receives PCM data.
"""
import array
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import sys
import threading
import wave
from app.waveform import Envelope


class WaveformIndex:
    block=256

    def __init__(self,path):
        try:os.setpriority(os.PRIO_PROCESS,threading.get_native_id(),10)
        except (AttributeError,OSError):pass
        with wave.open(str(path),'rb') as wav:
            self.width,self.channels,self.frames=wav.getsampwidth(),wav.getnchannels(),wav.getnframes()
            if self.width not in (1,2,3,4) or self.channels not in (1,2) or self.frames>8*1024*1024:
                raise ValueError('unsupported or oversized display sample')
            data=wav.readframes(self.frames)
        self.pcm=array.array({1:'B',2:'h',3:'i',4:'i'}[self.width])
        if self.width==3:
            self.pcm.extend(int.from_bytes(data[i:i+3],'little',signed=True) for i in range(0,len(data),3))
        else:
            self.pcm.frombytes(data)
            if self.width>1 and sys.byteorder!='little':self.pcm.byteswap()
        if len(self.pcm)!=self.frames*self.channels:raise ValueError('truncated display sample')
        self.low=array.array('i');self.high=array.array('i')
        stride=self.block*self.channels
        for i in range(0,len(self.pcm),stride):
            values=self.pcm[i:i+stride];self.low.append(min(values));self.high.append(max(values))

    @property
    def nbytes(self):
        return sum(len(a)*a.itemsize for a in (self.pcm,self.low,self.high))

    def envelope(self,start=0,end=None,columns=120):
        start=max(0,min(self.frames,start));end=self.frames if end is None else max(start,min(self.frames,end))
        peaks=[];c=self.channels;b=self.block
        for column in range(columns):
            first=start+(end-start)*column//columns;last=start+(end-start)*(column+1)//columns
            if first==last:peaks.append((0.0,0.0));continue
            lo=(first+b-1)//b;hi=last//b
            if lo>=hi:
                values=self.pcm[first*c:last*c];minimum,maximum=min(values),max(values)
            else:
                minimum,maximum=min(self.low[lo:hi]),max(self.high[lo:hi])
                edges=self.pcm[first*c:lo*b*c]+self.pcm[hi*b*c:last*c]
                if edges:minimum,maximum=min(minimum,min(edges)),max(maximum,max(edges))
            if self.width==1:minimum-=128;maximum-=128
            divisor=1<<(self.width*8-1);peaks.append((minimum/divisor,maximum/divisor))
        return Envelope(self.frames,tuple(peaks),start,end)


class IndexedWaveforms:
    def __init__(self, max_assets=2):
        self.max_assets=max_assets
        self.worker=ThreadPoolExecutor(max_workers=1,thread_name_prefix='display-wave-index')
        self.cache=OrderedDict();self.views=OrderedDict();self.future=None;self.loading_key=None
        self.budget=72*1024*1024;self.revision=0
    def collect(self):
        if self.future is None or not self.future.done():return
        try:result=self.future.result()
        except (OSError,ValueError,wave.Error,EOFError):result=None
        self.cache[self.loading_key]=result;self.future=None;self.revision+=1
        while len(self.cache)>1 and (len(self.cache)>self.max_assets or sum(v.nbytes for v in self.cache.values() if v)>self.budget):
            key,_=self.cache.popitem(last=False)
            self.views=OrderedDict((k,v) for k,v in self.views.items() if k[0]!=key)
    def key(self,path):
        if not path:return None
        try:metadata=Path(path).stat()
        except OSError:return None
        return str(path),metadata.st_mtime_ns,metadata.st_size
    def prepare(self,key,path):
        if key in self.cache:self.cache.move_to_end(key)
        elif self.future is None:
            self.loading_key=key;self.future=self.worker.submit(WaveformIndex,path)
    def prefetch(self,path):
        self.collect();key=self.key(path)
        if key is not None:self.prepare(key,path)
    def envelope(self,path,start=0,end=None,columns=120):
        self.collect();key=self.key(path)
        if key is None:return Envelope(0,()) if path else None
        self.prepare(key,path)
        if key not in self.cache:return None
        index=self.cache[key]
        if index is None:return Envelope(0,())
        view=(key,start,end,columns)
        if view not in self.views:
            self.views[view]=index.envelope(start,end,columns)
            if len(self.views)>64:self.views.popitem(last=False)
        else:self.views.move_to_end(view)
        return self.views[view]
    def close(self):self.worker.shutdown(wait=True,cancel_futures=True)
