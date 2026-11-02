#!/usr/bin/env python3
"""Reject dependencies or obsolete package symbols silently dropped by defconfig."""
import sys
from pathlib import Path

resolved = set(Path(sys.argv[1]).read_text().splitlines())
seed = Path(sys.argv[2]).read_text().splitlines()
required = [s for s in seed if s.startswith('CONFIG_PACKAGE_') and s.endswith('=y')]
missing = [s for s in required if s not in resolved]
if missing:
    raise SystemExit('Required components were lost during dependency resolution:\n' + '\n'.join(missing))
selected = sorted(s for s in resolved if s.startswith('CONFIG_TARGET_') and '_DEVICE_' in s and s.endswith('=y'))
if selected != ['CONFIG_TARGET_airoha_an7581_DEVICE_gemtek_w1701k=y']:
    raise SystemExit('Unexpected device selection: ' + repr(selected))
# The current Airoha tree links these drivers into vmlinux instead of exposing
# the vendor tree's former kmod packages. Verify the capability, not stale names.
kernel = set(Path('target/linux/airoha/an7581/config-6.18').read_text().splitlines())
for feature in ('CONFIG_NET_AIROHA=y', 'CONFIG_NET_AIROHA_NPU=y',
                'CONFIG_NET_DSA_MT7530=y', 'CONFIG_NET_DSA_MT7530_MMIO=y'):
    if feature not in kernel:
        raise SystemExit('Required built-in driver is missing: ' + feature)
print(f'PASS: all {len(required)} requested package symbols survived defconfig; only W1701K is selected')
print('PASS: Airoha Ethernet/NPU and MT7530/MMIO are built-in kernel drivers')
