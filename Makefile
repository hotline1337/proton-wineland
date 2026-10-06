#See help target below for documentation

target_arch ?= x86_64
WINE_UNIX_ARCHS := i386 x86_64
WINE_PE_ARCHS := i386 x86_64
PROTONSDK_ARCH := x86_64
ifeq ($(target_arch),arm64)
    WINE_UNIX_ARCHS := aarch64
    WINE_PE_ARCHS += aarch64
    PROTONSDK_ARCH := arm64-llvm
    ARCH_SUFFIX := -arm64
else ifneq ($(target_arch),x86_64)
    $(error Unknown target_arch=$(target_arch))
endif
WINE_LIB_ARCHS := $(addsuffix -windows,$(WINE_PE_ARCHS)) $(addsuffix -unix,$(WINE_UNIX_ARCHS))
wine-object-arch = $(if $(filter arm64,$(target_arch)),aarch64,$(1))

ifeq ($(build_name),)
    _build_name := $(shell git symbolic-ref --short HEAD 2>/dev/null)-local
else
    _build_name := $(build_name)
endif

ifeq ($(_build_name),)
    $(error ERROR: Unable to auto-detect build name. Check out a branch or specify with "build_name=...")
endif

# remove special chars
override _build_name := $(shell echo $(_build_name) | tr -dc '[:alnum:] ._-')

BUILD_ROOT := build

# make doesn't handle spaces well... replace them with underscores in paths
BUILD_DIR := $(BUILD_ROOT)/build-$(shell echo $(_build_name) | sed -e 's/ /_/g')$(ARCH_SUFFIX)
STEAM_DIR := $(HOME)/.steam/root

ifeq ($(build_name),)
    DEPLOY_DIR := $(shell git describe --tags --always --exclude proton-sdk*)
else
    DEPLOY_DIR := $(_build_name)
endif
DEPLOY_DIR := $(DEPLOY_DIR)$(ARCH_SUFFIX)

ifneq ($(module),)
    ifneq ($(findstring .drv,$(module)),)
        MODULE_PEFILE := $(module)
        MODULE_SOFILE := $(subst .drv,.so,$(module))
    else ifneq ($(findstring .sys,$(module)),)
        MODULE_PEFILE := $(module)
        MODULE_SOFILE := $(subst .sys,.so,$(module))
    else
        MODULE_PEFILE := $(module).dll
        MODULE_SOFILE := $(module).so
    endif
endif

ifneq ($(unstripped),)
    UNSTRIPPED := UNSTRIPPED_BUILD=1
    DEPLOY_DIR := $(DEPLOY_DIR)_unstripped
endif

CONFIGURE_CMD := ../../configure.sh \
	--build-name="$(_build_name)" --target-arch=$(target_arch)

ifneq ($(protonsdk_version),)
CONFIGURE_CMD += --proton-sdk-image=registry.gitlab.steamos.cloud/proton/steamrt4/sdk/$(PROTONSDK_ARCH):$(protonsdk_version)
else
protonsdk_version := $(lastword $(subst :, ,$(shell make --silent SRCDIR=. TARGET_ARCH=$(target_arch) --file Makefile.in get-steamrt-image)))
endif

enable_ccache := 1
ifneq ($(enable_ccache),0)
    CONFIGURE_CMD += --enable-ccache
endif

TOPLEVELGOALS := all any clean configure deploy downloads help install module proton protonsdk redist
CONTAINERGOALS := $(filter-out $(TOPLEVELGOALS),$(MAKECMDGOALS))
CONTAINERGOALS := $(filter-out $(BUILD_ROOT)/%,$(CONTAINERGOALS))

all: help
.PHONY: $(TOPLEVELGOALS)

