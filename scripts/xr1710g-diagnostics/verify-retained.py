#!/usr/bin/env python3
"""Focused diagnostic recheck of ONE retained image; never promotes a candidate."""
import contextlib
import datetime
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import urllib.request
import zlib

IMAGE_SHA = '0dbdc719652a5cd25d387a61026ea61ede27066cfb046e71bf10f92b8c703e63'
BUILD_SHA = '59bb0553fa3bed5d55570914a338a6c48ad5be09'
SOURCE_SHA = 'ba2d9bc4f3bd3ab731efb16e62d76cff0651e17c'
SOURCE_URL = 'https://github.com/naoki66/ImmortalWrt-for-Gemtek-brightspeed.git'
MIHOMO_URL = 'https://github.com/MetaCubeX/mihomo/releases/download/v1.19.30/mihomo-linux-arm64-v1.19.30.gz'
MIHOMO_SHA = '58896873736d28628f66de3677c8654fa0f180662523148e136cff4f6e890069'
WARNING = '''UNVALIDATED DIAGNOSTIC IMAGE. DO NOT FLASH.
This is the unchanged image from failed validation run 37091448542, attempt 1.
Its focused retained-image checks do not constitute the full candidate gate.
The original final kernel.config and compiled PCS source were not retained.
Full kernel/profile isolation and complete build provenance cannot be rechecked.
The required replacement full build and its complete evidence remain pending.
No device boot, upgrade, WAN, Wi-Fi, thermal, persistence or recovery test ran.
Passing this diagnostic workflow does not change these limitations.
Transfer names candidate.tar/candidate.partNN are inherited from the generic
transfer utility; their contents remain UNVALIDATED DIAGNOSTIC throughout.
'''
BASE = Path.cwd()
OUT = BASE / 'output'
RECORD = OUT / 'diagnostic-record'
WORK = BASE / '.xr-retained-work'
ROOT = WORK / 'rootfs'
HELPERS = BASE / 'scripts/xr1710g'
RESULTS = []


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(*args, env=None, timeout=180):
    args = [str(x) for x in args]
    print('+', ' '.join(args))
    result = subprocess.run(args, env=env, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout)
    print(result.stdout, end='')
    if result.returncode:
        raise RuntimeError(f'Command exited {result.returncode}')
    return result.stdout


def gate(name, fn):
    log = io.StringIO()
    try:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            value = fn()
        status, detail = 'passed', ''
    except Exception as exc:
        status, detail, value = 'failed', f'{type(exc).__name__}: {exc}', None
        log.write(detail + '\n')
    (RECORD / f'{name}.log').write_text(log.getvalue())
    RESULTS.append({'gate': name, 'status': status, 'detail': detail})
    print(f'{name}: {status}', flush=True)
    return status == 'passed', value


def one(directory, pattern):
    paths = sorted(directory.rglob(pattern))
    assert len(paths) == 1, f'Expected one {pattern}; found {len(paths)}'
    assert paths[0].is_file() and not paths[0].is_symlink()
    return paths[0]


def extract_metadata(image, retained):
    # Narrow parser for this pinned image's final, unsigned INFO trailer only.
    # fwtool CRC starts with ~0 and has no final complement; Python's does.
    data = image.read_bytes()
    assert len(data) >= 24, 'Missing metadata trailer'
    magic, crc, kind, pad, size = struct.unpack('>IIB3sI', data[-16:])
    assert magic == 0x46577830 and kind == 1 and pad == b'\0' * 3
    assert 24 <= size <= 30 * 1024 + 24 and size <= len(data)
    assert crc == (zlib.crc32(data[:-16]) ^ 0xffffffff), 'Metadata trailer CRC mismatch'
    assert data[-size:-size + 8] == b'\0' * 8, 'Unsupported metadata header'
    payload = data[-size + 8:-16]
    metadata = json.loads(payload)
    assert metadata == json.loads(retained.read_text()), 'Retained metadata differs from image'
    (RECORD / 'sysupgrade-metadata.json').write_bytes(payload)
    print('Pinned image INFO trailer/header/CRC and retained JSON comparison passed')


def fetch_reference():
    reference = WORK / 'reference'
    command('git', 'init', reference)
    command('git', '-C', reference, 'remote', 'add', 'origin', SOURCE_URL)
    command('git', '-C', reference, 'config', 'core.sparseCheckout', 'true')
    wifi = 'package/network/config/airoha-an7581-mt7996-board/files/etc/'
    paths = [wifi + 'board.d/03_wifi_defaults', wifi + 'uci-defaults/03_wireless',
             'scripts/check-gemtek-profile-isolation.sh']
    (reference / '.git/info/sparse-checkout').write_text('\n'.join('/' + p for p in paths) + '\n')
    command('git', '-C', reference, 'fetch', '--depth=1', '--filter=blob:none', 'origin', SOURCE_SHA)
    command('git', '-C', reference, 'checkout', '--detach', 'FETCH_HEAD')
    assert command('git', '-C', reference, 'rev-parse', 'HEAD').strip() == SOURCE_SHA
    for path in paths:
        source = reference / path
        destination = RECORD / 'pinned-source' / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return reference


