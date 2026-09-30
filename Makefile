# compiler
CC ?= gcc

# program names
PROG = plugin-hostd
VERSION = $(shell sed -n "s/^Version: *//p" packaging/plugin-hostd.spec)
FAKE = tests/fake-host
PIN_TEST = tests/pin-test

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
SRC = src/main.c src/conf.c src/proc.c src/supervisor.c src/verbs.c
OBJ = $(SRC:.c=.o)

# default build
all: $(PROG)

$(PROG): $(OBJ) $(PROTOCOL_LIB)
	$(CC) $(OBJ) $(PROTOCOL_LIBS) $(LDFLAGS) -o $@

ifneq ($(PROTOCOL_LIB),)
$(PROTOCOL_LIB):
	$(MAKE) -C $(MOD_HOST_DIR) libmod-host-protocol.so
endif

# the declared protocol is compiled into every object
$(OBJ): include/plugin-hostd/protocol.h

# meta-rule to generate the object files
%.o: %.c
	$(CC) $(INCS) $(CFLAGS) -c -o $@ $<

# install rule
PREFIX = /usr/local
BINDIR = $(PREFIX)/bin

MANDIR = $(PREFIX)/share/man/man1

DATADIR = $(PREFIX)/share
INCLUDEDIR = $(PREFIX)/include

install: $(PROG) install_man install_protocol
	install -d $(DESTDIR)$(BINDIR)
	install -m 755 $(PROG) $(DESTDIR)$(BINDIR)

# the declared protocol: the JSON for readers that are not C, which the package carries; the header, its pkg-config
# file and the schema of the JSON, which the development package carries
install_protocol:
	install -d $(DESTDIR)$(DATADIR)/plugin-hostd
	install -m 644 protocol/plugin-hostd.json $(DESTDIR)$(DATADIR)/plugin-hostd/protocol.json
	install -m 644 protocol/plugin-hostd.schema.json $(DESTDIR)$(DATADIR)/plugin-hostd/protocol.schema.json
	install -d $(DESTDIR)$(INCLUDEDIR)/plugin-hostd
	install -m 644 include/plugin-hostd/protocol.h $(DESTDIR)$(INCLUDEDIR)/plugin-hostd/protocol.h
	install -m 644 include/plugin-hostd/pin.h $(DESTDIR)$(INCLUDEDIR)/plugin-hostd/pin.h
	install -d $(DESTDIR)$(DATADIR)/pkgconfig
	sed -e 's,@PREFIX@,$(PREFIX),g' -e 's,@VERSION@,$(VERSION),g' protocol/plugin-hostd.pc.in > $(DESTDIR)$(DATADIR)/pkgconfig/plugin-hostd.pc
	chmod 644 $(DESTDIR)$(DATADIR)/pkgconfig/plugin-hostd.pc

