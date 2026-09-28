# Copy the notices from the dependency revisions used by this build.
# Missing required files must fail the build rather than drop a notice.
DXVK_LICENSE_PATHS := \
	LICENSE \
	include/openvr/LICENSE \
	include/spirv/LICENSE \
	include/vulkan/LICENSE.md \
	include/vulkan/LICENSES/Apache-2.0.txt \
	include/vulkan/LICENSES/MIT.txt \
	subprojects/dxbc-spirv/LICENSE \
	subprojects/dxbc-spirv/submodules/spirv_headers/LICENSE \
	subprojects/libdisplay-info/LICENSE

VKD3D_LICENSE_PATHS := \
	LICENSE COPYING AUTHORS \
	khronos/SPIRV-Headers/LICENSE \
	khronos/Vulkan-Headers/LICENSE.md \
	khronos/Vulkan-Headers/LICENSES/Apache-2.0.txt \
	khronos/Vulkan-Headers/LICENSES/MIT.txt \
	subprojects/dxil-spirv/LICENSE.MIT \
	subprojects/dxil-spirv/third_party/spirv-headers/LICENSE \
	subprojects/dxil-spirv/subprojects/dxbc-spirv/LICENSE \
	subprojects/dxil-spirv/subprojects/dxbc-spirv/submodules/spirv_headers/LICENSE

GRAPHICS_LICENSE_FILES := \
	$(foreach project,dxvk extras/dxvk-low-latency,$(addprefix $(project)/,$(DXVK_LICENSE_PATHS))) \
	$(foreach project,vkd3d-proton extras/vkd3d-low-latency,$(addprefix $(project)/,$(VKD3D_LICENSE_PATHS))) \
	extras/dxvk-sarek/LICENSE \
	extras/dxvk-sarek/include/openvr/LICENSE \
	extras/dxvk-sarek/include/spirv/LICENSE \
	extras/dxvk-sarek/include/vulkan/LICENSE.md \
	dxvk/subprojects/libdisplay-info/data/LICENSE.hwdata \
	dxvk/subprojects/libdisplay-info/data/COPYING.hwdata

# Recent Khronos headers split their notice and license texts. Older pinned
# copies carry a self-contained LICENSE instead.
GRAPHICS_LICENSE_FILES += $(patsubst $(SRCDIR)/%,%,$(wildcard \
	$(foreach project,dxvk extras/dxvk-low-latency, \
		$(SRCDIR)/$(project)/include/spirv/LICENSES/* \
		$(SRCDIR)/$(project)/subprojects/dxbc-spirv/submodules/spirv_headers/LICENSES/*) \
	$(foreach project,vkd3d-proton extras/vkd3d-low-latency, \
		$(SRCDIR)/$(project)/khronos/SPIRV-Headers/LICENSES/* \
		$(SRCDIR)/$(project)/subprojects/dxil-spirv/third_party/spirv-headers/LICENSES/* \
		$(SRCDIR)/$(project)/subprojects/dxil-spirv/subprojects/dxbc-spirv/submodules/spirv_headers/LICENSES/*)))

DIST_GRAPHICS_LICENSES := $(addprefix $(DST_BASE)/licenses/,$(GRAPHICS_LICENSE_FILES))

$(DIST_GRAPHICS_LICENSES): $(DST_BASE)/licenses/%: $(SRCDIR)/%
	mkdir -p "$(dir $@)"
	cp -a "$<" "$@"

.PHONY: graphics-licenses
graphics-licenses: $(DIST_GRAPHICS_LICENSES)

all-dist: graphics-licenses