def check_wifi(reference):
    prefix = reference / 'package/network/config/airoha-an7581-mt7996-board/files'
    for relative in ['etc/board.d/03_wifi_defaults', 'etc/uci-defaults/03_wireless']:
        assert (ROOT / relative).read_bytes() == (prefix / relative).read_bytes(), relative
    assert (ROOT / 'etc/uci-defaults/03_wireless').read_text().count("disabled='0'") == 3
    assert not (ROOT / 'etc/config/wireless').exists()


def check_image_contents():
    for relative in ['www/luci-static/resources/view/airoha_npu/status.js',
                     'www/luci-static/resources/view/fan/status.js']:
        assert (ROOT / relative).is_file(), relative
    for relative in ['www/luci-static/resources/view/airoha_flowsense',
                     'usr/libexec/rpcd/luci.airoha_flowsense', 'usr/libexec/npu-jitter-daemon',
                     'root/.ssh', 'etc/config/wireless']:
        assert not os.path.lexists(ROOT / relative), relative
    assert not list((ROOT / 'etc/dropbear').glob('dropbear_*_host_key'))
    assert not [p for p in (ROOT / 'etc/openclash/config').rglob('*') if p.is_file()]
    assert 'gemtek,xr1710g-ubi' in (ROOT / 'etc/board.d/05_compat-version').read_text()
    assert os.access(ROOT / 'usr/bin/xr1710g-link-report', os.X_OK)
    info = (ROOT / 'etc/xr1710g-build-info').read_text()
    for expected in [f'build_definition={BUILD_SHA}', f'source_commit={SOURCE_SHA}', 'kernel=6.18.52']:
        assert expected in info.splitlines(), expected
    (RECORD / 'image-build-info.txt').write_text(info)


def check_migration():
    actual = ROOT / 'etc/uci-defaults/22_airoha-network-migrate-v4'
    assert actual.read_bytes() == (BASE / 'xr1710g-files/etc/uci-defaults/22_airoha-network-migrate-v4').read_bytes()
    command('sh', '-n', actual)
    wrapper = WORK / 'uci-wrapper'
    wrapper.write_text('''#!/bin/sh
mkdir -p "$XR_MIGRATION_ROOT/tmp/uci-deltas"
exec qemu-aarch64 -L "$XR_TEST_FIRMWARE_ROOT" "$XR_TEST_FIRMWARE_ROOT/sbin/uci" \\
  -c "$XR_MIGRATION_ROOT/etc/config" -t "$XR_MIGRATION_ROOT/tmp/uci-deltas" "$@"
''')
    wrapper.chmod(0o755)
    env = dict(os.environ, XR_TEST_FIRMWARE_ROOT=str(ROOT), XR_TEST_UCI_WRAPPER=str(wrapper),
               XR_TEST_MIGRATION_SCRIPT=str(actual))
    command('python3', HELPERS / 'test_migration.py', env=env)


def check_frpc():
    binary = ROOT / 'usr/bin/frpc'
    assert 'ARM aarch64' in command('file', binary)
    assert command('qemu-aarch64', '-L', ROOT, binary, '--version').strip() == '0.70.1'
    fixture = WORK / 'frpc-verify.toml'
    fixture.write_text('serverAddr = "127.0.0.1"\nserverPort = 7000\n')
    # verify only parses this isolated fixture; it never starts a client.
    command('qemu-aarch64', '-L', ROOT, binary, 'verify', '-c', fixture)


def check_mihomo():
    core = ROOT / 'etc/openclash/core/clash_meta'
    assert os.access(core, os.X_OK)
    assert 'ARM aarch64' in command('file', core)
    with urllib.request.urlopen(MIHOMO_URL, timeout=60) as response:
        data = response.read(40 * 1024 * 1024 + 1)
    assert len(data) <= 40 * 1024 * 1024, 'Unexpected Mihomo archive size'
    assert hashlib.sha256(data).hexdigest() == MIHOMO_SHA
    assert gzip.decompress(data) == core.read_bytes(), 'Image Mihomo differs from pinned release'
    print(f'Pinned gzip SHA256: {MIHOMO_SHA}\nImage core SHA256: {sha(core)}')


