# Script pack in containers: test results

Tested 2026-11-08 on the Pi 5 with `norns/library/test-scripts.py`, on a
spare instance (norns 5, not used by any Sound) while norns 1–4 ran Awake
and Machinista played. Each script was loaded through the REPL, left to
settle for 8 s and measured for 10 s.

**CPU** is the whole container (matron, SuperCollider, crone, the bridge
daemon) in percent of one core; the Pi 5 has four. An instance with no
script uses about **6%**. Scripts were measured right after loading, without
playing them, so busy scripts can use more while played.

**Result: all 45 load without errors.** cheat_codes_2 needs at least one
MIDI device to start; it loads since each norns has its virtual MIDI device
(DESIGN.md, MIDI).

| Script | CPU % | Engine | Notes |
|---|---:|---|---|
| bloom | 23.7 | Bloom | |
| terrarium | 23.5 | Terrarium | mi-UGens |
| l_ll__l_ | 22.2 | EmissionSpectrum | |
| orgn | 21.6 | Orgn | |
| carters-delay | 21.1 | CartersDelay | processes audio input |
| wrms | 20.4 | | processes audio input |
| mangl | 18.6 | MGlut | |
| overwintering | 18.3 | Oystercatcher | |
| orca | 16.1 | Timber | |
| amen | 15.6 | Amen | |
| flora | 15.1 | BandSaw | |
| granchild | 15.0 | ZGlut | |
| takt | 14.6 | Timber_Takt | |
| sines | 14.1 | Sines | |
| otis | 13.8 | Decimator | processes audio input |
| cheat_codes_2 | 13.8 | PolyPerc | needs a MIDI device |
| silos | 13.4 | Thresher | |
| mlre | 13.2 | | processes audio input |
| stwnsh | 12.4 | | |
| fall | 12.1 | Autumn | |
| constellations | 11.7 | PolyPerc | |
| raindrops | 11.5 | Snowflake | |
| haven | 11.4 | Haven | |
| concrete | 11.0 | | |
| oooooo | 10.7 | SimpleDelay | processes audio input |
| reels | 10.4 | | processes audio input |
| nc01-drone | 10.3 | | |
| glaciers | 10.2 | Glacial | |
| eterna | 10.0 | Eterna | |
| compass | 9.6 | | |
| mlr | 9.2 | | processes audio input |
| awake | 8.8 | PolyPerc | |
| barcode | 8.8 | | |
| _awed | 8.6 | Sawed | |
| grd | 8.6 | Grd | |
| cranes | 7.7 | | processes audio input |
| ufo | 7.4 | SupSawEV | |
| delar | 7.4 | DelarSequencer | |
| colorwheel | 7.3 | | |
| timber | 7.0 | Timber | |
| pixels | 6.8 | Pixelbangs | |
| dreamsequence | 6.7 | | sequencer (MIDI and others) |
| nameless-nightmare | 6.2 | Nameless_Nightmare | |
| tapedeck | 6.2 | | processes audio input |
| dronecaster | 5.2 | Dronecaster | |

"Processes audio input" marks well-known input processors (delays, loopers,
tape), the natural candidates for the Norns Effect slot. Scripts without an
engine use softcut, norns' built-in tape/looper.

## What this means for instance count
- Even the heaviest script here costs about a quarter of one core, so eight
  instances (the current maximum) with heavy scripts would use about half
  the Pi 5. Light scripts (sequencers, Awake) cost 1–3% above an idle
  instance.
- Memory: each instance takes about 250–300 MB; the Pi 5 has 8 GB.

## Fixed on the way
- **version.txt:** norns reads its version from `~/version.txt`. The image
  had none, so norns reported "000000" and dreamsequence, mlre and
  cheat_codes_2 refused to load. The image now writes 260819 (v3.0.2; the
  pinned norns is newer).
- Errors in flora and tapedeck in the first run came from clocks left over
  by the previous script; both pass on their own. Running the whole pack
  in one go can show such follow-on errors, so failures are retested alone.

## How to rerun
```bash
norns/run-norns.sh 5
norns/library/test-scripts.py 5              # every script
norns/library/test-scripts.py 5 otis mlr     # only these
norns/run-norns.sh stop 5
```
