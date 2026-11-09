#!/usr/bin/env python3
"""Configure an OFFLINE official Raspberry Pi OS root inside an ARM Linux VM.

Usage: python3 build_beta_image.py /mnt/pi /tmp/machinista-payload.tar.gz
The caller mounts the disposable image, /dev, /proc and /sys first.
Never point this script at the running root or an existing user's installation.
"""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tarfile

VERSION='0.1.0-beta.19'

def main():
 root=Path(sys.argv[1]).resolve();payload=Path(sys.argv[2]).resolve();profile_id=sys.argv[3] if len(sys.argv)>3 else 'standard'
 if profile_id not in ('standard','pi3b-sampler'):raise SystemExit('Unknown image hardware profile')
 if root==Path('/') or not (root/'etc/rpi-issue').exists():raise SystemExit('Requires an offline official Raspberry Pi OS root')
 def run(*args,**kw):return subprocess.run(['chroot',str(root),*args],check=True,text=True,**kw)
 # Package maintainer scripts must not start services in the build VM.
 policy=root/'usr/sbin/policy-rc.d';old=policy.read_bytes() if policy.exists() else None
 policy.write_text('#!/bin/sh\nexit 101\n');policy.chmod(0o755)
 try:
  run('apt-get','update','-qq')
  run('env','DEBIAN_FRONTEND=noninteractive','apt-get','upgrade','-y','--with-new-pkgs','--no-remove','-o','Dpkg::Options::=--force-confold')
  run('env','DEBIAN_FRONTEND=noninteractive','apt-get','install','-y','--no-install-recommends','ffmpeg','python3-venv','rubberband-cli','fdisk','openssh-server','libasound2t64','liblilv-0-0','libhidapi-hidraw0','libusb-1.0-0','libstdc++6','bluez','alsa-utils','python3-dbus','python3-gi','python3-libgpiod','python3-pil','fonts-dejavu-core','samba','smbclient','dnsmasq-base','avahi-daemon','network-manager')
 finally:
  if old is None:policy.unlink(missing_ok=True)
  else:policy.write_bytes(old)
 # The official base currently contains a locked pi account. Replace it.
 if subprocess.run(['chroot',str(root),'id','pi'],capture_output=True).returncode==0:run('userdel','--remove','pi')
 app=root/'home/machinista/Machinista';app.mkdir(parents=True,exist_ok=True)
 with tarfile.open(payload) as archive:archive.extractall(app,filter='data')
 # Development-only migration scripts target the original development account.
 for name in ('install_machinista_branding.py','install_lv2_web.py'):
  (app/'tools'/name).unlink(missing_ok=True)
 # Hardware maps are generic; recorded unit identity/evidence is development-only.
 mapping=app/'captures/maschine-mk2-hardware-map.json'
 if mapping.exists():
  data=json.loads(mapping.read_text());data.get('device',{}).pop('serial',None);data.pop('evidence',None)
  mapping.write_text(json.dumps(data,indent=2)+'\n')
 exists=subprocess.run(['chroot',str(root),'id','machinista'],capture_output=True).returncode==0
 if not exists:run('useradd','--create-home','--shell','/bin/bash','machinista')
 run('chpasswd',input='machinista:machinista\n')
 run('groupadd','--force','gpio')
 run('usermod','-aG','audio,plugdev,input,video,render,bluetooth,dialout,netdev,gpio','machinista')
 (root/'etc/hostname').write_text('machinista\n')
 (root/'etc/hosts').write_text('127.0.0.1 localhost\n127.0.1.1 machinista\n::1 localhost ip6-localhost ip6-loopback\n')
 (root/'etc/sudoers.d/010-machinista').write_text('machinista ALL=(ALL:ALL) ALL\n');(root/'etc/sudoers.d/010-machinista').chmod(0o440)
 for folder in ('Kicks','Snares','Hi-Hats','Loops'):(app/'samples/Library'/folder).mkdir(parents=True,exist_ok=True)
 for folder in ('projects','config','cache','exports','presets','diagnostics'):(app/folder).mkdir(exist_ok=True)
 sys.path.insert(0,str(app));from app.model import new_project,Application
 (app/'projects/current.json').write_text(json.dumps(new_project(),indent=2)+'\n')
 (app/'config/settings.json').write_text(json.dumps({'audio':'AUTO','midi_in':'OFF','midi_out':'OFF','midi_channel':1,'display_brightness':100,'display_contrast':42},indent=2)+'\n')
 (root/'etc/machinista').mkdir(exist_ok=True)
 (root/'etc/machinista/hardware-profile').write_text(profile_id+'\n')
 if profile_id=='pi3b-sampler':
  settings=json.loads((app/'config/settings.json').read_text());settings['audio_buffer']=512;(app/'config/settings.json').write_text(json.dumps(settings,indent=2)+'\n')
 os.environ['MACHINISTA_HARDWARE_PROFILE']=profile_id
 Application(app)  # Validate generic configuration and blank project in situ.
 manager=root/'usr/local/lib/machinista/lv2_manager.py';manager.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(app/'app/lv2_manager.py',manager);manager.chmod(0o644)
 shutil.copy2(app/'tools/power_service.py',manager.parent/'power_service.py');(manager.parent/'power_service.py').chmod(0o644)
 updates=True  # All newly built images include the same updater service.
 if updates:
  for source in ('tools/update_service.py','tools/update_rpc.py','app/update_manager.py'):
   shutil.copy2(app/source,manager.parent/Path(source).name)
  (root/'etc/machinista').mkdir(exist_ok=True)
  updater_config=json.loads((app/'deploy/updater.example.json').read_text())
  updater_config['current_version']=VERSION
  updater_config.update(hardware_profile=profile_id,architecture='arm64')
  (root/'etc/machinista/updater.json').write_text(json.dumps(updater_config,indent=2)+'\n')
  if (app/'deploy/update-public.pub').is_file():shutil.copy2(app/'deploy/update-public.pub',root/'etc/machinista/update-public.pem')
  (root/'etc/machinista/updater.json').chmod(0o644)
  state=root/'var/lib/machinista-updater';state.mkdir(parents=True,exist_ok=True)
  (state/'channel.json').write_text(json.dumps({'channel':'beta' if '-beta.' in VERSION else 'release'})+'\n')
 shutil.copy2(app/'build/audio_engine',manager.parent/'lv2_scan');(manager.parent/'lv2_scan').chmod(0o755)
 shutil.copy2(app/'deploy/smb.conf',root/'etc/samba/smb.conf')
 for unit in (app/'deploy').glob('*.service'):
  if unit.name=='machinista-updater.service' and not updates:continue
  text=unit.read_text()
  if profile_id=='pi3b-sampler':text=text.replace('Wants=machinista-lv2.service\n','').replace('After=sound.target machinista-lv2.service','After=sound.target').replace('After=network.target machinista-media.service machinista-lv2.service','After=network.target machinista-media.service')
  if unit.name!='machinista-firstboot.service':text=text.replace('[Unit]','[Unit]\nRequires=machinista-firstboot.service\nAfter=machinista-firstboot.service',1)
  (root/'etc/systemd/system'/unit.name).write_text(text)
 for rule in (app/'deploy').glob('*.rules'):shutil.copy2(rule,root/'etc/udev/rules.d'/rule.name)
 run('systemctl','enable','machinista-firstboot',*(['machinista-lv2'] if profile_id=='standard' else []),'machinista-power','machinista','machinista-web','machinista-network','machinista-media','machinista-bluetooth','smbd','avahi-daemon','NetworkManager')
 if updates:run('systemctl','enable','machinista-updater')
 if profile_id=='pi3b-sampler':
  run('systemctl','disable','machinista-lv2','machinista-lv2-scan')
  for name in ('machinista-lv2.service','machinista-lv2-scan.service'):
   (root/'etc/systemd/system'/name).unlink(missing_ok=True)
  run('systemctl','mask','machinista-lv2.service','machinista-lv2-scan.service')
 # Prepared account replaces stock first-user provisioning; no shared SSH login.
 for unit in ('userconfig.service','ssh.service','ssh.socket','regenerate_ssh_host_keys.service'):
  subprocess.run(['chroot',str(root),'systemctl','disable',unit],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 run('systemctl','mask','ssh.service','ssh.socket','systemd-firstboot.service','cloud-init.service','cloud-init-local.service','cloud-config.service','cloud-final.service')
 (root/'etc/cloud').mkdir(exist_ok=True)
 (root/'etc/cloud/cloud-init.disabled').write_text('')
 run('chown','-R','machinista:machinista','/home/machinista')
 run('testparm','-s',stdout=subprocess.DEVNULL)
 run('ldd','/home/machinista/Machinista/build/audio_engine')
 run('ldd','/home/machinista/Machinista/build/mikro_monitor')
 run('ldd','/home/machinista/Machinista/build/mk2_monitor')
 if (app/'build/mk1_monitor').exists():run('ldd','/home/machinista/Machinista/build/mk1_monitor')
 run('sh','-c','cd /home/machinista/Machinista && MACHINISTA_HARDWARE_PROFILE=standard python3 -m unittest tests.test_network_manager tests.test_web_server tests.test_wave_zoom tests.test_manual_surface tests.test_mk2_surface tests.test_fokus_fein tests.test_hardware_profiles -q')
 # Keep package/source provenance; apt clean removes download payloads only.
 packages=run('dpkg-query','-W','-f=${Package}\t${Version}\t${Architecture}\n',capture_output=True).stdout
 (app/'BETA-PACKAGES.tsv').write_text(packages)
 if not (app/'BETA-README.txt').exists():shutil.copy2(app/'deploy/README-beta.md',app/'BETA-README.txt')
 (root/'etc/machinista-release').write_text(VERSION+'\n')
 run('apt-get','clean')
 for folder in ('var/log','var/lib/NetworkManager','var/lib/bluetooth','var/lib/samba','var/lib/cloud','etc/NetworkManager/system-connections','etc/netplan'):
  path=root/folder
  if path.exists():
   for child in path.iterdir():
    if child.is_dir() and not child.is_symlink():shutil.rmtree(child)
    else:child.unlink()
 (root/'etc/NetworkManager/system-connections').mkdir(parents=True,exist_ok=True);(root/'etc/NetworkManager/system-connections').chmod(0o700)
 (root/'etc/machine-id').write_text('')
 for path in (root/'etc/ssh').glob('ssh_host_*'):path.unlink()
 (root/'var/lib/systemd/random-seed').unlink(missing_ok=True)
 (root/'var/lib/dbus/machine-id').unlink(missing_ok=True)
 (root/'var/lib/dbus/machine-id').symlink_to('/etc/machine-id')
 (root/'var/lib/samba/private').mkdir(mode=0o700,parents=True,exist_ok=True)
 cmdline=root/'boot/firmware/cmdline.txt'
 words=[w for w in cmdline.read_text().split() if not w.startswith(('init=','systemd.run=','systemd.run_success_action=','systemd.unit=','ds=nocloud','cfg80211.ieee80211_regdom='))]
 words.append('cfg80211.ieee80211_regdom=DE');cmdline.write_text(' '.join(words)+'\n')
 # Firstboot expands the newly flashed card, not this build VM's disks.
 assert not (root/'var/lib/machinista/initialized').exists()
 assert not list((root/'etc/NetworkManager/system-connections').iterdir())
 assert not list((root/'etc/ssh').glob('ssh_host_*'))
 assert not list((app/'samples').rglob('*.wav'))
 assert {p.name for p in (root/'home').iterdir()}=={'machinista'}
 print('Machinista beta root configured and sanitized',flush=True)
if __name__=='__main__':main()
