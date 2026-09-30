/* A consumer of the declared protocol, the way a controller uses it: the installed header alone, plain C, no daemon
 * header, no library. It compiles against whatever `pkg-config --cflags plugin-hostd` says and is run by make test. */
#include <stdio.h>
#include <string.h>

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
    int errors = 0, verbs = 0, events = 0, ints = 0, strings = 0;
    char reply[32];

#define X(id, meaning) errors++; check(PHD_ERR_##id < 0, #id " is a refusal");
    PHD_ERRORS(X)
#undef X
#define X(id, name, args, rep, meaning) verbs++; check(*name && *rep, #id " is named and answers");
    PHD_VERBS(X)
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
    snprintf(reply, sizeof(reply), "resp %d", PHD_ERR_GAVE_UP);
    check(!strncmp(reply, "resp -5", 7), "a reply is resp <code>");
    if (failures)
        return 1;
    printf("ok   a C consumer of the installed header: %d errors, %d verbs, %d events, %d settings\n", errors, verbs, events,
           ints + strings);
    return 0;
}
