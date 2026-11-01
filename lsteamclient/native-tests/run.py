#!/usr/bin/env python3
"""Compile host tests against extracted initialization and matchmaking functions."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def function(source, signature):
    start = source.index(signature)
    opening = source.index('{', start)
    tokens = re.compile(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.S)
    masked = tokens.sub(lambda m: ' ' * len(m.group()), source)
    depth = 0
    for i in range(opening, len(source)):
        if masked[i] == '{':
            depth += 1
        elif masked[i] == '}':
            depth -= 1
            if not depth:
                return source[start:i + 1]
    raise ValueError('Unterminated function: ' + signature)


def policy(source):
    callbacks = ('Steam_BGetCallback', 'Steam_FreeLastCallback', 'Steam_GetAPICallResult')
    ordinary = ('CreateInterface', 'Steam_ReleaseThreadLocalMemory', 'Steam_IsKnownInterface',
                'Steam_NotifyMissingInterface', 'steamclient_init_registry')
    for name in callbacks + ordinary:
        match = re.search(r'^[^\n]*\b' + name + r'\([^;{]*?\)\s*\{', source, re.M | re.S)
        if not match:
            raise AssertionError('Missing entry point: ' + name)
        body = function(source, source[match.start():match.end() - 1])
        wanted = 'FALSE' if name in callbacks else 'TRUE'
        assert re.findall(r'load_steamclient\((TRUE|FALSE)\)', body) == [wanted], name
    print('Call-site policy: 3 cached callbacks, 5 synchronizing entry points')


def run(command, **kwargs):
    print('+ ' + ' '.join(map(str, command)), flush=True)
    subprocess.run(command, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Keep generated source and binaries here')
    parser.add_argument('--sanitize', choices=('address', 'thread'))
    parser.add_argument('--benchmark', action='store_true')
    args = parser.parse_args()
    output = args.output or Path(tempfile.mkdtemp(prefix='lsteamclient-init-'))
    output.mkdir(parents=True, exist_ok=True)
    pe = (ROOT / 'steamclient_main.c').read_text()
    unix = (ROOT / 'unixlib.cpp').read_text()
    header = (ROOT / 'unixlib.h').read_text()
    matchmaking = (ROOT / 'steam_matchmaking_manual.c').read_text()
    signatures = re.findall(r'^void \* __thiscall (winISteamMatchmakingServers_\w+_Request\w+ServerList)\(', matchmaking, re.M)
    assert len(signatures) == 12
    matchmaking_functions = '\n\n'.join(function(matchmaking, signature) for signature in (
        'static struct w_request *alloc_w_request(', 'static void free_w_request(',
        'static struct w_request *get_w_request('))
    declarations, creators = [], []
    for i, name in enumerate(signatures):
        body = function(matchmaking, 'void * __thiscall ' + name + '(')
        matchmaking_functions += '\n\n' + body
        param_name = re.search(r'struct (ISteamMatchmakingServers_\w+_params) params', body).group(1)
        declarations.append('REQUEST_PARAMS(' + param_name + ')')
        arguments = '&iface, 42, NULL' if '_RequestLANServerList' in name else '&iface, 42, NULL, 0, NULL'
        creators.append('static void *create_%d(void) { return %s(%s); }' % (i, name, arguments))
    creators.append('static void *(*const creators[])(void) = {' + ', '.join('create_' + str(i) for i in range(len(signatures))) + '};')
    request = re.search(r'^#define W_REQUEST_MAGIC .*$', header, re.M).group() + '\n'
    request += function(header, 'struct w_request\n') + ';'
    policy(pe)
    params = re.search(r'struct steamclient_init_params\s*\{.*?\};', header, re.S).group()
    pe_functions = '\n\n'.join(function(pe, signature) for signature in (
        'static BOOL get_env_win(', 'static int init_steamclient(', 'static int load_steamclient('))
    unix_functions = function(unix, 'static void sync_env_var(') + '\n\ntemplate< typename Params >\n'
    unix_functions += function(unix, 'static NTSTATUS steamclient_init( Params *params, bool wow64 )')
    for name, source in (('steamclient_main.c', pe), ('unixlib.cpp', unix), ('unixlib.h', header)):
        print(f'{name}: {hashlib.sha256(source.encode()).hexdigest()}')
    for name, extension, functions, compiler in (
        ('pe-init', 'c', pe_functions, os.environ.get('CC', 'cc')),
        ('unix-init', 'cpp', unix_functions, os.environ.get('CXX', 'c++')),
        ('matchmaking', 'c', matchmaking_functions, os.environ.get('CC', 'cc'))):
        template = (ROOT / 'native-tests' / f'{name}.{extension}.in').read_text()
        generated = template.replace('@PARAMS@', params).replace('@FUNCTIONS@', functions)
        generated = generated.replace('@REQUEST@', request).replace('@DECLARATIONS@', '\n'.join(declarations))
        generated = generated.replace('@CREATORS@', '\n'.join(creators))
        src = output / f'{name}.{extension}'
        src.write_text(generated)
        binary = output / name
        command = shlex.split(compiler) + ['-std=gnu11' if extension == 'c' else '-std=c++17', '-O2', '-g',
                   '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', '-pthread', str(src), '-o', str(binary)]
        if args.sanitize:
            sanitizer = 'address,undefined' if args.sanitize == 'address' else 'thread'
            command += ['-fsanitize=' + sanitizer, '-fno-omit-frame-pointer']
        run(command)
        run([str(binary)] + (['--benchmark'] if args.benchmark and name == 'pe-init' else []), timeout=45)
    print('Generated artifacts: ' + str(output))


if __name__ == '__main__':
    main()
