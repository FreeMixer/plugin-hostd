Profile: where plugin-hostd and omx-clap-host spend time and memory
===================================================================

A ranked list of measured costs, so the next cut is always known. Each cut is measured before it is made, lands red
first with a number that must move, and its row records the number after. The console runs the same daemon and worker,
so every row also says what the console gains.

Unless a row says otherwise: a Raspberry Pi 5 running Zynthian (Debian 13 arm64, 1336 LV2 plugins on its search path),
a private JACK server on the dummy driver at 48000 Hz and 256 frames, medians of three runs.

The list
--------

| # | cost | measured | cut | status |
|---|------|----------|-----|--------|
| 1 | Two JACK clients per own worker: the host's global client (no port, only xruns and the frame clock) and the instance's. A JACK client costs about 24 ms to open and activate (14.8 + 9.0 ms), and every active client is woken each cycle | own LV2 add about 60 ms, of which about 48 ms are the two clients | the instance's own client carries the xruns and the clock; the global client exists only while the host has no instance (omx-clap-core#446) | in review |
| 2 | An add into a chain opened a client for the member and the chain line closed it again | r1, 24 plugins: 887 ms against mod-host's 470; per add 23 ms add + 13 ms line, 0.3 ms daemon | `chain_expect` (omx-clap-core#442): the member joins the walk with no client of its own; plugin-hostd sends it (#358) | 0.26.0 released; #358 in review |
| 3 | The daemon walked the search path's manifests up to three times per add, in directory order, and listed the qualification directory (3664 files) and parsed the plugin's records on each add | own LV2 add, later adds: ZamComp 69 ms, a plugin found late (x42 fil4) 91 ms | bundle memo checked by its one manifest; records remembered by directory and file time (#359) | 59 and 59 ms; in review |
| 4 | A mono plugin ends a stereo run: 378 of the 1336 LV2 plugins are 1>1, and four of the ten third-party chain | the ten third-party chain runs as four groups, not one | a 1>1 member runs dual-mono inside a stereo run (omx-clap-core#361, ruled) | after the Pi rows |
| 5 | Per-block overhead of omx-clap-host against mod-host on the same plugins | JACK DSP 6.55 % against 6.23 % (ten third-party, one process) | to profile with perf and null plugins: event drain, port copies, per-client callback | to measure |
| 6 | Every omx-clap-host process links libraries it rarely uses: libxcb, libXau, libXdmcp (the plugin window), libdb (through libjack) | loaded in every worker at start (strace); PSS per worker not yet split | load the window libraries only with `--show-ui`; then measure PSS per worker | to measure |
| 7 | A daemon's first own add | about 150 ms against about 70 ms for the next, seen once, not reproduced under strace | find what the first add does once | to reproduce |
| 8 | Grouped DSP sometimes doubles (mixbus rerun on 0.15.7: 41.31 % against 20.41 % one worker each) | intermittent, per repeat | read mixbus.tsv per repeat: core placement, RT threads, add order | queued |
| 9 | The daemon polls a new worker's socket every 2.2 ms until it answers | up to 2 ms per own add | wait on the worker's ready line or an accept | small |

How each number was taken
-------------------------

- JACK client cost: a client opened, activated, deactivated and closed eight times from python-jack-client.
- Own add split: strace of the daemon and its worker over three own adds, then the same adds without strace for the
  times; the worker's cold start measured to its first answer, from a parent that has not loaded the LV2 world (a large
  parent's fork costs tens of ms and is not the host's).
- Add time rows: `bench/run.sh --scenarios cvp24 --repeats 3` on r1 (x86_64) for row 2.
