#!/usr/bin/env bash
set -Eeuo pipefail
# Regression for non-root CI failing to recreate /dev/console. This creates
# only Squashfs metadata, never a host device node and never runs image code.
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/source/etc" "$tmp/source/dev"
printf 'fixture\n' > "$tmp/source/etc/fixture"
mksquashfs "$tmp/source" "$tmp/fixture.squashfs" -noappend -comp gzip \
  -no-progress -processors 1 -p 'dev/console c 0600 0 0 5 1' >/dev/null
unsquashfs -excludes -no-progress -d "$tmp/extracted" "$tmp/fixture.squashfs" dev >/dev/null
cmp "$tmp/source/etc/fixture" "$tmp/extracted/etc/fixture"
test ! -e "$tmp/extracted/dev"
echo 'Data-only Squashfs extraction regression passed without root privileges'
