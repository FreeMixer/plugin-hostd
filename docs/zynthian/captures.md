Zynthian captures, 2026-10-29
=============================

Screens of the generated menus, the MOD GUIs and the plugin figures, taken on a Raspberry Pi 5 running the
plugin-hostd engine of the Zynthian fork. The images are in [evidence/captures-2026-10-29/](evidence/captures-2026-10-29/), one folder per plugin.

What the device ran
-------------------

| Part | Version |
| --- | --- |
| FreeMixer/zynthian-ui, branch vangelis | dc702a8b (includes the plugin figures and sort list, and the chain estimate footer) |
| zynthian-sys | 656515f |
| plugin-hostd | 0.13.1 |
| omx-plugins (and -clap, -lv2) | 0.15.1 for the captures above; 0.16.0 for the omx-eq8 retake below |
| plugin-qualify | 0.16.1 (retake only) |
| omx-panel | 0.6.0 |
| omx-clap-host | 0.23.2 |
| omx-contract-data | 3.4.0 |

Screen 1024x768, taken with scrot on the device. The MOD GUIs were taken from the device's mod-ui (port 8888) with
a headless Chromium at 1280x800. The three plugins were added to chains through the Zynthian menus (Add Chain, then
Insert Audio Processor), their pages and rows captured, and the chains removed again.

The omx-eq8 records on the device are older than its package
-------------------------------------------------------------

