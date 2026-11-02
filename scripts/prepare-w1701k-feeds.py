#!/usr/bin/env python3
"""Exclude two unselected optional feed menus with recursive Kconfig dependencies."""
from pathlib import Path

# These unrelated applications are absent from both firmware configurations.
# Their optional menus currently produce Kconfig self-dependencies even when
# unselected. Remove only their installed feed links, never hardware sources.
excluded = ('applications/luci-app-fwknopd', 'sound/squeezelite')
for group in Path('package/feeds').iterdir():
    if not group.is_dir():
        continue
    for entry in group.iterdir():
        if entry.is_symlink() and any(entry.resolve().as_posix().endswith('/' + p) for p in excluded):
            print('Excluding unused optional feed menu:', entry)
            entry.unlink()
