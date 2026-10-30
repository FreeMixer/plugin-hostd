#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# What is running on a Zynthian Pi and how far it got, read only. It starts nothing, stops nothing and writes nothing.
#
#   ssh root@<pi> 'bash -s' < tools/zynthian/pi-status.sh        (or run it on the Pi)
#
# Prints, in order: the boot and whether the previous boot ended cleanly; the omx units (transient units made with
# systemd-run do not survive a power-off, so a missing unit is read from its files); the processes that measure
# CPU; the benchmark matrix directories with their row counts and last write; the qualification journal tail.
# The last line is MEASURING or IDLE. Exit status is 0 whenever it could read the device.
# UNITS overrides the unit names to look for (space separated).
set -u
UNITS=${UNITS:-"omx-requalify-20261029d omx-resync-clap-20261030 omx-matrix-resume-20261030"}
now=$(date +%s)
boot=$(date -d "$(uptime -s)" +%s 2>/dev/null || echo 0)
echo "== boot"
echo "now        $(date '+%F %T %Z')"
echo "up since   $(uptime -s)  ($(uptime -p))"
if command -v journalctl >/dev/null; then
	echo "boots      $(journalctl --list-boots --no-pager 2>/dev/null | tail -3 | tr '\n' ';')"
	echo "previous boot, last 3 lines (a clean stop ends with systemd 'Reached target' or 'Journal stopped'):"
	journalctl -b -1 -n 3 --no-pager -o short-iso 2>/dev/null | sed 's/^/  /' || true
fi
if command -v last >/dev/null; then
	echo "last -x:"; last -x -n 6 shutdown reboot 2>/dev/null | sed 's/^/  /'
fi
echo "throttled  $(vcgencmd get_throttled 2>/dev/null || echo 'vcgencmd not found')  (0x0 = no undervoltage seen since boot)"

busy=""
stale=""
echo
echo "== units"
for u in $UNITS; do
	st=$(systemctl show "$u" -p LoadState,ActiveState,SubState,Result,ActiveEnterTimestamp,ExecMainStartTimestamp,ExecMainExitTimestamp 2>/dev/null | tr '\n' ' ')
	ls=$(systemctl show "$u" -p LoadState --value 2>/dev/null)
	as=$(systemctl show "$u" -p ActiveState --value 2>/dev/null)
	echo "$u: $st"
	if [ "$as" = active ] || [ "$as" = activating ]; then
		busy="$busy $u"
		echo "  RUNNING: do not stop it"
	elif [ "$ls" = not-found ] || [ -z "$ls" ]; then
		echo "  not loaded: never started on this boot, finished and was collected, or lost at a power-off (a transient unit does not survive one)"
	fi
	journalctl -u "$u" -n 4 --no-pager -o short-iso 2>/dev/null | sed 's/^/  | /'
done
echo "all omx units and timers:"
systemctl list-units --all --no-legend --no-pager 'omx-*' 2>/dev/null | sed 's/^/  /'
systemctl list-timers --no-pager 'omx-*' 2>/dev/null | sed 's/^/  /'
echo "failed units:"; systemctl --failed --no-legend --no-pager 2>/dev/null | sed 's/^/  /'

echo
echo "== processes that measure"
procs=$(pgrep -a -f 'matrix\.py|bench\.py|plugin-qualify|stress-pi5|omx-clap-host --probe|instrument-proof' 2>/dev/null | grep -v pgrep | grep -v pi-status)
[ -n "$procs" ] && echo "$procs" | cut -c1-200 | sed 's/^/  /' || echo "  none"
[ -n "$procs" ] && busy="$busy processes"

echo
echo "== benchmark matrices"
for d in /root/omx-matrix-* /root/omx-stress-*; do
	[ -d "$d" ] || continue
	rows=-; [ -f "$d/matrix.csv" ] && rows=$(( $(wc -l < "$d/matrix.csv") - 1 ))
	docs=$(ls "$d/docs" 2>/dev/null | wc -l)
	last=$(find "$d" -type f -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1)
	lt=${last%% *}; lp=${last#* }
	age=$(( now - ${lt%.*} ))
	flag=""; [ "$age" -lt 600 ] && flag="  WRITTEN IN THE LAST 10 MINUTES"
	[ "$boot" -gt 0 ] && [ "${lt%.*}" -lt "$boot" ] && [ "$rows" != - ] && { flag="$flag  last write before this boot"; stale="$stale $d"; }
	echo "  $d  rows=$rows docs=$docs last=$(date -d @"${lt%.*}" '+%F %T') ($lp)$flag"
	[ -f "$d/start.sh" ] && echo "    resume: bash $d/start.sh   (skips cells already in matrix.csv)"
done
ls -d /root/omx-matrix-* >/dev/null 2>&1 || echo "  none"

echo
echo "== qualification records"
for d in /var/lib/omx /var/lib/plugin-qualify; do
	[ -d "$d" ] && echo "  $d: $(find "$d" -type f -name '*.json' 2>/dev/null | wc -l) json files, newest $(find "$d" -type f -printf '%TF %TT\n' 2>/dev/null | sort | tail -1)"
done
echo
[ -n "$stale" ] && [ -z "$busy" ] && echo "POSSIBLY INTERRUPTED: nothing runs and these last wrote before this boot:$stale (compare with the clean-stop lines above; a finished run looks the same)"
if [ -n "$busy" ]; then echo "MEASURING:$busy"; else echo IDLE; fi
