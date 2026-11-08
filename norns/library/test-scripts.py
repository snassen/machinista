#!/usr/bin/env python3
"""Loads every script in the shared library on one norns instance and reports
errors and CPU use per script.

Run it on the Pi against an instance no Sound uses, so nothing reaches the MK3:
    norns/run-norns.sh 5
    norns/library/test-scripts.py 5              # every script
    norns/library/test-scripts.py 5 otis mlr     # only these
    norns/run-norns.sh stop 5

For each script it sends norns.script.load() through the instance's REPL,
waits, reads the matron and SuperCollider logs written meanwhile and measures
the container's CPU from its cgroup. CPU is in percent of one core, measured
after the script has settled; "base" is the instance with no script loaded.
Results go to stdout as a table and to results-<n>.json next to this file.
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CODE = Path.home() / 'norns/code'
SETTLE_S = 8      # after loading, before measuring
MEASURE_S = 10    # CPU averaged over this long
LIMIT = 150       # percent of a core: above this the script is stopped at once
SKIP = {'machinista_bridge'}
LUA_ERROR = re.compile(r'### SCRIPT ERROR|stack traceback|attempt to |load fail|script load failed|lua:\d+:')
SC_ERROR = re.compile(r'ERROR:|FAILURE IN SERVER|exception in GraphDef|not installed')
ENGINE = re.compile(r'loading engine; name: (\S+)|engine: (\S+)', re.I)


def docker(*args, timeout=30):
    return subprocess.run(['docker', *args], capture_output=True, text=True, timeout=timeout, errors='replace')


class Instance:
    def __init__(self, n):
        self.name = f'norns-{n}'

    def sh(self, command, timeout=30):
        return docker('exec', '-u', 'we', self.name, 'sh', '-c', command, timeout=timeout).stdout

    def lua(self, code):
        self.sh(f"printf '%s\\n' {sh_quote(code)} > /tmp/norns-lab.stdin")

    def log_sizes(self):
        out = self.sh('wc -c < /tmp/norns-lab-runtime.log; wc -c < /tmp/norns-lab-sclang.log').split()
        return int(out[0]), int(out[1])

    def logs_since(self, sizes):
        runtime = self.sh(f'tail -c +{sizes[0] + 1} /tmp/norns-lab-runtime.log')
        sclang = self.sh(f'tail -c +{sizes[1] + 1} /tmp/norns-lab-sclang.log')
        return runtime, sclang

    def cpu_usec(self):
        for line in self.sh('cat /sys/fs/cgroup/cpu.stat').splitlines():
            if line.startswith('usage_usec'):
                return int(line.split()[1])
        raise SystemExit('no cgroup v2 cpu.stat in the container')

    def cpu(self, seconds):
        a, t = self.cpu_usec(), time.monotonic()
        time.sleep(seconds)
        return round((self.cpu_usec() - a) / ((time.monotonic() - t) * 1e6) * 100, 1)

    def alive(self):
        return 'norns/build/norns/norns' in self.sh('ps -eo args')


def sh_quote(text):
    return "'" + text.replace("'", "'\\''") + "'"


def entry(folder):
    named = folder / f'{folder.name}.lua'
    if named.exists():
        return named
    found = sorted(p for p in folder.glob('*.lua'))
    return found[0] if found else None


def test(inst, folder):
    script = entry(folder)
    if script is None:
        return {'script': folder.name, 'status': 'no script file'}
    sizes = inst.log_sizes()
    inst.lua(f'norns.script.load("/home/we/dust/code/{folder.name}/{script.name}")')
    time.sleep(2)
    first = inst.cpu(2)
    if first > LIMIT:
        inst.lua('norns.script.clear()')
        return {'script': folder.name, 'status': 'stopped: too heavy', 'cpu': first}
    time.sleep(SETTLE_S - 4)
    cpu = inst.cpu(MEASURE_S)
    runtime, sclang = inst.logs_since(sizes)
    alive = inst.alive()
    inst.lua('norns.script.clear()')
    errors = [l.strip() for l in runtime.splitlines() if LUA_ERROR.search(l)]
    sc_errors = [l.strip() for l in sclang.splitlines() if SC_ERROR.search(l)]
    engine = next((m.group(1) or m.group(2) for m in ENGINE.finditer(runtime)), '')
    status = 'matron died' if not alive else 'lua error' if errors else 'sc error' if sc_errors else 'ok'
    result = {'script': folder.name, 'status': status, 'cpu': cpu, 'engine': engine}
    if errors or sc_errors:
        result['errors'] = (errors + sc_errors)[:4]
    return result


def main():
    if len(sys.argv) < 2 or not sys.argv[1].isdigit():
        raise SystemExit(__doc__)
    n = int(sys.argv[1])
    inst = Instance(n)
    if not inst.alive():
        raise SystemExit(f'{inst.name} is not running: norns/run-norns.sh {n}')
    names = sys.argv[2:] or sorted(p.name for p in CODE.iterdir() if p.is_dir() and not p.name.startswith('.'))
    inst.lua('norns.script.clear()')
    time.sleep(3)
    base = inst.cpu(MEASURE_S)
    print(f'base (no script): {base}% of one core', flush=True)
    results = []
    for name in names:
        if name in SKIP:
            continue
        try:
            r = test(inst, CODE / name)
        except subprocess.TimeoutExpired:
            r = {'script': name, 'status': 'timeout'}
        results.append(r)
        print(f"{r['script']:20} {r['status']:18} {str(r.get('cpu', '')):>6}  {r.get('engine', '')}"
              + (f"  {r['errors'][0][:90]}" if r.get('errors') else ''), flush=True)
        if r['status'] in ('matron died', 'timeout'):
            print('instance is unhealthy, stopping; restart it and continue with the remaining scripts')
            break
        time.sleep(3)
    out = HERE / f'results-{n}.json'
    out.write_text(json.dumps({'base': base, 'results': results}, indent=1))
    print(f'written {out}')


if __name__ == '__main__':
    main()