def main():
    RECORD.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(exist_ok=True)
    (OUT / 'UNVALIDATED-DIAGNOSTIC-READ-ME.txt').write_text(WARNING)
    (OUT / 'firmware').mkdir(exist_ok=True)
    (RECORD / 'verifier-source').mkdir(exist_ok=True)
    for path in [*HELPERS.glob('*.py'), *HELPERS.glob('*.sh'), Path(__file__),
                 BASE / '.github/workflows/verify-xr1710g-retained.yml',
                 BASE / '.github/workflows/build-xr1710g-candidate.yml']:
        shutil.copy2(path, RECORD / 'verifier-source' / path.name)

    def select_image():
        image = one(BASE / 'incoming/image', '*gemtek_xr1710g-ubi-squashfs-sysupgrade.itb')
        assert sha(image) == IMAGE_SHA, 'Retained image hash mismatch'
        manifest = one(BASE / 'incoming/image', '*gemtek_xr1710g-ubi.manifest')
        shutil.copy2(image, OUT / 'firmware' / image.name)
        shutil.copy2(manifest, OUT / 'firmware' / manifest.name)
        print(f'Image SHA256: {IMAGE_SHA}')
        return image, manifest

    image_ok, inputs = gate('01-image-identity', select_image)
    def collect_records():
        for name in ['source-changes.patch', 'resolved.config', 'resolved.diffconfig', 'sysupgrade-metadata.json']:
            shutil.copy2(one(BASE / 'incoming/logs', name), RECORD / ('original-' + name))
    records_ok, _ = gate('02-retained-records', collect_records)
    ref_ok, reference = gate('03-pinned-reference-source', fetch_reference)
    if records_ok:
        gate('04-resolved-config', lambda: command('python3', HELPERS / 'verify-config.py', RECORD / 'original-resolved.config'))
    if image_ok:
        image, manifest = inputs
        gate('05-manifest', lambda: command('python3', HELPERS / 'verify-config.py', manifest, '--manifest'))
        metadata_ok, _ = gate('06-metadata-trailer', lambda: extract_metadata(image, RECORD / 'original-sysupgrade-metadata.json'))
        fit_ok = False
        if metadata_ok:
            fit_ok, _ = gate('07-fit-dtb-payloads', lambda: command('python3', HELPERS / 'verify-fit.py', image, WORK / 'fit', RECORD / 'sysupgrade-metadata.json'))
        if fit_ok:
            for name in ['fit-validation.json', 'device.dtb']:
                shutil.copy2(WORK / 'fit' / name, RECORD / name)
            root_ok, _ = gate('08-data-only-extraction', lambda: command('unsquashfs', '-excludes', '-d', ROOT, WORK / 'fit/rootfs.squashfs', 'dev'))
            if root_ok:
                gate('09-requested-apps-frp-defaults', lambda: command('python3', HELPERS / 'verify-apps.py', ROOT))
                gate('10-config-generate', lambda: command('python3', HELPERS / 'verify-network-defaults.py', env=dict(os.environ, XR_CONFIG_GENERATE_SOURCE=str(ROOT / 'bin/config_generate'))))
                gate('11-real-uci-migration', check_migration)
                gate('12-frpc-qemu-loader', check_frpc)
                gate('13-mihomo-pinned-bytes', check_mihomo)
                gate('14-image-contents-build-identity', check_image_contents)
                if ref_ok:
                    gate('15-reference-wifi', lambda: check_wifi(reference))
        if records_ok and ref_ok:
            gate('16-profile-config-manifest-only', lambda: command('bash', reference / 'scripts/check-gemtek-profile-isolation.sh', '--config', RECORD / 'original-resolved.config', '--manifest', manifest))

    # Deliberately NOT a passed/skipped gate: absent compiled evidence stays incomplete.
    RESULTS.append({'gate': '17-final-kernel-profile-and-compiled-source-provenance',
                    'status': 'incomplete', 'detail': 'Original final kernel.config and compiled PCS source were not retained. Replacement full build required; never inferred from source pins or resolved.config.'})
    report = {'classification': 'UNVALIDATED DIAGNOSTIC; DO NOT FLASH',
              'complete_candidate_validation': False, 'source_run_id': 37091448542,
              'source_run_attempt': 1, 'image_artifact_id': 11263974621,
              'logs_artifact_id': 11264109268, 'original_build_definition': BUILD_SHA,
              'verifier_definition': os.environ.get('GITHUB_SHA'), 'source_commit': SOURCE_SHA,
              'expected_image_sha256': IMAGE_SHA, 'generated_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'checks': RESULTS, 'hardware_validation': 'NOT RUN'}
    # Gates not reached must be visible, not silently counted as successes.
    performed = {item['gate'].split('-')[0] for item in RESULTS}
    report['not_reached_gate_numbers'] = [f'{i:02}' for i in range(1, 17) if f'{i:02}' not in performed]
    (RECORD / 'diagnostic-report.json').write_text(json.dumps(report, indent=2) + '\n')
    text = WARNING + '\n' + '\n'.join(f"{r['gate']}: {r['status']} {r['detail']}" for r in RESULTS) + '\n'
    (RECORD / 'diagnostic-summary.txt').write_text(text)
    hashes = [f'{sha(p)}  {p.relative_to(OUT)}' for p in sorted(OUT.rglob('*')) if p.is_file()]
    (OUT / 'SHA256SUMS').write_text('\n'.join(hashes) + '\n')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as dest:
            dest.write(text)
    print(text)
    return int(any(r['status'] == 'failed' for r in RESULTS) or bool(report['not_reached_gate_numbers']))


if __name__ == '__main__':
    sys.exit(main())
