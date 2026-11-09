#!/usr/bin/env python3
"""Tries new scripts from the norns.community catalog, a batch at a time, on
the spare instance 5, and adds the ones that pass to the shared library.

    sg docker -c "norns/library/try-batch.py 10"          # the next 10 untried
    sg docker -c "norns/library/try-batch.py icarus mx.synths"   # these
    sg docker -c "norns/library/try-batch.py 10 icarus"   # icarus and 9 more

Nothing new touches the library the playing instances use until it passes:
  1. The batch is cloned into a test copy of the library (~/norns-staging/code,
     hard links of ~/norns/code plus the new scripts). Scripts that run system
     commands (sudo, apt, systemctl...) are rejected before anything runs.
  2. Instance 5 restarts on the test copy, so SuperCollider compiles every
     engine together. An engine that breaks the compile (a duplicate class,
     a missing UGen) would stop every norns at its next start; its script is
     taken out and the compile is tried again.
  3. Each new script is loaded and watched for Lua and SuperCollider errors
     and CPU use (test-scripts.py does the measuring). A script can leave
     something behind that breaks the next ones (taweeet leaves a failing
     startup hook), so after any failure the instance restarts and the
     script is tried once more on a clean start; that second result counts.
     A script using more than MAX_CPU counts as a failure too, and every
     start begins without a script (norns would load the last one).
  4. A script that passes is copied into ~/norns/code and added to pack.txt at
     the commit that was tested, and so is a library (no script of its own:
     ack, r...), which other scripts include. Every outcome goes to
     results.json. Name scripts to try them again (after their dependency
     arrived, say).
The playing instances compile new engines at their next restart.
"""
import json
import re
import shutil
import subprocess
import sys
import time
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
HOME = Path.home()
CODE = HOME / 'norns/code'
STAGING = HOME / 'norns-staging'
SURVEY = HERE / 'catalog-survey.json'
RESULTS = HERE / 'results.json'
PACK = HERE / 'pack.txt'
IMAGE = 'norns-station'
N = 5
MAX_CPU = 60  # percent of one core, the whole instance
BLOCKED = re.compile(r'\b(sudo|apt-get|apt install|systemctl|shutdown|reboot|poweroff|nmcli|passwd|chpasswd|mkfs|dd if=)\b'
                     r'|rm\s+-rf\s+[/~]')
COMPILE_ERROR = re.compile(r'ERROR:|Class not defined|Duplicate|duplicate|COMPILE ERROR|Compile failed|Parse error')
tester = SourceFileLoader('test_scripts', str(HERE / 'test-scripts.py')).load_module()


def log(*parts):
    print(time.strftime('%H:%M:%S'), *parts, flush=True)


def run(*command, timeout=300):
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, errors='replace')


def folder_name(entry):
    # norns writes the folder name into Lua source unescaped: keep it plain.
    name = entry['url'].rstrip('/').rsplit('/', 1)[-1]
    if name.endswith('.git'):
        name = name[:-4]
    return re.sub(r'[^A-Za-z0-9_.-]+', '-', name).strip('-')


def load_results():
    try:
        return json.loads(RESULTS.read_text())
    except (OSError, ValueError):
        return {}


def save_results(results):
    RESULTS.write_text(json.dumps(results, indent=1, sort_keys=True) + '\n')


def pack_dirs():
    return {line.split()[0] for line in PACK.read_text().splitlines() if line.strip() and not line.startswith('#')}


def git(*args, timeout=300):
    # The Pi image has no git; the norns image does.
    return run('docker', 'run', '--rm', '--user', '1000:1000', '-e', 'HOME=/tmp',
               '-v', f'{STAGING / "code"}:/code', '--entrypoint', 'git', IMAGE, *args, timeout=timeout)


def stage_library():
    """A fresh test copy of the library: hard links, so it costs no space."""
    shutil.rmtree(STAGING / 'code', ignore_errors=True)
    (STAGING).mkdir(exist_ok=True)
    run('cp', '-al', str(CODE), str(STAGING / 'code'))
    for sub in ('audio', 'data'):
        (STAGING / sub).mkdir(exist_ok=True)


def clone(entry, folder):
    target = f'/code/{folder}'
    result = git('clone', '-q', '--depth', '1', '--recurse-submodules', '--shallow-submodules', entry['url'], target)
    if result.returncode:
        return None, 'download failed: ' + (result.stderr.strip().splitlines() or [''])[-1][:120]
    rev = git('-C', target, 'rev-parse', 'HEAD').stdout.strip()
    for path in (STAGING / 'code' / folder).rglob('*'):
        if path.is_file() and path.suffix in ('.lua', '.sh', '.py', '.sc'):
            text = path.read_text(errors='replace')
            hit = BLOCKED.search(text)
            if hit:
                return None, f'runs system commands: {path.relative_to(STAGING / "code" / folder)}: {hit.group(0)}'
    return rev, None


def forget_script():
    """Start with no script: norns loads the last one at start, and one that
    misbehaves there (seaflex spins the CPU when norns starts with it) would
    skew every test after it."""
    state = STAGING / 'data' / str(N) / 'system.state'
    if state.exists():
        lines = state.read_text().splitlines()
        keep = [l for l in lines if not re.match(r'norns\.state\.(script|name|shortname|path|data) ', l)]
        state.write_text('\n'.join(keep) + '\n')


