#!/bin/bash
# The Pi 5 stress run of a Zynthian with plugin-hostd: chains of 4 plugins at 1, 2, 4, 8 and 16 chains, hosted grouped
# (one plugin-hostd worker per chain), alone (one worker per plugin) and by jalv (one process per plugin), each level
# held and measured on the device by stress-pi5.py.
#
#   tools/zynthian/stress-pi5.sh [<ssh target>] [<local out dir>]
#
# The run collects everything under /root/omx-stress-<date>/ on the device and copies it back to <local out dir>
# (default ./omx-stress-<date>). Environment: HOLD (60 s), LEVELS (1,2,4,8,16), MODES (grouped,alone,jalv),
# PORT (5590, the run's own plugin-hostd, started with zynthian-sys's plugin-hostd-start.sh), SSH_OPTS.
# It never reboots the device. It refuses to start with less than 2 GB free on the device's root filesystem.
set -u -o pipefail
target=${1:-root@zynthian.local}
here=$(cd "$(dirname "$0")" && pwd)
HOLD=${HOLD:-60}
LEVELS=${LEVELS:-1,2,4,8,16}
MODES=${MODES:-grouped,alone,jalv}
PORT=${PORT:-5590}
ssh_() { ssh ${SSH_OPTS:-} "$target" "$@"; }

stamp=$(ssh_ 'date -u +%Y%m%dT%H%MZ') || { echo "cannot reach $target" >&2; exit 1; }
dir=/root/omx-stress-$stamp
out=${2:-./omx-stress-$stamp}
mkdir -p "$out"

free_kb=$(ssh_ "df --output=avail -k / | tail -1 | tr -d ' '")
if [ "${free_kb:-0}" -lt 2097152 ]; then
	echo "only ${free_kb} kB free on the device: not starting" >&2
	exit 1
fi

# What the run ran on: the commits, the packages, the units, JACK's rate and quantum
ssh_ "mkdir -p $dir && cd $dir && {
	echo \"date_utc \$(date -u +%FT%TZ)\"
	echo \"zynthian_ui \$(git -C /zynthian/zynthian-ui rev-parse HEAD)\"
	echo \"zynthian_sys \$(git -C /zynthian/zynthian-sys rev-parse HEAD)\"
	echo \"mod_host_unit_sha256 \$(sha256sum /etc/systemd/system/mod-host.service | cut -d' ' -f1)\"
	echo \"jack_rate \$(jack_samplerate)\"
	echo \"jack_quantum \$(jack_bufsize)\"
	echo \"jackd \$(pgrep -a -f '^/usr/bin/jackd ' | cut -d' ' -f2-)\"
	echo \"kernel \$(uname -r)\"
	echo \"cpus \$(nproc)\"
	echo \"governor \$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)\"
	echo \"model \$(tr -d '\\0' </proc/device-tree/model)\"
	echo \"mem_total_mb \$(awk '/MemTotal/{print int(\$2/1024)}' /proc/meminfo)\"
	for u in zynthian mod-host mod-ui omx-modgui-sync; do echo \"unit_\$u \$(systemctl is-active \$u)/\$(systemctl is-enabled \$u 2>/dev/null)\"; done
} > device.txt
dpkg-query -W -f '\${Package} \${Version}\n' plugin-hostd plugin-qualify omx-plugins omx-plugins-lv2 omx-clap-host \
	omx-panel omx-contract-data jalv jackd2 lsp-plugins-lv2 calf-plugins x42-plugins 2>/dev/null > packages.txt
df -k / > df-before.txt
pgrep -fa 'mod-host|plugin-hostd|jalv' > processes-before.txt || true" || exit 1

scp -q ${SSH_OPTS:-} "$here/stress-pi5.py" "$target:$dir/stress-pi5.py" || exit 1

# The run outlives the ssh session: it is started detached and waited for by its exit file
ssh_ "cd $dir && setsid nohup sh -c '/zynthian/venv/bin/python3 -I stress-pi5.py --out $dir --port $PORT \
	--hold $HOLD --levels $LEVELS --modes $MODES > run.log 2>&1; echo \$? > exit' </dev/null >/dev/null 2>&1 &"
echo "running on $target in $dir"
while ! ssh_ "test -f $dir/exit"; do
	sleep 15
	ssh_ "tail -1 $dir/run.log" 2>/dev/null
done
rc=$(ssh_ "cat $dir/exit")

# After: the daemon this run started is gone, Zynthian still runs, its screen, the disk
ssh_ "cd $dir && {
	df -k / > df-after.txt
	pgrep -fa 'mod-host|plugin-hostd|jalv' > processes-after.txt || true
	echo \"zynthian \$(systemctl is-active zynthian)\" > after.txt
	echo \"xruns_zynthian_total \$(journalctl -u zynthian -o cat --no-pager -n 20000 | grep -o 'XRUN! =>count: [0-9]*' | tail -1)\" >> after.txt
	DISPLAY=:0 XAUTHORITY=/root/.Xauthority timeout 15 scrot -o captures/l99-after-zynthian.png
	echo \"dir_kb \$(du -sk $dir | cut -f1)\" >> after.txt
}"
rsync -a ${SSH_OPTS:+-e "ssh $SSH_OPTS"} "$target:$dir/" "$out/" || exit 1
echo "stress-pi5.py exit $rc; results in $out"
exit "$rc"
