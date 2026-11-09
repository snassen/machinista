"""Waveform cache policy for the MK3 and shared display readers."""
from app.waveform_index import IndexedWaveforms


class Mk3Waveforms(IndexedWaveforms):
    def __init__(self):
        super().__init__(max_assets=16)
