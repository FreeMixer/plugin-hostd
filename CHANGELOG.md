# Changelog

What changed in each release of plugin-hostd, in plain words. The RPM and Debian changelogs and the
GitHub release notes are generated from this file.

## 0.1.4 - 2026-10-08

- When a plugin worker cannot get its network ports because another process took them first, the daemon now
  starts it again on fresh ports, up to three tries, instead of giving up. This fixes the occasional
  "-503" when adding a plugin.
- The JACK test now also runs on JACK2's jackd, and the continuous checks use pinned versions of the tools
  they build with.

## 0.1.3 - 2026-10-08

- mod-host's own command vocabulary now ships as a JSON file, /usr/share/plugin-hostd/mod-host.json, beside
  protocol.json, so a controller that is not written in C can read both from the installed package.
- The package descriptions now say what plugin-hostd does for you: it keeps your effects and instruments
  running when one plugin crashes.

## 0.1.2 - 2026-10-01

- Messages the plugin workers send back, such as meter and state feedback, now reach the controller.
- New commands to ask about a plugin: track_info, remote_pages, remote_page_get and param_info.

## 0.1.1 - 2026-09-30

- A controller can pin the exact binary and layout of a plugin before adding it (pin_set, pin_clear,
  pin_expect), so a plugin that changed on disk is refused instead of loaded.
- Every command is now read from one declaration, so the daemon and its header cannot disagree.
- A pinned LV2 plugin gets a worker of its own, an add whose pin_expect goes unanswered fails, and a
  refused replay is announced.

## 0.1.0 - 2026-09-30

- First package.
