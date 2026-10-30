The ZynthianOS image with our work
==================================

What the image is: ZynthianOS `vangelis` for the Raspberry Pi 4 and 5, with zynthian-sys and zynthian-ui from the
FreeMixer forks (branch `vangelis`), the OpenMixer apt repository, and plugin-hostd, omx-clap-host, omx-plugins,
omx-panel and plugin-qualify installed and made the default, as zynthian-sys's `scripts/recipes/install_openmixer.sh`
does on a new install and on every update (FreeMixer/zynthian-sys#4).

How upstream builds its images
------------------------------

Upstream publishes the `vangelis` images at <https://os.zynthian.org/> (`2026-10-15-zynthianos-vangelis-2610-stable`,
`2026-09-30-zynthianos-vangelis-2609-beta`). No builder for them is published:

- [zynthian/ZynthianOS](https://github.com/zynthian/ZynthianOS) is a CustomPiOS distribution (qemu-user-static and a
  chroot over a downloaded RealtimePi image). Its last commit is from 2022 (`staging-2209`), it targets Raspbian
  stretch and the Raspberry Pi 1 to 3, and `zynthian/CustomPiOS` is a 2018 fork. It does not build `vangelis`.
- zynthian-sys's `scripts/setup_system_raspioslite_64bit_trixie.sh` is how a `vangelis` system is made: run as root
  on a Raspberry Pi booted from a fresh Raspberry Pi OS Lite (trixie, arm64) card. Its first lines are done "with the
  SD card mounted in your computer" (user `zyn`, ssh). It installs everything, compiles from source and ends in
  `set_first_boot.sh`; the card is then imaged. The fork's copy already takes zynthian-sys and zynthian-ui from the
  FreeMixer forks and runs `install_openmixer.sh`.
- zynthian-sys's `scripts/update_system_image.sh` ("update an image and prepare it for repacking") is upstream's way
  of refreshing an image: on a Pi booted from the previous image it runs `update_zynthian_recipes.sh`,
  `update_zynthian_data.sh`, `update_zynthian_sys.sh` and `update_zynthian_code.sh`, then clears the logs and history
  and stamps `/zynthian/build_info.txt`. It switches every repository to `testing`, so it is not run as it is here.
  The fork's copy ends with `install_openmixer.sh --upgrade`.
- zynthian-sys's `scripts/omx_prequalify_image.sh` (ours) qualifies every plugin once so the image ships qualified.
  It refuses anything but native arm64: the records are keyed by the plugin files' hashes and measured on the CPU.

Routes
------

| Route | Time | Hardware | Reproducible |
|---|---|---|---|
| (a) a builder pointed at our forks: `setup_system_raspioslite_64bit_trixie.sh` over Raspberry Pi OS Lite | many hours: it compiles the whole Zynthian stack (zyncoder, zynlibs, mod-host, jalv, the engines); natively on the Pi 5 (4 GB) longer still, under qemu on an x86_64 host far longer | a Pi with a spare card, or a host with qemu-user-static | yes, from two public inputs, but it rebuilds what upstream already released, and it is not what upstream's image carries |
| (b) upstream's released image, updated offline with the fork's update steps | about 7 minutes on the build host, after a 6 GB download (measured below) | an x86_64 Linux host with sudo, systemd-nspawn and a static qemu-aarch64 | yes: the inputs are upstream's image (by sha256), the fork commits and the OpenMixer packages, all public; the script is [tools/zynthian/image-build.sh](../../tools/zynthian/image-build.sh) |
| (c) a copy of the updated Pi's card | the copy time | the Pi, taken out of service | no: it carries the Pi's own state (keys, logs, snapshots, Wi-Fi, qualification records of that device), it cannot be rebuilt from anything named, and the Pi is our live test device |

Chosen: (b). It is what a Zynthian owner gets by flashing upstream's image and updating with the fork's
zynthian-sys, done once before the image is written; the Zynthian part stays bit for bit upstream's release.

How it is built
---------------

On the build host (x86_64 Fedora, sudo). The static qemu is taken from Fedora's package without installing it; the
script registers its binfmt entry only for the build when none exists, and removes it afterwards.

