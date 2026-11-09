"""Descriptor-relative library moves and permanent deletion, off the engine."""
from contextlib import contextmanager
import ctypes
import errno
import os
import secrets
import shutil
import stat
import sys


def rename_exclusive(src,name,dst,target):
    """Atomic no-overwrite rename, including directories and empty targets."""
    libc=ctypes.CDLL(None,use_errno=True)
    symbol='renameatx_np' if sys.platform=='darwin' else 'renameat2'
    function=getattr(libc,symbol,None)
    if function is None:raise OSError('This system cannot safely move library entries.')
    function.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
    function.restype=ctypes.c_int
    if function(src,os.fsencode(name),dst,os.fsencode(target),4 if sys.platform=='darwin' else 1):
        error=ctypes.get_errno()
        if error==errno.EEXIST:raise FileExistsError('An entry with this name already exists in the destination.')
        raise OSError(error,os.strerror(error))


class Files:
    def __init__(self,library):self.library=library
    @contextmanager
    def operation(self):
        if not self.library.upload_lock.acquire(blocking=False):raise BlockingIOError('Another library operation is in progress.')
        try:yield
        finally:self.library.upload_lock.release()
    def source(self,identity):
        source=self.library.source(identity)
        if source.read_only:raise PermissionError('The storage device is read-only.')
        return source
    def entry(self,fd,name):
        from app.web_server import filename
        filename(name);info=os.stat(name,dir_fd=fd,follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode) and not (stat.S_ISREG(info.st_mode) and name.lower().endswith(('.wav','.mp3'))):
            raise ValueError('Only sample files and folders can be managed.')
        return info
    def remove_entry(self,parent,name,info):
        current=os.stat(name,dir_fd=parent,follow_symlinks=False)
        if (current.st_dev,current.st_ino)!=(info.st_dev,info.st_ino):
            raise ValueError('The source changed during the operation.')
        if stat.S_ISDIR(info.st_mode):
            shutil.rmtree(name,dir_fd=parent)
        else:
            os.unlink(name,dir_fd=parent)
        os.fsync(parent)
    def delete(self,identity,relative,name):
        with self.operation():
            source=self.source(identity)
            with self.library.directory(source,relative) as parent:
                self.remove_entry(parent,name,self.entry(parent,name))
        return dict(ok=True,message='Deleted permanently.')
    def copy_entry(self,src,name,dst,target,depth=0,budget=None):
        if budget is None:budget=[0]
        budget[0]+=1
        if depth>64 or budget[0]>100000:raise ValueError('This folder is too large or deeply nested to move between storage devices.')
        info=os.stat(name,dir_fd=src,follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            os.mkdir(target,0o755,dir_fd=dst)
            a=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=src)
            b=os.open(target,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=dst)
            try:
                for child in os.listdir(a):self.copy_entry(a,child,b,child,depth+1,budget)
                os.fsync(b)
            finally:os.close(a);os.close(b)
        elif stat.S_ISREG(info.st_mode):
            a=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=src)
            b=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644,dir_fd=dst)
            with os.fdopen(a,'rb') as reader,os.fdopen(b,'wb') as writer:
                opened=os.fstat(reader.fileno())
                if not stat.S_ISREG(opened.st_mode) or (opened.st_dev,opened.st_ino)!=(info.st_dev,info.st_ino):raise ValueError('The source changed during the move.')
                shutil.copyfileobj(reader,writer,64*1024);writer.flush();os.fsync(writer.fileno())
                after=os.fstat(reader.fileno())
                if (opened.st_size,opened.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('The source changed during the move.')
        else:raise ValueError('Folders containing symbolic links or special files cannot be moved between storage devices.')
    def move(self,identity,relative,name,target_identity,target_path):
        with self.operation():
            source=self.source(identity);destination=self.source(target_identity)
            with self.library.directory(source,relative) as parent,self.library.directory(destination,target_path) as target:
                info=self.entry(parent,name)
                if stat.S_ISDIR(info.st_mode):
                    # Walk ancestors by fd, so aliases/mount paths cannot hide
                    # a destination nested inside its source directory.
                    ancestor=os.dup(target)
                    try:
                        for _ in range(256):
                            current=os.fstat(ancestor)
                            if (current.st_dev,current.st_ino)==(info.st_dev,info.st_ino):raise ValueError('A folder cannot be moved into itself.')
                            up=os.open('..',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=ancestor);upper=os.fstat(up)
                            if (current.st_dev,current.st_ino)==(upper.st_dev,upper.st_ino):os.close(up);break
                            os.close(ancestor);ancestor=up
                        else:raise ValueError('Destination is too deeply nested.')
                    finally:os.close(ancestor)
                try:rename_exclusive(parent,name,target,name)
                except OSError as error:
                    if error.errno!=errno.EXDEV:raise
                    stage='.move-'+secrets.token_hex(16);os.mkdir(stage,0o700,dir_fd=target)
                    fd=os.open(stage,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=target)
                    published=False
                    try:
                        self.copy_entry(parent,name,fd,'item')
                        rename_exclusive(fd,'item',target,name);published=True;os.fsync(target)
                        self.remove_entry(parent,name,info)
                    except Exception:
                        if published:return dict(ok=True,message='Copied to destination. Could not fully remove the source.')
                        raise
                    finally:
                        os.close(fd)
                        # Only our private staging directory is ever removed.
                        shutil.rmtree(stage,dir_fd=target)
                    return dict(ok=True,message='Moved.')
                os.fsync(parent);os.fsync(target)
        return dict(ok=True,message='Moved.')
