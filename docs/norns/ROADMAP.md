# Roadmap

Written 2026-11-08. The user's wishes, with notes on what each one needs.
Nothing below is decided until it says "Agreed".

## Where we are
- Four norns (1–4) run in Docker on the Pi 5 next to Machinista, played
  from the MK3 in NORNS mode (SHIFT + PLUG-IN).
- Norns Instrument and Norns Effect plug-ins connect a Sound to numbered
  instances; NORNS mode follows the selected Sound (left = its Instrument,
  right = its Effect).
- Four instances running Awake use about 6–9% CPU each; load average about
  1.2 with Machinista playing.

## 1. Master clock from Machinista
**Wish:** every norns follows Machinista's tempo and transport (start, stop,
position) without setting each one by hand.

**Built 2026-11-08 (agreed: MIDI clock through a Linux MIDI patchbay; every
norns switches to MIDI clock at start):** see DESIGN.md, MIDI. Machinista's
MIDI SYNC is OUT on the NORNS MIDI BUS, so every norns follows its tempo and
start/stop. Tested with an outside clock (norns locked to 89.95 BPM from 90)
and on the MK3: STOP stops at once; PLAY after STOP (a MIDI CONTINUE) needed
a fix in the mod and now starts on the next step.
- Later, possibly: Ableton Link as well, to sync with other gear and
  laptops over the network.

## 2. Script library
**Wish:** the scripts prepared for the Pi 4 are installed on every norns.

**Built 2026-11-08 (agreed: shared code, own data; extras in a derived
image):**
- `norns/library/pack.txt`: the Pi 4 pack plus Awake, 45 scripts pinned to
  commits. `norns/library/install-pack.sh` clones them into `~/norns/code`
  (inside a container when the host has no git).
- `~/norns/code` is shared by every instance; `~/norns/data/<n>` and
  `~/norns/tape/<n>` are per instance. All persist across restarts.
- `norns/container/Dockerfile` builds the `norns-station` image:
  norns-lab's runtime plus sc3-plugins and mi-UGens (arm64).
- Scripts are loaded from norns' own menu for now (K1 → SELECT).
- Tested (SCRIPTS.md): all 45 load (cheat_codes_2 once MIDI was in). CPU per instance ranges from about 6% (idle) to 24% of
  one core, so eight heavy instances would use about half the Pi 5. 4 is
  not a limit (the code allows 8).
