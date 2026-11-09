"""Filesystem browser with SD sample library and dynamically mounted USB roots."""
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path


@dataclass(frozen=True)
class Source:
    name: str
    path: Path
    identity: str = ''
    read_only: bool = False


USB_KIT_DIRECTORY = 'Machinista Sample Kits'


def usb_kit_path(source):
    return source.path / USB_KIT_DIRECTORY


class Browser:
    def __init__(self, samples, internal_sources=(), kit_root=None):
        self.samples = Path(samples)
        self.internal_sources = tuple(internal_sources)
        self.sources = [Source('SD CARD', self.samples)]
        self.kit_menu = Path(kit_root).parent / '.sample-kits' if kit_root is not None else None
        self.kit_sources = [Source('SD CARD',Path(kit_root))] if kit_root is not None else []
        self.directory = self.samples
        self.index = 0
        self.prehear = False
        self.started = False
        self.error = ''
        self._visible_rows = (None,{})

    def refresh(self, sources):
        self.sources = [Source('SD CARD', self.samples)]+[source for source in self.internal_sources if source.path.is_dir() or source.path == self.kit_menu]+list(sources)
        if self.kit_menu is not None:
            self.kit_sources[1:] = [Source(s.name,usb_kit_path(s)) for s in sources if s.name.startswith('USB ') and not usb_kit_path(s).is_symlink()]
        if self.directory is not None and self.directory != self.kit_menu:
            root = self.current_root()
            if root is None or (not self.directory.is_dir() and not self.kit_source(self.directory)):
                self.directory = None
                self.index = 0
                self.error = 'MEDIA REMOVED'

    def current_root(self):
        if self.directory is None:
            return None
        resolved = self.directory.resolve()
        roots=[source.path.resolve() for source in self.sources+self.kit_sources if resolved.is_relative_to(source.path.resolve())]
        return max(roots,key=lambda p:len(p.parts)) if roots else None

    def kit_source(self,path):
        return next((s for s in self.kit_sources if Path(path).is_relative_to(s.path)),None)

    def entries(self):
        if self.kit_menu is not None and self.directory == self.kit_menu:
            return [source.path for source in self.kit_sources]
        if self.directory is None:
            return [source.path for source in self.sources if source.name not in ('PROJECT ASSETS','PRESET ASSETS')]
        root = self.current_root()
        if root is None:
            self.directory, self.index = None, 0
            return [source.path for source in self.sources if source.name not in ('PROJECT ASSETS','PRESET ASSETS')]
        try:
            rows=self.directory_rows(root)
            self._visible_rows=(self.directory,rows)
            self.error=''
            return list(rows)
        except FileNotFoundError:
            return []
        except OSError:
            self.error='FOLDER UNAVAILABLE'
            return []

    def directory_rows(self,root=None):
        root=root or self.current_root() or self.directory.resolve()
        return _directory_rows(self.directory,root,self.directory.stat().st_mtime_ns)

    def label(self, path):
        if self.directory is None:
            return next(source.name for source in self.sources if source.path == path)
        if self.directory == self.kit_menu:
            return next(source.name for source in self.kit_sources if source.path == path)
        directory,rows=self._visible_rows
        if self.directory==directory and path in rows:return rows[path]
        return self.file_label(path)

    @staticmethod
    def file_label(path):
        if path.name=='Preset.json':
            if (path.parent.parent/'Set.json').is_file():
                try:
                    import json
                    if (path.parent.parent/'Set.json').stat().st_size<=256*1024:
                        data=json.loads((path.parent.parent/'Set.json').read_text())
                        return next(str(b['name'])[:80] for b in data['banks'] if b['id']==path.parent.name)
                except (ValueError,OSError,KeyError,TypeError,StopIteration):pass
            return path.parent.name
        if path.is_dir() and (path/'Set.json').is_file() and not (path/'Set.json').is_symlink():
            try:
                import json
                if (path/'Set.json').stat().st_size<=256*1024:return str(json.loads((path/'Set.json').read_text()).get('name',path.name))[:80]
            except (ValueError,OSError,TypeError):pass
        if path.suffix.lower()=='.sound':return path.stem
        return path.name

    def title(self):
        if self.directory is None:
            return 'SD / USB'
        if self.directory == self.kit_menu:
            return 'SAMPLE KITS'
        root = self.current_root()
        if root is None:
            return 'SD / USB'
        source = next(s for s in self.sources+self.kit_sources if s.path.resolve() == root)
        relative = self.directory.resolve().relative_to(root)
        return source.name if str(relative) == '.' else str(relative)

    def up(self):
        child=self.directory
        if self.directory == self.kit_menu:
            self.directory = None
        elif self.directory is not None:
            root = self.current_root()
            if root == self.directory.resolve():
                self.directory = self.kit_menu if self.kit_source(self.directory) else None
            else:
                self.directory = self.directory.parent
        entries=self.entries()
        self.index=entries.index(child) if child in entries else 0

    def selected(self):
        entries = self.entries()
        self.index = min(self.index, max(0, len(entries)-1))
        return entries[self.index] if entries else None

    def locate(self, sample):
        """Focus an existing sample within a currently available source, without loading."""
        if not sample:
            return 'NO SAMPLE'
        try:
            path = Path(sample).resolve()
            if not path.is_file():
                return 'SAMPLE MISSING'
            if not any(path.is_relative_to(source.path.resolve()) for source in self.sources):
                return 'SOURCE UNAVAILABLE'
            # Do not change the user's current folder when the target is hidden,
            # unsupported or no longer visible in a freshly enumerated directory.
            probe = Browser(self.samples)
            probe.sources = self.sources
            probe.directory = path.parent
            entries = probe.entries()
            index = next((i for i, entry in enumerate(entries) if entry.resolve() == path), None)
            if index is None:
                return 'SAMPLE UNAVAILABLE'
            self.directory, self.index = path.parent, index
            self.started, self.error = True, ''
            return ''
        except (OSError, RuntimeError):
            return 'SOURCE UNAVAILABLE'

    def is_folder(self,path):
        return path == self.kit_menu or (self.kit_menu is not None and self.directory == self.kit_menu) or path.is_dir()

    def single_kit_bank(self,path):
        if path==self.kit_menu or self.directory==self.kit_menu:return None
        manifest=path/'Set.json'
        if not self.kit_source(path) or not manifest.is_file() or manifest.is_symlink():
            return None
        # LOAD needs the current bank list even if the filesystem gave a
        # recent edit the same directory timestamp as the previous scan.
        _directory_rows.cache_clear()
        rows=_directory_rows(path,self.current_root(),path.stat().st_mtime_ns)
        if len(rows)==1:
            bank=next(iter(rows))
            if bank.name=='Preset.json':return bank
        return None

    def open(self):
        path = self.selected()
        if path is None:
            return None
        if self.is_folder(path):
            bank=self.single_kit_bank(path)
            if bank is None:
                self.directory, self.index = path, 0
                return None
            path=bank
        # Verify again at load time; directory state may change on hotplug.
        root = self.current_root()
        if root is None or not path.resolve().is_relative_to(root):
            raise OSError('sample is outside its source')
        return path


