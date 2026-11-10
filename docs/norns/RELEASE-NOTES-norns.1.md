# norns for Machinista, first release (v0.1.0-beta.19-norns.1)

An independent, unofficial fork of [Machinista](https://github.com/photogeen/machinista). It runs the real monome norns (matron, crone, SuperCollider and unchanged community scripts) in Docker next to Machinista on a Raspberry Pi, played from a Maschine MK3. It isn't made or supported by photogeen or monome. Questions and bugs about the norns parts go to this repository's [Issues](https://github.com/snassen/machinista/issues) and [Discussions](https://github.com/snassen/machinista/discussions), not to upstream Machinista.

## What you need
- **A Raspberry Pi 5 (8 GB) or Pi 4** running the official **Machinista 0.1.0-beta.19** image. The fork only deploys onto that exact version.
- **A Maschine MK3.**
- **A computer with git and SSH** to put the fork on the Pi.

## What it does
- **Norns Instrument and Norns Effect:** two LV2 plug-ins. They bring a norns instance's audio into a Sound and pass the Sound's notes to it, or send the Sound's audio through a norns and back. Several instances can run at once, so norns can feed norns.
- **NORNS mode (SHIFT + PLUG-IN):** the selected Sound's norns screens on the MK3 displays, with K1–K3 and E1–E3 on the display buttons and knobs. There are three MIDI layers for reverb, compressor and per-script controls.
- **Clock and transport follow Machinista:** scripts wait for PLAY, and STOP releases held notes.
- **About 236 community scripts:** each tested automatically for load errors and CPU, and grouped into folders in SELECT.
- **One-button loop recording (SHIFT + REC in NORNS mode):** records a Sound with its norns onto an empty pad as a synced loop.
- **Tape:** norns TAPE recordings land in Machinista's sample library.

## Install
1. **Put the fork on the Pi.** From a checkout of the `norns-mode` branch, run `tools/deploy-fork.sh machinista@<pi>`.
2. **Get the ready-made norns image** instead of compiling it:
   ```bash
   docker pull ghcr.io/snassen/norns-station:v0.1.0-beta.19-norns.1
   docker tag ghcr.io/snassen/norns-station:v0.1.0-beta.19-norns.1 norns-station
   ```
3. **Follow the "Quick start" in `docs/norns/README.md`.** It covers the script pack, the instances, the plug-in upload and the boot service.

[`docs/norns/INSTALL-NOTES.md`](https://github.com/snassen/machinista/blob/norns-mode/docs/norns/INSTALL-NOTES.md) has the full reference installation, including Docker and the MIDI kernel module.

## Known limits
- **Installation is manual.** There's no one-command installer yet.
- **Quiet line input:** a physical norns plugged into the MK3's line inputs needs a lot of gain.
- **Automation:** norns script parameters can't be recorded as Machinista automation yet. The plug-ins' Gain and Mix should work like any plug-in parameter, but that hasn't been tested yet.
- **Machinista updates:** after every update to Machinista itself, the fork has to be deployed again.
- **Pi 4:** runs the fork, but has been tested less than the Pi 5.

## License
GPL-3.0-or-later for the fork's own code, like Machinista. Each norns script keeps its own licence.
