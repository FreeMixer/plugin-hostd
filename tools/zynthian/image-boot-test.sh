#!/bin/bash
# Boot the ZynthianOS image (tools/zynthian/image-build.sh's output) in a container and record what a container can
# prove. The artefact is never modified: the root file system is mounted read-only and used through an overlayfs
# whose upper layer is scratch, the boot partition read-only.
#
#   tools/zynthian/image-boot-test.sh <zynthianos-vangelis-omx.img.xz> <work-dir> <evidence-dir>
#
# Two parts, both through qemu-user-static (QEMU_AARCH64 names a static qemu-aarch64; a binfmt entry is registered
# for the run when none exists and removed after):
#  1. systemd-nspawn --boot, for BOOT_SECS seconds (default 150): the manager state and the failed units are read
#     from outside (nsenter) into <evidence-dir>/boot-state.txt, the console into console.log.
#  2. the probes (omx-boot-probe, below), run in the same root with systemd-nspawn without --boot: package versions,
#     git heads, the plugin counts, the engine switches, the unit files and their enablement. Output in probe.txt.
# The xz's sha256 is checked before and after. Needs: sudo, systemd-nspawn, nsenter, losetup, xz, overlayfs.
set -euo pipefail

src=${1:?image .img.xz}
work=$(mkdir -p "${2:?work dir}" && cd "$2" && pwd)
ev=$(mkdir -p "${3:?evidence dir}" && cd "$3" && pwd)
QEMU_AARCH64=${QEMU_AARCH64:-/usr/bin/qemu-aarch64-static}
BOOT_SECS=${BOOT_SECS:-150}
KEEP_IMG=${KEEP_IMG:-0}
img=$work/$(basename "${src%.xz}")
ro=$work/bt-ro; boot=$work/bt-boot; up=$work/bt-upper; wk=$work/bt-work; mrg=$work/bt-merged
loop=""; binfmt_ours=0; decompressed=0

say() { printf '%s %s\n' "$(date +%T)" "$*" | tee -a "$ev/run.log"; }

killroot() { # a killed nspawn leaves the container's init alive: stop whatever has the overlay as its root
	for p in /proc/[0-9]*; do
		[ "$(sudo readlink "$p/root" 2>/dev/null)" = "$mrg" ] && sudo kill -9 "${p#/proc/}"
	done
	sleep 2
}

cleanup() {
	set +e
	killroot
	sudo systemctl stop omx-boot-test.scope 2>/dev/null; sudo systemctl reset-failed omx-boot-test.scope 2>/dev/null
	sudo umount "/run/systemd/nspawn/unix-export/omx-boot-test" 2>/dev/null
	sudo rmdir "/run/systemd/nspawn/unix-export/omx-boot-test" 2>/dev/null
	sudo umount "$mrg/boot/firmware" 2>/dev/null
	sudo umount "$mrg" 2>/dev/null
	sudo umount "$boot" 2>/dev/null
	sudo umount "$ro" 2>/dev/null
	[ -n "$loop" ] && sudo losetup -d "$loop"
	[ "$binfmt_ours" = 1 ] && echo -1 | sudo tee /proc/sys/fs/binfmt_misc/qemu-aarch64 >/dev/null
	sudo rm -rf "$up" "$wk"
	rmdir "$ro" "$boot" "$mrg" 2>/dev/null
	[ "$decompressed" = 1 ] && [ "$KEEP_IMG" != 1 ] && rm -f "$img"
	say "artefact sha256 after: $(sha256sum "$src" | cut -d' ' -f1)"
	say "binfmt qemu-aarch64 left registered: $([ -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ] && echo yes || echo no)"
}
trap cleanup EXIT

: >"$ev/run.log"
say "artefact sha256 before: $(sha256sum "$src" | cut -d' ' -f1)"
df -h "$work" | tee -a "$ev/run.log"

if [ ! -e "$img" ]; then
	say "decompressing $src"
	xz -dkc -T0 "$src" >"$img"
	decompressed=1
fi

loop=$(sudo losetup -r -fP --show "$img")
mkdir -p "$ro" "$boot" "$up" "$wk" "$mrg"
sudo mount -o ro,noload "${loop}p2" "$ro"
sudo mount -o ro "${loop}p1" "$boot"
sudo mount -t overlay overlay -o lowerdir="$ro",upperdir="$up",workdir="$wk" "$mrg"
sudo mount --bind -o ro "$boot" "$mrg/boot/firmware"

if [ ! -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ]; then
	say "registering qemu-aarch64 ($QEMU_AARCH64) for the run"
	sed "s#:/usr/bin/qemu-aarch64-static:#:$QEMU_AARCH64:#" "$(dirname "$QEMU_AARCH64")/../lib/binfmt.d/qemu-aarch64-static.conf" |
		sudo tee /proc/sys/fs/binfmt_misc/register >/dev/null
	binfmt_ours=1
fi

# a container is given its root, boot files and temporary file systems: the image's fstab lines for them (PARTUUID
# root and boot, tmpfs /tmp /var/tmp /var/log) fail there and put the boot in emergency mode; the upper layer's fstab
# holds only proc
printf '# the container provides /, /boot/firmware and the tmpfs mounts (image-boot-test.sh)\nproc /proc proc defaults 0 0\n' |
	sudo tee "$mrg/etc/fstab" >/dev/null
sudo ln -sf /dev/null "$mrg/etc/systemd/system/systemd-remount-fs.service"


