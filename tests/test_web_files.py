import errno
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app.browser import Source
from app.web_server import Library
from app.web_files import rename_exclusive

class FileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.samples=self.root/'samples';self.samples.mkdir()
        self.library=Library(self.root,lambda:[]);self.files=self.library.files
        (self.samples/'From').mkdir();(self.samples/'To').mkdir()
        (self.samples/'From/kick.wav').write_bytes(b'audio')
    def test_file_move_never_overwrites(self):
        self.files.move('sd','From','kick.wav','sd','To')
        self.assertEqual((self.samples/'To/kick.wav').read_bytes(),b'audio')
        (self.samples/'From/kick.wav').write_bytes(b'other')
        with self.assertRaises(FileExistsError):self.files.move('sd','From','kick.wav','sd','To')
        self.assertEqual((self.samples/'To/kick.wav').read_bytes(),b'audio')
        self.assertEqual((self.samples/'From/kick.wav').read_bytes(),b'other')
    def test_nested_folder_move_and_descendant_rejection(self):
        (self.samples/'From/Sub').mkdir()
        with self.assertRaises(ValueError):self.files.move('sd','','From','sd','From/Sub')
        self.files.move('sd','','From','sd','To')
        self.assertTrue((self.samples/'To/From/Sub').is_dir())
        self.assertEqual((self.samples/'To/From/kick.wav').read_bytes(),b'audio')
    def test_folder_delete_is_permanent(self):
        self.files.delete('sd','','From')
        self.assertFalse((self.samples/'From').exists())
        self.assertFalse((self.samples/'.machinista-trash').exists())
    def test_empty_destination_folder_is_not_replaced(self):
        (self.samples/'To/From').mkdir()
        with self.assertRaises(FileExistsError):self.files.move('sd','','From','sd','To')
        self.assertTrue((self.samples/'From/kick.wav').exists())
    def test_folder_delete_does_not_follow_nested_symlinks(self):
        external=self.root/'external';external.mkdir()
        (external/'keep.wav').write_bytes(b'keep')
        (self.samples/'From/escape').symlink_to(external,target_is_directory=True)
        self.files.delete('sd','','From')
        self.assertEqual((external/'keep.wav').read_bytes(),b'keep')
    def test_cross_device_nested_symlink_never_reads_external_content(self):
        (self.samples/'From/secret').symlink_to(self.root,target_is_directory=True)
        first=True
        def rename(*args):
            nonlocal first
            if first:first=False;raise OSError(errno.EXDEV,'Different device')
            return rename_exclusive(*args)
        with patch('app.web_files.rename_exclusive',side_effect=rename):
            with self.assertRaises(ValueError):self.files.move('sd','','From','sd','To')
        self.assertTrue((self.samples/'From/kick.wav').exists())
        self.assertEqual(list((self.samples/'To').iterdir()),[])
    def test_paths_symlinks_readonly_and_concurrent_operation_rejected(self):
        (self.samples/'escape').symlink_to(self.root,target_is_directory=True)
        for method in (lambda:self.files.delete('sd','','escape'),lambda:self.files.move('sd','From','kick.wav','sd','escape'),lambda:self.files.delete('sd','..','x.wav')):
            with self.assertRaises((ValueError,OSError)):method()
        self.library.scan=lambda:[Source('RO',self.samples,read_only=True)]
        ro=next(k for k in self.library.sources() if k!='sd')
        with self.assertRaises(PermissionError):self.files.delete(ro,'From','kick.wav')
        self.library.upload_lock.acquire()
        try:
            with self.assertRaises(BlockingIOError):self.files.delete('sd','From','kick.wav')
        finally:self.library.upload_lock.release()
    def test_cross_device_move_removes_original_after_publish(self):
        usb=self.root/'usb';usb.mkdir();self.library.scan=lambda:[Source('USB',usb)]
        identity=next(k for k in self.library.sources() if k!='sd')
        first=True
        def rename(*args):
            nonlocal first
            if first:first=False;raise OSError(errno.EXDEV,'Different device')
            return rename_exclusive(*args)
        with patch('app.web_files.rename_exclusive',side_effect=rename):self.files.move('sd','','From',identity,'')
        self.assertEqual((usb/'From/kick.wav').read_bytes(),b'audio')
        self.assertFalse((self.samples/'From').exists())
        self.assertFalse((self.samples/'.machinista-trash').exists())
    def test_cross_device_copy_failure_never_removes_original(self):
        with patch('app.web_files.rename_exclusive',side_effect=OSError(errno.EXDEV,'Different device')),patch.object(self.files,'copy_entry',side_effect=OSError('Disk full')):
            with self.assertRaises(OSError):self.files.move('sd','From','kick.wav','sd','To')
        self.assertEqual((self.samples/'From/kick.wav').read_bytes(),b'audio')
        self.assertEqual(list((self.samples/'To').iterdir()),[])
