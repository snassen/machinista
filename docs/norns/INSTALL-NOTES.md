# Install notes: Machinista + norns on a Raspberry Pi 5

Raw material for the install documentation and an unattended installer.
Each step records what was done, the commands, what went wrong, and whether a
person has to decide something (**DECISION**) or physically act (**HANDS**).
Everything else is a candidate for automation.

Reference run: 2026-11-08, Raspberry Pi 5 Model B Rev 1.0 (8 GB), 1 TB NVMe,
Maschine MK3, Machinista beta 17 image, norns-lab `7cc4f0e`.

`<ip>` below is the Pi's IPv4 address on the local network.

---

## 0. Prerequisites
- Pi 5, a power supply, an SD card, Ethernet to a router with internet.
- **Power supply:** with a non-official supply the kernel logged
  "Undervoltage detected" 3× within 25 s of boot (`throttled=0x50000`), and
  the Pi limited USB current (`usb_max_current_enable=0`). Use the official
  27 W (5 V/5 A) supply. *Installer:* check `vcgencmd get_throttled` and
  `dmesg | grep -i undervoltage` and warn, but don't block.
- Maschine MK3 with its own power supply (externally powered in the
  reference run).

## 1. Write the Machinista image (HANDS)
- Raspberry Pi Imager → Use custom → Machinista `.img.xz` → SD card. Skip
  Imager's customisation; the image brings its own account (`machinista`) and
  network setup.
- **Docs:** upstream `INSTALL.md` and `README.md` linked different beta
  releases. Always point at the latest release.

## 2. Boot from SD on a Pi 5 that normally boots NVMe
- Check: `rpi-eeprom-config | grep BOOT_ORDER`, read right to left (1 = SD,
  6 = NVMe, 4 = USB, f = restart). `0xf461` means SD first.
- If NVMe comes first: `sudo rpi-eeprom-config --edit` →
  `BOOT_ORDER=0xf461`.
- Machinista is headless: an attached HDMI or touch screen stops at the
  systemd log ("Reached target Graphical Interface"). That is expected, not a
  hang. **Docs:** say so explicitly.

## 3. Find the Pi and enable SSH (HANDS)
- The Pi gets the same DHCP address as its previous OS (it follows the MAC
  address).
- `machinista.local` collides when another Machinista is on the network, and
  on macOS it resolved to IPv6 first, where port 22 failed. Use the IPv4
  address. *Installer:* consider a unique hostname (`machinista-<serial4>`).
- SSH is off by default: WebUI `http://<ip>:8080` → System → SSH. This can't
  be automated from outside unless the WebUI's endpoint is called directly
  (to be checked).
- Installing a key from a non-interactive session (password prompts don't
  reach it):
  ```bash
  SSH_ASKPASS=<script that prints the password> SSH_ASKPASS_REQUIRE=force DISPLAY=:0 \
    ssh-copy-id -i ~/.ssh/id_ed25519.pub machinista@<ip> </dev/null
  ```
- Switching between an NVMe OS and an SD OS on the same IP changes the host
  key: run `ssh-keygen -R <ip>` first.
- **Security TODO (DECISION):** the image's default password stays active.
  An installer should change it or disable password login after installing
  the key.

## 4. Firmware
- `sudo rpi-eeprom-update`, then `sudo rpi-eeprom-update -a` and reboot. In
  the reference run: 2025-05-08 → 2026-10-30. "Up to date" on an older OS
  only compares against that OS's firmware package; Machinista's Debian
  trixie had a newer one.
- Non-interactive `sudo` needs the password on stdin (`sudo -S`).

## 5. Move the system from SD to NVMe (DECISION: wipe NVMe)
Cloning the running system (rather than writing a fresh image) keeps SSH
enabled and the installed key. Script: `clone-to-nvme.sh` (below), run as
root, about 1 minute for 4.6 GB.
1. New random DOS disk id, so SD and NVMe never share PARTUUIDs.
2. Same layout as the image: p1 512 MiB FAT32 at sector 16384, p2 the rest as
   ext4 (whole disk; no first-boot growth needed).
3. Stop `machinista` and `machinista-web`, `rsync -aAXHx --numeric-ids /` and
   `rsync -rt /boot/firmware/`, restart the services.
4. Rewrite `PARTUUID=` in the NVMe's `/etc/fstab` and `cmdline.txt`.
5. Remove leftover `pieeprom.upd`/`recovery.bin` from the copy.
6. Power off. **HANDS:** remove the SD card, power on. With BOOT_ORDER
   `0xf461` and no card it boots NVMe. The SD card remains a fallback.

Machinista's `tools/firstboot.py` resize logic is device-agnostic, so a fresh
image written straight to NVMe also works (but loses SSH and the key).

## 6. Audio with the MK3
- The MK3 on a USB 3 port is detected as HID and as ALSA `card 0: MK3`
  (4 out / 2 in, 48 kHz, S32_LE). Interface AUTO selects it.
- AUTO buffer gave 960 frames / 240 period (20 ms). Lowered to **128 frames /
  64 period (≈2.7 ms)**: no audible dropouts in a light test, not yet tested
  under heavy load. The engine counts xruns internally (`dsp_status`), but
  the count doesn't reach the journal. *Installer/diagnostics:* expose it.

