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

The build of 2026-10-28
-----------------------

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
- The first boot on a Raspberry Pi 5 is the operator's: the UI comes up, MOD-UI runs on plugin-hostd, a chain with an
  LV2 and a CLAP plugin sounds, and the qualification sync has run once (`/var/lib/omx/qualified.pins` filled).
