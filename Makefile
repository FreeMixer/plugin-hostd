# compiler
CC ?= gcc

# program names
PROG = plugin-hostd
VERSION = $(shell sed -n "s/^Version: *//p" packaging/plugin-hostd.spec)
FAKE = tests/fake-host
FORMAT_TEST = tests/format-test
HISTORY_TEST = tests/history-test
PROC_TEST = tests/proc-test
CONF_TEST = tests/conf-test
PLANNER_TEST = tests/planner-test
PLACEMENT_TEST = tests/placement-test
QUALCOST_TEST = tests/qualcost-test
RELAY_TEST = tests/relay-test
GESTURE_ALLOC_TEST = tests/gesture-alloc-test
LV2_ALLOC_TEST = tests/lv2-alloc-test
VERBS_ALLOC_TEST = tests/verbs-alloc-test
TRANSFORMS_TEST = tests/transforms-test
PROBE = plugin-hostd-probe
PROBE_LOCK = plugin-hostd-probe-lock.so

PKG_CONFIG ?= pkg-config

# a plugin-hostd-protocol checkout, used when pkg-config finds no installed plugin-hostd-protocol
PROTOCOL_DIR ?= ../plugin-hostd-protocol

# the protocol library, plugin-hostd-protocol: pkg-config when it is installed, a checkout of it otherwise. Beside the
# library: the scenario corpus and the source of its runner (the jack test), and the protocol page the verb table is
# read from
ifeq ($(shell $(PKG_CONFIG) --exists plugin-hostd-protocol && echo true), true)
PROTOCOL_CFLAGS = $(shell $(PKG_CONFIG) --cflags plugin-hostd-protocol)
PROTOCOL_LIBS = $(shell $(PKG_CONFIG) --libs plugin-hostd-protocol)
PROTOCOL_SCENARIOS = $(shell $(PKG_CONFIG) --variable=scenarios plugin-hostd-protocol)
PROTOCOL_RUNNER = $(shell $(PKG_CONFIG) --variable=runner plugin-hostd-protocol)
PROTOCOL_PAGE = $(shell $(PKG_CONFIG) --variable=protocoldoc plugin-hostd-protocol)
PROTOCOL_JSON = $(shell $(PKG_CONFIG) --variable=protocoljson plugin-hostd-protocol)
MODHOST_JSON = $(shell $(PKG_CONFIG) --variable=modhostjson plugin-hostd-protocol)
else
PROTOCOL_LIB = $(PROTOCOL_DIR)/libplugin-hostd-protocol.so
PROTOCOL_CFLAGS = -I$(PROTOCOL_DIR)/include
# the checkout's library is not installed: the binary finds it there through its rpath
PROTOCOL_LIBS = -L$(PROTOCOL_DIR) -lplugin-hostd-protocol -Wl,-rpath,$(abspath $(PROTOCOL_DIR))
PROTOCOL_SCENARIOS = $(PROTOCOL_DIR)/tests/host-scenarios.txt
PROTOCOL_RUNNER = $(PROTOCOL_DIR)/tests/host_scenarios.c
PROTOCOL_PAGE = $(PROTOCOL_DIR)/doc/protocol.md
PROTOCOL_JSON = $(PROTOCOL_DIR)/protocol/plugin-hostd.json
MODHOST_JSON = $(PROTOCOL_DIR)/protocol/mod-host.json
endif