## 7. Docker on Machinista's Debian trixie
```bash
sudo apt-get install -y --no-install-recommends docker.io docker-buildx containerd docker-cli
sudo usermod -aG docker machinista   # new sessions only; use `sg docker -c …` meanwhile
```
**Gotcha:** `docker.io` on trixie doesn't include the CLI. Without the
separate `docker-cli` package you get "docker: not found".

## 8. norns runtime image
- Copy norns-lab to the Pi (rsync from a workstation avoids storing GitHub
  credentials on the Pi), then run `bash scripts/smoke-runtime.sh`.
- The build compiles libmonome, nng and norns natively on the Pi 5. Build time
  was not measured; wrap it in `time` next run.
- **Gotcha (fixed in norns-lab `7cc4f0e`):** jackd died with `Bus error` and
  `Cannot lock down … memory` under Docker defaults. The container needs
  `--shm-size=256m --ulimit memlock=-1:-1 --ulimit rtprio=95 --cap-add SYS_NICE`.
- Result: JACK (dummy driver), sclang and matron start; Awake loads; PolyPerc
  registers; a screen frame is exported. Machinista kept running throughout.

## 9. Machinista fork and updater
- Fork: `gh repo fork photogeen/machinista --clone` → `snassen/machinista`,
  with remote `upstream` = photogeen. The fork is public, so commits use the
  GitHub noreply address as `user.email`.
- Branch `norns-mode` starts at tag `v0.1.0-beta.17` (`4a88106`), exactly what
  the Pi runs (`source_commit` in `BETA-MANIFEST.json`). Python-only changes
  therefore need no native rebuild.
- Machinista's updater would overwrite patched files, so it is disabled
  (DECISION, made):
  ```bash
  sudo systemctl disable --now machinista-updater
  ```
  It is an on-demand service started from the WebUI, not a timer.

## 10. norns frame export and OSC input
- **Screen out:** the norns mod `machinista_bridge`
  (`norns/mod/machinista_bridge/lib/mod.lua`) exports the native framebuffer
  to `/frames/screen.png` every `NORNS_FRAME_EXPORT_MS` (default 100).
  - `matronrc.lua` is the wrong place for this: matron's C config evaluates it
    in a separate Lua state (`error evaluating matronrc.lua`, no `metro`).
  - Mods are enabled with `dust/data/system.mods` in `tab.save` format
    (see `norns/data/system.mods`). A plain list crashes startup in
    `tabutil.load`.
  - A script metro (1–30) dies at startup because script load/clear calls
    `metro.free_all()`. The mod uses reserved `metro[34]` (33 and 34 are
    unused by core at norns `42df844`; 31, 32, 35 and 36 are taken).
- **Input in:** matron's OSC `/remote/key n z` and `/remote/enc n d` on UDP
  10111 (`lua/core/osc.lua`), published per container on 127.0.0.1 (norns A:
  10111, norns B: 10112).
- Verified on the Pi 5: frames refresh, and OSC E1/K2 visibly changed the
  norns menu in the exported frame.
- Containers are started with `norns/run-norns.sh A|B`. `-i` keeps stdin open;
  without it the runtime's REPL sees EOF and exits.

## Open items for an unattended installer
- Enabling SSH without the WebUI (or calling the WebUI endpoint).
- Unique hostname per device.
- Password change or key-only SSH (**DECISION**).
- Power-supply check with a clear warning.
- Measure and log build duration; prebuild and pull an ARM64 norns image
  instead of compiling on every Pi.
- Audio bridge between norns' JACK and Machinista's ALSA engine (open design).

## clone-to-nvme.sh (as run)
```bash
#!/bin/bash
set -euo pipefail
D=/dev/nvme0n1
[ -b $D ] || { echo "no nvme"; exit 1; }
findmnt -rn -o SOURCE | grep -q nvme0n1 && { echo "nvme mounted, abort"; exit 1; }
ID=$(od -An -N4 -tx4 /dev/urandom | tr -d ' ')
wipefs -a ${D}p1 ${D}p2 2>/dev/null || true
wipefs -a $D
printf 'label: dos\nlabel-id: 0x%s\nunit: sectors\nstart=16384, size=1048576, type=c\nstart=1064960, type=83\n' $ID | sfdisk --quiet $D
partx -u $D || true; sleep 2
mkfs.vfat -F 32 -n bootfs ${D}p1 >/dev/null
mkfs.ext4 -q -F -L rootfs ${D}p2
mkdir -p /mnt/nv; mount ${D}p2 /mnt/nv
mkdir -p /mnt/nv/boot/firmware; mount ${D}p1 /mnt/nv/boot/firmware
systemctl stop machinista machinista-web || true; sync
rsync -aAXHx --numeric-ids / /mnt/nv/
rsync -rt /boot/firmware/ /mnt/nv/boot/firmware/
systemctl start machinista machinista-web || true
sed -i "s/PARTUUID=819ae7c4-/PARTUUID=$ID-/g" /mnt/nv/etc/fstab /mnt/nv/boot/firmware/cmdline.txt
rm -f /mnt/nv/boot/firmware/pieeprom.upd /mnt/nv/boot/firmware/recovery.bin
umount /mnt/nv/boot/firmware /mnt/nv
```
The source PARTUUID prefix (`819ae7c4`) is the image's and is hard-coded
here. An installer must read it from the running system's `cmdline.txt`.
