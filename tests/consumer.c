/* A consumer of the declared protocol, the way a controller uses it: the installed header alone, plain C, no daemon
 * header, no library. It compiles against whatever `pkg-config --cflags plugin-hostd` says and is run by make test. */
#include <stdio.h>
#include <string.h>

#include <plugin-hostd/pin.h>
#include <plugin-hostd/protocol.h>

static int failures;

static void check(int cond, const char *what)
{
    if (!cond)
    {
        printf("FAIL %s\n", what);
        failures++;
    }
}

int main(void)
{
    int errors = 0, verbs = 0, events = 0, ints = 0, strings = 0, instance_verbs = 0;
    char reply[32];

#define X(id, meaning) errors++; check(PHD_ERR_##id < 0, #id " is a refusal");
    PHD_ERRORS(X)
#undef X
#define X(id, name, args, rep, meaning) verbs++; check(*name && *rep, #id " is named and answers");
    PHD_VERBS(X)
#undef X
#define X(id, name, args, rep, ledger, meaning) \
    instance_verbs++; check(*name && *rep && (PHD_LEDGER_##ledger == PHD_LEDGER_NONE || PHD_LEDGER_##ledger == PHD_LEDGER_REPLACE), \
                            #id " is named, answers and says what the ledger keeps");
    PHD_INSTANCE_VERBS(X)
#undef X
#define X(name, fields, meaning) events++; check(*name && *fields, name " has fields");
    PHD_EVENTS(X)
#undef X
#define X(key, def, unit, meaning) ints++;
    PHD_CONF_INTS(X)
#undef X
#define X(key, size, def, env, meaning) strings++;
    PHD_CONF_STRINGS(X)
#undef X
    check(errors && verbs && events && ints && strings, "every table has rows");
    check(PLUGIN_HOSTD_PROTOCOL_VERSION >= 1, "the protocol has a version");
    check(strstr(PHD_READY_LINE, PHD_WORKER_READY_MARKER) != NULL, "the readiness line ends as a worker's does");

    check(phd_pool_name_valid("strip_1-a"), "a pool name");
    check(!phd_pool_name_valid(""), "an empty pool name is refused");
    check(!phd_pool_name_valid("bad!name"), "a pool name with a stray character is refused");
    {
        char longest[PHD_POOL_NAME_MAX + 2];

        memset(longest, 'a', sizeof(longest));
        longest[PHD_POOL_NAME_MAX] = '\0';
        check(phd_pool_name_valid(longest), "a pool name of the longest length");
        longest[PHD_POOL_NAME_MAX] = 'a';
        longest[PHD_POOL_NAME_MAX + 1] = '\0';
        check(!phd_pool_name_valid(longest), "a pool name one longer is refused");
    }
    {
        char hex[PHD_SHA256_HEX_LEN + 1];

        phd_sha256_hex("abc", 3, hex);
        check(!strcmp(hex, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"), "the pin header hashes");
    }
    {
        char *ok[] = { "track_info", "0", "Kick \"In\" \xc3\xb1", "#FF8000", "bus" };
        char *bad_kind[] = { "track_info", "0", "a", "-", "aux" };
        char *bad_color[] = { "track_info", "0", "a", "FF8000" };
        char *bad_utf8[] = { "track_info", "0", "\xc3", "-" };
        char longest[PHD_STRING_MAX + 2];

        check(phd_track_info_valid(ok, 5), "a track_info line");
        check(!phd_track_info_valid(bad_kind, 5) && !phd_track_info_valid(bad_color, 4) &&
              !phd_track_info_valid(bad_utf8, 4), "a kind, a colour or a name outside the grammar is refused");
        memset(longest, 'a', sizeof(longest));
        longest[PHD_STRING_MAX] = '\0';
        check(phd_string_valid(longest), "a name of the longest length");
        longest[PHD_STRING_MAX] = 'a';
        longest[PHD_STRING_MAX + 1] = '\0';
        check(!phd_string_valid(longest), "a name one byte longer is refused");
    }
    snprintf(reply, sizeof(reply), "resp %d", PHD_ERR_GAVE_UP);
    check(!strncmp(reply, "resp -5", 7), "a reply is resp <code>");
    if (failures)
        return 1;
    printf("ok   a C consumer of the installed header: %d errors, %d verbs, %d instance verbs, %d events, %d settings\n",
           errors, verbs, instance_verbs, events, ints + strings);
    return 0;
}
