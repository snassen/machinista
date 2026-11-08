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
  pads stay with Machinista while NORNS mode is active.
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
- **Later:** how many instances fit on the Pi 5 (CPU, to be measured), how a
  Sound picks its instance number, and the edge cases below.
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
| Clock/MIDI | Machinista → norns | open | Not started |
| Grid | Maschine Jam 8×8 ↔ norns grid API | open | Later |

## MK3 control map
Verified against `BUTTON_BITS` in `app/mk3_protocol.py`.

| norns | norns A (left display) | norns B (right display) |
|---|---|---|
| K1–K3 | DISPLAY 1–3 | DISPLAY 5–7 |
| E1–E3 | KNOB 1–3 | KNOB 5–7 |
| spare | DISPLAY 4, KNOB 4 | DISPLAY 8, KNOB 8 |

Free for later functions: 16 pads, GROUP A–H, the master encoder
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
  `~/norns/<A|B>` on the host.
- Machinista's renderer reads the newest PNG per side (it watches mtime) and
  draws it scaled 3× (384×192) on the 480×272 display, with K1–K3 labels under
  the display buttons and E1–E3 labels above the knobs. A missing or partly
  written frame keeps the last good image. A side with no frame shows
  "NORNS x OFFLINE".
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
  container's published UDP port: A = 10111, B = 10112 (bound to 127.0.0.1).
  matron handles these in `lua/core/osc.lua`.
- When a container is not running, input is dropped and Machinista carries on.
- SHIFT is always passed through to Machinista, so its own shift state never
  sticks after leaving the mode.
- Instance paths and ports can be overridden in `config/norns.json`
  (`{"instances": [{"name", "frame", "port"}, …]}`, at most two).

## Earlier transport (replaced)
The first plan used the norns-lab Node gateway (WebSocket on port 5151,
frames polled every 200 ms). It was replaced by the file + OSC transport
above, so the Pi needs no gateway. The gateway remains useful for the
browser-based test workflow on a desktop machine.

## Proposed (needs a decision)
- **Spare controls:** KNOB 4/8 = output level of norns A/B; DISPLAY 4/8 =
  script menu, or choosing which norns instance sits on that side.
- **Pads and other buttons** in NORNS mode: pads still reach Machinista;
  every button except SHIFT and transport is swallowed. Should pads or
  GROUP buttons reach norns instead, e.g. as MIDI notes?

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
