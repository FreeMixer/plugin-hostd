/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * The daemon's own check of a preset file (src/presets.c), one line per file: "<code> <plugin id|-> <path>", the code
 * 0 for a file that holds and PHD_ERR_PRESET_INVALID for one that does not. tests/preset_conformance.py holds it to the
 * schema's verdict.
 *
 *   preset-check <file>...
 */

#include <stdio.h>
#include <stdlib.h>

#include "../src/presets.h"

int main(int argc, char **argv)
{
    int n;

    for (n = 1; n < argc; n++)
    {
        char *id = NULL;
        int rc = preset_file_check(argv[n], &id, NULL);

        printf("%d %s %s\n", rc, id ? id : "-", argv[n]);
        free(id);
    }
    return 0;
}
