#!/usr/bin/env python3
"""Reject unsafe paths or links in the private firmware configuration archive."""
import pathlib
import sys
import tarfile

allowed = ("etc/config/", "etc/openclash/")
required = {
    "etc/config/network", "etc/config/wireless", "etc/config/firewall",
    "etc/config/dhcp",
}

with tarfile.open(sys.argv[1], "r:gz") as archive:
    names = set()
    for member in archive.getmembers():
        path = pathlib.PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise SystemExit("Unsafe path in private config archive")
        if not member.isfile() and not member.isdir():
            raise SystemExit("Links and special files are forbidden")
        if member.isfile() and not member.name.startswith(allowed):
            raise SystemExit("Unexpected file in private config archive")
        names.add(member.name)
    if not required <= names:
        raise SystemExit("Private config archive is incomplete")

