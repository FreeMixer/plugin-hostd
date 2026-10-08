Name: plugin-hostd
Version: 0.1.3
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
