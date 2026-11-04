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

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <plugin-hostd/protocol.h>

#include "session.h"
#include "reply_words.h"

static const char *const g_extensions[] = OMX_PLUGIN_HOSTD_PROTOCOL_EXTENSIONS_INIT;
#define EXTENSIONS (sizeof(g_extensions) / sizeof(g_extensions[0]))

static unsigned char g_granted[EXTENSIONS];
/* the number of the last feedback line; the relay's thread numbers them */
static unsigned long g_seq;

static int granted(const char *extension)
{
    size_t i;

    for (i = 0; i < EXTENSIONS; i++)
        if (!strcmp(g_extensions[i], extension))
            return __atomic_load_n(&g_granted[i], __ATOMIC_SEQ_CST);
    return 0;
}

void session_reset(void)
{
    size_t i;

    for (i = 0; i < EXTENSIONS; i++)
        __atomic_store_n(&g_granted[i], 0, __ATOMIC_SEQ_CST);
    __atomic_store_n(&g_seq, 0, __ATOMIC_SEQ_CST);
}

char *session_hello(char **tok, int ntok)
{
    unsigned char want[EXTENSIONS];
    char *end, *out;
    size_t i, size = 32, pos;
    long version;
    int n;

    version = strtol(tok[1], &end, 10);
    if (!*tok[1] || *end || version < 1)
        return strdup("resp -902");
    for (i = 0; i < EXTENSIONS; i++)
    {
        want[i] = 0;
        for (n = 2; n < ntok; n++)
            if (!strcmp(tok[n], g_extensions[i]))
                want[i] = 1;
        size += strlen(g_extensions[i]) + 1;
    }
    out = malloc(size);
    if (!out)
        return NULL;
    /* the numbers start again at 1 after a hello, and a hello that drops seq drops them */
    __atomic_store_n(&g_seq, 0, __ATOMIC_SEQ_CST);
    pos = snprintf(out, size, "resp 0 %d", PLUGIN_HOSTD_PROTOCOL_VERSION);
    for (i = 0; i < EXTENSIONS; i++)
    {
        __atomic_store_n(&g_granted[i], want[i], __ATOMIC_SEQ_CST);
        if (want[i])
            pos += snprintf(out + pos, size - pos, " %s", g_extensions[i]);
    }
    return out;
}

static int tag_char(char c)
{
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.';
}

size_t session_tag_len(const char *line)
{
    size_t n = 1;

    if (line[0] != '@' || !granted(OMX_PLUGIN_HOSTD_PROTOCOL_EXTENSIONS_TAGS))
        return 0;
    while (tag_char(line[n]))
        n++;
    return n > 1 && (line[n] == ' ' || line[n] == '\0') ? n : 0;
}

/* "resp <n>" alone, n a refusal the protocol declares a code for: the text and the word, else the text */
static char *with_word(char *text)
{
    char bare[32], *line;
    size_t i, size;
    int resp;

    if (sscanf(text, "resp %d", &resp) != 1 || resp >= 0)
        return text;
    snprintf(bare, sizeof(bare), "resp %d", resp);
    if (strcmp(bare, text))
        return text;
    for (i = 0; i < sizeof(g_reply_words) / sizeof(g_reply_words[0]); i++)
    {
        if (g_reply_words[i].resp != resp)
            continue;
        size = strlen(text) + 1 + strlen(g_reply_words[i].code) + 1;
        line = malloc(size);
        /* with no memory for the word the refusal goes out bare: its number says it */
        if (!line)
            return text;
        snprintf(line, size, "%s %s", text, g_reply_words[i].code);
        free(text);
        return line;
    }
    return text;
}

char *session_answer(char *text, const char *tag, size_t tag_len)
{
    char *line;

    if (!text)
        return NULL;
    if (granted(OMX_PLUGIN_HOSTD_PROTOCOL_EXTENSIONS_ERRORS))
        text = with_word(text);
    if (!tag)
        return text;
    line = malloc(tag_len + 1 + strlen(text) + 1);
    /* with no memory for the tag the answer goes out bare, in its place: answers keep the order of requests */
    if (!line)
        return text;
    memcpy(line, tag, tag_len);
    line[tag_len] = ' ';
    strcpy(line + tag_len + 1, text);
    free(text);
    return line;
}

size_t session_feedback_prefix(char *buf, size_t size)
{
    unsigned long n;

    buf[0] = '\0';
    if (!granted(OMX_PLUGIN_HOSTD_PROTOCOL_EXTENSIONS_SEQ))
        return 0;
    n = __atomic_add_fetch(&g_seq, 1, __ATOMIC_SEQ_CST);
    return (size_t)snprintf(buf, size, "#%lu ", n);
}
