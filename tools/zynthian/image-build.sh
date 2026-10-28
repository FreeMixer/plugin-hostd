#!/bin/bash
# Build a ZynthianOS SD image that carries OpenMixer: upstream's released image, updated offline the way a Pi is
# updated, on an x86_64 build host.
#
#   tools/zynthian/image-build.sh <zynthianos-vangelis.img.xz> <work-dir>
#
# It takes upstream's image as it is, points /zynthian/zynthian-sys and /zynthian/zynthian-ui at the FreeMixer forks
# (branch vangelis), and runs, inside the image's root file system (systemd-nspawn, arm64 through qemu-user-static),
# what a Zynthian runs to update: update_zynthian_sys.sh (which makes OpenMixer the default with
# recipes/install_openmixer.sh), update_zynthian_code.sh, then install_openmixer.sh --upgrade. It then cleans the
# logs and apt caches and writes <work-dir>/zynthianos-vangelis-omx.img, with its .xz and .xz.sha256 next to it.
#
# Needs: sudo (loop devices, mount, nspawn, the binfmt entry), systemd-nspawn, losetup, growpart, e2fsck, resize2fs,
# xz, debugfs. QEMU_AARCH64 names a static qemu-aarch64; when no qemu-aarch64 binfmt entry is registered, one is
# registered with it for the build and removed afterwards. GROW is how much the image grows for the new packages
# (default 2G); the first boot expands the root file system to the card anyway.
# The plugins are not qualified here: that must run on the Pi (zynthian-sys scripts/omx_prequalify_image.sh), and the
# image's first boot does it at low priority.
set -euo pipefail

src=${1:?upstream image .img.xz}
work=$(mkdir -p "${2:?work dir}" && cd "$2" && pwd)
QEMU_AARCH64=${QEMU_AARCH64:-/usr/bin/qemu-aarch64-static}
GROW=${GROW:-2G}
SYS_REPO=${SYS_REPO:-https://github.com/FreeMixer/zynthian-sys.git}
UI_REPO=${UI_REPO:-https://github.com/FreeMixer/zynthian-ui.git}
BRANCH=${BRANCH:-vangelis}
here=$(cd "$(dirname "$0")" && pwd)
img=$work/zynthianos-vangelis-omx.img
mnt=$work/mnt
log=$work/build.log
loop=""
binfmt_ours=0

say() { printf '%s %s\n' "$(date +%T)" "$*" | tee -a "$log"; }

cleanup() {
	set +e
	sudo umount "$mnt/boot/firmware" 2>/dev/null
	sudo umount "$mnt" 2>/dev/null
	[ -n "$loop" ] && sudo losetup -d "$loop"
	[ "$binfmt_ours" = 1 ] && echo -1 | sudo tee /proc/sys/fs/binfmt_misc/qemu-aarch64 >/dev/null
}
trap cleanup EXIT

: >"$log"
start=$(date +%s)

say "decompressing $src"
xz -dc -T0 "$src" >"$img"

say "growing the image by $GROW"
truncate -s +"$GROW" "$img"
growpart "$img" 2 | tee -a "$log"

loop=$(sudo losetup -fP --show "$img")
sudo e2fsck -pf "${loop}p2" >>"$log" 2>&1 || [ $? -le 1 ]
sudo resize2fs "${loop}p2" 2>&1 | tee -a "$log"
mkdir -p "$mnt"
sudo mount "${loop}p2" "$mnt"
sudo mount "${loop}p1" "$mnt/boot/firmware"

if [ ! -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ]; then
	say "registering qemu-aarch64 ($QEMU_AARCH64) for the build"
	sed "s#:/usr/bin/qemu-aarch64-static:#:$QEMU_AARCH64:#" "$(dirname "$QEMU_AARCH64")/../lib/binfmt.d/qemu-aarch64-static.conf" |
		sudo tee /proc/sys/fs/binfmt_misc/register >/dev/null
	binfmt_ours=1
fi

sudo cp -a "$mnt/boot/firmware/config.txt" "$work/config.txt.before"

say "updating the image inside its root file system"
sudo systemd-nspawn -q -D "$mnt" --resolv-conf=replace-host --setenv=SYS_REPO="$SYS_REPO" \
	--setenv=UI_REPO="$UI_REPO" --setenv=BRANCH="$BRANCH" /bin/bash -c '
	# Zynthian'"'"'s scripts are not written for set -eu: only the steps that must not fail stop the build
	for r in zynthian-sys:$SYS_REPO zynthian-ui:$UI_REPO; do
		d=/zynthian/${r%%:*}; url=${r#*:}
		git -C "$d" remote set-url origin "$url" &&
			git -C "$d" fetch -q origin "$BRANCH" &&
			git -C "$d" checkout -q -f -B "$BRANCH" "origin/$BRANCH" &&
			git -C "$d" branch -q --set-upstream-to="origin/$BRANCH" || exit 1
		echo "$d $(git -C "$d" rev-parse HEAD) $url"
	done
	export ZYNTHIAN_SYS_DIR=/zynthian/zynthian-sys
	source $ZYNTHIAN_SYS_DIR/scripts/zynthian_envars_extended.sh
	cd $ZYNTHIAN_SYS_DIR/scripts
	./update_zynthian_sys.sh; echo "update_zynthian_sys.sh exit $?"
	./update_zynthian_code.sh; echo "update_zynthian_code.sh exit $?"
	$ZYNTHIAN_RECIPE_DIR/install_openmixer.sh --upgrade || exit 1
	apt-get clean
	rm -rf /var/lib/apt/lists/*
	for f in /var/log/* /var/log/**/*; do [ -f "$f" ] && : >"$f"; done
	: >/root/.bash_history
	sys=$(git -C /zynthian/zynthian-sys rev-parse --short=12 HEAD)
	ui=$(git -C /zynthian/zynthian-ui rev-parse --short=12 HEAD)
	{ echo; echo "OpenMixer: zynthian-sys $sys, zynthian-ui $ui (FreeMixer forks, $BRANCH)"; echo "Updated: $(date --rfc-3339=date)"; } >>/zynthian/build_info.txt
	dpkg-query -W -f="\${Package} \${Version}\n" openmixer-release plugin-hostd omx-clap-host omx-plugins omx-panel plugin-qualify || exit 1
' 2>&1 | tee -a "$log"

sudo diff "$work/config.txt.before" "$mnt/boot/firmware/config.txt" >"$work/config.txt.diff" || true
sudo umount "$mnt/boot/firmware" "$mnt"
sudo e2fsck -pf "${loop}p2" >>"$log" 2>&1 || [ $? -le 1 ]
sudo losetup -d "$loop"
loop=""

say "inspecting"
"$here/image-inspect.sh" "$img" "$work/inspect" >/dev/null
cat "$work/inspect/inspect.txt" >>"$log"

say "compressing"
xz -T0 -k -f "$img"
(cd "$work" && sha256sum "$(basename "$img").xz" >"$(basename "$img").xz.sha256")
say "done in $(($(date +%s) - start)) s: $img.xz ($(du -h "$img.xz" | cut -f1))"
cat "$img.xz.sha256" | tee -a "$log"