help:
	@echo "Proton Makefile instructions"
	@echo ""
	@echo "\"Quick start\" Makefile targets:"
	@echo "  install - Install Proton into current user's Steam installation"
	@echo "  redist - Build a package suitable for manual installation or distribution"
	@echo "           to other users in $(BUILD_ROOT)/ named after the nearest git tag"
	@echo "  deploy - Build Steam deployment files into a directory in $(BUILD_ROOT)/ named"
	@echo "           after the nearest git tag"
	@echo "  clean - Delete the Proton build directory"
	@echo ""
	@echo "Configuration variables:"
	@echo "  target_arch - x86_64 (default) or arm64. ARM builds use a separate build directory."
	@echo "  build_name - The name of the build, will be displayed in Steam. Defaults to"
	@echo "               current proton.git branch name if available. A new build dir"
	@echo "               will be created for each build_name, so if you override this,"
	@echo "               remember to always set it!"
	@echo "               Current build name: $(_build_name)"
	@echo "  unstripped - Set to non-empty to avoid stripping installed library files."
	@echo "  enable_ccache - Enabled by default, set to 0 prior to configuring to disable ccache."
	@echo "  protonsdk_version - Version of the proton sdk image to use for building,"
	@echo "                      use protonsdk_version=local to build it locally."
	@echo ""
	@echo "Development targets:"
	@echo "  configure - Configure Proton build directory"
	@echo "  proton - Build Proton"
	@echo ""
	@echo "  The following targets are development targets only useful after building Proton."
	@echo "  module - Rebuild a single Wine module and copy into $(BUILD_ROOT)/<module>/."
	@echo "           Specify module variable: make module=kernel32 module"
	@echo "  dxvk - Rebuild DXVK and copy it into $(BUILD_ROOT)/."
	@echo "  lsteamclient - Rebuild the Steam client wrapper and copy it into $(BUILD_ROOT)/."
	@echo ""
	@echo "Examples:"
	@echo "  make install - Build Proton and install into this user's Steam installation,"
	@echo "      with the current Proton branch name as the tool's name."
	@echo ""
	@echo "  make redist - Build a Proton redistribution package in a tagged directory"
	@echo "      in $(BUILD_ROOT)/."
	@echo ""
	@echo "  make build_name=mytest install - Build Proton with the tool name \"mytest\" and"
	@echo "      install into this user's Steam installation."
	@echo ""
	@echo "  make build_name=mytest module=dsound module - Build only the dsound module"
	@echo "      in the \"mytest\" build directory and place it into $(BUILD_ROOT)/dsound/."

clean:
	rm -rf $(BUILD_DIR)

protonsdk:
	$(MAKE) $(MFLAGS) $(MAKEOVERRIDES) -C docker $(UNSTRIPPED) PROTONSDK_VERSION=$(protonsdk_version) $(if $(filter arm64,$(target_arch)),BUILD_ARCH=aarch64 proton-llvm,proton)

configure: | $(BUILD_DIR)
	if [ ! -e $(BUILD_DIR)/Makefile ]; then \
		(cd $(BUILD_DIR) && $(CONFIGURE_CMD)); \
	fi

ifeq ($(protonsdk_version),local)
configure: protonsdk
endif

proton: configure
	$(MAKE) $(MFLAGS) $(MAKEOVERRIDES) -C $(BUILD_DIR)/ $(UNSTRIPPED) dist && \
	echo "Proton built locally. Use 'install', 'deploy' or 'redist' targets."

install: configure
	rm -rf $(STEAM_DIR)/compatibilitytools.d/$(_build_name)/files/ #remove proton's internal files, but preserve user_settings etc from top-level
	$(MAKE) $(MFLAGS) $(MAKEOVERRIDES) -C $(BUILD_DIR)/ $(UNSTRIPPED) install
	echo "Proton installed to your local Steam installation"

