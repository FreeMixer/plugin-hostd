#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# The release set on a Zynthian Pi: what is installed, what the apt channel offers, what the forks stand at. Read
# only; it does not run apt-get update (the lists show what the last update saw: run `apt-get update` first when the
# channel is the question).
#
#   ssh root@<pi> 'bash -s' < tools/zynthian/pi-packages.sh
#
# Prints one row per package: name, installed, candidate, and BEHIND when they differ.
set -u
PKGS=${PKGS:-"plugin-hostd plugin-hostd-contract libmod-host-protocol0 omx-clap-host libomx-clap-core1 omx-panel plugin-qualify omx-plugins omx-plugins-lv2 omx-plugins-clap omx-contract-data omx-qualification-records openmixer-release"}
printf '%-30s %-22s %-22s\n' package installed candidate
for p in $PKGS; do
	inst=$(dpkg-query -W -f '${Version}' "$p" 2>/dev/null)
	cand=$(apt-cache policy "$p" 2>/dev/null | awk '/Candidate:/{print $2}')
	flag=""
	[ -n "$cand" ] && [ "$cand" != "(none)" ] && [ "$inst" != "$cand" ] && flag=BEHIND
	printf '%-30s %-22s %-22s %s\n' "$p" "${inst:--}" "${cand:--}" "$flag"
done
echo
echo "forks:"
for r in zynthian-ui zynthian-sys; do
	d=/zynthian/$r
	[ -d "$d" ] && echo "  $r $(git -C "$d" rev-parse --short=8 HEAD 2>/dev/null) on $(git -C "$d" rev-parse --abbrev-ref HEAD 2>/dev/null); fork remote: $(git -C "$d" remote get-url fork 2>/dev/null || git -C "$d" remote -v | head -1)"
done
echo "daemon reports: $(printf 'help\n' | timeout 3 nc -q1 127.0.0.1 5555 2>/dev/null | head -1)"
echo "units: $(systemctl is-active zynthian jack2 plugin-hostd mod-host omx-track-latest.timer 2>/dev/null | tr '\n' ' ')"
