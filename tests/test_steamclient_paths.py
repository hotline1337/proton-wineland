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
            source.write_text(harness.replace("ACTUAL_HELPER", helper))
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


if __name__ == "__main__":
    unittest.main()
