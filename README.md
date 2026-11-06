plugin-hostd
============

plugin-hostd runs your LV2 and CLAP audio plugins, each in a worker process of its own, and
puts back any worker that dies. A plugin that crashes takes down its own worker and nothing
else. It speaks mod-host's socket protocol, same ports, same replies, so a mod-host controller
works unchanged; audio never passes through the daemon, every worker is a JACK client. It is for
anyone who runs plugins live on Linux, on a mixing console, a stage rig or a Raspberry Pi.

Install
-------

Fedora:

    sudo dnf install https://www.openmixer.org/rpm/openmixer-release.noarch.rpm
    sudo dnf install plugin-hostd omx-clap-host

Debian bookworm and trixie and Raspberry Pi OS (amd64 and arm64):

    curl -fsSLO https://www.openmixer.org/deb/openmixer-release.deb && sudo apt install ./openmixer-release.deb
    sudo apt update && sudo apt install plugin-hostd omx-clap-host

omx-clap-host runs both CLAP and LV2 plugins. A plugin it cannot run is refused with a code that says why, and is
never handed to another host. mod-host runs LV2 plugins only when you choose it (`lv2_worker mod-host`).

Start
-----

Start the daemon, with pin checking off for a first try (it says when both ports accept):

    echo 'require_pins 0' > plugin-hostd.conf
    plugin-hostd -n -p 5555 -c plugin-hostd.conf

Then drive it on port 5555 as you would mod-host: `add`, `param_set`, `connect`. `man plugin-hostd`
has the options.

Documentation
-------------

- <https://www.openmixer.org/projects/plugin-hostd>, and the documentation at <https://www.openmixer.org/docs>.
- In the source tree: the whole guide, with the protocol, placement, grouping, pins and formats,
  in [docs/guide.md](docs/guide.md); using it from your own host in [docs/own-host.md](docs/own-host.md).

Building from source: see [BUILDING.md](BUILDING.md).

Licence
-------

GPL-3.0-or-later. See [COPYING](COPYING).
