Use plugin-hostd in your own host
=================================

This page takes a Debian machine (Raspberry Pi OS, Zynthian, any Debian 12 or 13, arm64 or amd64) from nothing to a
plugin running under plugin-hostd, driven over its socket, in nine commands. CI runs every command below, as written, in
a clean Debian container on both architectures; a step that stops working fails that job.

The plugin is a CLAP effect from the `omx-plugins-clap` package, so nothing else has to be installed to try it. Any
host that already speaks mod-host's socket protocol can send the same lines.

The first line of the block is a helper, not counted: one protocol message in, the reply out (a message ends in a NUL
byte, which `printf` adds). A trailing `# resp ...` or `# has ...` is the reply or output CI expects; to you it is a
comment.

The commands, in order. Run them as a normal user with `sudo`, or as root:

```sh own-host
send() { printf '%s\0' "$1" | nc -w3 127.0.0.1 5555 | tr '\0' '\n'; }
sudo curl -fsSL --create-dirs -o /etc/apt/keyrings/freemixer.asc https://freemixer.github.io/deb/freemixer.asc
echo "deb [signed-by=/etc/apt/keyrings/freemixer.asc] https://freemixer.github.io/deb/debian/$(. /etc/os-release; echo $VERSION_CODENAME) ./" | sudo tee /etc/apt/sources.list.d/freemixer.list
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

Pins need nothing from you. A plugin has to be pinned (its files' hashes and its parameter layout) before the daemon
lets it run; in the default `first-use` mode the first `add` records the pin in `$XDG_STATE_HOME/plugin-hostd/pins`, and
a later `add` of a changed file is refused with a `pin_changed` event. A host that pins by itself sets `pin_mode strict`.
See Pins in the [README](../README.md).

What to read next: `man plugin-hostd`; the verbs and error codes in the README; `remote_pages` and `remote_page_get` for
the plugin's own pages of controls; the machine-readable protocol at `/usr/share/plugin-hostd/protocol.json`; a C
consumer can include `plugin-hostd/protocol.h` (`pkg-config --cflags plugin-hostd`, package `plugin-hostd-dev`).

What a Zynthian integration still needs from us
-----------------------------------------------

Checked against the published packages (0.2.1 of the daemon, 0.8.0 of the worker and plugins) in a clean Debian
trixie container:

- LV2 needs mod-host, which neither Debian nor the FreeMixer channel packages. Zynthian's plugins are mostly LV2, so
  until the channel carries an LV2 worker (mod-host, or `omx-clap-host` with `libomx-clap-lv2`, issue #45) the page
  above only covers CLAP.
- `param_info` answers `-511` for a CLAP instance with the released worker, so a host reads ranges and defaults from
  `omx-clap-scan` (or `omx-clap-scan --json`) and not from the socket.
- Parameters are named by their CLAP number (`0`, `1`, ...), not by a name; a host maps names to numbers from the scan.
- No Zynthian image was available to CI: the check is on plain Debian arm64, not on Zynthian's own userland (its jackd,
  its audio configuration, its realtime limits).

Each of these is an issue of its own.
