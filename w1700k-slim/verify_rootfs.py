#!/usr/bin/env python3
"""Verify non-secret files and package metadata from the actual built rootfs."""
import hashlib
import json
import re
import sys
from pathlib import Path

if not __debug__:
    raise RuntimeError('This gate must run without Python optimization')

from verify_config import check_packages

root, source, output = map(Path, sys.argv[1:])
packages={}
for block in (root/'lib/apk/db/installed').read_text().split('\n\n'):
    fields={}
    for line in block.splitlines():
        if len(line)>1 and line[1]==':' and line[0] in ('P','V','D'): fields[line[0]]=line[2:]
    if 'P' in fields: packages[fields['P']]=fields
check_packages(set(packages))
assert packages['kernel']['V'].startswith('6.18.55~')
kernel=packages['kernel']['V']
kernel_base=kernel.rsplit('-r',1)[0]
for name, fields in packages.items():
    if name.startswith('kmod-'):
        deps=[d for d in fields.get('D','').split() if d.startswith('kernel=')]
        assert len(deps)==1 and deps[0][7:] in (kernel,kernel_base), (name,deps,kernel)
required_files=['www/luci-static/resources/view/airoha_npu/status.js',
    'www/luci-static/resources/view/fan/status.js', 'usr/libexec/rpcd/luci.airoha_npu',
    'usr/libexec/rpcd/luci.fan', 'etc/init.d/fan', 'etc/init.d/airoha_fan',
    'etc/openclash/core/clash_meta','etc/uci-defaults/99-w1700k-slim']
for path in required_files: assert (root/path).is_file(), path
assert 'setOverclock' in (root/'usr/libexec/rpcd/luci.airoha_npu').read_text()
assert 'setOverclock' in (root/'www/luci-static/resources/view/airoha_npu/status.js').read_text()
assert not (root/'etc/vermagic.txt').exists(), 'Injected external ABI value'
feed=(root/'etc/apk/repositories.d/distfeeds.list').read_text()
assert not [l for l in feed.splitlines() if l.strip() and not l.lstrip().startswith('#')], 'Unverified public snapshot feed'
for path in ('lib/firmware/airoha/en7581_npu_data.bin','lib/firmware/airoha/en7581_npu_rv32.bin','root/.ssh','etc/config/wireless','usr/libexec/npu-jitter-daemon',
             'usr/libexec/rpcd/luci.airoha_flowsense','www/luci-static/resources/view/airoha_flowsense'):
    assert not (root/path).exists(), path
assert not list((root/'etc/dropbear').glob('dropbear_*_host_key'))
assert not any(p.is_file() for p in (root/'etc/openclash/config').glob('*'))
for path in root.rglob('*'):
    assert not re.search(r'(^|[-_.])frp[cs]?($|[-_.])',path.name), f'FRP file remains: {path.relative_to(root)}'
for path, src in [
    ('etc/init.d/fan','package/luci-app-w1700k-fancontrol/root/etc/init.d/fan'),
    ('etc/init.d/airoha_fan','target/linux/airoha/an7581/base-files/etc/init.d/airoha_fan'),
    ('usr/libexec/rpcd/luci.fan','package/luci-app-w1700k-fancontrol/root/usr/libexec/rpcd/luci.fan'),
    ('lib/wifi/mac80211.uc','package/network/config/wifi-scripts/files/lib/wifi/mac80211.uc')]:
    assert (root/path).read_bytes()==(source/src).read_bytes(), f'Unexpected modification: {path}'
    if 'fan' in path: assert 'echo "/sys/class/hwmon/hwmon5"' not in (root/path).read_text()
upnp=(root/'etc/config/upnpd').read_text()
assert re.search(r"option\s+enabled\s+['\"]?0['\"]?",upnp), 'UPnP unexpectedly enabled by default'
report={'packages':len(packages),'kernel':kernel,'required_files':required_files,
        'mihomo_sha256':hashlib.sha256((root/'etc/openclash/core/clash_meta').read_bytes()).hexdigest(),
        'frp_absent':True,'external_vermagic_absent':True,'unverified_feeds_disabled':True,
        'overclock':'manual UI only; no new startup tuning; runtime untested',
        'private_config_inspected':False,'hardware_validation':'NOT RUN'}
output.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
