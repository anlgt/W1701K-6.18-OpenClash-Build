#!/usr/bin/env python3
"""Reviewable, fail-closed W1700K-only changes; --check never edits source.

Never changes DTS, bootloader contents, radio stack, network/wireless credentials,
or another board profile. Does not fetch, push, publish, or run a firmware build.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

if not __debug__:
    raise RuntimeError('This gate must run without Python optimization')


PIN = '15490b469f68133da3d244881fb48dd5e42c1d87'

def plan(root):
    head = subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
    assert head == PIN, f'Wrong source commit: {head}'
    changes = {}
    def replace(path, old, new):
        before = changes.get(path, (root/path).read_text())
        assert before.count(old) == 1, f'{path}: expected exactly one original pattern'
        changes[path] = before.replace(old, new)

    # A downloaded value must never impersonate this custom kernel's actual ABI.
    replace('include/kernel-defaults.mk',
        '\t[ ! -f ../../../files/etc/vermagic.txt ] || cp ../../../files/etc/vermagic.txt $(LINUX_DIR)/.vermagic\n', '')
    # Stop at the first failed dependency-download submake.
    replace('include/toplevel.mk', '$(SUBMAKE) $(dir);)', '$(SUBMAKE) $(dir) || exit 1;)')
    # Activate the native additional FIT check for this board too.
    replace('target/linux/airoha/an7581/base-files/lib/upgrade/platform.sh',
        '\n\tnokia,xg-040g-md-ubi|\\\n',
        '\n\tgemtek,w1700k-ubi|\\\n\tnokia,xg-040g-md-ubi|\\\n')
    # This task builds only sysupgrade firmware, not new bootloader artifacts.
    replace('target/linux/airoha/image/an7581.mk',
        '  ARTIFACTS := chainload-uboot.itb\n  ARTIFACT/chainload-uboot.itb := an7581-chainloader gemtek_w1700k\n', '')
    # Never guess hwmon5 when the actual fan controller cannot be identified.
    fan_paths = [
        'package/luci-app-w1700k-fancontrol/root/etc/init.d/fan',
        'package/luci-app-w1700k-fancontrol/root/usr/libexec/rpcd/luci.fan',
        'target/linux/airoha/an7581/base-files/etc/init.d/airoha_fan',
    ]
    for path in fan_paths:
        text = (root/path).read_text()
        matches = [line for line in text.splitlines(True) if 'echo "/sys/class/hwmon/hwmon5"' in line]
        assert len(matches) == 1
        replace(path, matches[0], '\treturn 1\n')
    replace(fan_paths[2], '\t\thwmon=$(find_nct7802)\n', '\t\thwmon=$(find_nct7802) || return 1\n')
    replace(fan_paths[1], '\tcall)\n',
        '\tcall)\n\t\t[ -n "$HWMON" ] && [ -d "$HWMON" ] || { printf \'%s\\n\' \'{"error":"NCT7802 controller unavailable"}\'; exit 1; }\n')
    assert 'LINUX_VERSION-6.18 = .55' in (root/'target/linux/generic/kernel-6.18').read_text()
    assert '01367e60db433534ad0aa3d3b6c886de8cb7d44c' in (root/'package/kernel/mt76/Makefile').read_text()
    assert not (root/'files/etc/vermagic.txt').exists(), 'Unapproved ABI override overlay'
    return changes

if __name__ == '__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('source',type=Path)
    mode=ap.add_mutually_exclusive_group(required=True); mode.add_argument('--check',action='store_true'); mode.add_argument('--apply',action='store_true')
    args=ap.parse_args(); changes=plan(args.source)
    report=[]
    for path, text in changes.items():
        original=(args.source/path).read_bytes()
        report.append({'path':path,'before_sha256':hashlib.sha256(original).hexdigest(),'after_sha256':hashlib.sha256(text.encode()).hexdigest()})
        if args.apply: (args.source/path).write_text(text)
    print(json.dumps({'mode':'applied' if args.apply else 'check-only','source':PIN,'changes':report},indent=2))
