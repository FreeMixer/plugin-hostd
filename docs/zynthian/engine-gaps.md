What the jalv and mod-ui engines give a chain, and what Path B gives
===================================================================

The two engines plugind replaces, read at zynthian-ui `f46b0189b616` (`jalv.py` is `zyngine/zynthian_engine_jalv.py`,
`modui.py` is `zyngine/zynthian_engine_modui.py`, `engine.py` is `zyngine/zynthian_engine.py`, `manager.py` is
`zyngine/zynthian_chain_manager.py`, `chain.py` is `zyngine/zynthian_chain.py`), against Path B as merged in #125
(`zynthian_engine_plugind.py` of `zynthian_engine_plugind.patch`; `spike-report.md:97-104` lists what it lacks) and
as this branch extends it (the strip, `zynthian_plugind_strip.py`). jalv is one engine and one process per LV2 plugin,
one processor per slot; mod-ui is ONE `Special` processor (`modui.py:67`) whose pedalboard, edited in mod-ui's own web
page, is the whole chain inside it.

"Matters" says whether the gap matters for a Zynthian chain of single-processor slots: yes, the chain does not work
as a chain without it; use, a user loses a feature but the chain runs; no, it does not touch the chain.

| What | jalv engine | mod-ui engine | Path B (#125) | Path B, this branch | Matters |
|---|---|---|---|---|---|
| add a plugin | a new engine and `jalv` process per processor (`manager.py:1427-1429`, `jalv.py:134`) | mod-ui's page adds it to the pedalboard; Zynthian hears `add` on the websocket (`modui.py:376-379`, `add_plugin_cb` `:517`) | `add <uri> <n>` in `start()` | unchanged | yes, had |
| add at a slot position | the chain inserts the slot (`chain.py:639-680`); autoconnect wires it | inside the pedalboard only, by mod-ui's own graph | the chain inserts; autoconnect wires it | the strip re-links from the new slot order on the rebuild (`connect`) | yes, had through autoconnect, now the strip's |
| remove a plugin | engine stopped when unused (`manager.py:1250-1251`) | `remove` on the websocket (`modui.py:381-387`, `remove_plugin_cb` `:654`) | `remove <n>` in `stop()` | the strip first takes the instance's links down (`disconnect`) and joins its neighbours, then `remove` | yes, healing was missing |
| order of processors in a slot sequence | JACK links made by autoconnect from `audio_routes` (`chain.py:335-347`, `autoconnect.py:1089-1097`) | the pedalboard's `connect`/`disconnect` (`modui.py:389-393`, `graph_connect_cb` `:674`) | autoconnect only: the engine says nothing about order | the strip's `connect` links between adjacent plugind stages, in slot order; `chain` (plugin-hostd#101) is the marked seam | yes, gap closed |
| move a processor | `chain.nudge_processor` + autoconnect (`chain.py:758-804`) | in the pedalboard | autoconnect only | the strip re-links: stale links `disconnect`ed, new ones `connect`ed | yes, gap closed |
| parallel processors in a slot | fan-out and implicit JACK summing (`chain.py:342-347`) | any graph the pedalboard draws | implicit summing through autoconnect | fan-out + an explicit mix element (declared gains); realisation refused `MIX_ELEMENT_ABSENT` with no mixer declared | not for single slots |
| presets: list, load | lilv presets, bank by bank (`jalv.py:1035-1051`) | pedalboards and per-effect presets (`modui.py:167-230`) | lilv (LV2), `preset_list`/`preset_get` (CLAP), `preset_load` | unchanged | use, had |
| presets: save, rename, delete, user banks | `save preset` to jalv and TTL editing (`jalv.py:973-1170`) | none in Zynthian (mod-ui's page) | none | none | use |
| parameters and controllers | from lilv (`jalv.py:328-555`), set with `symbol=value` (`:574-611`) | from mod-ui's `/effect/get` (`modui.py:519-641`), set with `param_set` on the websocket (`:299-305`) | the jalv base's lilv controllers, `param_set`/`param_get`; CLAP from `omx-clap-scan` | unchanged | yes, had |
| parameter feedback (plugin moves a control) | `#CTR>` lines parsed (`jalv.py:232-262`) | `param_set` from the websocket (`modui.py:401-402`, `set_param_cb` `:730`) | none: `output_set` is read for meters only | none | use |
| meters (output controls) | `monitors` command (`jalv.py:560-563`, `:264-280`) | none | `monitor_output` + `output_set` feedback | unchanged | no |
| bypass | the plugin's own bypass or enable port, if it has one (`jalv.py:342-346`, `:527-540`) | a host `:bypass` controller per plugin (`modui.py:629-643`), mod-host `bypass` | the plugin's own port only (the jalv base) | a host `:bypass` controller when the plugin has no bypass port, sent as mod-host `bypass <n> <0/1>` | yes, gap closed |
| MIDI learn | Zynthian's own, by controller (`manager.py:1626`, `:1796`) for any engine | the same; mod-ui's native learn is unused ("These MOD-UI native functions are not used!", `modui.py:761`) | the same (controllers are `zynthian_controller`s) | unchanged, not tested here | use, had |
| MIDI channel | jalv base, per-plugin workarounds (`jalv.py:937-951`) | MIDI devices enabled in mod-ui (`modui.py:704-728`) | the jalv base's `set_midi_chan` | unchanged | no (effects) |
| native plugin GUI | `jalv -s`, jalv.qt5/gtk3 (`jalv.py:802-817`), `minimize_autogenerated_gui` (`:916`) | mod-ui's web page | none | none | use |
| Zynthian custom widgets | per plugin URL (`jalv.py:876-881`, `get_user_custom_gui` `:901`) | none | none | none | use |
| path (file) parameters | `set <path> <value>` (`jalv.py:583-603`) | none | none | none | use |
| crash of one plugin | the jalv process dies; nothing respawns it in these files | mod-host dies with every plugin of the pedalboard | the daemon puts the worker back (its own suite) | unchanged | no |
| web configuration (zynapi) | class methods (`jalv.py:1188-1360`) | `modui.py:821-861` | none | none | no |

The gaps that matter for a chain of single-processor slots were three: the order of the chain (Path B left it to
autoconnect and said nothing of it), removal healing, and a host bypass for plugins without a bypass port. This branch
closes those three through the strip; the remaining gaps are user features (preset saving, GUIs, custom widgets,
parameter feedback, file parameters) and do not stop a chain from running.
