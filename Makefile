# compiler
CC ?= gcc

# program names
PROG = plugin-hostd
VERSION = $(shell sed -n "s/^Version: *//p" packaging/plugin-hostd.spec)
FAKE = tests/fake-host
FORMAT_TEST = tests/format-test
PIN_TEST = tests/pin-test
RELAY_TEST = tests/relay-test
GESTURE_ALLOC_TEST = tests/gesture-alloc-test
LV2_ALLOC_TEST = tests/lv2-alloc-test
TRANSFORMS_TEST = tests/transforms-test
PROBE = plugin-hostd-probe

PKG_CONFIG ?= pkg-config

# a mod-host checkout: the library when pkg-config has none, and always the scenario corpus of the jack test
MOD_HOST_DIR ?= ../mod-host

# mod-host protocol library: pkg-config when it is installed, a mod-host checkout otherwise
ifeq ($(shell $(PKG_CONFIG) --exists mod-host-protocol && echo true), true)
PROTOCOL_CFLAGS = $(shell $(PKG_CONFIG) --cflags mod-host-protocol)
PROTOCOL_LIBS = $(shell $(PKG_CONFIG) --libs mod-host-protocol)
else
PROTOCOL_LIB = $(MOD_HOST_DIR)/libmod-host-protocol.so
PROTOCOL_CFLAGS = -I$(MOD_HOST_DIR)/src
# the checkout's library is not installed: the binary finds it there through its rpath
PROTOCOL_LIBS = -L$(MOD_HOST_DIR) -lmod-host-protocol -Wl,-rpath,$(abspath $(MOD_HOST_DIR))
endif

# the directory holding mod-host's protocol headers, which protocol/mod-host.json is written from: the -I of the
# protocol's flags (mod-host-protocol.pc names <includedir>/mod-host), or MOD_HOST_INCLUDE=<dir> on the command line
MOD_HOST_INCLUDE ?= $(patsubst -I%,%,$(firstword $(filter -I%,$(PROTOCOL_CFLAGS))))

# omx-contract's C header (omx-contract-devel, libomx-contract-dev): the probe runner's default rates and the protocol's
# parameter scales are read from it; CONTRACT_CFLAGS=-I<dir> for a header that is not installed
CONTRACT_CFLAGS ?= $(shell $(PKG_CONFIG) --cflags omx-contract 2>/dev/null)

# CLAP headers for the test plugin: pkg-config when clap-devel is installed, CLAP_CFLAGS=-I<dir> otherwise
CLAP_CFLAGS ?= $(shell $(PKG_CONFIG) --cflags clap 2>/dev/null)

# default compiler and linker flags
CFLAGS += -O2 -Wall -Wextra -std=gnu99 -fPIC -D_GNU_SOURCE -pthread -Wno-format-truncation
CFLAGS += -Werror=implicit-function-declaration -Werror=return-type

ifeq ($(DEBUG), 1)
   CFLAGS += -O0 -g -DDEBUG
else
   CFLAGS += -fvisibility=hidden
   LDFLAGS += -s
endif

INCS = -Iinclude $(PROTOCOL_CFLAGS)

LDFLAGS += -Wl,--no-undefined

# source and object files
SRC = src/main.c src/conf.c src/proc.c src/supervisor.c src/verbs.c src/pins.c src/relay.c src/formats.c src/lv2.c \
      src/descriptors.c src/describe.c src/transforms.c src/json.c
OBJ = $(SRC:.c=.o)

# the C names of the daemon's verbs and reply codes, rendered from data/verbs.json (render-verbs below); protocol.h
# includes them
RENDERED = include/plugin-hostd/plugin_hostd_host_verbs.h include/plugin-hostd/plugin_hostd_vocabulary.h

# default build
all: $(PROG) $(PROBE)

$(PROG): $(OBJ) $(PROTOCOL_LIB)
	$(CC) $(OBJ) $(PROTOCOL_LIBS) $(LDFLAGS) -pthread -lm -o $@

