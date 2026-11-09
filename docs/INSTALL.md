# Get started with Machinista

![Machinista connection diagram](../assets/setup/connections-en.svg)

Machinista runs on the **Pi**, not inside the controller. No controller firmware
is replaced; reconnect USB to your computer to return to your original software.
Maschine+ also needs an external Pi and must be in Controller mode.

## Before you begin

You need a Raspberry Pi 4 or 5, its power supply, an SD card of at least 8 GB,
a supported controller, and an audio device for headphones or speakers.
On MK3 / Maschine+, the built-in audio interface can be your audio device: use
the controller’s headphones or line outputs. Mikro / MK1 / MK2 need a separate
audio device. An audio device can be a compatible USB interface or a supported audio board
attached to the Pi (often called a HAT). A USB stick is optional.

The **image** is one ready-made system file. It contains Machinista and the
operating system, so you do not need to install or compile anything separately.
Use a spare SD card: writing the image erases the card you choose.

## Prepare the SD card on your computer

1. Download the `.img.xz` file and `SHA256SUMS` from the
   [current beta release](https://github.com/photogeen/machinista/releases/tag/v0.1.0-beta.18).
   The public image includes Machinista Synth sounds, but no drum sample pack
   or third-party plug-ins. Private tester editions list their extras separately.
2. Open Raspberry Pi Imager. Choose **Use custom** and select the `.img.xz` file.
   You can use the compressed file directly.
3. Choose your SD card. Check that it is the card you intend to erase.
4. Keep the image's prepared account and network settings. Do not add different
   usernames, passwords or Wi-Fi details in Imager's customization dialog.
5. Write the card and let Imager finish its verification. Eject the card safely.

`SHA256SUMS` contains file checksums: these let you check that a downloaded file
is complete and unchanged. Imager's verification separately checks the written
card. If you are unsure about checking a checksum, use a trusted download and
always let the card verification finish.

## Connect and switch on

1. With the Pi powered off, insert the card and connect the controller by USB.
   Connect your audio device and headphones or speakers. Connect any HAT only
   while power is disconnected.
2. Power the Pi. Allow about two minutes on the first start. It may restart once
   while preparing the card. The controller should then show Machinista.
3. Choose **AUTO** for the audio interface in Settings > AUDIO > INTERFACE, or
   choose your connected device. Set a comfortable listening volume. Your
   controller manual shows the exact settings buttons for your model.
4. Leave sample rate and buffer settings at their prepared values for the first
   test. MAIN OUTPUT selects the output pair sent to your speakers/headphones.

## Play a first sound

1. Select an empty pad in normal pad mode. Open BROWSE and choose Sounds.
2. Open Machinista Synth, choose a bank, choose a patch and use LOAD. A bank is a
   collection; a patch is one ready-made sound. Loading puts it on the selected pad.
3. Turn on KEYBOARD and play the pads. On controllers with a KEYBOARD button,
   use that button; otherwise hold SHIFT and press PAD MODE. The pads now play
   different notes of the same sound. Keep REC off while trying it.
4. Use the Pattern recording chapter of your manual when you want to record
   your playing. Save your project afterwards.

## Open the browser page

The **WebUI** is a local browser page for uploading samples, managing Sounds and
backing up projects. It works on a phone, tablet or computer; no extra app is needed.

- **Already on your home network:** connect your phone/computer to that network
  and open http://machinista.local:8080. Ethernet works too.
- **Not connected to a router:** find the Wi-Fi network `Machinista-XXXX` (the
  final four characters identify your Pi), connect with password `machinista`,
  then open http://10.42.0.1:8080. This Wi-Fi connection may say it has no internet;
  the local page still works.
- **Join your home Wi-Fi:** select your router in the WebUI Wi-Fi settings and
  enter its password. Afterwards, reconnect your phone/computer to your home
  network and open http://machinista.local:8080 again. If the router connection
  is lost, Machinista can return to its hotspot.

The WebUI has no login. Use a trusted home/studio network. The prepared system
account is `machinista`, with initial password `machinista`. SSH is remote
technical access; it starts disabled and is not needed for normal music making.

## Keep your work safe

Save projects and download backups through the WebUI. Keep the boot SD card in
place while the Pi is running. To move samples, use the browser page or a USB drive.
Shut down through System > Power or the WebUI before disconnecting power.
Never remove or attach a HAT while powered.

## Later updates

Use System / WebUI > Updates for an existing installation. **Beta** offers the
testing versions; **Release** offers a stable release when one is available.
An empty Release channel does not mean an update has been installed. Stop
playback and recording before installing an update. Back up important projects.
You do not need to write a new SD card for each normal update.

## If you cannot hear anything

Check the selected audio device and MAIN OUTPUT, then its output/headphone level
and mute controls. Check MUTE/SOLO on the controller too. Try the built-in synth
before troubleshooting your own sample. For model-specific controls, use your
[controller manual](USER_MANUALS.md).

This is a beta. A new Pi, controller or audio interface still needs a real-world
test for boot, sound, reconnect and networking; automated tests cannot prove
that every hardware combination works.
