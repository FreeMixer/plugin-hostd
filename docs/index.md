plugin-hostd documentation
==========================

plugin-hostd runs LV2 and CLAP audio plugins, each in a worker process of its own, behind mod-host's socket protocol,
and puts back any worker that dies. The [README on GitHub](../README.md) has the install lines, the verbs and the
error codes; these pages go further into one subject each.

Using it
--------

- [Use plugin-hostd in your own host](own-host.md): a Debian machine from nothing to a plugin running under the
  daemon, driven over its socket, in the commands CI runs.
- [Presets in the host](presets.md): who owns a preset, the verbs, and the preset file format.
- [The panel a plugin publishes](panel.md): the `panel_get` verb and what a host draws a panel from.

How it works
------------

- [The format tables](formats.md): how a CLAP or LV2 scan becomes a descriptor, and the same tables read backwards.

Use case: plugin-hostd as the host for Zynthian
-----------------------------------------------

Zynthian running its LV2 and CLAP plugins under plugin-hostd. The pages of this use case, with their figures and
captures, are being written; each becomes a link here when it is published.

- Instruments: voices across the cores (coming).
- Benchmarks (coming).
- Trade-offs (coming).
- The upstream series (coming).
- The acceptance report (coming).

About this site
---------------

The site is built from the markdown under `docs/` by `tools/site/build.mjs` on every push to main. A figure or a
capture is published when a page references it; design material stays in the repository and is not published.
