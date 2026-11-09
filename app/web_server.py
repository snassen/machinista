"""Standalone LAN sample library server. Never imports or changes the live engine."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, quote
import hashlib
import base64
import ipaddress
import json
import os
import secrets
import socket
import stat
import threading
import time

from app.browser import Source, mounted_sources
from app.system_info import read_resources

MAX_UPLOAD = 1024**3
RESERVE = 256*1024**2
CHUNK = 64*1024


def filename(value):
    if not value or value in ('.','..') or value.startswith('.') or any(c in value for c in ('/','\\','\0')) or any(ord(c)<32 for c in value) or len(value.encode('utf-8'))>240:
        raise ValueError('Invalid name.')
    return value


class Library:
    def __init__(self, root, source_scan=mounted_sources, password=None):
        self.authorization=('Basic '+base64.b64encode(('admin:'+password).encode()).decode()) if password else None
        from app.hardware_profiles import current
        self.hardware_profile=current()
        self.root=Path(root);self.samples=self.root/'samples';self.scan=source_scan
        self.token=secrets.token_urlsafe(32);self.upload_lock=threading.Lock();self.stats_lock=threading.Lock()
        from app.web_projects import Projects
        self.projects=Projects(self)
        from app.web_sets import SampleSets
        self.sets=SampleSets(self)
        from app.web_files import Files
        self.files=Files(self)
        from app.chord_library import ChordLibrary
        self.chords=ChordLibrary(self.root)
        from app.web_sounds import Sounds
        self.sounds=Sounds(self)
        from app.web_soundfonts import SoundFonts
        self.soundfonts=SoundFonts(self)
        from app.web_stems import Stems
        self.stems=Stems(self)
        self.previous=None;self.stats=None;self.next_stats=0

    def sources(self):
        rows=[('sd',Source('SD CARD',self.samples))]
        rows += [('usb-'+hashlib.sha256(str(s.path).encode()).hexdigest()[:16],s) for s in self.scan()]
        return dict(rows)

    def source(self, identity):
        source=self.sources().get(identity)
        if source is None:raise FileNotFoundError('Storage device unavailable.')
        return source

    @contextmanager
    def directory(self, source, relative):
        # Descriptor-relative traversal prevents symlinks/path races from
        # exposing projects, settings or arbitrary files outside the library.
        if relative.startswith('/') or '\\' in relative:raise ValueError('Invalid folder path.')
        parts=relative.split('/') if relative else []
        for part in parts:filename(part)
        fd=os.open(source.path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            for part in parts:
                child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                os.close(fd);fd=child
            yield fd
        finally:os.close(fd)

    def list(self, identity, relative):
        source=self.source(identity)
        with self.directory(source,relative) as fd:
            entries=[]
            with os.scandir(fd) as iterator:
                for item in iterator:
                    if item.name.startswith('.') or item.is_symlink():continue
                    folder=item.is_dir(follow_symlinks=False)
                    if not folder and (not item.is_file(follow_symlinks=False) or Path(item.name).suffix.lower() not in ('.wav','.mp3')):continue
                    info=item.stat(follow_symlinks=False)
                    entries.append(dict(name=item.name,folder=folder,size=info.st_size,modified=info.st_mtime))
                    if len(entries)>10000:raise ValueError('More than 10,000 entries. Please organize the library into subfolders.')
            writable=not source.read_only and os.access(f'/proc/self/fd/{fd}',os.W_OK) if Path('/proc/self/fd').exists() else not source.read_only and os.access(source.path,os.W_OK)
        return dict(entries=sorted(entries,key=lambda x:(not x['folder'],x['name'].casefold())),writable=writable)

    def mkdir(self, identity, relative, name):
        source=self.source(identity)
        if source.read_only:raise PermissionError('The storage device is read-only.')
        with self.directory(source,relative) as fd:os.mkdir(filename(name),mode=0o755,dir_fd=fd)

    def upload(self, identity, relative, name, stream, length):
        name=filename(name)
        mp3=Path(name).suffix.lower()=='.mp3'
        if Path(name).suffix.lower() not in ('.wav','.mp3'):raise ValueError('Please upload WAV or MP3 files.')
        if mp3:name=filename(Path(name).stem+'.wav')
        if not 0<length<=MAX_UPLOAD:raise ValueError('Maximum 1 GiB per audio file.')
        source=self.source(identity)
        if source.read_only:raise PermissionError('The storage device is read-only.')
        if not self.upload_lock.acquire(blocking=False):raise BlockingIOError('An upload is already in progress. Please wait.')
        try:
            with self.directory(source,relative) as directory:
                disk=os.fstatvfs(directory)
                if disk.f_bavail*disk.f_frsize<length+RESERVE:raise OSError('Not enough free space (256 MiB reserved).')
                try:os.stat(name,dir_fd=directory,follow_symlinks=False)
                except FileNotFoundError:pass
                else:raise FileExistsError('This file already exists. Please rename it before uploading.')
                temporary='.upload-'+secrets.token_hex(12)
                temporaries=[temporary];publication=temporary
                try:
                    fd=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_RDWR|os.O_NOFOLLOW,0o644,dir_fd=directory)
                    with os.fdopen(fd,'w+b') as out:
                        remaining=length
                        while remaining:
                            block=stream.read(min(CHUNK,remaining))
                            if not block:raise ValueError('Upload incomplete.')
                            out.write(block);remaining-=len(block)
                        out.flush()
                        from app.wav_validation import validate_pcm
                        details={}
                        if mp3:
                            from app.audio_import import decode_mp3
                            publication='.upload-decoded-'+secrets.token_hex(12);temporaries.append(publication)
                            decoded_fd=os.open(publication,os.O_CREAT|os.O_EXCL|os.O_RDWR|os.O_NOFOLLOW,0o644,dir_fd=directory)
                            with os.fdopen(decoded_fd,'w+b') as decoded:
                                base='/proc/self/fd' if Path('/proc/self/fd').exists() else '/dev/fd'
                                details=decode_mp3(f'{base}/{out.fileno()}',f'{base}/{decoded.fileno()}',pass_fds=(out.fileno(),decoded.fileno()))
                            details['saved_name']=name
                        else:validate_pcm(out,details)
                        os.fsync(out.fileno())
                    # Atomic publication without overwriting an existing sample.
                    # renameat2 isn't portable; hard-link first where available.
                    try:os.link(publication,name,src_dir_fd=directory,dst_dir_fd=directory,follow_symlinks=False)
                    except OSError as error:
                        # FAT/exFAT lack hard links. This process serializes all
                        # writes; reserve the destination exclusively before rename.
                        import errno
                        if error.errno not in (errno.EPERM,errno.EOPNOTSUPP,errno.ENOSYS):raise
                        reserved=os.open(name,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o644,dir_fd=directory)
                        os.close(reserved)
                        try:os.replace(publication,name,src_dir_fd=directory,dst_dir_fd=directory)
                        except BaseException:
                            os.unlink(name,dir_fd=directory);raise
                    os.fsync(directory)
                finally:
                    for item in temporaries:
                        try:os.unlink(item,dir_fd=directory)
                        except FileNotFoundError:pass
        finally:self.upload_lock.release()
        return details

    def system(self):
        with self.stats_lock:
            now=time.monotonic()
            if self.stats is None or now>=self.next_stats:
                resources,self.previous=read_resources(self.root,tuple(self.scan()),self.previous)
                def number(path,scale=1):
                    try:return float(Path(path).read_text().split()[0])/scale
                    except (OSError,ValueError,IndexError):return None
                resources.update(hardware_profile=self.hardware_profile,hostname=socket.gethostname(),uptime=number('/proc/uptime'),temperature=number('/sys/class/thermal/thermal_zone0/temp',1000))
                self.stats=resources;self.next_stats=now+1
            return self.stats


class Server(ThreadingHTTPServer):
    daemon_threads=True;request_queue_size=8
    def __init__(self,address,library,allow_unauthenticated=False):
        if not library.authorization and not allow_unauthenticated and address[0] not in ('127.0.0.1','::1','localhost'):raise ValueError('LAN access requires a password.')
        self.library=library;self.slots=threading.BoundedSemaphore(6)
        super().__init__(address,Handler)
    def process_request(self,request,client_address):
        if not self.slots.acquire(blocking=False):request.close();return
        try:super().process_request(request,client_address)
        except BaseException:self.slots.release();raise
    def process_request_thread(self,request,client_address):
        try:super().process_request_thread(request,client_address)
        finally:self.slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version='Machinista';sys_version=''
    def setup(self):
        super().setup();self.connection.settimeout(45)
    def response_headers(self,status,content_type,length,extra=()):
        self.send_response(status);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(length))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; media-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
        for k,v in extra:self.send_header(k,v)
        self.end_headers()
    def json(self,value,status=200):
        body=json.dumps(value,ensure_ascii=False).encode();self.response_headers(status,'application/json; charset=utf-8',len(body));self.wfile.write(body)
    def parsed(self):
        host=self.headers.get('Host','');name=urlsplit('//'+host).hostname or ''
        allowed=name.lower() in ('localhost',socket.gethostname().lower(),socket.gethostname().lower()+'.local')
        try:allowed=allowed or ipaddress.ip_address(name).is_private
        except ValueError:pass
        if not allowed:raise PermissionError('Unknown host.')
        url=urlsplit(self.path);q=parse_qs(url.query)
        return url.path,{k:v[0] for k,v in q.items()}
    def do_GET(self):self.dispatch(False)
    def do_POST(self):self.dispatch(True)
    def dispatch(self,write):
        try:
            path,q=self.parsed();library=self.server.library
            if library.authorization and not secrets.compare_digest(self.headers.get('Authorization','').encode(),library.authorization.encode()):
                self.close_connection=True;self.response_headers(401,'text/plain; charset=utf-8',0,[('WWW-Authenticate','Basic realm="Machinista", charset="UTF-8"')]);return
            disabled=(not library.hardware_profile['lv2'] and path.startswith(('/api/lv2','/api/plugin-banks'))) or (not library.hardware_profile['synth'] and path.startswith(('/api/synth','/api/oscillators'))) or (not library.hardware_profile['stems'] and path.startswith('/api/stems'))
            if disabled:raise PermissionError('This feature is disabled on '+library.hardware_profile['name']+'.')
            if write:
                origin=self.headers.get('Origin')
                if origin and origin!='http://'+self.headers.get('Host'):raise PermissionError('Invalid origin.')
                if not secrets.compare_digest(self.headers.get('X-Machinista-Token',self.headers.get('X-Machinist-Token','')),library.token):raise PermissionError('Please reload the page.')
                if path in ('/api/sets/import','/api/sets/upload','/api/sets/stage/file','/api/sets/inspect-mxgrp'):
                    if self.headers.get('Transfer-Encoding'):raise ValueError('Content-Length required.')
                    length=int(self.headers.get('Content-Length','0'))
                    if path=='/api/sets/inspect-mxgrp':result=library.sets.editor.inspect_maschine_kit(q.get('name',''),self.rfile,length,local=q.get('local')=='1')
                    elif path=='/api/sets/stage/file':result=library.sets.editor.upload_file(q.get('upload',''),q.get('path',''),self.rfile,length)
                    elif path=='/api/sets/import':result=library.sets.editor.import_archive(q.get('name',''),self.rfile,length,q.get('storage','sd'))
                    else:result=library.sets.upload(q.get('name',''),self.rfile,length)
                    self.json(result);return
                if path in ('/api/sets/save','/api/sets/delete','/api/sets/stage/start','/api/sets/stage/discard','/api/sets/import-folder','/api/sets/folders/create','/api/sets/folders/delete'):
                    length=int(self.headers.get('Content-Length','0'))
                    if self.headers.get('Transfer-Encoding') or not 0<length<=2*1024**2:raise ValueError('Invalid sample kit request size.')
                    value=json.loads(self.rfile.read(length))
                    if not isinstance(value,dict):raise ValueError('Invalid sample kit request.')
                    editor=library.sets.editor
                    if path.startswith('/api/sets/folders/'):
                        self.json(editor.manage_folder(value,delete=path.endswith('/delete')));return
                    operation={'/api/sets/save':editor.save,'/api/sets/delete':editor.delete,'/api/sets/stage/discard':editor.discard_stage,'/api/sets/import-folder':editor.import_folder}.get(path)
                    self.json(operation(value) if operation else editor.start(value));return
                if path in ('/api/stems/start','/api/stems/install','/api/stems/cancel'):
                    length=int(self.headers.get('Content-Length','0'))
                    if self.headers.get('Transfer-Encoding') or not 0<length<=8192:raise ValueError('Invalid stem request size.')
                    value=json.loads(self.rfile.read(length))
                    if not isinstance(value,dict):raise ValueError('Invalid stem request.')
                    result=library.stems.start(value) if path.endswith('/start') else library.stems.install() if path.endswith('/install') else library.stems.abort()
                    self.json(result);return
                if path=='/api/soundfonts/upload':
                    if self.headers.get('Transfer-Encoding'):raise ValueError('Content-Length required.')
                    self.json(library.soundfonts.upload(q.get('name',''),self.rfile,int(self.headers.get('Content-Length','0'))));return
                if path in ('/api/soundfonts/inspect','/api/soundfonts/import','/api/soundfonts/delete'):
                    length=int(self.headers.get('Content-Length','0'))
                    if self.headers.get('Transfer-Encoding') or not 0<length<=8192:raise ValueError('Invalid SoundFont request size.')
                    value=json.loads(self.rfile.read(length))
                    if not isinstance(value,dict):raise ValueError('Invalid SoundFont request.')
                    action={'/api/soundfonts/inspect':library.soundfonts.inspect,'/api/soundfonts/import':library.soundfonts.import_sound,'/api/soundfonts/delete':library.soundfonts.delete}[path]
                    self.json(action(value));return
                if path in ('/api/sounds/save','/api/sounds/command','/api/sounds/folder','/api/sounds/sample-info','/api/sounds/delete'):
                    from app.sound_library import MAX_JSON,folders
                    length=int(self.headers.get('Content-Length','0'))
                    if self.headers.get('Transfer-Encoding') or not 0<length<=MAX_JSON:raise ValueError('Invalid Sound request size.')
                    value=json.loads(self.rfile.read(length))
                    if path.endswith('/delete'):self.json(library.sounds.delete(value))
                    elif path.endswith('/sample-info'):self.json(library.sounds.info(value))
                    elif path.endswith('/save'):self.json(library.sounds.save(value))
                    elif path.endswith('/folder'):
                        with library.sounds.store.directory(folders(value.get('folder','')),True):pass
                        self.json({'ok':True})
                    else:
                        op=value.pop('operation',None)
                        if op not in ('load','save_current','autosample','cancel','plugin_parameters','synth_edit'):raise ValueError('Invalid Sound operation.')
                        self.json(library.sounds.command(op,value))
                    return
                if path in ('/api/virtualjv/upload','/api/virtualjv/prepare','/api/virtualjv/delete'):
                    from app.web_virtualjv import VirtualJV
                    if not library.upload_lock.acquire(blocking=False):raise BlockingIOError('Another upload is in progress.')
                    try:
                        addon=VirtualJV(library)
                        if path.endswith('/upload'):
                            length=int(self.headers.get('Content-Length','0'))
                            if self.headers.get('Transfer-Encoding'):raise ValueError('Invalid upload encoding.')
                            self.json(addon.upload(q.get('name',''),self.rfile,length))
                        elif path.endswith('/delete'):self.json(addon.delete(q.get('name','')))
                        else:self.json(addon.prepare())
                    finally:library.upload_lock.release()
                    return
                if path in ('/api/chords/upload','/api/chords/save','/api/chords/delete'):
                    from app.chords import MAX_BYTES,parse,normalize
                    if not library.upload_lock.acquire(blocking=False):raise BlockingIOError('Another upload is in progress.')
                    try:
                        if path.endswith('/delete'):result=library.chords.delete(q.get('id',''))
                        else:
                            length=int(self.headers.get('Content-Length','0'))
                            if self.headers.get('Transfer-Encoding') or not 0<length<=MAX_BYTES:raise ValueError('Maximum 1 MiB per chord preset.')
                            data=self.rfile.read(length)
                            if len(data)!=length:raise ValueError('Incomplete chord upload.')
                            preset=parse(data,q.get('name','')) if path.endswith('/upload') else normalize(json.loads(data))
                            result=library.chords.save(preset,q.get('id') if path.endswith('/save') else None)
                    finally:library.upload_lock.release()
                    self.json(result);return
                if path=='/api/files/delete':
                    if q.get('confirmed')!='true':raise ValueError('Confirm permanent deletion first.')
                    self.json(library.files.delete(q.get('source','sd'),q.get('path',''),q.get('name','')));return
                if path=='/api/files/move':
                    self.json(library.files.move(q.get('source','sd'),q.get('path',''),q.get('name',''),q.get('target_source','sd'),q.get('target_path','')));return
                if path=='/api/update':
                    from app.updater import request,enabled
                    if not enabled(library.root):raise PermissionError('Updates are not enabled in this image edition.')
                    op=q.get('op')
                    if op not in ('channel','check','install'):raise ValueError('Invalid update action.')
                    if not library.upload_lock.acquire(blocking=False):raise BlockingIOError('Wait for the upload to finish first.')
                    try:self.json(request(dict(op=op,channel=q.get('channel'),expected=q.get('expected'))))
                    finally:library.upload_lock.release()
                    return
                if path=='/api/ssh':
                    from app.power_client import request
                    action=q.get('action')
                    if action not in ('enable','disable'):raise ValueError('Invalid SSH action.')
                    self.json(request('ssh-'+action));return
                if path=='/api/power':
                    from app.power_client import request
                    action=q.get('action')
                    if action not in ('reboot','shutdown'):raise ValueError('Invalid power action.')
                    if not library.upload_lock.acquire(blocking=False):raise BlockingIOError('Wait for the upload to finish first.')
                    try:self.json(request(action))
                    finally:library.upload_lock.release()
                    return
                if path=='/api/projects/upload':
                    if self.headers.get('Transfer-Encoding'):raise ValueError('Content-Length required.')
                    self.json(library.projects.upload(q.get('name',''),self.rfile,int(self.headers.get('Content-Length','0'))));return
                if path=='/api/projects/delete':
                    length=int(self.headers.get('Content-Length','0'))
                    if self.headers.get('Transfer-Encoding') or not 0<length<=8192:raise ValueError('Invalid project request size.')
                    self.json(library.projects.delete(json.loads(self.rfile.read(length))));return
                if path in ('/api/oscillators/upload','/api/oscillators/delete','/api/oscillators/edit'):
                    from app import synth_library as synth
                    if not library.upload_lock.acquire(blocking=False):raise BlockingIOError('Another upload is in progress.')
                    try:
                        if path.endswith('/upload'):
                            if self.headers.get('Transfer-Encoding'):raise ValueError('Content-Length required.')
                            result=synth.upload(library.root,q.get('name',''),self.rfile,int(self.headers.get('Content-Length','0')),int(q.get('cycle','0')),q.get('mono')=='1',q.get('folder',''),q.get('tags','').split())
                        elif path.endswith('/delete'):result=synth.delete(library.root,q.get('id',''))
                        else:
                            length=int(self.headers.get('Content-Length','0'))
                            if self.headers.get('Transfer-Encoding') or not 0<length<=8192:raise ValueError('Invalid waveform metadata.')
                            result=synth.edit(library.root,q.get('id',''),json.loads(self.rfile.read(length)))
                    finally:library.upload_lock.release()
                    self.json(result);return
                if path=='/api/plugin-banks/upload':
                    from app.web_plugin_banks import upload
                    if self.headers.get('Transfer-Encoding'):raise ValueError('Content-Length required.')
                    if not library.upload_lock.acquire(blocking=False):raise BlockingIOError('Another upload is in progress.')
                    try:result=upload(library.root,q.get('name',''),q.get('profile',''),self.rfile,int(self.headers.get('Content-Length','0')))
                    finally:library.upload_lock.release()
                    self.json(result);return
                if path=='/api/plugin-banks/delete':
                    from app.web_plugin_banks import delete
                    if not library.upload_lock.acquire(blocking=False):raise BlockingIOError('Another upload is in progress.')
                    try:result=delete(library.root,q.get('profile',''),q.get('id',''))
                    finally:library.upload_lock.release()
                    self.json(result);return
                if path=='/api/lv2/upload':
                    from app.lv2_client import upload
                    if self.headers.get('Transfer-Encoding'):raise ValueError('Content-Length required.')
                    if not library.upload_lock.acquire(blocking=False):raise BlockingIOError('Another upload is in progress.')
                    try:result=upload(q.get('name',''),self.rfile,int(self.headers.get('Content-Length','0')))
                    finally:library.upload_lock.release()
                    self.json(result);return
                if path in ('/api/lv2/delete','/api/lv2/refresh'):
                    from app.lv2_client import request
                    self.json(request('delete' if path.endswith('/delete') else 'refresh',id=q.get('id')));return
                if path=='/api/upload':
                    if self.headers.get('Transfer-Encoding'):raise ValueError('Content-Length required.')
                    details=library.upload(q.get('source','sd'),q.get('path',''),q.get('name',''),self.rfile,int(self.headers.get('Content-Length','0')))
                    self.json({'ok':True,**details});return
                if path=='/api/folder':
                    library.mkdir(q.get('source','sd'),q.get('path',''),q.get('name',''));self.json({'ok':True});return
                if path=='/api/network/connect':
                    from app.network_client import request
                    length=int(self.headers.get('Content-Length','0'))
                    if self.headers.get('Transfer-Encoding') or not 0<length<=2048:raise ValueError('Invalid Wi-Fi request.')
                    value=json.loads(self.rfile.read(length))
                    self.json(request('connect',ssid=value.get('ssid'),password=value.get('password','')));return
            else:
                if path=='/api/sets':self.json(library.sets.listing(q.get('storage','sd')));return
                if path=='/api/sets/folders':self.json(sorted((p.name for p in library.sets.expansions(library.sets.root(q.get('storage','sd')))),key=str.casefold));return
                if path=='/api/sets/item':self.json(library.sets.editor.item(q.get('id','')));return
                if path=='/api/sets/audio':
                    raw=q.get('ref','')
                    if len(raw)>4096:raise ValueError('Invalid sample reference.')
                    ref=json.loads(raw)
                    extension=Path(ref.get('name') or ref.get('path','')).suffix.lower() if isinstance(ref,dict) else ''
                    if extension=='.png':raise ValueError('Choose an audio sample.')
                    mime={'.mp3':'audio/mpeg','.ogg':'audio/ogg','.flac':'audio/flac','.aif':'audio/aiff','.aiff':'audio/aiff'}.get(extension,'audio/wav')
                    with library.sets.editor.asset(ref) as stream:self.audio_stream(stream,mime)
                    return
                if path=='/api/sets/file':
                    with library.sets.download(q.get('id','')) as (stream,mime,name):
                        stream.seek(0,2);size=stream.tell();stream.seek(0)
                        self.response_headers(200,mime,size,[('Content-Disposition',"attachment; filename*=UTF-8''"+quote(name))])
                        while block:=stream.read(CHUNK):self.wfile.write(block)
                    return
                if path=='/api/stems':self.json(library.stems.status());return
                if path=='/api/soundfonts':self.json(library.soundfonts.status());return
                if path=='/api/sounds':self.json(library.sounds.status());return
                if path=='/api/sounds/current':self.json(library.sounds.current());return
                if path=='/api/virtualjv':
                    from app.web_virtualjv import VirtualJV
                    self.json(VirtualJV(library).status());return
                if path=='/api/sounds/runtime':self.json(library.sounds.runtime());return
                if path=='/api/sounds/item':self.json(library.sounds.store.draft(q.get('id')));return
                if path=='/api/chords':self.json(library.chords.list());return
                if path=='/api/projects':self.json(library.projects.list());return
                if path=='/api/projects/file':
                    with library.projects.download(q.get('id',''),q.get('format','zip')) as (stream,mime,name):
                        stream.seek(0,2);size=stream.tell();stream.seek(0)
                        self.response_headers(200,mime,size,[('Content-Disposition',"attachment; filename*=UTF-8''"+quote(name))])
                        while block:=stream.read(CHUNK):self.wfile.write(block)
                    return
                if path=='/api/synth/wave':
                    from app.synth_library import listing
                    from app.synth_display import user_preview
                    row=next((r for r in listing(library.root) if r['id']==q.get('id')),None)
                    if row is None:raise ValueError('Waveform no longer available.')
                    self.json(dict(id=row['id'],frames=user_preview(str(library.root),row['id'])));return
                if path=='/api/synth':
                    from app.web_synth import schema
                    self.json(schema(library.root));return
                if path=='/api/oscillators':
                    from app.synth_library import listing,FACTORY
                    self.json(dict(factory=FACTORY,users=listing(library.root)));return
                if path=='/api/plugin-banks':
                    from app.web_plugin_banks import listing
                    self.json(listing(library.root));return
                if path=='/api/lv2':
                    from app.lv2_client import request
                    self.json(request('status'));return
                if path=='/api/session':self.json({'token':library.token,'hardware_profile':library.hardware_profile});return
                if path=='/api/sources':
                    self.json([dict(id=k,name=v.name,readOnly=v.read_only) for k,v in library.sources().items()]);return
                if path=='/api/list':self.json(library.list(q.get('source','sd'),q.get('path','')));return
                if path=='/api/system':self.json(library.system());return
                if path=='/api/update':
                    from app.updater import request,enabled,initial
                    if not enabled(library.root):self.json(dict(enabled=False));return
                    try:self.json(request({'op':'status'}))
                    except OSError:self.json(initial(library.root))
                    return
                if path=='/api/ssh':
                    from app.power_client import request
                    self.json(request('ssh-status'));return
                if path=='/api/power':
                    from app.power_client import request
                    self.json(request('status'));return
                if path in ('/api/network','/api/network/scan'):
                    from app.network_client import request
                    self.json(request('scan' if path.endswith('/scan') else 'status'));return
                if path=='/api/file':self.download(q);return
                assets={'/sets.js':('sets.js','text/javascript; charset=utf-8'),'/stems.js':('stems.js','text/javascript; charset=utf-8'),'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/sounds.js':('sounds.js','text/javascript; charset=utf-8'),'/soundfonts.js':('soundfonts.js','text/javascript; charset=utf-8'),'/oscillators.js':('oscillators.js','text/javascript; charset=utf-8'),'/synth.js':('synth.js','text/javascript; charset=utf-8'),'/virtualjv.js':('virtualjv.js','text/javascript; charset=utf-8'),'/updates.js':('updates.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8'),'/logo.png':('logo.png','image/png')}
                if path in assets:
                    name,mime=assets[path];body=(library.root/'web'/name).read_bytes();self.response_headers(200,mime,len(body));self.wfile.write(body);return
            self.json({'error':'Not found.'},404)
        except (BrokenPipeError,ConnectionResetError,TimeoutError):self.close_connection=True
        except Exception as error:
            self.close_connection=True
            status=409 if isinstance(error,FileExistsError) else 403 if isinstance(error,PermissionError) else 404 if isinstance(error,FileNotFoundError) else 429 if isinstance(error,BlockingIOError) else 400
            self.json({'error':str(error) if isinstance(error,(ValueError,OSError)) else 'Request failed.'},status)
    def download(self,q):
        library=self.server.library;source=library.source(q.get('source','sd'));name=filename(q.get('name',''))
        if Path(name).suffix.lower() not in ('.wav','.mp3'):raise PermissionError('Audio files only.')
        mime='audio/mpeg' if Path(name).suffix.lower()=='.mp3' else 'audio/wav'
        with library.directory(source,q.get('path','')) as directory:
            fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory)
        with os.fdopen(fd,'rb') as stream:
            self.audio_stream(stream,mime,name if q.get('download')=='1' else None)

    def audio_stream(self,stream,mime='audio/wav',name=None):
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):raise PermissionError('Not a sample file.')
        start,end,status=0,info.st_size-1,200;extra=[('Accept-Ranges','bytes')]
        value=self.headers.get('Range')
        if value:
            import re
            match=re.fullmatch(r'bytes=(\d*)-(\d*)',value)
            if not match or not any(match.groups()):self.response_headers(416,mime,0);return
            first,last=match.groups()
            if first:start=int(first);end=min(end,int(last)) if last else end
            else:start=max(0,info.st_size-int(last))
            if start>end or start>=info.st_size:self.response_headers(416,mime,0,[('Content-Range',f'bytes */{info.st_size}')]);return
            status=206;extra.append(('Content-Range',f'bytes {start}-{end}/{info.st_size}'))
        if name:extra.append(('Content-Disposition',"attachment; filename*=UTF-8''"+quote(name)))
        remaining=max(0,end-start+1);self.response_headers(status,mime,remaining,extra);stream.seek(start)
        while remaining:
            block=stream.read(min(CHUNK,remaining))
            if not block:break
            self.wfile.write(block);remaining-=len(block)
