"""Bank/pad persistence, expansion mapping, browser previews and hostile imports."""
import copy
import http.client
import io
import json
import shutil
import tempfile
import threading
import unittest
import wave
import zipfile
from pathlib import Path
from urllib.parse import urlencode
from app.web_server import Library,Server
from app.presets import read_preset
from app.browser import Browser,Source


class SetEditorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.library=Library(self.root,source_scan=lambda:[]);self.editor=self.library.sets.editor
    def tearDown(self):
        for item in (self.library.sounds,self.library.stems,self.library.soundfonts):item.pool.shutdown(wait=True)
        self.tmp.cleanup()
    def wav(self,frames=200):
        stream=io.BytesIO()
        with wave.open(stream,'wb') as wav:wav.setparams((1,2,44100,0,'NONE','NONE'));wav.writeframes(b'\x01\x00'*frames)
        return stream.getvalue()
    def zip(self,files):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as archive:
            for name,data in files:archive.writestr(name,data)
        return stream.getvalue()
    def import_files(self,files,name='My Set.zip'):
        data=self.zip(files);return self.editor.import_archive(name,io.BytesIO(data),len(data))
    def draft(self):
        upload=self.editor.start()['id'];audio=self.wav();ref=self.editor.upload_file(upload,'Kick.wav',io.BytesIO(audio),len(audio))['asset']
        pads=[None]*16;pads[0]=dict(name='My Kick',asset=ref)
        return dict(name='My Custom Kit',banks=[dict(name='Main',pads=pads)],notes=[])
    def test_maschine_kit_draft_resolves_audio_and_compacts_synths(self):
        ids = b'\x02\x34\x12'
        record = bytes.fromhex('000000ff010000') + ids * 4

        def sound(name, *paths):
            wavs = b''.join(bytes([len(path)]) + path + b'\x01' for path in paths)
            return record + bytes(6) + ids * 2 + b'\x00\x01' + bytes([len(name)]) + name + ids + wavs

        kick = b'Samples/Drums/Kick.wav'
        kit = (bytes(12) + b'hsinserialization::archive' + sound(b'Kick', kick, kick)
               + sound(b'Synth') + sound(b'Kick Again', kick)
               + sound(b'Snare', b'Samples/Drums/Snare.wav')
               + ids + bytes.fromhex('01090101') + ids * 4
               + record + bytes(6) + ids * 2 + b'\x00\x01\x03Kit')
        path = self.root / 'samples' / 'Pack' / 'Samples' / 'Drums'
        path.mkdir(parents=True)
        (path / 'Kick.wav').write_bytes(self.wav())
        draft = self.editor.inspect_maschine_kit('My Kit.mxgrp', io.BytesIO(kit), len(kit))
        self.assertEqual(draft['name'], 'My Kit')
        self.assertEqual([pad['name'] for pad in draft['pads']], ['Kick', 'Kick Again', 'Snare'])
        self.assertIn('Skipped 1', draft['notes'][0])
        self.assertNotIn('asset', draft['pads'][2])
        self.assertEqual(draft['pads'][0]['asset'], draft['pads'][1]['asset'])
        self.assertEqual(self.library.sets.listing(), [])

        (path / 'Snare.wav').write_bytes(self.wav())
        draft = self.editor.inspect_maschine_kit('My Kit.mxgrp', io.BytesIO(kit), len(kit))
        pads = draft['pads'] + [None] * 13
        result = self.editor.save(dict(name=draft['name'], banks=[dict(name='My Kit', pads=pads)]))
        saved = self.editor.item(result['id'])
        self.assertEqual(saved['banks'][0]['pads'][2]['name'], 'Snare')

    def test_expansion_folder_contains_separately_editable_kits(self):
        first = self.draft()
        first['expansion'] = 'Velvet Bloom'
        second = dict(first, name='Second Kit')
        ids = [self.editor.save(value)['id'] for value in (first, second)]
        folder = self.library.sets.folder / 'Velvet Bloom'
        self.assertEqual([row['expansion'] for row in self.library.sets.listing()], ['Velvet Bloom'] * 2)
        self.assertTrue(all((folder / identity / 'Set.json').is_file() for identity in ids))
        browser = Browser(self.root / 'samples', (Source('SAMPLE KITS', self.library.sets.folder),))
        browser.refresh([])
        browser.directory = self.library.sets.folder
        self.assertEqual(browser.entries(), [folder])
        browser.directory = folder
        self.assertEqual([browser.label(path) for path in browser.entries()], ['My Custom Kit', 'Second Kit'])
        item = self.editor.item(ids[0])
        self.editor.save(dict(item, name='Renamed Kit'))
        self.assertEqual(self.editor.item(ids[0])['name'], 'Renamed Kit')
        self.editor.delete(dict(id=ids[0], revision=self.editor.revision(ids[0]), confirmed=True))
        self.assertEqual([row['id'] for row in self.library.sets.listing()], ids[1:])

    def test_custom_kit_folder_create_and_permanent_delete(self):
        editor=self.editor
        with self.assertRaises(ValueError):
            editor.manage_folder(dict(name='../Kits'))
        editor.manage_folder(dict(name='Live Kits'))
        self.assertEqual([p.name for p in self.library.sets.expansions()], ['Live Kits'])
        with self.assertRaises(FileExistsError):
            editor.manage_folder(dict(name='live kits'))
        draft=dict(self.draft(),expansion='Live Kits')
        identity=editor.save(draft)['id']
        with self.assertRaisesRegex(ValueError,'Confirm'):
            editor.manage_folder(dict(name='Live Kits'),delete=True)
        self.assertEqual(editor.item(identity)['expansion'],'Live Kits')
        editor.manage_folder(dict(name='Live Kits',confirmed=True),delete=True)
        self.assertEqual(self.library.sets.listing(),[])
        self.assertFalse(list(self.library.sets.expansions()))
        self.assertFalse((editor.folder/'.trash').exists())

    def test_usb_kit_storage_and_browser_hierarchy(self):
        usb=self.root/'usb';usb.mkdir()
        source=Source('USB TEST',usb)
        self.library.scan=lambda:[source]
        storage=next(key for key in self.library.sources() if key!='sd')
        upload=self.editor.start(dict(storage=storage))['id']
        data=self.wav()
        asset=self.editor.upload_file(upload,'Kick.wav',io.BytesIO(data),len(data))['asset']
        pads=[dict(name='Kick',asset=asset)]+[None]*15
        result=self.editor.save(dict(storage=storage,name='USB Kit',expansion='Live',banks=[dict(name='Bank A',pads=pads)]))
        identity=result['id']
        self.assertTrue(identity.startswith(storage+':'))
        self.assertEqual(self.library.sets.listing(),[])
        self.assertEqual(self.library.sets.listing(storage)[0]['name'],'USB Kit')
        item=self.editor.item(identity)
        with self.editor.asset(item['banks'][0]['pads'][0]['asset']) as stream:
            self.assertEqual(stream.read(),data)
        editor_root=self.library.sets.folder
        browser=Browser(self.root/'samples',kit_root=editor_root)
        browser.internal_sources=(Source('SAMPLE KITS',browser.kit_menu),)
        browser.refresh([source]);browser.directory=browser.kit_menu
        self.assertEqual([browser.label(p) for p in browser.entries()],['SD CARD','USB TEST'])
        browser.index=1;browser.open()
        self.assertEqual([p.name for p in browser.entries()],['Live'])
        browser.open()
        group=read_preset(browser.open(),'GROUP',self.root)
        self.assertTrue(Path(group['pads'][0]['sample']).is_relative_to(usb.resolve()))
        self.editor.discard_stage(dict(upload=upload))
        self.editor.delete(dict(id=identity,revision=item['revision'],confirmed=True))
        self.assertFalse((usb/'Machinista Sample Kits'/'.trash').exists())
        archive=self.zip([('Audio/Kick.wav',data)])
        imported=self.editor.import_archive('Audio.zip',io.BytesIO(archive),len(archive),storage)
        self.assertEqual(self.editor.item(imported['id'])['storage'],storage)

    def test_folder_name_and_all_samples_in_one_expansion(self):
        result=self.import_files([(f'Pack/Samples/{i:02}.wav',self.wav()) for i in range(19)],'Pack.zip')
        item=self.editor.item(result['id']);self.assertEqual(item['name'],'Pack');self.assertEqual(len(item['banks']),2)
        self.assertEqual(item['banks'][0]['pads'][0]['name'],'00');self.assertIsNone(item['banks'][1]['pads'][3])
        self.assertEqual(self.library.sets.listing()[0]['pads'],19)
        browser=Browser(self.root/'samples',(Source('SAMPLE KITS',self.library.sets.folder),));browser.refresh([]);browser.directory=self.library.sets.folder
        self.assertEqual(browser.label(browser.entries()[0]),'Pack');browser.directory=browser.entries()[0]
        entries=browser.entries();self.assertEqual(len(entries),2);self.assertEqual(browser.label(entries[0]),'Bank 1')
        group=read_preset(entries[0],'GROUP',self.root);self.assertTrue(Path(group['pads'][0]['sample']).is_file())
    def test_expansion_xml_title_and_sparse_mpc_bank_positions(self):
        xpm=b'<MPCVObject><Program type="Drum"><ProgramName>Night Kit</ProgramName><Instruments><Instrument number="1"><Layers><Layer><SampleName>Kick</SampleName></Layer></Layers></Instrument><Instrument number="18"><Layers><Layer><SampleName>Snare.WAV</SampleName></Layer></Layers></Instrument></Instruments></Program></MPCVObject>'
        result=self.import_files([('Expansion.xml',b'<expansion><title>Night Machines</title></expansion>'),('Kit.xpm',xpm),('Kick.wav',self.wav()),('Snare.wav',self.wav())],'Test.xpn')
        item=self.editor.item(result['id']);self.assertEqual(item['name'],'Night Machines');self.assertEqual(len(item['banks']),2)
        self.assertEqual(item['banks'][0]['pads'][0]['name'],'Kick');self.assertEqual(item['banks'][1]['pads'][1]['name'],'Snare')
        self.assertIsNone(item['banks'][1]['pads'][0])
    def test_mpc_velocity_layers_survive_native_roundtrip(self):
        xpm=b'<MPCVObject><Program type="Drum"><Instruments><Instrument number="4"><Layers><Layer><SampleName>Soft</SampleName><VelStart>1</VelStart><VelEnd>63</VelEnd></Layer><Layer><SampleName>Hard</SampleName><VelStart>64</VelStart><VelEnd>127</VelEnd></Layer></Layers></Instrument></Instruments></Program></MPCVObject>'
        result=self.import_files([('Kit.xpm',xpm),('Soft.wav',self.wav()),('Hard.wav',self.wav(300))])
        item=self.editor.item(result['id']);self.assertEqual(item['banks'][0]['pads'][3]['layers'],2)
        self.editor.save(item);item=self.editor.item(item['id'])
        _,banks=self.editor.banks(item['id']);group=read_preset(banks[0][1]/'Preset.json','GROUP',self.root)
        self.assertEqual([(z['vel_lo'],z['vel_hi']) for z in group['pads'][3]['zones']],[(1,63),(64,127)])
    def test_missing_mpc_sample_fails_atomically(self):
        xpm=b'<MPCVObject><Program type="Drum"><Instruments><Instrument number="1"><Layers><Layer><SampleName>Missing</SampleName></Layer></Layers></Instrument></Instruments></Program></MPCVObject>'
        with self.assertRaisesRegex(ValueError,'Missing'):self.import_files([('Kit.xpm',xpm),('Other.wav',self.wav())])
        self.assertEqual(self.library.sets.listing(),[])
    def test_maschine_import_skips_presets_and_uses_sample_directories(self):
        result=self.import_files([('Expansion/Samples/Kicks/Kick.wav',self.wav()),('Expansion/Samples/Snares/Snare.wav',self.wav()),('Expansion/Groups/Kit.mxgrp',b'native binary'),('Expansion/Sounds/Synth.nksf',b'plugin state'),('Expansion/Sounds/Protected.ncw',b'not decoded')],'Industrial Kit.zip')
        item=self.editor.item(result['id']);self.assertEqual(item['name'],'Industrial Kit');self.assertEqual(len(item['banks']),2)
        self.assertTrue(any('Native kit mappings' in n for n in item['notes']))
        self.assertFalse(any(p.suffix in ('.nksf','.ncw','.mxgrp') for p in self.library.sets.bundle(item['id']).rglob('*')))
    def test_editor_reorders_banks_and_pads_without_losing_assets(self):
        value=self.draft();value['banks'].append(dict(name='Second',pads=[None]*16))
        result=self.editor.save(value);item=self.editor.item(result['id']);pad=item['banks'][0]['pads'][0]
        item['banks'][1]['pads'][15]=pad;item['banks'][0]['pads'][0]=None;item['banks'].reverse()
        self.editor.save(item);saved=self.editor.item(item['id'])
        self.assertEqual(saved['banks'][0]['pads'][15]['name'],'My Kick');self.assertIsNone(saved['banks'][1]['pads'][0])
        with self.editor.asset(saved['banks'][0]['pads'][15]['asset']) as f:self.assertEqual(f.read(),self.wav())
    def test_save_copy_keeps_original_and_stale_revision_cannot_overwrite(self):
        result=self.editor.save(self.draft());item=self.editor.item(result['id']);stale=copy.deepcopy(item)
        item['name']='Changed';self.editor.save(item)
        with self.assertRaisesRegex(ValueError,'changed'):self.editor.save(stale)
        item=self.editor.item(result['id']);item.pop('id');item.pop('revision');self.editor.save(item)
        self.assertEqual(len(self.library.sets.listing()),2)
    def test_replacing_sample_keeps_previous_path_for_existing_projects(self):
        result=self.editor.save(self.draft());item=self.editor.item(result['id']);old=item['banks'][0]['pads'][0]['asset'];path=self.library.sets.bundle(old['set'])/old['path'];before=path.read_bytes()
        item['banks'][0]['pads'][0]=None;self.editor.save(item);self.assertEqual(path.read_bytes(),before)
    def test_delete_requires_confirmation_and_revision(self):
        result=self.editor.save(self.draft());item=self.editor.item(result['id'])
        with self.assertRaises(ValueError):self.editor.delete(item)
        with self.assertRaises(ValueError):self.editor.delete(dict(id=item['id'],revision='wrong',confirmed=True))
        self.editor.delete(dict(id=item['id'],revision=item['revision'],confirmed=True));self.assertEqual(self.library.sets.listing(),[])
        self.assertFalse((self.library.sets.folder/'.trash').exists())
    def test_hostile_archives_and_xml_cannot_publish(self):
        for files in [[('../x.wav',self.wav())],[('X.wav',self.wav()),('x.wav',self.wav())],[('evil.xpm',b'<!DOCTYPE a [<!ENTITY a SYSTEM "file:///etc/passwd">]><Program/>'),('x.wav',self.wav())],[('bad.wav',b'invalid')],[('Synth.nksf',b'synth only')]]:
            with self.subTest(names=[p for p,_ in files]):
                with self.assertRaises((ValueError,wave.Error)):self.import_files(files)
                self.assertEqual(self.library.sets.listing(),[])
    def test_bad_references_and_symlinks_do_not_escape_storage(self):
        value=self.draft();value['banks'][0]['pads'][0]['asset']=dict(set='../escape',path='x.wav')
        with self.assertRaises(ValueError):self.editor.save(value)
        result=self.editor.save(self.draft());item=self.editor.item(result['id']);ref=item['banks'][0]['pads'][0]['asset']
        with self.assertRaises(ValueError):
            with self.editor.asset(dict(ref,path='../../etc/passwd')):pass
        path=self.library.sets.bundle(ref['set'])/ref['path'];path.unlink();path.symlink_to(self.root/'outside.wav')
        with self.assertRaises(OSError):
            with self.editor.asset(ref):pass
    def test_staged_folder_title_and_rejected_truncated_upload(self):
        upload=self.editor.start()['id'];audio=self.wav();self.editor.upload_file(upload,'My Folder/Kick.wav',io.BytesIO(audio),len(audio))
        with self.assertRaises(ValueError):self.editor.upload_file(upload,'Short.wav',io.BytesIO(b'x'),100)
        self.assertFalse((self.editor.stage(upload)/'Short.wav').exists())
        result=self.editor.import_folder(dict(upload=upload,name='My Folder'));self.assertEqual(result['name'],'My Folder')
    def test_archive_export_reimport_restores_all_banks(self):
        result=self.import_files([(f'{i:02}.wav',self.wav()) for i in range(18)])
        with self.library.sets.download(result['id']) as (f,_,name):data=f.read()
        copied=self.editor.import_archive(name,io.BytesIO(data),len(data));item=self.editor.item(copied['id'])
        self.assertEqual(len(item['banks']),2);self.assertEqual(item['banks'][1]['pads'][1]['name'],'17')
    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
    def test_aiff_is_converted_to_playable_pcm(self):
        import subprocess
        source=self.root/'source.wav';source.write_bytes(self.wav());target=self.root/'sample.aiff'
        subprocess.run(['ffmpeg','-v','error','-i',str(source),str(target)],check=True)
        result=self.import_files([('Keys/sample.aiff',target.read_bytes())]);pad=self.editor.item(result['id'])['banks'][0]['pads'][0]
        with self.editor.asset(pad['asset']) as f,wave.open(f,'rb') as wav:self.assertEqual(wav.getnframes(),200)
    def test_http_auth_save_list_and_preview_ranges(self):
        server=Server(('127.0.0.1',0),self.library);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            client=http.client.HTTPConnection('127.0.0.1',server.server_port)
            value=self.draft();body=json.dumps(value)
            client.request('POST','/api/sets/save',body,{'Content-Type':'application/json'});response=client.getresponse();self.assertEqual(response.status,403);response.read();client.close()
            client=http.client.HTTPConnection('127.0.0.1',server.server_port);client.request('POST','/api/sets/save',body,{'Content-Type':'application/json','X-Machinista-Token':self.library.token});response=client.getresponse();self.assertEqual(response.status,200);identity=json.loads(response.read())['id']
            client.request('GET','/api/sets/item?'+urlencode(dict(id=identity)));response=client.getresponse();item=json.loads(response.read())
            client.request('GET','/api/sets/audio?'+urlencode(dict(ref=json.dumps(item['banks'][0]['pads'][0]['asset']))),headers={'Range':'bytes=0-43'});response=client.getresponse();self.assertEqual(response.status,206);self.assertEqual(response.read(),self.wav()[:44]);client.close()
        finally:server.shutdown();server.server_close();thread.join()
