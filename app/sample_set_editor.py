"""Transactional bank/pad editing and bounded sample-only expansion transfers."""
from contextlib import contextmanager
from pathlib import Path
import copy
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import wave
import tempfile
import time
import threading
from functools import wraps
import uuid
import zipfile
from app.kit_artwork import KIT_ARTWORK,MAX_IMAGE_BYTES,decode_png
from app.sample_set_import import AUDIO,METADATA,MAX_BANKS,convert,plan,title
from app.web_projects import parts,MAX_PACKAGE,RESERVE

MAX_FILES=8192
KIT_PREVIEW='.preview.wav'


def one_import(function):
    @wraps(function)
    def run(self,*args,**kwargs):
        if not self.import_lock.acquire(blocking=False):raise BlockingIOError('An expansion import is already running.')
        try:return function(self,*args,**kwargs)
        finally:self.import_lock.release()
    return run


class SetEditor:
    def __init__(self,sets):
        self.sets=sets;self.library=sets.library;self.folder=sets.folder;self.import_lock=threading.RLock()

    def metadata(self,base):
        path=base/'Set.json'
        if path.is_symlink() or path.stat().st_size>256*1024:raise ValueError('Invalid sample kit manifest.')
        value=json.loads(path.read_text())
        if value.get('format')!='Machinista-sample-set' or value.get('version')!=1 or not isinstance(value.get('banks'),list) or not 1<=len(value['banks'])<=MAX_BANKS:raise ValueError('Invalid sample kit.')
        for bank in value['banks']:
            if not isinstance(bank,dict) or not re.fullmatch(r'bank-[0-9]{3}',bank.get('id','')):raise ValueError('Invalid bank.')
        if len({b['id'] for b in value['banks']})!=len(value['banks']):raise ValueError('Duplicate bank ID.')
        return value

    def banks(self,identity):
        base=self.sets.bundle(identity)
        if (base/'Set.json').exists():
            meta=self.metadata(base)
            return meta,[(bank,base/bank['id']) for bank in meta['banks']]
        data=self.sets.document(base)
        return dict(name=data.get('name',identity),notes=[],banks=[dict(id='legacy',name='Bank A')]),[(dict(id='legacy',name='Bank A'),base)]

    def revision(self,identity):
        base=self.sets.bundle(identity);meta,rows=self.banks(identity);digest=hashlib.sha256()
        digest.update(json.dumps(meta,sort_keys=True).encode())
        for _,path in rows:digest.update((path/'Preset.json').read_bytes())
        return digest.hexdigest()

    def item(self,identity):
        base=self.sets.bundle(identity)
        meta,rows=self.banks(identity);revision=self.revision(identity);banks=[]
        for info,bank_path in rows:
            if bank_path.is_symlink():raise ValueError('Invalid bank directory.')
            data=self.sets.document(bank_path);pads=[]
            for index,pad in enumerate(data['project']['groups'][0]['pads']):
                ref=pad.get('sample') or next((z.get('sample') for z in pad.get('zones',[]) if z.get('sample')),None)
                if not ref and not pad.get('plugins'):pads.append(None);continue
                absolute=Path(ref) if ref else None
                if absolute is not None and not absolute.is_absolute():absolute=bank_path/absolute
                asset=dict(set=identity,path=str(absolute.relative_to(base))) if absolute else None
                pads.append(dict(name=pad.get('name') or (absolute.stem if absolute else 'Instrument'),asset=asset,
                                 layers=len(pad.get('zones',[])) or (1 if ref else 0),
                                 origin=dict(set=identity,bank=info['id'],pad=index,revision=revision)))
            banks.append(dict(name=info['name'],pads=pads,origin=dict(set=identity,bank=info['id'],revision=revision)))
        storage,_=self.sets.split(identity)
        preview=base/KIT_PREVIEW
        artwork={kind:dict(set=identity,path=leaf) for kind,leaf in KIT_ARTWORK.items()
                 if (base/leaf).is_file() and not (base/leaf).is_symlink()}
        return dict(artwork=artwork,preview=dict(set=identity,path=KIT_PREVIEW) if preview.is_file() and not preview.is_symlink() else None,
                    id=identity,name=title(meta['name']),revision=revision,banks=banks,notes=meta.get('notes',[]),
                    storage=storage,expansion=base.parent.name if base.parent!=self.sets.root(storage) else '')

    def listing(self,identity):
        item=self.item(identity)
        return dict(id=identity,name=item['name'],banks=len(item['banks']),pads=sum(p is not None for b in item['banks'] for p in b['pads']),notes=item['notes'],expansion=item['expansion'],preview=item['preview'])

    def stage(self,identity):
        storage,name=self.sets.split(identity)
        if not re.fullmatch(r'[a-f0-9]{32}',name):raise ValueError('Invalid upload session.')
        staging=self.sets.root(storage)/'.uploads'
        path=staging/name
        if staging.is_symlink() or path.is_symlink() or not path.is_dir():raise ValueError('Upload session expired. Select the files again.')
        return path

    def start(self,value=None):
        storage=(value or {}).get('storage','sd')
        staging=self.sets.root(storage,write=True)/'.uploads'
        if staging.is_symlink():raise ValueError('Invalid kit staging folder.')
        staging.mkdir(exist_ok=True)
        # Only remove abandoned temporary transfers, never saved banks.
        for path in staging.iterdir():
            if path.is_dir() and not path.is_symlink() and time.time()-path.stat().st_mtime>24*3600:shutil.rmtree(path)
        name=uuid.uuid4().hex;(staging/name).mkdir()
        return dict(id=self.sets.key(storage,name))

    def discard_stage(self, value):
        if not self.library.upload_lock.acquire(False):
            raise BlockingIOError('Another transfer is in progress.')
        try:
            shutil.rmtree(self.stage(value.get('upload')))
            return dict(ok=True)
        finally:
            self.library.upload_lock.release()

    def upload_file(self,identity,name,stream,length):
        components=parts(name)
        if any(p.startswith('.') or p=='__MACOSX' for p in components):raise ValueError('Hidden files are not imported.')
        suffix=Path(name).suffix.lower()
        if suffix not in AUDIO|METADATA:raise ValueError('Use an installed expansion folder or audio files, not an installer.')
        if not 0<length<=MAX_PACKAGE:raise ValueError('Maximum 1 GiB per transfer.')
        if not self.library.upload_lock.acquire(False):raise BlockingIOError('Another transfer is in progress.')
        try:
            base=self.stage(identity);files=[p for p in base.rglob('*') if p.is_file()]
            if len(files)>=MAX_FILES or sum(p.stat().st_size for p in files)+length>MAX_PACKAGE:raise ValueError('Folder exceeds 1 GiB or 8,192 files.')
            if shutil.disk_usage(base).free<length+RESERVE:raise ValueError('Not enough free storage.')
            target=base.joinpath(*components)
            if any(str(p.relative_to(base)).casefold()==str(target.relative_to(base)).casefold() for p in files):raise ValueError('Duplicate upload path.')
            target.parent.mkdir(parents=True,exist_ok=True)
            try:
                with target.open('xb') as out:
                    remaining=length
                    while remaining:
                        block=stream.read(min(65536,remaining))
                        if not block:raise ValueError('Incomplete sample upload.')
                        out.write(block);remaining-=len(block)
                os.utime(base,None)
            except BaseException:target.unlink(missing_ok=True);raise
            return dict(ok=True,asset=dict(upload=identity,path='/'.join(components)),name=target.name)
        finally:self.library.upload_lock.release()

    def inspect_maschine_kit(self, name, stream, length, *, local=False):
        from app.maschine_kit import MAX_KIT_BYTES, read_kit
        from app.web_server import filename

        filename(name)
        if Path(name).suffix.lower() != '.mxgrp' or not 0 < length <= MAX_KIT_BYTES:
            raise ValueError('Choose a Maschine Group (.mxgrp) up to 8 MiB.')
        data = stream.read(length)
        if len(data) != length:
            raise ValueError('Incomplete Maschine Group upload.')
        pads, notes = read_kit(data)
        if local:
            return dict(name=title(Path(name).stem), pads=pads, notes=notes)
        references = {pad['path'] for pad in pads}
        matches = {ref: [] for ref in references}
        candidates = []
        for identity, source in self.library.sources().items():
            for index, (directory, children, _) in enumerate(os.walk(source.path)):
                if index >= 8192 or len(candidates) >= 256:
                    break
                relative = Path(directory).relative_to(source.path)
                children[:] = sorted(child for child in children if not child.startswith('.'))
                if len(relative.parts) >= 6:
                    children.clear()
                if relative.name.casefold() == 'samples' or not relative.parts:
                    candidates.append((identity, source, relative))
                    if relative.parts:
                        children.clear()
        for identity, source, relative in candidates:
            for ref in references:
                is_sample_root = relative.parts or source.path.name.casefold() == 'samples'
                target = relative / (ref.split('/', 1)[1] if is_sample_root else ref)
                parent = '/'.join(target.parent.parts)
                try:
                    with self.library.directory(source, parent) as fd:
                        mode = os.stat(target.name, dir_fd=fd, follow_symlinks=False).st_mode
                except OSError:
                    continue
                if stat.S_ISREG(mode):
                    asset = dict(source=identity, path=parent, name=target.name)
                    if asset not in matches[ref]:
                        matches[ref].append(asset)
        for pad in pads:
            options = matches[pad['path']]
            if len(options) == 1:
                pad['asset'] = options[0]
        return dict(name=title(Path(name).stem), pads=pads, notes=notes)

    @contextmanager
    def asset(self,ref):
        if not isinstance(ref,dict):raise ValueError('Invalid pad sample.')
        if 'set' in ref:
            base=self.sets.bundle(ref['set']);relative=parts(ref.get('path',''));path=base.joinpath(*relative)
        elif 'upload' in ref:
            base=self.stage(ref['upload']);relative=parts(ref.get('path',''));path=base.joinpath(*relative)
        elif 'source' in ref:
            from app.web_server import filename
            source=self.library.source(ref['source']);name=filename(ref.get('name',''))
            if Path(name).suffix.lower() not in AUDIO|{'.png'}:raise ValueError('Unsupported kit asset.')
            with self.library.directory(source,ref.get('path','')) as parent:fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=parent)
            with os.fdopen(fd,'rb') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):raise ValueError('Not a sample file.')
                yield stream
            return
        else:
            with self.library.sounds.asset(ref) as stream:yield stream
            return
        if path.suffix.lower() not in AUDIO|{'.png'}:raise ValueError('Unsupported kit asset.')
        with self.library.projects.opened(path,[base]) as stream:yield stream

    def original(self,origin):
        if not isinstance(origin,dict):raise ValueError('Invalid bank reference.')
        identity=origin.get('set')
        if origin.get('revision')!=self.revision(identity):raise ValueError('Sample kit changed. Reload before saving.')
        _,rows=self.banks(identity)
        base=next((base for info,base in rows if info['id']==origin.get('bank')),None)
        if base is None:raise ValueError('Bank unavailable.')
        data=self.sets.document(base)
        from app.assets import resolve_assets
        return resolve_assets(copy.deepcopy(data['project']),base)

    def save(self,value):
        if not isinstance(value,dict):raise ValueError('Invalid sample kit.')
        rows=value.get('banks');name=title(value.get('name',''))
        if not str(value.get('name','')).strip():raise ValueError('Enter a sample kit name.')
        if not isinstance(rows,list) or not 1<=len(rows)<=MAX_BANKS:raise ValueError('Use 1–128 banks.')
        if not self.library.upload_lock.acquire(False):raise BlockingIOError('Another transfer is in progress.')
        try:
            identity=value.get('id');old=self.sets.bundle(identity) if identity else None
            storage=self.sets.split(identity)[0] if identity else value.get('storage','sd')
            root=self.sets.root(storage,write=True)
            if old is not None and value.get('revision')!=self.revision(identity):raise ValueError('Sample kit changed. Reload before saving.')
            if shutil.disk_usage(root).free<RESERVE:raise ValueError('Not enough free storage.')
            with tempfile.TemporaryDirectory(prefix='.edit-',dir=root) as tmp:
                base=Path(tmp)/'set';base.mkdir();banks=[];size=0
                from app.model import new_project,validate_project
                from app.assets import collect_project
                for index,row in enumerate(rows):
                    if not isinstance(row,dict) or not isinstance(row.get('pads'),list) or len(row['pads'])!=16:raise ValueError('Each bank must contain 16 pads.')
                    project=self.original(row['origin']) if row.get('origin') else validate_project(new_project())
                    blank=validate_project(new_project());group=project['groups'][0]
                    for slot,pad in enumerate(row['pads']):
                        if pad is None:group['pads'][slot]=copy.deepcopy(blank['groups'][0]['pads'][slot]);continue
                        if not isinstance(pad,dict):raise ValueError('Invalid pad.')
                        if pad.get('origin'):
                            origin=pad['origin'];position=origin.get('pad')
                            if type(position) is not int or not 0<=position<16:raise ValueError('Invalid source pad.')
                            track=self.original(origin)['groups'][0]['pads'][position]
                        else:
                            track=copy.deepcopy(blank['groups'][0]['pads'][slot]);ref=pad.get('asset')
                            extension=Path(ref.get('name') or ref.get('path','')).suffix.lower() if isinstance(ref,dict) else ''
                            if extension not in AUDIO:raise ValueError('Choose an audio sample for this pad.')
                            # Work on private copies; source libraries are never rewritten.
                            source=Path(tmp)/('source-'+uuid.uuid4().hex+extension);dest=Path(tmp)/('pcm-'+uuid.uuid4().hex+'.wav')
                            with self.asset(ref) as stream,source.open('wb') as out:shutil.copyfileobj(stream,out,65536)
                            info=convert(source,dest);size+=dest.stat().st_size
                            if size>MAX_PACKAGE:raise ValueError('Sample kit exceeds 1 GiB decoded audio.')
                            track.update(sample=str(dest),start=0,end=info['frames'],zones=[])
                        track['name']=title(pad.get('name','Sample'))[:32];group['pads'][slot]=track
                    # Sample kits never overwrite pattern/event content in a Group.
                    from app.presets import PATTERN_KEYS
                    for key in PATTERN_KEYS:
                        if key in blank['groups'][0]:group[key]=copy.deepcopy(blank['groups'][0][key])
                        else:group.pop(key,None)
                    group['name']=re.sub(r'[^A-Za-z0-9 _-]','',title(row.get('name','Bank')))[:32] or 'Bank'
                    bank_id=f'bank-{index+1:03}';bank=base/bank_id
                    validate_project(project);collect_project(project,bank)
                    doc=json.loads((bank/'Project.json').read_text());(bank/'Project.json').unlink()
                    (bank/'Preset.json').write_text(json.dumps(dict(format='Machinista-preset',version=1,kind='GROUP',name=group['name'],project=doc)))
                    banks.append(dict(id=bank_id,name=title(row.get('name','Bank '+str(index+1)))))
                    if sum(p.stat().st_size for p in base.rglob('*') if p.is_file())>MAX_PACKAGE:raise ValueError('Sample kit exceeds 1 GiB.')
                notes=value.get('notes',[])
                notes=[title(n) for n in notes[:64]] if isinstance(notes,list) else []
                preview=value.get('preview')
                if preview:
                    source=Path(tmp)/'preview.ogg'
                    extension=Path(preview.get('name') or preview.get('path','')).suffix.lower() if isinstance(preview,dict) else ''
                    if extension not in ('.ogg','.wav'):raise ValueError('Invalid kit preview.')
                    source=source.with_suffix(extension)
                    dest=base/KIT_PREVIEW
                    try:
                        with self.asset(preview) as stream:
                            if os.fstat(stream.fileno()).st_size>8*1024**2:raise ValueError('Kit preview exceeds 8 MiB.')
                            with source.open('wb') as out:shutil.copyfileobj(stream,out,65536)
                        info=convert(source,dest)
                        if info['frames']>60*info['rate']:raise ValueError('Kit preview exceeds 60 seconds.')
                    except (OSError,ValueError,subprocess.SubprocessError,wave.Error):
                        dest.unlink(missing_ok=True)
                        notes.append('The kit preview could not be imported.')
                artwork=value.get('artwork',{})
                if isinstance(artwork,dict):
                    for kind,leaf in KIT_ARTWORK.items():
                        if not artwork.get(kind):continue
                        try:
                            with self.asset(artwork[kind]) as stream:
                                if os.fstat(stream.fileno()).st_size>MAX_IMAGE_BYTES:raise ValueError('Kit image exceeds 2 MiB.')
                                image=decode_png(stream)
                            image.thumbnail((640,640))
                            image.save(base/leaf)
                        except (OSError,ValueError):
                            (base/leaf).unlink(missing_ok=True)
                            notes.append('The kit '+kind+' could not be imported.')
                (base/'Set.json').write_text(json.dumps(dict(format='Machinista-sample-set',version=1,name=name,banks=banks,notes=notes),ensure_ascii=False))
                # A loaded/saved project may still reference an older sample by
                # its collected filename. Preserve those files at the same path.
                if old is not None:
                    for previous in old.rglob('*'):
                        if previous.is_symlink():raise ValueError('Set contains a symbolic link.')
                        if previous.is_file() and (previous.suffix.lower() in {'.wav','.ttl'} or previous.name in KIT_ARTWORK.values()):
                            destination=base/previous.relative_to(old)
                            if not destination.exists():
                                destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(previous,destination)
                if sum(p.stat().st_size for p in base.rglob('*') if p.is_file())>MAX_PACKAGE:raise ValueError('Sample kit including preserved assets exceeds 1 GiB. Use Save copy.')
                name_on_disk=old.name if old is not None else 'set-'+uuid.uuid4().hex
                identity=self.sets.key(storage,name_on_disk)
                expansion=value.get('expansion')
                if expansion is not None and not isinstance(expansion,str):raise ValueError('Invalid expansion name.')
                parent=old.parent if old is not None else self.sets.expansion(expansion,root) if expansion else root
                if old is None and (parent/name_on_disk).exists():raise FileExistsError('Sample kit already exists.')
                backup=root/('.replaced-'+uuid.uuid4().hex)
                if old is not None:old.rename(backup)
                try:base.rename(parent/name_on_disk)
                except BaseException:
                    if backup.exists():backup.rename(old)
                    raise
                if backup.exists():
                    shutil.rmtree(backup)
            return dict(ok=True,id=identity,name=name)
        finally:self.library.upload_lock.release()

    def manage_folder(self, value, *, delete=False):
        name=value.get('name')
        if (not isinstance(name,str) or not name.strip() or name != title(name)
                or name.startswith('.')):
            raise ValueError('Enter a folder name of 1–80 characters without slashes.')
        if not delete and re.fullmatch(r'set-[a-f0-9]{32}',name,re.I):
            raise ValueError('This folder name is reserved for sample kit IDs.')
        if delete and value.get('confirmed') is not True:
            raise ValueError('Confirm deletion first.')
        if not self.library.upload_lock.acquire(False):
            raise BlockingIOError('Another transfer is in progress.')
        try:
            root=self.sets.root(value.get('storage','sd'),write=True)
            existing=next((p for p in self.sets.expansions(root) if p.name.casefold()==name.casefold()),None)
            if delete:
                if existing is None:raise ValueError('Sample kit folder unavailable.')
                shutil.rmtree(existing)
                return dict(ok=True,message='Folder and its kits deleted permanently.')
            if existing is not None:raise FileExistsError('A folder with this name already exists.')
            folder=self.sets.expansion(name,root)
            return dict(ok=True,name=folder.name)
        finally:self.library.upload_lock.release()

    def delete(self,value):
        if not isinstance(value,dict) or value.get('confirmed') is not True:raise ValueError('Confirm deletion first.')
        if not self.library.upload_lock.acquire(False):raise BlockingIOError('Another transfer is in progress.')
        try:
            identity=value.get('id');base=self.sets.bundle(identity)
            if value.get('revision')!=self.revision(identity):raise ValueError('Sample kit changed. Reload before deleting.')
            self.sets.root(self.sets.split(identity)[0],write=True)
            shutil.rmtree(base)
            return dict(ok=True,message='Sample kit deleted permanently.')
        finally:self.library.upload_lock.release()

    @one_import
    def import_folder(self,value):
        base=self.stage(value.get('upload'));name=title(value.get('name','Sample Kit'))
        storage=value.get('storage','sd');root=self.sets.root(storage,write=True)
        # Native saved sets round-trip without losing their portable pad state.
        manifests=list(base.rglob('Set.json'))
        presets=list(base.rglob('Preset.json'))
        if manifests or presets:
            return self.import_native(base,manifests,presets,storage)
        draft=plan(base,name)
        with tempfile.TemporaryDirectory(prefix='.decode-',dir=root) as tmp:
            cache={};used=0
            for bank in draft['banks']:
                for pad in bank['pads']:
                    if not pad:continue
                    for layer in pad['layers']:
                        p=layer['path']
                        if p not in cache:
                            dest=Path(tmp)/(uuid.uuid4().hex+'.wav');info=convert(p,dest);used+=dest.stat().st_size
                            if used>MAX_PACKAGE:raise ValueError('Decoded expansion exceeds 1 GiB.')
                            cache[p]=(dest,info)
            # Build bank presets with velocity zones, then use the same atomic publisher.
            from app.model import new_project,validate_project
            from app.assets import collect_project
            prepared=Path(tmp)/'native';prepared.mkdir();meta=[]
            for index,bank in enumerate(draft['banks']):
                project=validate_project(new_project())
                for slot,pad in enumerate(bank['pads']):
                    if not pad:continue
                    dest,info=cache[pad['layers'][0]['path']];track=project['groups'][0]['pads'][slot]
                    track.update(name=title(pad['name'])[:32],sample=str(dest),start=0,end=info['frames'],zones=[])
                    if len(pad['layers'])>1:
                        from app.sampler import default_zone
                        for layer in pad['layers']:
                            wav,stats=cache[layer['path']];zone=default_zone(track);zone.update(sample=str(wav),start=0,end=stats['frames'],loop_end=stats['frames'],vel_lo=layer['vel_lo'],vel_hi=layer['vel_hi']);track['zones'].append(zone)
                bank_id=f'bank-{index+1:03}';directory=prepared/bank_id;collect_project(project,directory)
                doc=json.loads((directory/'Project.json').read_text());(directory/'Project.json').unlink()
                (directory/'Preset.json').write_text(json.dumps(dict(format='Machinista-preset',version=1,kind='GROUP',name=bank['name'],project=doc)))
                meta.append(dict(id=bank_id,name=bank['name']))
            (prepared/'Set.json').write_text(json.dumps(dict(format='Machinista-sample-set',version=1,name=draft['name'],banks=meta,notes=draft['notes'])))
            result=self.import_native(prepared,[prepared/'Set.json'],[],storage)
        shutil.rmtree(base)
        return result

    def import_native(self,base,manifests,presets,storage):
        if not self.library.upload_lock.acquire(False):raise BlockingIOError('Another transfer is in progress.')
        try:
            if manifests:
                if len(manifests)!=1:raise ValueError('Import one saved sample kit per archive.')
                source=manifests[0].parent;meta=self.metadata(source)
                for bank in meta['banks']:
                    if (source/bank['id']).is_symlink():raise ValueError('Invalid bank directory.')
                    self.sets.document(source/bank['id'])
                name=meta['name']
            else:
                if len(presets)!=1:raise ValueError('Import one saved Group per archive.')
                source=presets[0].parent;doc=self.sets.document(source);name=doc.get('name',source.name)
            # Validate every member even when the manifest doesn't refer to it.
            size=0
            for p in source.rglob('*'):
                if p.is_symlink():raise ValueError('Symbolic links are not supported.')
                if p.is_file():
                    if p.name in KIT_ARTWORK.values() and p.parent==source:
                        with p.open('rb') as stream:
                            if p.stat().st_size>MAX_IMAGE_BYTES:raise ValueError('Kit image exceeds 2 MiB.')
                            decode_png(stream)
                    elif p.suffix.lower() not in {'.wav','.json','.ttl'}:raise ValueError('Saved sample kits contain only WAV/JSON/TTL assets.')
                    size+=p.stat().st_size
                    if p.suffix.lower()=='.wav':
                        from app.wav_validation import validate_pcm
                        with p.open('r+b') as stream:validate_pcm(stream,{})
            if size>MAX_PACKAGE:raise ValueError('Sample kit exceeds 1 GiB.')
            root=self.sets.root(storage,write=True)
            if shutil.disk_usage(root).free<size+RESERVE:raise ValueError('Not enough free storage.')
            identity='set-'+uuid.uuid4().hex
            with tempfile.TemporaryDirectory(prefix='.publish-',dir=root) as tmp:
                target=Path(tmp)/'set';shutil.copytree(source,target);target.rename(root/identity)
            identity=self.sets.key(storage,identity)
            return dict(ok=True,id=identity,name=title(name),sets=[identity],notes=meta.get('notes',[]) if manifests else [])
        finally:self.library.upload_lock.release()

    def attach_expansion_previews(self,base,name,storage):
        root=self.sets.root(storage,write=True)
        previews={}
        for path in base.rglob('*'):
            if path.is_file() and path.name.lower().endswith('.mxgrp.ogg'):
                label=path.name[:-10].casefold()
                if label in previews:raise ValueError('Duplicate kit preview: '+path.name)
                previews[label]=path
        folder=next((p for p in self.sets.expansions(root) if p.name.casefold()==name.casefold()),None)
        if folder is None:raise ValueError('Name the preview ZIP after an installed expansion.')
        if not self.library.upload_lock.acquire(False):raise BlockingIOError('Another transfer is in progress.')
        try:
            updated=0;available=0;failures=[]
            for kit in folder.iterdir():
                if kit.is_symlink() or not kit.is_dir() or not kit.name.startswith('set-'):continue
                try:name_in_set=self.metadata(kit)['name']
                except (OSError,ValueError,KeyError):continue
                preview=previews.get(name_in_set.casefold())
                if not preview:continue
                target=kit/KIT_PREVIEW
                if target.is_file() and not target.is_symlink():
                    available+=1;continue
                try:
                    if preview.stat().st_size>8*1024**2:raise ValueError('Preview exceeds 8 MiB.')
                    with tempfile.TemporaryDirectory(prefix='.preview-',dir=root) as temp:
                        wav=Path(temp)/'preview.wav'
                        info=convert(preview,wav)
                        if info['frames']>60*info['rate']:raise ValueError('Preview exceeds 60 seconds.')
                        wav.replace(target)
                    updated+=1;available+=1
                except (OSError,ValueError,subprocess.SubprocessError,wave.Error) as error:
                    failures.append(name_in_set+' · '+str(error))
            return dict(ok=True,name=folder.name,previews=available,updated=updated,failures=failures)
        finally:self.library.upload_lock.release()

    def import_maschine_archive(self,base,upload,kits,storage,name):
        from app.maschine_kit import MAX_KIT_BYTES,read_kit
        files={p.relative_to(base).as_posix().casefold():p for p in base.rglob('*') if p.is_file()}
        saved=[];failures=[];preview_count=0
        for kit in kits:
            try:
                if kit.stat().st_size>MAX_KIT_BYTES:raise ValueError('Maschine Group exceeds 8 MiB.')
                pads,notes=read_kit(kit.read_bytes())
                directories=[kit.parent,*kit.parents]
                groups=next((p for p in directories if p.name.casefold()=='groups'),None)
                expansion=groups.parent if groups else kit.parent
                prefix=expansion.relative_to(base).as_posix().casefold()
                prefix='' if prefix=='.' else prefix+'/'
                def asset(path):
                    return dict(upload=upload,path=path.relative_to(base).as_posix())
                for pad in pads:
                    sample=files.get(prefix+pad['path'].casefold())
                    if sample is None:raise ValueError('Missing sample: '+pad['path'])
                    pad['asset']=asset(sample)
                preview=files.get((kit.parent/'.previews'/(kit.name+'.ogg')).relative_to(base).as_posix().casefold())
                resources=sorted((path for key,path in files.items() if key.startswith(prefix+'paresources/image/')),key=str)
                artwork={}
                for kind,names in {'artwork':('mst_artwork.png','vb_artwork.png'),
                                   'logo':('oso_logo.png','vb_logo.png','mst_logo.png')}.items():
                    match=next((path for name in names for path in resources if path.name.casefold()==name),None)
                    if match:artwork[kind]=asset(match)
                label=title(kit.stem)
                result=self.save(dict(name=label,storage=storage,expansion=expansion.name if expansion!=base else name,
                                      notes=notes,preview=asset(preview) if preview else None,artwork=artwork,
                                      banks=[dict(name=label,pads=pads+[None]*(16-len(pads)))]))
                saved.append(result)
                preview_count+=(self.sets.bundle(result['id'])/KIT_PREVIEW).is_file()
            except (OSError,ValueError) as error:
                failures.append(kit.name+' · '+str(error))
        return dict(ok=True,id=saved[0]['id'] if saved else None,kits=len(saved),total=len(kits),
                    previews=preview_count,failures=failures)

    @one_import
    def import_archive(self,name,stream,length,storage='sd'):
        if Path(name).suffix.lower() not in ('.zip','.xpn') or not 0<length<=MAX_PACKAGE:raise ValueError('Upload a ZIP or MPC XPN up to 1 GiB. For Maschine, use its installed audio folder.')
        identity=self.start(dict(storage=storage))['id'];base=self.stage(identity)
        try:
            with tempfile.TemporaryFile(dir=base.parent) as archive:
                remaining=length
                while remaining:
                    block=stream.read(min(65536,remaining))
                    if not block:raise ValueError('Incomplete expansion upload.')
                    archive.write(block);remaining-=len(block)
                archive.seek(0);seen=set();total=0
                with zipfile.ZipFile(archive) as z:
                    if len(z.infolist())>MAX_FILES:raise ValueError('Archive exceeds 8,192 entries.')
                    for info in z.infolist():
                        components=parts(info.filename);mode=info.external_attr>>16
                        if info.flag_bits&1 or stat.S_ISLNK(mode) or mode and stat.S_IFMT(mode) not in (0,stat.S_IFREG,stat.S_IFDIR):raise ValueError('Encrypted archives and special files are not supported.')
                        if any((p.startswith('.') and p not in (KIT_PREVIEW,*KIT_ARTWORK.values(),'.previews')) or p=='__MACOSX' for p in components):continue
                        key='/'.join(components).casefold()
                        if key in seen:raise ValueError('Duplicate archive path.')
                        seen.add(key);total+=info.file_size
                        if total>MAX_PACKAGE:raise ValueError('Expanded archive exceeds 1 GiB.')
                        if info.is_dir():continue
                        if Path(info.filename).suffix.lower() not in AUDIO|METADATA:continue
                        if shutil.disk_usage(base).free<info.file_size+RESERVE:raise ValueError('Not enough free storage.')
                        target=base.joinpath(*components);target.parent.mkdir(parents=True,exist_ok=True)
                        with z.open(info) as inp,target.open('xb') as out:shutil.copyfileobj(inp,out,65536)
            kits=[]
            for candidate in base.rglob('*'):
                if candidate.is_file() and candidate.suffix.lower()=='.mxgrp':
                    with candidate.open('rb') as stream:
                        if stream.read(16)[12:16]==b'hsin':kits.append(candidate)
            if kits:
                return self.import_maschine_archive(base,identity,sorted(kits),storage,Path(name).stem)
            if any(p.name.lower().endswith('.mxgrp.ogg') for p in base.rglob('*')):
                return self.attach_expansion_previews(base,Path(name).stem,storage)
            return self.import_folder(dict(upload=identity,name=Path(name).stem,storage=storage))
        except zipfile.BadZipFile as error:raise ValueError('Invalid or damaged ZIP/XPN.') from error
        finally:
            if base.exists():shutil.rmtree(base)