```
mkdir -p zynthian-image/{dl,qemu}
cd zynthian-image/dl
curl -sSfLO https://os.zynthian.org/2026-10-15-zynthianos-vangelis-2610-stable.img.xz
curl -sSfLO https://os.zynthian.org/2026-10-15-zynthianos-vangelis-2610-stable.img.xz.md5
md5sum -c 2026-10-15-zynthianos-vangelis-2610-stable.img.xz.md5
# sha256 83c4078be5726f148cfc496cbbe2ef39a1933d0e0984e730ff0477126dff19b6, as in evidence/image/sha256.txt
cd ../qemu && dnf download qemu-user-static-aarch64 && rpm2cpio qemu-user-static-aarch64-*.rpm | cpio -idm
cd .. && QEMU_AARCH64=$PWD/qemu/usr/bin/qemu-aarch64-static \
    <plugin-hostd>/tools/zynthian/image-build.sh dl/2026-10-15-zynthianos-vangelis-2610-stable.img.xz out
```

What `image-build.sh` does, in order: decompresses the image, grows it by 2 GiB (`growpart`, `resize2fs`; the first
boot expands the root file system to the card as before), loop-mounts both partitions, and in a `systemd-nspawn` of
the root file system:

1. points `/zynthian/zynthian-sys` and `/zynthian/zynthian-ui` at `FreeMixer/zynthian-sys` and
   `FreeMixer/zynthian-ui`, branch `vangelis`, so later updates on the device follow the forks;
