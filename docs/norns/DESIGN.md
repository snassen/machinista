# NORNS mode: design

Status as of 2026-11-08. "Agreed" means decided; "Proposed" still needs a
decision.

## Decisions
- **Fork.** NORNS mode lives in the fork `snassen/machinista` (upstream
  `photogeen/machinista`) on branch `norns-mode`. It does not wait for
  upstream.
- **Takeover mode.** Entering NORNS mode steps away from normal Machinista use
  and hands most of the MK3's controls to norns, in the spirit of Ableton
  Push 3's mode for third-party devices.
- **Two norns side by side** (superseded by "norns as instrument and effect"
  below; the displays now follow the selected Sound's instrument and effect).
- **Enter/exit:** SHIFT + PLUG-IN toggles the mode. The PLUG-IN LED stays lit
  and both displays carry a "NORNS" label, so the mode is never ambiguous.
- **Machinista keeps playing underneath.** PLAY, STOP, REC, RESTART and the
  pads stay with Machinista while NORNS mode is active, and so do KEYBOARD
  and FIXED VEL (agreed 2026-11-09), so the pads can switch to keyboard mode
  while they play a norns. Root and octave still need leaving the mode.
- **KNOB 4 / KNOB 8** (built 2026-11-09) change a norns system parameter on
  their side, whatever script is loaded: the reverb return
  (`rev_return_level`, how much reverb is heard from every source), or the
  output level (`output_level`) while SHIFT is held. Machinista sends OSC
  `/machinista/param <id> <steps>`; the mod applies `params:delta`, so one
  step is 1% of the range. At the bottom (-inf) the mod switches norns'
  reverb OFF (user's wish 2026-11-09; measured saving about 1% of a core
  per norns), and turning it up switches it back ON. Reverb return does
  nothing while a script sends nothing into the reverb.
- **Keys and encoders bypass the script's OSC handler** (2026-11-09). norns
  passes every OSC message to the script's `osc.event` before handling
  `/remote/key` and `/remote/enc`. amen assumes every message is a voice
  position from its engine, errors on any first argument other than 1 or 2,
  and so swallowed K3 and E3 (also in the script menu while amen was loaded).
  The mod now hands `/remote/key` and `/remote/enc` to norns directly, and
  the `/machinista/...` messages never reach the script either.
- **Scripts resumed at startup** (2026-11-09): norns runs a resumed script's
  init before it has set `_menu.redraw`. amen calls it there and stops with
  "error: init" after every restart, though it loads fine from the menu.
  The mod sets a no-op `_menu.redraw` at startup if there is none.
- **STOP releases notes** (2026-11-09, after a stuck note in orgn): every
  STOP press, playing or stopped, in or out of NORNS mode, sends OSC
  `/machinista/notes_off` to every norns. The mod remembers which notes it
  played from Machinista and sends each a note-off. STOP still reaches
  Machinista as before.
- **norns runs in Docker** (norns-lab runtime image), one container per
  instance.
- **Bridges** use the simplest working transport first (files and OSC).
  Native code (Rust or a matron backend) only where measurement shows a need.
- **Deployment:** the fork runs on the Pi with Machinista's own updater
  disabled, because the updater would overwrite patched files.

## norns as instrument and effect (agreed 2026-11-08)
This replaces the fixed "norns A left, norns B right" model.
- **Two plug-in roles in a Sound's chain:**
  - **Norns Instrument** (instrument slot): generates sound.
  - **Norns Effect** (effect slot): receives the chain's audio as its input
    and returns norns' output.
- **Every norns instance has a number** (norns 1, 2, 3…), one container each.
  Nothing in the code assumes exactly two.
- **Several sound-generating norns** = Norns Instruments on separate Sounds,
  mixed in Machinista's mixer. They are never shown side by side.
- **Instrument + effect** = a Norns Instrument and a Norns Effect on the same
  Sound, e.g. a drone through a glitch script.
- **NORNS mode displays follow the selected Sound:** the left display is its
  Norns Instrument, the right display is always its Norns Effect, the effect
  running on top of the first norns.
- **Built 2026-11-08:** each plug-in's **Norns** control (1–8) picks its
  instance. NORNS mode reads the selected Sound's first Norns Instrument and
  first Norns Effect and shows those instances; a missing one shows
  "NO NORNS INSTRUMENT" / "NO NORNS EFFECT" and its controls do nothing. The
  footer says "INSTR n" / "EFFECT n". A key is always released on the norns
  where it was pressed, even after switching Sound or leaving the mode.
- **Measured:** four instances (two Sounds, each Instrument + Effect) running
  Awake use about 6–9% CPU each; load average about 1.2 on the Pi 5. Heavier
  scripts still need measuring.
- **Later:** an instance pool (a Sound picks a free number by itself), and
  the edge cases below.
- **Edge cases (proposed defaults, not yet confirmed):** a Sound with only a
  Norns Effect (e.g. after a sampler) shows "no norns instrument" on the left;
  with several Norns Effects on one Sound, the right display shows the first.
- **Latency to keep in mind:** a Norns Effect adds the bridge buffers in both
  directions (about 45 ms with the Pi 4 settings).

## Architecture
Machinista owns the MK3 and is the host. Each norns runs in its own container
with its own JACK server.

| Bridge | Direction | Transport | Status |
|---|---|---|---|
| Screen | norns 128×64 → MK3 display | PNG file per instance | Prototype |
| Input | MK3 buttons/knobs → norns K1–K3, E1–E3 | OSC over UDP | Prototype |
| Audio | norns ↔ Machinista Sound | Shared memory per instance (`/dev/shm/norns/<n>/bridge`) | Working |
| Clock/MIDI | Machinista ↔ norns ↔ MK3 MIDI port | ALSA sequencer patchbay | Working |
| Grid | Maschine Jam 8×8 ↔ norns grid API | open | Later |

## MK3 control map
Verified against `BUTTON_BITS` in `app/mk3_protocol.py`.

| norns | Instrument (left display) | Effect (right display) |
|---|---|---|
| K1–K3 | DISPLAY 1–3 | DISPLAY 5–7 |
| E1–E3 | KNOB 1–3 | KNOB 5–7 |
| spare | DISPLAY 4, KNOB 4 | DISPLAY 8, KNOB 8 |

Machinista's tempo controls stay active: TEMPO + master encoder, SHIFT +
NOTE REPEAT (tap). Free for later functions: 16 pads, GROUP A–H, the master encoder
(push/4-way/touch), touch strip, SHIFT combinations and knob-touch sensing.

Knob scaling: the MK3 knobs report 1000 counts per revolution. `KNOB_TRAVEL`
in `app/norns_mode.py` (default 10, i.e. 100 norns steps per turn) sets how
many counts make one norns encoder step; `"knob_travel"` in
`config/norns.json` overrides it and is re-read about once a second while
Machinista runs, so it can be tuned without a restart. The first value (25)
felt sluggish on the MK3, whose knobs are heavy to turn. After a knob has
rested for 0.3 s, its next movement starts half a step ahead, so a small
nudge answers at once.

Pacing (agreed 2026-11-08): norns has its own encoder handling
(`lua/core/encoders.lua`). Scripts set a sensitivity (ticks per step,
default 2; Awake sets E1 to 8), and without the norns ADC hardware
`process_with_accel` multiplies a delta by 2–6 when messages arrive less than
30 ms apart. The MK3 reports knob movement every few milliseconds, so a quick
turn jumped straight to the extreme. Machinista therefore collects knob steps
and sends at most one `/remote/enc` per knob every 40 ms (`PACE_S`); the
session's poll loop flushes the rest. norns' acceleration never triggers,
script sensitivity still applies, and Machinista alone decides the feel.
Machinista-side acceleration is a possible later improvement.

## Screen
- The norns mod `machinista_bridge` exports the native framebuffer to
  `/frames/screen.png` every `NORNS_FRAME_EXPORT_MS` (default 100 ms) using
  `_norns.screen_export_png`. The container's `/frames` is mounted from
  `/dev/shm/norns/<n>` on the host.
- Machinista's renderer reads the newest PNG per side (it watches mtime) and
  draws it scaled 3× (384×192) on the 480×272 display, with K1–K3 labels under
  the display buttons and E1–E3 labels above the knobs. A missing or partly
  written frame keeps the last good image. A side whose instance shows no
  frame says it is offline.
- The PNG is not written atomically: `_norns.screen_export_png` only queues
  the export (`matron/src/screen_events.cc`), so the mod can't rename the
  file once it is complete without waiting a tick. On the Pi the reader
  regularly hits an empty file mid-write; it keeps the last good frame and
  retries on the next poll.
- If 10 fps feels sluggish: raise the export rate first, then consider a
  matron `screen_ops` backend that streams raw frames. That backend exists in
  norns only for the `NORNS_DESKTOP` (SDL) build today
  (`matron/src/hardware/io.h`).

## Input
- Machinista sends OSC `/remote/key n z` and `/remote/enc n d` to each
  container's published UDP port: norns n listens on 10110 + n (bound to
  127.0.0.1). matron handles these in `lua/core/osc.lua`.
