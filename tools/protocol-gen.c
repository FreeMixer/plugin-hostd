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

/* Everything generated from include/plugin-hostd/protocol.h, compiled against it, so the values are the header's own:
 *
 *   protocol-gen json          protocol/plugin-hostd.json on stdout
 *   protocol-gen regions       the name of every region, one per line
 *   protocol-gen probe-schema TEMPLATE   TEMPLATE on stdout with each @PHD_PROBE_...@ token replaced by that list of the
 *                              header, and each @OMX_...@ token by that list of omx-contract's vocabulary header
 *   protocol-gen splice FILE   FILE on stdout with every generated region replaced; a region is the lines between
 *                              "BEGIN GENERATED protocol:<name>" and "END GENERATED protocol:<name>" */

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <omxcontract/omx_contract_limits.h>
#include <omxcontract/omx_vocabulary.h>
#include <plugin-hostd/protocol.h>

/* The parameter scales are omx-contract's PARAM_SCALES, whose words the contract declares for this protocol: the same
 * ids in the same order, or nothing generated from the header builds. The contract renders an id as its word in
 * capitals, which scales_are_the_contracts() checks of every word at run time. */
enum {
#define X(id, name, meaning) PHD_SCALE_AT_##id,
    PHD_PARAM_SCALES(X)
#undef X
    PHD_SCALE_COUNT
};
#define X(id, name, meaning) \
    _Static_assert((int)PHD_SCALE_AT_##id == (int)OMX_PARAM_SCALES_##id, "PHD_PARAM_SCALES: " #id " is not where omx-contract's PARAM_SCALES has it");
PHD_PARAM_SCALES(X)
#undef X
_Static_assert((unsigned)PHD_SCALE_COUNT == OMX_PARAM_SCALES_COUNT, "PHD_PARAM_SCALES: not as many scales as omx-contract's PARAM_SCALES");

static int scales_are_the_contracts(void)
{
    int ok = 1;
    size_t n;

#define X(id, name, meaning) \
    for (n = 0; n <= strlen(name); n++) \
        if (toupper((unsigned char)name[n]) != #id[n]) \
        { \
            fprintf(stderr, "protocol-gen: PHD_PARAM_SCALES: the word \"%s\" is not omx-contract's PARAM_SCALES id " #id "\n", name); \
            ok = 0; \
            break; \
        }
    PHD_PARAM_SCALES(X)
#undef X
    return ok;
}

#define PATH_MAX_DOC 512

/* ---------------------------------------------------------------- json */

static void jstr(const char *s)
{
    putchar('"');
    for (; *s; s++)
    {
        if (*s == '"' || *s == '\\')
            putchar('\\');
        putchar(*s);
    }
    putchar('"');
}

static void json(void)
{
    const char *sep;

    printf("{\n  \"protocol\": \"plugin-hostd\",\n  \"version\": %d,\n", PLUGIN_HOSTD_PROTOCOL_VERSION);
    printf("  \"readiness\": {\"daemon_line\": ");
    jstr(PHD_READY_LINE);
    printf(", \"worker_marker\": ");
    jstr(PHD_WORKER_READY_MARKER);
    printf("},\n  \"constants\": [");
    sep = "\n";
#define X(name, value, unit, meaning) \
    printf("%s    {\"name\": \"" #name "\", \"value\": %d, \"unit\": \"" unit "\", \"meaning\": ", sep, value); \
    jstr(meaning); \
    printf("}"); \
    sep = ",\n";
    PHD_CONSTANTS(X)
#undef X
    printf("\n  ],\n  \"placement\": {\n    \"own\": ");
    jstr(PHD_PLACE_OWN);
    printf(",\n    \"default\": ");
    jstr(PHD_PLACE_DEFAULT);
    printf(",\n    \"pool_prefix\": ");
    jstr(PHD_PLACE_POOL_PREFIX);
    printf(",\n    \"pool_sibling_separator\": ");
    jstr(PHD_POOL_SIBLING_SEPARATOR);
    printf(",\n    \"syntax\": ");
    jstr(PHD_PLACEMENT_SYNTAX);
    printf(",\n    \"pool_name\": {\"pattern\": ");
    jstr(PHD_POOL_NAME_PATTERN);
    printf(", \"class\": ");
    jstr(PHD_POOL_NAME_CLASS);
    printf(", \"min\": %d, \"max\": %d}\n  },\n", PHD_POOL_NAME_MIN, PHD_POOL_NAME_MAX);
    printf("  \"formats\": [");
    sep = "";
#define X(id, name) printf("%s\"%s\"", sep, name); sep = ", ";
    PHD_FORMATS(X)
#undef X
    printf("],\n  \"words\": {\"all\": ");
    jstr(PHD_WORD_ALL);
    printf(", \"none\": ");
    jstr(PHD_WORD_NONE);
    printf(", \"any_format\": ");
    jstr(PHD_FORMAT_ANY);
    printf("},\n  \"worker_states\": [");
    sep = "\n";
#define X(id, name, meaning) \
    printf("%s    {\"name\": \"%s\", \"meaning\": ", sep, name); \
    jstr(meaning); \
    printf("}"); \
    sep = ",\n";
    PHD_WORKER_STATES(X)
#undef X
    printf("\n  ],\n  \"errors\": [");
    sep = "\n";
#define X(id, meaning) \
    printf("%s    {\"name\": \"" #id "\", \"macro\": \"PHD_ERR_" #id "\", \"code\": %d, \"meaning\": ", sep, PHD_ERR_##id); \
    jstr(meaning); \
    printf("}"); \
    sep = ",\n";
    PHD_ERRORS(X)
#undef X
    printf("\n  ],\n  \"verbs\": [");
    sep = "\n";
#define X(id, name, args, reply, meaning) \
    printf("%s    {\"name\": ", sep); \
    jstr(name); \
    printf(", \"arguments\": "); \
    jstr(args); \
    printf(", \"reply\": "); \
    jstr(reply); \
    printf(", \"meaning\": "); \
    jstr(meaning); \
    printf("}"); \
    sep = ",\n";
    PHD_VERBS(X)
#undef X
    printf("\n  ],\n  \"instance_verbs\": [");
    sep = "\n";
#define X(id, name, args, reply, ledger, meaning) \
    printf("%s    {\"name\": ", sep); \
    jstr(name); \
    printf(", \"arguments\": "); \
    jstr(args); \
    printf(", \"reply\": "); \
    jstr(reply); \
    printf(", \"ledger\": \"%s\", \"meaning\": ", PHD_LEDGER_##ledger == PHD_LEDGER_REPLACE ? "replace" : "none"); \
    jstr(meaning); \
    printf("}"); \
    sep = ",\n";
    PHD_INSTANCE_VERBS(X)
#undef X
    printf("\n  ],\n  \"track_kinds\": [");
    sep = "";
#define X(id, name) printf("%s\"%s\"", sep, name); sep = ", ";
    PHD_TRACK_KINDS(X)
#undef X
    printf("],\n  \"param_scales\": [");
    sep = "\n";
#define X(id, name, meaning) \
    printf("%s    {\"name\": \"%s\", \"meaning\": ", sep, name); \
    jstr(meaning); \
    printf("}"); \
    sep = ",\n";
    PHD_PARAM_SCALES(X)
#undef X
    printf("\n  ],\n  \"remote_page_slots\": %d,\n  \"string_max\": %d,\n  \"events\": [", PHD_REMOTE_PAGE_SLOTS,
           PHD_STRING_MAX);
    sep = "\n";
#define X(name, fields, meaning) \
    printf("%s    {\"name\": ", sep); \
    jstr(name); \
    printf(", \"fields\": "); \
    jstr(fields); \
    printf(", \"meaning\": "); \
    jstr(meaning); \
    printf("}"); \
    sep = ",\n";
    PHD_EVENTS(X)
#undef X
    printf("\n  ],\n  \"pin_limits\": [");
    sep = "\n";
#define X(id, meaning) \
    printf("%s    {\"name\": \"" #id "\", \"meaning\": ", sep); \
    jstr(meaning); \
    printf("}"); \
    sep = ",\n";
    PHD_PIN_LIMITS(X)
#undef X
    printf("\n  ],\n  \"relay\": {\n    \"worker_arguments\": ");
    jstr(PHD_WORKER_ARGUMENTS);
    printf(",\n    \"rules\": [");
    sep = "\n";
#define X(id, meaning) \
    printf("%s      {\"name\": \"" #id "\", \"meaning\": ", sep); \
    jstr(meaning); \
    printf("}"); \
    sep = ",\n";
    PHD_RELAY(X)
#undef X
    printf("\n    ]\n  },\n  \"host_settings\": [");
    sep = "\n";
#define X(id, meaning) \
    printf("%s    {\"name\": \"" #id "\", \"meaning\": ", sep); \
    jstr(meaning); \
    printf("}"); \
    sep = ",\n";
    PHD_HOST_SETTINGS(X)
#undef X
    printf("\n  ],\n  \"config\": [");
    sep = "\n";
#define X(key, size, def, env, meaning) \
    printf("%s    {\"key\": \"" #key "\", \"type\": \"string\", \"default\": ", sep); \
    jstr(def); \
    printf(", \"env\": "); \
    jstr(env); \
    printf(", \"meaning\": "); \
    jstr(meaning); \
    printf("}"); \
    sep = ",\n";
    PHD_CONF_STRINGS(X)
#undef X
#define X(key, def, unit, meaning) \
    printf("%s    {\"key\": \"" #key "\", \"type\": \"int\", \"default\": %d, \"unit\": \"" unit "\", \"meaning\": ", sep, def); \
    jstr(meaning); \
    printf("}"); \
    sep = ",\n";
    PHD_CONF_INTS(X)
#undef X
    printf("\n  ]\n}\n");
}

/* ---------------------------------------------------------------- regions */

/* one cell of a markdown table: a '|' inside it must not end the cell */
static void cell(const char *s)
{
    for (; *s; s++)
    {
        if (*s == '|')
            putchar('\\');
        putchar(*s);
    }
}

static void row(const char *first, const char *second, const char *third, const char *fourth)
{
    putchar('|');
    cell(first);
    putchar('|');
    cell(second);
    putchar('|');
    cell(third);
    if (fourth)
    {
        putchar('|');
        cell(fourth);
    }
    printf("|\n");
}

static void region_config(void)
{
    char buffer[PATH_MAX_DOC];

    row(" key ", " default ", " meaning ", NULL);
    printf("|---|---|---|\n");
#define X(key, size, def, env, meaning) \
    if (*(env)) \
        snprintf(buffer, sizeof(buffer), " `$" env "`, else `%s` ", def); \
    else \
        snprintf(buffer, sizeof(buffer), " `%s` ", def); \
    row(" `" #key "` ", buffer, " " meaning " ", NULL);
    PHD_CONF_STRINGS(X)
#undef X
#define X(key, def, unit, meaning) \
    snprintf(buffer, sizeof(buffer), " %d %s ", def, unit); \
    row(" `" #key "` ", buffer, " " meaning " ", NULL);
    PHD_CONF_INTS(X)
#undef X
}

static void region_constants(void)
{
    char buffer[PATH_MAX_DOC];

    row(" name ", " value ", " meaning ", NULL);
    printf("|---|---|---|\n");
#define X(name, value, unit, meaning) \
    snprintf(buffer, sizeof(buffer), " %d %s ", value, unit); \
    row(" `" #name "` ", buffer, " " meaning " ", NULL);
    PHD_CONSTANTS(X)
#undef X
}

static void region_placement(void)
{
    printf("The placement of an `add` is `%s`. `%s` is a worker for that instance alone; `%s<name>` is the pool's worker, "
           "opened on first use and capped by `%s`, and a full pool opens `<name>%s2`, `<name>%s3`, and so on; `%s` is "
           "the policy of `%s`. A pool name matches `%s`.\n",
           PHD_PLACEMENT_SYNTAX, PHD_PLACE_OWN, PHD_PLACE_POOL_PREFIX, PHD_VERB_POOL_CONFIG, PHD_POOL_SIBLING_SEPARATOR,
           PHD_POOL_SIBLING_SEPARATOR, PHD_PLACE_DEFAULT, PHD_VERB_POLICY_SET, PHD_POOL_NAME_PATTERN);
}

static void region_verbs(void)
{
    const char *sep = "";
    char args[PATH_MAX_DOC], reply[PATH_MAX_DOC];

    row(" verb ", " arguments ", " reply ", " meaning ");
    printf("|---|---|---|---|\n");
#define X(id, name, arguments, rep, meaning) \
    snprintf(args, sizeof(args), *(arguments) ? " `%s` " : " none ", arguments); \
    snprintf(reply, sizeof(reply), " `%s` ", rep); \
    row(" `" name "` ", args, reply, " " meaning " ");
    PHD_VERBS(X)
#undef X
    printf("\nA `<state>` is ");
#define X(id, name, meaning) printf("%s`%s` (%s)", sep, name, meaning); sep = ", ";
    PHD_WORKER_STATES(X)
#undef X
    printf(".\n");
}

static void region_instance_verbs(void)
{
    const char *sep = "";
    char args[PATH_MAX_DOC], reply[PATH_MAX_DOC];

    row(" verb ", " arguments ", " reply ", " meaning ");
    printf("|---|---|---|---|\n");
#define X(id, name, arguments, rep, ledger, meaning) \
    snprintf(args, sizeof(args), " `%s` ", arguments); \
    snprintf(reply, sizeof(reply), " `%s` ", rep); \
    row(" `" name "` ", args, reply, " " meaning " ");
    PHD_INSTANCE_VERBS(X)
#undef X
    printf("\nThe ledger keeps the latest ");
#define X(id, name, arguments, rep, ledger, meaning) \
    if (PHD_LEDGER_##ledger == PHD_LEDGER_REPLACE) { printf("%s`%s`", sep, name); sep = ", "; }
    PHD_INSTANCE_VERBS(X)
#undef X
    printf(" of an instance and replays it after the add; the others are never replayed. A `<scale>` is ");
    sep = "";
#define X(id, name, meaning) printf("%s`%s` (%s)", sep, name, meaning); sep = ", ";
    PHD_PARAM_SCALES(X)
#undef X
    printf(". A string word is at most %d bytes of UTF-8 with no control character.\n", PHD_STRING_MAX);
}

static void region_errors(void)
{
    char code[PATH_MAX_DOC];

    row(" code ", " name ", " meaning ", NULL);
    printf("|---|---|---|\n");
#define X(id, meaning) \
    snprintf(code, sizeof(code), " `%d` ", PHD_ERR_##id); \
    row(code, " `PHD_ERR_" #id "` ", " " meaning " ", NULL);
    PHD_ERRORS(X)
#undef X
}

static void region_events(void)
{
    char fields[PATH_MAX_DOC];

    row(" event ", " fields ", " meaning ", NULL);
    printf("|---|---|---|\n");
#define X(name, fld, meaning) \
    snprintf(fields, sizeof(fields), " `%s` ", fld); \
    row(" `" name "` ", fields, " " meaning " ", NULL);
    PHD_EVENTS(X)
#undef X
}

static void region_pin_limits(void)
{
#define X(id, meaning) printf("- %s.\n", meaning);
    PHD_PIN_LIMITS(X)
#undef X
}

static void roff_escape(const char *s);

static void region_relay(void)
{
    printf("Every worker is started as `<program> %s`.\n\n", PHD_WORKER_ARGUMENTS);
#define X(id, meaning) printf("- %s.\n", meaning);
    PHD_RELAY(X)
#undef X
}

static void region_host_settings(void)
{
#define X(id, meaning) printf("- %s.\n", meaning);
    PHD_HOST_SETTINGS(X)
#undef X
}

static void region_man_host_settings(void)
{
#define X(id, meaning) printf(".IP \\(bu 2\n"); roff_escape(meaning); printf(".\n");
    PHD_HOST_SETTINGS(X)
#undef X
}

static void region_man_relay(void)
{
#define X(id, meaning) printf(".IP \\(bu 2\n"); roff_escape(meaning); printf(".\n");
    PHD_RELAY(X)
#undef X
}

static void region_readiness(void)
{
    printf("It prints `%s` once both ports accept.\n", PHD_READY_LINE);
}

static void region_worker_ready(void)
{
    printf("- print a line ending `%s` on stdout once its socket accepts;\n", PHD_WORKER_READY_MARKER);
}

static void roff_escape(const char *s)
{
    for (; *s; s++)
    {
        if (*s == '-')
            putchar('\\');
        putchar(*s);
    }
}

static void region_man_keys(void)
{
    const char *sep = "";

    printf(".RI \\(dq key \" value\" \\(dq\nper line: ");
#define X(key, size, def, env, meaning) printf("%s" #key, sep); sep = ", ";
    PHD_CONF_STRINGS(X)
#undef X
#define X(key, def, unit, meaning) printf("%s" #key, sep); sep = ", ";
    PHD_CONF_INTS(X)
#undef X
    printf(".\n");
}

static void region_man_ready(void)
{
    printf(".B ");
    roff_escape(PHD_READY_LINE);
    printf("\n");
}

static void region_man_pin_limits(void)
{
#define X(id, meaning) printf(".IP \\(bu 2\n"); roff_escape(meaning); printf(".\n");
    PHD_PIN_LIMITS(X)
#undef X
}

static void region_man_port(void)
{
    printf("Command port (default %d).\n", PHD_DEFAULT_COMMAND_PORT);
}

static const struct {
    const char *name;
    void (*emit)(void);
} REGIONS[] = {
    { "config", region_config }, { "constants", region_constants }, { "placement", region_placement },
    { "verbs", region_verbs }, { "instance-verbs", region_instance_verbs }, { "errors", region_errors }, { "events", region_events },
    { "pin-limits", region_pin_limits }, { "man-pin-limits", region_man_pin_limits },
    { "readiness", region_readiness }, { "worker-ready", region_worker_ready },
    { "man-keys", region_man_keys }, { "man-ready", region_man_ready }, { "man-port", region_man_port },
    { "relay", region_relay }, { "man-relay", region_man_relay }, { "host-settings", region_host_settings },
    { "man-host-settings", region_man_host_settings },
};

static int splice(const char *path)
{
    char line[4096], name[64];
    FILE *file = fopen(path, "r");
    size_t n;
    int skipping = 0;

    if (!file)
    {
        perror(path);
        return 1;
    }
    while (fgets(line, sizeof(line), file))
    {
        const char *b = strstr(line, "BEGIN GENERATED protocol:"), *e = strstr(line, "END GENERATED protocol:");

        if (skipping)
        {
            if (!e)
                continue;
            skipping = 0;
        }
        else if (b)
        {
            b += strlen("BEGIN GENERATED protocol:");
            /* a name may hold '-': it ends at a space, a newline or the closing of a comment */
            for (n = 0; b[n] && b[n] != ' ' && b[n] != '\n' && n < sizeof(name) - 1; n++)
                name[n] = b[n];
            name[n] = '\0';
            for (n = 0; n < sizeof(REGIONS) / sizeof(*REGIONS); n++)
                if (!strcmp(name, REGIONS[n].name))
                    break;
            if (n == sizeof(REGIONS) / sizeof(*REGIONS))
            {
                fprintf(stderr, "%s: no generated region '%s'\n", path, name);
                return 1;
            }
            fputs(line, stdout);
            REGIONS[n].emit();
            skipping = 1;
            continue;
        }
        fputs(line, stdout);
    }
    fclose(file);
    if (skipping)
    {
        fprintf(stderr, "%s: a generated region is not closed\n", path);
        return 1;
    }
    return 0;
}

/* ---------------------------------------------------------------- probe output schema */

/* the code or name of each entry of a PHD_PROBE_* list: the second argument of X(id, code, meaning) */
static const char *const PROBE_OUTCOMES[] = {
#define X(id, code, meaning) code,
    PHD_PROBE_OUTCOMES(X)
#undef X
};
static const char *const PROBE_LIMIT_NAMES[] = {
#define X(id, code, meaning) code,
    PHD_PROBE_LIMIT_NAMES(X)
#undef X
};
static const char *const PROBE_LIMIT_MECHANISMS[] = {
#define X(id, code, meaning) code,
    PHD_PROBE_LIMIT_MECHANISMS(X)
#undef X
};
static const char *const PROBE_LIMIT_CODES[] = {
#define X(id, code, meaning) code,
    PHD_PROBE_LIMIT_CODES(X)
#undef X
};
static const char *const PROBE_PROFILE_CODES[] = {
#define X(id, code, meaning) code,
    PHD_PROBE_PROFILE_CODES(X)
#undef X
};
static const char *const PROBE_REASONS[] = {
#define X(id, code, meaning) code,
    PHD_PROBE_REASONS(X)
#undef X
};
static const char *const PROBE_STEPS[] = {
#define X(id, code, meaning) code,
    PHD_PROBE_STEPS(X)
#undef X
};

/* words plugin-hostd does not declare: the schema reads these straight out of omx-contract's own vocabulary header,
 * so a word moved or renamed there moves here with no edit of this file (plugin-hostd#115) */
static const char *const CONTRACT_LATENCY_METHODS[] = OMX_MEASUREMENT_LATENCY_METHODS_INIT;
static const char *const CONTRACT_VOICE_BASES[] = OMX_MEASUREMENT_VOICE_BASES_INIT;
static const char *const CONTRACT_CORE_BANDS[] = OMX_MACHINE_CORE_BANDS_INIT;
static const char *const CONTRACT_CLOCK_BANDS[] = OMX_MACHINE_CLOCK_BANDS_INIT;
static const char *const CONTRACT_THREAD_SCHEDULING[] = OMX_RESOURCE_THREAD_SCHEDULING_INIT;

#define PROBE_LIST(token, list) { "@" token "@", list, sizeof(list) / sizeof(*list) }

/* TEMPLATE on stdout with each @PHD_PROBE_...@ or @OMX_...@ token replaced by the quoted codes of that list, the
 * former plugin-hostd's own header, the latter omx-contract's vocabulary header, so the schema's enumerations are
 * never retyped; a token the template holds and the generator does not know is an error */
static int probe_schema(const char *path)
{
    static const struct
    {
        const char *token;
        const char *const *codes;
        size_t count;
    } LISTS[] = {
        PROBE_LIST("PHD_PROBE_OUTCOMES", PROBE_OUTCOMES),
        PROBE_LIST("PHD_PROBE_LIMIT_NAMES", PROBE_LIMIT_NAMES),
        PROBE_LIST("PHD_PROBE_LIMIT_MECHANISMS", PROBE_LIMIT_MECHANISMS),
        PROBE_LIST("PHD_PROBE_LIMIT_CODES", PROBE_LIMIT_CODES),
        PROBE_LIST("PHD_PROBE_PROFILE_CODES", PROBE_PROFILE_CODES),
        PROBE_LIST("PHD_PROBE_STEPS", PROBE_STEPS),
        PROBE_LIST("PHD_PROBE_REASONS", PROBE_REASONS),
        PROBE_LIST("OMX_MEASUREMENT_LATENCY_METHODS", CONTRACT_LATENCY_METHODS),
        PROBE_LIST("OMX_MEASUREMENT_VOICE_BASES", CONTRACT_VOICE_BASES),
        PROBE_LIST("OMX_MACHINE_CORE_BANDS", CONTRACT_CORE_BANDS),
        PROBE_LIST("OMX_MACHINE_CLOCK_BANDS", CONTRACT_CLOCK_BANDS),
        PROBE_LIST("OMX_RESOURCE_THREAD_SCHEDULING", CONTRACT_THREAD_SCHEDULING),
    };
    FILE *f = fopen(path, "r");
    char line[512];

    if (f == NULL)
    {
        perror(path);
        return 1;
    }
    while (fgets(line, sizeof(line), f))
    {
        char *at = strchr(line, '@');
        size_t n;

        if (at == NULL)
        {
            fputs(line, stdout);
            continue;
        }
        for (n = 0; n < sizeof(LISTS) / sizeof(*LISTS); n++)
        {
            size_t k, len = strlen(LISTS[n].token);

            if (strncmp(at, LISTS[n].token, len))
                continue;
            fwrite(line, 1, (size_t)(at - line), stdout);
            for (k = 0; k < LISTS[n].count; k++)
            {
                printf("%s", k ? ", " : "");
                jstr(LISTS[n].codes[k]);
            }
            fputs(at + len, stdout);
            break;
        }
        if (n == sizeof(LISTS) / sizeof(*LISTS))
        {
            fprintf(stderr, "%s: no list of the header is called %s", path, at);
            fclose(f);
            return 1;
        }
    }
    fclose(f);
    return 0;
}

int main(int argc, char **argv)
{
    if (!scales_are_the_contracts())
        return 1;
    if (argc == 2 && !strcmp(argv[1], "json"))
    {
        json();
        return 0;
    }
    if (argc == 3 && !strcmp(argv[1], "splice"))
        return splice(argv[2]);
    if (argc == 3 && !strcmp(argv[1], "probe-schema"))
        return probe_schema(argv[2]);
    if (argc == 2 && !strcmp(argv[1], "regions"))
    {
        size_t n;

        for (n = 0; n < sizeof(REGIONS) / sizeof(*REGIONS); n++)
            puts(REGIONS[n].name);
        return 0;
    }
    fprintf(stderr, "usage: protocol-gen json | regions | splice FILE | probe-schema TEMPLATE\n");
    return 2;
}
