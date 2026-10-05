#!/usr/bin/env python3
"""Pure-Python positive/negative artifact tests; no firmware/network fixtures.

Run: python3 -m unittest discover -s w1700k-slim -p 'test_artifact.py' -v
The synthetic rootfs is an empty binary header, never a private filesystem.
"""
import copy
import gzip
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import verify_artifact as gate


def u32(*values):
    return struct.pack('>' + 'I' * len(values), *values)


def text(value):
    return value.encode() + b'\0'


def encode_fdt(nodes, padded=None):
    """Minimal fixture writer, intentionally independent of the parser."""
    nodes = copy.deepcopy(nodes)
    for path in list(nodes):
        parent = path.rsplit('/', 1)[0] or '/'
        while parent not in nodes:
            nodes[parent] = {}
            parent = parent.rsplit('/', 1)[0] or '/'
    names = {}
    strings = bytearray()
    for props in nodes.values():
        for name in props:
            if name not in names:
                names[name] = len(strings)
                strings.extend(text(name))
    structure = bytearray()

    def align():
        structure.extend(b'\0' * (-len(structure) % 4))

    def emit(path):
        structure.extend(u32(1))
        structure.extend(text('' if path == '/' else path.rsplit('/', 1)[1]))
        align()
        for name, value in nodes[path].items():
            structure.extend(u32(3, len(value), names[name]))
            structure.extend(value)
            align()
        prefix = '' if path == '/' else path
        for child in sorted(nodes):
            if child != '/' and child.rsplit('/', 1)[0] == prefix:
                emit(child)
        structure.extend(u32(2))

    emit('/')
    structure.extend(u32(9))
    total = 56 + len(structure) + len(strings)
    if padded is not None:
        if total > padded:
            raise ValueError('Test FIT header too big')
        total = padded
    header = u32(0xD00DFEED, total, 56, 56 + len(structure), 40, 17, 16, 0,
                 len(strings), len(structure))
    result = header + b'\0' * 16 + bytes(structure) + bytes(strings)
    return result + b'\0' * (total - len(result))


def device_nodes():
    root = gate.PARTITION_PARENT
    dt = {
        '/': {'compatible': b'gemtek,w1700k-ubi\0airoha,an7581\0airoha,en7581\0',
              'model': text('Gemtek W1700K (OpenWrt U-Boot layout)')},
        '/soc/spi@1fa10000': {'status': text('okay')},
        root: {'compatible': text('fixed-partitions'), '#address-cells': u32(1), '#size-cells': u32(1)},
        '/chosen': {'rootdisk': u32(10),
                    'bootargs': text('console=ttyS0,115200 earlycon ubi.block=0,fit root=/dev/fit0 rootwait')},
    }
    for label, (offset, size, ro) in gate.PARTITIONS.items():
        path = root + '/partition@' + format(offset, 'x')
        dt[path] = {'label': text(label), 'reg': u32(offset, size)}
        if ro:
            dt[path]['read-only'] = b''
        if label == 'ubi':
            dt[path]['compatible'] = text('linux,ubi')
    vols = root + '/partition@700000/volumes'
    for name in ('ubootenv', 'ubootenv2', 'fit', 'factory'):
        path = vols + '/ubi-volume-' + name
        dt[path] = {'volname': text(name)}
        if name in ('ubootenv', 'ubootenv2'):
            dt[path + '/nvmem-layout'] = {'compatible': text('u-boot,env-redundant-bool')}
    dt[vols + '/ubi-volume-fit']['phandle'] = u32(10)
    factory = vols + '/ubi-volume-factory/nvmem-layout'
    dt[factory] = {'compatible': text('fixed-layout'), '#address-cells': u32(1), '#size-cells': u32(1)}
    dt[factory + '/eeprom@0'] = {'reg': u32(0, 0x1E00), 'phandle': u32(20)}
    dt[factory + '/macaddr@5000'] = {'reg': u32(0x5000, 6), 'phandle': u32(21)}
    dt[factory + '/macaddr@6000'] = {'reg': u32(0x6000, 6), 'phandle': u32(22)}
    pcie = '/soc/pcie@1fc00000'
    dt['/soc/scu'] = {'phandle': u32(30)}
    dt[pcie] = {'compatible': text('airoha,en7581-pcie'), 'status': text('okay'),
                'num-lanes': u32(2), 'reg': u32(0, 0x1FC00000, 0, 0x1670, 0, 0x1FC20000, 0, 0x1670),
                'reg-names': b'pcie-mac\0sec-pcie-mac\0',
                'reset-names': b'phy-lane0\0phy-lane1\0perstout\0sec-perstout\0',
                'airoha,scu': u32(30), 'resets': u32(30, 48, 30, 49, 30, 53, 30, 54)}
    dt['/soc/pcie@1fc20000'] = {'status': text('disabled')}
    dt['/soc/pcie@1fc40000'] = {'status': text('okay')}
    npu = '/soc/npu@1e900000'
    dt[npu] = {'compatible': text('airoha,en7581-npu'), 'status': text('okay'), 'phandle': u32(31),
               'firmware-name': b'airoha/en7581_MT7996_npu_rv32.bin\0airoha/en7581_MT7996_npu_data.bin\0',
               'memory-region': u32(40, 41, 42, 43, 44),
               'memory-region-names': b'binary\0pkt\0tx-pkt\0tx-bufid\0ba\0'}
    for index, (name, start, size) in enumerate(gate.NPU_MEMORY.values()):
        dt['/reserved-memory/' + name] = {'no-map': b'', 'reg': u32(0, start, 0, size),
                                         'phandle': u32(40 + index)}
    dt['/soc/ethernet@1fb50000'] = {'status': text('okay'), 'phandle': u32(32)}
    wifi = pcie + '/pcie@0,0/mt7996@0,0'
    dt[wifi] = {'airoha,npu': u32(31), 'airoha,eth': u32(32), 'nvmem-cells': u32(20),
                'nvmem-cell-names': text('eeprom')}
    for band in range(3):
        dt[wifi + '/band@' + str(band)] = {'reg': u32(band), 'nvmem-cells': u32(22, band + 1),
                                          'nvmem-cell-names': text('mac-address')}
    return dt