# The declared protocol is plugin-hostd-protocol's (0.4.1 or later, before 0.5), never this tree's: <plugin-hostd/protocol.h> and
# the headers it includes are found through PROTOCOL_CFLAGS, after this tree's -Iinclude (which holds the
# vocabulary of data/, and in a scratch tree of tests/sabotage.py a changed copy of the protocol headers); the JSON of
# protocol.h (PROTOCOL_JSON) and mod-host's (MODHOST_JSON) are its files. make check-no-protocol-copy fails when a copy
# of any of them is back in this tree.
PROTOCOL_INCLUDE = $(firstword $(foreach d,$(patsubst -I%,%,$(filter -I%,$(PROTOCOL_CFLAGS))),$(if $(wildcard $(d)/plugin-hostd/protocol.h),$(d))))
# what is built from them depends on them, and on a scratch copy of them in include/plugin-hostd/ where one is
PROTOCOL_HEADERS = $(wildcard include/plugin-hostd/*.h $(PROTOCOL_INCLUDE)/plugin-hostd/*.h)

# omx-contract's C header (omx-contract-devel, libomx-contract-dev): the probe runner's default rates and the protocol's
# parameter scales are read from it; CONTRACT_CFLAGS=-I<dir> for a header that is not installed
CONTRACT_CFLAGS ?= $(shell $(PKG_CONFIG) --cflags omx-contract 2>/dev/null)

# CLAP headers for the test plugin: pkg-config when clap-devel is installed, CLAP_CFLAGS=-I<dir> otherwise
CLAP_CFLAGS ?= $(shell $(PKG_CONFIG) --cflags clap 2>/dev/null)

# cJSON (cjson-devel, libcjson-dev): what reads every JSON document here, the probe runner's child lines and the format tables
CJSON_CFLAGS ?= $(shell $(PKG_CONFIG) --cflags libcjson)
CJSON_LIBS ?= $(shell $(PKG_CONFIG) --libs libcjson)

# default compiler and linker flags
CFLAGS += $(CJSON_CFLAGS)
CFLAGS += -O2 -Wall -Wextra -std=gnu99 -fPIC -D_GNU_SOURCE -pthread -Wno-format-truncation
CFLAGS += -Werror=implicit-function-declaration -Werror=return-type

ifeq ($(DEBUG), 1)
   CFLAGS += -O0 -g -DDEBUG
else
   CFLAGS += -fvisibility=hidden
   LDFLAGS += -s
endif

# <plugin-db/pin.h>: the pins, the layout digests, and what its SHA-256 links (plugin-db.pc requires libcrypto)
PIN_CFLAGS := $(shell $(PKG_CONFIG) --cflags plugin-db)
PIN_LIBS := $(shell $(PKG_CONFIG) --libs plugin-db)
INCS = -Iinclude $(PROTOCOL_CFLAGS) $(PIN_CFLAGS)

LDFLAGS += -Wl,--no-undefined

# source and object files
SRC = src/main.c src/conf.c src/proc.c src/supervisor.c src/verbs.c src/pins.c src/pin_words.c src/relay.c src/formats.c src/lv2.c \
      src/descriptors.c src/describe.c src/transforms.c src/json.c src/fsutil.c src/machine.c src/history.c src/planner.c src/qualcost.c src/placement.c src/session.c src/words.c
OBJ = $(SRC:.c=.o)

# the C names of the words of this tree's tables (data/grouping.json, data/history.json), rendered by omx-contract
# (render-verbs below); the daemon's verbs and reply codes are rendered in plugin-hostd-protocol, beside protocol.h
RENDERED = include/plugin-hostd/plugin_hostd_vocabulary.h

# the error words of the extension errors: every refusal number the protocol declares a code for, written at build time
# from plugin-hostd-protocol's JSON of the protocol (beside PROTOCOL_JSON) and never committed (src/session.c)
.DEFAULT_GOAL := all
REPLY_WORDS = src/reply_words.h
$(REPLY_WORDS): $(dir $(PROTOCOL_JSON))plugin-hostd-protocol.json tools/reply-words.py
	python3 tools/reply-words.py $< > $@.tmp && mv $@.tmp $@

# default build
all: $(PROG) $(PROBE) $(PROBE_LOCK)

$(PROG): $(OBJ) $(PROTOCOL_LIB)
	$(CC) $(OBJ) $(PROTOCOL_LIBS) $(LDFLAGS) -pthread $(PIN_LIBS) $(CJSON_LIBS) -lm -o $@

# the probe runner: it loads no plugin and links nothing of the daemon or of the protocol library
# describe reads the installed table of a format by default (docs/formats.md)
PROBE_SRC = src/probe.c src/probe_cgroup.c src/json.c src/describe.c src/transforms.c src/machine.c
$(PROBE): $(PROBE_SRC) src/probe_cgroup.h src/json.h src/describe.h src/transforms.h src/machine.h src/probe_lock.h $(PROTOCOL_HEADERS) $(RENDERED)
	$(CC) -Iinclude $(PROTOCOL_CFLAGS) $(PIN_CFLAGS) -Isrc $(CONTRACT_CFLAGS) $(CFLAGS) -D_GNU_SOURCE -DPROBE_VERSION='"$(VERSION)"' \
	  -DPROBE_CONTRACTDIR='"$(CONTRACTDIR)"' -DPROBE_CONTRACT_MAJOR='"$(CONTRACT_SCHEMA_MAJOR)"' \
	  -DPROBE_LOCK_PRELOAD='"$(LIBEXECDIR)/plugin-hostd/probe-lock.so"' -o $@ $(PROBE_SRC) -lm $(PIN_LIBS) $(CJSON_LIBS)

# the probe's lock preload (src/probe_lock.c): preloaded into the measured child only, it locks the child's memory before
# its main; installed where the runner looks for it by default, $(LIBEXECDIR)/plugin-hostd/probe-lock.so
$(PROBE_LOCK): src/probe_lock.c src/probe_lock.h
	$(CC) $(CFLAGS) -shared -o $@ src/probe_lock.c $(LDFLAGS)

ifneq ($(PROTOCOL_LIB),)
$(PROTOCOL_LIB):
	$(MAKE) -C $(PROTOCOL_DIR) libplugin-hostd-protocol.so
endif

# the declared protocol is compiled into every object
$(OBJ): $(PROTOCOL_HEADERS) $(RENDERED) $(REPLY_WORDS)

# the host class of the history is the probe's machine class: the contract's band words; the JSON string literals of the
# daemon and the probe are spelled by omx-contract's one writer, <omxcontract/omx_json_write.h> (check-no-json-escape-loop)
src/machine.o src/json.o src/transforms.o: INCS += $(CONTRACT_CFLAGS)

src/descriptors.o: src/descriptors.h src/describe.h src/json.h src/formats.h src/supervisor.h

# meta-rule to generate the object files
%.o: %.c
	$(CC) $(INCS) $(CFLAGS) -c -o $@ $<

# install rule
PREFIX = /usr/local
BINDIR = $(PREFIX)/bin

MANDIR = $(PREFIX)/share/man/man1

DATADIR = $(PREFIX)/share
INCLUDEDIR = $(PREFIX)/include
LIBEXECDIR = $(PREFIX)/libexec

install: $(PROG) $(PROBE) $(PROBE_LOCK) install_man install_protocol install_tests
	install -d $(DESTDIR)$(BINDIR)
	install -m 755 $(PROG) $(DESTDIR)$(BINDIR)
	install -m 755 $(PROBE) $(DESTDIR)$(BINDIR)
	install -d $(DESTDIR)$(LIBEXECDIR)/plugin-hostd
	install -m 644 $(PROBE_LOCK) $(DESTDIR)$(LIBEXECDIR)/plugin-hostd/probe-lock.so

# what this tree declares beside the protocol (the protocol itself is plugin-hostd-protocol's): the schemas of the probe
# output and of a preset file, the pin header and the vocabulary of data/, their pkg-config file, and the pins_dir other
# packages drop their pins in
install_protocol:
	install -d $(DESTDIR)$(DATADIR)/plugin-hostd
	install -m 644 protocol/probe-output.schema.json $(DESTDIR)$(DATADIR)/plugin-hostd/probe-output.schema.json
	install -m 644 protocol/preset.schema.json $(DESTDIR)$(DATADIR)/plugin-hostd/preset.schema.json
	install -d $(DESTDIR)$(DATADIR)/plugin-hostd/pins.d
	install -d $(DESTDIR)$(INCLUDEDIR)/plugin-hostd
	install -m 644 $(RENDERED) $(DESTDIR)$(INCLUDEDIR)/plugin-hostd/
	install -d $(DESTDIR)$(DATADIR)/pkgconfig
	sed -e 's,@PREFIX@,$(PREFIX),g' -e 's,@VERSION@,$(VERSION),g' protocol/plugin-hostd.pc.in > $(DESTDIR)$(DATADIR)/pkgconfig/plugin-hostd.pc
	chmod 644 $(DESTDIR)$(DATADIR)/pkgconfig/plugin-hostd.pc

# the format tables (data/formats/, docs/formats.md) and the grouping and history words this tree owns, installed as the
# package plugin-hostd into omx-contract's contract directory, <contractdir>/<schema major>/plugin-hostd/, with a
# MANIFEST.json naming this version and the tree they came from; plugin-hostd-contract ships them. contractdir and the
# install script are omx-contract-devel's; a checkout of omx-contract (OMX_CONTRACT_DIR) stands in for the script when
# it is not installed. The schema major is omx-contract's, read from its pkg-config file (schema_major, omx-contract 3.9.0
# or later) and never typed here: a recipe that needs it fails naming the missing variable when no omx-contract-devel
# answers, while a target that does not need it (fuzz, the checks) still runs without one.
CONTRACT_SCHEMA_MAJOR_PC := $(shell $(PKG_CONFIG) --variable=schema_major omx-contract 2>/dev/null)
CONTRACT_SCHEMA_MAJOR = $(or $(CONTRACT_SCHEMA_MAJOR_PC),$(error CONTRACT_SCHEMA_MAJOR: pkg-config names no schema_major of omx-contract: install omx-contract-devel 3.9.0 or later))
CONTRACTDIR = $(or $(shell $(PKG_CONFIG) --variable=contractdir omx-contract 2>/dev/null),$(DATADIR)/omx-contract/contract.d)
INSTALL_CONTRACT_DIR = $(firstword $(wildcard $(shell $(PKG_CONFIG) --variable=datadir omx-contract 2>/dev/null)/install-contract-dir.sh) $(wildcard $(OMX_CONTRACT_DIR)/tools/install-contract-dir.sh))
.PHONY: install-contract
install-contract:
	@test -n "$(INSTALL_CONTRACT_DIR)" || { echo "install-contract: no install-contract-dir.sh: install omx-contract-devel, or set OMX_CONTRACT_DIR to a checkout" >&2; exit 1; }
	sh $(INSTALL_CONTRACT_DIR) $(PROG) $(VERSION) $(CONTRACT_SCHEMA_MAJOR) data $(DESTDIR)$(CONTRACTDIR) data

# the contract directory as a reader of it sees it: install-contract into a staging directory, then omx-contract validate
# of the staged package together with the installed contract directory (omx-contract's own tables, omx-clap-core's),
# red on any table the installed schema refuses (#165; tests/format_coverage.py walks the schema for the words, never
# for the row keys). An absent omx-contract command is red, never a skip
.PHONY: check-contract-dir
check-contract-dir:
	@command -v $(OMX_CONTRACT) >/dev/null || { echo "$@: no $(OMX_CONTRACT) command: install omx-contract 3.2.0 or later" >&2; exit 1; }
	@set -e; tmp=$$(mktemp -d); trap 'rm -rf $$tmp' EXIT; \
	$(MAKE) --no-print-directory install-contract DESTDIR=$$tmp >/dev/null; \
	OMX_CONTRACT_PATH=$$tmp$(CONTRACTDIR)$(if $(OMX_CONTRACT_PATH),:$(OMX_CONTRACT_PATH)):$(CONTRACTDIR) $(OMX_CONTRACT) validate --installed

# the words of this tree's tables (data/), rendered by omx-contract as the package installs them, beside the packages of
# OMX_CONTRACT_PATH and of the installed contract directory: the C names the planner and the history read
# (plugin_hostd_vocabulary.h). `make render-verbs` writes them, `make check-rendered` fails on any drift. The daemon's
# verbs are plugin-hostd-protocol's, rendered there.
OMX_CONTRACT ?= omx-contract
.PHONY: render-verbs check-rendered
render-verbs check-rendered:
	@test -n "$(INSTALL_CONTRACT_DIR)" || { echo "$@: no install-contract-dir.sh: install omx-contract-devel, or set OMX_CONTRACT_DIR to a checkout" >&2; exit 1; }
	@set -e; tmp=$$(mktemp -d); trap 'rm -rf $$tmp' EXIT; \
	sh $(INSTALL_CONTRACT_DIR) $(PROG) $(VERSION) $(CONTRACT_SCHEMA_MAJOR) data $$tmp data >/dev/null; \
	OMX_CONTRACT_PATH=$$tmp$(if $(OMX_CONTRACT_PATH),:$(OMX_CONTRACT_PATH)):$(CONTRACTDIR) \
	  $(OMX_CONTRACT) render --target c --package $(PROG) --installed --out include/plugin-hostd $(if $(filter check-rendered,$@),--check)

# the tables cover their format (tests/format_coverage.py, docs/formats.md#the-coverage-test): every term of
# omx-contract's installed TERM files and every row with a from, once per format, each field one row; then its sabotage
# arms, each red naming its field. CONTRACT_SCHEMA_MAJOR=<n> reads the TERM files of another major
.PHONY: test-format-coverage
test-format-coverage:
	python3 tests/format_coverage.py --contract-dir $(CONTRACTDIR) --major $(CONTRACT_SCHEMA_MAJOR) clap
	python3 tests/format_coverage.py --contract-dir $(CONTRACTDIR) --major $(CONTRACT_SCHEMA_MAJOR) lv2
	python3 tests/format_coverage.py --contract-dir $(CONTRACTDIR) --major $(CONTRACT_SCHEMA_MAJOR) --self-test

# the fake worker and the protocol clients (lib/protocol.sh, lib/plugin_hostd_client.py), for a program that drives plugin-hostd: away from $(BINDIR), where nothing runs it by chance
install_tests: $(FAKE)
	install -d $(DESTDIR)$(LIBEXECDIR)/plugin-hostd/tests
	install -m 755 $(FAKE) $(DESTDIR)$(LIBEXECDIR)/plugin-hostd/tests/fake-host
	install -d $(DESTDIR)$(LIBEXECDIR)/plugin-hostd/tests/lib
	install -m 644 tests/lib/protocol.sh tests/lib/plugin_hostd_client.py $(DESTDIR)$(LIBEXECDIR)/plugin-hostd/tests/lib

install_man:
	install -d $(DESTDIR)$(MANDIR)
	install -m 644 doc/*.1 $(DESTDIR)$(MANDIR)

# The declared protocol is plugin-hostd-protocol's: no copy of its tables, its JSON, its headers or their generators is
# back in this tree, and no header here declares what protocol.h declares (tests/no_protocol_copy.py, with its
# --self-test, which plants each kind of copy in a scratch tree and must see it red)
check-no-protocol-copy:
	python3 tests/no_protocol_copy.py
	python3 tests/no_protocol_copy.py --self-test

# The JSON string literals of the daemon and the probe are spelled by omx-contract's one writer,
# <omxcontract/omx_json_write.h>: no C file of this tree carries an escape loop of its own (tests/no_json_escape_loop.py,
# with its --self-test, which plants each shape of loop in a scratch tree and must see it red)
check-no-json-escape-loop:
	python3 tests/no_json_escape_loop.py
	python3 tests/no_json_escape_loop.py --self-test

# No tracked file points into a private repository, issue, branch or path: FreeMixer/.github's private-refs check, from a
# checkout of it (FREEMIXER_DOTGITHUB, else ../freemixer-dotgithub); CI runs it through the public-sources-check workflow.
FREEMIXER_DOTGITHUB ?= ../freemixer-dotgithub
.PHONY: private-refs check-no-protocol-copy check-no-json-escape-loop
private-refs:
	$(FREEMIXER_DOTGITHUB)/.github/actions/private-refs-check/check.sh .

# libFuzzer harnesses (fuzz/README.md): the command parser and dispatcher, src/verbs.c with the mod-host side replaced by
# a recorder, and the reply stream, src/relay.c with its sockets answered by the harness; clang with libFuzzer,
# AddressSanitizer and UndefinedBehaviorSanitizer, into build/fuzz/. Nothing of the ordinary build is touched.
#   make fuzz                  build every harness
#   make fuzz-run FUZZ_TIME=60 fuzz each one from its seed corpus; red on any crash
#   make fuzz-sabotage         each mutant of fuzz/sabotage/ must make its harness abort on a seed, in its own property
#   make fuzz-records          each check's mutant: record must make that check abort on its input: seed
#   make fuzz-coverage         the coverage witness: llvm-cov over the corpus, held to fuzz/coverage-floor.txt
#   make fuzz-corpus           write fuzz/corpus/ again from the declared protocol and the guide's examples
FUZZ_CC        ?= clang
FUZZ_TIME      ?= 60
FUZZ_BUILD     := build/fuzz
FUZZ_HARNESSES := command reply
FUZZ_SAN       := -fsanitize=address,undefined -fno-sanitize-recover=all
FUZZ_CFLAGS    := -O1 -g -std=c11 -D_GNU_SOURCE -Wall -Wextra -Werror -fno-omit-frame-pointer
FUZZ_INCS      := -Iinclude -Isrc -Ifuzz $(PROTOCOL_CFLAGS) $(PIN_CFLAGS)
# what each harness is built from beside its own file: the command harness links the parser and the recorder, the
# reply harness includes src/relay.c itself
FUZZ_SRC_command := src/verbs.c src/session.c src/words.c src/pin_words.c fuzz/recorder.c
FUZZ_SRC_reply   :=
FUZZ_DEPS        := src/pin_words.c fuzz/fuzz.h fuzz/syntax.h fuzz/recorder.h src/relay.c src/verbs.h src/session.h $(REPLY_WORDS) $(PROTOCOL_HEADERS) $(RENDERED)

$(FUZZ_BUILD)/fuzz_%: fuzz/fuzz_%.c $(FUZZ_DEPS) $(FUZZ_SRC_command)
	@mkdir -p $(dir $@)
	$(FUZZ_CC) $(FUZZ_CFLAGS) $(FUZZ_SAN) -fsanitize=fuzzer $(FUZZ_INCS) $< $(FUZZ_SRC_$*) -pthread -o $@ $(PIN_LIBS) $(PROTOCOL_LIBS)

fuzz: $(FUZZ_HARNESSES:%=$(FUZZ_BUILD)/fuzz_%)

fuzz-run: fuzz
	FUZZ_BUILD=$(FUZZ_BUILD) FUZZ_TIME=$(FUZZ_TIME) fuzz/run.sh $(FUZZ_HARNESSES)

fuzz-sabotage:
	FUZZ_BUILD=$(FUZZ_BUILD) MAKE="$(MAKE)" fuzz/sabotage.sh

# every check's comment names a one-line change and the seed on which that check aborts, or why it is not a property;
# each change is applied alone to the plain harness (fuzz/records.sh)
fuzz-records:
	FUZZ_BUILD=$(FUZZ_BUILD) FUZZ_CC=$(FUZZ_CC) PROTOCOL_CFLAGS="$(PROTOCOL_CFLAGS)" PROTOCOL_LIBS="$(PROTOCOL_LIBS)" PIN_CFLAGS="$(PIN_CFLAGS)" fuzz/records.sh

# the coverage witness: the same harnesses without sanitizers, instrumented for llvm-cov, each run once over its seed
# corpus (-runs=0 executes the corpus and nothing else); the llvm-cov and llvm-profdata of FUZZ_CC's own LLVM
FUZZ_COV_BUILD := $(FUZZ_BUILD)/cov
FUZZ_COV_FLAGS := -O0 -g -std=c11 -D_GNU_SOURCE -fprofile-instr-generate -fcoverage-mapping
LLVM_COV       ?= llvm-cov
LLVM_PROFDATA  ?= llvm-profdata

$(FUZZ_COV_BUILD)/fuzz_%: fuzz/fuzz_%.c $(FUZZ_DEPS) $(FUZZ_SRC_command)
	@mkdir -p $(dir $@)
	$(FUZZ_CC) $(FUZZ_COV_FLAGS) -fsanitize=fuzzer $(FUZZ_INCS) $< $(FUZZ_SRC_$*) -pthread -o $@ $(PIN_LIBS) $(PROTOCOL_LIBS)

fuzz-coverage: $(FUZZ_HARNESSES:%=$(FUZZ_COV_BUILD)/fuzz_%)
	@set -e; for h in $(FUZZ_HARNESSES); do \
	  rm -f $(FUZZ_COV_BUILD)/$$h.profraw; \
	  LLVM_PROFILE_FILE=$(FUZZ_COV_BUILD)/$$h.profraw $(FUZZ_COV_BUILD)/fuzz_$$h -runs=0 fuzz/corpus/$$h/ \
	      >$(FUZZ_COV_BUILD)/$$h.log 2>&1 || \
	    { cat $(FUZZ_COV_BUILD)/$$h.log; echo "fuzz-coverage: fuzz_$$h failed on its own corpus"; exit 1; }; \
	  $(LLVM_PROFDATA) merge -sparse $(FUZZ_COV_BUILD)/$$h.profraw -o $(FUZZ_COV_BUILD)/$$h.profdata; \
	done
	@LLVM_COV=$(LLVM_COV) fuzz/coverage.sh $(FUZZ_COV_BUILD) $(FUZZ_HARNESSES)

# the seed corpus is written from plugin-hostd-protocol's JSON of the protocol and of mod-host's (PROTOCOL_JSON,
# MODHOST_JSON) and the send lines of docs/guide.md and docs/own-host.md, never from a network, and committed;
# fuzz-corpus-check fails when it is not what they give
fuzz-corpus:
	PROTOCOL_JSON=$(PROTOCOL_JSON) MODHOST_JSON=$(MODHOST_JSON) python3 fuzz/gen_corpus.py fuzz/corpus

fuzz-corpus-check:
	@set -e; tmp=$$(mktemp -d); trap 'rm -rf $$tmp' EXIT; \
	PROTOCOL_JSON=$(PROTOCOL_JSON) MODHOST_JSON=$(MODHOST_JSON) python3 fuzz/gen_corpus.py $$tmp; diff -r $$tmp fuzz/corpus; echo "the seed corpus is current"

.PHONY: fuzz fuzz-run fuzz-sabotage fuzz-records fuzz-coverage fuzz-corpus fuzz-corpus-check

# clean rule
clean:
	@rm -f src/*.o $(REPLY_WORDS) $(PROG) $(PROBE) $(PROBE_LOCK) tests/probe-child tests/lv2-probe-child tests/rt_interpose.so tests/sched-refuse.so tests/plugin-hostd-plan-refused tests/plan-refused.out $(FAKE) $(HISTORY_TEST) $(PROC_TEST) $(CONF_TEST) $(PLANNER_TEST) $(QUALCOST_TEST) $(RELAY_TEST) tests/relay-test-relay.o $(FORMAT_TEST) tests/plugin-hostd-alloc-fail $(GESTURE_ALLOC_TEST) $(LV2_ALLOC_TEST) tests/lv2-alloc-lv2.o $(VERBS_ALLOC_TEST) $(TRANSFORMS_TEST) $(GEN) tests/stress.clap tests/jack_levels tests/host_scenarios $(LV2_FIXTURE) $(PLACEMENT_TEST)
	@rm -rf build tests/alloc-fail-objs tests/plan-refused-objs

# the daemon against workers that are not plugin hosts at all (tests/fake-host speaks the same protocol and can be
# made to die on cue): placement, forwarding, ledger, replay, attribution, the storm bound; no jack, no plugin
# SHA-256 is libcrypto's (plugin-db's pin.h, EVP_Digest): no tracked C source or header carries one of its own, found by the first
# of FIPS 180-4's round constants; the sabotage arm runs the same search over a planted copy, which must find it
SHA256_K0 = 0x428a2f98
.PHONY: test-no-sha256-copy
test-no-sha256-copy:
	@if git grep -nIi -e $(SHA256_K0) -- '*.c' '*.h' '*.S'; then echo "FAIL a SHA-256 of the tree's own; the digest is libcrypto's"; exit 1; fi
	@set -e; t=$$(mktemp -d); trap 'rm -rf $$t' EXIT; git init -q $$t; printf 'static const unsigned k[] = { 0x428A2F98 };\n' > $$t/sha.h; \
	git -C $$t add sha.h; if git -C $$t grep -qIi -e $(SHA256_K0) -- '*.c' '*.h' '*.S'; then :; else \
	  echo "FAIL the sabotage arm: a planted SHA-256 is not found"; exit 1; fi
	@echo "ok   SHA-256 is libcrypto's, and a planted copy is found"

test: test-no-sha256-copy test-protocol-lib test-plan-refused test-sabotage-pool test-history test-proc test-conf test-own-host-probe-teardown test-planner test-placement test-transforms test-format-coverage test-describe test-relay test-alloc test-alloc-sweep test-format test-ready-connect test-ready-connect-sabotage test-bind test-bind-sabotage test-daemon test-verbs-declared check-rendered check-generated check-no-protocol-copy check-no-json-escape-loop test-probe-schema test-vocabulary test-probe test-contract test-consumer test-perturbation check-readme check-own-host-page check-no-pins check-ci-guards test-socket check-preset-schema test-install-schemas check-contract-floor check-clap-core-floor check-plugin-db-floor check-readme-facts test-pin-files
	PROTOCOL_DIR=$(PROTOCOL_DIR) PROTOCOL_PAGE=$(PROTOCOL_PAGE) python3 tests/verbs_contract.py

# the protocol clients plugin-hostd-tests ships (tests/lib/), against a peer that frames by NUL, and their sabotage
.PHONY: test-protocol-lib
test-protocol-lib:
	python3 tests/protocol_lib.py

# the pool tests/sabotage.py runs its arms in: their order, their trees, their ports, and one run side by side against one after the other
.PHONY: test-sabotage-pool
test-sabotage-pool:
	python3 tests/sabotage_pool_test.py

# the first connect after the ready line, many starts, no retry (issue 238)
test-ready-connect: $(PROG) $(FAKE)
	PLUGIN_HOSTD=./$(PROG) FAKE_HOST=./$(FAKE) python3 tests/ready_connect_test.py

# the same test against a daemon whose ready line goes out before its sockets exist: it must fail (issue 238)
.PHONY: test-ready-connect test-ready-connect-sabotage
test-ready-connect-sabotage: $(PROG) $(FAKE)
	python3 tests/ready_connect_sabotage.py ./$(PROG) $(FAKE) "$(CC)" "$(CFLAGS) $(INCS)" "$(OBJ)" "$(PROTOCOL_LIBS) $(PIN_LIBS) $(CJSON_LIBS) $(LDFLAGS)"

# who reaches the ports: 127.0.0.1 by default, other addresses only when asked (tests/bind_test.py), and the same test
# against a daemon built with each guard taken out, which must fail
.PHONY: test-bind test-bind-sabotage
test-bind: $(PROG) $(FAKE)
	PLUGIN_HOSTD=./$(PROG) FAKE_HOST=./$(FAKE) python3 tests/bind_test.py
test-bind-sabotage: $(PROG) $(FAKE)
	python3 tests/bind_sabotage.py ./$(PROG) $(FAKE) "$(CC)" "$(CFLAGS) $(INCS)" "$(OBJ)" "$(PROTOCOL_LIBS) $(PIN_LIBS) $(CJSON_LIBS) $(LDFLAGS)"

# the same without the verb table, which is read from the protocol page (PROTOCOL_PAGE)
test-daemon: $(PROG) $(FAKE)
	PLUGIN_HOSTD=./$(PROG) FAKE_HOST=./$(FAKE) python3 tests/daemon_test.py

# the declared verbs on the daemon's socket (tests/verbs_declared.py): each answers its declared reply and codes, the
# daemon answers no undeclared word itself, and a verb both hosts owe answers in one shape from both; omx-clap-core's
# declarations come from OMX_CONTRACT_PATH or the installed contract directory
test-verbs-declared: $(PROG) $(PROBE) $(FAKE)
	PLUGIN_HOSTD=./$(PROG) PROBE=./$(PROBE) FAKE_HOST=./$(FAKE) python3 tests/verbs_declared.py

# panel_get on the wire against the installed omx-clap-scan (omx-clap-core 0.20.0 or later) and real plugins: one that
# publishes a panel (omx-plugins-clap's omx-delay) and one that publishes none (omx-clap-host-tests' fake compressor)
test-panel-wire: $(PROG) $(PROBE) $(FAKE)
	PLUGIN_HOSTD=./$(PROG) PROBE=./$(PROBE) FAKE_HOST=./$(FAKE) python3 tests/panel_wire.py

$(FAKE): tests/fake_host.c src/verbs.h $(PROTOCOL_LIB)
	$(CC) $(INCS) $(CFLAGS) -Werror -o $@ $< $(PROTOCOL_LIBS) $(PIN_LIBS) -lm

# the command socket's framing, by omx-clap-core's socket_conformance.py. Which copy runs, in this order: the one
# SOCKET_CONFORMANCE names; ../omx-clap-core/tests/socket_conformance.py when an omx-clap-core checkout sits beside
# this one (a developer working on both runs the script being changed); else the one omx-clap-host-tests installs.
# The run prints the path it used.
SOCKET_CONFORMANCE ?= $(firstword $(wildcard ../omx-clap-core/tests/socket_conformance.py) /usr/libexec/omx-clap-host/tests/socket_conformance.py)
test-socket: $(PROG)
	PLUGIN_HOSTD=./$(PROG) SOCKET_CONFORMANCE=$(SOCKET_CONFORMANCE) ./tests/socket_e2e.sh

# a format registered only by the test goes through add, param, pin and remove; a row with a capability missing is refused
test-format: $(FORMAT_TEST) $(FAKE)
	PLUGIN_HOSTD_FORMAT_TEST_DIR=$${TMPDIR:-$${XDG_RUNTIME_DIR:-.}} ./$(FORMAT_TEST) ./$(FAKE)

# the daemon's parts without its main and its verbs: format_test calls the supervisor as the verbs do
FORMAT_OBJ = $(filter-out src/main.o src/verbs.o,$(OBJ))

$(FORMAT_TEST): tests/format_test.c $(FORMAT_OBJ) $(PROTOCOL_LIB)
	$(CC) $(INCS) -Isrc $(CFLAGS) -Werror -o $@ tests/format_test.c $(FORMAT_OBJ) $(PROTOCOL_LIBS) -pthread $(PIN_LIBS) $(CJSON_LIBS) -lm


# the running history (src/history.c, the grouping-planner design note): its line grammar, its file, what its
# counts and its summary come to, against records written out by hand; and the host class it is kept under (src/machine.c)
test-history: $(HISTORY_TEST)
	./$(HISTORY_TEST)

$(HISTORY_TEST): tests/history_test.c src/history.c src/words.c src/words.h src/history.h src/fsutil.c src/fsutil.h src/machine.c src/machine.h $(PROTOCOL_HEADERS) $(RENDERED)
	$(CC) -Iinclude $(PROTOCOL_CFLAGS) $(PIN_CFLAGS) -Isrc $(CONTRACT_CFLAGS) $(CFLAGS) -Werror -o $@ tests/history_test.c src/history.c src/words.c src/fsutil.c src/machine.c $(PROTOCOL_LIBS) $(PIN_LIBS) -lm

# tests/own_host_lv2_probe.py closes its JACK client on every exit path: run against a fake libjack whose realtime thread
# keeps firing the callback, a probe that skips the close dies with SIGSEGV at interpreter teardown
.PHONY: test-own-host-probe-teardown
test-own-host-probe-teardown:
	python3 tests/own_host_lv2_probe_teardown_test.py

# src/proc.c's readers of /proc: the text the kernel writes, and this process's own files
test-proc: $(PROC_TEST)
	./$(PROC_TEST)

$(PROC_TEST): tests/proc_test.c src/proc.c src/proc.h src/conf.h $(PROTOCOL_HEADERS) $(RENDERED)
	$(CC) $(INCS) -Isrc $(CFLAGS) -Werror -o $@ tests/proc_test.c src/proc.c -pthread $(PIN_LIBS) -lm

# the search settings (src/conf.c, plugin-hostd-protocol's plugin-hostd/search_paths.h): the default lists, $LV2_PATH, lv2_extra, $CLAP_PATH
test-conf: $(CONF_TEST)
	./$(CONF_TEST)
	python3 tests/search_paths_once.py

$(CONF_TEST): tests/conf_test.c src/conf.c src/conf.h $(PROTOCOL_HEADERS) $(RENDERED)
	$(CC) $(INCS) -Isrc $(CFLAGS) -Werror -o $@ tests/conf_test.c src/conf.c $(PIN_LIBS)

# the grouping planner (src/planner.c, the grouping-planner design note), on its own: each reason it gives, the order its
# rules decide in, the text of a plan, and that the same members give the same bytes
test-planner: $(PLANNER_TEST) $(QUALCOST_TEST)
	./$(PLANNER_TEST)
	./$(QUALCOST_TEST)

$(QUALCOST_TEST): tests/qualcost_test.c src/qualcost.c src/qualcost.h src/json.c src/json.h $(PROTOCOL_HEADERS) $(RENDERED)
	$(CC) -Isrc $(PROTOCOL_CFLAGS) $(CONTRACT_CFLAGS) $(CFLAGS) -Werror -o $@ tests/qualcost_test.c src/qualcost.c src/json.c $(PIN_LIBS) $(CJSON_LIBS) -lm

$(PLANNER_TEST): tests/planner_test.c src/planner.c src/planner.h $(PROTOCOL_HEADERS) $(RENDERED)
	$(CC) -Iinclude $(PROTOCOL_CFLAGS) $(PIN_CFLAGS) -Isrc $(CFLAGS) -Werror -o $@ tests/planner_test.c src/planner.c $(PIN_LIBS)

# the core placement (src/placement.c, docs/placement.md), on its own: the cpu lists and the audio and reserved cores of
# a mask
test-placement: $(PLACEMENT_TEST)
	./$(PLACEMENT_TEST)

$(PLACEMENT_TEST): tests/placement_test.c src/placement.c src/placement.h
	$(CC) -Isrc $(CFLAGS) -Werror -o $@ tests/placement_test.c src/placement.c $(PIN_LIBS)

# the transforms the format tables name (src/transforms.c, docs/formats.md): every one and its inverse over its vectors,
# and a lookup that is not one to one refused
test-transforms: $(TRANSFORMS_TEST)
	./$(TRANSFORMS_TEST)

$(TRANSFORMS_TEST): tests/transforms_test.c src/transforms.c src/transforms.h
	$(CC) -Isrc $(CONTRACT_CFLAGS) $(CFLAGS) -Werror -o $@ tests/transforms_test.c src/transforms.c $(PIN_LIBS) -lm

# src/relay.c when memory runs out: built here with its realloc calls renamed, so the test picks the one that fails
test-relay: $(RELAY_TEST)
	./$(RELAY_TEST)

$(RELAY_TEST): tests/relay_test.c src/relay.c src/relay.h $(PROTOCOL_HEADERS) $(RENDERED)
	$(CC) -Iinclude $(PROTOCOL_CFLAGS) $(CFLAGS) -Werror -Drealloc=relay_test_realloc -c -o tests/relay-test-relay.o src/relay.c
	$(CC) -Isrc $(CFLAGS) -Werror -o $@ tests/relay_test.c tests/relay-test-relay.o -pthread $(PIN_LIBS)
# the whole daemon when memory runs out: built with every allocation of its own sources going through tests/alloc_fail.c,
# and the scenario of tests/alloc_sweep.py run with each allocation refused in turn
ALLOC_SWEEP_DAEMON = tests/plugin-hostd-alloc-fail
$(ALLOC_SWEEP_DAEMON): $(SRC) tests/alloc_fail.c tests/alloc_fail.h $(wildcard src/*.h) $(PROTOCOL_HEADERS) $(RENDERED) $(REPLY_WORDS) $(PROTOCOL_LIB)
	mkdir -p tests/alloc-fail-objs
	for f in $(SRC); do $(CC) $(CFLAGS) $(INCS) $(CONTRACT_CFLAGS) -include tests/alloc_fail.h -c -o tests/alloc-fail-objs/$$(basename $$f .c).o $$f || exit 1; done
	$(CC) $(CFLAGS) -c -o tests/alloc-fail-objs/alloc_fail.o tests/alloc_fail.c
	$(CC) tests/alloc-fail-objs/*.o $(PROTOCOL_LIBS) $(LDFLAGS) -pthread $(PIN_LIBS) $(CJSON_LIBS) -lm -o $@

# a refused plan over a longer one: the daemon's joint world cannot be built, and a pointer array ends against a guard page
PLAN_REFUSED_DAEMON = tests/plugin-hostd-plan-refused
$(PLAN_REFUSED_DAEMON): $(SRC) tests/world_refuse.c tests/guard_calloc.c tests/guard_calloc.h $(wildcard src/*.h) $(PROTOCOL_HEADERS) $(RENDERED) $(REPLY_WORDS) $(PROTOCOL_LIB)
	mkdir -p tests/plan-refused-objs
	for f in $(SRC); do $(CC) $(CFLAGS) $(INCS) $(CONTRACT_CFLAGS) -include tests/guard_calloc.h -c -o tests/plan-refused-objs/$$(basename $$f .c).o $$f || exit 1; done
	$(CC) $(CFLAGS) -c -o tests/plan-refused-objs/guard_calloc.o tests/guard_calloc.c
	$(CC) $(CFLAGS) -c -o tests/plan-refused-objs/world_refuse.o tests/world_refuse.c
	$(CC) tests/plan-refused-objs/*.o $(PROTOCOL_LIBS) $(LDFLAGS) -pthread $(PIN_LIBS) $(CJSON_LIBS) -lm -ldl -o $@

.PHONY: test-plan-refused
test-plan-refused: $(PLAN_REFUSED_DAEMON) $(FAKE)
	PLUGIN_HOSTD_WORLD_REFUSE=1 ONLY=a_refused_plan_shorter_than_the_one_before_it_keeps_every_segment \
	  PLUGIN_HOSTD=./$(PLAN_REFUSED_DAEMON) FAKE_HOST=./$(FAKE) python3 tests/daemon_test.py > tests/plan-refused.out 2>&1 || { cat tests/plan-refused.out; exit 1; }
	grep -q '^ok   a_refused_plan_shorter_than_the_one_before_it_keeps_every_segment' tests/plan-refused.out

.PHONY: test-alloc-sweep
test-alloc-sweep: $(ALLOC_SWEEP_DAEMON) $(FAKE)
	ALLOC_SWEEP_DAEMON=./$(ALLOC_SWEEP_DAEMON) FAKE_HOST=./$(FAKE) python3 tests/alloc_sweep.py
	FAKE_HOST=./$(FAKE) python3 tests/alloc_sweep_sabotage.py "$(CC)" "$(CFLAGS) $(INCS) $(CONTRACT_CFLAGS)" "$(PROTOCOL_LIBS) $(PIN_LIBS) $(CJSON_LIBS) $(LDFLAGS)" tests/alloc-fail-objs

# the relay's gesture table, lv2.c's refusal and pick tables, and the verbs' copies and answer when memory runs out:
# each is built with its allocation calls renamed, so the test picks the one that fails
test-alloc: $(GESTURE_ALLOC_TEST) $(LV2_ALLOC_TEST) $(VERBS_ALLOC_TEST)
	./$(GESTURE_ALLOC_TEST)
	./$(LV2_ALLOC_TEST)
	./$(VERBS_ALLOC_TEST)

$(GESTURE_ALLOC_TEST): tests/gesture_alloc_test.c src/relay.c src/relay.h $(PROTOCOL_HEADERS) $(RENDERED)
	$(CC) -Iinclude $(PROTOCOL_CFLAGS) $(PIN_CFLAGS) -Isrc $(CFLAGS) -Werror -Drealloc=alloc_test_realloc -o $@ tests/gesture_alloc_test.c -pthread $(PIN_LIBS)

$(LV2_ALLOC_TEST): tests/lv2_alloc_test.c src/lv2.c src/formats.h
	$(CC) $(INCS) -Isrc $(CFLAGS) -Werror -Drealloc=alloc_test_realloc -c -o tests/lv2-alloc-lv2.o src/lv2.c
	$(CC) $(INCS) -Isrc $(CFLAGS) -Werror -o $@ tests/lv2_alloc_test.c tests/lv2-alloc-lv2.o $(PIN_LIBS)

$(VERBS_ALLOC_TEST): tests/verbs_alloc_test.c src/verbs.c src/verbs.h $(FORMAT_OBJ) $(PROTOCOL_LIB)
	$(CC) $(INCS) -Isrc $(CFLAGS) -Werror -Dstrndup=alloc_test_strndup -Dstrdup=alloc_test_strdup \
	  -Dfree=alloc_test_free -o $@ tests/verbs_alloc_test.c $(FORMAT_OBJ) $(PROTOCOL_LIBS) -pthread -lm $(PIN_LIBS) $(CJSON_LIBS)

tests/stress.clap: tests/stress_plugin.c
	$(CC) $(CLAP_CFLAGS) $(CFLAGS) -Werror -shared -o $@ $<

# every guard broken on purpose, one at a time: its test must go red
sabotage: $(PROG) $(FAKE) tests/probe-child tests/stress.clap tests/lv2-probe-child tests/rt_interpose.so $(LV2_FIXTURE)
	PROTOCOL_DIR=$(PROTOCOL_DIR) FAKE_HOST=./$(FAKE) python3 tests/sabotage.py

# the jack server the real-worker tests run over: pipewire's own jack implementation (default) or JACK2's jackd
JACK_SERVER ?= pipewire

# the real workers over jack in a PipeWire of its own: omx-clap-host (OMX_CLAP_HOST) and, when MOD_HOST is
# given, mod-host with an LV2 bundle (LV2_DIR, LV2_URI, LV2_BUNDLE, LV2_PARAM name the plugin); with omx-clap-host's
# meter fixtures (FAKE_COMPRESSOR_CLAP, JACK_METER_SOURCE) the meters reach the controller through the daemon
test-jack: $(PROG) tests/stress.clap tests/jack_levels tests/host_scenarios
	JACK_SERVER=$(JACK_SERVER) PLUGIN_HOSTD=./$(PROG) STRESS_CLAP=$(abspath tests/stress.clap) JACK_LEVELS=$(abspath tests/jack_levels) \
	HOST_SCENARIOS=$(abspath tests/host_scenarios) SCENARIOS=$(abspath $(PROTOCOL_SCENARIOS)) ./tests/jack_e2e.sh

# test-jack against JACK2's jackd (the server Zynthian runs) instead of pipewire's own jack implementation
test-jack2:
	$(MAKE) test-jack JACK_SERVER=jackd

# the LV2 adapter of a real omx-clap-host behind the daemon, with the real mod-host (MOD_HOST, default the one on PATH),
# over jack in a PipeWire of its own: omx-clap-host and its fixture bundles are built in an omx-clap-core checkout
# (OMX_CLAP_HOST_SRC) against this tree's headers; without OMX_CLAP_HOST_SRC the target says it skipped
OMX_CLAP_HOST_SRC ?=
LV2_FIXTURE = tests/plugin-hostd-fixture.lv2/plugin-hostd-fixture.so

test-lv2-adapter:
	@if [ -z "$(OMX_CLAP_HOST_SRC)" ]; then \
	    echo "skip test-lv2-adapter: OMX_CLAP_HOST_SRC is not set (an omx-clap-core checkout to build omx-clap-host from)"; \
	else \
	    $(MAKE) lv2-adapter-e2e; \
	fi

lv2-adapter-e2e: $(PROG) tests/stress.clap tests/jack_levels $(LV2_FIXTURE)
	@set -e; src=$$(cd $(OMX_CLAP_HOST_SRC) && pwd); \
	$(MAKE) -C $$src PLUGIN_HOSTD_DIR=$(abspath .) omx-clap-host build/lv2/omx-host-fixture.lv2/omx-host-fixture.so; \
	JACK_E2E_PY=lv2_adapter_e2e.py JACK_SERVER=pipewire PLUGIN_HOSTD=./$(PROG) OMX_CLAP_HOST=$$src/omx-clap-host \
	ADAPTER_BUNDLES=$$src/build/lv2 LV2_FIXTURE=$(abspath tests) MOD_HOST=$${MOD_HOST:-$$(command -v mod-host)} \
	STRESS_CLAP=$(abspath tests/stress.clap) JACK_LEVELS=$(abspath tests/jack_levels) ./tests/jack_e2e.sh

$(LV2_FIXTURE): tests/lv2_fixture.c
	$(CC) $(shell $(PKG_CONFIG) --cflags lv2) $(CFLAGS) -Werror -shared -o $@ $<

# the protocol's scenario corpus, the runner every host is tested with
tests/host_scenarios: $(PROTOCOL_RUNNER) $(PROTOCOL_LIB)
	$(CC) $(INCS) $(CFLAGS) -Werror -o $@ $< $(PROTOCOL_LIBS) -lpthread $(PIN_LIBS)

tests/jack_levels: tests/jack_levels.c
	$(CC) $(shell $(PKG_CONFIG) --cflags jack) $(CFLAGS) -Werror -o $@ $< $(shell $(PKG_CONFIG) --libs jack) $(PIN_LIBS) -lm

# what <plugin-hostd/protocol.h> (plugin-hostd-protocol's) declares, written out in this tree's pages: docs/guide.md and the
# man page between their markers, and the probe output's schema. The JSON of the protocol and mod-host's are
# plugin-hostd-protocol's (PROTOCOL_JSON, MODHOST_JSON)
GEN = tools/protocol-gen
GENERATED = docs/guide.md doc/plugin-hostd.1 protocol/probe-output.schema.json

$(GEN): tools/protocol-gen.c $(PROTOCOL_HEADERS) $(RENDERED)
	$(CC) -Wall -Wextra -Werror -std=gnu99 -Iinclude $(PROTOCOL_CFLAGS) $(CONTRACT_CFLAGS) -o $@ tools/protocol-gen.c $(PIN_LIBS)

gen: $(GEN)
	$(GEN) probe-schema protocol/probe-output.schema.in > protocol/probe-output.schema.json.new && mv protocol/probe-output.schema.json.new protocol/probe-output.schema.json
	for f in docs/guide.md doc/plugin-hostd.1; do $(GEN) splice $$f > $$f.new && mv $$f.new $$f || exit 1; done

# fails on any drift: every generated output must be byte-identical to a fresh generation, every region the generator
# knows must be in a file
check-generated: $(GEN)
	@set -e; tmp=$$(mktemp -d); trap 'rm -rf $$tmp' EXIT; \
	$(GEN) probe-schema protocol/probe-output.schema.in > $$tmp/probe; cmp $$tmp/probe protocol/probe-output.schema.json; \
	for f in docs/guide.md doc/plugin-hostd.1; do $(GEN) splice $$f > $$tmp/out; cmp $$tmp/out $$f; done; \
	$(GEN) regions > $$tmp/regions; test -s $$tmp/regions; \
	while read r; do grep -q "BEGIN GENERATED protocol:$$r\( .*\)\?$$" docs/guide.md doc/plugin-hostd.1 || { echo "region $$r is in no file"; exit 1; }; done < $$tmp/regions; \
	echo "generated files are current"

# the README and the guide sell the packages: no build command on them, and BUILDING.md carries the build
check-readme:
	python3 tests/readme_build.py

# the prose beside the generated protocol tables: still the daemon's and its workers' verified behavior today
check-readme-facts:
	python3 tests/readme_facts.py

# the own-host page: its commands are few, and the reader that CI runs them with stops on any wrong reply
check-own-host-page:
	python3 tests/own_host_page.py selftest

# no pin: a dependency is declared in the spec and debian/control with a floor (no ceiling), nowhere else
check-no-pins:
	python3 tests/no_pins.py

# the package that ships contract.d/<major>/plugin-hostd requires omx-contract 3.2.0 or later at run time, in the spec and
# debian/control: the first whose schema takes every row key of the tables (#165)
check-clap-core-floor:
	python3 tests/clap_core_floor.py

check-plugin-db-floor:
	python3 tests/plugin_db_floor.py

check-contract-floor:
	python3 tests/contract_floor.py

# the plugin-hostd-protocol floor is one number, at or above the first protocol release that declares what the sources
# use (tests/protocol_floor.py)
test: check-protocol-floor
check-protocol-floor:
	python3 tests/protocol_floor.py

# a workflow step the runner may be unable to run fails where it cannot run it (#107)
# the org.openmixer.preset file (docs/presets.md) holds to protocol/preset.schema.json, and a broken one does not
check-preset-schema:
	python3 tests/preset_format.py

# make install into a scratch DESTDIR carries both schemas the development package ships (#145); the protocol's is
# plugin-hostd-protocol's
test-install-schemas: all
	@set -e; tmp=$$(mktemp -d); trap 'rm -rf $$tmp' EXIT; \
	$(MAKE) --no-print-directory install DESTDIR=$$tmp PREFIX=/usr >/dev/null; \
	for f in probe-output.schema.json preset.schema.json; do \
	  test -s $$tmp/usr/share/plugin-hostd/$$f || { echo "not installed: usr/share/plugin-hostd/$$f"; exit 1; }; \
	done; \
	echo "install carries the two schemas"

check-ci-guards:
	python3 tests/ci_guards.py

# the probe output's words shared with omx-contract are the contract's: each enum the template takes from it matches the
# installed omx-vocabulary.schema.json, and the template types none of the contract's lists by hand
test-vocabulary:
	python3 tests/vocabulary_derived.py

# the probe runner over the stress plugin: crash, hang and a process left behind each give the named outcome in a document
# that validates
test-probe: $(PROBE) $(PROBE_LOCK) tests/probe-child tests/stress.clap tests/lv2-probe-child tests/rt_interpose.so tests/sched-refuse.so $(LV2_FIXTURE)
	python3 tests/probe_test.py

# lv2_measure's arguments and lines, with no lilv and no interposer: the LV2 tests of the runner load the fixture with it
tests/lv2-probe-child: tests/lv2_probe_child.c
	$(CC) -Iinclude $(PROTOCOL_CFLAGS) $(PIN_CFLAGS) $(shell $(PKG_CONFIG) --cflags lv2) $(CFLAGS) -Wall -Wextra -Werror -o $@ $< -ldl $(PIN_LIBS)

tests/rt_interpose.so: tests/rt_interpose_stub.c
	$(CC) $(CFLAGS) -Werror -shared -o $@ $<

# a sched_setscheduler that refuses, preloaded into the runner: the record says the kernel refused, never the grant
tests/sched-refuse.so: tests/sched_refuse.c
	$(CC) $(CFLAGS) -Werror -shared -o $@ $<

tests/probe-child: tests/probe_child.c
	$(CC) $(CLAP_CFLAGS) $(CFLAGS) -Wall -Wextra -Werror -o $@ $< -ldl $(PIN_LIBS)

# describe over the recorded field dumps (tests/fixtures/fields/, docs/formats.md#the-field-dump): each gives its recorded
# descriptor, which validates; each refusal names what it refuses; a stand-in child gives the same descriptor
test-describe: $(PROBE)
	PROBE=./$(PROBE) python3 tests/describe_test.py

# what is omx-contract's is read from it: the runner's default rates, the protocol's parameter scales and the probe
# schema's latency methods follow a scratch copy of its headers with other values
test-contract: $(PROBE)
	PROBE=./$(PROBE) CJSON_CFLAGS='$(CJSON_CFLAGS)' CJSON_LIBS='$(CJSON_LIBS)' python3 tests/contract_derived.py

# the probe output: its three fixtures validate and five broken copies of the first are refused
test-probe-schema:
	python3 tests/probe_schema.py

# the declaration is the one copy: change values in a scratch copy of it, regenerate, rebuild, and the daemon and the docs follow
test-perturbation: $(PROG) $(FAKE) $(GEN)
	PROTOCOL_DIR=$(PROTOCOL_DIR) FAKE_HOST=./$(FAKE) python3 tests/perturbation.py

# a consumer compiles against the installed header alone, through pkg-config, as plain C
test-consumer:
	@set -e; tmp=$$(mktemp -d); trap 'rm -rf $$tmp' EXIT; \
	$(MAKE) -s install_protocol PREFIX=$$tmp DESTDIR=; \
	export PKG_CONFIG_PATH=$$tmp/share/pkgconfig$${PKG_CONFIG_PATH:+:$$PKG_CONFIG_PATH}; \
	$(PKG_CONFIG) --exists plugin-hostd; \
	$(CC) $$($(PKG_CONFIG) --cflags plugin-hostd) -std=c99 -Wall -Wextra -Werror \
	  -o $$tmp/consumer tests/consumer.c $$($(PKG_CONFIG) --libs plugin-hostd); \
	$$tmp/consumer

# --pin-files: the files a pin holds as an add collects them, the list plugin-qualify takes (plugin-qualify#228)
test-pin-files: $(PROG)
	sh tests/pin_files_test.sh ./$(PROG)