def restart_instance():
    forget_script()
    env =f'NORNS_HOME={STAGING} NORNS_TAPE_ROOT={STAGING}/tape NORNS_NO_MIDI=1'
    run('bash', '-c', f'{env} {ROOT}/run-norns.sh {N}', timeout=120)
    inst = tester.Instance(N)
    for _ in range(90):
        time.sleep(2)
        out = inst.sh('grep -c "available engines" /tmp/norns-lab-runtime.log 2>/dev/null; true')
        if out.strip() not in ('', '0'):
            return inst, inst.sh('cat /tmp/norns-lab-sclang.log 2>/dev/null; true')
    return inst, inst.sh('cat /tmp/norns-lab-sclang.log 2>/dev/null; true') + '\nCOMPILE ERROR: norns never got ready'


def compile_errors(sclang):
    return [l.strip() for l in sclang.splitlines() if COMPILE_ERROR.search(l)]


def culprit(errors, folders):
    text = '\n'.join(errors)
    for folder in folders:
        if f'/{folder}/' in text:
            return folder
    return None


def install(folder, entry, rev):
    target = CODE / folder
    if not target.exists():
        shutil.copytree(STAGING / 'code' / folder, target, symlinks=True)
    if folder not in pack_dirs():
        with PACK.open('a') as f:
            f.write(f'{folder} {entry["url"]} {rev}\n')


def pick(names, count):
    survey = json.loads(SURVEY.read_text())
    results = load_results()
    have = {p.name for p in CODE.iterdir()} | pack_dirs()
    chosen = []
    for entry in survey:
        folder = folder_name(entry)
        if entry['name'] in names or folder in names:
            chosen.insert(0, (entry, folder))
        elif count and len(chosen) < count and not (folder in have or folder in results or entry['name'] in results):
            chosen.append((entry, folder))
    named = [c for c in chosen if c[0]['name'] in names or c[1] in names]
    rest = [c for c in chosen if c not in named]
    return (named + rest)[:max(count, len(named))]


def main():
    args = sys.argv[1:]
    numbers = [a for a in args if a.isdigit()]
    names = {a for a in args if not a.isdigit()}
    count = int(numbers[0]) if numbers else (0 if names else 10)
    batch = pick(names, count)
    if not batch:
        log('nothing left to try')
        return
    results = load_results()
    log('staging the library')
    stage_library()
    staged = {}
    for entry, folder in batch:
        rev, reason = clone(entry, folder)
        if reason:
            results[folder] = {'status': 'rejected', 'reason': reason, 'tags': entry['tags']}
            log(f'{folder}: {reason}')
            shutil.rmtree(STAGING / 'code' / folder, ignore_errors=True)
        else:
            staged[folder] = (entry, rev)
    save_results(results)
    if not staged:
        return
    # Compile everything together; take out an engine that breaks it.
    while True:
        log(f'compiling with {len(staged)} new: {" ".join(staged)}')
        inst, sclang = restart_instance()
        errors = compile_errors(sclang)
        if not errors:
            break
        bad = culprit(errors, staged)
        if bad is None:
            log('compile fails, cause unknown:', errors[:3])
            bad = next(iter(staged))  # take them out one at a time
        entry, _ = staged.pop(bad)
        results[bad] = {'status': 'rejected', 'reason': 'engine breaks the compile: ' + errors[0][:150],
                        'tags': entry['tags']}
        save_results(results)
        shutil.rmtree(STAGING / 'code' / bad, ignore_errors=True)
        log(f'{bad}: breaks the compile, taken out')
        if not staged:
            return
    inst.lua('norns.script.clear()')
    time.sleep(3)
    def attempt(inst, folder):
        try:
            r = tester.test(inst, STAGING / 'code' / folder)
        except subprocess.TimeoutExpired:
            return {'status': 'timeout'}
        # More than most of a core is a runaway (or something left behind):
        # retried on a clean start like any failure.
        if r.get('status') == 'ok' and (r.get('cpu') or 0) > MAX_CPU:
            r['status'] = 'cpu'
            r.setdefault('errors', []).insert(0, f'uses {r["cpu"]}% CPU')
        return r

    def fresh():
        inst, _ = restart_instance()
        inst.lua('norns.script.clear()')
        time.sleep(3)
        return inst

    for folder, (entry, rev) in staged.items():
        tester.CODE = STAGING / 'code'
        r = attempt(inst, folder)
        if r.get('status') == 'no script file':
            # A library other scripts include (ack, r, nb...): installed, or
            # they fail with "module not found".
            results[folder] = {'status': 'library', 'reason': 'a library for other scripts, installed',
                               'tags': entry['tags'], 'rev': rev}
            install(folder, entry, rev)
            save_results(results)
            log(f'{folder:22} library, installed')
            continue
        if r.get('status') != 'ok':
            log(f'{folder:22} {r.get("status")}: retrying on a clean start')
            inst = fresh()
            r = attempt(inst, folder)
        status = r.get('status')
        record = {'status': 'installed' if status == 'ok' else 'failed', 'test': status, 'cpu': r.get('cpu'),
                  'engine': r.get('engine', ''), 'tags': entry['tags'], 'rev': rev,
                  'description': entry.get('description', '')}
        if r.get('errors'):
            record['errors'] = r['errors']
        if status == 'ok':
            install(folder, entry, rev)
        results[folder] = record
        save_results(results)
        log(f'{folder:22} {status:16} cpu {r.get("cpu", "")}  {r.get("engine", "")}'
            + (f'  {r["errors"][0][:80]}' if r.get('errors') else ''))
        if status != 'ok':
            inst = fresh()  # whatever it left behind must not reach the next script
        time.sleep(2)
    run('docker', 'stop', f'norns-{N}', timeout=60)
    log('done')


if __name__ == '__main__':
    main()
