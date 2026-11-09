#!/usr/bin/env python3
"""Loads scripts on one norns instance and writes each script's own
parameters (not norns' system ones) to <out>/<script>.json, the raw material
for the MIDI layer maps (norns/mod/machinista_bridge/maps/<script>.map).

    sg docker -c "norns/library/dump-params.py 4 ~/norns-params"            # all scripts
    sg docker -c "norns/library/dump-params.py 4 ~/norns-params orgn amen"  # these

Use an instance no Sound plays; the last script it had is loaded again at the end.
"""
import json
import subprocess
import sys
import time
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = Path(__file__).resolve().parent
CODE = Path.home() / 'norns/code'
tester = SourceFileLoader('test_scripts', str(HERE / 'test-scripts.py')).load_module()
SKIP = {'machinista_bridge'}

DUMP = r'''
local T = require "core/paramset"
local first = (_machinista_system_count or 0) + 1
local out = {}
for i = first, params.count do
  local p = params.params[i]
  if p and p.id and p.t ~= T.tSEPARATOR and p.t ~= T.tGROUP then
    local e = {id = p.id, name = p.name or p.id, t = p.t, value = params:string(i)}
    if p.controlspec then e.min = p.controlspec.minval; e.max = p.controlspec.maxval; e.units = p.controlspec.units end
    if p.min and not p.controlspec then e.min = p.min; e.max = p.max end
    if p.options then e.options = p.options end
    table.insert(out, e)
  end
end
local function esc(s) return (tostring(s):gsub("[\t\n]", " ")) end
for _, e in ipairs(out) do
  print("PARAMDUMP", esc(e.id), esc(e.name), e.t, esc(e.min or ""), esc(e.max or ""), esc(e.units or ""),
        esc(e.options and table.concat(e.options, "|") or ""), esc(e.value))
end
print("PARAMDUMP_END", #out)
'''


def one_line(code):
    return ' '.join(line.strip() for line in code.strip().splitlines())


def restart(n):
    """A fresh start without a script (some scripts leave norns unable to
    load the next one, so its parameters never appear)."""
    state = Path.home() / f'norns/data/{n}/system.state'
    if state.exists():
        keep = [l for l in state.read_text().splitlines()
                if not l.split(' ')[0] in ('norns.state.script', 'norns.state.name', 'norns.state.shortname',
                                           'norns.state.path', 'norns.state.data')]
        state.write_text('\n'.join(keep) + '\n')
    subprocess.run(['bash', '-c', f'NORNS_NO_MIDI=1 {HERE.parent}/run-norns.sh {n}'], capture_output=True, timeout=120)
    time.sleep(45)


def dump(inst, name, script):
    inst.lua(f'norns.script.load("/home/we/dust/code/{name}/{script.name}")')
    time.sleep(7)
    sizes = inst.log_sizes()
    inst.lua(one_line(DUMP))
    time.sleep(1.5)
    runtime, _ = inst.logs_since(sizes)
    rows = []
    for line in runtime.splitlines():
        parts = line.split('\t')
        if parts[0] == 'PARAMDUMP' and len(parts) >= 9:
            rows.append(dict(id=parts[1], name=parts[2], t=int(parts[3]), min=parts[4], max=parts[5],
                             units=parts[6], options=parts[7].split('|') if parts[7] else [], value=parts[8]))
    return rows


def dump_system(inst):
    sizes = inst.log_sizes()
    inst.lua(one_line(DUMP.replace('(_machinista_system_count or 0) + 1', '1')))
    time.sleep(1.5)
    runtime, _ = inst.logs_since(sizes)
    return [dict(id=l.split('\t')[1]) for l in runtime.splitlines() if l.startswith('PARAMDUMP\t')]


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    n, out = int(sys.argv[1]), Path(sys.argv[2]).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    inst = tester.Instance(n)
    previous = inst.sh("grep -m1 \"^norns.state.script\" /home/we/dust/data/system.state | cut -d\"'\" -f2").strip()
    names = sys.argv[3:] or sorted(p.name for p in CODE.iterdir() if p.is_dir() and not p.name.startswith('.'))
    inst.lua('norns.script.clear()')
    time.sleep(3)
    inst.lua('_machinista_system_count = params.count')
    time.sleep(1)
    # norns' own parameters, to tell whether a script's appeared.
    system = {r['id'] for r in dump_system(inst)}
    for name in names:
        if name in SKIP:
            continue
        script = tester.entry(CODE / name)
        if script is None:
            continue
        rows = dump(inst, name, script)
        if not [r for r in rows if r['id'] not in system]:
            restart(n)
            inst.lua('norns.script.clear()')
            time.sleep(3)
            inst.lua('_machinista_system_count = params.count')
            rows = dump(inst, name, script)
            note = ' (after a restart)'
        else:
            note = ''
        (out / f'{name}.json').write_text(json.dumps(rows, indent=1))
        print(f'{name:22} {len(rows)} params{note}', flush=True)
    inst.lua('norns.script.clear()')
    if previous:
        time.sleep(2)
        inst.lua(f'norns.script.load("{previous}")')


if __name__ == '__main__':
    main()
