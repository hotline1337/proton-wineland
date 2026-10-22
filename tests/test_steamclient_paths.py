"""Compile the actual Steam path helpers and run their failure and Unicode cases."""

import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "lsteamclient/unixlib.cpp"


class SteamClientPathTests(unittest.TestCase):
    def run_native(self, helper, harness):
        with tempfile.TemporaryDirectory(prefix="steamclient-paths-") as temporary:
            directory = Path(temporary)
            source = directory / "test.cpp"
            binary = directory / "test"
            source.write_text(harness.replace("ACTUAL_HELPER", helper).replace("TEST_DIRECTORY", str(directory)))
            command = shlex.split(os.environ.get("CXX", "c++"))
            command += ["-std=c++11", "-Wall", "-Wextra", "-Werror", "-g"]
            if os.environ.get("STEAMCLIENT_PATH_SANITIZERS"):
                command += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
            subprocess.run(command + [str(source), "-o", str(binary)], check=True, timeout=30)
            subprocess.run([str(binary)], check=True, timeout=30)

    def test_file_name_failure(self):
        source = SOURCE.read_text()
        helper = source[source.index("static char *get_unix_file_name("):
                        source.index("static unsigned char hexdigit(")]
        self.run_native(helper, r"""
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>

typedef uint16_t WCHAR;
typedef uint32_t NTSTATUS;
#define STATUS_NO_SUCH_FILE 0xc000000f
#define FILE_OPEN_IF 3

static unsigned int mode, free_count;

static NTSTATUS ntdll_get_unix_file_name(const WCHAR *, char **output, unsigned int)
{
    switch (mode)
    {
    case 0: *output = strdup("existing"); return 0;
    case 1: *output = strdup("missing"); return STATUS_NO_SUCH_FILE;
    case 2: return 0xc0000022;
    case 3: *output = strdup("discarded"); return 0xc0000022;
    }
    abort();
}

static void counted_free(void *pointer)
{
    if (pointer) ++free_count;
    free(pointer);
}

#define free counted_free
ACTUAL_HELPER
#undef free

int main()
{
    const WCHAR path[] = {'a', 0};
    for (mode = 0; mode < 4; ++mode)
    {
        free_count = 0;
        char *result = get_unix_file_name(path);
        if (mode < 2)
        {
            assert(result);
            assert(!strcmp(result, mode ? "missing" : "existing"));
        }
        else assert(!result);
        assert(free_count == (mode == 3));
        free(result);
    }
}
""")

    def test_install_directory_boundaries(self):
        source = SOURCE.read_text()
        helper = source[source.index("char *steamclient_dos_to_unix_path_fixup_slash("):
                        source.index("void steamclient_free_path(")]
        self.run_native(helper, r"""
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
#define TRACE(...) ((void)0)

static bool fail_conversion, fail_resolution;
static char *steamclient_dos_to_unix_path(const char *src, int)
{
    return src && !fail_conversion ? strdup(src) : nullptr;
}
static char *resolve_path(const char *src, char *dst)
{
    return fail_resolution ? nullptr : realpath(src, dst);
}
#define realpath resolve_path
ACTUAL_HELPER
#undef realpath

static void check(const std::string &src, const std::string &expected)
{
    char *path = steamclient_dos_to_unix_path_fixup_slash(src.c_str(), 0);
    assert(path && !strcmp(path, expected.c_str()));
    free(path);
}
int main()
{
    const std::string base = "TEST_DIRECTORY/game", alias = "TEST_DIRECTORY/alias";
    assert(!mkdir(base.c_str(), 0700));
    assert(!symlink(base.c_str(), alias.c_str()));
    assert(!setenv("STEAM_COMPAT_INSTALL_PATH", base.c_str(), 1));
    check("/", "/");
    check("", "");
    check(base, base);
    check(base + "/nested/data/file", base + "/nested\\data\\file");
    check(base + "-other/data/file", base + "-other/data/file");
    check("relative/data/file", "relative/data/file");
    check("file://" + base + "/nested/file", "file://" + base + "/nested/file");
    assert(!steamclient_dos_to_unix_path_fixup_slash(nullptr, 0));
    assert(!setenv("STEAM_COMPAT_INSTALL_PATH", alias.c_str(), 1));
    check(base + "/nested/file", base + "/nested\\file");
    assert(!setenv("STEAM_COMPAT_INSTALL_PATH", "/", 1));
    check("/elsewhere/data/file", "/elsewhere\\data\\file");
    check("/", "/");
    fail_resolution = true;
    check(base + "/nested/file", base + "/nested/file");
    fail_resolution = false;
    fail_conversion = true;
    assert(!steamclient_dos_to_unix_path_fixup_slash(base.c_str(), 0));
    fail_conversion = false;
    assert(!setenv("STEAM_COMPAT_INSTALL_PATH", "/missing-install-directory", 1));
    check(base + "/nested/file", base + "/nested/file");
    assert(!unsetenv("STEAM_COMPAT_INSTALL_PATH"));
    check(base + "/nested/file", base + "/nested/file");
}
""")

    def test_canonical_paths(self):
        source = SOURCE.read_text()
        helper = source[source.index("char *steamclient_dos_to_unix_path("):
                        source.index("char *steamclient_dos_to_unix_path_fixup_slash(")]
        self.run_native(helper, r"""
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits.h>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
using WCHAR = char16_t;
#define TRACE(...) ((void)0)
#define ERR(...) ((void)0)
#define IS_ABSOLUTE(x) (*(x) == '/' || *(x) == '\\' || (*(x) && *((x) + 1) == ':'))
static const char *converted_path;
static bool fail_resolution;
static uint32_t ntdll_umbstowcs(const char *src, int length, WCHAR *dst, int capacity)
{
    assert(length < capacity);
    for (int i = 0; i < length; ++i) dst[i] = src[i];
    return length;
}
static void collapse_path(WCHAR *, unsigned int) {}
static void url_unescape(WCHAR *) {}
static char *get_unix_file_name(WCHAR *) { return strdup(converted_path); }
static void lstrcpynA(char *dst, const char *src, size_t size)
{
    snprintf(dst, size, "%s", src);
}
static char *resolve_path(const char *src, char *dst)
{
    return fail_resolution ? nullptr : realpath(src, dst);
}
#define realpath resolve_path
ACTUAL_HELPER
#undef realpath
static void check(const char *src, int url, const std::string &expected)
{
    char *path = steamclient_dos_to_unix_path(src, url);
    assert(path && !strcmp(path, expected.c_str()));
    free(path);
}
int main()
{
    const std::string base = "TEST_DIRECTORY/game", alias = "TEST_DIRECTORY/alias";
    assert(!mkdir(base.c_str(), 0700));
    assert(!symlink(base.c_str(), alias.c_str()));
    FILE *file = fopen((base + "/data").c_str(), "w");
    assert(file && !fclose(file));
    std::string converted = alias + "/data";
    converted_path = converted.c_str();
    check("Z:\\alias\\data", 0, base + "/data");
    check("file://Z:/alias/data", 1, "file://" + alias + "/data");
    check("https://example.test/data", 1, "https://example.test/data");
    check("relative\\data", 0, "relative/data");
    check("", 0, "");
    fail_resolution = true;
    check("Z:\\alias\\data", 0, converted);
    fail_resolution = false;
    converted = alias + "/missing";
    converted_path = converted.c_str();
    check("Z:\\alias\\missing", 0, converted);
    assert(!steamclient_dos_to_unix_path(nullptr, 0));
}
""")

    def test_url_unescape(self):
        source = SOURCE.read_text()
        helper = source[source.index("static unsigned char hexdigit("):
                        source.index("char *steamclient_dos_to_unix_path(")]
        self.run_native(helper, r"""
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iconv.h>
#include <string>
#include <vector>

typedef char16_t WCHAR;
static unsigned int conversions;
static bool allocation_failure;

static size_t wide_length(const WCHAR *s)
{
    const WCHAR *end = s;
    while (*end) ++end;
    return end - s;
}

static void *test_malloc(size_t count)
{
    return allocation_failure ? nullptr : malloc(count);
}

/* Supply the ntdll conversion contract while exercising the actual path helper. */
static uint32_t RtlUTF8ToUnicodeN(WCHAR *dst, unsigned int size,
                                unsigned int *written, const char *src, unsigned int count)
{
    ++conversions;
    assert(size == count * sizeof(*dst));
    iconv_t converter = iconv_open("UTF-16LE", "UTF-8");
    assert(converter != (iconv_t)-1);
    char *input = const_cast<char *>(src), *output = reinterpret_cast<char *>(dst);
    size_t remaining = count, space = size;
    uint32_t status = 0;
    while (remaining)
    {
        if (iconv(converter, &input, &remaining, &output, &space) != (size_t)-1) continue;
        assert(errno == EILSEQ || errno == EINVAL);
        assert(space >= 2);
        *output++ = '\xfd';
        *output++ = '\xff';
        space -= 2;
        ++input;
        --remaining;
        status = 0x00000107;
    }
    *written = size - space;
    iconv_close(converter);
    return status;
}

#define wcslen wide_length
#define malloc test_malloc
ACTUAL_HELPER
#undef malloc
#undef wcslen

static void check(const std::u16string &input, const std::u16string &expected)
{
    std::vector<WCHAR> buffer(input.begin(), input.end());
    buffer.push_back(0);
    buffer.push_back(0xabcd);
    buffer.push_back(0x1234);
    url_unescape(buffer.data());
    assert(std::u16string(buffer.data()) == expected);
    assert(wide_length(buffer.data()) <= input.size());
    assert(buffer[input.size() + 1] == 0xabcd);
    assert(buffer[input.size() + 2] == 0x1234);
}

int main()
{
    check(u"", u"");
    check(u"%", u"%");
    check(u"%2", u"%2");
    check(u"%41", u"A");
    check(u"file%20", u"file ");
    check(u"%c3%a9", u"\u00e9");
    check(u"%E4%B8%AD", u"\u4e2d");
    check(u"%F0%9F%8E%AE", u"\U0001f3ae");
    check(u"\u00e9/%E4%B8%AD/\U0001f3ae%20name", u"\u00e9/\u4e2d/\U0001f3ae name");
    check(u"%GG%41%2", u"%GGA%2");
    check(u"%41%00%42", u"A%00B");
    check(u"%2520", u"%20");
    check(u"%FF%41", u"\ufffdA");
    check(u"%C3", u"\ufffd");
    check(u"%C3x%A9", u"\ufffdx\ufffd");
    check(std::u16string(1, 0xd800) + u"%41", std::u16string(1, 0xd800) + u"A");
    check(std::u16string(4090, u'x') + u"%41", std::u16string(4090, u'x') + u"A");
    check(std::u16string(4093, u'x'), std::u16string(4093, u'x'));

    allocation_failure = true;
    conversions = 0;
    check(u"\u00e9/%E4%B8%AD", u"\u00e9/%E4%B8%AD");
    assert(!conversions);
    allocation_failure = false;

    const std::u16string inputs[] = {u"%41", u"%c3%a9", u"%E4%B8%AD", u"%F0%9F%8E%AE",
                                    u"%GG", u"%00", u"%FF", u"_", u"\u00e9", u"\U0001f3ae"};
    const std::u16string outputs[] = {u"A", u"\u00e9", u"\u4e2d", u"\U0001f3ae", u"%GG",
                                     u"%00", u"\ufffd", u"_", u"\u00e9", u"\U0001f3ae"};
    uint32_t state = 1;
    for (unsigned int iteration = 0; iteration < 5000; ++iteration)
    {
        std::u16string input, expected;
        for (unsigned int j = 0; j < iteration % 31; ++j)
        {
            state = state * 1664525 + 1013904223;
            unsigned int choice = state % 10;
            input += inputs[choice];
            expected += outputs[choice];
        }
        check(input, expected);
    }
}
""")


if __name__ == "__main__":
    unittest.main()
