"""Exercise the production OpenXR extension queries against a synthetic runtime."""

import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OpenXRExtensionTests(unittest.TestCase):
    def test_extension_queries(self):
        functions = []
        for filename, name in (("openxr.c", "wine_xrGetVulkanInstanceExtensionsKHR"),
                               ("openxr_loader.c", "xrGetVulkanDeviceExtensionsKHR")):
            source = (ROOT / "wineopenxr" / filename).read_text()
            match = re.search(r"XrResult WINAPI " + name + r"\(.*?^\}", source, re.M | re.S)
            self.assertIsNotNone(match)
            functions.append(match.group())
        header = (ROOT / "wineopenxr/openxr_loader.h").read_text()
        constants = "\n".join(re.findall(r"^static const char WINE_VULKAN_DEVICE_.*?;$", header, re.M))
        self.assertEqual(len(constants.splitlines()), 2)
        harness = HARNESS.replace("ACTUAL_CONSTANTS", constants).replace("ACTUAL_FUNCTIONS", "\n\n".join(functions))
        with tempfile.TemporaryDirectory(prefix="openxr-extensions-") as temporary:
            directory = Path(temporary)
            generated, binary = directory / "test.c", directory / "test"
            generated.write_text(harness)
            command = shlex.split(os.environ.get("CC", "cc"))
            command += ["-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter"]
            if os.environ.get("OPENXR_EXTENSION_TEST_SANITIZERS"):
                command += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
            subprocess.run(command + [str(generated), "-o", str(binary)], check=True, timeout=30)
            subprocess.run([str(binary)], check=True, timeout=30)


HARNESS = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uintptr_t XrInstance;
typedef uint64_t XrSystemId;
typedef int XrResult;
enum { XR_SUCCESS, XR_ERROR_SIZE_INSUFFICIENT = -1, XR_ERROR_OUT_OF_MEMORY = -2,
       XR_ERROR_RUNTIME_FAILURE = -3, XR_ERROR_VALIDATION_FAILURE = -4, XR_ERROR_HANDLE_INVALID = -5 };
#define WINAPI
#define TRACE(...) ((void)0)
#define ERR(...) ((void)0)
ACTUAL_CONSTANTS

static char *host_value, *saved_environment;
static unsigned int calls, allocations, live_allocations, fail_allocation, fail_host_call, padding;
static unsigned int grow, unterminated, stalled, zero_count, environment_updates, checks;
static uint32_t forced_count;
static const char suffix[] = "VK_KHR_surface VK_KHR_win32_surface";

struct instance_data { XrInstance host_instance; };
static struct instance_data instance_data = {55};
static struct instance_data *wine_instance_from_handle(XrInstance instance)
{
    assert(instance == 1);
    return &instance_data;
}

static XrResult host_query(XrInstance instance, XrSystemId system, uint32_t capacity, uint32_t *size, char *buffer)
{
    assert(instance == 55 && system == 7);
    ++calls;
    if (calls == fail_host_call) return XR_ERROR_HANDLE_INVALID;
    if (zero_count) { *size = 0; return XR_SUCCESS; }
    if (stalled && capacity) { *size = capacity; return XR_ERROR_SIZE_INSUFFICIENT; }
    if (capacity && grow)
    {
        size_t length = strlen(host_value);
        host_value = realloc(host_value, length + 18);
        assert(host_value);
        memset(host_value + length, 'b', 17);
        host_value[length + 17] = 0;
        --grow;
    }
    *size = forced_count ? forced_count : strlen(host_value) + 1 + padding;
    if (!capacity) return XR_SUCCESS;
    if (capacity < *size) return XR_ERROR_SIZE_INSUFFICIENT;
    if (unterminated) memset(buffer, 'a', capacity);
    else memcpy(buffer, host_value, strlen(host_value) + 1);
    return XR_SUCCESS;
}

static struct { XrResult (*p_xrGetVulkanInstanceExtensionsKHR)(XrInstance, XrSystemId, uint32_t, uint32_t *, char *); }
    g_xr_host_instance_dispatch_table = {host_query};
struct xrGetVulkanDeviceExtensionsKHR_params
{
    XrInstance instance;
    XrSystemId systemId;
    uint32_t bufferCapacityInput;
    uint32_t *bufferCountOutput;
    char *buffer;
    XrResult result;
};
static void unix_call(struct xrGetVulkanDeviceExtensionsKHR_params *params)
{
    params->result = host_query(wine_instance_from_handle(params->instance)->host_instance, params->systemId,
                               params->bufferCapacityInput, params->bufferCountOutput, params->buffer);
}
#define UNIX_CALL_CHECKED(name, params) unix_call(params)
static void __wine_set_unix_env(const char *name, const char *value)
{
    assert(!strcmp(name, WINE_VULKAN_DEVICE_VARIABLE));
    free(saved_environment);
    saved_environment = strdup(value);
    assert(saved_environment);
    ++environment_updates;
}