- When a container is not running, input is dropped and Machinista carries on.
- SHIFT is always passed through to Machinista, so its own shift state never
  sticks after leaving the mode.

## Earlier transport (replaced)
The first plan used the norns-lab Node gateway (WebSocket on port 5151,
frames polled every 200 ms). It was replaced by the file + OSC transport
above, so the Pi needs no gateway. The gateway remains useful for the
browser-based test workflow on a desktop machine.

## Proposed (needs a decision)
- **Spare controls, pads and layers:** see ROADMAP.md, item 3 (DISPLAY 4/8
  as layer toggles, KNOB 4/8 as live controls, pads as MIDI notes).

## Audio bridge (built 2026-11-08)
Reused from the Pi 4 add-on and extended for numbered instances
(`norns/bridge/`):
- Each instance has a RAM folder `/dev/shm/norns/<n>`, mounted as `/frames`
  in its container. Its `bridge` file holds two lock-free rings, one per
  direction. Both ends resample very slightly to absorb the drift between
  norns' JACK clock and the MK3 (about 130 ppm measured).
- **Norns Instrument** and **Norns Effect** are two LV2 plug-ins in one bundle
  (`norns.lv2`). The **Norns** control (1–8) picks the instance; the plug-in
  maps all eight at load, so switching while playing is safe. Only one
  plug-in may use an instance; another one on the same number stays silent
  (instrument) or dry (effect). The effect also stays dry while its norns is
  not running.
