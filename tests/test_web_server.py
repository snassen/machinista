import http.client
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import wave
from app.browser import Source
from app.web_server import Library, Server, MAX_UPLOAD


def wav():
    stream=io.BytesIO()
    with wave.open(stream,'wb') as w:w.setparams((1,2,44100,0,'NONE','NONE'));w.writeframes(b'\0\0'*100)
    return stream.getvalue()


class WebLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        (self.root/'samples'/'Library'/'Kicks').mkdir(parents=True)
        self.library=Library(self.root,lambda:[])
    def test_upload_preserves_bytes_and_lists_folders_before_samples(self):
        body=wav();self.library.upload('sd','Library/Kicks','Kick 01.WAV',io.BytesIO(body),len(body))
        self.assertEqual((self.root/'samples/Library/Kicks/Kick 01.WAV').read_bytes(),body)
        self.assertEqual(self.library.list('sd','Library')['entries'][0]['name'],'Kicks')
        self.assertEqual(self.library.list('sd','Library/Kicks')['entries'][0]['name'],'Kick 01.WAV')
    def test_legacy_metadata_riff_length_is_repaired_without_changing_audio(self):
        import struct
        original=wav()
        # A legacy exporter adds a metadata chunk but omits it from RIFF size.
        bad=original[:36]+b'smpl'+struct.pack('<I',56)+bytes(56)+original[36:]
        self.library.upload('sd','Library/Kicks','Legacy.WAV',io.BytesIO(bad),len(bad))
        result=(self.root/'samples/Library/Kicks/Legacy.WAV').read_bytes()
        self.assertEqual(result[:4],bad[:4]);self.assertEqual(result[8:],bad[8:])
        self.assertEqual(struct.unpack_from('<I',result,4)[0],len(result)-8)
        with wave.open(io.BytesIO(result),'rb') as w:
            w.setpos(w.getnframes()-1);self.assertEqual(len(w.readframes(1)),2)

    def test_invalid_and_incomplete_uploads_leave_no_partial_sample(self):
        for body,length in [(b'not a wav',9),(wav()[:-3],len(wav())-3),(wav(),len(wav())+10)]:
            with self.subTest(length=length),self.assertRaises(ValueError):self.library.upload('sd','Library/Kicks','bad.wav',io.BytesIO(body),length)
        self.assertEqual(list((self.root/'samples/Library/Kicks').iterdir()),[])
    def test_existing_sample_never_overwritten_and_upload_limit(self):
        p=self.root/'samples/keep.wav';p.write_bytes(wav())
        with self.assertRaises(FileExistsError):self.library.upload('sd','','keep.wav',io.BytesIO(b'bad'),3)
        self.assertEqual(p.read_bytes(),wav())
        with self.assertRaises(ValueError):self.library.upload('sd','','large.wav',io.BytesIO(),MAX_UPLOAD+1)
    def test_paths_and_symlinks_cannot_escape_library(self):
        (self.root/'secret.wav').write_bytes(wav());(self.root/'samples/escape').symlink_to(self.root,target_is_directory=True)
        for path in ['..','../samples','/etc','Library/../../','escape']:
            with self.subTest(path=path),self.assertRaises((ValueError,OSError)):self.library.list('sd',path)
        for name in ['../secret.wav','.hidden.wav','a/b.wav','bad\\name.wav']:
            with self.subTest(name=name),self.assertRaises(ValueError):self.library.upload('sd','',name,io.BytesIO(wav()),len(wav()))
        self.assertNotIn('escape',[e['name'] for e in self.library.list('sd','')['entries']])
    def test_usb_read_only_media_and_folder_creation(self):
        usb=self.root/'usb';usb.mkdir();self.library.scan=lambda:[Source('USB TEST',usb,read_only=True)]
        identity=next(k for k in self.library.sources() if k!='sd')
        self.assertFalse(self.library.list(identity,'')['writable'])
        with self.assertRaises(PermissionError):self.library.mkdir(identity,'','No')
        self.library.mkdir('sd','Library','Loops');self.assertTrue((self.root/'samples/Library/Loops').is_dir())
    def test_no_space_and_concurrent_upload_are_rejected(self):
        with patch('app.web_server.os.fstatvfs',return_value=type('Disk',(),dict(f_bavail=0,f_frsize=4096))()):
            with self.assertRaises(OSError):self.library.upload('sd','','full.wav',io.BytesIO(wav()),len(wav()))
        self.library.upload_lock.acquire()
        try:
            with self.assertRaises(BlockingIOError):self.library.upload('sd','','busy.wav',io.BytesIO(wav()),len(wav()))
        finally:self.library.upload_lock.release()
    def test_fat_publication_fallback_keeps_complete_bytes(self):
        import errno
        with patch('app.web_server.os.link',side_effect=OSError(errno.EOPNOTSUPP,'FAT')):
            self.library.upload('sd','','fat.wav',io.BytesIO(wav()),len(wav()))
        self.assertEqual((self.root/'samples/fat.wav').read_bytes(),wav())
        self.assertEqual([p.name for p in (self.root/'samples').iterdir() if p.name.startswith('.upload')],[])


