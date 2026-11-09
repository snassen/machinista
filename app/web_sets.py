"""Portable Group sample kit transfer. No live-engine access; sample-only expansion conversion."""
from contextlib import contextmanager
from pathlib import Path
import copy,json,re,shutil,stat,tempfile,uuid,wave,zipfile
from app.web_projects import parts,MAX_PACKAGE,RESERVE,read_project,plugins
from app.assets import resolve_assets,sample_references

class SampleSets:
 def __init__(self,library):
  self.library=library;self.folder=library.root/'presets/Groups';self.folder.mkdir(parents=True,exist_ok=True)
  from app.sample_set_editor import SetEditor
  self.editor=SetEditor(self)
 def root(self,storage='sd',*,write=False):
  if storage=='sd':return self.folder
  if not isinstance(storage,str) or not storage.startswith('usb-'):raise ValueError('Invalid kit storage.')
  from app.browser import usb_kit_path
  source=self.library.source(storage)
  root=usb_kit_path(source)
  if root.is_symlink():raise ValueError('Invalid USB sample kit folder.')
  if write:
   if source.read_only:raise PermissionError('USB storage is read-only.')
   root.mkdir(exist_ok=True)
  return root
 def key(self,storage,name):
  return name if storage=='sd' else storage+':'+name
 def split(self,identity):
  if not isinstance(identity,str):raise ValueError('Invalid sample kit ID.')
  storage,separator,name=identity.partition(':')
  return (storage,name) if separator else ('sd',storage)
 def expansions(self,root=None):
  root=root or self.folder
  if not root.is_dir():return iter(())
  return (p for p in root.iterdir() if not p.name.startswith('.') and not p.is_symlink()
          and p.is_dir() and (p/'.expansion').is_file() and not (p/'.expansion').is_symlink())
 def expansion(self,name,root=None):
  from app.sample_set_import import title
  root=root or self.folder
  name=title(name,'Expansion').lstrip('.') or 'Expansion'
  for p in self.expansions(root):
   if p.name.casefold()==name.casefold():return p
  target=root/name
  if target.exists() or target.is_symlink():
   raise ValueError('An existing sample kit already uses this expansion name.')
  target.mkdir()
  (target/'.expansion').touch()
  return target
 def bundle(self,identity):
  storage,name=self.split(identity)
  if not re.fullmatch(r'(?:[A-Za-z0-9 _-]{1,32}|set-[a-f0-9]{32})',name):raise ValueError('Invalid sample kit name.')
  root=self.root(storage)
  p=root/name
  if not p.exists() and name.startswith('set-'):
   p=next((folder/name for folder in self.expansions(root) if (folder/name).is_dir()),p)
  if p.is_symlink() or not p.is_dir() or (p/'.expansion').exists():raise ValueError('Sample kit unavailable.')
  return p
 def document(self,base):
  p=base/'Preset.json'
  if p.is_symlink() or p.stat().st_size>8*1024**2:raise ValueError('Invalid set manifest.')
  data=json.loads(p.read_text())
  if data.get('format') not in ('Machinista-preset','Machinist-preset','maschineOS-preset') or data.get('kind')!='GROUP' or data.get('version')!=1:raise ValueError('Upload a Machinista Group preset.')
  project=read_project(json.dumps(data['project']).encode());resolved=resolve_assets(copy.deepcopy(project),base)
  refs=[obj[key] for obj,key in sample_references(resolved)]+[p['state'] for p in plugins(resolved) if p.get('state')]
  for ref in refs:
   p=Path(ref)
   if not p.resolve().is_relative_to(base.resolve()) or not p.is_file() or any(q.is_symlink() for q in (p,*p.parents) if q.is_relative_to(base)):raise ValueError('Set contains an external or missing asset.')
  return data
 def listing(self,storage='sd'):
  root=self.root(storage)
  if not root.is_dir():return []
  rows=[]
  folders=list(self.expansions(root))
  paths=[p for p in root.iterdir() if p not in folders]
  for folder in folders:paths.extend(folder.iterdir())
  for p in sorted(paths,key=lambda p:p.name.casefold()):
   if p.name.startswith('.') or not p.is_dir():continue
   try:
    rows.append(self.editor.listing(self.key(storage,p.name)))
   except (ValueError,OSError,KeyError,TypeError):continue
  return rows
 @contextmanager
 def download(self,name):
  if not self.library.upload_lock.acquire(False):raise BlockingIOError('Another transfer is in progress.')
  try:
   base=self.bundle(name)
   _,banks=self.editor.banks(name)
   for _,bank in banks:self.document(bank)
   with tempfile.TemporaryFile(dir=self.folder) as stream:
    total=0
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
     for p in base.rglob('*'):
      if p.is_symlink():raise ValueError('Set contains a symbolic link.')
      if not p.is_file():continue
      with self.library.projects.opened(p,[base]) as f:
       import os
       total+=os.fstat(f.fileno()).st_size
       if total>MAX_PACKAGE:raise ValueError('Set exceeds 1 GiB.')
       with z.open(str(p.relative_to(base)),'w') as target:shutil.copyfileobj(f,target,65536)
    stream.seek(0);yield stream,'application/zip',re.sub(r'[^A-Za-z0-9 _-]','',self.editor.item(name)['name'])+'.zip'
  finally:self.library.upload_lock.release()
 def upload(self,name,stream,length):
  if Path(name).suffix.lower()!='.zip' or not 0<length<=MAX_PACKAGE:raise ValueError('Upload a ZIP up to 1 GiB.')
  if not self.library.upload_lock.acquire(False):raise BlockingIOError('Another transfer is in progress.')
  try:
   if shutil.disk_usage(self.folder).free<length*3+RESERVE:raise ValueError('Not enough free storage.')
   with tempfile.TemporaryDirectory(prefix='.set-',dir=self.folder) as tmp:
    tmp=Path(tmp);archive=tmp/'upload.zip';remaining=length
    with archive.open('wb') as out:
     while remaining:
      block=stream.read(min(65536,remaining))
      if not block:raise ValueError('Incomplete upload.')
      out.write(block);remaining-=len(block)
    files=tmp/'files';files.mkdir();total=0;seen=set()
    with zipfile.ZipFile(archive) as z:
     if len(z.infolist())>4096:raise ValueError('Too many archive entries.')
     for info in z.infolist():
      components=parts(info.filename);mode=info.external_attr>>16
      if stat.S_ISLNK(mode) or mode and stat.S_IFMT(mode) not in (0,stat.S_IFREG,stat.S_IFDIR):raise ValueError('Archive contains special files.')
      if info.flag_bits&1:raise ValueError('Encrypted archives are not supported.')
      if any(c.startswith('.') or c=='__MACOSX' for c in components):continue
      key='/'.join(components).casefold()
      if key in seen:raise ValueError('Duplicate archive path.')
      seen.add(key);total+=info.file_size
      if total>MAX_PACKAGE:raise ValueError('Expanded archive exceeds 1 GiB.')
      if info.is_dir():continue
      if Path(info.filename).suffix.lower() not in ('.wav','.json','.ttl'):raise ValueError('Use WAV files or a Machinista Group ZIP. Native Maschine/NCW content is not supported.')
      target=files.joinpath(*components);target.parent.mkdir(parents=True,exist_ok=True)
      with z.open(info) as source,target.open('xb') as dest:shutil.copyfileobj(source,dest,65536)
      if target.suffix.lower()=='.wav':
       from app.wav_validation import validate_pcm
       with target.open('r+b') as wav:validate_pcm(wav,{})
    manifests=list(files.rglob('Preset.json'));prepared=[]
    title=re.sub(r'[^A-Za-z0-9 _-]','',Path(name).stem).strip()[:24] or 'Sample Kit'
    if manifests:
     if len(manifests)!=1:raise ValueError('Import one saved Group per ZIP.')
     base=manifests[0].parent;data=self.document(base);prepared=[(base,re.sub(r'[^A-Za-z0-9 _-]','',str(data.get('name',title))).strip()[:32] or title)]
    else:
     wavs=sorted(files.rglob('*'),key=lambda p:str(p.relative_to(files)).casefold());wavs=[p for p in wavs if p.suffix.lower()=='.wav']
     if not wavs:raise ValueError('No WAV samples found.')
     if len(wavs)>256:raise ValueError('Import at most 256 samples per ZIP.')
     from app.model import new_project,validate_project
     from app.assets import collect_project
     for offset in range(0,len(wavs),16):
      label=title+(f' {offset//16+1:03}' if len(wavs)>16 else '');base=tmp/uuid.uuid4().hex;project=validate_project(new_project());project['groups'][0]['name']=label
      for pad,p in zip(project['groups'][0]['pads'],wavs[offset:offset+16]):
       with wave.open(str(p),'rb') as wav:frames=wav.getnframes()
       pad.update(name=p.stem,sample=str(p),start=0,end=frames,zones=[])
      collect_project(project,base);project=json.loads((base/'Project.json').read_text());(base/'Project.json').unlink();(base/'Preset.json').write_text(json.dumps(dict(format='Machinista-preset',version=1,kind='GROUP',name=label,project=project)));prepared.append((base,label))
    labels=[label for _,label in prepared];existing={p.name.casefold() for p in self.folder.iterdir()}
    if len(set(x.casefold() for x in labels))!=len(labels) or any(x.casefold() in existing for x in labels):raise ValueError('A sample kit with this name already exists. Rename the ZIP or kit first.')
    published=[]
    try:
     for base,label in prepared:base.rename(self.folder/label);published.append(label)
    except Exception:
     for label in published:shutil.rmtree(self.folder/label)
     raise
    return dict(ok=True,sets=published)
  except zipfile.BadZipFile as error:raise ValueError('Invalid or damaged sample kit ZIP.') from error
  finally:self.library.upload_lock.release()