def metadata(mode='candidate'):
    return {'metadata_version': '1.1', 'compat_version': '2.0', 'compat_message': gate.COMPAT_MESSAGE,
            'new_supported_devices': [gate.BOARD], 'supported_devices': [gate.LEGACY_SUPPORTED],
            'version': {'target': 'airoha/an7581', 'board': gate.PROFILE,
                        'dist': 'W1700K-Slim' if mode == 'candidate' else 'OpenWrt',
                        'version': '6.18.55-ubi2' if mode == 'candidate' else 'ubi2',
                        'revision': 'r0-15490b4' if mode == 'candidate' else 'r36860-15490b469f'}}


def kernel(version='6.18.55'):
    data = bytearray(64)
    data[56:60] = b'ARMd'
    data.extend(b'\0Linux version ' + version.encode() + b' (synthetic@test)\n\0')
    return gzip.compress(data, mtime=0)


def squashfs():
    data = bytearray(96)
    data[:4] = b'hsqs'
    struct.pack_into('<I', data, 12, 262144)
    struct.pack_into('<HH', data, 28, 4, 0)
    struct.pack_into('<Q', data, 40, len(data))
    return bytes(data)


def trailer(content, meta=None, kind=1):
    extra = b'\0' * 8 + json.dumps(meta or metadata()).encode() if kind == 1 else b'test-signature'
    body = content + extra
    crc = gate.zlib.crc32(body) ^ 0xFFFFFFFF
    return body + struct.pack('>IIB3sI', 0x46577830, crc, kind, b'\0' * 3, len(extra) + 16)


