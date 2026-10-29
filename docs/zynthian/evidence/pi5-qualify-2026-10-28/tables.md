| host profile | format | suitable | isolated | unsuitable | format not hosted | unknown | of |
|---|---|---|---|---|---|---|---|
| jalv | lv2 | 1059 | 185 | 79 | 0 | 6 | 1329 |
| jalv | clap | 0 | 0 | 43 | 204 | 0 | 247 |
| mod-host | lv2 | 1058 | 183 | 82 | 0 | 6 | 1329 |
| mod-host | clap | 0 | 0 | 43 | 204 | 0 | 247 |
| omx-clap-host | lv2 | 1059 | 185 | 79 | 0 | 6 | 1329 |
| omx-clap-host | clap | 71 | 133 | 43 | 0 | 0 | 247 |
| openmixer-console | lv2 | 1059 | 185 | 79 | 0 | 6 | 1329 |
| openmixer-console | clap | 69 | 135 | 43 | 0 | 0 | 247 |

| cost cell (format:rate:quantum) | points | p50 | p90 | p95 | p99 | max |
|---|---|---|---|---|---|---|
| clap:44100:512 | 388 | 132.4 | 1537.0 | 2442.0 | 3671.0 | 3852.0 |
| clap:48000:512 | 388 | 118.5 | 1510.0 | 2010.0 | 3673.0 | 3973.0 |
| clap:96000:512 | 388 | 111.5 | 1347.0 | 2295.0 | 4160.0 | 6518.0 |
| clap:192000:512 | 388 | 110.1 | 1242.0 | 2732.0 | 6714.0 | 12000.0 |
| lv2:192000:512 | 1141 | 80.84 | 1148.0 | 2439.0 | 5198.0 | 27490.0 |

| plugin | format | 48000/512 median | 48000/512 p95 | 192000/512 median | 192000/512 p95 | per 512-frame block at 48000, median (us) | RT sweep (rate swept) |
|---|---|---|---|---|---|---|---|
| org.openmixer.chorus | clap | 0.8506 | 799.9 | 0.8496 | 795.2 | 0.44 | clean at 44100 |
| org.openmixer.comp | clap | 13.6 | 379.2 | 13.53 | 384.7 | 6.96 | clean at 44100 |
| org.openmixer.deesser | clap | 12.8 | 117.4 | 12.73 | 116.9 | 6.56 | clean at 44100 |
| org.openmixer.delay | clap | 5.987 | 592.4 | 5.914 | 574.5 | 3.07 | clean at 44100 |
| org.openmixer.drive | clap | 3.418 | 333.6 | 3.057 | 333.3 | 1.75 | clean at 44100 |
| org.openmixer.eq16 | clap | 12.19 | 129.9 | 11.61 | 129.2 | 6.24 | clean at 44100 |
| org.openmixer.eq32 | clap | 161.9 | 238.5 | 161.2 | 237.3 | 82.88 | clean at 44100 |
| org.openmixer.eq8 | clap | 8.572 | 79.62 | 8.265 | 79.25 | 4.39 | clean at 44100 |
| org.openmixer.flanger | clap | 0.7969 | 120.3 | 0.7969 | 122.2 | 0.41 | clean at 44100 |
| org.openmixer.geq | clap | 9.946 | 497.5 | 9.893 | 497.2 | 5.09 | clean at 44100 |
| org.openmixer.keyed-gate | clap | 34.87 | 91.09 | 37.45 | 84.27 | 17.85 | clean at 44100 |
| org.openmixer.limiter | clap | 1.555 | 158.6 | 3.037 | 159.9 | 0.80 | clean at 44100 |
| org.openmixer.phaser | clap | 0.8682 | 161.9 | 0.832 | 151.3 | 0.44 | clean at 44100 |
| org.openmixer.pitch | clap | 1.34 | 235.5 | 1.267 | 237.2 | 0.69 | clean at 44100 |
| org.openmixer.reverb | clap | 54.71 | 281 | 63.42 | 769.7 | 28.01 | clean at 44100 |
| org.openmixer.rotary | clap | 1.339 | 300 | 1.356 | 298.9 | 0.69 | clean at 44100 |
| org.openmixer.strip | clap | 11.5 | 521.4 | 11.32 | 522.3 | 5.89 | clean at 44100 |
| org.openmixer.transient | clap | 71.52 | 147.3 | 71.16 | 145.1 | 36.62 | clean at 44100 |
| org.openmixer.tremolo | clap | 8.391 | 19.17 | 16.55 | 19.17 | 4.30 | clean at 44100 |
| urn:openmixer:chorus | lv2 | - | - | 592.2 | 805.3 | not measured | clean at 192000 |
| urn:openmixer:comp | lv2 | - | - | 49.97 | 93.66 | not measured | clean at 192000 |
| urn:openmixer:deesser | lv2 | - | - | 92.77 | 106.5 | not measured | clean at 192000 |
| urn:openmixer:delay | lv2 | - | - | 10.74 | 561.1 | not measured | clean at 192000 |
| urn:openmixer:drive | lv2 | - | - | 267.5 | 440.2 | not measured | clean at 192000 |
| urn:openmixer:eq16 | lv2 | - | - | 141.4 | 244.4 | not measured | clean at 192000 |
| urn:openmixer:eq32 | lv2 | - | - | 254.1 | 439.5 | not measured | clean at 192000 |
| urn:openmixer:eq8 | lv2 | - | - | 66.39 | 147.4 | not measured | clean at 192000 |
| urn:openmixer:flanger | lv2 | - | - | 116.2 | 118.6 | not measured | clean at 192000 |
| urn:openmixer:geq | lv2 | - | - | 255.9 | 501.2 | not measured | clean at 192000 |
| urn:openmixer:keyed-gate | lv2 | - | - | 81.47 | 120.3 | not measured | clean at 192000 |
| urn:openmixer:limiter | lv2 | - | - | 147.4 | 151.8 | not measured | clean at 192000 |
| urn:openmixer:phaser | lv2 | - | - | 105.4 | 152.2 | not measured | clean at 192000 |
| urn:openmixer:pitch | lv2 | - | - | 187.4 | 235.8 | not measured | clean at 192000 |
| urn:openmixer:reverb | lv2 | - | - | 153.6 | 744.1 | not measured | clean at 192000 |
| urn:openmixer:rotary | lv2 | - | - | 289.3 | 291.6 | not measured | clean at 192000 |
| urn:openmixer:strip | lv2 | - | - | 183.6 | 569 | not measured | clean at 192000 |
| urn:openmixer:transient | lv2 | - | - | 142.2 | 148.7 | not measured | clean at 192000 |
| urn:openmixer:tremolo | lv2 | - | - | 17.38 | 19.02 | not measured | clean at 192000 |