class WebHttpTests(unittest.TestCase):
    def test_mp3_storage_lists_and_downloads_with_mpeg_mime_and_ranges(self):
        body=b'ID3'+bytes(29);(self.root/'samples/Native.MP3').write_bytes(body)
        self.assertEqual(json.loads(self.request('GET','/api/list')[2])['entries'][1]['name'],'Native.MP3')
        status,headers,data=self.request('GET','/api/file?name=Native.MP3',headers={'Range':'bytes=0-9'})
        self.assertEqual((status,headers['Content-Type'],data),(206,'audio/mpeg',body[:10]))
    def test_file_management_requires_csrf_and_permanent_delete_confirmation(self):
        body=wav();self.library.upload('sd','Library/Kicks','Move.wav',io.BytesIO(body),len(body))
        headers={'X-Machinista-Token':self.library.token}
        url='/api/files/move?source=sd&path=Library%2FKicks&name=Move.wav&target_source=sd&target_path=Library'
        self.assertEqual(self.request('POST',url)[0],403)
        self.assertEqual(self.request('GET',url)[0],404)
        self.assertEqual(self.request('POST',url,headers=headers)[0],200)
        delete='/api/files/delete?source=sd&path=Library&name=Move.wav'
        self.assertEqual(self.request('POST',delete)[0],403)
        self.assertEqual(self.request('POST',delete,headers=headers)[0],400)
        self.assertEqual(self.request('POST',delete+'&confirmed=true',headers=headers)[0],200)
        self.assertFalse((self.root/'samples/Library/Move.wav').exists())
        self.assertFalse((self.root/'samples/.machinista-trash').exists())
    def test_ssh_status_and_csrf_guarded_fixed_actions(self):
        with patch('app.power_client.request',return_value={'active':True,'enabled':True,'user':'machinista'}) as request:
            self.assertEqual(self.request('GET','/api/ssh')[0],200)
            request.assert_called_once_with('ssh-status');request.reset_mock()
            self.assertEqual(self.request('POST','/api/ssh?action=disable')[0],403)
            request.assert_not_called()
            headers={'X-Machinista-Token':self.library.token}
            self.assertEqual(self.request('POST','/api/ssh?action=other',headers=headers)[0],400)
            request.assert_not_called()
            for action in ('enable','disable'):
                self.assertEqual(self.request('POST','/api/ssh?action='+action,headers=headers)[0],200)
                request.assert_called_once_with('ssh-'+action);request.reset_mock()
    def test_power_routes_require_csrf_and_only_delegate_fixed_actions(self):
        headers={'X-Machinista-Token':self.library.token}
        with patch('app.power_client.request',return_value={'ok':True}) as request:
            self.assertEqual(self.request('POST','/api/power?action=shutdown')[0],403)
            request.assert_not_called()
            self.assertEqual(self.request('GET','/api/power?action=shutdown')[0],200)
            request.assert_called_once_with('status');request.reset_mock()
            self.assertEqual(self.request('POST','/api/power?action=other',headers=headers)[0],400)
            request.assert_not_called()
            self.assertEqual(self.request('POST','/api/power?action=reboot',headers=headers)[0],200)
            request.assert_called_once_with('reboot');request.reset_mock()
            self.library.upload_lock.acquire()
            try:self.assertEqual(self.request('POST','/api/power?action=shutdown',headers=headers)[0],429)
            finally:self.library.upload_lock.release()
            request.assert_not_called()

    def test_project_transfer_http_zip_json_and_csrf(self):
        from app.model import new_project
        folder=self.root/'projects';folder.mkdir();project=new_project();project['name']='HTTP PROJECT'
        original=json.dumps(project).encode();(folder/'PROJECT-0001.json').write_bytes(original)
        self.assertEqual(self.request('GET','/api/projects')[0],200)
        status,headers,data=self.request('GET','/api/projects/file?id=PROJECT-0001.json&format=json')
        self.assertEqual(status,200);self.assertEqual(json.loads(data)['name'],'HTTP PROJECT')
        self.assertIn('attachment',headers['Content-Disposition'])
        status,headers,body=self.request('GET','/api/projects/file?id=PROJECT-0001.json')
        self.assertEqual((status,headers['Content-Type']),(200,'application/zip'))
        # CSRF rejection happens before reading any body. Keep this probe empty
        # so an early close cannot race the test client's large ZIP sendall.
        self.assertEqual(self.request('POST','/api/projects/upload?name=beat.zip')[0],403)
        status,_,data=self.request('POST','/api/projects/upload?name=beat.zip',body,{'X-Machinista-Token':self.library.token})
        self.assertEqual(status,200);self.assertNotEqual(json.loads(data)['id'],'PROJECT-0001.json')
        self.assertEqual((folder/'PROJECT-0001.json').read_bytes(),original)
        self.assertEqual(self.request('GET','/api/projects/file?id=../config/settings.json')[0],400)
    def setUp(self):
        WebLibraryTests.setUp(self);self.server=Server(('127.0.0.1',0),self.library)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.stop)
    def stop(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def request(self,method,path,body=None,headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        connection.request(method,path,body,headers or {});response=connection.getresponse();result=(response.status,dict(response.getheaders()),response.read());connection.close();return result
    def test_http_upload_list_download_range_and_conflicts(self):
        body=wav();h={'X-Machinista-Token':self.library.token}
        self.assertEqual(self.request('POST','/api/upload?name=Test.wav',body,h)[0],200)
        self.assertEqual(self.request('POST','/api/upload?name=Test.wav',body,h)[0],409)
        self.assertEqual(self.request('GET','/api/file?name=Test.wav')[2],body)
        status,headers,data=self.request('GET','/api/file?name=Test.wav',headers={'Range':'bytes=10-19'})
        self.assertEqual((status,data),(206,body[10:20]));self.assertEqual(headers['Content-Range'],f'bytes 10-19/{len(body)}')
        self.assertEqual(self.request('GET','/api/file?name=Test.wav',headers={'Range':'bytes=99999-'})[0],416)
    def test_approved_logo_is_a_bounded_static_asset_and_legacy_tabs_can_upload(self):
        folder=self.root/'web';folder.mkdir()
        data=(Path(__file__).resolve().parents[1]/'web/logo.png').read_bytes()
        (folder/'logo.png').write_bytes(data)
        status,headers,body=self.request('GET','/logo.png')
        self.assertEqual((status,body),(200,data));self.assertEqual(headers['Content-Type'],'image/png')
        self.assertTrue(headers['Server'].startswith('Machinista'))
        self.assertEqual(self.request('POST','/api/upload?name=Legacy.wav',wav(),{'X-Machinist-Token':self.library.token})[0],200)
    def test_cross_origin_or_rebinding_uploads_are_rejected(self):
        self.assertEqual(self.request('POST','/api/folder?name=New')[0],403)
        self.assertEqual(self.request('POST','/api/folder?name=New',headers={'X-Machinista-Token':self.library.token,'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request('GET','/api/session',headers={'Host':'evil.example'})[0],403)
        self.assertEqual(json.loads(self.request('GET','/api/session')[2])['token'],self.library.token)
    def test_symlink_sample_cannot_be_downloaded(self):
        (self.root/'outside.wav').write_bytes(wav());(self.root/'samples/link.wav').symlink_to(self.root/'outside.wav')
        self.assertNotEqual(self.request('GET','/api/file?name=link.wav')[0],200)

    def test_authentication_covers_html_files_api_and_writes(self):
        import base64
        password='test-password-only'
        self.library.authorization='Basic '+base64.b64encode(('admin:'+password).encode()).decode()
        for route in ['/', '/app.js','/api/session','/api/system','/api/file?name=test.wav']:
            with self.subTest(route=route):self.assertEqual(self.request('GET',route)[0],401)
        headers={'Authorization':self.library.authorization}
        self.assertEqual(self.request('GET','/api/session',headers=headers)[0],200)
        self.assertEqual(self.request('POST','/api/folder?name=Protected',headers={'X-Machinista-Token':self.library.token})[0],401)
        headers['X-Machinista-Token']=self.library.token
        self.assertEqual(self.request('POST','/api/folder?name=Protected',headers=headers)[0],200)
    def test_unauthenticated_server_cannot_bind_to_lan(self):
        with self.assertRaisesRegex(ValueError,'requires a password'):Server(('0.0.0.0',0),self.library)

    def test_explicit_no_auth_allows_lan_server_without_login(self):
        with Server(('0.0.0.0',0),self.library,allow_unauthenticated=True) as server:
            self.assertIsNone(server.library.authorization)
        self.assertEqual(self.request('GET','/api/session')[0],200)
        self.assertEqual(self.request('GET','/api/list')[0],200)

    def test_wifi_credentials_require_csrf_and_are_sent_only_to_local_manager(self):
        body=json.dumps({'ssid':'Home: Router','password':'test-secret'}).encode()
        with patch('app.network_client.request',return_value={'ok':True}) as manager:
            self.assertEqual(self.request('POST','/api/network/connect',body)[0],403)
            manager.assert_not_called()
            status,headers,response=self.request('POST','/api/network/connect',body,{'X-Machinista-Token':self.library.token,'Content-Type':'application/json'})
            self.assertEqual(status,200)
            manager.assert_called_once_with('connect',ssid='Home: Router',password='test-secret')
            self.assertNotIn(b'test-secret',response)

    def test_lv2_routes_preserve_csrf_and_delegate_only_fixed_operations(self):
        headers={'X-Machinista-Token':self.library.token}
        with patch('app.lv2_client.request',return_value={'bundles':[]}) as manager:
            self.assertEqual(self.request('GET','/api/lv2')[0],200)
            self.assertEqual(self.request('POST','/api/lv2/delete?id='+('a'*32))[0],403)
            self.assertEqual(self.request('POST','/api/lv2/delete?id='+('a'*32),headers=headers)[0],200)
            manager.assert_called_with('delete',id='a'*32)
        with patch('app.lv2_client.upload',return_value={'job':'a'*32}) as upload:
            self.assertEqual(self.request('POST','/api/lv2/upload?name=Plugin.zip',b'zip',headers)[0],200)
            self.assertEqual(upload.call_args.args[0],'Plugin.zip');self.assertEqual(upload.call_args.args[2],3)
            self.assertEqual(self.request('POST','/api/lv2/upload?name=Plugin.zip',b'zip')[0],403)
