# Steam callback initialization tests

Run from the Proton repository root on Linux with Python 3, a host C compiler,
a host C++ compiler and pthreads:

```sh
python3 lsteamclient/native-tests/run.py --benchmark
python3 lsteamclient/native-tests/run.py --sanitize address
python3 lsteamclient/native-tests/run.py --sanitize thread
```

Paths above are relative to the Proton repository root. `--output /tmp/my-tests`
keeps generated source and executables at an explicit location. The default is
a fresh temporary directory. `CC` and `CXX` can select the compilers.

The runner extracts the current production `get_env_win`, `init_steamclient`,
`load_steamclient`, `sync_env_var` and Unix `steamclient_init` bodies. It also
extracts the parameter structure from `unixlib.h` and prints the source hashes.
No separate copy of the algorithm is maintained in these tests.

The PE-side host model substitutes Windows environment access, recursive
critical sections, atomics, last error, Winsock and the Unix call. Tests cover
first-use initialization, 100,000 cached callback checks with no environment
reads, forced environment resynchronization and removal, oversized environment
values, success last-error preservation, failed initialization retries,
same-thread reentry and simultaneous first use by eight threads.

The Unix-side host model substitutes only the environment and dynamic loader.
Each missing export has an independent template instantiation so static state
cannot leak between cases. Every case fails twice, then retries successfully
without reopening the library. A separate case covers repeated `dlopen` failure.
Successful initialization still synchronizes changed and removed variables.
Call-site checks require all three callback exports to use the cached path and
all five other initialization entry points to retain forced synchronization.

The optional benchmark compares one million cached checks with one million
forced synchronizations in seven batches. It measures the extracted functions
with mocks. It is not a Wine environment-scanning benchmark and says nothing
about game loading time, frame rates or the duration of an individual real
Steam callback. Sanitizer timings are not performance results.

These are focused host tests, not binary-layout validation or substitutes for
building both Wine DLL architectures and running Steam games. No Steam
installation, Wine prefix or installed Proton build is modified.
