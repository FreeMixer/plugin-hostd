// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
#ifndef PLUGIN_HOSTD_VOCABULARY_H
#define PLUGIN_HOSTD_VOCABULARY_H
/*
 * GENERATED — DO NOT EDIT BY HAND.
 * Produced by `omx-contract render --target c` from FreeMixer/plugin-hostd's data/: the vocabulary
 * (docs/data-layout.md). A code is OMX_ and the code in upper snake case; a word is OMX_<ITEM>_<NAME>, each words
 * item with its _COUNT and an _INIT of its words in their order. A consumer writes and compares these, never a
 * literal of its own.
 */

/* PLUGIN_HOSTD_REPLY_CODES (data/verbs.json) */
#define OMX_REPLY_PLUGIN_HOSTD_INVALID_OPERATION "reply.plugin-hostd.invalid-operation" ///< mod-host's ERR_INVALID_OPERATION, answered by the daemon for a line outside the grammar of one of its own verbs
#define OMX_REPLY_PLUGIN_HOSTD_INSTANCE_UNKNOWN "reply.plugin-hostd.instance-unknown" ///< mod-host's ERR_INSTANCE_NON_EXISTS, answered by the daemon for an instance no add made
#define OMX_REPLY_PLUGIN_HOSTD_PLACEMENT_INVALID "reply.plugin-hostd.placement-invalid" ///< PHD_ERR_PLACEMENT_INVALID: not a placement, or not valid here
#define OMX_REPLY_PLUGIN_HOSTD_NO_BACKEND "reply.plugin-hostd.no-backend" ///< PHD_ERR_NO_BACKEND: no worker program for the scheme
#define OMX_REPLY_PLUGIN_HOSTD_WORKER_SPAWN "reply.plugin-hostd.worker-spawn" ///< PHD_ERR_WORKER_SPAWN: the worker is not up
#define OMX_REPLY_PLUGIN_HOSTD_REPLAY "reply.plugin-hostd.replay" ///< PHD_ERR_REPLAY: the name of a refused replay on stderr, never a reply
#define OMX_REPLY_PLUGIN_HOSTD_GAVE_UP "reply.plugin-hostd.gave-up" ///< PHD_ERR_GAVE_UP: the storm bound is spent for that placement
#define OMX_REPLY_PLUGIN_HOSTD_NO_SUCH_WORKER "reply.plugin-hostd.no-such-worker" ///< PHD_ERR_NO_SUCH_WORKER: no such worker
#define OMX_REPLY_PLUGIN_HOSTD_VERB_DROPPED "reply.plugin-hostd.verb-dropped" ///< PHD_ERR_VERB_DROPPED: the worker died on this very command and the daemon dropped it
#define OMX_REPLY_PLUGIN_HOSTD_PIN_ABSENT "reply.plugin-hostd.pin-absent" ///< PHD_ERR_PIN_ABSENT: the plugin has no pin, or its layout pin is in a scheme this version does not know
#define OMX_REPLY_PLUGIN_HOSTD_PIN_BINARY_MISMATCH "reply.plugin-hostd.pin-binary-mismatch" ///< PHD_ERR_PIN_BINARY_MISMATCH: a pinned file is missing or its SHA-256 differs
#define OMX_REPLY_PLUGIN_HOSTD_PIN_LAYOUT_MISMATCH "reply.plugin-hostd.pin-layout-mismatch" ///< PHD_ERR_PIN_LAYOUT_MISMATCH: the parameter layout after init differs from the layout pin
#define OMX_REPLY_PLUGIN_HOSTD_NO_PARAM_CONTRACT "reply.plugin-hostd.no-param-contract" ///< PHD_ERR_NO_PARAM_CONTRACT: the host holds no checked unit and scale for this parameter
#define OMX_REPLY_PLUGIN_HOSTD_LV2_ADAPTER_REFUSED "reply.plugin-hostd.lv2-adapter-refused" ///< PHD_ERR_LV2_ADAPTER_REFUSED: the lv2-clap worker's LV2 adapter cannot run this plugin
#define OMX_REPLY_PLUGIN_HOSTD_NO_NOTE_INPUT "reply.plugin-hostd.no-note-input" ///< PHD_ERR_NO_NOTE_INPUT: the instance's plugin takes no notes
#define OMX_REPLY_PLUGIN_HOSTD_NOTES_BY_JACK "reply.plugin-hostd.notes-by-jack" ///< PHD_ERR_NOTES_BY_JACK: the instance's worker takes no notes on its socket
#define OMX_REPLY_PLUGIN_HOSTD_NO_PRESET_LIST "reply.plugin-hostd.no-preset-list" ///< PHD_ERR_NO_PRESET_LIST: the instance's worker cannot list the plugin's presets
#define OMX_REPLY_PLUGIN_HOSTD_PIN_REFUSED "reply.plugin-hostd.pin-refused" ///< PHD_ERR_PIN_REFUSED: the plugin's pin carries verdict=refused
#define OMX_REPLY_PLUGIN_HOSTD_NOTE_QUEUE_FULL "reply.plugin-hostd.note-queue-full" ///< PHD_ERR_NOTE_QUEUE_FULL: the instance's worker has no room for this note before its next block
#define OMX_REPLY_PLUGIN_HOSTD_CHAIN_UNKNOWN_INSTANCE "reply.plugin-hostd.chain-unknown-instance" ///< PHD_ERR_CHAIN_UNKNOWN_INSTANCE: a member is an instance no add made
#define OMX_REPLY_PLUGIN_HOSTD_CHAIN_DUPLICATE "reply.plugin-hostd.chain-duplicate" ///< PHD_ERR_CHAIN_DUPLICATE: an instance is named twice in one chain
#define OMX_REPLY_PLUGIN_HOSTD_CHAIN_INSTANCE_BUSY "reply.plugin-hostd.chain-instance-busy" ///< PHD_ERR_CHAIN_INSTANCE_BUSY: a member is already in another chain
#define OMX_REPLY_PLUGIN_HOSTD_CHAIN_MIXED_FORMAT "reply.plugin-hostd.chain-mixed-format" ///< PHD_ERR_CHAIN_MIXED_FORMAT: no one worker program runs every member
#define OMX_REPLY_PLUGIN_HOSTD_NO_SUCH_CHAIN "reply.plugin-hostd.no-such-chain" ///< PHD_ERR_NO_SUCH_CHAIN: a chain no chain line declared
#define OMX_REPLY_PLUGIN_HOSTD_PRESET_NOT_OFFERED "reply.plugin-hostd.preset-not-offered" ///< PHD_ERR_PRESET_NOT_OFFERED: a stable name the plugin does not offer
#define OMX_REPLY_PLUGIN_HOSTD_PRESET_INVALID "reply.plugin-hostd.preset-invalid" ///< PHD_ERR_PRESET_INVALID: a preset file or path that is not the preset format
#define OMX_REPLY_PLUGIN_HOSTD_PRESET_NEEDS_STATE "reply.plugin-hostd.preset-needs-state" ///< PHD_ERR_PRESET_NEEDS_STATE: a preset file that carries state for a worker that cannot take state
#define OMX_REPLY_PLUGIN_HOSTD_PRESET_PLUGIN_CHANGED "reply.plugin-hostd.preset-plugin-changed" ///< PHD_ERR_PRESET_PLUGIN_CHANGED: the preset file's plugin id, version or fingerprint is not the instance's
#define OMX_REPLY_PLUGIN_HOSTD_LOAD_REFUSED "reply.plugin-hostd.load-refused" ///< PHD_ERR_LOAD_REFUSED: the plugin refused the preset or the state its file carries
#define OMX_REPLY_PLUGIN_HOSTD_DIR_NOT_WRITABLE "reply.plugin-hostd.dir-not-writable" ///< PHD_ERR_DIR_NOT_WRITABLE: descriptor_dir or qualification_dir cannot be made or written
#define OMX_REPLY_PLUGIN_HOSTD_DESCRIPTOR_ABSENT "reply.plugin-hostd.descriptor-absent" ///< PHD_ERR_DESCRIPTOR_ABSENT: no descriptor (panel) for the plugin's binary as it is now
#define OMX_REPLY_PLUGIN_HOSTD_DESCRIPTOR_PENDING "reply.plugin-hostd.descriptor-pending" ///< PHD_ERR_DESCRIPTOR_PENDING: the scan its add started has not written the descriptor (panel) yet
#define OMX_REPLY_PLUGIN_HOSTD_DESCRIPTOR_SCAN_FAILED "reply.plugin-hostd.descriptor-scan-failed" ///< PHD_ERR_DESCRIPTOR_SCAN_FAILED: the plugin's last scan wrote no descriptor (panel)

#endif /* PLUGIN_HOSTD_VOCABULARY_H */
