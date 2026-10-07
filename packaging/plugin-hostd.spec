Name: plugin-hostd
Version: 0.1.2
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

%files devel
%license COPYING
%{_includedir}/plugin-hostd/protocol.h
%{_includedir}/plugin-hostd/pin.h
%{_datadir}/pkgconfig/plugin-hostd.pc
%{_datadir}/plugin-hostd/protocol.schema.json

%changelog
* Thu Oct 01 2026 Pau Aliagas <linuxnow@gmail.com> - 0.1.2-1
- relay the workers' feedback to the controller
- plugin info commands: track_info, remote_pages, remote_page_get, param_info

* Wed Sep 30 2026 Pau Aliagas <linuxnow@gmail.com> - 0.1.1-1
- pin a plugin's binary and layout before add admits it (pin_set, pin_clear, pin_expect)
- read every verb from its declaration
- give a pinned LV2 plugin a worker of its own, fail an add whose pin_expect goes unanswered, announce a refused replay

* Wed Sep 30 2026 Pau Aliagas <linuxnow@gmail.com> - 0.1.0-1
- first package
