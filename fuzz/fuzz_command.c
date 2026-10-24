/* SPDX-License-Identifier: GPL-3.0-or-later */
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

/* libFuzzer harness: THE COMMAND PARSER AND DISPATCHER (src/verbs.c, verbs_receive and everything it calls in that
 * file), with the mod-host side replaced by the recorder of fuzz/recorder.c. A controller's message is whatever bytes
 * it sends; the daemon reads its words, refuses what is outside its grammar, and hands the rest to the supervisor.
 *
 * Input: up to MESSAGES_MAX messages, each
 *          [flags] [u16 LE length] [that many bytes, at most MESSAGE_MAX]
 *        flags bit 0: the recorder refuses every call of this message that can refuse, with the declared code
 *        rec_codes[(flags >> 1) % rec_ncodes]; clear, it accepts with the reply each verb declares. Each message is
 *        copied into an allocation of exactly its length, with no terminator, as the socket hands it over.
 *
 * The words of a message, below, are what the daemon reads: its bytes up to the first NUL, the newlines, carriage
 * returns and spaces at its end removed, split at spaces and tabs. Its verb is the first word.
 *
 * Properties, each an abort():
 *   - reply: every message gets exactly one reply, one NUL-terminated string with no NUL before its end, which is
 *     the text the supervisor answered, unchanged; a refusal is "resp <code>" of a declared code, and anything else
 *     has the reply shape its verb declares (PHD_VERBS, PHD_INSTANCE_VERBS) or mod-host's "resp 0".
 *     Mutant: fuzz/mutants/command-reply.patch, the reply sent without its NUL.
 *   - arity: a verb the daemon parses itself (PHD_VERBS, the rows tools/protocol-gen.c writes into
 *     protocol/plugin-hostd.json, and mod-host's remove, connect, disconnect and quit) is acted on only with an
 *     argument count its declared syntax allows; a word past PHD_LINE_WORDS_MAX is not read.
 *     Mutant: fuzz/mutants/command-arity.patch, pool_config taking three words or more.
 *   - round-trip: the words of a command the daemon acted on, joined by one space as the declaration writes them,
 *     make the same calls with the same arguments, the same reply and the same state. A command whose last word ends
 *     in a carriage return or a newline is left out: the daemon keeps that character when a tab follows it and
 *     removes it when the line ends there, so its joined words are another command.
 *     Mutant: fuzz/mutants/command-round-trip.patch, words split at spaces only.
 *   - refusal: a refused command (its reply's code is negative) leaves the daemon's state as it was: no call the
 *     supervisor took and none of the daemon's own follow-ups (a descriptor scan, the LV2 refusals asked again, quit).
 *     The host settings are not part of it: PHD_HOST_SETTINGS keeps them as sent, whatever the workers answer.
 *     Mutant: fuzz/mutants/command-refusal.patch, a refused add still scanned.
 */

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <host-errors.h>
#include <mod-host.h>

#include <plugin-hostd/protocol.h>

#include "supervisor.h"
#include "verbs.h"

#include "fuzz.h"
#include "recorder.h"
#include "syntax.h"

#define MESSAGES_MAX 32
#define MESSAGE_MAX  (2 * PHD_LINE_MAX)

/* the verbs the daemon parses itself, with their declared argument syntax */
static const struct {
    const char *name;
    const char *syntax;
    int format;                 /* 1: syntax is a mod-host command format, "<verb> %i ..." */
} g_parsed[] = {
#define X(id, name, arguments, reply, meaning) { name, arguments, 0 },
    PHD_VERBS(X)
#undef X
    { "remove", EFFECT_REMOVE, 1 },
    { "connect", EFFECT_CONNECT, 1 },
    { "disconnect", EFFECT_DISCONNECT, 1 },
    { "quit", QUIT, 1 },
};

/* the words of a message as the daemon reads them */
struct words {
    char *text;                 /* the message up to its first NUL, its end trimmed; the words point into a copy */
    char *copy;
    char **w;
    int n;
};

static void words_of(const char *data, size_t size, struct words *out)
{
    size_t len = strnlen(data, size), cap = len / 2 + 2;
    char *t;

    out->text = malloc(len + 1);
    out->copy = malloc(len + 1);
    out->w = malloc(cap * sizeof(char *));
    if (!out->text || !out->copy || !out->w)
        abort();
    memcpy(out->text, data, len);
    out->text[len] = '\0';
    while (len > 0 && (out->text[len - 1] == '\n' || out->text[len - 1] == '\r' || out->text[len - 1] == ' '))
        out->text[--len] = '\0';
    memcpy(out->copy, out->text, len + 1);
    out->n = 0;
    for (t = out->copy; *t;)
    {
        t += strspn(t, " \t");
        if (!*t)
            break;
        out->w[out->n++] = t;
        t += strcspn(t, " \t");
        if (*t)
            *t++ = '\0';
    }
}

static void words_free(struct words *w)
{
    free(w->text);
    free(w->copy);
    free(w->w);
}

/* the message's words joined by one space */
static char *joined(const struct words *w, size_t *len)
{
    size_t n = 0;
    char *s;
    int k;

    for (k = 0; k < w->n; k++)
        n += strlen(w->w[k]) + 1;
    s = malloc(n + 1);
    if (!s)
        abort();
    s[0] = '\0';
    for (k = 0, n = 0; k < w->n; k++)
    {
        size_t l = strlen(w->w[k]);

        if (k)
            s[n++] = ' ';
        memcpy(s + n, w->w[k], l);
        n += l;
    }
    s[n] = '\0';
    *len = n;
    return s;
}

