#!/bin/bash
# Surge XT main as CLAP for Debian trixie arm64, cross-compiled in a debian:trixie amd64 container.
# /src holds this directory and a clone of surge (git clone --recursive), /out the build; run luajit.sh first.
set -euxo pipefail
dpkg --add-architecture arm64
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends crossbuild-essential-arm64 build-essential cmake ninja-build git python3 pkg-config file ca-certificates \
  libcairo2-dev:arm64 libxkbcommon-x11-dev:arm64 libxkbcommon-dev:arm64 libxcb-cursor-dev:arm64 libxcb-keysyms1-dev:arm64 libxcb-util-dev:arm64 \
  libxrandr-dev:arm64 libxinerama-dev:arm64 libxcursor-dev:arm64 libasound2-dev:arm64 libjack-jackd2-dev:arm64 libfreetype-dev:arm64 libfontconfig-dev:arm64 libx11-dev:arm64 libxext-dev:arm64 libgl-dev:arm64 libcurl4-openssl-dev:arm64 libfreetype-dev libfontconfig-dev libx11-dev libxext-dev libxrandr-dev libxinerama-dev libxcursor-dev libasound2-dev
cd /src/surge
cmake -G Ninja -B /out/b -DCMAKE_TOOLCHAIN_FILE=/src/tc-trixie-aarch64.cmake -DCMAKE_BUILD_TYPE=Release -DSURGE_BUILD_CLAP=TRUE -DSURGE_BUILD_LV2=FALSE -DSURGE_EXPOSE_PRESETS=TRUE -DSURGE_SKIP_STANDALONE=TRUE -DCMAKE_INSTALL_PREFIX=/usr/local
cmake --build /out/b --target surge-xt_CLAP --parallel 16
find /out/b -name "*.clap" -exec file {} \;
