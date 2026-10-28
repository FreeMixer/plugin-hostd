# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#
# The spike's plugind engine, sourced by chain.sh, chain-e2e.sh and path-b.sh. The Zynthian engine that ships is the
# plugin-hostd engine of FreeMixer/zynthian-ui (branch vangelis, docs/zynthian/README.md); these tools drive the
# daemon's chain verb through the spike's engine, zynthian_engine_plugind and zynthian_plugind_chain, which that
# fork does not carry. The spike's patch is read from the commit of this repository it was last changed at, never
# kept beside the tools: SPIKE_ENGINE_PATCH names a local copy instead.
#
#   spike_engine_apply <zynthian-ui worktree at ZUI_SHA> <out-dir>
#
# Exit 2 with the reason named when the patch cannot be read or does not apply.
ZUI_SHA=f46b0189b6163472db39aa607369f397ed23b65a
SPIKE_REV=b0190da1278f00253964b038ae3624762805472c
SPIKE_PATCH_URL=https://raw.githubusercontent.com/FreeMixer/plugin-hostd/$SPIKE_REV/docs/zynthian/zynthian_engine_plugind.patch

spike_engine_apply() {
    local zui=$1 out=$2 patch=${SPIKE_ENGINE_PATCH:-}
    if [ -z "$patch" ]; then
        patch=$out/zynthian_engine_plugind.patch
        curl -fsSL --retry 5 -o "$patch" "$SPIKE_PATCH_URL" || {
            echo "the spike engine's patch could not be read from $SPIKE_PATCH_URL" >&2; return 2; }
    fi
    git -C "$zui" apply "$patch" || { echo "the spike engine's patch does not apply at zynthian-ui $ZUI_SHA" >&2; return 2; }
}
