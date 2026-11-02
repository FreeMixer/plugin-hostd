#!/bin/bash
# step 2: instruments and voices on the Pi 5, 48000 Hz, 256 frames, private dummy JACK servers (voices-cores.py)
export HOME=/root PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LV2_PATH=/usr/lib/lv2:/usr/lib/aarch64-linux-gnu/lv2:/usr/local/lib/lv2:/usr/local/lib/aarch64-linux-gnu/lv2:/zynthian/zynthian-plugins/lv2
export CLAP_PATH=/usr/local/lib/clap:/usr/lib/clap
export INSTRUMENT_PROBE=/root/mixbus-menu-20261102/tools/jack-instrument-probe
D=/root/omx-final-20261102; O=$D/s2-instruments; cd $D/plugin-hostd
V="python3 -I tools/zynthian/voices-cores.py --out $O --notes 1,8,16 --hold 8 --repeats 3 --rate 48000 --frames 256"
SC="clap:/usr/local/lib/clap/Surge%20XT.clap#org.surge-synth-team.surge-xt"
SL="https://surge-synthesizer.github.io/lv2/surge-xt"
ZP="/usr/share/zynaddsubfx/banks/Pads/0003-Analog Pad 1.xiz"
echo "=== step 2 begins $(date -u +%FT%TZ)"
for h in hostd mod-host; do $V --name "mda piano" --host $h --uri http://moddevices.com/plugins/mda/Piano; done
for h in hostd mod-host; do $V --name "odin 2" --host $h --uri https://thewavewarden.com/odin2 --settle 4; done
$V --name "surge xt clap" --host hostd --uri "$SC" --param "240235375 1.0" --settle 4
$V --name "surge xt lv2" --host mod-host --uri "$SL" --settle 4
$V --name "zynaddsubfx analog pad 1" --host cmd --client zynaddsubfx --settle 5 \
   --cmd "zynaddsubfx -r 48000 -b 256 -O jack -I jack -U -L \"$ZP\""
$V --name "sfizz salamander grand" --host cmd --client sfizz --settle 15 \
   --cmd "sfizz_jack --client_name sfizz --num_voices 64 $D/salamander/AccurateSalamanderGrand-Z.sfz"
echo "=== step 2 ends $(date -u +%FT%TZ)"
