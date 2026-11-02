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
print(f'PASS: all {len(required)} requested package symbols survived defconfig; only W1701K is selected')
