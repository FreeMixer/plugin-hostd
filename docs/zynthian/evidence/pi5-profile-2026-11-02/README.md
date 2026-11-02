Profile of the 24-plugin chain on the Pi 5
==========================================

Where the time of a plugin-hostd chain goes, against mod-host running the same 24 plugins. Raspberry Pi 5, a private
JACK server on the dummy driver at 48000 Hz and 256 frames, the CPU governor at performance, plugin-hostd 0.15.9.
`perf record` ran for 30 s on the host's processes while the bench row ran, so each row also carries its DSP load,
memory and xruns, measured under perf (`rpi5-20261102-1.json` in each pass).

**The figures here come from a library built on the Pi, not from the shipped one.** The channel's libomx-clap-core
0.26.4 and omx-clap-host are stripped and have no debug package, and a build on the Pi does not reproduce the shipped
build id. So the profiled rows ran libomx-clap-core built on the Pi from the v0.26.4 tag (`dpkg-buildpackage`, its own
debug file, build id `e00eaaa9560ad3bf12fb36868ad5e1de8a97ac86`), loaded through `LD_LIBRARY_PATH`; the shipped library is
`5b2e51f9bc9fa227da194957f2503a77c0dd3366`. The compiler is the Pi's gcc 14.2. That can move a share by a point; it does not
change what costs what. The bench rows of [benchmarks.md](../../benchmarks.md) run the shipped packages.

- `pass1-channel-host/`: the channel's omx-clap-host 0.26.4 (stripped), the Pi-built library. Rows: cvp24 plugin-hostd
  added into a chain, and cvp24 mod-host, each with `perf record -g` and with `--call-graph dwarf`; cvp24-lv2 plugin-hostd
  added into a chain with `-g`. The worker's own code shows as bare addresses here.
- `pass2-unstripped-host/`: the plugin-hostd rows again, the worker being omx-clap-host linked from the same 0.26.4 objects
  without `-s` (build id `c30982bfcdf8b0891f4f8864706d99f974ee5190`; the shipped one is `62d8594477cb50b2e8fb1f85793b4b24b9267750`),
  given to plugin-hostd as `clap_host`. The release Makefile links omx-clap-host with `-s`, so the package has no debug
  file for it. Each `.data.txt` names the process profiled, its executable and the library it mapped.

Per row: `.dso.txt` (share per object), `.top30.txt` (`perf report --no-children`, the 30 heaviest symbols),
`.top5-callgraph.txt` (the call graph of the top five), and in pass 2 `.host.txt` (every symbol of the host's own code),
`.memcpy-callers.txt`, and for the `-g` rows the audio thread alone: `.rt-dso.txt`, `.rt-host-srcline-all.txt` (the host's
code by source line) and `.rt-memcpy.txt`.

Sample counts. perf's frequency mode gave 2.8k to 9k samples a row with `-g`, and one `--call-graph dwarf` row only 42;
shares are read from rows with 2.8k samples or more, and the 42-sample row is not used.

The audio thread of plugin-hostd's worker
-----------------------------------------

The worker's audio thread holds 97.5 % of its samples; the control thread holds the rest. Shares of the audio thread's
samples, `-g` rows of pass 2:

| where | cvp24-lv2 (every plugin LV2) | cvp24 (CLAP builds, Calf LV2) |
|---|---|---|
| the plugins and libm | 87.9 % | 91.6 % |
| `memcpy` called by the LV2 adapter's `plugin_process` | 1.92 % | 0.29 % |
| `memcpy` at the chain's input and output (`omx_clap_host_run`, `process_gated`) | 0.94 % | 1.09 % |
| the adapter's control and event work each cycle (`lv2_instance.c`, `lv2_clap.c`: the scan of control outputs, the reset of triggers, the time position, the event ports) | about 1.0 % of 2.01 % | about 0.25 % of 0.52 % |
| the stage's guards (`clap_stage.h`, `hosted_stage.h`, `cycle_gate.h`, the clamp among them) | 0.47 % | 0.56 % |
| the per-member wrapper (`clap_host.h` ports and transport, `effects.c`) | 0.86 % | 1.25 % |
| kernel and libjack | 0.53 % | 0.53 % |

The host's own code and its copies come to about 4 to 7 % of the audio thread, about 0.5 to 0.9 points of the chain's
12.7 % DSP load. The heaviest single symbol is `tanhf` in omx-drive, 14 to 15 %.

The worker's control thread walks every one of the 9990 instance slots on each idle tick (`effects_idle`): 2.5 % of the
worker's samples, outside the audio thread.

mod-host on the same chain
--------------------------

mod-host runs the 24 plugins as 24 JACK clients, one thread each, each about 10 % of its samples. Kernel and libjack are
9.6 % (`--call-graph dwarf`) to 14.1 % (`-g`) of mod-host's samples; on plugin-hostd's chain, one JACK client, they are
0.5 %. DSP load under perf: mod-host 16.6 to 16.8 %, plugin-hostd's chain 12.7 to 13.3 %.

Reproducing
-----------

`s7.sh` and `s7b.sh` ran on the Pi as root; `profile-chain.py` runs the bench's own row (`bench/lib/bench.py`) and runs
`perf record` during the row's measuring window:

    LD_LIBRARY_PATH=<lib dir> python3 profile-chain.py --bench bench --out out --seconds 30 --rate 48000 --frames 256 \
        --conf "clap_host <omx-clap-host linked without -s>" --rows cvp24:H2:chain-add:fp,cvp24:H3::fp
