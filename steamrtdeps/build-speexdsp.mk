##
## speexdsp
##

SPEEXDSP_CONFIGURE_ARGS := \
	--enable-shared \
	--disable-static \
	--disable-examples

# See build-speex.mk: keep autoreconf-generated files out of the source sync so
# the dry-run does not force a --delete re-sync that wipes configure mid-build.
SPEEXDSP_SOURCE_ARGS = \
  --exclude aclocal.m4 \
  --exclude ar-lib \
  --exclude autom4te.cache \
  --exclude compile \
  --exclude config.guess \
  --exclude config.h.in \
  --exclude config.sub \
  --exclude configure \
  --exclude depcomp \
  --exclude install-sh \
  --exclude ltmain.sh \
  --exclude m4/libtool.m4 \
  --exclude m4/ltoptions.m4 \
  --exclude m4/ltsugar.m4 \
  --exclude m4/ltversion.m4 \
  --exclude m4/lt~obsolete.m4 \
  --exclude Makefile.in \
  --exclude missing \
  --exclude test-driver \

$(eval $(call rules-source,speexdsp,$(SRCDIR)/steamrtdeps/speexdsp))
$(eval $(call rules-configure,speexdsp,i386,unix))

$(OBJ)/.speexdsp-post-source:
	cd "$(SPEEXDSP_SRC)" && autoreconf -fiv
	touch $@

SPEEXDSP_DEPENDENCY := speexdsp
