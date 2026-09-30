Name: plugin-hostd
Version: 0.1.0
Release: 1%{?dist}
License: GPL-3.0-or-later
Summary: Supervisor that runs LV2 and CLAP plugin hosts as isolated workers behind one mod-host socket
URL: https://github.com/FreeMixer/plugin-hostd

Source0: %{url}/archive/v%{version}/%{name}-%{version}.tar.gz

BuildRequires: gcc
BuildRequires: make
BuildRequires: python3
BuildRequires: pkgconfig(mod-host-protocol)

# the workers: a format whose worker is not installed refuses its adds (-503), the other format is unaffected
Recommends: mod-host
Recommends: omx-clap-host

%description
plugin-hostd speaks mod-host's socket protocol to a controller and runs one
worker process per plugin, or per named pool of plugins, behind it: mod-host
for LV2 plugins and omx-clap-host for CLAP plugins. A plugin that crashes takes
down its own worker and nothing else, and the daemon puts it back. Audio never
passes through the daemon: every worker is a JACK client, as in mod-host.

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

make test-daemon

%files
%license COPYING
%doc README.md
%{_bindir}/plugin-hostd
%{_mandir}/man1/plugin-hostd.1*

%changelog
* Wed Sep 30 2026 Pau Aliagas <linuxnow@gmail.com> - 0.1.0-1
- first package