- `~/norns/audio` (norns' `dust/audio`) is shared by every instance, with
  `tape/<n>` mounted over its tape folder. Before 2026-11-09 it lived inside
  each container and was lost when one was recreated.
- Copied from the Pi 4 (2026-11-09): its samples (the amen break, three
  dronecaster recordings) into `~/norns/audio`, and its 10 presets (orgn,
  sines, wrms, oooooo, orca, terrarium) into each of norns 1–4. The Pi 4 has
  the same 45 scripts as the pack, nothing more.
- Pi 4 vs Pi 5, one norns with Awake stopped: about 16% of a core on the
  Pi 4 (native) against about 6% per instance on the Pi 5 (Docker).
- Still to do: check by ear that effect scripts process the Sound's audio;
  measure while scripts are being played.

**Notes from planning:**
- The Pi 4 pack is in `snassen/machinista-norns` (`library/pack.txt`):
  44 community scripts pinned to commits, all of which loaded on a Pi 4.
  It includes effect scripts for the Norns Effect slot (otis,
  carters-delay, wrms, mlr/mlre, oooooo, cranes, reels…). Scripts installed
  on the Pi 4 beyond the pack (e.g. icarus?) would need adding.
- `install_batch.py` (keeps only scripts that compile, load and stay within
  CPU) and the script chooser (`select.lua`, virtual folders, favorites) can
  be reused.
- Needs first:
  - **Persistent `dust`**: today a recreated container loses its scripts.
  - **D4:** one shared script library for all instances, with separate
    data/presets per instance (proposed), or a full `dust` per instance.
  - **sc3-plugins and mi-UGens** in the runtime image; several scripts in
    the pack need them.
- Also the way to choose a script from the MK3 (LOAD), see 3.

## 2b. MIDI out from norns
**Wish:** norns scripts (sequencers above all) send MIDI out of the MK3's
MIDI port, from several instances at once. Test it.

**Built 2026-11-08:** every norns' virtual MIDI device is connected to the
MK3 MIDI port; Linux's MIDI sequencer merges them (DESIGN.md, MIDI). Tested
from the REPL (note and CC reach the sequencer); still to try with a real
sequencer script and external gear.
- Each script picks its own MIDI channel; nothing is filtered. If several
  norns send MIDI clock out (off by default), the MK3 port gets them all.

## 3. More control from the MK3 in NORNS mode
**Wish:**
- **Pads** (keyboard mode) send MIDI notes to the norns on the selected
  Sound, for scripts that play notes (icarus and similar).
- **DISPLAY 4 / DISPLAY 8** toggle through layers for their norns: the
  native layer (K1–K3, E1–E3) plus three layers of MIDI controls, so each
  norns gets 3 buttons and 3 knobs, four times over.
- **KNOB 4 / KNOB 8** are always a live control, e.g. reverb amount.
- Mappings per script, where useful, chosen by hand for the scripts in the
  pack.
- The grid (Maschine Jam) comes later.

**Agreed 2026-11-08:** the Norns Instrument passes all the Sound's notes
(pads and patterns, in and out of NORNS mode); KNOB 4/8 = reverb amount,
output level with SHIFT; MIDI layer keys are toggles (CC 127/0, lit while
on). Order: notes, KNOB 4/8, layers.
- **Notes: built 2026-11-08** (DESIGN.md, MIDI). Played from the MK3 into
  orgn, in and out of NORNS mode (2026-11-09). KEYBOARD and FIXED VEL work
  in NORNS mode.
- **KNOB 4/8: built 2026-11-09.** KNOB 4 (left, Instrument) and KNOB 8
  (right, Effect) set norns' reverb return; with SHIFT, its output level.
  One step = 1% of the parameter's range. Works on the MK3. At the bottom
  the reverb switches off. Nothing shows the value yet (norns' screen
  belongs to the script).
- STOP releases every note Machinista played on every norns (stuck notes).
- **MIDI layers: built 2026-11-09** (defaults agreed). DISPLAY 4 / 8 cycle
  native → MIDI 1 → 2 → 3. On a MIDI layer, DISPLAY 1–3 / 5–7 are toggles
  (CC 127/0, lit while on) and KNOB 1–3 / 5–7 send CC values 0–127, on MIDI
  channel 1 to that side's norns: layer 1 = CC 102–107, layer 2 = 108–113,
  layer 3 = 114–119 (keys, then knobs). The label rows above and below the
  norns screen show the layer, the keys and the knob values. Layer and
  values belong to the norns instance, kept in `config/norns-layers.json`.
  KNOB 4/8 stay reverb/level on every layer. Map the CCs to script
  parameters in norns' PARAMS > MAP. Works on the MK3 (2026-11-09): a
  MIDI 1 knob mapped to the reverb's mid time through PARAMS > MAP.
- **MIDI 1 is the same everywhere (2026-11-09, user's spec):** the bridge
  mod (`lib/layers.lua`) applies layer 1 to norns' own reverb and
  compressor, whatever script runs: keys LF 200 Hz/1 kHz, HF damping
  6/20 kHz, compressor attack/release 5/50 ms ↔ 80/300 ms; knobs reverb mid
  time, one-knob compressor (off at the left, then mix 0→1, ratio 1→20,
  threshold 0→−40 dB, post gain 0→30 dB), reverb send (engine + softcut,
  Claude's pick). Layers 2/3 come from `maps/<script>.map` per script. The
  mod writes the names to `layers.txt` next to the screen frame and the
  MK3 shows them instead of CC numbers. The CCs still reach the script, so
  PMAP keeps working.

**Notes:**
- Pads as MIDI: the Instrument's MIDI port can carry them, the same path as
  the clock.
- MIDI layers: norns maps MIDI CC to any script parameter through its own
  PMAP (learned per script, saved with the script's data). Default per-script
  maps could ship with the library.
- KNOB 4/8: norns system parameters (reverb, compressor, levels) are
  reachable over OSC, independent of the script.
- **PARAMS and LOAD from the MK3: on hold (2026-11-09).** The Pi 4 add-on
  drew the running script's PARAMS on the MK3 (one knob per parameter,
  page buttons between pages) and had a LOAD page (script + PSET, one
  button). The user isn't sure it fits next to two norns screens and the
  MIDI layers; norns' own menus (K1 → PARAMS, SELECT) work from the MK3
  meanwhile. Reuse `machinista-norns` (norns-mod/machinista) when it comes
  back.
- **Decision needed:** what each layer shows on the display, and which
  system parameters KNOB 4/8 control.

## 4. norns tape into Machinista's sampler
**Wish:** a recording made on norns' tape lands in Machinista, ideally
straight onto a pad or Sound as a loop or sample, at least in the sample
library.

**Built 2026-11-09 (agreed: a folder in the sample library first):** each
norns' tape folder is `samples/norns-tape/<n>` in Machinista's sample
library (`run-norns.sh` mounts it over norns' `dust/audio/tape`). A
recording shows in Machinista's sample browser (SD CARD → norns-tape → n)
and loads onto a pad like any sample; norns' TAPE menu still plays it.
norns writes 48 kHz 24-bit stereo WAV, which Machinista reads. Works on
the MK3 (2026-11-09): recorded on norns 1, loaded onto a pad.
- In norns' TAPE menu, K3 starts, pauses and resumes; the file is only
  finished (and loadable) after K2 → "unload". A paused recording shows in
  the browser but won't load.
- Later (user's wish 2026-11-09): a finished norns recording goes by itself
  onto the first free pad of the Sound, as a loop (loop on), and starts
  playing. Still open: trimming to bars, and which Sound when the norns is
  an Effect.

**Notes:**
- The Pi 4 add-on already shared folders: norns saw Machinista's samples,
  and tape files landed in Machinista. Here that becomes a Docker volume.
- Automatic placement on a pad needs a rule: which pad, what happens to the
  pad's current sample, whether the loop is trimmed to bars (clock from 1
  makes that possible).
- **Decision needed:** folder only first, or straight to a pad.

## 5. Norns Station
**Wish:** the fork becomes **Norns Station**: Machinista as an environment
for a bunch of norns, for experimental music (ambient, noise, dark
trance/techno), played as one instrument among others. Default Sounds get a
Norns Instrument and a Norns Effect; other synths may go; effects stay.
Its look and behavior can change.

**Notes:**
- This changes the starting point for 1–4: NORNS mode could become the main
  view rather than a takeover mode, and a new Sound could start on its own
  norns instance automatically.
- Likely low-hanging fruit:
  - Rename (product name, display, WebUI, docs).
  - New Sound = Norns Instrument on a free instance; instances start and
    stop with the Sounds that use them (an instance pool).
  - Show the norns screen by default when a Sound with a norns is selected.
- Keep the fork mergeable with upstream for as long as that helps, or
  decide to let it diverge.
- **Decisions needed:** how far to diverge from upstream, and whether
  NORNS mode becomes the default view.

## Smaller open items
- A blocked plug-in (its number taken by another Sound) is silent or dry
  without saying so. Show it on the display?
- Edge-case defaults (only a Norns Effect on a Sound, several Effects) are
  proposed, not confirmed.
- CPU measurement with heavy scripts (granular, loopers) once the library
  is in.
- Merge beta 18 into the fork.

## Suggested order
1. Script library (2): almost everything else needs real scripts to test,
   especially effects and per-script mappings.
2. Clock (1) and MIDI out (2b): both need MIDI between Machinista and the
   containers, so they share the transport.
3. Pads as MIDI and the KNOB 4/8 controls (3), then the layers.
4. Tape into Machinista (4).
5. Norns Station (5) runs alongside: decide the direction early, since it
   changes how 3 and 4 should look; rename and defaults can come any time.
