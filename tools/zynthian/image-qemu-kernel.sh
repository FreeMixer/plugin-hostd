#!/bin/bash
# A generic arm64 kernel and a minimal initramfs that boot the ZynthianOS image on qemu's virt machine, for
# image-first-boot-qemu.sh (KERNEL=<dir>). The image's own Raspberry Pi kernel has no virtio block driver, so it
# cannot find a root disk on virt (the serial log of that attempt is in docs/zynthian/evidence/image/).
#
#   tools/zynthian/image-qemu-kernel.sh <empty dir>
#
# Debian trixie's linux-image-cloud-arm64 (virtio PCI built in, virtio_blk a module) gives vmlinuz; initrd.img is a
# cpio of busybox-static (arm64), the virtio_blk module and an init that loads it, waits for /dev/vda2 and runs
# the image's /sbin/init. The image's root file system has no modules for this kernel, and the boot partition (vfat)
# and the network (virtio_net) need some: the initramfs carries them and copies them into /lib/modules of the root
# file system it mounts (the VM's overlay, never the artefact), indexed with depmod.
# Needs: podman (debian:trixie, amd64).
set -euo pipefail
out=$(mkdir -p "${1:?empty dir}" && cd "$1" && pwd)
podman run --rm --platform linux/amd64 --security-opt label=disable -v "$out":/k debian:trixie sh -ec '
	dpkg --add-architecture arm64
	apt-get update -qq >/dev/null
	apt-get install -y -qq cpio xz-utils kmod >/dev/null
	cd /k
	v=$(apt-cache depends linux-image-cloud-arm64:arm64 | sed -n "s/.*Depends: \(linux-image-.*\)/\1/p" | head -1)
	apt-get download "$v" busybox-static:arm64 >/dev/null
	dpkg-deb -x linux-image-*.deb kernel
	dpkg-deb -x busybox-static_*.deb bb
	cp kernel/boot/vmlinuz-* vmlinuz
	rm -rf rd && mkdir -p rd/bin rd/dev rd/proc rd/sys rd/newroot
	cp bb/usr/bin/busybox rd/bin/busybox
	xz -dc kernel/usr/lib/modules/*/kernel/drivers/block/virtio_blk.ko.xz >rd/virtio_blk.ko
	kv=$(ls kernel/usr/lib/modules)
	depmod -b kernel/usr "$kv"
	mkdir -p rd/modstage/lib/modules/$kv
	for m in vfat fat nls_ascii nls_cp437 nls_iso8859_1 virtio_net net_failover failover; do
		modprobe -d kernel/usr -S "$kv" --show-depends $m | sed "s/^insmod //"
	done | sort -u | while read -r f; do
		r=${f#*/lib/modules/$kv/}
		mkdir -p "rd/modstage/lib/modules/$kv/$(dirname "$r")"; cp "$f" "rd/modstage/lib/modules/$kv/$r"
	done
	depmod -b rd/modstage "$kv"
	mv rd/modstage/lib/modules/$kv rd/modules; rm -rf rd/modstage
	echo "$kv" >rd/kver
	cat >rd/init <<INIT
#!/bin/busybox sh
/bin/busybox --install -s /bin
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs dev /dev
insmod /virtio_blk.ko
i=0; while [ ! -b /dev/vda2 ] && [ \$i -lt 60 ]; do sleep 1; i=\$((i+1)); done
mount -t ext4 /dev/vda2 /newroot || { echo "initrd: no root"; exec sh; }
kv=\$(cat /kver)
if [ ! -d /newroot/lib/modules/\$kv ]; then mkdir -p /newroot/lib/modules && cp -a /modules /newroot/lib/modules/\$kv; fi
umount /proc /sys /dev
exec switch_root /newroot /sbin/init
INIT
	chmod +x rd/init
	(cd rd && find . | cpio -o -H newc --quiet | gzip -9) >initrd.img
	rm -rf kernel bb rd
	ls -la vmlinuz initrd.img
'
sha256sum "$out"/*.deb "$out"/vmlinuz "$out"/initrd.img
