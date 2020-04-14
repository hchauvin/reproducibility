#!/usr/bin/env python3

# SPDX-License-Identifier: MIT
# Copyright (c) 2020 Hadrien Chauvin
"""Assess the reproducibility of a build rule."""

import sys
import argparse
import subprocess
import os
import hashlib
import zipfile
import json
from collections import ChainMap


def digest_files(files):
    """
    Digests a list of files and directories.

    The directories are processed recursively.

    Args:
        files: A list of file paths.

    Return:
        A dictionary of file name to hex digests.
    """
    digests = {}
    for file in files:
        if os.path.islink(file):
            digests = {**digests, file: 'symlink=' + os.readlink(file)}
        elif os.path.isdir(file):
            digests = {
                **digests,
                **digest_files(
                    [os.path.join(file, name) for name in os.listdir(file)])
            }
        else:
            digests = {**digests, file: 'sha256=' + _digest_file(file)}
    return digests


def _digest_file(file):
    """
    Digests a single file.

    Args:
        file: The path to the file to digest.

    Return:
        A hex digest (a string).
    """
    BUF_SIZE = 65536

    m = hashlib.sha256()
    with open(file, 'rb') as f:
        while True:
            buf = f.read(BUF_SIZE)
            if not buf:
                break
            m.update(buf)

    return m.hexdigest()


def digest_archive(archive):
    """Digest each entry in an archive separately."""
    if archive.endswith(".zip") or archive.endswith(".jar") or archive.endswith(
            ".war"):
        return _digest_zip_archive(archive)
    else:
        raise Exception(f"{archive} has an unsupported archive format")


def _digest_zip_archive(archive):
    digests = {}
    with zipfile.ZipFile(archive, 'r') as ar:
        infolist = ar.infolist()
        digests[f'{archive}#namelist'] = _digest_json(
            [info.filename for info in infolist])
        for info in ar.infolist():
            digests[f'{archive}#{info.filename}#date_time'] = _digest_json(
                info.date_time)
            with ar.open(info.filename, 'r') as f:
                BUF_SIZE = 65536
                m = hashlib.sha256()
                while True:
                    buf = f.read(BUF_SIZE)
                    if not buf:
                        break
                    m.update(buf)
                digests[f'{archive}#{info.filename}'] = m.hexdigest()
    return digests


def _digest_string(s):
    """
    Digests a string.

    Args:
        s: The string to digest.

    Return:
        A hex digest (a string).
    """
    m = hashlib.sha256()
    m.update(s.encode('utf8'))
    return m.hexdigest()


def _digest_json(o):
    return _digest_string(json.dumps(o, sort_keys=True))


def compare_digests(digests1, digests2):
    """
    Compares two dictionaries of digests, as produced by `digest_files`.

    Args:
        digests1: First dictionary of digests.
        digests2: Second dictionary of digests.

    Return:
        A sorted list of all the files with different digests.
    """
    differences = []
    all_keys = set().union(digests1.keys(), digests2.keys())
    for key in all_keys:
        if digests1.get(key) != digests2.get(key):
            differences.append(key)
    differences.sort()
    return differences


def test_reproducibility(func, output_files, output_archives):
    """
    Tests the reproducibility of a function by looking at whether
    the content of its output files change between invocations.

    Args:
        func: The function to invoke.  It takes no argument.
        output_files: A list of paths to output files and directories that
            are produced by the function.  Directories are processed
            recursively.
        output_archives: A list of paths to output archives that are produced
            by the function.  Each entry in the archive is compared separately,
            in addition to the comparison on the archive itself.

    Return:
        A sorted list of all the files with digests that differ between
        the two invocations.
    """

    def digest_outputs():
        return ChainMap(
            digest_files(output_files + output_archives),
            *[digest_archive(ar) for ar in output_archives])

    func()
    digests1 = digest_outputs()
    func()
    digests2 = digest_outputs()
    return compare_digests(digests1, digests2)


class CLI:
    """
    Command-Line Interface.
    """

    def __init__(self):
        parser = argparse.ArgumentParser(
            description='Make', usage="make <command> [<args>]")
        subcommands = [
            attr for attr in dir(self)
            if not attr.startswith("_") and callable(getattr(self, attr))
        ]
        parser.add_argument(
            'command',
            help='Subcommand to run: one of: ' + " ".join(subcommands))
        args = parser.parse_args(sys.argv[1:2])
        if not hasattr(self, args.command):
            print('Unrecognized command')
            parser.print_help()
            exit(1)
        getattr(self, args.command)()

    def test(self):
        parser = argparse.ArgumentParser(
            description='Test reproducibility by running twice a command')
        parser.add_argument(
            '-f',
            '--file',
            action='append',
            help='file or directory produced by the command')
        parser.add_argument(
            '-ar',
            '--archive',
            action='append',
            help='archive produced by the command (all the ' +
            'files in the archive will be compared separately, ' +
            'in addition to a comparison for the archive itself)')
        parser.add_argument('command', help='the command to run')
        parser.add_argument(
            'args', nargs=argparse.REMAINDER, help='arguments to the command')
        args = parser.parse_args(sys.argv[2:])

        def func():
            subprocess.run([args.command] + args.args, check=True)

        differences = test_reproducibility(
            func,
            output_files=args.file or [],
            output_archives=args.archive or [])
        if len(differences) == 0:
            print("The command is reproducible!")
        else:
            print("The command is not reproducible: the following files are " +
                  "produced differently")
            print("by the second invocation:")
            for file in differences:
                print(f"    {file}")


if __name__ == "__main__":
    try:
        CLI()
    except KeyboardInterrupt as e:
        print("Interrupted")
        sys.exit(1)
