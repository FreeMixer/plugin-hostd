/*
 * This file is part of plugin-hostd.
 *
 * plugin-hostd is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * plugin-hostd is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with plugin-hostd.  If not, see <http://www.gnu.org/licenses/>.
 *
 * Copyright (C) 2026 Pau Aliagas <linuxnow@gmail.com>
 */

/* include/plugin-hostd/pin.h against answers it did not compute: the FIPS 180-2 examples, sha256sum of a file, and
 * omx-layout/1 bytes and their digests written out by hand and hashed by another implementation (Python's hashlib). */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <plugin-hostd/pin.h>

static int failures, checks;

static void check(int ok, const char *what)
{
    checks++;
    if (!ok)
    {
        failures++;
        printf("FAIL pin: %s\n", what);
    }
}

static void check_hex(const char *got, const char *want, const char *what)
{
    checks++;
    if (strcmp(got, want))
    {
        failures++;
        printf("FAIL pin: %s\n     got  %s\n     want %s\n", what, got, want);
    }
}

typedef struct BUF_T {
    char data[4096];
    size_t used;
} buf_t;

static void buf_sink(void *ctx, const char *data, size_t size)
{
    buf_t *b = ctx;

    if (b->used + size < sizeof(b->data))
    {
        memcpy(b->data + b->used, data, size);
        b->used += size;
        b->data[b->used] = '\0';
    }
}

