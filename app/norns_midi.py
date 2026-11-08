"""MIDI between Machinista, the norns instances and the MK3's MIDI port.

The MK3 MIDI port has only one owner: either Machinista opens it directly or
the ALSA sequencer routes it, not both. So everything goes through the
sequencer:
- Machinista uses the NORNS MIDI BUS (a snd-virmidi port) as its MIDI device:
  its clock, start/stop and notes leave through it, and MIDI arriving at the
  MK3 port reaches Machinista through it.
- Every norns has a virtual MIDI device (norns' own, an ALSA sequencer client
  once the container has /dev/snd/seq).
- The patchbay keeps these connections: bus -> every norns, bus -> MK3,
  every norns -> MK3, MK3 -> bus. The sequencer merges what several norns send.
It only adds connections, never removes any, so connections made by hand stay.
"""
import re
import subprocess
from pathlib import Path

from app.devices import MidiDevice

BUS_KEY = 'norns:bus'
BUS_NAME = 'NORNS MIDI BUS'
PERIOD_S = 2.0
RETRY_S = 30.0
CLIENT = re.compile(r"client (\d+): '([^']*)' \[([^\]]*)\]")
PORT = re.compile(r"\s+(\d+) '([^']*)'")
LINK = re.compile(r'\s+Connecting To: (.*)')


def discover_bus(proc=Path('/proc/asound'), dev=Path('/dev/snd')):
    """The snd-virmidi card, as a Machinista MIDI device."""
    for card in sorted(proc.glob('card*')):
        try:
            if (card/'id').read_text().strip() != 'VirMIDI':
                continue
            number = int(card.name[4:])
        except (OSError, ValueError):
            continue
        path = dev/f'midiC{number}D0'
        if path.exists():
            return [MidiDevice(BUS_KEY, BUS_NAME, str(path))]
    return []


def parse_clients(text):
    """aconnect -l output -> {client: {'name', 'kind', 'pid', 'ports': {port: name}, 'to': {(c, p)}}}."""
    clients, current = {}, None
    for line in text.splitlines():
        match = CLIENT.match(line)
        if match:
            info = dict(part.split('=', 1) for part in match[3].split(',') if '=' in part)
            current = clients[int(match[1])] = {
                'name': match[2], 'kind': info.get('type', ''), 'pid': int(info['pid']) if info.get('pid', '').isdigit() else None,
                'ports': {}, 'to': set()}
            continue
        if current is None:
            continue
        match = LINK.match(line)
        if match:
            for target in match[1].split(','):
                target = target.strip().split('[')[0].strip()
                if ':' in target:
                    c, p = target.split(':', 1)
                    if c.isdigit() and p.isdigit():
                        current['to'].add((int(c), int(p)))
            continue
        match = PORT.match(line)
        if match:
            current['ports'][int(match[1])] = match[2].strip()
    return clients


def is_norns(pid, proc=Path('/proc')):
    try:
        return (proc/str(pid)/'comm').read_text().strip() == 'norns'
    except OSError:
        return False


def wanted(clients, norns_check=is_norns):
    """The connections the patchbay keeps, as {(source, destination)} of (client, port)."""
    bus = next(((c, 0) for c, i in clients.items() if i['kind'] == 'kernel' and i['name'].startswith('Virtual Raw MIDI')), None)
    mk3 = next(((c, 0) for c, i in clients.items() if i['kind'] == 'kernel' and i['name'].startswith('Maschine MK3')), None)
    norns = [(c, 0) for c, i in clients.items()
             if i['kind'] == 'user' and i['ports'].get(0) == 'Virtual RawMIDI' and i['pid'] and norns_check(i['pid'])]
    edges = set()
    if bus:
        edges |= {(bus, n) for n in norns}
    if mk3:
        edges |= {(n, mk3) for n in norns}
        if bus:
            edges |= {(bus, mk3), (mk3, bus)}
    return edges


def missing(clients, edges):
    return {(s, d) for s, d in edges if d not in clients.get(s[0], {}).get('to', set())}


class Patchbay:
    def __init__(self, run=subprocess.run, norns_check=is_norns, log=print):
        self.run, self.norns_check, self.log = run, norns_check, log
        self.next_check = 0.0
        self.failed = {}
        self.enabled = True

    def tick(self, now):
        if not self.enabled or now < self.next_check:
            return
        self.next_check = now + PERIOD_S
        try:
            listing = self.run(['aconnect', '-l'], capture_output=True, text=True, timeout=2)
        except (OSError, subprocess.SubprocessError):
            self.enabled = False
            self.log('norns MIDI: aconnect not available, patchbay off')
            return
        clients = parse_clients(listing.stdout)
        for source, dest in sorted(missing(clients, wanted(clients, self.norns_check))):
            if self.failed.get((source, dest), 0) > now:
                continue
            result = self.run(['aconnect', f'{source[0]}:{source[1]}', f'{dest[0]}:{dest[1]}'],
                              capture_output=True, text=True, timeout=2)
            if result.returncode:
                if (source, dest) not in self.failed:
                    self.log(f'norns MIDI: cannot connect {source[0]}:{source[1]} -> {dest[0]}:{dest[1]}: {result.stderr.strip()}'
                             ' (is the MK3 MIDI port selected directly in Machinista?)')
                self.failed[(source, dest)] = now + RETRY_S
            else:
                self.failed.pop((source, dest), None)
                self.log(f'norns MIDI: connected {source[0]}:{source[1]} -> {dest[0]}:{dest[1]}')
