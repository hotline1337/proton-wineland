# Development files for RADV's X11 build. These libraries are never distributed.
MESA_XCB_VERSION := 1.17.0
MESA_XCB_PROTO_VERSION := 1.17.0
MESA_XCB_DOWNLOADS := $(OBJ)/downloads/mesa
MESA_XCB_SRC := $(OBJ)/src-mesa-xcb-$(MESA_XCB_VERSION)
MESA_XCB_PROTO_SRC := $(OBJ)/src-mesa-xcb-proto-$(MESA_XCB_PROTO_VERSION)
MESA_XCB_PROTO_OBJ := $(OBJ)/obj-mesa-xcb-proto
MESA_XCB_PROTO_DST := $(OBJ)/dst-mesa-xcb-proto
MESA_XCB_RULES := $(lastword $(MAKEFILE_LIST))

$(MESA_XCB_DOWNLOADS)/libxcb-$(MESA_XCB_VERSION).tar.xz:
	mkdir -p "$(MESA_XCB_DOWNLOADS)"
	curl --fail --location --retry 3 --output "$@.tmp" \
	    "https://xorg.freedesktop.org/archive/individual/lib/libxcb-$(MESA_XCB_VERSION).tar.xz"
	printf '%s  %s\n' \
	    599ebf9996710fea71622e6e184f3a8ad5b43d0e5fa8c4e407123c88a59a6d55 "$@.tmp" | sha256sum --check
	mv "$@.tmp" "$@"

$(MESA_XCB_DOWNLOADS)/xcb-proto-$(MESA_XCB_PROTO_VERSION).tar.xz:
	mkdir -p "$(MESA_XCB_DOWNLOADS)"
	curl --fail --location --retry 3 --output "$@.tmp" \
	    "https://xorg.freedesktop.org/archive/individual/proto/xcb-proto-$(MESA_XCB_PROTO_VERSION).tar.xz"
	printf '%s  %s\n' \
	    2c1bacd2110f4799f74de6ebb714b94cf6f80fb112316b1219480fd22562148c "$@.tmp" | sha256sum --check
	mv "$@.tmp" "$@"

$(OBJ)/.mesa-xcb-source: \
    $(MESA_XCB_DOWNLOADS)/libxcb-$(MESA_XCB_VERSION).tar.xz \
    $(MESA_XCB_DOWNLOADS)/xcb-proto-$(MESA_XCB_PROTO_VERSION).tar.xz
	mkdir -p "$(MESA_XCB_SRC)" "$(MESA_XCB_PROTO_SRC)"
	tar -xf "$(MESA_XCB_DOWNLOADS)/libxcb-$(MESA_XCB_VERSION).tar.xz" \
	    --strip-components=1 -C "$(MESA_XCB_SRC)"
	tar -xf "$(MESA_XCB_DOWNLOADS)/xcb-proto-$(MESA_XCB_PROTO_VERSION).tar.xz" \
	    --strip-components=1 -C "$(MESA_XCB_PROTO_SRC)"
	touch "$@"

$(OBJ)/.mesa-xcb-proto-build: $(OBJ)/.mesa-xcb-source $(MESA_XCB_RULES)
	mkdir -p "$(MESA_XCB_PROTO_OBJ)"
	cd "$(MESA_XCB_PROTO_OBJ)" && \
	    "$(MESA_XCB_PROTO_SRC)/configure" --prefix="$(MESA_XCB_PROTO_DST)" PYTHON=python3
	+$(MAKE) -C "$(MESA_XCB_PROTO_OBJ)" install
	touch "$@"

MESA_XCB_i386_TRIPLET := i386-linux-gnu
MESA_XCB_i386_HOST := i686-linux-gnu
MESA_XCB_i386_CC := gcc -m32
MESA_XCB_x86_64_TRIPLET := x86_64-linux-gnu
MESA_XCB_x86_64_HOST := x86_64-linux-gnu
MESA_XCB_x86_64_CC := gcc

