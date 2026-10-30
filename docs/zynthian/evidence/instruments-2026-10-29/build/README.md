Surge XT CLAP for trixie arm64
==============================

Built from surge-synthesizer/surge `main` at `dab78c6170732b3883216e569a84bf084ae0ea97` (project version 1.4.0) as
CLAP, in a `debian:trixie` amd64 container with Debian's arm64 cross toolchain and arm64 multiarch
libraries (no qemu: the build host's binfmt registration was not ours to change). The result is
`Surge XT.clap`, ELF aarch64, sha256 `097a80795a0d0f89be441a5244cc61d345d382858b1874f808e82feb4d7b7500` after
`aarch64-linux-gnu-strip`, needing only libfontconfig, libfreetype, libstdc++, libm, libgcc_s and libc.

    git clone --recursive https://github.com/surge-synthesizer/surge.git
    podman run --rm --arch amd64 -v $PWD:/src -v $PWD/out:/out docker.io/amd64/debian:trixie /src/luajit.sh
    podman run --rm --arch amd64 -v $PWD:/src -v $PWD/out:/out docker.io/amd64/debian:trixie /src/build.sh
    aarch64-linux-gnu-strip -o 'Surge XT.clap' 'out/b/surge_xt_products/Surge XT.clap'

with `build.sh`, `luajit.sh` and `tc-trixie-aarch64.cmake` from this directory next to `surge/`. Two things a plain
cross build trips on, both handled here: JUCE's `juceaide` is built for the build machine, so the container needs the
native compiler and the native freetype and fontconfig headers too; and LuaJIT is built with the host compiler at
configure time unless `CROSS=aarch64-linux-gnu-` reaches its make (`luajit.sh`).