The descriptors and qualification records under /var/lib/omx on the device name omx-eq8 at 0.13.0, while the
installed omx-plugins package is 0.15.1 (the generated headers carried the old version, omx-plugins#260). The
controller pages therefore show the older layout: HPF, LPF, then ten pages named "Bands 1 1" to "Bands 5 2" (each
page holds parts of two bands) and a "Controls" page, thirteen pages in all. They do not show one band per page.
The captures below are what the device shows and are to be retaken once the records follow the package.

Plugin list rows and the sort list
----------------------------------

A row reads: name, hosting (PH is plugin-hostd), tier (live or studio), latency as measured/declared frames, RT
safety, cost. The list is 1024 pixels wide, so a row is cut at the right edge: the latency and the RT safety are
readable, the cost is cut ("cost un" is "cost unknown"). The sort list opens with the MENU action and orders the
list by tier, name, cost, latency or RT safety, and can show only plugin-hostd plugins.

- [common/sort-menu.png](evidence/captures-2026-10-29/common/sort-menu.png): the Plugin list sort menu, Tier ticked.

Kars (LV2 instrument, qualified)
--------------------------------

OB-Xf is in the instrument menus only as a hidden JACK-hosted entry with no qualification record, and Surge XT is
listed as "not qualified" (no figures), so the instrument shown is Kars, which has records and a generated MOD GUI.

- [kars/list-by-tier.png](evidence/captures-2026-10-29/kars/list-by-tier.png): the Synth category in the default order. The Kars row reads
  live, 0/0 frames, RT clean, cost unknown; Surge XT and Ultramaster rows read "not qualified", the others "refused".
- [kars/list-sorted-by-latency.png](evidence/captures-2026-10-29/kars/list-sorted-by-latency.png): the same list sorted by latency: 0, 14, 31,
  262 frames, then "latency unknown" rows.
- [kars/list-sorted-by-cost.png](evidence/captures-2026-10-29/kars/list-sorted-by-cost.png): sorted by cost; every cost is unknown, so the
  order falls back to the name.
- [kars/controller-page-1-controls.png](evidence/captures-2026-10-29/kars/controller-page-1-controls.png): the engine's one page "Controls"
  with Sustain, Release and Volume.
- [kars/modgui-pedalboard.png](evidence/captures-2026-10-29/kars/modgui-pedalboard.png): mod-ui's pedalboard with Kars and its generated GUI
  (one "Controls" group of three knobs), the CPU and RAM readings at the bottom.

ZamComp (third-party LV2 compressor, qualified)
-----------------------------------------------

- [zamcomp/list-row.png](evidence/captures-2026-10-29/zamcomp/list-row.png): the Dynamics menu with the ZamComp row highlighted: live, 0/0
  frames, RT clean.
- [zamcomp/list-sorted-by-cost-with-estimate-footer.png](evidence/captures-2026-10-29/zamcomp/list-sorted-by-cost-with-estimate-footer.png):
  the Dynamics menu sorted by cost, with the chain estimate footer reading "estimate unavailable" at the bottom (see
  Usage information).
- [zamcomp/list-sorted-by-latency.png](evidence/captures-2026-10-29/zamcomp/list-sorted-by-latency.png): the Dynamics menu sorted by latency:
  0/0 rows first, then omx limiter 108/108, Limiter Mono 240/0, then the studio rows with latency unknown.
- [zamcomp/controller-page-1-main-1.png](evidence/captures-2026-10-29/zamcomp/controller-page-1-main-1.png),
  [page 2 (Main 2)](evidence/captures-2026-10-29/zamcomp/controller-page-2-main-2.png),
  [page 3 (Setup)](evidence/captures-2026-10-29/zamcomp/controller-page-3-setup.png): the three pages built from omx-panel's layout: Attack,
  Release, Ratio, Threshold; Knee, Makeup, Gain; Sidechain.
- [zamcomp/modgui-pedalboard.png](evidence/captures-2026-10-29/zamcomp/modgui-pedalboard.png): mod-ui's pedalboard with Kars and ZamComp; the
  ZamComp GUI has the groups Main 1, Main 2, Setup and Controls, the same groups as the engine pages.

omx-eq8 (our equaliser, records at 0.13.0)
------------------------------------------

- [omx-eq8/list-row.png](evidence/captures-2026-10-29/omx-eq8/list-row.png): the Filter & EQ menu with omx eq8 highlighted: live, 0/0 frames,
  RT clean.
- [omx-eq8/controller-page-01.png](evidence/captures-2026-10-29/omx-eq8/controller-page-01.png) to
  [controller-page-13.png](evidence/captures-2026-10-29/omx-eq8/controller-page-13.png): every page of the chain's control screen for omx eq8,
  one capture each: 01 HPF, 02 LPF, 03 to 12 "Bands 1 1" to "Bands 5 2", 13 Controls (Bypass).
- [omx-eq8/modui-add-segfault.png](evidence/captures-2026-10-29/omx-eq8/modui-add-segfault.png): adding omx eq8 to a mod-ui pedalboard (on the
  device, twice) ends the mod-ui process with a segmentation fault (status 139, systemd restarts it); the page reads
  "Disconnected". No live MOD GUI of omx eq8 could be captured for that reason.
- [omx-eq8/modgui-shipped-screenshot.png](evidence/captures-2026-10-29/omx-eq8/modgui-shipped-screenshot.png): the screenshot the package's
  MOD GUI bundle carries, served by mod-ui (not a live pedalboard): five rows of eight controls and the two filters.

omx-eq8 retaken on omx-plugins 0.16.0
-------------------------------------

The device was upgraded to omx-plugins 0.16.0 and plugin-qualify 0.16.1. plugin-qualify-sync has no option to
qualify one plugin (its options are --system, --force and the path and port settings); its path unit ran it itself
after the upgrade (08:39 to 08:43, "qualified 0, skipped 1581" for the rerun) and a new descriptor
org.openmixer.eq8@0.16.0 was written at 08:41, next to the 0.13.0 ones. The pages could still not be retaken:

- [omx-eq8/zynthian-add-refused-0.16.0.png](evidence/captures-2026-10-29/omx-eq8/zynthian-add-refused-0.16.0.png): omx eq8 chosen in the
  Filter & EQ menu (Return pressed, twice) and nothing happens; the journal of the UI
  ([journal-0.16.0.txt](evidence/captures-2026-10-29/omx-eq8/journal-0.16.0.txt)) says plugin-hostd refused the add with
  PHD_ERR_PIN_BINARY_MISMATCH (-509) for clap:/usr/lib/clap/omx-eq8.clap#org.openmixer.eq8: the daemon the UI talks
  to (port 5570) holds the pin of the old binary. The pin file was rewritten at 08:41; that daemon was not
  restarted, so no pin reload reached it. Each attempt left an Audio Input chain holding an "omx eq8" box with no
  processor; both were removed.
- [omx-eq8/modui-add-error-0.16.0.png](evidence/captures-2026-10-29/omx-eq8/modui-add-error-0.16.0.png): adding omx eq8 to a mod-ui pedalboard
  on 0.16.0 no longer ends the mod-ui process (no segmentation fault, no systemd restart); mod-ui shows "Error
  adding effect" and the pedalboard stays empty. mod-ui logged "unrecognized command: pin_changed" at that moment
  (its feedback parser does not know that message). The refusal text of the daemon on port 5555 is not in any log,
  so the cause there is not shown; it is probably the same pin mismatch.

The eq8 pages with one band per page remain to be captured once the daemon has reloaded its pins.

Chains and status
-----------------

- [common/add-chain-types.png](evidence/captures-2026-10-29/common/add-chain-types.png) and
  [common/add-chain-special-modui.png](evidence/captures-2026-10-29/common/add-chain-special-modui.png): the Add Chain menu and the MOD-UI entry
  under Special, which starts mod-ui and its plugin-hostd backend.
- [common/modui-chain-pedalboard-list.png](evidence/captures-2026-10-29/common/modui-chain-pedalboard-list.png) and
  [common/modui-chain-controls.png](evidence/captures-2026-10-29/common/modui-chain-controls.png): the MOD-UI chain's pedalboard list and its
  control page (the two Kars instances of the session).
- [common/chain-view-kars-zamcomp.png](evidence/captures-2026-10-29/common/chain-view-kars-zamcomp.png) and
  [common/chain-manager-all-chains.png](evidence/captures-2026-10-29/common/chain-manager-all-chains.png): the Kars chain with ZamComp, and the
  Chain Manager with both chains (Kars, ZamComp and omx eq8; MOD-UI).
- [common/mixer-with-chains-status-indicator.png](evidence/captures-2026-10-29/common/mixer-with-chains-status-indicator.png): the mixer with
  the two chains. The status symbol at the top right is the fork's CPU and xrun indicator: green below 50 percent
  load, turning to red with load, and an error symbol on an xrun; it stayed green with the plugins loaded. The UI
  has no status screen with figures; mod-ui shows CPU and RAM percentages at the bottom of its page.

Not captured
------------

- A "runs alone" row for a plugin with RT violations. The records with violations on the device are CLAP records
  (ZaMaximX2, ZaMultiComp, ZaMultiCompX2, ZamAutoSat, ZamComp, ZamCompX2, ZamDelay, deciding code
  hosting.rt-safety.violations-in-run, hosting isolated), and the menus list those plugins by their LV2 rows, which
  read RT clean; no row on the device shows RT violations.
- The cost cell of every row, cut at the right edge of the list.
- A live MOD GUI of omx-eq8, on 0.15.1 (segmentation fault) and on 0.16.0 (add refused).

Usage information
-----------------

What the UI shows today: every plugin-hostd row carries latency (measured/declared frames), RT safety and cost.
Cost reads unknown on the device because the records have no cell at its 48000 Hz and 256 frames. The chain
estimate footer at the bottom of the plugin list reads "estimate unavailable" on plugin-hostd 0.13.1, which does not
answer the estimate verb; it is shown as it is.

What comes next: the estimate verb (plugin-hostd#224) gives the chain's latency, CPU, RAM and workers for the
plugins in the chain plus the highlighted one, and zynthian-ui#13 shows CPU and RAM per chain before an insert; the
footer then reads figures in place of "estimate unavailable".
