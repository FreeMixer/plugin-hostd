plugin-hostd for Zynthian
=========================

Zynthian's jalv engine runs every plugin in a process of its own, and a synth's voices all run on one core of the Pi. Nothing
tells it, or you, what a plugin costs on that board before it is in a chain.

plugin-hostd is a plugin host that speaks mod-host's protocol, so Zynthian's engines can drive it as they drive
mod-host today. It gives Zynthian:

- **Chains in one worker.** 16 plugins in one chain run in 2 processes and 42.9 MB of memory (PSS), against 17
  processes and 118.2 MB with one process per plugin; Raspberry Pi 5, 2026-10-27
  ([the measurement](https://www.openmixer.org/docs/grouped-vs-processes); jalv and mod-host beside it in
  [Benchmarks](zynthian/benchmarks.md#grouped-versus-alone-plugin-hostd-jalv-mod-host)).
- **Instruments with their voices across the cores**, once the CLAP thread pool of omx-clap-core#395 lands. Not
  measured yet; the figures will be in [Instruments](zynthian/instruments.md).
- **What a plugin costs, in the menu.** All 1584 plugins on a Pi 5 (1337 LV2, 247 CLAP) were qualified on 2026-10-28:
  for plugin-hostd's worker, 1059 LV2 plugins suitable, 185 isolated in a worker of their own, 79 unsuitable
  ([Benchmarks](zynthian/benchmarks.md#qualification-of-every-plugin-on-the-pi)). The plugin-hostd engine's menus
  read these records ([FreeMixer/zynthian-ui#4](https://github.com/FreeMixer/zynthian-ui/pull/4)); showing the figures in the menu is the next step of
  [the upstream series](zynthian/upstream-series.md).
- **One panel for both surfaces.** The engine's controller pages and the MOD GUI are drawn from the same layout of
  the plugin's descriptor ([the panel](panel.md)); the system check of that step passes 110 of 110 with omx-panel
  0.6.0, 2026-10-28 ([the upstream series](zynthian/upstream-series.md)).

{{captures}}

**Try it**: flash [the image](zynthian/image.md), or, on a Zynthian running vangelis, add the OpenMixer channel and
install the host:

    curl -fsSLO https://www.openmixer.org/deb/openmixer-release.deb && sudo apt install ./openmixer-release.deb
    sudo apt update && sudo apt install plugin-hostd omx-clap-host

then [switch Zynthian's engine to it](zynthian/README.md).

Read on: [Start here](start-here.md) for what plugin-hostd is and how it runs; the
[Zynthian use case](section:zynthian) for every measurement, trade-off and patch; the [Reference](section:reference)
for the protocol and the formats; the [Evidence](section:evidence) behind every number.
