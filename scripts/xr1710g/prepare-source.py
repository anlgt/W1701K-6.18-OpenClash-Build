#!/usr/bin/env python3
"""Narrow, fail-closed changes to the pinned, successfully built XR1710G tree.
No kernel/mt76 patches are removed, reordered, ignored or imported from another tree.
"""
import json
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
assert subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip() == 'ba2d9bc4f3bd3ab731efb16e62d76cff0651e17c'

def replace(path, old, new, count=1):
    p = root / path
    s = p.read_text()
    if s.count(old) != count:
        raise SystemExit(f'{path}: expected {count} occurrences of {old!r}, found {s.count(old)}')
    p.write_text(s.replace(old, new))

# Propagate the first download sub-make failure instead of returning only the last.
replace('include/toplevel.mk', '$(SUBMAKE) $(dir);)', '$(SUBMAKE) $(dir) || exit 1;)')

# Keep the established UBI2 compatibility contract, without touching flash layout.
replace('target/linux/airoha/image/an7581.mk',
        '  DEVICE_DTS := an7581-xr1710g-ubi\n',
        '  DEVICE_DTS := an7581-xr1710g-ubi\n'
        '  DEVICE_COMPAT_VERSION := 2.0\n'
        '  DEVICE_COMPAT_MESSAGE := The XR1710G BMT/BBT boundary has changed. Install an XR1710G chainloader/U-Boot using the new layout first, then boot recovery/initramfs and fully recreate UBI. A normal sysupgrade that preserves configuration is unsafe.\n')
replace('target/linux/airoha/an7581/base-files/etc/board.d/05_compat-version',
        '\tgemtek,w1700k-ubi)', '\tgemtek,xr1710g-ubi|\\\n\tgemtek,w1700k-ubi)')
# Run the upstream FIT validator for this board, as well as metadata validation.
replace('target/linux/airoha/an7581/base-files/lib/upgrade/platform.sh',
        '\n\tgemtek,xg2010g-ubi|\\\n', '\n\tgemtek,xr1710g-ubi|\\\n\tgemtek,xg2010g-ubi|\\\n', count=1)
# Match installed firmware protection; factory provisioning is never a user feature.
p = root / 'target/linux/airoha/dts/an7581-xr1710g-ubi.dts'
s = p.read_text()
start = s.index('\t\t\t/*\n\t\t\t * Intentionally NOT marked read-only')
end = s.index('\t\t\t */', start) + len('\t\t\t */')
p.write_text(s[:start] + '\t\t\tread-only;' + s[end:])

# Preserve the reference's matched SoC UI, with only the requested SoC/NPU page.
app = root / 'package/luci-app-airoha'
p = app / 'Makefile'
s = p.read_text()
s = '\n'.join(line for line in s.split('\n') if '$(INSTALL_' not in line or ('airoha_flowsense' not in line and 'npu-jitter' not in line and 'npu-monitor' not in line))
s = s.replace('Status & FlowSense', 'SoC / NPU Status')
p.write_text(s)
p = app / 'root/usr/share/luci/menu.d/luci-app-airoha.json'
menu = json.loads(p.read_text())
assert 'admin/status/airoha/flowsense' in menu
del menu['admin/status/airoha/flowsense']
p.write_text(json.dumps(menu, indent=2) + '\n')
p = app / 'root/usr/share/rpcd/acl.d/luci-app-airoha.json'
acl = json.loads(p.read_text())
for mode in ('read', 'write'):
    assert 'luci.airoha_flowsense' in acl['luci-app-airoha'][mode]['ubus']
    del acl['luci-app-airoha'][mode]['ubus']['luci.airoha_flowsense']
acl['luci-app-airoha']['description'] = 'Grant access to Airoha SoC / NPU status and controls'
p.write_text(json.dumps(acl, indent=2) + '\n')
# Remove the optional ping-monitor service's maintainer-script side effects.
replace('package/luci-app-airoha/Makefile', '/etc/init.d/npu-jitter enable 2>/dev/null\n/etc/init.d/npu-jitter start 2>/dev/null\n', '')
replace('package/luci-app-airoha/Makefile', '/etc/init.d/npu-jitter stop 2>/dev/null\n/etc/init.d/npu-jitter disable 2>/dev/null\n', '')
replace('package/luci-app-airoha/Makefile', '/etc/config/npu-monitor\n', '')

# Preserve reference Wi-Fi, region and initial login defaults as requested.

# Fail closed when the fan sensor is absent; never guess hwmon5 and write to it.
for name in ('package/luci-app-airoha-fancontrol/root/etc/init.d/fan',
             'package/luci-app-airoha-fancontrol/root/usr/libexec/rpcd/luci.fan',
             'target/linux/airoha/an7581/base-files/etc/init.d/airoha_fan'):
    p = root / name
    s = p.read_text()
    lines = [line for line in s.splitlines() if 'echo "/sys/class/hwmon/hwmon5"' in line]
    assert len(lines) == 1
    s = s.replace(lines[0], '\treturn 1')
    if name.endswith('/airoha_fan'):
        s = s.replace('hwmon=$(find_nct7802)', 'hwmon=$(find_nct7802) || return 1')
    p.write_text(s)

# Source preflight: preserve native patch machinery and hardware stack.
assert 'exit 1' in (root / 'scripts/patch-kernel.sh').read_text()
assert 'Recovered' not in (root / 'scripts/patch-kernel.sh').read_text()
assert 'LINUX_VERSION-6.18 = .52' in (root / 'target/linux/generic/kernel-6.18').read_text()
assert 'PKG_SOURCE_VERSION:=be5ce7910521492d4a2e4ce7ee3843680a46c047' in (root / 'package/kernel/mt76/Makefile').read_text()
print('Pinned source preparation passed; kernel/MT76 patch sets unchanged')
