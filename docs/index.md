plugin-hostd for Zynthian
=========================

plugin-hostd is a plugin host that speaks mod-host's protocol, so Zynthian's engines can drive it as they drive
mod-host. On a Raspberry Pi 5, measured digitally at 48000 Hz and 256 frames, a chain in plugin-hostd costs less than the
same plugins in mod-host, in every scenario and every repeat:

| | plugin-hostd, one chain | mod-host |
|---|---|---|
| 24 plugins, CLAP builds, DSP load and memory (PSS) | 12.5 %, 64 MB | 15.0 %, 109 MB |
| the same 24, LV2 builds | 12.7 %, 63 MB | 15.4 %, 109 MB |
| ten third-party LV2 plugins | 5.6 %, 45 MB | 6.6 %, 90 MB |

That is 14 to 17 % less DSP and 41 to 49 % less memory, with one JACK client for the chain and no xruns
([the three hosts](zynthian/benchmarks.md#the-three-hosts-on-current-versions)). It gives Zynthian:

- **A set ready sooner.** 24 plugins are running 0.55 s after a cold start, against 1.46 s
  ([time to add](zynthian/benchmarks.md#time-to-add)).
- **Instruments that cost less memory.** mda Piano, Odin 2 and Surge XT take the same CPU as under mod-host and about
  43 MB less memory each ([instruments](zynthian/benchmarks.md#instruments)). The cores are used by placement: one worker
  per instrument or chain, all of them on the audio cores and the daemon kept off them.
- **What a plugin costs, in the menu.** All 1602 plugins on a Pi 5 went through qualification on the device, and 1385
  qualified: 1079 in-process and 306 in a worker of their own. Another 38 rate suitable but have no memory figure yet, 152
  crashed, hung or were refused, and 27 could not be measured ([qualification](zynthian/benchmarks.md#qualification-and-acceptance)). The
  plugin-hostd engine's menus read these records ([FreeMixer/zynthian-ui#4](https://github.com/FreeMixer/zynthian-ui/pull/4)); showing the figures in the menu is the next step of
  [the upstream series](zynthian/upstream-series.md).
- **One panel for both surfaces.** The engine's controller pages and the MOD GUI are drawn from the same layout of
  the plugin's descriptor ([the panel](panel.md)); the system check of that step passes 110 of 110 with omx-panel
  0.6.0 ([the upstream series](zynthian/upstream-series.md)).

Where it costs more: one worker per plugin uses more than mod-host (17.8 % and 183 MB against 15.0 % and 109 MB, and it is
not the default), and mod-host adds two plugins to a running host faster (45 ms against 56 ms).

[From a plugin file to a page on the screen](from-file-to-page.md) shows how plugin-hostd and its tools find out what a
plugin costs, in five stages.

{{captures}}

**Try it**: flash [the image](zynthian/image.md), or, on a Zynthian running vangelis, add the OpenMixer channel and
install the host:

    curl -fsSLO https://www.openmixer.org/deb/openmixer-release.deb && sudo apt install ./openmixer-release.deb
    sudo apt update && sudo apt install plugin-hostd omx-clap-host

then [switch Zynthian's engine to it](zynthian/README.md).

Read on: [Start here](start-here.md) for what plugin-hostd is and how it runs; the
[Zynthian use case](section:zynthian) for every measurement, trade-off and patch; the [Reference](section:reference)
for the protocol and the formats; the [Evidence](section:evidence) behind every number.
