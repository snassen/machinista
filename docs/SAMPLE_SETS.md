# Sample Kits & Expansions

Open the **Sample Kits** tab in the WebUI and choose **Storage**. Imports, new kits and folders go to the selected SD or USB drive. USB kits are stored in `Machinista Sample Kits` on that drive. It is separate from Sounds:
Sounds holds playable instruments and synth patches; Sample Kits holds kits and
expansions with banks of 16 pad Sounds.

## Build your own kit

1. Choose **+ New** and enter a set name.
2. Drag audio files from your computer onto a pad. Several files fill successive
   pads, starting at that pad; additional banks are created when necessary.
   Confirm before replacing occupied pads. Pad 1 is at the bottom left,
   matching the controller.
3. Alternatively select a pad and choose **Choose sample** to use samples already
   on the Pi's SD card or USB drive. Click a sample in the picker to assign it.
4. Click a loaded pad to preview its sample through your browser device. This
   does not play or record notes in the running Pi project. Use **Stop preview**
   or the audio player to stop playback. A layered pad previews its first sample;
   this is not a rendering of its complete effect chain or velocity layers.
5. Drag pads to swap their assignments. Rename the selected sample using the
   field below the grid. Use **+ Bank**, **Rename** and **Remove bank** to arrange
   the set. Each bank has its own 4×4 grid.
6. Choose **Save kit**. **Save copy** makes a separate set. Saved sets and
   expansions appear in the list at the left; click one to view/edit its banks.
   **Download ZIP** creates a portable backup. **Delete** always asks first.

The editor keeps unsaved changes while switching WebUI tabs. Changing to another
set or importing a pack asks before discarding edits. Saved Group presets from
the controller also appear in this tab and can be edited and downloaded.

## Import a folder or expansion

Drop an installed sample/expansion folder onto the import area, or use
**Import folder**. The folder name becomes the set name. Audio files are sorted
by their relative path and divided into banks; distinct sample subfolders become
separate banks. Dropping a folder on a pad instead fills pads from that position
and uses the folder name for an unnamed new set.

Use **Import ZIP / XPN** for an archive:

| Input | Result |
| --- | --- |
| Machinista sample kit ZIP | Restores its named banks, pads and portable sample state. |
| Existing Machinista Group ZIP | Imports the saved Group as a single-bank set. |
| MPC XPN, ZIP or installed folder | Reads the name from `Expansion.xml` when present. Drum `.xpm` programs keep their numbered pad positions, banks and velocity sample layers. Missing/ambiguous sample references stop the import rather than silently mapping the wrong sample. |
| Maschine Group (.mxgrp) | Drop a kit in Sample Kits to open an editable 4×4 draft. WAV pads keep their order and close up around skipped sounds. Select **Save kit** to keep the kit. |
| Maschine expansion folder containing .mxgrp files | Imports each kit as a separate saved set inside the expansion folder in the WebUI and controller browser. Keep the `Groups` and `Samples` folders together. Unsupported kits and missing WAVs are listed after import. |
| Maschine audio folder or ZIP | Converts readable audio and groups it by sample folder. Its folder/archive name becomes the expansion name. For kit mappings, drop the unpacked expansion folder or an individual .mxgrp file. |
| Generic audio folder or ZIP | Creates a named set with sequential 16-pad banks. |

WAV, AIFF, FLAC, MP3 and OGG audio is copied/converted into collected PCM WAV
files. The audio converter runs with one low-priority worker process. MPC
keygroup audio remains available as unassigned samples; keygroup instrument
mapping is not reproduced. MPC layer stacking/round-robin, tuning, effects and
patterns are not reproduced. **Import details** reports these limitations.

Supply the already installed content, not an EXE/PKG/ISO installer. Protected
NKI/NKX/NCW content is not decoded. Synth presets and plug-in binaries are not
installed by this importer.

For a single Maschine kit, Machinista looks for the referenced WAVs on its
accessible SD or USB storage. If the samples are on your computer, choose
**Locate expansion samples** and select the expansion folder containing
`Samples`. Only the referenced audio is uploaded. Synth-only sounds are
skipped. A pad with multiple WAVs uses its first WAV. Layers, slices, patterns,
effects and synth presets are not transferred. Unsupported Group layouts
are reported before the kit is opened.

Vendor structure references:
[MPC expansion creation](https://support.akaipro.com/en/support/solutions/articles/69000857886-mpc-2-desktop-and-standalone-create-your-own-expansion-packs),
[Maschine expansion content](https://support.native-instruments.com/support/solutions/articles/69000879600-how-to-load-an-expansion-in-maschine).
The converter reads sample metadata directly; it does not contain vendor code.

For a batch, each kit is saved individually. If the expansion includes a matching
`.previews/Kit.mxgrp.ogg` file, use **Preview** next to the kit in the WebUI or **PREH**
while highlighting the kit in the controller browser. **Locate expansion folder** also adds the preview and images to an individually imported kit. If the browser omits the hidden preview folder, use **Attach preview** to choose the OGG directly. The MK3 right display shows the imported artwork and logo while highlighting the kit. Only WAVs referenced by the kit
are uploaded, and the 1 GiB transfer limit applies per kit. An import that
fails for one kit leaves other successfully imported kits available.

Use **New folder** in Sample Kits to organize your own kits. Select the
folder when saving a new kit. Open a folder to find **Delete folder**, or
select a kit and choose **Delete kit**. Both actions ask for confirmation
and permanently delete the selected content.

## Load on the controller

Open **BROWSE → SAMPLE KITS**, choose SD or USB, then choose a kit and press **LOAD**. Kits with multiple banks open a bank list first.
A legacy single-bank Group can be loaded directly. Stop PLAY/REC first. Loading
replaces the selected Group's Sounds and Group processing; existing Patterns
remain. Use **SAVE GROUP** first if you want to keep the current Group's Sounds.
The normal preset undo flow remains available.

Uploading or editing a set in the WebUI does not change the running project.
For project portability, collect its referenced assets when saving/exporting it.
When editing a set, older collected samples are retained at their original paths
for projects that still reference them. Deleting a set removes it from the
catalog/controller browser and permanently removes its bundle;
projects referring to that removed set should have their samples collected first.

## Load a single expansion sample

Open **BROWSE → SD CARD or USB → EXPANSION SAMPLES → expansion → kit**.
Choose a WAV and press **LOAD** to assign it to the selected pad. **PREH**
auditions the highlighted WAV. Use **SAMPLE KITS** when you want to load the
whole kit instead.

## Storage and limits

SD kits are stored in `presets/Groups`. New sets have stable internal IDs, a
`Set.json` bank index and one portable `Preset.json` Group per bank. Existing
single-Group presets remain compatible. Editing uses revision checks and a
staged replacement to prevent stale browser tabs from overwriting newer edits.

Limits: 128 banks / 2,048 pads per set, 1 GiB per archive/folder and expanded or
saved bundle, 8,192 archive entries. Symbolic links, path traversal, duplicate
archive paths and encrypted archives are rejected. Transfers reserve free disk
space; interrupted imports do not publish partial sets. Unfinished browser
uploads are temporary and expire after 24 hours. Plug-in binaries are never
included in exports. Use converted commercial content according to its license.

If the browser omits hidden files during folder import, import a ZIP that contains
`.previews`. For kits already saved in an expansion folder, drop a ZIP named
after the expansion and containing its `.mxgrp.ogg` files to add the previews
in one pass.