2. runs `update_zynthian_sys.sh`: the fork's system files, `config.txt` from its template, and
   `install_openmixer.sh` (the repository, the five packages, `ZYNTHIAN_MODHOST_BACKEND` and
   `ZYNTHIAN_PLUGIN_ENGINE` set to plugin-hostd, `plugin-hostd.conf`, `qualify.conf`, the sync's units enabled);
3. runs `update_zynthian_code.sh` (the UI fork pulled, zyncoder and zynlibs rebuilt), then
   `install_openmixer.sh --upgrade`;
4. clears the apt caches and lists, the logs and root's history, and adds the fork commits to
   `/zynthian/build_info.txt`.

It then checks the file system, runs [image-inspect.sh](../../tools/zynthian/image-inspect.sh) on the result, and
writes `zynthianos-vangelis-omx.img.xz` (`xz -T0`) and its `.sha256`. `config.txt.diff` shows what the update
changed in `/boot/firmware/config.txt`.

Inside the nspawn the board is not detected (`VIRTUALIZATION` is `systemd-nspawn`, no device tree): the steps that
read the sound card or the ALSA mixer are skipped by the scripts themselves, as they are under any virtualization, and
`config.txt` is the template's, which carries the Pi 4 and Pi 5 sections both. The first boot sets the rest, as for
upstream's image.

`systemctl` inside the nspawn has no running systemd: `daemon-reload` and the restarts the update scripts ask for
print "System has not been booted with systemd" and are skipped, which is right for an image; `enable` works.
`update_zynthian_code.sh` exits 1 for that reason alone (its last step restarts zynthian-webconf), after the engines
database is regenerated. A
command the scripts cannot find fails the build (they would skip it silently).

The plugins are not qualified in the image. `omx_prequalify_image.sh` must run on the Pi itself, and without it the
first boot qualifies them at low priority two minutes after boot (`plugin-qualify-sync.timer`).

Where it is published
---------------------

A release asset on [FreeMixer/zynthian-sys](https://github.com/FreeMixer/zynthian-sys/releases): the `.img.xz` and
its `.img.xz.sha256`, the release named after the upstream image and the fork commit it carries (for example
`vangelis-2610-omx-<zynthian-sys short sha>`). The release notes carry the `image-inspect.sh` output. GitHub takes
release assets up to 2 GiB and this image compresses to 5.9 GiB, so it is published in four parts
(`split -b 1900M -d -a 2 zynthianos-vangelis-omx.img.xz zynthianos-vangelis-omx.img.xz.`), the sha256 of the joined
file and of each part beside them; the notes say `cat zynthianos-vangelis-omx.img.xz.* > zynthianos-vangelis-omx.img.xz`
before checking and flashing.

The build on Vangelis-2610.1
----------------------------

On an x86_64 Fedora host with 24 cores: 434 s from the upstream `.img.xz` to the compressed image (decompress 6 s,
update in the nspawn 3 min 7 s, compress 3 min 57 s). The image is 19.4 GB raw (upstream's 17.4 GB plus 2 GiB) and
6 286 200 184 bytes compressed, sha256 `48fca2510d93b06df5dbffe9b8f209a37869f44bba7155c632788cfbcd324d26`
([evidence/image/sha256.txt](evidence/image/sha256.txt)). What it carries, as `image-inspect.sh` reads it, is
[evidence/image/omx-inspect.txt](evidence/image/omx-inspect.txt): zynthian-sys `aa36238dcb36` and zynthian-ui
`4f0e87fbb8ac` from the forks, openmixer-release 1-3, plugin-hostd 0.13.1, omx-clap-host 0.23.2, omx-plugins
0.15.1, omx-panel 0.6.0, plugin-qualify 0.16.1, and `config.txt` unchanged from upstream's.

How it is checked
-----------------

- `image-inspect.sh` on the built image (no root): `/zynthian/build_info.txt` names upstream's build and the fork
  commits; `openmixer-release`, `plugin-hostd`, `omx-clap-host`, `omx-plugins`, `omx-panel` and `plugin-qualify` have
  versions; `zynthian-sys` and `zynthian-ui` are on `refs/heads/vangelis` at the fork's commit with the fork's URL.
- `/zynthian/config/zynthian_envars.sh` in the image says `ZYNTHIAN_MODHOST_BACKEND="plugin-hostd"` and
  `ZYNTHIAN_PLUGIN_ENGINE="plugin-hostd"`, and `/zynthian/config/openmixer-defaults` lists the steps done.
- The first boot on a Raspberry Pi 5 is still to be done by hand: the UI comes up, MOD-UI runs on plugin-hostd, a chain with an
  LV2 and a CLAP plugin sounds, and the qualification sync has run once (`/var/lib/omx/qualified.pins` filled).

Boot test in a container
------------------------

[tools/zynthian/image-boot-test.sh](../../tools/zynthian/image-boot-test.sh) mounts the image's root file system
read-only, puts an overlayfs with a scratch upper layer over it (the boot partition read-only), and runs it through
the static qemu-aarch64 on the build host, binfmt registered for the run only. The artefact is checked by sha256
before and after (unchanged: `48fca251...`). Two runs, both in
[evidence/image/boot-test-2026-10-28/](evidence/image/boot-test-2026-10-28/):

- `systemd-nspawn --boot`, 150 s (`boot-state.txt`, read from outside the container). With `SYSTEMD_SECCOMP=0` the
  arm64 systemd runs as init and reaches `degraded`: the manager runs, but **every process a unit starts exits 1 at
  once**, including a unit whose command is `/bin/true` that the script adds to tell the emulation from the services.
  The same binaries run fine when started from outside the container. A container under qemu-user therefore cannot
  say anything about whether a service starts, and the failed-unit list (36 units, `journald` among them) is the
  emulation, not the image. The image's own `fstab` lines (root and boot by PARTUUID, three tmpfs mounts) failed there
  and put the boot in emergency mode; the upper layer's `fstab` holds only `proc`, so that the boot gets as far as
  `degraded`. The console of a pipe-attached container stays empty and the journal is never written, so there is no
  console or journal capture of this boot.
- The probes, in the same root without `--boot` (`probe.txt`): what a root file system can answer without starting
  anything.

| Check | Result | Proven in container |
|---|---|---|
| Image boots to a login | not reached: init runs, no unit starts (see above). The full-system run below boots it | no |
| `systemctl list-units --failed` | 36 units, every one the emulation (child processes exit 1); `/bin/true` as a unit fails the same | no |
| zynthian.service | installed, **not enabled** (no `*.wants` link); state `inactive`. The failure reason, `no screens found` from X, is in the full-system run | no (see First boot) |
| jack2.service | installed, wanted by `multi-user.target`; container state `failed` (exit 1, the emulation). The real reason, no ALSA card, is in the full-system run | no |
| mod-host.service (the fork's backend unit) | installed in `/etc/systemd/system`, `[Install] WantedBy=multi-user.target` but not enabled (no `*.wants` link); `Requires=jack2.service`; `ExecStart=mod-host-backend.sh start`, which starts plugin-hostd through `plugin-hostd-start.sh`. There is no `plugin-hostd.service` | file only |
| omx-modgui-sync | `omx-modgui-sync.service` installed (`/usr/lib/systemd/system`) with the Zynthian drop-in; there is no `.path` unit; `plugin-qualify-sync.service` starts it after each sync | file only |
| plugin-qualify-sync | `.service`, `.timer` and `.path` installed and enabled (`timers.target.wants`, `paths.target.wants`), with Zynthian's drop-ins | file only |
| omx-track-latest.timer | not installed | yes (absence) |
| `dpkg -l \| grep -E 'omx-\|plugin-'` | omx-clap-host 0.23.2, omx-clap-core-contract 0.23.2, libomx-clap-core1 0.23.2, omx-contract-data 3.4.0, omx-panel 0.6.0, omx-plugins (+ -clap, -lv2, -contract) 0.15.1, plugin-hostd (+ -contract) 0.13.1, plugin-qualify 0.16.1 | yes |
| zynthian-ui HEAD | `4f0e87fbb8acc8fbfa58a37605bfcb38cacdc6f5` (expected 4f0e87fb) | yes |
| zynthian-sys HEAD | `aa36238dcb36fc004eaa4e027184adc8e67e8e8b` (expected aa36238d) | yes |
| `plugin-hostd --version` | `version: 0.13.1`, exit 0 | yes |
| `from zyngine import zynthian_engine_plugin_hostd` | `import ok`, exit 0, with the venv and Zynthian's environment sourced as `zynthian_envars_extended.sh` does; JACK absent, so `libzynaudioplayer` logs that it could not start a client | yes |
| `lv2ls \| wc -l` | 1336 (with Zynthian's `LV2_PATH`; 10 without it) | yes |
| `find /usr/lib/clap -name '*.clap' \| wc -l` | 58 | yes |
| `plugin-qualify-sync --system --dry-run` | no such option: `unknown argument --dry-run`, exit 2. `--help` exits 0; a run over empty search paths with its state in `/tmp` qualifies 0 plugins and exits 0 | yes |
| `omx-panel --version` | no such option (usage, exit 2); the package is 0.6.0 | yes |
| Engine switches | `/zynthian/config/zynthian_envars.sh`: `ZYNTHIAN_MODHOST_BACKEND="plugin-hostd"`, `ZYNTHIAN_PLUGIN_ENGINE="plugin-hostd"` | yes |
| `/zynthian/build_info.txt` | ZynthianOS Vangelis-2610.1; OpenMixer: zynthian-sys aa36238dcb36, zynthian-ui 4f0e87fbb8ac (FreeMixer forks, vangelis); updated 2026-10-28 | yes |

What a container cannot prove: that any unit starts, so nothing about `zynthian.service`, `jack2`, the timers
firing, or time to boot. Those are in "First boot" below.

First boot
----------

The container above cannot start a service, so the image was also booted under full emulation:
[tools/zynthian/image-first-boot-qemu.sh](../../tools/zynthian/image-first-boot-qemu.sh) runs `qemu-system-aarch64`
(machine `virt`, `cortex-a72`, 4 cores, 4 GB, TCG: an x86_64 host has no aarch64 KVM) on a qcow2 overlay whose backing
file is the decompressed image. The overlay is a 32 GB disk, a card larger than the image so that the resize has
work to do; the artefact is untouched (sha256 checked before and after every run). The serial console is the log,
every line stamped with the seconds since the start of the run, with the journal forwarded to it. After the run
[tools/zynthian/image-qemu-harvest.sh](../../tools/zynthian/image-qemu-harvest.sh) reads the files the console does not
carry (`/root/first_boot.log`, the qualification state) out of the overlay. Evidence:
[evidence/image/first-boot-qemu-2026-10-28/](evidence/image/first-boot-qemu-2026-10-28/). Repeated message lines are
cut after the eighth (the cut is counted at the end of each log); the raw logs stay on the build host.

**The userland first boot was proven with a generic kernel, not the image's.** The first try was the image's own
Raspberry Pi kernel (`kernel8.img`, 6.18.50+rpt, with its `initramfs8`) and its command line: it starts and the initramfs
runs, then gives up after 30 s with `PARTUUID=e249d476-02 does not exist`, the root disk never appearing, and stays at
the initramfs shell for the 10 minutes allowed (`serial-attempt-pi-kernel.txt`): that kernel has no virtio block
driver. The second was Debian trixie's `linux-image-cloud-arm64` 6.12.113 alone, which has virtio PCI built in but
`virtio_blk` as a module, so it waited for a root disk without a message (`serial-attempt-generic-kernel-no-initrd.txt`);
with a minimal initramfs that loads `virtio_blk` it reached systemd, which went to emergency mode because
`/boot/firmware` (vfat) has no driver in the image's module tree (`serial-attempt-generic-kernel-no-modules.txt`). The
run below uses that kernel with an initramfs ([tools/zynthian/image-qemu-kernel.sh](../../tools/zynthian/image-qemu-kernel.sh))
that loads `virtio_blk`, mounts `/dev/vda2` and copies the eight modules vfat, fat, nls and virtio_net need into
`/lib/modules/6.12.113+deb13-cloud-arm64` **of the overlay** before `switch_root`. The image's userland, its
`first_boot.service`, its resize and its units are the ones shipped; the kernel, the missing audio card, display, I2C
bus and the Pi's firmware are not, and the command line drops the image's display and splash words (it adds the serial
console and the journal on it).

### What the first boot does, with durations in the VM

Times are seconds on the serial console of the first boot (`serial-first-boot.txt`; boot 1 starts at 0, boot 2 at
38.7); "per card" means the step is about this card and is never copied.

| Step | VM | By nature | Can it be copied into the image |
|---|---|---|---|
| Boot 1: kernel, systemd, up to `first_boot.service` | 10.5 s | every boot | n/a |
| Hardware autoconfig (`zynthian_autoconfig.py`) | 1.5 s; no I2C bus here, so it ends in a traceback (`i2cdetect -y 1`), "Hardware Model: linux,dummy-virt (UNSUPPORTED!)" | per device: it reads the kit's hardware. On a Pi it may ask for a reboot, and then `first_boot.sh` enables `zynthian.service` and reboots before anything below | no |
| ALSA mixer settings | about 1 s | per sound card | no |
| Regenerate the SSH host keys (RSA 3072, ECDSA), restart sshd | about 5 s (`/root/first_boot.log`: "Removing current system SSH keys... Generating new system SSH keys") | **per card, never copied**: a key in the image would be every card's key | no |
| Webconf cookie secret, 100-year SSL certificate | about 1.5 s | per card | no |
| Create the Wi-Fi access point connection | 0.3 s | per card (a NetworkManager connection with its own UUID) | no |
| Regenerate the LV2 cache (`zynthian_lv2.py`, only if `config/jalv` holds fewer than 20 files) | 0 s: not run, the cache is shipped | per plugin set | **already copied** (the image ships it) |
| Wait for the splash images (10 polls of 0.5 s) | 5 s, it never saw `fb_zynthian_error.jpg` in the VM | fixed wait | the images could be shipped; the wait is a constant |
| Disable `first_boot`, plymouth theme | about 2 s | once | n/a |
| `raspi-config --expand-rootfs`: rewrite partition 2 to the end of the disk, arm `resize2fs_once`, reboot | 3.6 s, then 3.5 s to the next kernel | **per card**: the card's size | no |
| Boot 2: `resize2fs_once` grows the file system (17.5 GiB to 31.5 GiB, online) | 5.8 s | per card | no |
| Login prompt of boot 2 | 69 s on the console, 30 s into boot 2 | | |
| `a2jmidid` and `mod-ttymidi` wait for JACK, then time out; `multi-user.target` | 188.7 s (150 s into boot 2) | the VM has no sound card, so `jack2` cannot start: on a Pi with its card this wait is not there | n/a |
| `plugin-qualify-sync.timer` fires (`OnBootSec=2min`) | 121 s into boot 2; first line of the sweep 2.4 s later | every boot, cheap when the records are current | **copyable by the records package (plugin-qualify#197)** |
| The sweep: 37 CLAP plugins in `/usr/lib/clap` | 327 s: 8.8 s a plugin under emulation, at `Nice=19`, `CPUQuota=200%`. 5 qualified, 31 refused (`hosting.rt-safety.violations-in-run`), 1 hung (`probe.timeout`) | per plugin file (keyed by its hash), per CPU | records package |
| The descriptors step, then the LV2 stage (1336 bundles by `lv2ls`) | not reached: "descriptors of a .clap not all written (spawnSync python3 ETIMEDOUT)" at 563 s, then silence until the end of the run at 1359 s | | records package |
| Engines database, `install_openmixer.sh`, `update_zynthian_sys.sh` | **no first-boot step**: nothing in the first boot's log; they ran at build time (image-build.sh) | | already in the image |

Totals in the VM: login prompt 69 s after power-on; `multi-user.target` 189 s; the sweep, started 2 min after boot,
had finished 37 plugins when stopped at 1359 s. Two boots, because `first_boot.sh` reboots once.

### A normal boot

The same overlay booted again (`serial-normal-boot.txt`, 600 s): kernel 1.2 s, login prompt after 25.6 s,
`multi-user.target` after 441 s ("Startup finished in 1.247 s (kernel) + 7 min 19.570 s (userspace)"). The time is the
same JACK wait, repeated: `jack2.service` fails (`ALSA lib ... Cannot get card index for 0`, "Failed to open server") and is
restarted about every 5 s (104 starts in 600 s) while `a2jmidid` and `mod-ttymidi` wait for it and time out, and the
sweep competes for the CPU. The sweep started again at 121 s and was **killed by the memory ceiling at 286 s**
(`plugin-qualify-sync.service: A process of this unit has been killed by the OOM killer ... Failed with result
'oom-kill'`, 1000M peak, 1 min 49 s of CPU): the unit stopped, where its comment says a plugin past the ceiling "is
killed and recorded as crashed, the run goes on". The state on the overlay after both runs: 37 entries (all CLAP), 112
descriptors, 356 record files, 37 pins (`harvest-after-first-boot.txt`).

### zynthian.service

It is installed and **not enabled** after the first boot: the autoconfig found no hardware, so the path that runs
`systemctl enable zynthian` was not taken. Started with `systemd.wants=zynthian.service` on the kernel command line
(`serial-zynthian-service-requested.txt`) it starts `startx` and fails at once: `(EE) Fatal server error: (EE) no
screens found`. That is the failure to expect without a display; it says nothing about the UI itself.

### The first boot on a Pi 5

Not measured on the device. From the VM, the steps that cannot be copied are the card's own and total under a minute
of work (keys, certificate, access point, partition and file system resize, two reboots); the VM took 69 s to a login
prompt, and a Pi 5 running native code is not expected to be slower, but that is an expectation, not a measurement.
What can run for much longer is the sweep, which is a background service at the lowest priority two minutes after boot
and does not hold the boot:

- **Without the records package:** every plugin is qualified on the card. The VM's rate for CLAP plugins (8.8 s each
  under emulation) is not a Pi 5 figure and the LV2 stage did not run, so no total can be given; the VM's refusals
  (31 of 37) are timing verdicts from an emulated CPU and must not be copied to a card. Not measured on the device.
- **With the records package (plugin-qualify#197):** the timer finds records for the plugin files' hashes and only
  checks that nothing changed; the first boot is the table's card-bound steps. Not measured on the device, and that
  package is not in this image.

### What this does not prove

Audio: no JACK server ran, no card was present. The UI: `zynthian-ui` was only started once, without a display.
The Pi kernel and firmware, I2C autoconfig on a real kit, the Wi-Fi access point, the resize on a physical card, the
sweep to its end, the LV2 stage, and every timing on a Pi. A hardware claim needs the device, never this log.

### Findings

- `plugin-qualify-sync.service` is stopped by systemd when one process is OOM-killed (`oom-kill`), against the
  behaviour its own comment promises; `OOMPolicy=continue` is the setting for "the run goes on". Seen under 4 GB of
  RAM and emulation; not checked on a Pi.
- The descriptors step of the sweep timed out (`spawnSync python3 ETIMEDOUT`) in both boots before the LV2 stage.
- `jack2.service` restarts without a pause every 5 s when there is no sound card, and `a2jmidid` and `mod-ttymidi`
  hold `multi-user.target` for 150 s or more while waiting for it.
- Expected in a VM, not findings: `rpi-eeprom-update.service` fails (no Pi), `networking.service` timed out
  (`reduce-timeout.conf`), `run-rpc_pipefs.mount` failed (a module the scaffolding does not carry).
- The clock: with no RTC and no network, `fake-hwclock` restores the image's time, so the SSH key files carry the image's date.

### Installing on an existing vangelis

A `vangelis` system already running needs no new image. As root, add the OpenMixer repository and install the
packages; the fork's update script keeps them current afterwards:

```
curl -fsSLO https://www.openmixer.org/deb/openmixer-release.deb
sudo apt install ./openmixer-release.deb
sudo apt install plugin-hostd omx-clap-host omx-clap-scan omx-panel
```

`openmixer-release` carries the signing key and the apt source of the running Debian release. The fork's setup scripts
do the same through `scripts/recipes/install_openmixer.sh`, and `update_system_image.sh` updates the packages with the
rest of the system. No service is enabled by this; mod-host, MOD-UI, jalv and the menus are as before (step 2 of
[the upstream patch series](upstream-series.md)).
