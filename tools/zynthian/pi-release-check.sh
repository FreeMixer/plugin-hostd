#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# Which releases of the Zynthian set are published on GitHub right now, against the floors a session wants. Runs
# anywhere with gh and network (REST only); it never touches the Pi.
#
#   tools/zynthian/pi-release-check.sh [repo=floor ...]
#
# With no arguments it checks the default floors below, in the order the Pi takes them. Prints OK (latest is at or
# above the floor, with the published time), BEHIND (latest is below the floor: not published yet, wait or stop) or
# MISSING. Exit 1 when any is BEHIND or MISSING. Packages come from the apt channel after the release workflow ends:
# a release listed here is a tag, pi-packages.sh on the Pi says whether the packages are there.
set -u
ORG=${ORG:-FreeMixer}
FLOORS=("$@")
[ ${#FLOORS[@]} -eq 0 ] && FLOORS=(plugin-hostd=0.15.3 omx-clap-core=0.25.1 omx-panel=0.7.2 plugin-qualify=0.17.5 omx-plugins=0.16.0)
rc=0
for f in "${FLOORS[@]}"; do
	repo=${f%%=*}; want=${f#*=}
	row=$(gh api "repos/$ORG/$repo/releases?per_page=30" --jq '[.[]|select(.draft==false and .prerelease==false)][0]|"\(.tag_name) \(.published_at)"' 2>/dev/null)
	if [ -z "$row" ] || [ "$row" = "null null" ]; then printf 'MISSING %-16s no release\n' "$repo"; rc=1; continue; fi
	tag=${row%% *}; have=${tag#v}
	if [ "$(printf '%s\n%s\n' "$want" "$have" | sort -V | head -1)" = "$want" ]; then
		printf 'OK      %-16s %s (floor %s) published %s\n' "$repo" "$tag" "$want" "${row#* }"
	else
		printf 'BEHIND  %-16s latest %s, floor %s\n' "$repo" "$tag" "$want"; rc=1
	fi
done
exit $rc