MESA_XCB_CONFIGURE_ARGS := \
	--enable-shared --disable-static --disable-devel-docs --without-doxygen \
	--disable-dependency-tracking \
	--enable-dri3 --enable-present --enable-randr --enable-xfixes \
	--enable-sync --enable-shm --enable-render --enable-shape \
	--disable-composite --disable-damage --disable-dbe --disable-dpms \
	--disable-dri2 --disable-ge --disable-glx --disable-record \
	--disable-resource --disable-screensaver --disable-xevie \
	--disable-xfree86-dri --disable-xinerama --disable-xinput --disable-xkb \
	--disable-xprint --disable-selinux --disable-xtest --disable-xv --disable-xvmc

define mesa-xcb-dev-rules
MESA_XCB_$(1)_OBJ := $$(OBJ)/obj-mesa-xcb-$(1)
MESA_XCB_$(1)_DST := $$(OBJ)/dst-mesa-xcb-$(1)
MESA_XCB_$(1)_LIBDIR := $$(OBJ)/dst-mesa-xcb-$(1)/lib/$$(MESA_XCB_$(1)_TRIPLET)
MESA_XCB_$(1)_PKG_CONFIG_PATH := $$(MESA_XCB_$(1)_LIBDIR)/pkgconfig

$$(OBJ)/.mesa-xcb-$(1)-configure: $$(OBJ)/.mesa-xcb-proto-build $$(MESA_XCB_RULES)
	mkdir -p "$$(MESA_XCB_$(1)_OBJ)"
	cd "$$(MESA_XCB_$(1)_OBJ)" && \
	    env PKG_CONFIG_PATH="$$(MESA_XCB_PROTO_DST)/share/pkgconfig" \
	        PKG_CONFIG_LIBDIR="/usr/lib/$$(MESA_XCB_$(1)_TRIPLET)/pkgconfig:/usr/share/pkgconfig" \
	        PYTHONDONTWRITEBYTECODE=1 \
	    "$$(MESA_XCB_SRC)/configure" \
	        --build=x86_64-linux-gnu --host="$$(MESA_XCB_$(1)_HOST)" \
	        --prefix="$$(MESA_XCB_$(1)_DST)" --libdir="$$(MESA_XCB_$(1)_LIBDIR)" \
	        $$(MESA_XCB_CONFIGURE_ARGS) CC="$$(MESA_XCB_$(1)_CC)" CFLAGS='-O2 -fPIC' PYTHON=python3
	touch "$$@"

$$(OBJ)/.mesa-xcb-$(1)-build: $$(OBJ)/.mesa-xcb-$(1)-configure
	+$$(MAKE) -C "$$(MESA_XCB_$(1)_OBJ)" install
	touch "$$@"

.PHONY: mesa-xcb-$(1)-build
mesa-xcb-$(1)-build: $$(OBJ)/.mesa-xcb-$(1)-build
endef

$(foreach arch,$(filter i386 x86_64,$(unix_ARCHS)),$(eval $(call mesa-xcb-dev-rules,$(arch))))

.PHONY: mesa-xcb-distclean
mesa-xcb-distclean:
	rm -rf "$(MESA_XCB_SRC)" "$(MESA_XCB_PROTO_SRC)" "$(MESA_XCB_PROTO_OBJ)" "$(MESA_XCB_PROTO_DST)"
	rm -rf $(foreach arch,$(filter i386 x86_64,$(unix_ARCHS)),"$(MESA_XCB_$(arch)_OBJ)" "$(MESA_XCB_$(arch)_DST)")
	rm -f $(OBJ)/.mesa-xcb-source $(OBJ)/.mesa-xcb-proto-build
	rm -f $(foreach arch,$(filter i386 x86_64,$(unix_ARCHS)),$(OBJ)/.mesa-xcb-$(arch)-configure $(OBJ)/.mesa-xcb-$(arch)-build)
