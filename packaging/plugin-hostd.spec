%bcond_without check

Name: plugin-hostd
Version: 0.5.0
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
# a command of exactly the socket's buffer size, or several commands in one read, needs mod-audio/mod-host#113:
# FreeMixer's build carrying it (11.1.fmx) or audinux's once it carries it (12); a floor only
Requires: mod-host-protocol%{?_isa} >= 0.10.6.f14a230-11.1
# omx-clap-core is a build dependency of the check stage only: the CLAP worker and the fixtures the real-worker
# tests drive. A build with `--without check` needs nothing of omx-clap-core, so plugin-hostd and omx-clap-core
# do not build-depend on each other. A floor only: the lowest release with what the tests need (omx-clap-core 0.9)
%if %{with check}
BuildRequires: omx-clap-host-tests >= 0.9.0
%endif

# the workers: a format whose worker is not installed refuses its adds (-503), the other format is unaffected
Recommends: mod-host
Recommends: omx-clap-host >= 0.9.0

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

%package tests
Summary: A stand-in plugin worker to test a program that drives plugin-hostd
Requires: %{name}%{?_isa} = %{version}-%{release}

%description tests
A small worker that speaks the same protocol as mod-host and omx-clap-host and
can be made to die on cue, so a program that talks to plugin-hostd can be
tested against a real daemon without a plugin, a JACK server or any audio.
Run it with -L to print the layout it reports. It is installed in
%{_libexecdir}/plugin-hostd/tests, away from the directories programs run
from, and is of no use to anyone else.

%prep
%autosetup

sed -i 's,LDFLAGS += -s,LDFLAGS +=,g' Makefile

%build

%set_build_flags

%make_build
%make_build tests/fake-host

%install

%make_install PREFIX=%{_prefix}

# the verb table is checked against mod-host's README, which a build does not have
%check
%if %{with check}
make test-daemon check-generated
%endif

%files
%license COPYING
%doc README.md
%{_bindir}/plugin-hostd
%{_bindir}/plugin-hostd-probe
%{_mandir}/man1/plugin-hostd.1*
%{_mandir}/man1/plugin-hostd-probe.1*
%{_datadir}/plugin-hostd/protocol.json
%{_datadir}/plugin-hostd/mod-host.json

%files tests
%license COPYING
%{_libexecdir}/plugin-hostd/tests/fake-host

%files devel
%license COPYING
%{_includedir}/plugin-hostd/protocol.h
%{_includedir}/plugin-hostd/pin.h
%{_datadir}/pkgconfig/plugin-hostd.pc
%{_datadir}/plugin-hostd/protocol.schema.json
%{_datadir}/plugin-hostd/probe-output.schema.json

%changelog
* Sun Oct 18 2026 Pau Aliagas <linuxnow@gmail.com> - 0.5.0-1
- plugin-hostd-probe runs LV2 plugins too: `run lv2:<uri>` measures a
  plugin through plugin-qualify's lv2_measure, the pin pass and then the
  measurement, each a child under the same limits and wall clock. The
  bundle's files become the document's binary. A plugin of which nothing
  can be pinned exits 2 with no document, and stderr starts with its
  outcome code (probe.unpinnable).
- A pin whose verdict is refused refuses the add with the new code
  PIN_REFUSED (-516), after the files are checked against the pin; an
  instance whose pin turns refused is refused at its next replay.
- Under lv2_worker auto, a plugin the LV2 adapter refused gets a worker of
  its own unless the add names a placement, so a plugin that aborts on
  mod-host no longer takes a pool's other instances with it. An add whose
  worker dies on it also sends instance_verb_dropped, which names it.
- A worker whose feedback the relay cannot follow is not started: the add
  answers -503. With no memory the relay closes a worker's socket instead
  of leaving it unread, and its poll set no longer crashes the daemon.

* Sun Oct 18 2026 Pau Aliagas <linuxnow@gmail.com> - 0.4.0-1
- New tool plugin-hostd-probe: it starts a program that loads a plugin
  (clap-qualify by default) under limits of CPU time, memory, open files,
  file size and real-time priority, kills the whole process tree on the
  deadline, and writes the facts of the run as a JSON document. Its manual
  page is installed, and plugin-hostd-devel ships the document's schema in
  /usr/share/plugin-hostd/probe-output.schema.json.
- Notes: the instance verbs note_input, note_on, note_off and
  all_notes_off pass notes to a worker that takes them; an effect answers
  -513, and an LV2 instance on mod-host answers -514 (play it through its
  JACK MIDI port).
- The tempo and transport (set_bpm, set_bpb, transport, transport_sync) are
  kept by the daemon and handed to every worker when it starts or restarts.
- Presets: preset_list and preset_get list an instance's presets by the key
  preset_load takes; an LV2 instance on mod-host answers -515.
- The events param_gesture and remote_page_suggest are relayed. When a
  worker dies or an instance is removed in the middle of a gesture, the
  daemon sends the gesture's end itself.
- Under lv2_worker auto, a plugin the adapter refused is asked again after
  lv2_worker_set, pin_set, pin_accept or pin_clear.
- param_info on a CLAP instance passes the worker's answer through; -511
  (no checked unit and scale) is documented.
- mod-host-protocol 0.10.6.f14a230-11.1 or newer is required: older builds
  hang on a command of exactly the socket's buffer size and run only the
  first of several commands that arrive in one read.
- A worker line too long to relay is now dropped whole; before, its tail
  reached the controller as a line of its own.
- Numbers are refused when written as -0, so zero has a single spelling.
- The package builds without omx-clap-core; omx-clap-host-tests is needed
  only to run the tests.

* Fri Oct 16 2026 Pau Aliagas <linuxnow@gmail.com> - 0.3.0-1
- You choose which program runs LV2 plugins: mod-host, omx-clap-host or auto
  (the setting lv2_worker, changed with the lv2_worker_set command). A host
  that cannot take LV2 plugins now answers with a new error (-512) and the
  daemon announces the refusal with the lv2_adapter_refused event.
- omx-clap-host 0.9.0 or newer is recommended: older versions do not load LV2
  plugins, so with the default auto choice everything would run on mod-host.
- A new page explains how to use plugin-hostd in your own host.
- Fixed a build failure of programs that include pin.h with gcc -O3 -Werror.

* Thu Oct 15 2026 Pau Aliagas <linuxnow@gmail.com> - 0.2.1-1
- New package plugin-hostd-tests ships the fake worker (fake-host) in
  /usr/libexec/plugin-hostd/tests/, so the CI of other repositories can run
  the pin-file test for real.

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