@lru_cache(maxsize=16)
def _directory_rows(directory,root,modified):
    rows=[]
    for path in directory.iterdir():
        if path.name.startswith('.') or not path.resolve().is_relative_to(root):
            continue
        folder=path.is_dir()
        preset=path/'Preset.json'
        if folder and preset.is_file() and not preset.is_symlink():
            path=preset
            folder=False
        elif not folder and path.suffix.lower() not in ('.wav','.mp3','.sound'):
            continue
        rows.append((path,folder,Browser.file_label(path)))
    rows.sort(key=lambda row:(not row[1],row[2].casefold()))
    return {path:label for path,_,label in rows}


def browser_snapshot(browser):
    def rows(sources):
        return tuple((s.name,str(s.path)) for s in sources)
    return (str(browser.directory) if browser.directory is not None else None,
            rows(browser.sources),browser.index,browser.prehear,rows(browser.kit_sources))


def browser_from_snapshot(state):
    directory,sources,index,prehear,*kits = state
    kit_sources = [Source(name,Path(path)) for name,path in kits[0]] if kits else []
    browser = Browser(sources[0][1],kit_root=kit_sources[0].path if kit_sources else None)
    browser.sources = [Source(name,Path(path)) for name,path in sources]
    browser.kit_sources = kit_sources
    browser.directory = Path(directory) if directory else None
    return browser,index,prehear


def mount_identities(path=Path('/proc/self/mountinfo')):
    def unescape(value):
        for code,char in (('\\040',' '),('\\011','\t'),('\\012','\n'),('\\134','\\')):value=value.replace(code,char)
        return value
    result={}
    try:
        for line in path.read_text().splitlines():
            left,right=line.split(' - ',1);fields=left.split();other=right.split()
            if len(fields)<6 or len(other)<2:continue
            result[unescape(fields[4])]=(json.dumps([fields[0],fields[2],fields[3],other[0],unescape(other[1])]),'ro' in fields[5].split(','))
    except (OSError,ValueError):pass
    return result


def mounted_sources(manifest=Path('/run/maschineos-media.json'),mountinfo=Path('/proc/self/mountinfo')):
    try:
        rows=json.loads(manifest.read_text());identities=mount_identities(mountinfo)
        return [Source('USB '+row['name'],Path(row['path']),json.dumps([row.get('uuid',''),identities[row['path']][0]]) if row['path'] in identities else '',identities.get(row['path'],('',True))[1]) for row in rows
                if Path(row['path']).is_dir() and any(Path(row['path']).is_relative_to(base)
                    for base in ('/media','/mnt','/run/media'))]
    except (OSError,ValueError,KeyError,TypeError):return []
