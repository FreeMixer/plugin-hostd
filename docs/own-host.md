Use plugin-hostd in your own host
=================================

This page takes a Debian machine (Raspberry Pi OS, Zynthian, any Debian 12 or 13, arm64 or amd64) from nothing to a
plugin running under plugin-hostd, driven over its socket, in nine commands, and then runs an LV2 plugin the same way in eight more. CI runs every command below, as written, in
a clean Debian container on Debian 12 and 13, on both architectures; a step that stops working fails that job.

The plugin is a CLAP effect from the `omx-plugins-clap` package, so nothing else has to be installed to try it. Any
host that already speaks mod-host's socket protocol can send the same lines.

The first line of the block is a helper, not counted: one protocol message in, the reply out (a message ends in a NUL
byte, which `printf` adds). A trailing `# resp ...` or `# has ...` is the reply or output CI expects; to you it is a
comment.

The commands, in order. Run them as a normal user with `sudo`, or as root:

```sh own-host
send() { printf '%s\0' "$1" | nc -w3 127.0.0.1 5555 | tr '\0' '\n'; }
curl -fsSLO https://www.openmixer.org/deb/openmixer-release.deb
sudo apt-get install -y ./openmixer-release.deb
sudo apt-get update && sudo apt-get install -y plugin-hostd omx-clap-host omx-plugins-clap jackd2 netcat-openbsd
jackd -r -d dummy >/dev/null 2>&1 & sleep 2
plugin-hostd -n -p 5555 >plugin-hostd.log 2>&1 & sleep 2
omx-clap-scan /usr/lib/clap/omx-comp.clap | grep 'param 1 '  # has Ratio [1 .. 20] default 4
send "add clap:/usr/lib/clap/omx-comp.clap#org.openmixer.comp 0"   # resp 0
send "param_set 0 1 8"   # resp 0
send "param_get 0 1"   # resp 0 8.0000
```

What each step did:

1. `curl` fetches the repository key of the FreeMixer channel. It signs every package, for x86_64 and arm64.
2. The `echo` adds the channel for your Debian release (`bookworm` and `trixie` are published).
3. `apt-get install` takes the daemon, the CLAP worker `omx-clap-host`, a set of CLAP plugins to try, and JACK. On a
   machine that already runs JACK (Zynthian does) leave `jackd2` out.
4. `jackd -r -d dummy` starts a JACK server that needs no sound card. On a real machine use the one you have.
5. `plugin-hostd -n -p 5555` starts the daemon on the command port, 5555. It prints `plugin-hostd ready!` once the port
   accepts. No worker exists until the first `add`.
6. `omx-clap-scan` reads the plugin's layout: every parameter, its number, range and default. The number is the symbol
   the protocol takes, so the compressor's Ratio is `1`.
7. `add` loads the plugin as instance `0`. The daemon starts a worker of its own for it, a JACK client named
   `effect_0`, and puts it back if it dies.
8. `param_set` sets Ratio to 8.
9. `param_get` reads it back.

LV2 plugins
-----------

Zynthian's plugins are mostly LV2. `omx-clap-host`, which you already installed, also runs an LV2 plugin through its LV2
adapter; the LV2 build of the same plugins is the package `omx-plugins-lv2`. Continue in the same shell, with the
`send` helper of the first block and JACK still running. `lv2_worker` names the program that runs LV2 plugins, and
`mod-host` is the default, so the daemon is restarted with `omx-clap-host` named in its configuration file. An LV2
plugin is added by its URI with an `lv2:` prefix, and its parameters are named by their LV2 symbol (`ratio`), not by a
number.

```sh own-host-lv2
send "quit"; sleep 1   # resp 0
sudo apt-get install -y omx-plugins-lv2
echo "lv2_worker omx-clap-host" > plugin-hostd.conf
plugin-hostd -n -p 5555 -c plugin-hostd.conf >plugin-hostd-lv2.log 2>&1 & sleep 2
send "add lv2:urn:openmixer:comp 0"   # resp 0
send "param_set 0 ratio 8"   # resp 0
send "param_get 0 ratio"   # resp 0 8.0000
send "worker_list"   # has :lv2-clap:
```

