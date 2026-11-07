# SPDX-FileCopyrightText: 2026 rarrifano
# SPDX-License-Identifier: MIT

# YorkFolio Desktop — C++ core + Python/Qt app
PY      ?= python3
VENV    ?= .venv
VPY     := $(VENV)/bin/python
CXX     ?= g++
CXXFLAGS ?= -O2
CORE_FLAGS := -std=c++20 -Wall -Wextra -fPIC -fvisibility=hidden -Icore/include -Icore/third_party
SRC     := core/src/book.cpp core/src/tax.cpp core/src/aporte.cpp core/src/capi.cpp
OBJ     := $(patsubst core/src/%.cpp,build/%.o,$(SRC))
UNAME   := $(shell uname -s)
ifeq ($(UNAME),Darwin)
  LIBEXT := dylib
  SOFLAG := -dynamiclib
else ifneq (,$(findstring MINGW,$(UNAME))$(findstring MSYS,$(UNAME)))
  LIBEXT := dll
  SOFLAG := -shared
else
  LIBEXT := so
  SOFLAG := -shared
endif
LIB     := yorkfolio_qt/libyorkfolio_core.$(LIBEXT)

.PHONY: help all core venv run test test-core test-py clean flatpak flatpak-install flatpak-run
help:  ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/'

all: core  ## build the C++ core

core: $(LIB)  ## build the shared library into yorkfolio_qt/

$(LIB): $(OBJ)
	$(CXX) $(SOFLAG) -o $@ $^

build/%.o: core/src/%.cpp $(wildcard core/include/yorkfolio/*)
	@mkdir -p build
	$(CXX) $(CORE_FLAGS) $(CXXFLAGS) -c $< -o $@

venv:  ## create .venv with the Python dependencies (PySide6)
	$(PY) -m venv $(VENV) || ($(PY) -m venv --without-pip $(VENV) && curl -sSL https://bootstrap.pypa.io/get-pip.py | $(VPY))
	$(VPY) -m pip install -q -r requirements.txt

run: core  ## start the desktop app
	$(VPY) -m yorkfolio_qt

test-core: build/test_core  ## C++ unit tests
	./build/test_core

build/test_core: core/tests/test_core.cpp $(filter-out build/capi.o,$(OBJ))
	@mkdir -p build
	$(CXX) $(CORE_FLAGS) $(CXXFLAGS) $^ -o $@

test-py: core  ## Python tests (parity with the reference engine, services, UI smoke test)
	QT_QPA_PLATFORM=offscreen $(VPY) -m unittest discover -s tests -t . -v

test: test-core test-py  ## everything

FLATPAK_ID := io.github.rarrifano.YorkFolioQt
BUILDER    ?= flatpak run org.flatpak.Builder

flatpak:  ## build $(FLATPAK_ID).flatpak (needs flatpak-builder, org.kde.Sdk//6.10, io.qt.PySide.BaseApp//6.10)
	$(BUILDER) --user --force-clean --disable-rofiles-fuse --state-dir=.flatpak-builder \
	  --install-deps-from=flathub --repo=flatpak-repo flatpak-build flatpak/$(FLATPAK_ID).yml
	flatpak build-bundle flatpak-repo $(FLATPAK_ID).flatpak $(FLATPAK_ID)

flatpak-install: flatpak  ## install the bundle for the current user
	flatpak install --user -y $(FLATPAK_ID).flatpak

flatpak-run:  ## run the installed flatpak
	flatpak run $(FLATPAK_ID)

clean:  ## remove build output
	rm -rf build $(LIB) flatpak-build flatpak-repo .flatpak-builder $(FLATPAK_ID).flatpak
