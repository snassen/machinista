import tempfile
import time
from pathlib import Path
import unittest
from unittest.mock import patch
import wave
from app.waveform import read_envelope
from app.waveform_index import WaveformIndex,IndexedWaveforms


class WaveformIndexTests(unittest.TestCase):
    def write(self,path,width=2,channels=2,frames=33001):
        values=[((i*7919)%(1<<(width*8)))-(0 if width==1 else 1<<(width*8-1)) for i in range(frames*channels)]
        with wave.open(str(path),'wb') as wav:
            wav.setparams((channels,width,48000,0,'NONE','not compressed'))
            wav.writeframes(b''.join(v.to_bytes(width,'little',signed=width!=1) for v in values))

    def test_all_pcm_formats_and_zoom_ranges_match_exact_envelopes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'fixture.wav'
            for width in (1,2,3,4):
                for channels in (1,2):
                    self.write(path,width,channels);index=WaveformIndex(path)
                    self.assertLess(index.nbytes,33001*channels*4+10000)
                    for first,last in ((0,None),(13,32999),(250,30000),(511,17001),(14000,14120),(30,32)):
                        self.assertEqual(index.envelope(first,last),read_envelope(path,start=first,end=last),(width,channels,first,last))

    def test_scroll_and_zoom_reuse_loaded_index_without_blanks_or_file_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'fixture.wav';self.write(path)
            reader=IndexedWaveforms()
            try:
                with patch('app.waveform_index.wave.open',wraps=wave.open) as opened:
                    deadline=time.monotonic()+3;result=None
                    while result is None and time.monotonic()<deadline:
                        result=reader.envelope(path,0,15000);time.sleep(.001)
                    self.assertIsNotNone(result);self.assertEqual(opened.call_count,1)
                    for first in range(0,18000,137):
                        result=reader.envelope(path,first,first+15000)
                        self.assertIsNotNone(result);self.assertEqual(result.start,first)
                    for size in (10000,1000,120,2):self.assertIsNotNone(reader.envelope(path,1000,1000+size))
                    self.assertEqual(opened.call_count,1);self.assertIsNone(reader.future)
            finally:reader.close()

    def test_cache_is_bounded_and_changed_asset_is_reloaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader=IndexedWaveforms()
            try:
                paths=[Path(tmp)/f'{i}.wav' for i in range(3)]
                for path in paths:
                    self.write(path,frames=300)
                    deadline=time.monotonic()+3
                    while reader.envelope(path) is None and time.monotonic()<deadline:time.sleep(.001)
                self.assertEqual(len(reader.cache),2)
                self.write(paths[-1],frames=500)
                deadline=time.monotonic()+3;result=None
                while result is None and time.monotonic()<deadline:
                    result=reader.envelope(paths[-1]);time.sleep(.001)
                self.assertEqual(result.frames,500)
            finally:reader.close()

    def test_mk2_reuses_waveforms_when_returning_to_pads(self):
        from app.mk2_display import Mk2Renderer

        with tempfile.TemporaryDirectory() as tmp:
            renderer = Mk2Renderer()
            self.addCleanup(renderer.close)
            paths = [Path(tmp) / f'{i}.wav' for i in range(4)]
            for path in paths:
                self.write(path, frames=300)
            with patch('app.waveform_index.wave.open', wraps=wave.open) as opened:
                for path in paths:
                    self.assertIsNone(renderer.waveforms.envelope(path))
                    renderer.waveforms.future.result(timeout=3)
                    self.assertIsNotNone(renderer.waveforms.envelope(path))
                first = renderer.waveforms.envelope(paths[0])
                self.assertIsNotNone(first)
                self.assertIs(renderer.waveforms.envelope(paths[0]), first)
                self.assertEqual(opened.call_count, len(paths))
