# norns on Machinista (fork, branch `norns-mode`)

This fork adds a **NORNS mode** to Machinista: the real monome norns stack
(matron, crone, SuperCollider, unchanged scripts) runs on the same Raspberry
Pi as Machinista and is played from the Maschine MK3.

Status: **prototype, working on the MK3** (2026-11-08, Pi 5, one norns
instance). SHIFT + PLUG-IN enters the mode, norns A's screen shows on the
left display, and the knobs and display buttons play norns, with paced knob
input that feels right in Awake. Not yet done: a second norns instance, the
audio path, clock/MIDI.

## Goals
1. Machinista on a Raspberry Pi with a Maschine MK3, using the MK3's own
   audio interface. (Done: Pi 5, beta 17, MK3 audio at buffer 128.)
2. The real norns stack on the same Pi, bridged to Machinista: screen, input,
   audio and clock/MIDI.
3. Later: Maschine Jam 8×8 as a grid surface for norns scripts.

## Documents
- [DESIGN.md](DESIGN.md): decisions, the MK3 control map, the bridges and
  open questions.
- [INSTALL-NOTES.md](INSTALL-NOTES.md): the reference installation on a Pi 5,
  step by step, as raw material for an installer.

## Where the code is
| Path | What it does |
|---|---|
| `app/norns_mode.py` | Takeover mode: SHIFT + PLUG-IN, routes MK3 input to norns over OSC |
| `app/norns_display.py` | Draws the norns frames on the MK3 displays (renderer process) |
| `app/mk3_session.py`, `app/mk3_display.py` | Hooks, marked `norns-mode fork hook` |
| `norns/mod/machinista_bridge/` | norns mod that exports the framebuffer as PNG |
| `norns/data/system.mods` | Enables the mod inside the container |
| `norns/run-norns.sh` | Starts norns instance A or B in Docker |
| `norns/tools/osc_send.py` | Sends a test OSC message to a norns instance |
| `tests/test_norns_mode.py` | Unit tests |

The norns runtime image comes from norns-lab (a separate, currently private
repository): upstream norns built for ARM64 Linux in Docker.

## Quick start (on the Pi)
```bash
norns/run-norns.sh A        # OSC on 127.0.0.1:10111, frames in ~/norns/A
norns/run-norns.sh B        # OSC on 127.0.0.1:10112, frames in ~/norns/B
sudo systemctl restart machinista
```
On the MK3, press **SHIFT + PLUG-IN** to enter or leave NORNS mode.

Test input without the MK3:
```bash
PORT=10111 python3 norns/tools/osc_send.py /remote/enc 1 1
PORT=10111 python3 norns/tools/osc_send.py /remote/key 2 1
```

## Licensing
Machinista is GPL-3.0-or-later and norns is GPLv3.