static void *tracked_realloc(void *ptr, size_t size)
{
    void *result;
    ++allocations;
    if (allocations == fail_allocation || size > 1024 * 1024) return NULL;
    result = realloc(ptr, size);
    if (result && !ptr) ++live_allocations;
    return result;
}
static void tracked_free(void *ptr)
{
    if (ptr) { assert(live_allocations == 1); --live_allocations; }
    free(ptr);
}
#define realloc tracked_realloc
#define free tracked_free
ACTUAL_FUNCTIONS
#undef free
#undef realloc

static void reset(size_t length)
{
    assert(!live_allocations);
    free(host_value);
    free(saved_environment);
    saved_environment = NULL;
    host_value = malloc(length + 1);
    assert(host_value);
    memset(host_value, 'a', length);
    host_value[length] = 0;
    calls = allocations = fail_allocation = fail_host_call = padding = grow = 0;
    unterminated = stalled = zero_count = environment_updates = forced_count = 0;
}

typedef XrResult (*query_func)(XrInstance, XrSystemId, uint32_t, uint32_t *, char *);
static void check_value(query_func query, int device)
{
    char output[70000];
    uint32_t count = 0, expected;
    memset(output, 0xcc, sizeof(output));
    assert(query(1, 7, 0, &count, NULL) == XR_SUCCESS);
    expected = device ? sizeof(WINE_VULKAN_DEVICE_EXTENSION_NAME) :
               strlen(host_value) + (strlen(host_value) ? 1 : 0) + sizeof(suffix);
    assert(count == expected && !live_allocations && !environment_updates);
    assert(query(1, 7, count - 1, &count, output) == XR_ERROR_SIZE_INSUFFICIENT);
    assert(count == expected && (unsigned char)output[0] == 0xcc && !live_allocations && !environment_updates);
    assert(query(1, 7, count, &count, output) == XR_SUCCESS);
    assert(count == expected && (unsigned char)output[count] == 0xcc && !live_allocations);
    if (device)
    {
        assert(!strcmp(output, WINE_VULKAN_DEVICE_EXTENSION_NAME));
        assert(environment_updates == 1 && !strcmp(saved_environment, host_value));
    }
    else
    {
        size_t length = strlen(host_value);
        assert(!memcmp(output, host_value, length));
        if (length) assert(output[length++] == ' ');
        assert(!strcmp(output + length, suffix));
    }
    ++checks;
}

int main(void)
{
    query_func queries[] = {wine_xrGetVulkanInstanceExtensionsKHR, xrGetVulkanDeviceExtensionsKHR};
    const size_t lengths[] = {0, 1, 31, 4062, 4095, 4096, 8192, 65536};
    unsigned int device, i;
    for (device = 0; device < 2; ++device)
    {
        query_func query = queries[device];
        char output[70000];
        uint32_t count;
        for (i = 0; i < sizeof(lengths) / sizeof(*lengths); ++i)
        {
            reset(lengths[i]);
            check_value(query, device);
            reset(lengths[i]);
            padding = 13;
            check_value(query, device);
        }
        reset(16);
        grow = 1;
        assert(query(1, 7, sizeof(output), &count, output) == XR_SUCCESS);
        assert(allocations == 2 && !live_allocations);
        if (device) assert(!strcmp(saved_environment, host_value));
        else assert(!memcmp(output, host_value, strlen(host_value)));
        ++checks;
        for (i = 1; i <= 2; ++i)
        {
            reset(16);
            grow = i == 2;
            fail_allocation = i;
            assert(query(1, 7, sizeof(output), &count, output) == XR_ERROR_OUT_OF_MEMORY);
            assert(!live_allocations && !environment_updates);
            ++checks;
            reset(16);
            fail_host_call = i;
            assert(query(1, 7, sizeof(output), &count, output) == XR_ERROR_HANDLE_INVALID);
            assert(!live_allocations && !environment_updates);
            ++checks;
        }
        reset(16);
        unterminated = 1;
        assert(query(1, 7, sizeof(output), &count, output) == XR_ERROR_RUNTIME_FAILURE);
        assert(!live_allocations && !environment_updates);
        ++checks;
        reset(16);
        stalled = 1;
        assert(query(1, 7, sizeof(output), &count, output) == XR_ERROR_RUNTIME_FAILURE);
        assert(!live_allocations && !environment_updates);
        ++checks;
        reset(16);
        zero_count = 1;
        assert(query(1, 7, sizeof(output), &count, output) == XR_ERROR_RUNTIME_FAILURE);
        assert(!live_allocations && !environment_updates);
        ++checks;
        reset(16);
        forced_count = UINT32_MAX;
        assert(query(1, 7, sizeof(output), &count, output) == XR_ERROR_OUT_OF_MEMORY);
        assert(!live_allocations && !environment_updates);
        ++checks;
        reset(16);
        assert(query(1, 7, sizeof(output), NULL, output) == XR_ERROR_VALIDATION_FAILURE);
        assert(query(1, 7, sizeof(output), &count, NULL) == XR_ERROR_VALIDATION_FAILURE);
        assert(!calls && !live_allocations);
        ++checks;
    }
    free(host_value);
    free(saved_environment);
    printf("OpenXR extension queries: %u scenarios passed\n", checks);
}
"""


if __name__ == "__main__":
    unittest.main()
