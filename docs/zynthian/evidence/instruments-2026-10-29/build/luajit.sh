#!/bin/bash
# LuaJIT for aarch64: surge builds it at configure time with the host compiler, which a cross build cannot link.
# Building it first into the place surge looks for it makes the configure step reuse it.
set -euo pipefail
dpkg --add-architecture arm64; apt-get update -qq; DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends crossbuild-essential-arm64 build-essential file >/dev/null
BD=/out/b/libs/luajitlib/LuaJIT
rm -rf $BD; mkdir -p $BD/src $BD/bin $BD/include
cp -r /src/surge/libs/luajitlib/LuaJIT $BD/src
cd $BD/src/LuaJIT/src
make amalg BUILDMODE=static CROSS=aarch64-linux-gnu- HOST_CC=gcc TARGET_SYS=Linux CFLAGS+=" -fPIC -fvisibility=hidden" > /out/luajit-make.log 2>&1
cp lib*a $BD/bin; cp *.h *.hpp $BD/include
cd /tmp; ar x $BD/bin/libluajit.a; file /tmp/*.o | head -2