def fixture(dt=None, meta=None, fit_edit=None, kernel_payload=None, rootfs=None):
    payloads = {'kernel-1': kernel() if kernel_payload is None else kernel_payload,
                'fdt-1': encode_fdt(device_nodes() if dt is None else dt),
                'rootfs-1': squashfs() if rootfs is None else rootfs}
    nodes = {'/': {}, '/images': {}, '/configurations': {'default': text('config-1')},
             '/configurations/config-1': {'kernel': text('kernel-1'), 'fdt': text('fdt-1'),
                                         'loadables': text('rootfs-1')}}
    blob = bytearray(4096)
    for name, kind in [('kernel-1', 'kernel'), ('fdt-1', 'flat_dt'), ('rootfs-1', 'filesystem')]:
        blob.extend(b'\0' * (-len(blob) % 16))
        path = '/images/' + name
        payload = payloads[name]
        nodes[path] = {'type': text(kind), 'arch': text('arm64'),
                       'compression': text('gzip' if kind == 'kernel' else 'none'),
                       'data-position': u32(len(blob)), 'data-size': u32(len(payload))}
        if kind == 'kernel':
            nodes[path].update({'os': text('linux'), 'load': u32(0x80200000), 'entry': u32(0x80200000)})
        for index, algo in enumerate(('crc32', 'sha1'), 1):
            digest = u32(gate.zlib.crc32(payload)) if algo == 'crc32' else hashlib.sha1(payload).digest()
            nodes[path + '/hash-' + str(index)] = {'algo': text(algo), 'value': digest}
        blob.extend(payload)
    if fit_edit:
        fit_edit(nodes)
    blob[:4096] = encode_fdt(nodes, 4096)
    return trailer(bytes(blob), meta)


