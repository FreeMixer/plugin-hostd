#!/bin/bash
# Boot the ZynthianOS image (tools/zynthian/image-build.sh's output) under full emulation, a Raspberry Pi stand-in
# on the build host: qemu-system-aarch64, machine virt, TCG (no aarch64 KVM on an x86_64 host). The artefact is
# never written: the VM runs on a qcow2 overlay whose backing file is the decompressed raw image.
#
#   tools/zynthian/image-first-boot-qemu.sh <zynthianos-vangelis-omx.img.xz> <work-dir> <evidence-dir> first|<name>
#
# first   a new overlay (DISK_SIZE, default 32G, a card bigger than the image so that the root resize has work to do),
#         then the first boot; any other name (again) = a boot of the overlay as it is, logged as serial-<name>.log.
# EXTRA_APPEND  more kernel command line words (systemd.wants=zynthian.service starts the UI service, which a first boot
#         on hardware the autoconfig does not know leaves disabled).
# KERNEL  pi (default): the image's own Raspberry Pi kernel and initramfs from its boot partition; or the directory of
#         a generic arm64 kernel (vmlinuz, optionally initrd.img) that boots on virt, root on virtio-blk.
# The serial console is the log: every line stamped with the seconds since the start of the run, and the journal
# forwarded to it. TIMEOUT (seconds, default 2400) bounds the run; stop earlier with: podman kill omx-qemu.
# QEMU_IMAGE names a container image with qemu-system-aarch64 and qemu-img (default localhost/omx-qemu-aarch64: a
# Fedora container with qemu-system-aarch64-core and qemu-img installed). Needs: sudo (loop mount of the boot
# partition), podman, xz, python3. Checks the xz's sha256 before and after.
set -euo pipefail

src=${1:?image .img.xz}
work=$(mkdir -p "${2:?work dir}" && cd "$2" && pwd)
ev=$(mkdir -p "${3:?evidence dir}" && cd "$3" && pwd)
mode=${4:?first|again}
KERNEL=${KERNEL:-pi}
DISK_SIZE=${DISK_SIZE:-32G}
TIMEOUT=${TIMEOUT:-2400}
QEMU_IMAGE=${QEMU_IMAGE:-localhost/omx-qemu-aarch64}
img=$work/$(basename "${src%.xz}")
vm=$work/vm
log=$ev/serial-$mode.log
say() { printf '%s %s\n' "$(date +%T)" "$*" | tee -a "$ev/run-$mode.log"; }
pq() { podman run --rm --security-opt label=disable -v "$work":/w "$QEMU_IMAGE" "$@"; }

: >"$ev/run-$mode.log"
say "artefact sha256 before: $(sha256sum "$src" | cut -d' ' -f1)"
mkdir -p "$vm"
if [ ! -e "$img" ]; then say "decompressing"; xz -dkc -T0 "$src" >"$img"; fi

if [ "$KERNEL" = pi ]; then
	if [ ! -e "$vm/Image" ]; then
		mkdir -p "$vm/boot"
		loop=$(sudo losetup -r -fP --show "$img")
		sudo mount -o ro "${loop}p1" "$vm/boot"
		# kernel8.img is the 4 KiB-page arm64 kernel (gzip); the 16 KiB-page kernel_2712.img is the Pi 5's
		gzip -dc "$vm/boot/kernel8.img" >"$vm/Image" || cp "$vm/boot/kernel8.img" "$vm/Image"
		cp "$vm/boot/initramfs8" "$vm/initrd"
		cp "$vm/boot/cmdline.txt" "$ev/image-cmdline.txt"
		sudo umount "$vm/boot"; sudo losetup -d "$loop"; rmdir "$vm/boot"
	fi
	kernel=Image initrd=initrd
	root='root=PARTUUID=e249d476-02'
else
	cp "$KERNEL"/vmlinuz "$vm/Image-generic"; kernel=Image-generic initrd=""
	[ -e "$KERNEL/initrd.img" ] && { cp "$KERNEL/initrd.img" "$vm/initrd-generic"; initrd=initrd-generic; }
	root='root=/dev/vda2'
fi

if [ "$mode" = first ]; then
	rm -f "$vm/overlay.qcow2"
	pq qemu-img create -q -f qcow2 -F raw -b "/w/$(basename "$img")" /w/vm/overlay.qcow2 "$DISK_SIZE"
fi

# the image's own command line without its display and splash words, plus the serial console and the journal on it
append="$root rootfstype=ext4 rootwait fsck.repair=yes console=ttyAMA0,115200 earlycon=pl011,0x9000000 printk.time=1 loglevel=6 systemd.show_status=1 systemd.journald.forward_to_console=1 systemd.journald.max_level_console=info ${EXTRA_APPEND:-}"
say "boot ($mode, kernel $KERNEL), timeout ${TIMEOUT}s"
start=$(date +%s)
podman rm -f omx-qemu >/dev/null 2>&1 || true
set +e
timeout "$TIMEOUT" podman run --rm --name omx-qemu --security-opt label=disable -v "$work":/w "$QEMU_IMAGE" \
	qemu-system-aarch64 -machine virt -cpu cortex-a72 -smp 4 -m 4G -nographic -monitor none \
	-kernel "/w/vm/$kernel" ${initrd:+-initrd "/w/vm/$initrd"} -append "$append" \
	-drive if=none,id=d0,file=/w/vm/overlay.qcow2,format=qcow2 -device virtio-blk-pci,drive=d0 \
	-netdev user,id=n0,hostfwd=tcp::2222-:22 -device virtio-net-pci,netdev=n0 -device virtio-rng-pci </dev/null 2>&1 |
	python3 -I -c '
import sys, time
t0 = time.time()
for line in sys.stdin.buffer:
    sys.stdout.write("%7.1f %s\n" % (time.time() - t0, line.decode("utf-8", "replace").rstrip("\r\n")))
    sys.stdout.flush()
' >"$log"
rcs=("${PIPESTATUS[@]}"); set -e
say "podman exit ${rcs[0]}"
say "qemu ended after $(($(date +%s) - start)) s; serial log $(wc -c <"$log") bytes"
say "artefact sha256 after: $(sha256sum "$src" | cut -d' ' -f1)"
