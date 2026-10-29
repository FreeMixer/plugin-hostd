# Grouped (one worker per chain) vs one process per plugin

Raspberry Pi 5, Zynthian vangelis-2610.1 (Debian 13 arm64, kernel 6.18), governor performance during the run (powersave restored after), 4 cores.
plugin-hostd 0.12.0 with omx-clap-host 0.22.1 as the worker, `require_pins 1` with the pin file written by plugin-qualify-sync (every plugin used carries verdict=in-process).
Plugins: N instances in series, cycling omx-chorus, omx-comp, omx-deesser, omx-delay, omx-drive, omx-eq8, omx-flanger, omx-geq (omx-plugins 0.13.0). Sine in, 256 frames, private JACK server (`jackd -n gvp<rate> -d dummy`), the live JACK untouched.
Window 10 s after a 1 s warm-up. Processes: plugin-hostd plus its workers. RSS and PSS summed over those processes. cpu_pct: utime+stime of those processes over the window, percent of one core. ctx: voluntary plus involuntary context switches of all their threads over the window. DSP: `jack_cpu_load` once a second (avg / max). xruns: JACK xrun callbacks during the window. Stress: 8 busy-loop python processes on the 4 cores.
Outputs of both modes carry the same signal (peak equal within 1%).

| rate | N | stress | mode | procs | JACK clients | RSS MB | PSS MB | cpu_pct | ctx | DSP avg/max % | xruns |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 48000 | 3 | no | grouped | 2 | 1 | 113.4 | 31.0 | 2.1 | 2795 | 2.1 / 2.27 | 0 |
| 48000 | 3 | no | individual | 4 | 3 | 331.0 | 59.0 | 2.6 | 7579 | 2.34 / 2.37 | 0 |
| 48000 | 3 | yes | grouped | 2 | 1 | 113.4 | 30.9 | 2.4 | 2838 | 2.11 / 2.23 | 0 |
| 48000 | 3 | yes | individual | 4 | 3 | 330.9 | 58.9 | 2.7 | 7616 | 2.4 / 2.45 | 0 |
| 48000 | 8 | no | grouped | 2 | 1 | 118.1 | 35.6 | 3.9 | 2793 | 3.86 / 3.88 | 0 |
| 48000 | 8 | no | individual | 9 | 8 | 881.6 | 92.7 | 6.3 | 19612 | 4.86 / 4.9 | 0 |
| 48000 | 8 | yes | grouped | 2 | 1 | 118.1 | 35.6 | 4.0 | 2809 | 3.89 / 3.99 | 0 |
| 48000 | 8 | yes | individual | 9 | 8 | 881.7 | 92.6 | 6.49 | 19820 | 4.92 / 5.33 | 0 |
| 48000 | 16 | no | grouped | 2 | 1 | 125.4 | 42.9 | 7.2 | 2801 | 7.25 / 7.29 | 0 |
| 48000 | 16 | no | individual | 17 | 16 | 1764.6 | 118.2 | 13.39 | 38985 | 9.83 / 9.98 | 0 |
| 48000 | 16 | yes | grouped | 2 | 1 | 125.4 | 42.9 | 7.3 | 2795 | 7.24 / 7.31 | 0 |
| 48000 | 16 | yes | individual | 17 | 16 | 1764.5 | 118.0 | 13.15 | 39219 | 9.94 / 12.49 | 18 |
| 96000 | 3 | no | grouped | 2 | 1 | 113.4 | 31.0 | 3.8 | 4678 | 4.05 / 4.11 | 0 |
| 96000 | 3 | no | individual | 4 | 3 | 330.9 | 59.0 | 4.6 | 13233 | 4.52 / 4.57 | 0 |
| 96000 | 3 | yes | grouped | 2 | 1 | 113.4 | 30.9 | 3.9 | 4749 | 4.16 / 4.26 | 0 |
| 96000 | 3 | yes | individual | 4 | 3 | 330.9 | 59.0 | 4.8 | 13397 | 4.62 / 4.82 | 0 |
| 96000 | 8 | no | grouped | 2 | 1 | 118.1 | 35.6 | 7.5 | 4679 | 7.62 / 7.79 | 2 |
| 96000 | 8 | no | individual | 9 | 8 | 881.5 | 92.7 | 10.69 | 34674 | 9.38 / 9.45 | 0 |
| 96000 | 8 | yes | grouped | 2 | 1 | 118.1 | 35.6 | 7.4 | 4696 | 7.59 / 7.76 | 3 |
| 96000 | 8 | yes | individual | 9 | 8 | 881.7 | 92.6 | 11.38 | 34875 | 9.53 / 10.15 | 10 |
| 96000 | 16 | no | grouped | 2 | 1 | 125.4 | 42.9 | 14.2 | 4700 | 14.41 / 14.79 | 0 |
| 96000 | 16 | no | individual | 17 | 16 | 1764.5 | 118.2 | 22.68 | 69466 | 19.16 / 22.33 | 13 |
| 96000 | 16 | yes | grouped | 2 | 1 | 125.4 | 42.9 | 14.2 | 4717 | 14.37 / 14.61 | 5 |
| 96000 | 16 | yes | individual | 17 | 16 | 1764.4 | 118.0 | 23.33 | 76520 | 19.52 / 19.94 | 0 |

## Ratios, individual / grouped (no stress)

| rate | N | processes | RSS | PSS | cpu_pct | ctx | DSP avg |
|---|---|---|---|---|---|---|---|
| 48000 | 3 | 4 vs 2 | 2.92x | 1.90x | 1.24x | 2.71x | 1.11x |
| 48000 | 8 | 9 vs 2 | 7.46x | 2.60x | 1.62x | 7.02x | 1.26x |
| 48000 | 16 | 17 vs 2 | 14.07x | 2.76x | 1.86x | 13.92x | 1.36x |
| 96000 | 3 | 4 vs 2 | 2.92x | 1.90x | 1.21x | 2.83x | 1.12x |
| 96000 | 8 | 9 vs 2 | 7.46x | 2.60x | 1.43x | 7.41x | 1.23x |
| 96000 | 16 | 17 vs 2 | 14.07x | 2.76x | 1.60x | 14.78x | 1.33x |

Xruns summed over the 12 runs of each mode: grouped 10, individual 41.
The runs are single 10 s windows; xruns are few and unevenly spread (grouped 96 kHz N=8: 2 and 3, N=16 stressed: 5; individual 96 kHz N=16: 13, N=8 stressed: 10, 48 kHz N=16 stressed: 18), so read them as a count, not as a rate. No hardware claim is made from any of it: DSP load and xruns are the JACK dummy driver's.

Finding: a chain of CLAP members is one JACK client (the head's `effect_<n>` carries the chain's ports); the FreeMixer/zynthian-ui engine still names each processor `effect_<instance>` (open).
