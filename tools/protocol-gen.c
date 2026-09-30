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
 *   protocol-gen splice FILE   FILE on stdout with every generated region replaced; a region is the lines between
 *                              "BEGIN GENERATED protocol:<name>" and "END GENERATED protocol:<name>" */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <plugin-hostd/protocol.h>

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
    printf("\n  ],\n  \"events\": [");
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
    { "verbs", region_verbs }, { "errors", region_errors }, { "events", region_events },
    { "pin-limits", region_pin_limits }, { "man-pin-limits", region_man_pin_limits },
    { "readiness", region_readiness }, { "worker-ready", region_worker_ready },
    { "man-keys", region_man_keys }, { "man-ready", region_man_ready }, { "man-port", region_man_port },
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

int main(int argc, char **argv)
{
    if (argc == 2 && !strcmp(argv[1], "json"))
    {
        json();
        return 0;
    }
    if (argc == 3 && !strcmp(argv[1], "splice"))
        return splice(argv[2]);
    if (argc == 2 && !strcmp(argv[1], "regions"))
    {
        size_t n;

        for (n = 0; n < sizeof(REGIONS) / sizeof(*REGIONS); n++)
            puts(REGIONS[n].name);
        return 0;
    }
    fprintf(stderr, "usage: protocol-gen json | regions | splice FILE\n");
    return 2;
}
