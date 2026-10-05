#!/usr/bin/env python3
"""Fail-closed, standard-library-only W1700K UBI2 FIT artifact gate.

CI must first run ``fwtool -i metadata.json image.itb`` and pass that file here.
This gate independently checks the fwtool framing/CRC and binds supplied JSON to
those exact image bytes; CRC32/SHA1 detect corruption, not publisher authenticity.
No router access, flashing, rootfs mounting or rootfs file inspection is performed.

Usage: verify_artifact.py IMAGE OUT_DIR METADATA --mode candidate
       verify_artifact.py IMAGE OUT_DIR METADATA --mode reference \
           --metadata-source reference-extracted

The reference-only source option documents that local fwtool was not run. It is
not allowed for candidate validation. Reference mode pins the published SHA256.
"""

import argparse
import hashlib
import json
import re
import struct
import sys
import zlib
from pathlib import Path

BOARD = 'gemtek,w1700k-ubi'
PROFILE = 'gemtek_w1700k-ubi'
KERNEL = '6.18.55'
SOURCE_COMMIT = '15490b469f68133da3d244881fb48dd5e42c1d87'
# image-commands.mk uses REVISION from getver.sh, not CONFIG_VERSION_CODE.
# This exact shallow source checkout produces r0-15490b4. The full source SHA
# must be verified independently by the build; the short revision is not proof.
CANDIDATE_REVISION = 'r0-15490b4'
REFERENCE_REVISION = 'r36860-15490b469f'
REFERENCE_SHA256 = '6b63de6786f8e473a0b0277e3bc8348a5b0cebf7fca75faaf9c1768c813ed6d8'
REFERENCE_BYTES = 22336319
MAX_IMAGE_BYTES = 0x1B700000
MAX_KERNEL_BYTES = 128 * 1024 * 1024
PARTITION_PARENT = '/soc/spi@1fa10000/nand@0/partitions'
PARTITIONS = {
    'vendor': (0, 0x600000, True),
    'chainloader': (0x600000, 0x100000, True),
    'ubi': (0x700000, 0x1B700000, False),
    'reserved_bmt': (0x1BE00000, 0x4200000, True),
}
COMPAT_MESSAGE = ('Partition table has been changed to cooperate with the vendor '
                  'bootloader with regard to the BMT/BBT partition at the end of '
                  'flash. A reinstall including corrected chainloader is needed.')
LEGACY_SUPPORTED = (BOARD + ' - Image version mismatch: image 2.0, device 1.0. '
                    'Please wipe config during upgrade (force required) or '
                    'reinstall. Reason: ' + COMPAT_MESSAGE)
NPU_MEMORY = {
    'binary': ('npu-binary@84000000', 0x84000000, 0xA00000),
    'pkt': ('npu-pkt@8a000000', 0x8A000000, 0x2C00000),
    'tx-pkt': ('npu-txpkt@8cc00000', 0x8CC00000, 0x4000000),
    'tx-bufid': ('npu-txbufid@90c00000', 0x90C00000, 0x6800),
    'ba': ('npu-ba@90c06800', 0x90C06800, 0x200000),
}


class ValidationError(ValueError):
    """Artifact does not satisfy the pinned board contract."""


def require(condition, message):
    # Do not use Python assert: safety gates must survive python -O.
    if not condition:
        raise ValidationError(message)


def be32(value):
    return struct.pack('>I', value)


