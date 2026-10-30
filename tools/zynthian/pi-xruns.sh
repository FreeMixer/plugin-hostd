#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# Xruns on a Zynthian Pi over a window of real audio: lines jackd logged, per minute. Read only.
#
#   ssh root@<pi> 'bash -s -- "<since>"' < tools/zynthian/pi-xruns.sh      since as journalctl takes it, default "30 min ago"
#
# It counts the xrun lines in the jack2 unit's journal (jackd reports them there) and in the daemon's, and prints the
# first and last. This is a count of log lines, not a hardware statement: the audible result is the owner's to judge.
set -u
since=${1:-"30 min ago"}
for u in jack2 plugin-hostd zynthian; do
	n=$(journalctl -u "$u" --since "$since" --no-pager 2>/dev/null | grep -c -i -E 'xrun|late|buffer under|delay of')
	echo "$u: $n xrun-like lines since '$since'"
	journalctl -u "$u" --since "$since" --no-pager -o short-iso 2>/dev/null | grep -i -E 'xrun|late|buffer under|delay of' | sed -n '1p;$p' | sed 's/^/    /'
done
command -v jack_samplerate >/dev/null && echo "jack $(jack_samplerate) Hz, $(jack_bufsize | head -1) frames now"