redist: | $(BUILD_ROOT)/$(DEPLOY_DIR)
redist: configure
	rm -rf $(BUILD_ROOT)/$(DEPLOY_DIR)/* && \
	$(MAKE) $(MFLAGS) $(MAKEOVERRIDES) -C $(BUILD_DIR)/ $(UNSTRIPPED) redist && \
	cp -Rf $(BUILD_DIR)/redist/* $(BUILD_ROOT)/$(DEPLOY_DIR) && \
	echo "Proton build available at $(BUILD_ROOT)/$(DEPLOY_DIR)"

deploy: | $(BUILD_ROOT)/$(DEPLOY_DIR)-deploy
deploy: configure
	rm -rf $(BUILD_ROOT)/$(DEPLOY_DIR)-deploy/* && \
	$(MAKE) $(MFLAGS) $(MAKEOVERRIDES) -C $(BUILD_DIR)/ $(UNSTRIPPED) deploy && \
	cp -Rf $(BUILD_DIR)/deploy/* $(BUILD_ROOT)/$(DEPLOY_DIR)-deploy && \
	echo "Proton deployed to $(BUILD_ROOT)/$(DEPLOY_DIR)-deploy"

module: | $(addprefix $(BUILD_ROOT)/$(module)/lib/wine/,$(WINE_LIB_ARCHS))
module: configure
	$(MAKE) $(MFLAGS) $(MAKEOVERRIDES) -C $(BUILD_DIR)/ $(UNSTRIPPED) module=$(module) module && \
	$(foreach arch,$(WINE_PE_ARCHS),cp -f $(BUILD_DIR)/obj-wine-$(call wine-object-arch,$(arch))/dlls/$(module)/$(arch)-windows/$(MODULE_PEFILE) $(BUILD_ROOT)/$(module)/lib/wine/$(arch)-windows/ &&) true
	for arch in $(WINE_UNIX_ARCHS); do \
		for file in $(MODULE_PEFILE).so $(MODULE_SOFILE); do \
			if [ -e $(BUILD_DIR)/obj-wine-$$arch/dlls/$(module)/$$file ]; then \
				cp -f $(BUILD_DIR)/obj-wine-$$arch/dlls/$(module)/$$file $(BUILD_ROOT)/$(module)/lib/wine/$$arch-unix/ || exit 1; \
			fi; \
		done; \
	done

any $(CONTAINERGOALS): configure
	$(MAKE) $(MFLAGS) $(MAKEOVERRIDES) -C $(BUILD_DIR)/ $(UNSTRIPPED) $(CONTAINERGOALS)

dxvk: | $(BUILD_ROOT)/dxvk/lib/wine/dxvk
dxvk: any
	cp -rf $(BUILD_DIR)/dist/files/lib/wine/dxvk/* $(BUILD_ROOT)/dxvk/lib/wine/dxvk/

dxvk-nvapi: | $(BUILD_ROOT)/dxvk-nvapi/lib/wine/nvapi
dxvk-nvapi: any
	cp -rf $(BUILD_DIR)/dist/files/lib/wine/nvapi/* $(BUILD_ROOT)/dxvk-nvapi/lib/wine/nvapi/

vkd3d-proton: | $(BUILD_ROOT)/vkd3d-proton/lib/wine/vkd3d-proton
vkd3d-proton: any
	cp -rf $(BUILD_DIR)/dist/files/lib/wine/vkd3d-proton/* $(BUILD_ROOT)/vkd3d-proton/lib/wine/vkd3d-proton/

define copy-wine-libs
	for arch in $(or $(3),$(WINE_LIB_ARCHS)); do \
		mkdir -p $(BUILD_ROOT)/$(1)/lib/wine/$$arch && \
		cp -f $(BUILD_DIR)/dist/files/lib/wine/$$arch/$(2) $(BUILD_ROOT)/$(1)/lib/wine/$$arch/ || exit 1; \
	done
endef

lsteamclient: any
	$(call copy-wine-libs,lsteamclient,lsteamclient.*)

vrclient: any
	$(call copy-wine-libs,vrclient,vrclient*)

wineopenxr: any
	$(call copy-wine-libs,wineopenxr,wineopenxr.*,$(if $(filter arm64,$(target_arch)),$(WINE_LIB_ARCHS),x86_64-windows x86_64-unix))

battleye: | $(BUILD_ROOT)/battleye/v1/lib/wine/i386-windows
battleye: | $(BUILD_ROOT)/battleye/v1/lib/wine/i386-unix
battleye: | $(BUILD_ROOT)/battleye/v1/lib/wine/x86_64-windows
battleye: | $(BUILD_ROOT)/battleye/v1/lib/wine/x86_64-unix
battleye: any
	cp -f $(BUILD_DIR)/dist-battleye/v1/lib/wine/i386-windows/beclient.dll $(BUILD_ROOT)/battleye/v1/lib/wine/i386-windows/ && \
	cp -f $(BUILD_DIR)/dist-battleye/v1/lib/wine/i386-unix/beclient.dll.so $(BUILD_ROOT)/battleye/v1/lib/wine/i386-unix/ && \
	cp -f $(BUILD_DIR)/dist-battleye/v1/lib/wine/x86_64-windows/beclient_x64.dll $(BUILD_ROOT)/battleye/v1/lib/wine/x86_64-windows/ && \
	cp -f $(BUILD_DIR)/dist-battleye/v1/lib/wine/x86_64-unix/beclient_x64.dll.so $(BUILD_ROOT)/battleye/v1/lib/wine/x86_64-unix/

$(BUILD_ROOT)/%:
	mkdir -p $@