/* one message to the daemon, in an allocation of exactly its length */
static void send_message(const uint8_t *bytes, size_t len)
{
    msg_t msg;

    msg.sender_id = 7;
    msg.data = fuzz_dup(bytes, len);
    msg.data_size = len;
    g_quitting = 0;
    rec_clear();
    verbs_receive(&msg);
    free(msg.data);
}

/* whether the daemon acted on the message: it called the supervisor, or it is quitting */
static int acted(void)
{
    return g_quitting || g_rec.ncalls > 0;
}

/* the reply property */
__attribute__((noinline)) static void check_reply(const struct words *w)
{
    char refusal[32];
    const char *shape;
    int code;

    /* one reply, and it is a string that ends where the message the socket sends ends */
    if (g_rec.nreplies != 1 || g_rec.reply_size == 0)
        abort();
    if (g_rec.reply[g_rec.reply_size - 1] != '\0' || memchr(g_rec.reply, '\0', g_rec.reply_size - 1))
        abort();
    /* the supervisor's answer, as it answered it */
    if (g_rec.answer == NULL || strcmp(g_rec.reply, g_rec.answer))
        abort();
    code = sup_reply_code(g_rec.reply);
    if (code < 0)
    {
        snprintf(refusal, sizeof(refusal), "resp %d", code);
        if (!rec_code_declared(code) || strcmp(g_rec.reply, refusal))
            abort();
        return;
    }
    shape = w->n ? rec_shape_of(w->w[0], strlen(w->w[0])) : REC_MOD_HOST_SHAPE;
    if (!syntax_reply_matches(shape, g_rec.reply) && !syntax_reply_matches(REC_MOD_HOST_SHAPE, g_rec.reply))
        abort();
}

/* the arity property */
__attribute__((noinline)) static void check_arity(const struct words *w)
{
    size_t n;
    int read, min, max;

    if (w->n == 0 || !acted() || (g_rec.ncalls > 0 && g_rec.calls[0].fn == REC_BROADCAST))
        return;
    read = w->n < PHD_LINE_WORDS_MAX ? w->n : PHD_LINE_WORDS_MAX;
    for (n = 0; n < sizeof(g_parsed) / sizeof(g_parsed[0]); n++)
    {
        if (strcmp(w->w[0], g_parsed[n].name))
            continue;
        if (g_parsed[n].format)
            syntax_format_arity(g_parsed[n].syntax, &min, &max);
        else
            syntax_arity(g_parsed[n].syntax, &min, &max);
        /* acted on with an argument count the declaration allows */
        if (read - 1 < min || read - 1 > max)
            abort();
        return;
    }
}

/* the refusal property */
__attribute__((noinline)) static void check_refusal(uint64_t before)
{
    if (g_rec.reply == NULL || sup_reply_code(g_rec.reply) >= 0)
        return;
    /* nothing changed: no accepted call, no follow-up, no quit */
    if (g_rec.state != before || g_quitting)
        abort();
}

/* the round-trip property: the message has been sent, and the daemon acted on it */
__attribute__((noinline)) static void check_round_trip(const struct words *w, uint64_t state_before,
                                                       uint64_t host_before)
{
    struct rec_call first[REC_CALLS_MAX];
    int nfirst, quit_first;
    uint64_t state_first, host_first;
    char *reply_first, *line;
    const char *last;
    size_t len;

    if (w->n == 0 || !acted())
        return;
    last = w->w[w->n - 1];
    if (last[strlen(last) - 1] == '\r' || last[strlen(last) - 1] == '\n')
        return;
    nfirst = rec_calls_copy(first);
    quit_first = g_quitting;
    state_first = g_rec.state;
    host_first = g_rec.host_settings;
    reply_first = strdup(g_rec.reply);
    if (!reply_first)
        abort();

    /* the same command again, from the state it was sent in, as its words joined by one space */
    g_rec.state = state_before;
    g_rec.host_settings = host_before;
    line = joined(w, &len);
    send_message((const uint8_t *)line, len);
    free(line);

    if (!rec_calls_equal(first, nfirst, g_rec.calls, g_rec.ncalls))
        abort();
    if (g_rec.reply == NULL || strcmp(g_rec.reply, reply_first))
        abort();
    if (g_quitting != quit_first || g_rec.state != state_first || g_rec.host_settings != host_first)
        abort();
    rec_calls_free(first, nfirst);
    free(reply_first);
}

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size)
{
    struct fuzz_in in;
    int m;

    if (size >= FUZZ_INPUT_MAX)
        return 0;
    in = fuzz_in(data, size);
    rec_clear();
    g_rec.state = 0;
    g_rec.host_settings = 0;
    for (m = 0; m < MESSAGES_MAX && in.n; m++)
    {
        uint8_t flags = fuzz_u8(&in);
        uint16_t want = fuzz_u16(&in);
        const uint8_t *bytes;
        size_t len = fuzz_take(&in, want < MESSAGE_MAX ? want : MESSAGE_MAX, &bytes);
        uint64_t state_before = g_rec.state, host_before = g_rec.host_settings;
        struct words w;

        g_rec.refuse = flags & 1;
        g_rec.code = rec_codes[(flags >> 1) % rec_ncodes];
        send_message(bytes, len);
        words_of((const char *)bytes, len, &w);
        check_reply(&w);
        check_arity(&w);
        check_refusal(state_before);
        check_round_trip(&w, state_before, host_before);
        words_free(&w);
    }
    rec_clear();
    g_quitting = 0;
    return 0;
}
