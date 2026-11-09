# norns on Machinista (fork, branch `norns-mode`)

This fork adds a **NORNS mode** to Machinista: the real monome norns stack
(matron, crone, SuperCollider, unchanged scripts) runs on the same Raspberry
Pi as Machinista and is played from the Maschine MK3.

Status: **prototype, working on the MK3** (2026-11-08, Pi 5).
- SHIFT + PLUG-IN enters NORNS mode, which follows the selected Sound: its
  Norns Instrument on the left display, its Norns Effect on the right.
  Knobs and display buttons play those norns, with paced knob input that
  feels right in Awake.
- **Audio works:** the Norns Instrument and Norns Effect plug-ins connect a
  Sound to numbered norns instances. Verified on the MK3 with four instances
  on two Sounds (each Sound: Awake → Norns Instrument → Norns Effect).
- Not yet done: see [ROADMAP.md](ROADMAP.md) (clock, script library, more
  MK3 controls, tape into the sampler, Norns Station).

## Goals
1. Machinista on a Raspberry Pi with a Maschine MK3, using the MK3's own
   audio interface. (Done: Pi 5, beta 17, MK3 audio at buffer 128.)
2. The real norns stack on the same Pi, bridged to Machinista: screen, input,
   audio and clock/MIDI.
3. Later: Maschine Jam 8×8 as a grid surface for norns scripts.

## Documents
- [ROADMAP.md](ROADMAP.md): what is still to do, with notes and open
  decisions.
- [SCRIPTS.md](SCRIPTS.md): which scripts in the pack work in the
  containers, and their CPU use.
- [DESIGN.md](DESIGN.md): decisions, the MK3 control map, the bridges and
  open questions.
- [INSTALL-NOTES.md](INSTALL-NOTES.md): the reference installation on a Pi 5,
  step by step, as raw material for an installer.
- [PI4-ADDON-REVIEW.md](PI4-ADDON-REVIEW.md): what the earlier Pi 4 add-on
  (GitHub `snassen/machinista-norns`, one norns, working audio) contributes,
  and which choices the dual setup reopens.

## Where the code is
| Path | What it does |
|---|---|
| `app/norns_mode.py` | Takeover mode: SHIFT + PLUG-IN, routes MK3 input to norns over OSC |
| `app/norns_display.py` | Draws the norns frames on the MK3 displays (renderer process) |
| `app/mk3_session.py`, `app/mk3_display.py` | Hooks, marked `norns-mode fork hook` |
| `norns/mod/machinista_bridge/` | norns mod that exports the framebuffer as PNG |
| `norns/data/system.mods` | Enables the mod inside the container |
| `norns/run-norns.sh` | Starts numbered norns instance `<n>` in Docker (`stop <n>` removes it); scripts in `~/norns/code` are shared, `~/norns/data/<n>` and `~/norns/tape/<n>` are per instance |
| `norns/bridge/` | Audio bridge: Norns Instrument / Norns Effect LV2 plug-ins, the JACK daemon, tests |
| `norns/container/Dockerfile` | The `norns-station` image: norns-lab runtime plus sc3-plugins and mi-UGens |
| `app/norns_midi.py` | NORNS MIDI BUS device and the MIDI patchbay (bus ↔ norns ↔ MK3 MIDI port) |
| `norns/library/` | The script pack (`pack.txt`), its installer and `test-scripts.py` (load errors and CPU per script) |
| `norns/container/post-ready.sh` | Runs in each container once norns is ready: builds and starts the bridge daemon |
| `norns/tools/osc_send.py` | Sends a test OSC message to a norns instance |
| `tests/test_norns_mode.py` | Unit tests |

The norns runtime image comes from norns-lab (a separate, currently private
repository): upstream norns built for ARM64 Linux in Docker.

## Putting the fork on a Pi
Both Pis run the official Machinista release the fork is built on (beta 19
as of 2026-11-09; update with Machinista's own updater), with the fork on
top. From a checkout of this branch:
```bash
tools/deploy-fork.sh machinista@<pi>   # refuses if the Pi runs another version
```
Run it again after every Machinista update (an update overwrites the files
the fork changes). A new Pi also needs Docker (`apt install docker.io`, user
in the docker group), the `norns-station` image (built here, or
`docker save | docker load` from another Pi), `~/norns` (the script library
and data), linger, and the Norns plug-ins uploaded once.

## Quick start (on the Pi)
```bash
loginctl enable-linger machinista   # once: keeps /dev/shm/norns alive (below)
docker build -t norns-station norns/container   # once, after the norns-lab image
norns/library/install-pack.sh   # the script pack into ~/norns/code (shared)
norns/run-norns.sh 1        # OSC on 127.0.0.1:10111, files in /dev/shm/norns/1
norns/run-norns.sh 2        # OSC on 127.0.0.1:10112, files in /dev/shm/norns/2
norns/bridge/build.sh plugin
norns/bridge/test.sh        # guard + drift tests in a throwaway container
```
Install the plug-ins: zip the `norns/bridge/build/norns.lv2` **folder** (not its files) and
upload it in the WebUI (LV2 Plugins), or with `POST /api/lv2/upload`.
Machinista picks up the new catalog by itself while the transport is stopped.

On the MK3, load **Norns Instrument** in a Sound's instrument slot (browser:
F1 for INSTRUMENT) and **Norns Effect** in an effect slot. Their **Norns**
control picks the instance (Instrument defaults to 1, Effect to 2). Press
**SHIFT + PLUG-IN** to enter or leave NORNS mode.

Check a bridge: `norns/bridge/bridge_stat <n>`.

**Linger is required.** systemd (RemoveIPC, on by default) deletes
everything a user owns in `/dev/shm` when that user's last login session
ends, even while Machinista (a system service) and the containers still use
it. Without linger, logging out of SSH wipes `/dev/shm/norns`: the displays
show the norns as OFFLINE and the audio bridge loses its shared file until
Machinista and the instances are restarted. Found 2026-11-09.

Test input without the MK3:
```bash
PORT=10111 python3 norns/tools/osc_send.py /remote/enc 1 1
PORT=10111 python3 norns/tools/osc_send.py /remote/key 2 1
```

## Licensing
Machinista is GPL-3.0-or-later and norns is GPLv3.