# the probe runner: it loads no plugin and links nothing of the daemon or of mod-host
# describe reads the installed table of a format by default (docs/formats.md)
PROBE_SRC = src/probe.c src/json.c src/describe.c src/transforms.c
$(PROBE): $(PROBE_SRC) src/json.h src/describe.h src/transforms.h include/plugin-hostd/protocol.h $(RENDERED) include/plugin-hostd/pin.h
	$(CC) -Iinclude -Isrc $(CONTRACT_CFLAGS) $(CFLAGS) -D_GNU_SOURCE -DPROBE_VERSION='"$(VERSION)"' \
	  -DPROBE_CONTRACTDIR='"$(CONTRACTDIR)"' -DPROBE_CONTRACT_MAJOR='"$(CONTRACT_SCHEMA_MAJOR)"' -o $@ $(PROBE_SRC) -lm

ifneq ($(PROTOCOL_LIB),)
$(PROTOCOL_LIB):
	$(MAKE) -C $(MOD_HOST_DIR) libmod-host-protocol.so
endif

# the declared protocol is compiled into every object
$(OBJ): include/plugin-hostd/protocol.h $(RENDERED) include/plugin-hostd/pin.h

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

install: $(PROG) install_man install_protocol install_tests
	install -d $(DESTDIR)$(BINDIR)
	install -m 755 $(PROG) $(DESTDIR)$(BINDIR)
	install -m 755 $(PROBE) $(DESTDIR)$(BINDIR)

# the declared protocol: the JSON for readers that are not C, which the package carries; the header, its pkg-config
# file and the schema of the JSON, which the development package carries; and the pins_dir other packages drop their
# pins in
install_protocol:
	install -d $(DESTDIR)$(DATADIR)/plugin-hostd
	install -m 644 protocol/plugin-hostd.json $(DESTDIR)$(DATADIR)/plugin-hostd/protocol.json
	install -m 644 protocol/mod-host.json $(DESTDIR)$(DATADIR)/plugin-hostd/mod-host.json
	install -m 644 protocol/plugin-hostd.schema.json $(DESTDIR)$(DATADIR)/plugin-hostd/protocol.schema.json
	install -m 644 protocol/probe-output.schema.json $(DESTDIR)$(DATADIR)/plugin-hostd/probe-output.schema.json
	install -m 644 protocol/preset.schema.json $(DESTDIR)$(DATADIR)/plugin-hostd/preset.schema.json
	install -d $(DESTDIR)$(DATADIR)/plugin-hostd/pins.d
	install -d $(DESTDIR)$(INCLUDEDIR)/plugin-hostd
	install -m 644 include/plugin-hostd/protocol.h $(DESTDIR)$(INCLUDEDIR)/plugin-hostd/protocol.h
	install -m 644 $(RENDERED) $(DESTDIR)$(INCLUDEDIR)/plugin-hostd/
	install -m 644 include/plugin-hostd/pin.h $(DESTDIR)$(INCLUDEDIR)/plugin-hostd/pin.h
	install -d $(DESTDIR)$(DATADIR)/pkgconfig
	sed -e 's,@PREFIX@,$(PREFIX),g' -e 's,@VERSION@,$(VERSION),g' protocol/plugin-hostd.pc.in > $(DESTDIR)$(DATADIR)/pkgconfig/plugin-hostd.pc
	chmod 644 $(DESTDIR)$(DATADIR)/pkgconfig/plugin-hostd.pc

# the format tables (data/formats/, docs/formats.md) and the verbs (data/verbs.json) this tree owns, installed as the
# package plugin-hostd into omx-contract's contract directory, <contractdir>/<schema major>/plugin-hostd/, with a
# MANIFEST.json naming this version and the tree they came from; plugin-hostd-contract ships them. contractdir and the
# install script are omx-contract-devel's; a checkout of omx-contract (OMX_CONTRACT_DIR) stands in for the script when
# it is not installed.
CONTRACT_SCHEMA_MAJOR = 3
CONTRACTDIR = $(or $(shell $(PKG_CONFIG) --variable=contractdir omx-contract 2>/dev/null),$(DATADIR)/omx-contract/contract.d)
INSTALL_CONTRACT_DIR = $(firstword $(wildcard $(shell $(PKG_CONFIG) --variable=datadir omx-contract 2>/dev/null)/install-contract-dir.sh) $(wildcard $(OMX_CONTRACT_DIR)/tools/install-contract-dir.sh))
.PHONY: install-contract
install-contract:
	@test -n "$(INSTALL_CONTRACT_DIR)" || { echo "install-contract: no install-contract-dir.sh: install omx-contract-devel, or set OMX_CONTRACT_DIR to a checkout" >&2; exit 1; }
	sh $(INSTALL_CONTRACT_DIR) $(PROG) $(VERSION) $(CONTRACT_SCHEMA_MAJOR) data $(DESTDIR)$(CONTRACTDIR) data