class ArtifactTests(unittest.TestCase):
    def validate(self, image, meta=None):
        return gate.validate_image(image, meta or metadata())[0]

    def reject_dt(self, edit, message=None):
        dt = device_nodes()
        edit(dt)
        with self.assertRaisesRegex(gate.ValidationError, message or '.'):
            self.validate(fixture(dt=dt))

    def reject_fit(self, edit, message=None):
        with self.assertRaisesRegex(gate.ValidationError, message or '.'):
            self.validate(fixture(fit_edit=edit))

    def test_valid_candidate(self):
        result = self.validate(fixture())
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['kernel']['version'], '6.18.55')
        self.assertEqual(len(result['device_tree']['partitions']), 4)
        self.assertIn('NOT RUN', result['hardware_validation'])

    def test_reference_metadata_identity(self):
        gate.validate_metadata(metadata('reference'), 'reference')
        with self.assertRaisesRegex(gate.ValidationError, 'distribution/version'):
            gate.validate_metadata(metadata(), 'reference')

    def test_candidate_revision_is_one_exact_shallow_checkout_value(self):
        for revision in ['r36860-15490b469f', 'r0-15490b5', 'r0-15490b469f',
                         'r1-15490b4', 'r0-15490b4-dirty', '', None]:
            meta = metadata()
            meta['version']['revision'] = revision
            with self.subTest(revision=revision), self.assertRaisesRegex(
                    gate.ValidationError, 'Wrong pinned source revision'):
                self.validate(fixture(meta=meta), meta)

    def test_reference_revision_remains_exact(self):
        for revision in ['r0-15490b4', 'r36860-15490b469e', 'r36860-15490b4', '', None]:
            meta = metadata('reference')
            meta['version']['revision'] = revision
            with self.subTest(revision=revision), self.assertRaisesRegex(
                    gate.ValidationError, 'Wrong pinned source revision'):
                gate.validate_metadata(meta, 'reference')

    def test_full_source_commit_requires_external_build_provenance(self):
        provenance = self.validate(fixture())['source_provenance_requirement']
        self.assertEqual(provenance['required_full_source_commit'],
                         '15490b469f68133da3d244881fb48dd5e42c1d87')
        self.assertEqual(provenance['metadata_revision'], 'r0-15490b4')
        self.assertIn('git rev-parse HEAD', provenance['required_evidence'])
        self.assertIn('NOT VERIFIED FROM ARTIFACT', provenance['artifact_verification'])

    def test_reference_requires_exact_published_file(self):
        with self.assertRaisesRegex(gate.ValidationError, 'pinned SHA256'):
            gate.validate_image(fixture(meta=metadata('reference')), metadata('reference'),
                                'reference', 'reference-extracted')

    def test_candidate_requires_fwtool_source(self):
        with self.assertRaisesRegex(gate.ValidationError, 'fwtool -i'):
            gate.validate_image(fixture(), metadata(), metadata_source='reference-extracted')

    def test_output_files_and_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'input.itb').write_bytes(fixture())
            (base / 'meta.json').write_text(json.dumps(metadata()))
            run = subprocess.run([sys.executable, '-O', str(Path(gate.__file__)),
                                  str(base / 'input.itb'), str(base / 'out'), str(base / 'meta.json')],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual({p.name for p in (base / 'out').iterdir()},
                             {'rootfs.squashfs', 'device.dtb', 'fit-validation.json'})
            self.assertEqual(json.loads(run.stdout)['status'], 'PASS')

    def test_optimized_python_rejects_invalid_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'bad.itb').write_bytes(b'not an image')
            (base / 'meta.json').write_text(json.dumps(metadata()))
            run = subprocess.run([sys.executable, '-O', str(Path(gate.__file__)),
                                  str(base / 'bad.itb'), str(base / 'out'), str(base / 'meta.json')],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 1)
            self.assertIn('FAIL:', run.stderr)
            self.assertFalse((base / 'out').exists())

    def test_missing_or_corrupted_trailer(self):
        data = fixture()
        for bad in [data[:-16], data[:-1], data[:-12] + bytes([data[-12] ^ 1]) + data[-11:]]:
            with self.subTest(length=len(bad)), self.assertRaises(gate.ValidationError):
                self.validate(bad)

    def test_payload_corruption_crc_rejects(self):
        data = bytearray(fixture())
        data[4100] ^= 1
        with self.assertRaisesRegex(gate.ValidationError, 'trailer CRC32'):
            self.validate(bytes(data))

    def test_payload_corruption_repaired_trailer_still_fails_fit_hash(self):
        data = fixture()
        _, end, _ = gate.extract_metadata(data)
        damaged = bytearray(data[:end])
        damaged[4100] ^= 1
        with self.assertRaisesRegex(gate.ValidationError, 'payload hash mismatch'):
            self.validate(trailer(bytes(damaged)))

    def test_signature_crc_is_checked_but_authenticity_not_claimed(self):
        result = self.validate(trailer(fixture(), kind=0))
        self.assertEqual(result['metadata_validation']['signature_trailers'], 1)
        self.assertEqual(result['metadata_validation']['signature_authenticity'], 'NOT VERIFIED')

    def test_detached_metadata_rejected(self):
        other = metadata()
        other['version']['dist'] = 'Other'
        with self.assertRaisesRegex(gate.ValidationError, 'does not match this image'):
            self.validate(fixture(), other)

    def test_duplicate_json_key_rejected(self):
        with self.assertRaisesRegex(gate.ValidationError, 'Duplicate metadata JSON key'):
            gate.load_json(b'{"version":1,"version":2}')

    def test_wrong_metadata_board_target_and_compatibility(self):
        for path, value in [('board', 'gemtek_xr1710g-ubi'), ('board', 'gemtek_w1701k-ubi'),
                            ('target', 'mediatek/filogic'), ('dist', 'OpenWrt'), ('version', 'ubi2')]:
            meta = metadata()
            meta['version'][path] = value
            with self.subTest(path=path, value=value), self.assertRaises(gate.ValidationError):
                self.validate(fixture(meta=meta), meta)
        for key, value in [('compat_version', '1.0'), ('new_supported_devices', ['gemtek,w1701k-ubi']),
                           ('new_supported_devices', [gate.BOARD, 'gemtek,xr1710g-ubi']),
                           ('supported_devices', [gate.BOARD]), ('compat_message', 'skip safety checks')]:
            meta = metadata()
            meta[key] = value
            with self.subTest(key=key), self.assertRaises(gate.ValidationError):
                self.validate(fixture(meta=meta), meta)

    def test_wrong_board_and_extra_board_compatible(self):
        for compatible in [b'gemtek,xr1710g-ubi\0airoha,an7581\0airoha,en7581\0',
                           b'gemtek,w1701k-ubi\0airoha,an7581\0airoha,en7581\0',
                           b'gemtek,w1700k-ubi\0gemtek,xr1710g-ubi\0airoha,an7581\0airoha,en7581\0']:
            with self.subTest(compatible=compatible):
                self.reject_dt(lambda dt: dt['/'].__setitem__('compatible', compatible), 'wrong compatible')

    def test_all_partition_boundaries_and_protection(self):
        for _, (offset, size, ro) in gate.PARTITIONS.items():
            path = gate.PARTITION_PARENT + '/partition@' + format(offset, 'x')
            with self.subTest(partition=path, fault='boundary'):
                self.reject_dt(lambda dt: dt[path].__setitem__('reg', u32(offset, size - 0x1000)), 'wrong reg')
            with self.subTest(partition=path, fault='protection'):
                self.reject_dt(lambda dt: dt[path].pop('read-only') if ro else
                               dt[path].__setitem__('read-only', b''), 'protection mismatch')

    def test_missing_extra_duplicate_partition(self):
        path = gate.PARTITION_PARENT + '/partition@0'
        self.reject_dt(lambda dt: dt.pop(path), 'Missing UBI2 partition')
        self.reject_dt(lambda dt: dt.__setitem__(gate.PARTITION_PARENT + '/extra',
                                                {'label': text('extra'), 'reg': u32(0, 4096)}), 'Unexpected')
        self.reject_dt(lambda dt: dt.__setitem__(gate.PARTITION_PARENT + '/duplicate',
                                                copy.deepcopy(dt[path])), 'duplicate')

    def test_rootdisk_and_bootargs_contract(self):
        self.reject_dt(lambda dt: dt['/chosen'].__setitem__('rootdisk', u32(20)), 'rootdisk')
        self.reject_dt(lambda dt: dt['/chosen'].__setitem__('rootdisk', u32(999)), 'dangling')
        for args in ['root=/dev/fit0 rootwait', 'ubi.block=0,fit root=/dev/mtdblock0 rootwait',
                     'ubi.block=0,fit root=/dev/fit0 root=/dev/other rootwait']:
            with self.subTest(args=args):
                self.reject_dt(lambda dt: dt['/chosen'].__setitem__('bootargs', text(args)), 'boot arguments')

    def test_factory_eeprom_and_band_links(self):
        wifi = '/soc/pcie@1fc00000/pcie@0,0/mt7996@0,0'
        self.reject_dt(lambda dt: dt[wifi].__setitem__('nvmem-cells', u32(21)), 'EEPROM')
        self.reject_dt(lambda dt: dt[wifi + '/band@2'].__setitem__('nvmem-cells', u32(22, 2)), 'band MAC')

    def test_disabled_parent_and_duplicate_phandle(self):
        self.reject_dt(lambda dt: dt.__setitem__('/soc', {'status': text('disabled')}), 'Disabled')
        self.reject_dt(lambda dt: dt.__setitem__('/duplicate', {'phandle': u32(10)}), 'duplicate DT phandle')

    def test_pcie_x2_contract(self):
        path = '/soc/pcie@1fc00000'
        self.reject_dt(lambda dt: dt[path].__setitem__('num-lanes', u32(1)), 'num-lanes')
        self.reject_dt(lambda dt: dt[path].__setitem__('reg-names', text('pcie-mac')), 'reg-names')
        self.reject_dt(lambda dt: dt[path].__setitem__('resets', u32(30, 48)), 'reset wiring')
        self.reject_dt(lambda dt: dt['/soc/pcie@1fc20000'].__setitem__('status', text('okay')), 'status')

    def test_npu_firmware_memory_and_wiring(self):
        path = '/soc/npu@1e900000'
        self.reject_dt(lambda dt: dt[path].__setitem__('status', text('disabled')), 'Disabled')
        self.reject_dt(lambda dt: dt[path].__setitem__('firmware-name', text('MT7992.bin')), 'firmware-name')
        self.reject_dt(lambda dt: dt[path].__setitem__('memory-region', u32(40, 42, 41, 43, 44)), 'phandle')
        self.reject_dt(lambda dt: dt['/reserved-memory/npu-pkt@8a000000'].pop('no-map'), 'no-map')

    def test_component_identities_config_and_arch(self):
        self.reject_fit(lambda nodes: nodes['/images/kernel-1'].__setitem__('arch', text('arm')), 'arch')
        self.reject_fit(lambda nodes: nodes['/images/fdt-1'].__setitem__('type', text('kernel')), 'type')
        self.reject_fit(lambda nodes: nodes['/images/kernel-1'].__setitem__('entry', u32(0)), 'entry')
        self.reject_fit(lambda nodes: nodes['/configurations/config-1'].__setitem__('fdt', text('wrong')), 'fdt')
        self.reject_fit(lambda nodes: nodes.__setitem__('/configurations/config-2', {}), 'configurations')
        self.reject_fit(lambda nodes: nodes.__setitem__('/images/extra', {}), 'payload names')
        self.reject_fit(lambda nodes: nodes['/images/kernel-1'].__setitem__('data-offset', u32(0)), 'external')

    def test_payload_bounds(self):
        for key, value in [('data-position', 0), ('data-position', 4097), ('data-position', 0xFFFFFFFC),
                            ('data-size', 0), ('data-size', 0xFFFFFFFF)]:
            with self.subTest(key=key, value=value):
                self.reject_fit(lambda nodes: nodes['/images/kernel-1'].__setitem__(key, u32(value)), 'bounds')

    def test_payload_overlap_even_when_hashes_match(self):
        def overlap(nodes):
            first, second = '/images/kernel-1', '/images/fdt-1'
            for key in ('data-position', 'data-size'):
                nodes[second][key] = nodes[first][key]
            for suffix in ('/hash-1', '/hash-2'):
                nodes[second + suffix] = copy.deepcopy(nodes[first + suffix])
        self.reject_fit(overlap, 'Overlapping FIT payloads')

    def test_missing_duplicate_and_bad_hashes(self):
        self.reject_fit(lambda nodes: nodes.pop('/images/kernel-1/hash-2'), 'hash nodes')
        self.reject_fit(lambda nodes: nodes['/images/kernel-1/hash-2'].__setitem__('algo', text('crc32')),
                        'duplicate FIT hash')
        self.reject_fit(lambda nodes: nodes['/images/kernel-1/hash-2'].__setitem__('value', b'\0' * 20),
                        'sha1 payload hash mismatch')

    def test_kernel_version_exact_and_gzip_arm64(self):
        for payload in [kernel('6.18.550'), kernel('6.18.52'), b'invalid', kernel()[:-1],
                        kernel() + gzip.compress(b'extra'), gzip.compress(b'Linux version 6.18.55\n')]:
            with self.subTest(bytes=len(payload)), self.assertRaises(gate.ValidationError):
                self.validate(fixture(kernel_payload=payload))

    def test_kernel_decompression_limit(self):
        with mock.patch.object(gate, 'MAX_KERNEL_BYTES', 64):
            with self.assertRaisesRegex(gate.ValidationError, 'size limit'):
                self.validate(fixture())

    def test_squashfs_header_bounds(self):
        data = bytearray(squashfs())
        struct.pack_into('<Q', data, 40, 1024)
        with self.assertRaisesRegex(gate.ValidationError, 'bytes_used'):
            self.validate(fixture(rootfs=bytes(data)))

    def test_fdt_truncation_offsets_and_overlap(self):
        good = encode_fdt({'/': {'compatible': text('test')}})
        candidates = [good[:20], good[:-1]]
        for index, value in [(0, 0), (2, 0xFFFFFFFC), (3, 56), (4, 41), (5, 16), (9, 0xFFFFFFFF)]:
            bad = bytearray(good)
            struct.pack_into('>I', bad, index * 4, value)
            candidates.append(bytes(bad))
        for bad in candidates:
            with self.subTest(blob=bad[:40].hex()), self.assertRaises(gate.ValidationError):
                gate.fdt(bad)

    def test_fdt_duplicate_property_and_unknown_token(self):
        good = encode_fdt({'/': {'one': b'1234', 'two': b'5678'}})
        bad = bytearray(good)
        # Root begin = 8 bytes; each 4-byte property = 16 bytes.
        struct.pack_into('>I', bad, 56 + 8 + 16 + 8, 0)
        with self.assertRaisesRegex(gate.ValidationError, 'Duplicate FDT property'):
            gate.fdt(bytes(bad))
        bad = bytearray(good)
        struct.pack_into('>I', bad, 56, 0x1234)
        with self.assertRaisesRegex(gate.ValidationError, 'Unknown FDT token'):
            gate.fdt(bytes(bad))


if __name__ == '__main__':
    unittest.main()
