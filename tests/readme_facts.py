# SPDX-License-Identifier: GPL-3.0-or-later
# The prose next to the generated protocol tables states only verified facts about what the daemon and its workers
# answer today. This checks the CLAP param_info sentence and the preset sentence: a stale version number, or the old "-511 for every
# parameter" claim, means the text has drifted from src/lv2.c and omx-clap-core's contract-based answer again.
import os, re, sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    readme = open(os.path.join(ROOT, "README.md")).read()
    failed = 0

    if re.search(r"omx-clap-host 0\.8\.0 answers it `-511` for every parameter", readme):
        print("FAIL README.md still claims omx-clap-host 0.8.0 answers param_info -511 for every parameter "
              "(it answers from org.openmixer.param-contract/1)")
        failed += 1

    if "org.openmixer.param-contract/1" not in readme:
        print("FAIL README.md does not say param_info answers from org.openmixer.param-contract/1")
        failed += 1

    if not re.search(r"`-511` for a parameter the worker holds no checked contract for", readme):
        print("FAIL README.md does not say -511 is only for a parameter with no checked contract")
        failed += 1

    if "omx-clap-host does not list them yet" in readme:
        print("FAIL README.md still claims omx-clap-host does not list presets (preset_list and preset_get list them)")
        failed += 1

    if "omx-clap-host lists them with `preset_list` and `preset_get`" not in readme:
        print("FAIL README.md does not say omx-clap-host lists presets with preset_list and preset_get")
        failed += 1

    # #152: the daemon answers LV2 param_info and remote pages from the bundle's ports
    if "param_info` answers `-511` until the daemon reads the bundle's port data" in readme:
        print("FAIL README.md still says LV2 param_info answers -511 until the daemon reads the bundle's port data (#152 reads it)")
        failed += 1

    if "`remote_pages` and\n`remote_page_get` make a page of each `pg:group`" not in readme:
        print("FAIL README.md does not say LV2 remote pages come from the bundle's pg:group")
        failed += 1

    if not failed:
        print("ok   README.md's CLAP param_info sentence matches org.openmixer.param-contract/1, the LV2 ones read from the bundle")
    return 1 if failed else 0


sys.exit(main())
