#!/usr/bin/env python3
"""Proposes MIDI layer 3 maps for scripts from their dumped parameters
(dump-params.py), as norns/mod/machinista_bridge/maps/<script>.map.

    norns/library/suggest-maps.py ~/norns-params            # every dumped script without a map
    norns/library/suggest-maps.py ~/norns-params orgn amen  # these (overwrites)

Knobs go to the most playable continuous parameters (filter, feedback,
rate, decay, mix...), keys to on/off and trigger parameters (freeze, hold,
reverse, record...). Set-up parameters (MIDI, clock, outputs, files) are
left out. The result is a starting point: maps are reviewed by hand, and a
map edited by hand is kept (only scripts without a map are written unless
named).
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAPS = HERE.parent / 'mod/machinista_bridge/maps'

# paramset types
NUMBER, OPTION, CONTROL, FILE, TAPER, TRIGGER, BINARY = 1, 2, 3, 4, 5, 9, 10

SKIP = re.compile(r'midi|clock|channel|\bch\b|device|crow|grid|arc\b|jf|\bjust ?friends|w/|txo|output|\bout\b|'
                  r'\bin\b|input|pset|preset|save|load|file|folder|sample ?select|scale|root|tuning|octave|'
                  r'transpose|note|bpm|tempo|meter|brightness|seed|random seed|cc|port|voice ?count|polyphony|'
                  r'engine|nb_|tts|osc|mod ?source|lfo ?shape|shape$|wave ?form|sync', re.I)
# Higher is more playable as a knob.
KNOB_WORDS = [
    (r'cutoff|filter|freq|lpf|hpf|tone|bright', 10),
    (r'feedback|fdbk|fb\b|regen', 9),
    (r'rate|speed|pitch|stretch', 8),
    (r'decay|release|sustain|length|time|size', 7),
    (r'mix|wet|dry|blend|send|amount|depth|drive|dist|crush|bits|fold|noise', 7),
    (r'res\b|resonance|q\b', 6),
    (r'density|spread|jitter|grain|chaos|prob|rand|drift|wobble|mod|lfo', 6),
    (r'attack|pan|width|detune|spray', 4),
    (r'level|vol|amp|gain', 3),
]
KEY_WORDS = [
    (r'freeze|hold|loop|reverse|rev\b|rec|record|overdub|play|run|mute|bypass|on$|enable', 10),
    (r'random|randomi[sz]e|reset|clear|trig|retrig|shuffle|jump|next|regen', 8),
]


def score(param, words):
    text = f"{param['id']} {param['name']}"
    best = 0
    for pattern, value in words:
        if re.search(pattern, text, re.I):
            best = max(best, value)
    return best


def label(param):
    name = re.sub(r'[^A-Za-z0-9 +#./-]+', ' ', param['name']).strip() or param['id']
    return name.upper()[:12]


def numeric_range(param):
    try:
        return float(param['min']), float(param['max'])
    except (TypeError, ValueError):
        return None


def suggest(params, system=frozenset()):
    knobs, keys, seen = [], [], set()
    for i, p in enumerate(params):
        if p['id'] in system or SKIP.search(f"{p['id']} {p['name']}") or p['id'] in seen:
            continue
        t = p['t']
        if t in (CONTROL, TAPER) or (t == NUMBER and (numeric_range(p) or (0, 0))[1] - (numeric_range(p) or (0, 0))[0] >= 8):
            s = score(p, KNOB_WORDS)
            if s:
                knobs.append((-s, i, p))
        elif t in (BINARY, TRIGGER) or (t == OPTION and len(p['options']) == 2):
            s = score(p, KEY_WORDS)
            if s:
                keys.append((-s, i, p))
    knobs.sort(key=lambda x: (x[0], x[1]))
    keys.sort(key=lambda x: (x[0], x[1]))
    chosen_knobs, used = [], set()
    for _, _, p in knobs:
        # Spread over the script: two "filter" knobs from different voices are fine,
        # the same name twice in a row is not.
        if label(p) in used:
            continue
        used.add(label(p))
        chosen_knobs.append(p)
        if len(chosen_knobs) == 6:
            break
    chosen_keys = [p for _, _, p in keys][:6]
    return chosen_keys, chosen_knobs


def key_entry(p, name):
    entry = {'id': p['id'], 'label': name}
    if p['t'] == OPTION:
        entry['off'], entry['on'] = 1, 2
        entry['off_label'] = (name + ' ' + str(p['options'][0]).upper())[:12]
        entry['on_label'] = (name + ' ' + str(p['options'][1]).upper())[:12]
    elif p['t'] == BINARY:
        entry['off'], entry['on'] = 0, 1
    return entry


def lua(value):
    if isinstance(value, str):
        return json.dumps(value)
    return repr(value)


def distinct_labels(params):
    """Labels for the chosen controls; per-voice ones ("PLAY" x 6) get their
    number from the id (1play -> 1 PLAY)."""
    labels = [label(p) for p in params]
    for i, p in enumerate(params):
        if labels.count(labels[i]) > 1:
            digits = re.findall(r'\d+', p['id'])
            if digits:
                labels[i] = (digits[0] + ' ' + labels[i])[:12]
    return labels


def render(name, keys, knobs):
    key_labels = dict(zip(map(id, keys), distinct_labels(keys)))
    knob_labels = dict(zip(map(id, knobs), distinct_labels(knobs)))
    lines = [f'-- MIDI layer 3 for {name}: keys 1-3 then knobs 1-3 per layer.',
             '-- Proposed by norns/library/suggest-maps.py, reviewed by hand.', 'return {']
    for layer in (3,):  # layers 1 and 2 are the same for every script (lib/layers.lua)
        start = 0
        controls = keys[start:start + 3] + [None] * (3 - len(keys[start:start + 3]))
        controls += knobs[start:start + 3] + [None] * (3 - len(knobs[start:start + 3]))
        if not any(controls):
            continue
        lines.append(f'  [{layer}] = {{')
        for i, p in enumerate(controls):
            if p is None:
                lines.append('    {},')
                continue
            if i < 3:
                entry = key_entry(p, key_labels[id(p)])
            else:
                entry = {'id': p['id'], 'label': knob_labels[id(p)]}
            lines.append('    { ' + ', '.join(f'{k} = {lua(v)}' for k, v in entry.items()) + ' },')
        lines.append('  },')
    lines.append('}')
    return '\n'.join(lines) + '\n'


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    source = Path(sys.argv[1]).expanduser()
    names = sys.argv[2:]
    MAPS.mkdir(parents=True, exist_ok=True)
    # norns' own parameters (levels, reverb, compressor, clock...) appear in
    # every dump; the script's own ones don't.
    dumps = {path.stem: json.loads(path.read_text()) for path in source.glob('*.json')}
    common = None
    for params in dumps.values():
        ids = {p['id'] for p in params}
        if len(ids) > 20:
            common = ids if common is None else common & ids
    system = frozenset(common or ())
    for path in sorted(source.glob('*.json')):
        name = path.stem
        target = MAPS / f'{name}.map'
        if names and name not in names:
            continue
        if not names and target.exists():
            continue
        params = dumps[name]
        keys, knobs = suggest(params, system)
        if not keys and not knobs:
            print(f'{name:22} nothing playable found')
            continue
        target.write_text(render(name, keys, knobs))
        print(f'{name:22} keys: {", ".join(label(p) for p in keys[:6])} | knobs: {", ".join(label(p) for p in knobs[:6])}')


if __name__ == '__main__':
    main()
