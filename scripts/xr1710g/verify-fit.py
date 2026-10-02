#!/usr/bin/env python3
"""Offline FIT payload hashes, compiled DTB layout, and sysupgrade metadata gate."""
import gzip
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path

def fdt(data):
    assert len(data) >= 40, 'Truncated FDT header'
    hdr = struct.unpack_from('>10I', data)
    assert hdr[0] == 0xd00dfeed and 40 <= hdr[1] <= len(data), 'Invalid/truncated FDT'
    off, strings = hdr[2:4]
    struct_end, string_end = off + hdr[9], strings + hdr[8]
    assert 40 <= off <= struct_end <= hdr[1]
    assert 40 <= strings <= string_end <= hdr[1]
    stack, nodes = [], {}
    while off + 4 <= struct_end:
        token, = struct.unpack_from('>I', data, off); off += 4
        if token == 1:
            end = data.index(0, off, struct_end)
            stack.append(data[off:end].decode()); off = (end + 4) & ~3
            path = '/'.join(stack) or '/'
            assert path not in nodes, 'Duplicate FDT node'
            nodes[path] = {}
        elif token == 2:
            assert stack, 'Unbalanced FDT nodes'
            stack.pop()
        elif token == 3:
            assert stack and off + 8 <= struct_end
            size, nameoff = struct.unpack_from('>II', data, off); off += 8
            assert strings + nameoff < string_end and off + size <= struct_end
            name = data[strings + nameoff:data.index(0, strings + nameoff, string_end)].decode()
            props = nodes['/'.join(stack) or '/']
            assert name not in props, 'Duplicate FDT property'
            props[name] = data[off:off + size]
            off = (off + size + 3) & ~3
        elif token == 9:
            assert not stack
            return hdr[1], nodes
        else: assert token == 4, f'Bad FDT token: {token}'
    raise AssertionError('Missing FDT end token')

def string(value): return value.rstrip(b'\0').decode()
def number(value): return int.from_bytes(value, 'big')

def inspect(image, out, metadata_path, expected_compat='2.0', require_ro=True):
    data = Path(image).read_bytes()
    total, nodes = fdt(data)
    results, payloads = {}, {}
    for name, props in nodes.items():
        if not name.startswith('/images/') or name.count('/') != 2: continue
        assert 'data-position' in props, f'{name}: expected external static FIT payload'
        pos, size = number(props['data-position']), number(props['data-size'])
        assert pos >= total and size > 0 and pos + size <= len(data)
        payload = data[pos:pos + size]
        kind = string(props['type'])
        assert kind not in payloads, 'Duplicate FIT component type'
        payloads[kind] = payload
        hashes = []
        for child, hp in nodes.items():
            if not child.startswith(name + '/hash-'): continue
            algo = string(hp['algo'])
            digest = (zlib.crc32(payload) & 0xffffffff).to_bytes(4, 'big') if algo == 'crc32' else hashlib.new(algo, payload).digest()
            assert digest == hp['value'], f'{name} {algo} payload hash mismatch'
            hashes.append(algo)
        assert 'crc32' in hashes and 'sha1' in hashes, f'{name}: missing expected FIT checksums'
        results[name] = {'bytes': size, 'sha256': hashlib.sha256(payload).hexdigest(), 'verified_hashes': hashes}
    assert set(payloads) == {'kernel', 'flat_dt', 'filesystem'}, 'Unexpected image component types'
    assert string(nodes['/configurations']['default']) == 'config-1'
    config = nodes['/configurations/config-1']
    for prop, value in [('kernel', 'kernel-1'), ('fdt', 'fdt-1'), ('loadables', 'rootfs-1')]:
        assert string(config[prop]) == value
    assert string(nodes['/images/kernel-1']['arch']) == 'arm64'
    assert string(nodes['/images/kernel-1']['compression']) == 'gzip'
    kernel = gzip.decompress(payloads['kernel'])
    assert b'Linux version 6.18.52' in kernel, 'Kernel version mismatch'
    assert number(nodes['/images/kernel-1']['load']) == 0x80200000
    assert payloads['filesystem'].startswith(b'hsqs'), 'Rootfs is not squashfs'
    _, dt = fdt(payloads['flat_dt'])
    assert b'gemtek,xr1710g-ubi\0' in dt['/']['compatible']
    expected = {'vendor': (0, 0x600000, True), 'chainloader': (0x600000, 0x100000, True), 'ubi': (0x700000, 0x1b700000, False), 'reserved_bmt': (0x1be00000, 0x4200000, True)}
    parts = {}
    for name, p in dt.items():
        if string(p.get('label', b'')) in expected:
            label = string(p['label']); assert label not in parts
            addr, size = struct.unpack('>II', p['reg'])
            assert (addr, size) == expected[label][:2], f'{label} partition boundaries changed'
            if require_ro: assert ('read-only' in p) == expected[label][2], f'{label}: partition protection mismatch'
            parts[label] = {'start': hex(addr), 'size': hex(size), 'read_only': 'read-only' in p}
    assert set(parts) == set(expected), 'Partition labels missing'
    fit_volumes = [p for p in dt.values() if p.get('volname') == b'fit\0']
    assert len(fit_volumes) == 1 and fit_volumes[0]['phandle'] == dt['/chosen']['rootdisk']
    assert any(p.get('num-lanes') == b'\0\0\0\2' and 'airoha,x2-mode' in p and p.get('status') == b'okay\0' for p in dt.values()), 'Missing PCIe x2 hardware contract'
    assert any('/npu@' in name and p.get('status') == b'okay\0' for name, p in dt.items()), 'NPU not enabled'
    assert any(p.get('volname') == b'factory\0' for p in dt.values())
    assert b'ubi.block=0,fit' in dt['/chosen']['bootargs'] and b'root=/dev/fit0' in dt['/chosen']['bootargs']
    # The caller must first use fwtool -i, which checks the metadata trailer.
    metadata = json.loads(Path(metadata_path).read_text())
    assert metadata['compat_version'] == expected_compat, 'Wrong upgrade compatibility version'
    supported = metadata.get('new_supported_devices', metadata['supported_devices'])
    assert 'gemtek,xr1710g-ubi' in supported
    assert not any('w1700' in b or 'w1701' in b or 'xg2010' in b for b in supported)
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    (out / 'rootfs.squashfs').write_bytes(payloads['filesystem'])
    (out / 'device.dtb').write_bytes(payloads['flat_dt'])
    report = {'image': str(image), 'sha256': hashlib.sha256(data).hexdigest(), 'image_bytes': len(data), 'payloads': results, 'partitions': parts, 'metadata': metadata, 'hardware_validation': 'NOT RUN: no device access; candidate must not be treated as hardware-validated'}
    (out / 'fit-validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))

if __name__ == '__main__': inspect(sys.argv[1], sys.argv[2], sys.argv[3])
