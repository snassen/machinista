import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.norns_midi import BUS_KEY, Patchbay, discover_bus, missing, parse_clients, wanted

# aconnect -l on the Pi 5 with the MK3, the virmidi bus and two norns.
LISTING = """client 0: 'System' [type=kernel]
    0 'Timer           '
    1 'Announce        '
client 14: 'Midi Through' [type=kernel]
    0 'Midi Through Port-0'
client 16: 'Maschine MK3' [type=kernel,card=0]
    0 'Maschine MK3 MIDI 1'
\tConnected From: 128:0
client 20: 'Virtual Raw MIDI 3-0' [type=kernel,card=3]
    0 'VirMIDI 3-0     '
client 128: 'Client-128' [type=user,pid=208344]
    0 'Virtual RawMIDI '
\tConnecting To: 16:0
client 129: 'Client-129' [type=user,pid=208400]
    0 'Virtual RawMIDI '
client 130: 'Client-130' [type=user,pid=300]
    0 'Virtual RawMIDI '
"""
NORNS_PIDS = {208344, 208400}


class ParseTest(unittest.TestCase):
    def test_clients_ports_and_links(self):
        clients = parse_clients(LISTING)
        self.assertEqual(clients[16]['name'], 'Maschine MK3')
        self.assertEqual(clients[128]['pid'], 208344)
        self.assertEqual(clients[128]['ports'][0], 'Virtual RawMIDI')
        self.assertEqual(clients[128]['to'], {(16, 0)})
        self.assertIsNone(clients[0]['pid'])

    def test_several_targets_on_one_line(self):
        clients = parse_clients("client 20: 'Virtual Raw MIDI 3-0' [type=kernel,card=3]\n    0 'VirMIDI 3-0'\n"
                                "\tConnecting To: 128:0, 129:0[real:0], 16:0\n")
        self.assertEqual(clients[20]['to'], {(128, 0), (129, 0), (16, 0)})


class WantedTest(unittest.TestCase):
    def test_bus_feeds_every_norns_and_norns_feed_the_mk3(self):
        edges = wanted(parse_clients(LISTING), lambda pid: pid in NORNS_PIDS)
        self.assertEqual(edges, {((20, 0), (128, 0)), ((20, 0), (129, 0)),
                                 ((128, 0), (16, 0)), ((129, 0), (16, 0)),
                                 ((20, 0), (16, 0)), ((16, 0), (20, 0))})

    def test_other_virtual_clients_are_left_alone(self):
        edges = wanted(parse_clients(LISTING), lambda pid: pid in NORNS_PIDS)
        self.assertFalse(any((130, 0) in edge for edge in edges))

    def test_existing_connections_are_not_repeated(self):
        clients = parse_clients(LISTING)
        todo = missing(clients, wanted(clients, lambda pid: pid in NORNS_PIDS))
        self.assertNotIn(((128, 0), (16, 0)), todo)
        self.assertIn(((129, 0), (16, 0)), todo)

    def test_no_mk3_still_feeds_norns(self):
        clients = parse_clients(LISTING)
        del clients[16]
        edges = wanted(clients, lambda pid: pid in NORNS_PIDS)
        self.assertEqual(edges, {((20, 0), (128, 0)), ((20, 0), (129, 0))})


class PatchbayTest(unittest.TestCase):
    def make(self, fail=()):
        calls, logs = [], []

        def run(command, **_):
            calls.append(command)
            if command == ['aconnect', '-l']:
                return SimpleNamespace(stdout=LISTING, returncode=0, stderr='')
            busy = tuple(command[1:]) in fail
            return SimpleNamespace(stdout='', returncode=1 if busy else 0, stderr='Connection failed' if busy else '')
        return Patchbay(run=run, norns_check=lambda pid: pid in NORNS_PIDS, log=logs.append), calls, logs

    def test_connects_what_is_missing_then_waits(self):
        bay, calls, _ = self.make()
        bay.tick(10.0)
        connects = [c[1:] for c in calls if c[1] != '-l']
        self.assertIn(['20:0', '128:0'], connects)
        self.assertIn(['129:0', '16:0'], connects)
        self.assertNotIn(['128:0', '16:0'], connects)
        before = len(calls)
        bay.tick(10.5)
        self.assertEqual(len(calls), before)

    def test_busy_mk3_port_is_logged_once_and_retried_later(self):
        bay, calls, logs = self.make(fail={('129:0', '16:0')})
        bay.tick(0.0)
        bay.tick(5.0)
        self.assertEqual(sum('cannot connect 129:0' in l for l in logs), 1)
        self.assertEqual(sum(c[1:] == ['129:0', '16:0'] for c in calls), 1)
        bay.tick(31.0)
        self.assertEqual(sum(c[1:] == ['129:0', '16:0'] for c in calls), 2)

    def test_missing_aconnect_turns_it_off(self):
        def run(command, **_):
            raise FileNotFoundError('aconnect')
        logs = []
        bay = Patchbay(run=run, log=logs.append)
        bay.tick(0.0)
        bay.tick(5.0)
        self.assertFalse(bay.enabled)
        self.assertEqual(len(logs), 1)


class DiscoverBusTest(unittest.TestCase):
    def test_finds_the_virmidi_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc, dev = Path(tmp)/'asound', Path(tmp)/'snd'
            for n, name in ((0, 'MK3'), (3, 'VirMIDI')):
                (proc/f'card{n}').mkdir(parents=True)
                (proc/f'card{n}'/'id').write_text(name + '\n')
            dev.mkdir()
            (dev/'midiC0D0').touch()
            (dev/'midiC3D0').touch()
            found = discover_bus(proc, dev)
            self.assertEqual([(d.key, d.path) for d in found], [(BUS_KEY, str(dev/'midiC3D0'))])

    def test_nothing_without_virmidi(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(discover_bus(Path(tmp), Path(tmp)), [])


if __name__ == '__main__':
    unittest.main()
