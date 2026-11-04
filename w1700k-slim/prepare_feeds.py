#!/usr/bin/env python3
"""Exclude one unused pinned feed entry whose Kconfig is recursive.

Run after feeds install -a and before defconfig. Only unlink the verified
package/feeds/packages/squeezelite entry; never edit or delete feed source.
"""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


PACKAGES_COMMIT = '349c2ca5c8a058b30d42c537faa4c9e94e997106'
SQUEEZELITE_MAKEFILE_SHA256 = '2502c1809fc6b32be93ee50e2eb8ec4d81cd9c2905387646352604d85719a22e'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_selection(config):
    selected = re.findall(r'^CONFIG_((?:PACKAGE_squeezelite[^=\s]*|SQUEEZELITE_[^=\s]*))=(?:y|m)$', config, re.M)
    require(not selected, 'Cannot exclude selected squeezelite components: ' + ', '.join(selected))


def inspect_entry(root, config):
    check_selection(config)
    root = root.resolve(strict=True)
    feed = root / 'feeds/packages'
    target = feed / 'sound/squeezelite'
    require(feed.resolve(strict=True).is_relative_to(root), 'Packages feed escapes source tree')
    require(target.resolve(strict=True).is_relative_to(feed.resolve()), 'Squeezelite source escapes pinned feed')
    makefile = target / 'Makefile'
    digest = hashlib.sha256(makefile.read_bytes()).hexdigest()
    require(digest == SQUEEZELITE_MAKEFILE_SHA256, 'Squeezelite Makefile differs from reviewed pin')
    link = root / 'package/feeds/packages/squeezelite'
    require(link.parent.resolve(strict=True).is_relative_to(root), 'Package link parent escapes source tree')
    if link.is_symlink():
        require(link.resolve(strict=True) == target.resolve(strict=True), 'Squeezelite link points to an unexpected directory')
    else:
        require(not link.exists(), 'Refusing to remove a real squeezelite directory or file')
    return link, digest


def prepare(root, config, apply=False):
    feed = root / 'feeds/packages'
    head = subprocess.check_output(['git', '-C', str(feed), 'rev-parse', 'HEAD'], text=True).strip()
    require(head == PACKAGES_COMMIT, 'Unexpected packages feed commit: ' + head)
    link, digest = inspect_entry(root, config)
    present = link.is_symlink()
    if apply and present:
        link.unlink()
    return {'mode': 'applied' if apply else 'check-only', 'feed_commit': head,
            'excluded_entry': 'package/feeds/packages/squeezelite',
            'makefile_sha256': digest, 'link_was_present': present,
            'feed_source_modified': False,
            'reason': 'Unused squeezelite-custom Kconfig has PACKAGE_squeezelite-custom / SQUEEZELITE_WMA_ALAC dependency cycle'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--config', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.config.read_text(encoding='utf-8'), args.apply), indent=2))