# the daemon's verbs and reply codes (data/verbs.json), rendered by omx-contract as the package installs them, beside
# the packages of OMX_CONTRACT_PATH and of the installed contract directory: the C names every source and protocol.h
# read (OMX_VERB_<VERB>, its _FMT, _REPLY and _CODES_INIT). `make render-verbs` writes them, `make check-rendered`
# fails on any drift.
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

# the fake worker, for a program that drives plugin-hostd: away from $(BINDIR), where nothing runs it by chance
install_tests: $(FAKE)
	install -d $(DESTDIR)$(LIBEXECDIR)/plugin-hostd/tests
	install -m 755 $(FAKE) $(DESTDIR)$(LIBEXECDIR)/plugin-hostd/tests/fake-host

install_man:
	install -d $(DESTDIR)$(MANDIR)
	install -m 644 doc/*.1 $(DESTDIR)$(MANDIR)

# No tracked file points into a private repository, issue, branch or path (tools/private-refs-check.sh, with its
# --self-test, which turns each kind of pointer red in each kind of file).
.PHONY: private-refs check-verb-table
private-refs:
	tools/private-refs-check.sh
	tools/private-refs-check.sh --self-test

# libFuzzer harnesses (fuzz/README.md): the command parser and dispatcher, src/verbs.c with the mod-host side replaced by
# a recorder, and the reply stream, src/relay.c with its sockets answered by the harness; clang with libFuzzer,
# AddressSanitizer and UndefinedBehaviorSanitizer, into build/fuzz/. Nothing of the ordinary build is touched.
#   make fuzz                  build every harness
#   make fuzz-run FUZZ_TIME=60 fuzz each one from its seed corpus; red on any crash
#   make fuzz-sabotage         each mutant of fuzz/sabotage/ must make its harness abort on a seed, in its own property
#   make fuzz-records          each check's mutant: record must make that check abort on its input: seed
#   make fuzz-coverage         the coverage witness: llvm-cov over the corpus, held to fuzz/coverage-floor.txt
#   make fuzz-corpus           write fuzz/corpus/ again from the declared protocol and the README examples
FUZZ_CC        ?= clang
FUZZ_TIME      ?= 60
FUZZ_BUILD     := build/fuzz
FUZZ_HARNESSES := command reply
FUZZ_SAN       := -fsanitize=address,undefined -fno-sanitize-recover=all
FUZZ_CFLAGS    := -O1 -g -std=c11 -D_GNU_SOURCE -Wall -Wextra -Werror -fno-omit-frame-pointer
FUZZ_INCS      := -Iinclude -Isrc -Ifuzz $(PROTOCOL_CFLAGS)
# what each harness is built from beside its own file: the command harness links the parser and the recorder, the
# reply harness includes src/relay.c itself
FUZZ_SRC_command := src/verbs.c fuzz/recorder.c
FUZZ_SRC_reply   :=
FUZZ_DEPS        := fuzz/fuzz.h fuzz/syntax.h fuzz/recorder.h src/relay.c src/verbs.h include/plugin-hostd/protocol.h $(RENDERED)

$(FUZZ_BUILD)/fuzz_%: fuzz/fuzz_%.c $(FUZZ_DEPS) $(FUZZ_SRC_command)
	@mkdir -p $(dir $@)
	$(FUZZ_CC) $(FUZZ_CFLAGS) $(FUZZ_SAN) -fsanitize=fuzzer $(FUZZ_INCS) $< $(FUZZ_SRC_$*) -pthread -o $@

fuzz: $(FUZZ_HARNESSES:%=$(FUZZ_BUILD)/fuzz_%)

fuzz-run: fuzz
	FUZZ_BUILD=$(FUZZ_BUILD) FUZZ_TIME=$(FUZZ_TIME) fuzz/run.sh $(FUZZ_HARNESSES)

fuzz-sabotage:
	FUZZ_BUILD=$(FUZZ_BUILD) MAKE="$(MAKE)" fuzz/sabotage.sh

# every check's comment names a one-line change and the seed on which that check aborts, or why it is not a property;
# each change is applied alone to the plain harness (fuzz/records.sh)
fuzz-records:
	FUZZ_BUILD=$(FUZZ_BUILD) FUZZ_CC=$(FUZZ_CC) PROTOCOL_CFLAGS="$(PROTOCOL_CFLAGS)" fuzz/records.sh

# the coverage witness: the same harnesses without sanitizers, instrumented for llvm-cov, each run once over its seed
# corpus (-runs=0 executes the corpus and nothing else); the llvm-cov and llvm-profdata of FUZZ_CC's own LLVM
FUZZ_COV_BUILD := $(FUZZ_BUILD)/cov
FUZZ_COV_FLAGS := -O0 -g -std=c11 -D_GNU_SOURCE -fprofile-instr-generate -fcoverage-mapping
LLVM_COV       ?= llvm-cov
LLVM_PROFDATA  ?= llvm-profdata

$(FUZZ_COV_BUILD)/fuzz_%: fuzz/fuzz_%.c $(FUZZ_DEPS) $(FUZZ_SRC_command)
	@mkdir -p $(dir $@)
	$(FUZZ_CC) $(FUZZ_COV_FLAGS) -fsanitize=fuzzer $(FUZZ_INCS) $< $(FUZZ_SRC_$*) -pthread -o $@

fuzz-coverage: $(FUZZ_HARNESSES:%=$(FUZZ_COV_BUILD)/fuzz_%)
	@set -e; for h in $(FUZZ_HARNESSES); do \
	  rm -f $(FUZZ_COV_BUILD)/$$h.profraw; \
	  LLVM_PROFILE_FILE=$(FUZZ_COV_BUILD)/$$h.profraw $(FUZZ_COV_BUILD)/fuzz_$$h -runs=0 fuzz/corpus/$$h/ \
	      >$(FUZZ_COV_BUILD)/$$h.log 2>&1 || \
	    { cat $(FUZZ_COV_BUILD)/$$h.log; echo "fuzz-coverage: fuzz_$$h failed on its own corpus"; exit 1; }; \
	  $(LLVM_PROFDATA) merge -sparse $(FUZZ_COV_BUILD)/$$h.profraw -o $(FUZZ_COV_BUILD)/$$h.profdata; \
	done
	@LLVM_COV=$(LLVM_COV) fuzz/coverage.sh $(FUZZ_COV_BUILD) $(FUZZ_HARNESSES)

# the seed corpus is written from protocol/plugin-hostd.json, protocol/mod-host.json and the send lines of README.md and
# docs/own-host.md, never from a network, and committed; fuzz-corpus-check fails when it is not what they give
fuzz-corpus:
	python3 fuzz/gen_corpus.py fuzz/corpus

fuzz-corpus-check:
	@set -e; tmp=$$(mktemp -d); trap 'rm -rf $$tmp' EXIT; \
	python3 fuzz/gen_corpus.py $$tmp; diff -r $$tmp fuzz/corpus; echo "the seed corpus is current"

.PHONY: fuzz fuzz-run fuzz-sabotage fuzz-records fuzz-coverage fuzz-corpus fuzz-corpus-check

# clean rule
clean:
	@rm -f src/*.o $(PROG) $(PROBE) tests/probe-child tests/lv2-probe-child tests/rt_interpose.so $(FAKE) $(PIN_TEST) $(RELAY_TEST) tests/relay-test-relay.o $(FORMAT_TEST) $(GESTURE_ALLOC_TEST) $(LV2_ALLOC_TEST) tests/lv2-alloc-lv2.o $(TRANSFORMS_TEST) $(GEN) tests/stress.clap tests/jack_levels tests/host_scenarios $(LV2_FIXTURE)
	@rm -rf build

# the daemon against workers that are not plugin hosts at all (tests/fake-host speaks the same protocol and can be
# made to die on cue): placement, forwarding, ledger, replay, attribution, the storm bound; no jack, no plugin
test: test-pin test-transforms test-format-coverage test-describe test-relay test-alloc test-format test-daemon test-verbs-declared check-rendered check-generated check-schema test-probe-schema test-vocabulary test-probe test-contract test-consumer test-perturbation check-readme check-own-host-page check-no-pins check-ci-guards test-mod-host-json test-socket check-verb-table check-preset-schema test-install-schemas
	MOD_HOST_DIR=$(MOD_HOST_DIR) python3 tests/verbs_contract.py

# the same without the verb table, which is read from a mod-host checkout's README
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
	$(CC) $(INCS) $(CFLAGS) -Werror -o $@ $< $(PROTOCOL_LIBS) -lm

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

# the daemon's parts without its main and its verbs: the test calls the supervisor as the verbs do
FORMAT_OBJ = src/conf.o src/proc.o src/supervisor.o src/pins.o src/relay.o src/formats.o src/lv2.o

$(FORMAT_TEST): tests/format_test.c $(FORMAT_OBJ) $(PROTOCOL_LIB)
	$(CC) $(INCS) -Isrc $(CFLAGS) -Werror -o $@ tests/format_test.c $(FORMAT_OBJ) $(PROTOCOL_LIBS) -pthread -lm

# include/plugin-hostd/pin.h against answers it did not compute
test-pin: $(PIN_TEST)
	./$(PIN_TEST)

$(PIN_TEST): tests/pin_test.c include/plugin-hostd/pin.h
	$(CC) -Iinclude $(CFLAGS) -Werror -o $@ tests/pin_test.c

# the transforms the format tables name (src/transforms.c, docs/formats.md): every one and its inverse over its vectors,
# and a lookup that is not one to one refused
test-transforms: $(TRANSFORMS_TEST)
	./$(TRANSFORMS_TEST)

$(TRANSFORMS_TEST): tests/transforms_test.c src/transforms.c src/transforms.h
	$(CC) -Isrc $(CFLAGS) -Werror -o $@ tests/transforms_test.c src/transforms.c -lm

# src/relay.c when memory runs out: built here with its realloc calls renamed, so the test picks the one that fails
test-relay: $(RELAY_TEST)
	./$(RELAY_TEST)

$(RELAY_TEST): tests/relay_test.c src/relay.c src/relay.h include/plugin-hostd/protocol.h $(RENDERED)
	$(CC) -Iinclude $(CFLAGS) -Werror -Drealloc=relay_test_realloc -c -o tests/relay-test-relay.o src/relay.c
	$(CC) -Isrc $(CFLAGS) -Werror -o $@ tests/relay_test.c tests/relay-test-relay.o -pthread
# the relay's gesture table and lv2.c's refusal and pick tables when memory runs out: each is built with its realloc
# calls renamed, so the test picks the one that fails
test-alloc: $(GESTURE_ALLOC_TEST) $(LV2_ALLOC_TEST)
	./$(GESTURE_ALLOC_TEST)
	./$(LV2_ALLOC_TEST)

$(GESTURE_ALLOC_TEST): tests/gesture_alloc_test.c src/relay.c src/relay.h include/plugin-hostd/protocol.h $(RENDERED)
	$(CC) -Iinclude -Isrc $(CFLAGS) -Werror -Drealloc=alloc_test_realloc -o $@ tests/gesture_alloc_test.c -pthread

$(LV2_ALLOC_TEST): tests/lv2_alloc_test.c src/lv2.c src/formats.h
	$(CC) $(INCS) -Isrc $(CFLAGS) -Werror -Drealloc=alloc_test_realloc -c -o tests/lv2-alloc-lv2.o src/lv2.c
	$(CC) $(INCS) -Isrc $(CFLAGS) -Werror -o $@ tests/lv2_alloc_test.c tests/lv2-alloc-lv2.o

tests/stress.clap: tests/stress_plugin.c
	$(CC) $(CLAP_CFLAGS) $(CFLAGS) -Werror -shared -o $@ $<

# every guard broken on purpose, one at a time: its test must go red
sabotage: $(PROG) $(FAKE) tests/probe-child tests/stress.clap tests/lv2-probe-child tests/rt_interpose.so $(LV2_FIXTURE)
	MOD_HOST_DIR=$(MOD_HOST_DIR) FAKE_HOST=./$(FAKE) python3 tests/sabotage.py

# the jack server the real-worker tests run over: pipewire's own jack implementation (default) or JACK2's jackd
JACK_SERVER ?= pipewire

# the real workers over jack in a PipeWire of its own: omx-clap-host (OMX_CLAP_HOST) and, when MOD_HOST is
# given, mod-host with an LV2 bundle (LV2_DIR, LV2_URI, LV2_BUNDLE, LV2_PARAM name the plugin); with omx-clap-host's
# meter fixtures (FAKE_COMPRESSOR_CLAP, JACK_METER_SOURCE) the meters reach the controller through the daemon
test-jack: $(PROG) tests/stress.clap tests/jack_levels tests/host_scenarios
	JACK_SERVER=$(JACK_SERVER) PLUGIN_HOSTD=./$(PROG) STRESS_CLAP=$(abspath tests/stress.clap) JACK_LEVELS=$(abspath tests/jack_levels) \
	HOST_SCENARIOS=$(abspath tests/host_scenarios) SCENARIOS=$(abspath $(MOD_HOST_DIR)/tests/host-scenarios.txt) ./tests/jack_e2e.sh

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

# mod-host's scenario corpus, the runner every host is tested with
tests/host_scenarios: $(MOD_HOST_DIR)/tests/host_scenarios.c $(PROTOCOL_LIB)
	$(CC) $(INCS) $(CFLAGS) -Werror -o $@ $< $(PROTOCOL_LIBS) -lpthread

tests/jack_levels: tests/jack_levels.c
	$(CC) $(shell $(PKG_CONFIG) --cflags jack) $(CFLAGS) -Werror -o $@ $< $(shell $(PKG_CONFIG) --libs jack) -lm

# what include/plugin-hostd/protocol.h declares, written out: README.md and the man page between their markers, and
# protocol/plugin-hostd.json, the same for readers that are not C; and protocol/mod-host.json, the protocol of the
# worker this daemon serves LV2 with, read from the mod-host headers it compiles against
GEN = tools/protocol-gen
GENERATED = README.md doc/plugin-hostd.1 protocol/plugin-hostd.json protocol/mod-host.json protocol/probe-output.schema.json

$(GEN): tools/protocol-gen.c include/plugin-hostd/protocol.h $(RENDERED)
	$(CC) -Wall -Wextra -Werror -std=gnu99 -Iinclude $(CONTRACT_CFLAGS) -o $@ tools/protocol-gen.c

gen: $(GEN)
	$(GEN) json > protocol/plugin-hostd.json.new && mv protocol/plugin-hostd.json.new protocol/plugin-hostd.json
	$(GEN) probe-schema protocol/probe-output.schema.in > protocol/probe-output.schema.json.new && mv protocol/probe-output.schema.json.new protocol/probe-output.schema.json
	python3 tools/mod-host-json.py $(MOD_HOST_INCLUDE) > protocol/mod-host.json.new && mv protocol/mod-host.json.new protocol/mod-host.json
	for f in README.md doc/plugin-hostd.1; do $(GEN) splice $$f > $$f.new && mv $$f.new $$f || exit 1; done

# fails on any drift: every generated output must be byte-identical to a fresh generation, every region the generator
# knows must be in a file
check-generated: $(GEN)
	@set -e; tmp=$$(mktemp -d); trap 'rm -rf $$tmp' EXIT; \
	$(GEN) json > $$tmp/json; cmp $$tmp/json protocol/plugin-hostd.json; \
	$(GEN) probe-schema protocol/probe-output.schema.in > $$tmp/probe; cmp $$tmp/probe protocol/probe-output.schema.json; \
	python3 tools/mod-host-json.py $(MOD_HOST_INCLUDE) > $$tmp/mod-host.json; cmp $$tmp/mod-host.json protocol/mod-host.json; \
	for f in README.md doc/plugin-hostd.1; do $(GEN) splice $$f > $$tmp/out; cmp $$tmp/out $$f; done; \
	$(GEN) regions > $$tmp/regions; test -s $$tmp/regions; \
	while read r; do grep -q "BEGIN GENERATED protocol:$$r\( .*\)\?$$" README.md doc/plugin-hostd.1 || { echo "region $$r is in no file"; exit 1; }; done < $$tmp/regions; \
	echo "generated files are current"

# the README sells the packages: no build command on it, and BUILDING.md carries the build
check-readme:
	python3 tests/readme_build.py

# the own-host page: its commands are few, and the reader that CI runs them with stops on any wrong reply
check-own-host-page:
	python3 tests/own_host_page.py selftest

# no pin: a dependency is declared in the spec and debian/control with a floor (no ceiling), nowhere else
check-no-pins:
	python3 tests/no_pins.py

# a workflow step the runner may be unable to run fails where it cannot run it (#107)
# the org.openmixer.preset file (docs/presets.md) holds to protocol/preset.schema.json, and a broken one does not
check-preset-schema:
	python3 tests/preset_format.py

# make install into a scratch DESTDIR carries all three schemas the development package ships (#145)
test-install-schemas: all
	@set -e; tmp=$$(mktemp -d); trap 'rm -rf $$tmp' EXIT; \
	$(MAKE) --no-print-directory install DESTDIR=$$tmp PREFIX=/usr >/dev/null; \
	for f in protocol.schema.json probe-output.schema.json preset.schema.json; do \
	  test -s $$tmp/usr/share/plugin-hostd/$$f || { echo "not installed: usr/share/plugin-hostd/$$f"; exit 1; }; \
	done; \
	echo "install carries the three schemas"

check-ci-guards:
	python3 tests/ci_guards.py

# mod-host.json follows its headers: a moved verb, code or message in a scratch copy moves the JSON, and a header it
# cannot read is refused
test-mod-host-json:
	python3 tests/mod_host_json.py $(MOD_HOST_INCLUDE)

# the host verb table has a row for every verb a controller sends the daemon, no more and no fewer, and requires of every
# profile the verbs the daemon answers itself
check-verb-table:
	python3 tests/verb_table.py

# the JSON against its schema, for which the jsonschema module is needed
check-schema:
	python3 tests/protocol_schema.py protocol/plugin-hostd.json protocol/plugin-hostd.schema.json

# the probe output's words shared with omx-contract are the contract's: each enum the template takes from it matches the
# installed omx-vocabulary.schema.json, and the template types none of the contract's lists by hand
test-vocabulary:
	python3 tests/vocabulary_derived.py

# the probe runner over the stress plugin: crash, hang and a process left behind each give the named outcome in a document
# that validates
test-probe: $(PROBE) tests/probe-child tests/stress.clap tests/lv2-probe-child tests/rt_interpose.so $(LV2_FIXTURE)
	python3 tests/probe_test.py

# lv2_measure's arguments and lines, with no lilv and no interposer: the LV2 tests of the runner load the fixture with it
tests/lv2-probe-child: tests/lv2_probe_child.c include/plugin-hostd/pin.h
	$(CC) -Iinclude $(shell $(PKG_CONFIG) --cflags lv2) $(CFLAGS) -Wall -Wextra -Werror -o $@ $< -ldl

tests/rt_interpose.so: tests/rt_interpose_stub.c
	$(CC) $(CFLAGS) -Werror -shared -o $@ $<

tests/probe-child: tests/probe_child.c
	$(CC) $(CLAP_CFLAGS) $(CFLAGS) -Wall -Wextra -Werror -o $@ $< -ldl

# describe over the recorded field dumps (tests/fixtures/fields/, docs/formats.md#the-field-dump): each gives its recorded
# descriptor, which validates; each refusal names what it refuses; a stand-in child gives the same descriptor
test-describe: $(PROBE)
	PROBE=./$(PROBE) python3 tests/describe_test.py

# what is omx-contract's is read from it: the runner's default rates, the protocol's parameter scales and the probe
# schema's latency methods follow a scratch copy of its headers with other values
test-contract: $(PROBE)
	PROBE=./$(PROBE) python3 tests/contract_derived.py

# the probe output: its three fixtures validate and five broken copies of the first are refused
test-probe-schema:
	python3 tests/probe_schema.py

# the declaration is the one copy: change values in a scratch copy of it, regenerate, rebuild, and the daemon and the docs follow
test-perturbation: $(PROG) $(FAKE) $(GEN)
	MOD_HOST_DIR=$(MOD_HOST_DIR) FAKE_HOST=./$(FAKE) python3 tests/perturbation.py

# a consumer compiles against the installed header alone, through pkg-config, as plain C
test-consumer:
	@set -e; tmp=$$(mktemp -d); trap 'rm -rf $$tmp' EXIT; \
	$(MAKE) -s install_protocol PREFIX=$$tmp DESTDIR=; \
	PKG_CONFIG_PATH=$$tmp/share/pkgconfig $(PKG_CONFIG) --exists plugin-hostd; \
	$(CC) $$(PKG_CONFIG_PATH=$$tmp/share/pkgconfig $(PKG_CONFIG) --cflags plugin-hostd) -std=c99 -Wall -Wextra -Werror \
	  -o $$tmp/consumer tests/consumer.c; \
	$$tmp/consumer