install_man:
	install -d $(DESTDIR)$(MANDIR)
	install -m 644 doc/*.1 $(DESTDIR)$(MANDIR)

# clean rule
clean:
	@rm -f src/*.o $(PROG) $(FAKE) $(PIN_TEST) $(GEN) tests/stress.clap tests/jack_levels tests/host_scenarios

# the daemon against workers that are not plugin hosts at all (tests/fake-host speaks the same protocol and can be
# made to die on cue): placement, forwarding, ledger, replay, attribution, the storm bound; no jack, no plugin
test: test-pin test-daemon check-generated check-schema test-consumer test-perturbation
	MOD_HOST_DIR=$(MOD_HOST_DIR) python3 tests/verbs_contract.py

# the same without the verb table, which is read from a mod-host checkout's README
test-daemon: $(PROG) $(FAKE)
	PLUGIN_HOSTD=./$(PROG) FAKE_HOST=./$(FAKE) python3 tests/daemon_test.py

$(FAKE): tests/fake_host.c $(PROTOCOL_LIB)
	$(CC) $(INCS) $(CFLAGS) -Werror -o $@ $< $(PROTOCOL_LIBS) -lm

# include/plugin-hostd/pin.h against answers it did not compute
test-pin: $(PIN_TEST)
	./$(PIN_TEST)

$(PIN_TEST): tests/pin_test.c include/plugin-hostd/pin.h
	$(CC) -Iinclude $(CFLAGS) -Werror -o $@ tests/pin_test.c

tests/stress.clap: tests/stress_plugin.c
	$(CC) $(CLAP_CFLAGS) $(CFLAGS) -Werror -shared -o $@ $<

# every guard broken on purpose, one at a time: its test must go red
sabotage: $(PROG) $(FAKE)
	MOD_HOST_DIR=$(MOD_HOST_DIR) FAKE_HOST=./$(FAKE) python3 tests/sabotage.py

# the real workers over jack in a PipeWire of its own: omx-clap-host (OMX_CLAP_HOST) and, when MOD_HOST is
# given, mod-host with an LV2 bundle (LV2_DIR, LV2_URI, LV2_BUNDLE, LV2_PARAM name the plugin)
test-jack: $(PROG) tests/stress.clap tests/jack_levels tests/host_scenarios
	PLUGIN_HOSTD=./$(PROG) STRESS_CLAP=$(abspath tests/stress.clap) JACK_LEVELS=$(abspath tests/jack_levels) \
	HOST_SCENARIOS=$(abspath tests/host_scenarios) SCENARIOS=$(abspath $(MOD_HOST_DIR)/tests/host-scenarios.txt) ./tests/jack_e2e.sh

# mod-host's scenario corpus, the runner every host is tested with
tests/host_scenarios: $(MOD_HOST_DIR)/tests/host_scenarios.c $(PROTOCOL_LIB)
	$(CC) $(INCS) $(CFLAGS) -Werror -o $@ $< $(PROTOCOL_LIBS) -lpthread

tests/jack_levels: tests/jack_levels.c
	$(CC) $(shell $(PKG_CONFIG) --cflags jack) $(CFLAGS) -Werror -o $@ $< $(shell $(PKG_CONFIG) --libs jack) -lm

# what include/plugin-hostd/protocol.h declares, written out: README.md and the man page between their markers, and
# protocol/plugin-hostd.json, the same for readers that are not C
GEN = tools/protocol-gen
GENERATED = README.md doc/plugin-hostd.1 protocol/plugin-hostd.json

$(GEN): tools/protocol-gen.c include/plugin-hostd/protocol.h
	$(CC) -Wall -Wextra -Werror -std=gnu99 -Iinclude -o $@ tools/protocol-gen.c

gen: $(GEN)
	$(GEN) json > protocol/plugin-hostd.json.new && mv protocol/plugin-hostd.json.new protocol/plugin-hostd.json
	for f in README.md doc/plugin-hostd.1; do $(GEN) splice $$f > $$f.new && mv $$f.new $$f || exit 1; done

# fails on any drift: every generated output must be byte-identical to a fresh generation, every region the generator
# knows must be in a file
check-generated: $(GEN)
	@set -e; tmp=$$(mktemp -d); trap 'rm -rf $$tmp' EXIT; \
	$(GEN) json > $$tmp/json; cmp $$tmp/json protocol/plugin-hostd.json; \
	for f in README.md doc/plugin-hostd.1; do $(GEN) splice $$f > $$tmp/out; cmp $$tmp/out $$f; done; \
	$(GEN) regions > $$tmp/regions; test -s $$tmp/regions; \
	while read r; do grep -q "BEGIN GENERATED protocol:$$r\( .*\)\?$$" README.md doc/plugin-hostd.1 || { echo "region $$r is in no file"; exit 1; }; done < $$tmp/regions; \
	echo "generated files are current"

# the JSON against its schema, for which the jsonschema module is needed
check-schema:
	python3 tests/protocol_schema.py protocol/plugin-hostd.json protocol/plugin-hostd.schema.json

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