1. `quit` stops the daemon and the worker of the first block.
2. `apt-get install` adds the LV2 bundles under `/usr/lib/lv2`, where the daemon searches.
3. The configuration file makes `omx-clap-host` the worker of LV2 plugins.
4. The daemon starts again with it.
5. `add` loads the plugin by its URI as instance `0`, in a worker of its own.
6. and 7. `param_set` and `param_get` set and read back the compressor's Ratio by its symbol.
8. `worker_list` names the worker of each instance; `lv2-clap` is `omx-clap-host` running an LV2 plugin.

CI also sends a sine into the instance's JACK ports and measures what comes out, with the Makeup gain set to 6 dB and
Ratio to 1: the output peak must be 1.995 times the input's.

Pins need nothing from you. A plugin has to be pinned (its files' hashes and its parameter layout) before the daemon
lets it run; in the default `first-use` mode the first `add` records the pin in `$XDG_STATE_HOME/plugin-hostd/pins`, and
a later `add` of a changed file is refused with a `pin_changed` event. A host that pins by itself sets `pin_mode strict`.
See Pins in the [README](../README.md).

What to read next: `man plugin-hostd`; the verbs and error codes in the README; `remote_pages` and `remote_page_get` for
the plugin's own pages of controls; the machine-readable protocol at `/usr/share/plugin-hostd/protocol.json`; a C
consumer can include `plugin-hostd/protocol.h` (`pkg-config --cflags plugin-hostd`, package `plugin-hostd-dev`).

Measuring plugins at real-time priority
---------------------------------------

`plugin-hostd-probe` measures a plugin on a SCHED_FIFO thread at the highest priority it is granted, with its memory
locked, as JACK or PipeWire runs it; without a grant the figures are taken at ordinary priority, and the record says so
(`run.realtime.class: none` and the reason). On Zynthian and on the console, plugin-qualify's sync service
(`plugin-qualify-sync.service`) runs the probe; it passes the grant with a drop-in,
`/etc/systemd/system/plugin-qualify-sync.service.d/realtime.conf`:

```ini
[Service]
# the highest SCHED_FIFO priority, which the probe asks for, and a lock as large as the probe's memory limit
LimitRTPRIO=99
LimitMEMLOCK=infinity
# the unit forbids real time to everything it starts; the probe bounds it instead (RLIMIT_RTPRIO, RLIMIT_RTTIME)
RestrictRealtime=no
```

then `sudo systemctl daemon-reload`. Where the distribution lets a service hold capabilities,
`AmbientCapabilities=CAP_SYS_NICE` grants the same priority without the rlimit; a CI job whose container holds CAP_SYS_NICE
and no CAP_SYS_RESOURCE runs the probe's real-time arm on that route, so the record's `grantedBy: cap` is measured on every
push. `plugin-qualify --all`, run by hand,
gets the grant of the user's login session: the `rtprio` and `memlock` of `/etc/security/limits.d/`, as for JACK (for
example the `audio` group's). `plugin-hostd-probe run --list-limits` prints what a run would get: the `realtime` line
names the grant and the priority, or why there is none.

The probe's memory limit is `memory.max` of a cgroup it makes for the measured child. A service running as root needs nothing
for that. A service under another user needs `Delegate=memory` in the same drop-in; without it the limit is `RLIMIT_DATA`, and
the document says so under `limits.unavailable`.

What a Zynthian integration still needs from us
-----------------------------------------------

Checked in a clean Debian container against published packages. The first item against 0.4.0 of the daemon and 0.10.0 of
the worker and plugins (the page's CI); the others against 0.2.1 of the daemon and 0.8.0 of the worker and plugins, on
trixie, and not re-checked since:

- An LV2 plugin that the LV2 adapter of `omx-clap-host` refuses needs mod-host, which neither Debian nor the FreeMixer
  channel packages. The add answers `-512`; `lv2_worker auto` runs such a plugin in mod-host when one is installed.
- `param_info` answers `-511` (the worker holds no checked unit and scale) for every parameter of a CLAP instance with
  the released worker, 0.8.0; the daemon passes the answer through. A host reads ranges and defaults from
  `omx-clap-scan` (or `omx-clap-scan --json`) and not from the socket, until a worker answers `resp 0`.
- Parameters are named by their CLAP number (`0`, `1`, ...), not by a name; a host maps names to numbers from the scan.
- No Zynthian image was available to CI: the check is on plain Debian arm64, not on Zynthian's own userland (its jackd,
  its audio configuration, its realtime limits).

Each of these is an issue of its own.