# the probes, run once the boot part is over
sudo mkdir -p "$mrg/usr/local/sbin"
sudo tee "$mrg/usr/local/sbin/omx-boot-probe" >/dev/null <<'PROBE'
#!/bin/bash
t() { printf '\n## %s\n' "$*"; }
exec >/probe/probe.txt 2>&1
t "unit files (a container under qemu-user cannot start services: boot-state.txt)"
for u in zynthian.service zynthian-config-on-boot.service first_boot.service jack2.service mod-host.service \
	plugin-hostd.service omx-modgui-sync.service omx-modgui-sync.path plugin-qualify-sync.service \
	plugin-qualify-sync.path plugin-qualify-sync.timer omx-track-latest.service omx-track-latest.timer; do
	f=$(ls /etc/systemd/system/"$u" /usr/lib/systemd/system/"$u" 2>/dev/null | head -1)
	w=$(ls /etc/systemd/system/*.wants/"$u" 2>/dev/null | head -1)
	printf '%s: %s; wanted by: %s\n' "$u" "${f:-not installed}" "${w:-none}"
done
ls /etc/systemd/system/*.d 2>/dev/null | head -40
export ZYNTHIAN_SYS_DIR=/zynthian/zynthian-sys
source /zynthian/zynthian-sys/scripts/zynthian_envars_extended.sh >/dev/null 2>&1
t "dpkg -l | grep -E 'omx-|plugin-'"; dpkg -l | grep -E 'omx-|plugin-'
t "git zynthian-ui HEAD"; git -C /zynthian/zynthian-ui rev-parse HEAD
t "git zynthian-sys HEAD"; git -C /zynthian/zynthian-sys rev-parse HEAD
t "plugin-hostd --version"; plugin-hostd --version; echo "exit $?"
t "omx-panel (no --version: usage exit code, package version)"; omx-panel >/dev/null 2>&1; echo "exit $?"; dpkg-query -W omx-panel
t "zyngine import"
(
	cd /zynthian/zynthian-ui && PYTHONPATH=/zynthian/zynthian-ui:/zynthian/zynthian-ui/zyngine \
		python3 -c 'from zyngine import zynthian_engine_plugin_hostd as m; print("import ok", m.__name__)'
	echo "exit $?"
)
t "lv2ls | wc -l"; lv2ls | wc -l
t "clap count"; find /usr/lib/clap -name '*.clap' | wc -l
t "plugin-qualify-sync --help (it has no --dry-run)"; plugin-qualify-sync --help >/dev/null 2>&1; echo "exit $?"
t "plugin-qualify-sync over empty search paths, state in /tmp (the narrowest run)"
plugin-qualify-sync --system --lv2-path /nonexistent --lv2-extra /nonexistent --clap-path /nonexistent --hostd-port 0 \
	--pin-file /tmp/q.pins --qualification-dir /tmp/q-rec --descriptor-dir /tmp/q-desc --state-file /tmp/q.json; echo "exit $?"
t "engine switches"; grep -HE 'ZYNTHIAN_MODHOST_BACKEND|ZYNTHIAN_PLUGIN_ENGINE' /zynthian/config/* 2>&1
t "os"; head -3 /etc/os-release; cat /zynthian/build_info.txt
PROBE
sudo chmod +x "$mrg/usr/local/sbin/omx-boot-probe"

say "boot part: ${BOOT_SECS}s"
sudo SYSTEMD_SECCOMP=0 timeout -k 20 $((BOOT_SECS + 40)) systemd-nspawn --setenv=SYSTEMD_SECCOMP=0 -D "$mrg" --boot \
	--console=pipe --machine=omx-boot-test --resolv-conf=off --register=no \
	systemd.show_status=1 </dev/null >"$ev/console.log" 2>&1 &
sleep 20
pid=$(pgrep -f '[q]emu-aarch64-static /usr/lib/systemd/systemd' | head -1 || true)
if [ -n "$pid" ]; then
	ns() { sudo timeout 60 nsenter -t "$pid" -m -p -u -i -r "$@" || true; }
	for _ in $(seq 1 $((BOOT_SECS / 5))); do
		[ "$(ns systemctl is-system-running 2>&1)" != starting ] && break
		sleep 5
	done
	{
		echo "## systemctl is-system-running"; ns systemctl is-system-running
		echo "## systemctl list-units --failed"; ns systemctl list-units --failed --no-pager --plain
		echo "## systemctl list-jobs"; ns systemctl list-jobs --no-pager
		echo "## ps"; ns ps -eo pid,etime,args
		echo "## the units asked for"
		for u in zynthian.service jack2.service mod-host.service plugin-hostd.service omx-modgui-sync.service \
			plugin-qualify-sync.path plugin-qualify-sync.timer omx-track-latest.timer first_boot.service; do
			printf '%s: ' "$u"; ns systemctl show -p LoadState,ActiveState,SubState,Result,ExecMainStatus --value "$u" 2>&1 | tr '\n' ' '; echo
		done
		echo "## a trivial unit, to tell the emulation from the services"
		ns sh -c 'printf "[Service]\nType=oneshot\nExecStart=/bin/true\n" >/run/systemd/system/omx-true.service; systemctl daemon-reload; systemctl start omx-true.service; echo "start exit $?"; systemctl show -p Result,ExecMainStatus omx-true.service'
	} >"$ev/boot-state.txt" 2>&1
fi
killroot
sudo systemctl stop omx-boot-test.scope 2>/dev/null
wait || true

say "probe part"
sudo SYSTEMD_SECCOMP=0 systemd-nspawn -q -D "$mrg" --bind="$ev":/probe --resolv-conf=off --register=no /usr/local/sbin/omx-boot-probe || true
sudo chown -R "$(id -u):$(id -g)" "$ev"
