##
## wayland-protocols
##

WAYLAND_PROTOCOLS_MESON_ARGS := \
	-Dtests=false

$(eval $(call rules-source,wayland-protocols,$(SRCDIR)/steamrtdeps/wayland-protocols))
$(eval $(call rules-meson,wayland-protocols,i386,unix))
$(eval $(call rules-meson,wayland-protocols,x86_64,unix))
$(eval $(call rules-meson,wayland-protocols,aarch64,unix))

WAYLAND_PROTOCOLS_PATCH := $(SRC)/patches/wayland-protocols/0001-build-require-compatible-scanner-for-enum-headers.patch

$(OBJ)/.wayland-protocols-post-source: $(WAYLAND_PROTOCOLS_PATCH)
	cp "$(WAYLAND_PROTOCOLS_ORIGIN)/meson.build" "$(WAYLAND_PROTOCOLS_SRC)/meson.build"
	patch --batch --fuzz=0 -d "$(WAYLAND_PROTOCOLS_SRC)" -Np1 -i "$(WAYLAND_PROTOCOLS_PATCH)"
	touch "$@"

WAYLAND_PROTOCOLS_DEPENDENCY := wayland-protocols
