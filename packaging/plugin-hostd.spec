Name: plugin-hostd
Version: 0.2.0
Release: 1%{?dist}
License: GPL-3.0-or-later
Summary: Run LV2 and CLAP plugins in a live rig without one crash taking down the show
URL: https://github.com/FreeMixer/plugin-hostd

Source0: %{url}/archive/v%{version}/%{name}-%{version}.tar.gz

BuildRequires: gcc
BuildRequires: make
BuildRequires: diffutils
BuildRequires: python3
BuildRequires: pkgconfig(mod-host-protocol)
# the CLAP worker and the fixtures the real-worker tests drive: the lowest release with what this build needs
# (omx-clap-core 0.7); a floor only, minor and patch releases stay compatible
BuildRequires: omx-clap-host-tests >= 0.7.0

# the workers: a format whose worker is not installed refuses its adds (-503), the other format is unaffected
Recommends: mod-host
Recommends: omx-clap-host

%description
plugin-hostd keeps your effects and instruments running when one of them
misbehaves. It gives a controller one mod-host socket and starts each plugin, or
each named group of plugins, in a worker process of its own: mod-host for LV2,
omx-clap-host for CLAP. If a plugin crashes, only its worker goes down and the
daemon brings it back. Audio never passes through the daemon, so it adds no
latency: every worker is a JACK client.

%package devel
Summary: Talk to plugin-hostd from your own controller without retyping its protocol
BuildArch: noarch

%description devel
The C header that declares everything a controller needs to drive plugin-hostd:
the verbs it adds to mod-host's protocol, error codes, feedback events and
settings. Include it instead of copying the values, and pkg-config plugin-hostd
gives the flags. The same declaration as JSON, for tools not written in C, ships
in the plugin-hostd package.

%prep
%autosetup

sed -i 's,LDFLAGS += -s,LDFLAGS +=,g' Makefile

%build

%set_build_flags

%make_build

%install

%make_install PREFIX=%{_prefix}

# the verb table is checked against mod-host's README, which a build does not have
%check

make test-daemon check-generated

%files
%license COPYING
%doc README.md
%{_bindir}/plugin-hostd
%{_mandir}/man1/plugin-hostd.1*
%{_datadir}/plugin-hostd/protocol.json
%{_datadir}/plugin-hostd/mod-host.json

%files devel
%license COPYING
%{_includedir}/plugin-hostd/protocol.h
%{_includedir}/plugin-hostd/pin.h
%{_datadir}/pkgconfig/plugin-hostd.pc
%{_datadir}/plugin-hostd/protocol.schema.json

%changelog
* Thu Oct 15 2026 Pau Aliagas <linuxnow@gmail.com> - 0.2.0-1
- Pins are learned on first use: the first time a plugin is added its pin is
  recorded in a pin store, and a later change of the plugin or its layout is
  announced instead of passing silently.
- pin_file names the pin store; saves are fsync'd so a crash never loses a
  pin, and a corrupt or overlong store line is refused rather than trusted.
- One format table holds a row per plugin format: the pins and the
  supervisor read the row, so a new format needs no changes elsewhere, and
  the protocol names capabilities instead of formats.
- The packages require omx-clap-host-tests as a floor only, with no ceiling.

* Thu Oct 15 2026 Pau Aliagas <linuxnow@gmail.com> - 0.1.7-1
- The build needs omx-clap-core 0.7.
- The packages require omx-clap-host-tests >= 0.7.0 and below 0.8 for the
  tests.

* Thu Oct 15 2026 Pau Aliagas <linuxnow@gmail.com> - 0.1.6-1
- The CLAP worker and its test fixtures now come from the installed
  omx-clap-core packages (omx-clap-host and omx-clap-host-tests) instead of a
  pinned checkout. There are no pins anywhere in the build.
- The packages require omx-clap-host-tests >= 0.6.0 and below 0.7 for the
  tests.

* Wed Oct 14 2026 Pau Aliagas <linuxnow@gmail.com> - 0.1.5-1
- The README gains a Status section drawn from the CI jobs, and spells out
  the apt lines for Debian and Ubuntu.
- The project keeps no changelog file: the git history is the changelog.

* Thu Oct 08 2026 Pau Aliagas <linuxnow@gmail.com> - 0.1.4-1
- When a plugin worker cannot get its network ports because another process
  took them first, the daemon now starts it again on fresh ports, up to three
  tries, instead of giving up. This fixes the occasional "-503" when adding a
  plugin.
- The JACK test now also runs on JACK2's jackd, and the continuous checks use
  pinned versions of the tools they build with.

* Thu Oct 08 2026 Pau Aliagas <linuxnow@gmail.com> - 0.1.3-1
- mod-host's own command vocabulary now ships as a JSON file,
  /usr/share/plugin-hostd/mod-host.json, beside protocol.json, so a controller
  that is not written in C can read both from the installed package.
- The package descriptions now say what plugin-hostd does for you: it keeps
  your effects and instruments running when one plugin crashes.

* Thu Oct 01 2026 Pau Aliagas <linuxnow@gmail.com> - 0.1.2-1
- Messages the plugin workers send back, such as meter and state feedback, now
  reach the controller.
- New commands to ask about a plugin: track_info, remote_pages,
  remote_page_get and param_info.

* Wed Sep 30 2026 Pau Aliagas <linuxnow@gmail.com> - 0.1.1-1
- A controller can pin the exact binary and layout of a plugin before adding
  it (pin_set, pin_clear, pin_expect), so a plugin that changed on disk is
  refused instead of loaded.
- Every command is now read from one declaration, so the daemon and its header
  cannot disagree.
- A pinned LV2 plugin gets a worker of its own, an add whose pin_expect goes
  unanswered fails, and a refused replay is announced.

* Wed Sep 30 2026 Pau Aliagas <linuxnow@gmail.com> - 0.1.0-1
- First package.