static void sha256_known_answers(void)
{
    static const struct { const char *text; const char *digest; } vectors[] = {
        { "", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" },
        { "abc", "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad" },
        { "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq",
          "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1" },
    };
    char hex[PHD_SHA256_HEX_LEN + 1], *million;
    phd_sha256_t c;
    size_t n;

    for (n = 0; n < sizeof(vectors) / sizeof(vectors[0]); n++)
    {
        phd_sha256_hex(vectors[n].text, strlen(vectors[n].text), hex);
        check_hex(hex, vectors[n].digest, vectors[n].text);
    }
    million = malloc(1000000);
    memset(million, 'a', 1000000);
    phd_sha256_hex(million, 1000000, hex);
    check_hex(hex, "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0", "one million 'a'");
    /* the same bytes fed in pieces that straddle every block boundary */
    phd_sha256_init(&c);
    for (n = 0; n < 1000000; n += 1 + n % 97)
        phd_sha256_update(&c, million + n, (n + 1 + n % 97 > 1000000 ? 1000000 - n : 1 + n % 97));
    phd_sha256_final(&c, hex);
    check_hex(hex, "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0", "one million 'a' in pieces");
    free(million);
}

static void file_digest(void)
{
    char path[] = "/tmp/plugin-hostd-pin.XXXXXX", hex[PHD_SHA256_HEX_LEN + 1];
    int fd = mkstemp(path);

    check(fd >= 0 && write(fd, "abc", 3) == 3, "a scratch file");
    check(phd_pin_fd_digest(fd, hex) == 0, "a descriptor at its end is read from its start");
    check_hex(hex, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", "the file holding abc");
    check(phd_pin_fd_digest(fd, hex) == 0, "the same descriptor again");
    check_hex(hex, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", "the file holding abc, again");
    close(fd);
    unlink(path);
    check(phd_pin_fd_digest(fd, hex) != 0, "a closed descriptor is an error, not a digest");
}

static void clap_layout(void)
{
    static const char want[] =
        "omx-layout/1 clap\n"
        "2\tMix\\\\Wet\\n\t0000000000000000\t3ff0000000000000\t3fe0000000000000\t40000000\n"
        "7\tGain\\tdB\tc04e000000000000\t4028000000000000\t0000000000000000\t00000001\n"
        "4294967295\tbypass\t0000000000000000\t3ff0000000000000\t0000000000000000\t00000031\n";
    const phd_layout_clap_param_t params[] = {
        { 7, "Gain\tdB", -60.0, 12.0, 0.0, 0x1 },
        { 4294967295u, "bypass", 0.0, 1.0, 0.0, 0x31 },
        { 2, "Mix\\Wet\n", 0.0, 1.0, 0.5, 0x40000000 },
    };
    char hex[PHD_SHA256_HEX_LEN + 1];
    buf_t b = { "", 0 };

    check(phd_layout_clap_write(params, 3, buf_sink, &b) == 0, "a CLAP layout is written");
    check(!strcmp(b.data, want), "the CLAP bytes: sorted by id, escaped, numbers as their bits, flags as 8 hex digits");
    if (strcmp(b.data, want))
        printf("     got  %s", b.data);
    check(phd_layout_clap_digest(params, 3, hex) == 0, "a CLAP digest");
    check_hex(hex, "c1a3a4e239e20653d34b7282bbeae683d331fcc4a395185507b1616978d82d78", "the CLAP layout digest");
    check(phd_layout_clap_digest(params, 0, hex) == 0, "an empty CLAP layout");
    phd_sha256_hex(PHD_PIN_LAYOUT_SCHEME " clap\n", strlen(PHD_PIN_LAYOUT_SCHEME " clap\n"), b.data);
    check_hex(hex, b.data, "an empty CLAP layout is its first line alone");
}

static void lv2_layout(void)
{
    static const char want[] =
        "omx-layout/1 lv2\n"
        "1\tgain\tin\t-\t3fb99999a0000000\t3fb99999a0000000\t"
        "http://lv2plug.in/ns/ext/port-props#logarithmic http://lv2plug.in/ns/lv2core#integer\n"
        "3\tlevel\tout\t0000000000000000\t3ff0000000000000\t-\t-\n";
    static const char *const props[] = {
        "http://lv2plug.in/ns/lv2core#integer", "http://lv2plug.in/ns/ext/port-props#logarithmic",
    };
    float tenth = 0.1f;
    const phd_layout_lv2_port_t ports[] = {
        { 3, "level", 1, PHD_LAYOUT_HAS_MIN | PHD_LAYOUT_HAS_MAX, 0.0f, 1.0f, 0.0, NULL, 0 },
        { 1, "gain", 0, PHD_LAYOUT_HAS_MAX | PHD_LAYOUT_HAS_DEF, 0.0, tenth, tenth, props, 2 },
    };
    char hex[PHD_SHA256_HEX_LEN + 1];
    buf_t b = { "", 0 };

    check(phd_layout_lv2_write(ports, 2, buf_sink, &b) == 0, "an LV2 layout is written");
    check(!strcmp(b.data, want), "the LV2 bytes: sorted by index, a float widened, - for a number not declared, "
                                 "properties sorted bytewise");
    if (strcmp(b.data, want))
        printf("     got  %s", b.data);
    check(phd_layout_lv2_digest(ports, 2, hex) == 0, "an LV2 digest");
    check_hex(hex, "ea8f2e6dd64cd44352cf25fcae657aeb6524a7a735f5836af8acb42f37d261f7", "the LV2 layout digest");
}

static void layout_pin_words(void)
{
    char scheme[32], hex[PHD_SHA256_HEX_LEN + 1];

    check(phd_pin_layout_parse(PHD_PIN_LAYOUT_SCHEME ":ea8f2e6dd64cd44352cf25fcae657aeb6524a7a735f5836af8acb42f37d261f7",
                               scheme, sizeof(scheme), hex) == 0, "a layout pin");
    check(!strcmp(scheme, PHD_PIN_LAYOUT_SCHEME), "its scheme");
    check_hex(hex, "ea8f2e6dd64cd44352cf25fcae657aeb6524a7a735f5836af8acb42f37d261f7", "its digest");
    check(phd_pin_layout_parse("omx-layout/1:EA8F2E6DD64CD44352CF25FCAE657AEB6524A7A735F5836AF8ACB42F37D261F7",
                               scheme, sizeof(scheme), hex) != 0, "upper-case hex is not a pin's");
    check(phd_pin_layout_parse("omx-layout/1:ea8f", scheme, sizeof(scheme), hex) != 0, "a short digest");
    check(phd_pin_layout_parse(":ea8f2e6dd64cd44352cf25fcae657aeb6524a7a735f5836af8acb42f37d261f7",
                               scheme, sizeof(scheme), hex) != 0, "no scheme");
    check(!phd_pin_hex_valid("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b8550"), "65 digits");
}

int main(void)
{
    sha256_known_answers();
    file_digest();
    clap_layout();
    lv2_layout();
    layout_pin_words();
    if (failures)
    {
        printf("pin.h FAILED (%d of %d)\n", failures, checks);
        return 1;
    }
    printf("ok   pin.h: %d checks, SHA-256 known answers, a file digest and omx-layout/1 for CLAP and LV2\n", checks);
    return 0;
}