def cells(value, context='property'):
    require(isinstance(value, bytes) and len(value) % 4 == 0,
            context + ': invalid cell array')
    return struct.unpack('>' + 'I' * (len(value) // 4), value)


def number(value, context='property'):
    require(isinstance(value, bytes) and len(value) == 4,
            context + ': expected one 32-bit cell')
    return struct.unpack('>I', value)[0]


def strings(value, context='property'):
    require(isinstance(value, bytes) and value.endswith(b'\0'),
            context + ': expected NUL-terminated string list')
    chunks = value[:-1].split(b'\0')
    require(all(chunks), context + ': empty string')
    try:
        return tuple(chunk.decode('ascii') for chunk in chunks)
    except UnicodeDecodeError as exc:
        raise ValidationError(context + ': non-ASCII string') from exc


def string(value, context='property'):
    result = strings(value, context)
    require(len(result) == 1, context + ': expected exactly one string')
    return result[0]


def children(nodes, parent):
    prefix = parent.rstrip('/') + '/'
    return {name: props for name, props in nodes.items()
            if name.startswith(prefix) and '/' not in name[len(prefix):]}


def prop(nodes, path, key):
    require(path in nodes, 'Missing node: ' + path)
    require(key in nodes[path], path + ': missing ' + key)
    return nodes[path][key]


def expect(nodes, path, key, value):
    require(prop(nodes, path, key) == value, path + ': wrong ' + key)


def fdt(data):
    """Parse a v17 flattened device tree with explicit bounds and uniqueness."""
    require(len(data) >= 40, 'Truncated FDT header')
    (magic, total, soff, stroff, roff, version, last_version, _, strsize,
     ssize) = struct.unpack_from('>10I', data)
    require(magic == 0xD00DFEED and 40 <= total <= len(data),
            'Invalid/truncated FDT')
    require(version == 17 and 16 <= last_version <= 17,
            'Unsupported FDT format version')
    require(soff % 4 == 0 and roff % 8 == 0, 'Misaligned FDT blocks')
    require(40 <= soff < soff + ssize <= total, 'FDT structure outside bounds')
    require(40 <= stroff <= stroff + strsize <= total, 'FDT strings outside bounds')
    require(40 <= roff <= total - 16, 'FDT reservations outside bounds')
    rend = roff
    while True:
        require(rend + 16 <= total, 'Unterminated FDT reservation map')
        address, size = struct.unpack_from('>QQ', data, rend)
        rend += 16
        if address == size == 0:
            break
        require(size > 0 and address + size <= 1 << 64,
                'Invalid FDT reserved-memory range')
    blocks = sorted([(soff, soff + ssize), (stroff, stroff + strsize), (roff, rend)])
    require(all(a[1] <= b[0] for a, b in zip(blocks, blocks[1:])),
            'Overlapping FDT blocks')
    off, end, string_end = soff, soff + ssize, stroff + strsize
    stack, nodes = [], {}
    while off + 4 <= end:
        token = struct.unpack_from('>I', data, off)[0]
        off += 4
        if token == 1:  # FDT_BEGIN_NODE
            stop = data.find(b'\0', off, end)
            require(stop >= 0, 'Unterminated FDT node name')
            try:
                name = data[off:stop].decode('ascii')
            except UnicodeDecodeError as exc:
                raise ValidationError('Non-ASCII FDT node name') from exc
            require('/' not in name, 'Invalid slash in FDT node name')
            require((not stack and not nodes and name == '') or
                    (bool(stack) and bool(name)), 'Invalid/multiple FDT roots')
            stack.append(name)
            path = '/'.join(stack) or '/'
            require(path not in nodes, 'Duplicate FDT node: ' + path)
            nodes[path] = {}
            off = (stop + 4) & ~3
            require(off <= end, 'Truncated FDT node padding')
        elif token == 2:  # FDT_END_NODE
            require(bool(stack), 'Unbalanced FDT nodes')
            stack.pop()
        elif token == 3:  # FDT_PROP
            require(bool(stack) and off + 8 <= end, 'Invalid FDT property header')
            size, nameoff = struct.unpack_from('>II', data, off)
            off += 8
            require(nameoff < strsize and off + size <= end,
                    'FDT property outside bounds')
            stop = data.find(b'\0', stroff + nameoff, string_end)
            require(stop >= 0, 'Unterminated FDT property name')
            try:
                name = data[stroff + nameoff:stop].decode('ascii')
            except UnicodeDecodeError as exc:
                raise ValidationError('Non-ASCII FDT property name') from exc
            require(bool(name), 'Empty FDT property name')
            props = nodes['/'.join(stack) or '/']
            require(name not in props, 'Duplicate FDT property: ' + name)
            props[name] = data[off:off + size]
            off = (off + size + 3) & ~3
            require(off <= end, 'Truncated FDT property padding')
        elif token == 9:  # FDT_END
            require(not stack and '/' in nodes, 'Unbalanced/incomplete FDT')
            require(not any(data[off:end]), 'Unexpected data after FDT end')
            return total, nodes
        else:
            require(token == 4, 'Unknown FDT token: ' + str(token))
    raise ValidationError('Missing FDT end token')


def load_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate metadata JSON key: ' + key)
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(
                              ValidationError('Invalid JSON constant: ' + value)))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError('Invalid metadata JSON') from exc


def extract_metadata(data):
    """Check fwtool CRC/framing and return JSON, payload boundary and evidence.

    Format and unfinalized CRC32 follow the pinned OpenWrt fwtool source:
    https://github.com/openwrt/fwtool/blob/04cd252e4e9394ffacd51f56f1f124abc534f715/fwimage.h
    https://github.com/openwrt/fwtool/blob/04cd252e4e9394ffacd51f56f1f124abc534f715/fwtool.c
    Optional signature framing/CRC is checked, never signature authenticity.
    """
    end, metadata, signature_count, chunks = len(data), None, 0, 0
    while end >= 16 and data[end - 16:end - 12] == b'FWx0':
        _, crc, kind, padding, size = struct.unpack_from('>IIB3sI', data, end - 16)
        require(padding == b'\0' * 3, 'Invalid fwtool trailer padding')
        require(16 < size <= end, 'Invalid fwtool trailer size')
        require((zlib.crc32(memoryview(data)[:end - 16]) ^ 0xFFFFFFFF) == crc,
                'fwtool trailer CRC32 mismatch')
        start = end - size
        content = data[start:end - 16]
        chunks += 1
        require(chunks <= 2, 'Unexpected extra fwtool trailers')
        if kind == 0:
            require(metadata is None and signature_count == 0 and len(content) <= 1024,
                    'Unexpected fwtool signature trailer')
            signature_count += 1
        elif kind == 1:
            require(metadata is None, 'Duplicate fwtool metadata trailer')
            require(8 < len(content) <= 8 + 30 * 1024, 'Invalid fwtool metadata size')
            require(content[:8] == b'\0' * 8, 'Unsupported fwtool metadata header')
            metadata = load_json(content[8:])
        else:
            raise ValidationError('Unsupported fwtool trailer type')
        end = start
    require(metadata is not None, 'Missing fwtool metadata trailer')
    return metadata, end, {
        'framing_and_crc32': 'PASS (independent Python verification)',
        'supplied_metadata_bound_to_image': True,
        'signature_trailers': signature_count,
        'signature_authenticity': 'NOT VERIFIED',
    }


def validate_metadata(metadata, mode):
    require(mode in ('candidate', 'reference'), 'Unknown validation mode')
    require(isinstance(metadata, dict), 'Metadata must be an object')
    require(metadata.get('metadata_version') == '1.1', 'Wrong metadata format')
    require(metadata.get('compat_version') == '2.0', 'Wrong upgrade compatibility version')
    require(metadata.get('compat_message') == COMPAT_MESSAGE, 'Wrong UBI2 compatibility message')
    require(metadata.get('new_supported_devices') == [BOARD],
            'new_supported_devices must contain only W1700K UBI2')
    require(metadata.get('supported_devices') == [LEGACY_SUPPORTED],
            'Wrong legacy supported_devices compatibility guard')
    version = metadata.get('version')
    require(isinstance(version, dict), 'Missing metadata version object')
    require(version.get('target') == 'airoha/an7581', 'Wrong target')
    require(version.get('board') == PROFILE, 'Wrong metadata board')
    expected = ('W1700K-Slim', '6.18.55-ubi2') if mode == 'candidate' else ('OpenWrt', 'ubi2')
    require((version.get('dist'), version.get('version')) == expected,
            'Wrong ' + mode + ' distribution/version')
    revision = CANDIDATE_REVISION if mode == 'candidate' else REFERENCE_REVISION
    require(version.get('revision') == revision, 'Wrong pinned source revision')


def enabled(nodes, path):
    """Check the device and all ancestors; absent status means enabled in DT."""
    original = path
    while path:
        require(path in nodes, 'Missing node: ' + path)
        require(nodes[path].get('status', b'okay\0') in (b'okay\0', b'ok\0'),
                'Disabled hardware path: ' + original)
        path = path.rsplit('/', 1)[0]


def validate_dtb(blob):
    total, dt = fdt(blob)
    require(total == len(blob), 'Unexpected bytes after compiled DTB')
    expect(dt, '/', 'compatible', b'gemtek,w1700k-ubi\0airoha,an7581\0airoha,en7581\0')
    expect(dt, '/', 'model', b'Gemtek W1700K (OpenWrt U-Boot layout)\0')
    phandles = {}
    for path, props in dt.items():
        if 'phandle' not in props and 'linux,phandle' not in props:
            continue
        handle = number(props.get('phandle', props.get('linux,phandle')), path)
        require(0 < handle < 0xFFFFFFFF and handle not in phandles,
                'Invalid/duplicate DT phandle')
        if 'linux,phandle' in props:
            require(number(props['linux,phandle'], path) == handle,
                    'Conflicting linux,phandle')
        phandles[handle] = path

    def resolve(raw, context):
        handle = number(raw, context)
        require(handle in phandles, context + ': dangling phandle')
        return phandles[handle]

    enabled(dt, PARTITION_PARENT)
    expect(dt, '/soc/spi@1fa10000', 'status', b'okay\0')
    expect(dt, PARTITION_PARENT, 'compatible', b'fixed-partitions\0')
    expect(dt, PARTITION_PARENT, '#address-cells', be32(1))
    expect(dt, PARTITION_PARENT, '#size-cells', be32(1))
    parts, paths = {}, {}
    for path, props in children(dt, PARTITION_PARENT).items():
        label = string(prop(dt, path, 'label'), path)
        require(label in PARTITIONS and label not in parts, 'Unexpected/duplicate flash partition')
        start, size, read_only = PARTITIONS[label]
        expect(dt, path, 'reg', struct.pack('>II', start, size))
        require(('read-only' in props) == read_only, label + ': partition protection mismatch')
        if read_only:
            expect(dt, path, 'read-only', b'')
        enabled(dt, path)
        parts[label] = {'start': hex(start), 'size': hex(size), 'read_only': read_only}
        paths[label] = path
    require(set(parts) == set(PARTITIONS), 'Missing UBI2 partition')
    expect(dt, paths['ubi'], 'compatible', b'linux,ubi\0')
    volumes_parent = paths['ubi'] + '/volumes'
    volumes = {}
    for path, props in children(dt, volumes_parent).items():
        volume = string(prop(dt, path, 'volname'), path)
        require(volume not in volumes, 'Duplicate UBI volume')
        volumes[volume] = path
        enabled(dt, path)
    require(set(volumes) == {'ubootenv', 'ubootenv2', 'fit', 'factory'}, 'Wrong UBI volumes')
    require(resolve(prop(dt, '/chosen', 'rootdisk'), 'rootdisk') == volumes['fit'],
            'chosen rootdisk does not reference the UBI fit volume')
    args = string(prop(dt, '/chosen', 'bootargs'), 'bootargs').split()
    require([a for a in args if a.startswith('root=')] == ['root=/dev/fit0'] and
            [a for a in args if a.startswith('ubi.block=')] == ['ubi.block=0,fit'] and
            'rootwait' in args, 'Wrong chosen FIT root boot arguments')
    for name in ('ubootenv', 'ubootenv2'):
        expect(dt, volumes[name] + '/nvmem-layout', 'compatible', b'u-boot,env-redundant-bool\0')
    factory = volumes['factory'] + '/nvmem-layout'
    expect(dt, factory, 'compatible', b'fixed-layout\0')
    expect(dt, factory, '#address-cells', be32(1))
    expect(dt, factory, '#size-cells', be32(1))
    for name, offset, size in [('eeprom@0', 0, 0x1E00), ('macaddr@5000', 0x5000, 6),
                               ('macaddr@6000', 0x6000, 6)]:
        expect(dt, factory + '/' + name, 'reg', struct.pack('>II', offset, size))

    # W1700K native x2 binding; deliberately no XR-specific airoha,x2-mode test.
    pcie = '/soc/pcie@1fc00000'
    enabled(dt, pcie)
    expect(dt, pcie, 'status', b'okay\0')
    expect(dt, pcie, 'compatible', b'airoha,en7581-pcie\0')
    expect(dt, pcie, 'num-lanes', be32(2))
    expect(dt, pcie, 'reg', struct.pack('>8I', 0, 0x1FC00000, 0, 0x1670,
                                      0, 0x1FC20000, 0, 0x1670))
    expect(dt, pcie, 'reg-names', b'pcie-mac\0sec-pcie-mac\0')
    expect(dt, pcie, 'reset-names', b'phy-lane0\0phy-lane1\0perstout\0sec-perstout\0')
    resets = cells(prop(dt, pcie, 'resets'), 'PCIe resets')
    scu = number(prop(dt, pcie, 'airoha,scu'), 'PCIe scu')
    require(scu in phandles and resets == (scu, 48, scu, 49, scu, 53, scu, 54),
            'Wrong PCIe x2 reset wiring')
    expect(dt, '/soc/pcie@1fc20000', 'status', b'disabled\0')
    enabled(dt, '/soc/pcie@1fc40000')
    expect(dt, '/soc/pcie@1fc40000', 'status', b'okay\0')
    npu = '/soc/npu@1e900000'
    enabled(dt, npu)
    expect(dt, npu, 'status', b'okay\0')
    expect(dt, npu, 'compatible', b'airoha,en7581-npu\0')
    expect(dt, npu, 'firmware-name',
           b'airoha/en7581_MT7996_npu_rv32.bin\0airoha/en7581_MT7996_npu_data.bin\0')
    names = strings(prop(dt, npu, 'memory-region-names'), 'NPU memory-region-names')
    handles = cells(prop(dt, npu, 'memory-region'), 'NPU memory-region')
    require(names == tuple(NPU_MEMORY) and len(handles) == len(names), 'Wrong NPU memory regions')
    for name, handle in zip(names, handles):
        node, start, size = NPU_MEMORY[name]
        path = '/reserved-memory/' + node
        require(phandles.get(handle) == path, 'Wrong NPU memory phandle: ' + name)
        expect(dt, path, 'reg', struct.pack('>4I', 0, start, 0, size))
        expect(dt, path, 'no-map', b'')
    wifi = pcie + '/pcie@0,0/mt7996@0,0'
    enabled(dt, wifi)
    require(resolve(prop(dt, wifi, 'airoha,npu'), 'MT7996 NPU') == npu, 'Wrong MT7996 NPU link')
    eth = '/soc/ethernet@1fb50000'
    require(resolve(prop(dt, wifi, 'airoha,eth'), 'MT7996 Ethernet') == eth,
            'Wrong MT7996 Ethernet link')
    enabled(dt, eth)
    expect(dt, eth, 'status', b'okay\0')
    require(resolve(prop(dt, wifi, 'nvmem-cells'), 'MT7996 EEPROM') == factory + '/eeprom@0',
            'MT7996 EEPROM does not reference factory')
    expect(dt, wifi, 'nvmem-cell-names', b'eeprom\0')
    for band in range(3):
        path = wifi + '/band@' + str(band)
        expect(dt, path, 'reg', be32(band))
        refs = cells(prop(dt, path, 'nvmem-cells'), path)
        require(len(refs) == 2 and phandles.get(refs[0]) == factory + '/macaddr@6000'
                and refs[1] == band + 1, 'Wrong Wi-Fi band MAC reference')
        expect(dt, path, 'nvmem-cell-names', b'mac-address\0')
    return {'compatible': list(strings(dt['/']['compatible'])), 'partitions': parts,
            'rootdisk_volume': 'fit', 'factory_nvmem': 'PASS',
            'pcie': 'PASS: native W1700K dual-MAC x2; PCIe1 disabled; PCIe2 enabled',
            'npu': 'PASS: enabled, MT7996 firmware/memory and Wi-Fi links'}


def validate_kernel(payload):
    require(payload.startswith(b'\x1f\x8b\x08'), 'Kernel is not gzip')
    try:
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        kernel = decoder.decompress(payload, MAX_KERNEL_BYTES + 1)
    except zlib.error as exc:
        raise ValidationError('Invalid gzip kernel') from exc
    require(len(kernel) <= MAX_KERNEL_BYTES, 'Kernel decompression size limit exceeded')
    require(decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,
            'Truncated/concatenated gzip kernel')
    require(len(kernel) >= 64 and kernel[56:60] == b'ARMd', 'Missing ARM64 Linux image magic')
    versions = re.findall(rb'Linux version ([^\s\0]+)', kernel)
    require(bool(versions) and set(versions) == {KERNEL.encode()}, 'Kernel version mismatch')
    return {'version': KERNEL, 'arch': 'arm64', 'compression': 'gzip',
            'uncompressed_bytes': len(kernel)}


def validate_squashfs(payload):
    # Only public binary superblock fields are read. No filesystem contents.
    require(len(payload) >= 96 and payload[:4] == b'hsqs', 'Rootfs is not squashfs')
    require(struct.unpack_from('<HH', payload, 28) == (4, 0), 'Wrong squashfs version')
    used = struct.unpack_from('<Q', payload, 40)[0]
    require(96 <= used <= len(payload), 'Squashfs bytes_used outside payload')
    block = struct.unpack_from('<I', payload, 12)[0]
    require(4096 <= block <= 1048576 and block & (block - 1) == 0,
            'Invalid squashfs block size')


def validate_image(data, metadata, mode='candidate', metadata_source='fwtool'):
    require(mode in ('candidate', 'reference'), 'Unknown validation mode')
    require(metadata_source in ('fwtool', 'reference-extracted'), 'Unknown metadata source')
    require(mode == 'reference' or metadata_source == 'fwtool',
            'Candidate metadata must be extracted with fwtool -i')
    require(40 <= len(data) <= MAX_IMAGE_BYTES, 'Image size outside permitted bounds')
    embedded, payload_end, trailer = extract_metadata(data)
    require(metadata == embedded, 'Supplied metadata does not match this image')
    validate_metadata(metadata, mode)
    digest = hashlib.sha256(data).hexdigest()
    if mode == 'reference':
        require(len(data) == REFERENCE_BYTES and digest == REFERENCE_SHA256,
                'Reference artifact does not match pinned SHA256/size')
    total, nodes = fdt(data[:payload_end])
    image_types = {'kernel-1': 'kernel', 'fdt-1': 'flat_dt', 'rootfs-1': 'filesystem'}
    require(set(children(nodes, '/images')) == {'/images/' + name for name in image_types},
            'Unexpected FIT payload names')
    require(set(children(nodes, '/configurations')) == {'/configurations/config-1'},
            'Unexpected FIT boot configurations')
    expect(nodes, '/configurations', 'default', b'config-1\0')
    config = '/configurations/config-1'
    for key, value in [('kernel', 'kernel-1'), ('fdt', 'fdt-1'), ('loadables', 'rootfs-1')]:
        expect(nodes, config, key, value.encode() + b'\0')
    require(not {'ramdisk', 'firmware', 'script', 'setup'} & nodes[config].keys(),
            'Unexpected alternate FIT boot components')
    spans, payloads, results = [], {}, {}
    for name, kind in image_types.items():
        path = '/images/' + name
        props = nodes[path]
        expect(nodes, path, 'type', kind.encode() + b'\0')
        expect(nodes, path, 'arch', b'arm64\0')
        expect(nodes, path, 'compression', b'gzip\0' if name == 'kernel-1' else b'none\0')
        require('data' not in props and 'data-offset' not in props,
                path + ': expected only external static FIT payload')
        position = number(prop(nodes, path, 'data-position'), path)
        size = number(prop(nodes, path, 'data-size'), path)
        require(position >= total and position % 4 == 0 and size > 0 and
                position + size <= payload_end, path + ': payload outside FIT/image bounds')
        spans.append((position, position + size, path))
        payload = data[position:position + size]
        payloads[kind] = payload
        hashes = {}
        hash_nodes = children(nodes, path)
        require(len(hash_nodes) == 2, path + ': expected CRC32 and SHA1 hash nodes')
        for hash_path, props in hash_nodes.items():
            require(hash_path.rsplit('/', 1)[1].startswith('hash-') and not children(nodes, hash_path),
                    path + ': unexpected FIT hash node')
            algorithm = string(prop(nodes, hash_path, 'algo'), hash_path)
            require(algorithm in ('crc32', 'sha1') and algorithm not in hashes,
                    path + ': unexpected/duplicate FIT hash algorithm')
            digest_bytes = (be32(zlib.crc32(payload)) if algorithm == 'crc32' else
                            hashlib.sha1(payload).digest())
            require(prop(nodes, hash_path, 'value') == digest_bytes,
                    path + ': ' + algorithm + ' payload hash mismatch')
            hashes[algorithm] = digest_bytes.hex()
        require(set(hashes) == {'crc32', 'sha1'}, path + ': missing FIT checksums')
        results[name] = {'position': position, 'bytes': size, 'type': kind,
                         'sha256': hashlib.sha256(payload).hexdigest(), 'verified_hashes': hashes}
    spans.sort()
    require(all(left[1] <= right[0] for left, right in zip(spans, spans[1:])),
            'Overlapping FIT payloads')
    expect(nodes, '/images/kernel-1', 'os', b'linux\0')
    for key in ('load', 'entry'):
        expect(nodes, '/images/kernel-1', key, be32(0x80200000))
    kernel = validate_kernel(payloads['kernel'])
    validate_squashfs(payloads['filesystem'])
    device = validate_dtb(payloads['flat_dt'])
    trailer['external_fwtool'] = ('Required CI prerequisite: caller reports fwtool -i success'
                                  if metadata_source == 'fwtool' else
                                  'NOT RUN: reference metadata independently extracted in Python')
    report = {'status': 'PASS', 'mode': mode, 'sha256': digest, 'image_bytes': len(data),
              'fit_bytes': total, 'payloads': results, 'kernel': kernel, 'device_tree': device,
              'metadata': metadata, 'metadata_validation': trailer,
              'source_provenance_requirement': {
                  'required_full_source_commit': SOURCE_COMMIT,
                  'metadata_revision': metadata['version']['revision'],
                  'required_evidence': 'Build workflow and source preparation must independently '
                                       'verify git rev-parse HEAD against the full source commit',
                  'artifact_verification': 'NOT VERIFIED FROM ARTIFACT: the abbreviated metadata '
                                           'revision does not establish the full source commit',
              },
              'hardware_validation': 'NOT RUN: offline artifact checks only; do not flash or release',
              'rootfs_content_validation': 'NOT RUN: only binary superblock and payload hashes checked'}
    return report, payloads


def inspect(image, out, metadata_path, mode='candidate', metadata_source='fwtool'):
    image = Path(image)
    require(image.stat().st_size <= MAX_IMAGE_BYTES, 'Image exceeds size limit')
    metadata_path = Path(metadata_path)
    require(metadata_path.stat().st_size <= 30 * 1024, 'Metadata exceeds size limit')
    report, payloads = validate_image(image.read_bytes(), load_json(metadata_path.read_bytes()),
                                      mode, metadata_source)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    # Write no extracted binary until every check has passed.
    (out / 'rootfs.squashfs').write_bytes(payloads['filesystem'])
    (out / 'device.dtb').write_bytes(payloads['flat_dt'])
    report['image'] = str(image)
    (out / 'fit-validation.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', help='W1700K sysupgrade FIT image')
    parser.add_argument('out_dir', help='validation report and binary extraction directory')
    parser.add_argument('metadata', help='JSON extracted from this image using fwtool -i')
    parser.add_argument('--mode', choices=('candidate', 'reference'), default='candidate')
    parser.add_argument('--metadata-source', choices=('fwtool', 'reference-extracted'), default='fwtool')
    args = parser.parse_args(argv)
    try:
        report = inspect(args.image, args.out_dir, args.metadata, args.mode, args.metadata_source)
    except (ValidationError, OSError) as exc:
        print('FAIL: ' + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
