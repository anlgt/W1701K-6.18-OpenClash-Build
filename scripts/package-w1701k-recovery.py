#!/usr/bin/env python3
"""Package only the immutable, successfully audited recovery candidates."""
import hashlib
import json
import os
import shutil
from pathlib import Path

root = Path('output')
record = root / 'build-record'
full = json.loads((record / 'full-image-audit.json').read_text())
lite = json.loads((record / 'lite-image-audit.json').read_text())
assert full['rootfs_dependencies'] == lite['rootfs_dependencies'] == 'passed'
assert full['kernel_config_sha256'] == lite['kernel_config_sha256']
assert full['supported_devices'] == ['gemtek,w1701k']
assert full['mihomo_runtime_version'] == '1.19.33'
assert lite['mihomo_runtime_version'] == 'not included'
packages = lite['package_versions']
assert len(packages) > 50, 'Lite installed package database is missing'
kernel = 'kernel - ' + packages['kernel']
assert kernel == (record / 'openclash-kernel-abi.txt').read_text().strip(), 'kernel ABI mismatch'
full_manifest, = (root / 'firmware').glob('*sysupgrade-openclash.manifest')
full_packages = dict(line.split(' - ', 1) for line in full_manifest.read_text().splitlines() if ' - ' in line)
assert {k: v for k, v in packages.items() if k.startswith('kmod-')} == {
    k: v for k, v in full_packages.items() if k.startswith('kmod-')}, 'actual module versions differ'
for name in ('luci-app-openclash', 'ruby', 'ruby-yaml', 'bash', 'dnsmasq-full'):
    assert name in full_packages and name not in packages
for name in ('curl', 'dnsmasq', 'irqbalance', 'wpad-openssl', 'luci-app-wifi7', 'luci-app-mlo'):
    assert name in packages
image, = Path('openwrt/bin/targets/airoha/an7581').glob('*gemtek_w1701k-initramfs-uImage.itb')
assert image.stat().st_size <= 20 * 1024 * 1024
assert hashlib.file_digest(image.open('rb'), 'sha256').hexdigest() == lite['image_sha256']
shutil.copy2(image, root / 'firmware' / image.name)
(root / 'firmware/openwrt-airoha-an7581-gemtek_w1701k-initramfs-lite.manifest').write_text(
    ''.join(f'{k} - {v}\n' for k, v in sorted(packages.items())))
(record / 'lite-ram-kernel-abi.txt').write_text(kernel + '\n')
for source in Path('recovery-diagnostics').rglob('*'):
    if source.is_file() and source.suffix in ('.config', '.diffconfig', '.diff'):
        shutil.copy2(source, record / source.name)
provenance = {
    'compiled_run': 41458182897,
    'compiled_commit': 'dc97b7732dc3939015ac08463a8a50514c525eb1',
    'source_commit': '778d561059fe01a527cf49451ef4de14f433e303',
    'audit_run': os.environ['GITHUB_RUN_ID'], 'audit_commit': os.environ['GITHUB_SHA'],
    'kernel_abi': kernel, 'actual_lite_package_count': len(packages),
    'full_image_sha256': full['image_sha256'], 'lite_image_sha256': lite['image_sha256'],
    'network_defaults': {'lan': '10.98.0.1/24', 'ssid': 'GT', 'country': 'CN', 'bands': ['2g', '5g']},
    'hardware_boot_test': 'not performed; RAM acceptance and sysupgrade -T required'
}
(record / 'recovery-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
files = sorted(p for d in ('firmware', 'build-record') for p in (root / d).rglob('*') if p.is_file())
assert len({p.name for p in files}) == len(files), 'duplicate release asset names'
lines = [f'{hashlib.file_digest(p.open("rb"), "sha256").hexdigest()}  {p.name}\n' for p in files]
(root / 'RELEASE-SHA256SUMS').write_text(''.join(lines))
print(f'PASS: {len(packages)} actual Lite packages; matching kernel ABI and kmod versions; both image hashes verified')
