#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# plugin-hostd --pin-files <uri>: the files a pin of the plugin holds, as an add collects them (pins_check). A copy of
# the LV2 fixture bundle whose manifest also names a presets file for the plugin, as mda Piano's and Surge XT's do: the
# presets file is listed, the bundle's file named for another plugin only is not, a plugin in no bundle exits 1 with
# its reason, and a CLAP uri lists its .clap file. plugin-qualify takes the list from here (plugin-qualify#228).
set -u
daemon=${1:-./plugin-hostd}
here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
failed=0
check() { if [ "$1" = 0 ]; then echo "ok   $2"; else echo "FAIL $2"; failed=1; fi; }

bundle=$work/lv2/presets-fixture.lv2
mkdir -p "$bundle"
cp "$here/plugin-hostd-fixture.lv2/plugin-hostd-fixture.ttl" "$bundle/"
: > "$bundle/plugin-hostd-fixture.so"
: > "$bundle/presets.ttl"
: > "$bundle/other.ttl"
cat > "$bundle/manifest.ttl" <<'TTL'
@prefix lv2:  <http://lv2plug.in/ns/lv2core#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<urn:plugin-hostd:test:gain> a lv2:Plugin ; lv2:binary <plugin-hostd-fixture.so> ;
    rdfs:seeAlso <plugin-hostd-fixture.ttl> , <presets.ttl> .
<urn:plugin-hostd:test:other> a lv2:Plugin ; lv2:binary <plugin-hostd-fixture.so> ; rdfs:seeAlso <other.ttl> .
TTL
printf 'lv2_path %s\n' "$work/lv2" > "$work/conf"

out=$("$daemon" -c "$work/conf" --pin-files urn:plugin-hostd:test:gain); rc=$?
want="root $bundle
file manifest.ttl
file plugin-hostd-fixture.so
file plugin-hostd-fixture.ttl
file presets.ttl"
[ $rc -eq 0 ] && [ "$out" = "$want" ]; check $? "an LV2 plugin: the manifest, its binary and every file the manifest names for it, presets.ttl included, and not other.ttl"
[ $rc -eq 0 ] || echo "$out" | sed 's/^/     /'

"$daemon" -c "$work/conf" --pin-files urn:plugin-hostd:test:absent >/dev/null 2>"$work/err"; rc=$?
[ $rc -eq 1 ] && grep -q 'in no bundle of lv2_path' "$work/err"; check $? "a plugin in no bundle exits 1 with the collector's reason ($rc: $(cat "$work/err"))"

# a manifest that names the plugin by a prefixed name (mda-lv2's, mod-mda-Piano's, whose uri is
# http://example.org/mda/Piano): the bundle is found, and a lookalike (mdap:Piano, mda:PianoRes) is no match
pbundle=$work/lv2/prefixed-fixture.lv2
mkdir -p "$pbundle"
: > "$pbundle/Piano.so"
: > "$pbundle/Piano.ttl"
: > "$pbundle/presets.ttl"
cat > "$pbundle/manifest.ttl" <<'TTL'
@prefix lv2:  <http://lv2plug.in/ns/lv2core#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix mda:  <http://example.org/mda/> .
@prefix mdap: <http://example.org/mda/presets#> .
mda:Piano a lv2:Plugin ; rdfs:seeAlso <Piano.ttl> ; lv2:binary <Piano.so> .
mdap:Piano-plain a <http://lv2plug.in/ns/ext/presets#Preset> ; lv2:appliesTo mda:Piano ; rdfs:seeAlso <presets.ttl> .
mda:PianoRes a lv2:Plugin ; lv2:binary <Piano.so> .
TTL
out=$("$daemon" -c "$work/conf" --pin-files http://example.org/mda/Piano); rc=$?
want="root $pbundle
file manifest.ttl
file Piano.ttl
file Piano.so"
[ $rc -eq 0 ] && [ "$out" = "$want" ]; check $? "an LV2 plugin the manifest names by a prefixed name is found: its binary and files, not the preset subject's (rc $rc)"
[ "$out" = "$want" ] || echo "$out" | sed 's/^/     /'

"$daemon" -c "$work/conf" --pin-files http://example.org/mda/Pian >/dev/null 2>"$work/err"; rc=$?
[ $rc -eq 1 ] && grep -q 'in no bundle of lv2_path' "$work/err"; check $? "a name that is only the start of a prefixed name is in no bundle ($rc)"

out=$("$daemon" -c "$work/conf" --pin-files "clap:/usr/lib/clap/some plugin.clap#org.example.x"); rc=$?
[ $rc -eq 0 ] && [ "$out" = "root /usr/lib/clap
file some plugin.clap" ]; check $? "a CLAP plugin: its .clap file beside its directory"
exit $failed
