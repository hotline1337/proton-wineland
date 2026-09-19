##
## speex
##

SPEEX_CONFIGURE_ARGS := \
	--enable-shared \
	--disable-static \
	--disable-binaries \
	--disable-valgrind

# Exclude generated autotools files from the source sync so they are not seen
# as "extras" by the rsync dry-run (which would force a --delete re-sync that
# wipes the autoreconf-generated configure mid-build). autoreconf regenerates
# them in the synced tree. Mirrors openfst.
SPEEX_SOURCE_ARGS = \
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

$(eval $(call rules-source,speex,$(SRCDIR)/steamrtdeps/speex))
$(eval $(call rules-configure,speex,i386,unix))

$(OBJ)/.speex-post-source:
	cd "$(SPEEX_SRC)" && autoreconf -fiv
	touch $@

SPEEX_DEPENDENCY := speex