- `norns_bridged` runs inside each container (started by
  `norns/container/post-ready.sh` through norns-lab's `NORN_LAB_POST_READY`)
  and connects crone's outputs and inputs. JACK runs with 256-frame periods
  (`NORN_LAB_JACK_PERIOD`).
- Fixed on the way: after one side stopped, the reader re-locked onto old
  audio still in the ring and replayed it in short bursts (inherited from the
  Pi 4 bridge). It now locks only on audio written after the last underrun.
- Tests (`norns/bridge/test.sh`): 13 guard checks plus drift runs for both
  plug-ins at 0 and ±200 ppm, no clicks and no dropouts.
- Measured with the MK3: Awake on norns 1 → Norns Instrument → Norns Effect
  → norns 2 (input monitor + reverb) → back, peaks around 0.35 at each stage,
  no underruns. CPU at that point: load average about 0.3 on the Pi 5.

## MIDI (built 2026-11-08)
Agreed: a Linux MIDI patchbay; every norns follows Machinista's MIDI clock.
- **One owner for the MK3 MIDI port.** Either Machinista opens it directly
  (raw MIDI) or the ALSA sequencer routes it; each blocks the other ("busy").
  So all MIDI goes through the sequencer.
- **NORNS MIDI BUS:** a `snd-virmidi` port (one-time setup with sudo, see
  INSTALL-NOTES.md). Machinista's MIDI IN and OUT are set to it, with MIDI
  SYNC OUT, so its clock, start/stop and MIDI notes leave through it, and
  MIDI arriving at the MK3 port reaches Machinista through it.
  `app/norns_midi.py` adds it to Machinista's MIDI devices.
- **norns:** each container gets `/dev/snd/seq` (its user is in group
  `audio`), so norns' own virtual MIDI device becomes an ALSA sequencer
  client on the Pi. `run-norns.sh` puts it on norns MIDI port 1 (unless port
  1 was given to something else) and makes MIDI the clock source before
  every start; the `machinista_bridge` mod does the same for a new instance
  with no saved state (its startup hook runs before norns restores
  `system.state`, which would overwrite it). `NORNS_MIDI_CLOCK=0` keeps the
  instance's own clock; `NORNS_NO_MIDI=1` starts it without the sequencer.
- **Patchbay** (`app/norns_midi.py`, run from the MK3 session's poll loop
  every 2 s): reads `aconnect -l` and adds missing connections: bus → every
  norns, bus → MK3, MK3 → bus, every norns → MK3. A norns client is a user
  client with a "Virtual RawMIDI" port whose process is called `norns`. It
  never removes connections, so hand-made ones stay. A connection that fails
  (e.g. the MK3 port selected directly in Machinista) is logged once and
  retried every 30 s.
- **Transport at script load:** many scripts (Awake among them) start
  running when they load and only obey the transport after a START or STOP
  arrives, so they ran free until the first PLAY. The mod watches the
  virtual device (START/CONTINUE, STOP, clock ticks) and stops a script
  that loads while Machinista is stopped (`clock.transport.stop()`), so it
  waits for PLAY.
- **PLAY after STOP (CONTINUE):** Machinista resumes with a song position
  and CONTINUE, which norns' MIDI clock ignores. Its beat ran on while
  stopped and drops back to where the ticks left off, so every
  `clock.sync()` waited for a beat far ahead: about 10 beats of silence
  after PLAY. At the second tick after CONTINUE the mod reschedules the
  waiting syncs from the real beat (switching the clock source to internal
  and back) and calls the script's transport start. Measured: first Awake
  step about 150 ms after CONTINUE (the next quarter beat), was about 6 s.
- **Notes from the Sound (built 2026-11-08):** the Norns Instrument passes
  the MIDI it gets (pads in keyboard or pad mode, Machinista's patterns,
  in and out of NORNS mode) to its own norns: plug-in → a MIDI ring in the
  bridge file (`MidiRing` in `bridge_shm.h`, lock-free, 1024 messages) →
  `norns_bridged` in the container → OSC `/machinista/midi` to matron → the
  mod plays it as MIDI from the virtual device. Scripts see it on port 1,
  together with the bus (clock). Only the plug-in that owns the bridge
  writes; event times within a block are dropped (at most one block late).
  The daemon skips messages written while it was not running.
- **Tempo in NORNS mode:** TEMPO, the master encoder (while TEMPO is
  selected) and SHIFT + NOTE REPEAT (tap) reach Machinista; the tempo shows
  in the free top slot of the left display while TEMPO is selected. The
  master encoder stays with NORNS mode otherwise, so it never changes
  something on a hidden Machinista page.
- **Consequences:** with MIDI as the clock source, norns scripts that use
  the clock stand still while Machinista's transport is stopped. Everything
  Machinista sends on the bus reaches every norns as well as the MK3 port,
  including notes for external gear. Each norns script picks its own MIDI
  channel; their output is merged unfiltered.

## Open questions
- **CPU budget:** two SuperCollider servers plus Machinista on a Pi 5, to be
  measured.
- **Upstream merges:** the branch is based on beta 17; merging beta 18 is the
  first merge test.

## Parked
- The Pi 5 touch display (Touch Display 2) as an extra surface: larger norns
  screens, a third view or touch controls. Machinista is headless today, so
  this would be a separate output path.
- norns on iOS/iPadOS.

## Background: norns internals
- Scripts draw into a 128×64 ARGB32 cairo surface
  (`matron/src/hardware/screen.cc`). On norns hardware it is pushed to an
  SSD1322 OLED over SPI.
- A plain Pi has no norns shield (no OLED, no GPIO keys or encoders), which is
  why the screen and input bridges are needed.
- norns-lab (upstream norns pinned at `42df844`, built for ARM64 Linux) needs
  one build patch: drop `-mfpu=neon` and fix printf formats.
