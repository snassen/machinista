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

**Notes:**
- norns clock sources: internal, MIDI, Link and crow. Scripts written with
  `clock.sync` follow whichever is selected; start/stop reaches scripts
  through `clock.transport.start/stop`.
- Two routes:
  - **MIDI clock:** the Norns Instrument already has a MIDI input that is
    unused today. Machinista would send clock ticks, start and stop through
    the bridge (or a virtual MIDI port in each container), and each norns
    sets its clock source to MIDI. It works with any script that uses the
    norns clock.
  - **Ableton Link:** norns supports Link with start/stop sync. Machinista
    would have to join a Link session. A bonus: it would also sync with
    other gear and laptops, which fits playing Norns Station alongside other
    instruments.
- Either way, the clock source should be set automatically when an instance
  starts, so nothing is set by hand.
- **Decision needed:** MIDI clock, Link or both.

## 2. Script library
**Wish:** the scripts prepared for the Pi 4 are installed on every norns.

**Notes:**
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

**Notes:**
- Pads as MIDI: the Instrument's MIDI port can carry them, the same path as
  the clock.
- MIDI layers: norns maps MIDI CC to any script parameter through its own
  PMAP (learned per script, saved with the script's data). Default per-script
  maps could ship with the library.
- KNOB 4/8: norns system parameters (reverb, compressor, levels) are
  reachable over OSC, independent of the script.
- Still open: where script PARAMS and LOAD fit (D3).
- **Decision needed:** what each layer shows on the display, and which
  system parameters KNOB 4/8 control.

## 4. norns tape into Machinista's sampler
**Wish:** a recording made on norns' tape lands in Machinista, ideally
straight onto a pad or Sound as a loop or sample, at least in the sample
library.

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
2. Clock (1).
3. Pads as MIDI and the KNOB 4/8 controls (3), then the layers.
4. Tape into Machinista (4).
5. Norns Station (5) runs alongside: decide the direction early, since it
   changes how 3 and 4 should look; rename and defaults can come any time.
