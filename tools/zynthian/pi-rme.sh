#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# Does a Zynthian Pi see its USB audio interface (an RME Babyface), and does Zynthian's jackd run on it, at which
# rates. Read only: it restarts nothing and changes no setting.
#
#   ssh root@<pi> 'bash -s' < tools/zynthian/pi-rme.sh        (or run it on the Pi)
#
# Lines start PASS, FAIL or NOTE. Exit 1 when the kernel does not list the card, 2 when the card is there but jackd
# does not run on it, else 0. CARD overrides the name to look for (default: Babyface|Fireface|RME).
set -u
CARD=${CARD:-'Babyface|Fireface|RME'}
rc=0
echo "== kernel"
cards=$(cat /proc/asound/cards 2>/dev/null)
echo "$cards" | sed 's/^/  /'
line=$(echo "$cards" | grep -i -E "$CARD" | head -1)
if [ -z "$line" ]; then
	echo "FAIL the kernel lists no card matching '$CARD' in /proc/asound/cards"
	echo "NOTE USB devices: $(lsusb 2>/dev/null | grep -i -E 'rme|2a39' || echo 'none from RME (vendor 2a39)')"
	echo "NOTE the Babyface must run in class compliant mode to work on a Pi; if lsusb lists it and no card appears, read dmesg below"
	dmesg 2>/dev/null | grep -i -E 'usb|snd|uac|babyface|fireface' | tail -15 | sed 's/^/  dmesg /'
	exit 1
fi
idx=$(echo "$line" | awk '{print $1}')
id=$(echo "$line" | sed -E 's/^ *[0-9]+ \[([^ ]+) *\].*/\1/')
echo "PASS the kernel has card $idx ($id)"
echo "NOTE playback and capture devices:"; { aplay -l; arecord -l; } 2>/dev/null | grep -E "^card $idx" | sed 's/^/  /'
for s in /proc/asound/card$idx/stream*; do
	[ -f "$s" ] && { echo "NOTE $s"; grep -E 'Playback|Capture|Rates|Channels|Format|Momentary freq' "$s" | sed 's/^/    /'; }
done
echo "NOTE clock the card runs on now: $(cat /proc/asound/card$idx/pcm0p/sub0/hw_params 2>/dev/null | tr '\n' ' ' || true)"
echo
echo "== jackd"
jp=$(pgrep -a -x jackd 2>/dev/null || pgrep -a -f '/usr/bin/jackd' | head -1)
if [ -z "$jp" ]; then echo "FAIL jackd is not running"; exit 2; fi
echo "  $jp"
dev=$(echo "$jp" | grep -o -E -- '-d +hw:[^ ]+' | head -1 | sed 's/.*hw://')
rate=$(echo "$jp" | grep -o -E -- '-r +[0-9]+' | head -1 | awk '{print $2}')
per=$(echo "$jp" | grep -o -E -- '-p +[0-9]+' | head -1 | awk '{print $2}')
nper=$(echo "$jp" | grep -o -E -- '-n +[0-9]+' | head -1 | awk '{print $2}')
echo "NOTE jackd device hw:${dev:-?}  rate ${rate:-?}  frames ${per:-?}  periods ${nper:-?}"
if echo "$dev" | grep -q -i -E "^($id|$idx)$"; then echo "PASS jackd runs on the interface (hw:$dev)"; else echo "FAIL jackd runs on hw:${dev:-?}, not on the interface ($id / $idx): the owner picks the card in Zynthian's Audio settings, then this is run again"; rc=2; fi
if command -v jack_samplerate >/dev/null; then
	echo "NOTE jack_samplerate $(jack_samplerate 2>&1)  jack_bufsize $(jack_bufsize 2>&1 | head -1)"
	echo "NOTE hardware ports: $(jack_lsp -t 2>/dev/null | grep -c -i 'system:')"
	jack_lsp 2>/dev/null | grep -E '^system:' | head -12 | sed 's/^/    /'
fi
echo
echo "== Zynthian's own setting (read only)"
for f in /zynthian/config/zynthian_envars.sh /zynthian/config/jackd.last_config; do
	[ -f "$f" ] && { echo "  $f"; grep -E 'SOUNDCARD|JACKD|AUDIO_(IN|OUT)|JACK_' "$f" | sed 's/^/    /'; }
done
echo "NOTE the rates Zynthian actually runs are the rate and frames above; the proofs are taken at that pair and the Pi's quantum list is in the runbook"
exit $rc
