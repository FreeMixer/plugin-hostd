#!/bin/bash
# Copy what a booted VM left in its overlay (the logs and the qualification state that the serial console does not
# carry) to an evidence directory: the overlay is flattened to a raw file, its root partition mounted read-write (the
# overlay is the VM's own copy; the image is its read-only backing file), the files copied, everything released.
#
#   tools/zynthian/image-qemu-harvest.sh <work-dir> <evidence-dir> <name>
#
# The VM must be stopped. Needs: sudo, podman; disk for the flattened copy (sparse, about the image size).
set -euo pipefail
work=$(cd "${1:?work dir}" && pwd)
ev=$(mkdir -p "${2:?evidence dir}" && cd "$2" && pwd)
name=${3:?name}
QEMU_IMAGE=${QEMU_IMAGE:-localhost/omx-qemu-aarch64}
mnt=$work/harvest-mnt
cleanup() {
	set +e
	sudo umount "$mnt" 2>/dev/null
	rm -f "$work/vm/overlay.raw"
	rmdir "$mnt" 2>/dev/null
}
trap cleanup EXIT
mkdir -p "$mnt"
# the overlay flattened to a sparse raw file (rootless podman cannot attach it with qemu-nbd), then loop-mounted
podman run --rm --security-opt label=disable -v "$work":/w "$QEMU_IMAGE" \
	qemu-img convert -f qcow2 -O raw -S 64k /w/vm/overlay.qcow2 /w/vm/overlay.raw
# the root partition starts at sector 1056768 (the resize moves its end, not its start)
sudo mount -o offset=$((1056768 * 512)) "$work/vm/overlay.raw" "$mnt"
{
	echo "## df"; df -h "$mnt"
	echo "## /root/first_boot.log"; sudo cat "$mnt/root/first_boot.log"
	echo "## qualify-sync state"; sudo ls -la "$mnt/var/lib/omx/" 2>&1
	echo "## qualification records"; sudo find "$mnt/var/lib/omx/qualification" -type f 2>/dev/null | wc -l
	echo "## qualify-sync.json: plugins by outcome and code"
	sudo cat "$mnt/var/lib/omx/qualify-sync.json" | python3 -I -c '
import json, sys, collections
d = json.load(sys.stdin)
c = collections.Counter()
for e in d["entries"].values():
    for p in e["plugins"]:
        c[(e["format"], p["outcome"], p.get("code", ""))] += 1
for k, n in sorted(c.items()):
    print(n, *k)
print("entries", len(d["entries"]))
' 2>&1
	echo "## pins"; sudo wc -l "$mnt/var/lib/omx/qualified.pins" 2>&1
	echo "## descriptors"; sudo find "$mnt/var/lib/omx/descriptors" -type f 2>/dev/null | wc -l
	echo "## ssh host keys"; sudo ls -la --time-style=full-iso "$mnt"/etc/ssh/ssh_host_*_key.pub 2>&1
	echo "## zynthian.service enabled?"; sudo ls "$mnt"/etc/systemd/system/*.wants/zynthian.service 2>&1
	echo "## partition"; fdisk -l "$work/vm/overlay.raw" 2>&1 | tail -4
	echo "## LV2 cache files"; sudo ls "$mnt/zynthian/config/jalv" 2>/dev/null | wc -l
} >"$ev/harvest-$name.txt" 2>&1
sudo umount "$mnt"
rm -f "$work/vm/overlay.raw"
