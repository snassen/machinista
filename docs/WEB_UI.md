# Machinista WebUI

Open http://machinista.local:8080 on the same network as the Pi. In hotspot mode,
join Machinista-XXXX with password machinista and open http://10.42.0.1:8080.
The WebUI intentionally has no login. The service is machinista-web.service.
All interface assets are local; no external packages or CDNs are loaded.

- **Samples:** browse SD/USB folders, preview audio, create folders and upload WAV
  or MP3 files. MP3 and floating-point WAV uploads are converted to sampler PCM.
  Existing files are never overwritten. Move selects another destination folder;
  Delete permanently removes the selected items after confirmation.
- **Sounds:** create multisample instruments, edit key/velocity zones, save the
  selected live LV2 Sound and plug-in strip, or run the Autosampler. See
  SOUNDS_AND_AUTOSAMPLER.md for English/German workflows on WebUI and controllers.
  Each Sound has a confirmed Delete action, including generated bank patches.
  Deleted bank entries stay hidden after refresh/restart. The original bank and
  assets used by existing projects remain; recovery links are in `presets/Sounds/.trash`.
- **Sample Kits:** a dedicated kit/expansion editor with named banks and a 4×4 pad grid. Drop samples onto pads, swap pads, preview with a click, and save named kits. Import folders, ZIPs, MPC XPN/XPM sample mappings and installed Maschine audio folders; synth presets and protected content are skipped. Load saved banks through BROWSE > SAMPLE KITS on the controller. See [Sample Kits](SAMPLE_SETS.md) for the complete workflow and conversion limits.
- **Projects:** upload and download project archives with their sample assets.
  Delete is available for every project and always asks for confirmation. Deleting
  the loaded project opens an empty project; stop playback and recording first.
  Recovery manifests are kept under `projects/.trash`; sample/plugin assets remain.
- **Chords:** import MPC progression and Ripchord chord presets and edit mappings.
- **LV2 Plugins:** upload compatible compiled Linux ARM64 bundles, check them,
  list installed plug-ins and remove them. No plug-ins are bundled in the image.
- **System:** resource information, graceful restart/shutdown, SSH switch and
  Wi-Fi network selection. SSH is disabled initially on a fresh image.

Preview plays through the browser device. On the controllers, samples are played
by the Pi's selected audio interface. Read-only USB media can be browsed; uploads
need writable storage. Moving library files does not rewrite saved project
references. Back up projects before changing cards or reorganizing sample paths.

### Stem separation from the controller

The controller uses the same background job as the WebUI. In BROWSE, select a WAV/MP3 and choose STEMS (display button 7 on full-size controllers; SHIFT + F3 on Mikro). Sampling > Edit also offers STEM SEPARATION beside Truncate/Normalize. INSTALL sets up the optional local engine after confirmation; START separates the whole source file, with progress and CANCEL. OPEN opens completed files in SD CARD / Library / Stems. Originals and pad assignments are retained. Sources collected with a project are supported; arbitrary filesystem paths and symlinks are rejected. Existing 60-second/64-MiB, RAM and storage limits apply.

The controller browser hides the internal PROJECT ASSETS / PRESET ASSETS entries. FIND still locates a loaded project sample. Folder names have no leading slash or arrow; selection is shown with a highlight.
