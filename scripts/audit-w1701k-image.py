#!/usr/bin/env python3
"""Check the actual W1701K firmware on the Linux Actions runner before release."""
import argparse
import hashlib
import json
import lzma
import os
import re
import stat
import struct
import subprocess
import tarfile
import tempfile
import zlib
from pathlib import Path


def run(*args):
    result = subprocess.run([str(a) for a in args], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode:
        # Keep extractor/runtime diagnostics visible rather than only a Python
        # traceback. Commands here never print the wireless key.
        print(result.stdout[-12000:], flush=True)
        result.check_returncode()
    return result.stdout


def require(condition, message):
    if not condition:
        raise SystemExit('Firmware audit failed: ' + message)


def fdt(blob):
    require(len(blob) >= 40, 'truncated FDT')
    magic, size, off, strings, *_ = struct.unpack_from('>10I', blob)
    require(magic == 0xd00dfeed and size <= len(blob), 'invalid FDT header')
    nodes, stack = {}, []
    while off < size:
        token = struct.unpack_from('>I', blob, off)[0]
        off += 4
        if token == 1:
            end = blob.index(b'\0', off)
            stack.append(blob[off:end].decode())
            nodes['/' + '/'.join(stack[1:])] = {}
            off = (end + 4) & ~3
        elif token == 2:
            stack.pop()
        elif token == 3:
            length, nameoff = struct.unpack_from('>II', blob, off)
            off += 8
            name = blob[strings + nameoff:blob.index(b'\0', strings + nameoff)].decode()
            nodes['/' + '/'.join(stack[1:])][name] = blob[off:off + length]
            off = (off + length + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            return nodes
        else:
            raise SystemExit(f'Unknown FDT token: {token}')
    raise SystemExit('Missing FDT end token')


def string(value):
    return value.rstrip(b'\0').decode()


def cells(value):
    return struct.unpack('>' + 'I' * (len(value) // 4), value)


def unpack_initrd(data, root):
    if data.startswith(b'\xfd7zXZ\0'):
        data = lzma.decompress(data)
    require(data.startswith(b'070701'), 'initrd is not newc CPIO/XZ')
    root.mkdir()
    off, links = 0, {}
    while off + 110 <= len(data):
        require(data[off:off + 6] in (b'070701', b'070702'), 'corrupt initrd CPIO header')
        fields = [int(data[off + 6 + i * 8:off + 14 + i * 8], 16) for i in range(13)]
        ino, mode, _, _, nlink, _, size, major, minor, _, _, namesize, _ = fields
        off += 110
        name = data[off:off + namesize - 1].decode()
        off = (off + namesize + 3) & ~3
        contents = data[off:off + size]
        off = (off + size + 3) & ~3
        if name == 'TRAILER!!!':
            break
        require(not name.startswith('/') and '..' not in Path(name).parts, 'unsafe initrd path')
        target = root / name
        # No archive parent may point outside the temporary extraction root.
        require(target.parent.resolve().is_relative_to(root.resolve()), 'initrd parent symlink escape')
        target.parent.mkdir(parents=True, exist_ok=True)
        if stat.S_ISDIR(mode):
            target.mkdir(exist_ok=True)
        elif stat.S_ISLNK(mode):
            target.symlink_to(contents.decode())
        elif stat.S_ISREG(mode):
            target.write_bytes(contents)
            target.chmod(mode & 0o777)
            if nlink > 1:
                group = links.setdefault((major, minor, ino), {'paths': [], 'data': b''})
                group['paths'].append(target)
                if size:
                    group['data'] = contents
    else:
        raise SystemExit('Missing initrd CPIO trailer')
    for group in links.values():
        for target in group['paths']:
            target.write_bytes(group['data'])


def check_fit(blob, ram, root=None):
    tree = fdt(blob)
    default = string(tree['/configurations']['default'])
    config = tree['/configurations/' + default]
    kinds, dtb = [], None
    for prop in ('kernel', 'fdt', 'ramdisk'):
        if prop not in config:
            require(prop == 'ramdisk' and not ram, f'FIT missing {prop}')
            continue
        path = '/images/' + string(config[prop])
        node = tree[path]
        require(string(node['type']) == {'kernel': 'kernel', 'fdt': 'flat_dt', 'ramdisk': 'ramdisk'}[prop],
                f'wrong FIT image type for {prop}')
        require('data' in node, f'FIT {prop} must contain inline data')
        data = node['data']
        require(bool(data), f'empty FIT {prop}')
        hashes = [(p, n) for p, n in tree.items() if p.startswith(path + '/') and 'algo' in n]
        require(bool(hashes), f'FIT {prop} lacks a hash')
        for _, h in hashes:
            algo = string(h['algo'])
            if algo == 'crc32':
                require(struct.pack('>I', zlib.crc32(data)) == h['value'], f'FIT {prop} CRC mismatch')
            elif algo in hashlib.algorithms_available:
                require(hashlib.new(algo, data).digest() == h['value'], f'FIT {prop} hash mismatch')
            else:
                raise SystemExit(f'Unsupported FIT hash: {algo}')
        kinds.append(string(node['type']))
        if prop == 'kernel':
            require(string(node['arch']) == 'arm64', 'kernel architecture is not ARM64')
            require(string(node['os']) == 'linux', 'kernel OS is not Linux')
            for field in ('load', 'entry'):
                require(0x80200000 <= int.from_bytes(node[field], 'big') < 0x100000000,
                        f'kernel {field} lies outside W1701K usable RAM')
        if prop == 'fdt':
            require(string(node.get('compression', b'none')) == 'none', 'compressed DTB needs review')
            dtb = fdt(data)
        if prop == 'ramdisk' and root is not None:
            unpack_initrd(data, root)
    require(dtb is not None, 'no embedded board DTB')
    require('gemtek,w1701k' in string(dtb['/']['compatible']).split('\0'), 'wrong board compatible')
    expected = {'bootloader': (0, 0x200000), 'uenv': (0x200000, 0x200000),
                'dsd': (0x400000, 0x1000), 'factory': (0x401000, 0x1ff000),
                'kernel': (0x600000, 0x1000000), 'rootfs': (0x1600000, 0x1e800000),
                'reserved_bmt': (0x1fe00000, 0x200000)}
    partitions = {string(n['label']): cells(n['reg']) for n in dtb.values()
                  if 'label' in n and 'reg' in n and string(n['label']) in expected}
    require(partitions == expected, 'NAND partition layout differs from tested W1701K')
    pcie = next((n for p, n in dtb.items() if p.endswith('/pcie@1fc00000')), {})
    require(cells(pcie.get('num-lanes', b'')) == (2,), 'PCIe x2 is missing')
    require(pcie.get('reg-names') == b'pcie-mac\0sec-pcie-mac\0', 'secondary PCIe registers missing')
    require('airoha,scu' in pcie, 'PCIe SCU binding missing')
    memory = next((n for p, n in dtb.items() if p == '/memory@80000000'), {})
    require(cells(memory.get('reg', b'')) == (0, 0x80000000, 0, 0x80000000), 'unexpected RAM size')
    require(cells(dtb['/chosen'].get('linux,usable-memory-range', b'')) ==
            (0, 0x80200000, 0, 0x7fe00000), 'ATF memory exclusion differs from tested W1701K')
    if ram:
        require('ramdisk' in kinds, 'RAM-test image has no initrd')
    return {'fit_images': kinds, 'partitions': partitions, 'pcie_lanes': 2, 'ram_bytes': 0x80000000}


def virtual(root, path):
    # Resolve target-root symlinks without following absolute links into the host.
    parts = list(Path('/' + path.lstrip('/')).parts[1:])
    resolved = []
    hops = 0
    while parts:
        piece = parts.pop(0)
        if piece in ('', '.'):
            continue
        if piece == '..':
            require(bool(resolved), 'symlink escapes target root')
            resolved.pop()
            continue
        current = root.joinpath(*resolved, piece)
        if current.is_symlink():
            hops += 1
            require(hops < 64, 'symlink loop')
            target = os.readlink(current)
            if target.startswith('/'):
                resolved = []
            parts = target.split('/') + parts
        else:
            resolved.append(piece)
    return root.joinpath(*resolved)


def check_root(root, full):
    essentials = ('sbin/init', 'sbin/ubusd', 'sbin/netifd', 'sbin/uci', 'usr/sbin/dropbear',
                  'usr/sbin/uhttpd', 'usr/sbin/dnsmasq', 'sbin/fw4', 'usr/sbin/pppd',
                  'usr/sbin/odhcpd', 'usr/sbin/hostapd', 'usr/sbin/wpa_supplicant',
                  'usr/sbin/iw', 'usr/bin/curl', 'usr/bin/lspci', 'usr/bin/w1701k-acceptance',
                  'usr/libexec/w1701k-network-defaults', 'lib/upgrade/platform.sh',
                  'lib/firmware/airoha/EthMD32.dm.bin', 'lib/firmware/airoha/EthMD32.DSP.bin',
                  'lib/firmware/airoha/en7581_MT7996_npu_data.bin',
                  'lib/firmware/airoha/en7581_MT7996_npu_rv32.bin')
    for name in essentials:
        require(virtual(root, name).is_file(), f'missing runtime {name}')
    for directory, pattern in (('lib/firmware', 'mt7996_wm.bin'), ('lib/firmware', 'mt7996_wa.bin'),
                               ('lib/firmware', 'mt7996_dsp.bin'), ('lib/modules', 'mt7996e.ko*')):
        require(any((root / directory).rglob(pattern)), f'missing hardware file {pattern}')
    key = root / 'etc/w1701k-wifi-key'
    require(key.is_file() and key.stat().st_mode & 0o077 == 0, 'wireless key file permissions are not private')
    require(8 <= len(key.read_text().rstrip('\n')) <= 63, 'invalid wireless key length')
    require(key.read_bytes() == Path('openwrt/files/etc/w1701k-wifi-key').read_bytes(),
            'image wireless key differs from the build injection')
    script = 'usr/libexec/w1701k-network-defaults'
    require((root / script).read_bytes() == (Path('w1701k-refresh-files') / script).read_bytes(),
            'tested network defaults script missing from image')
    elf_count = 0
    for path in root.rglob('*'):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open('rb') as handle:
            header = handle.read(20)
        if not header.startswith(b'\x7fELF'):
            continue
        elf_count += 1
        require(header[4] == 2 and header[5] == 1 and header[18:20] == b'\xb7\x00',
                f'non-aarch64 ELF: {path.relative_to(root)}')
        dynamic = run('readelf', '-d', path)
        for name in re.findall(r'Shared library: \[(.*?)\]', dynamic):
            require(any(virtual(root, d + '/' + name).is_file() for d in ('lib', 'usr/lib')),
                    f'missing {name} needed by {path.relative_to(root)}')
        interpreter = re.search(r'Requesting program interpreter: (.*?)\]', run('readelf', '-l', path))
        if interpreter:
            require(virtual(root, interpreter[1]).is_file(), f'missing ELF interpreter for {path.relative_to(root)}')
    require(elf_count > 20, 'rootfs ELF inventory is implausibly small')
    core = virtual(root, 'etc/openclash/core/clash_meta')
    if full:
        require(core.is_file(), 'Mihomo core missing')
        version = run('qemu-aarch64', '-L', root, core, '-v')
        require('1.19.33' in version, 'unexpected Mihomo runtime version')
    else:
        require(not core.exists(), 'Mihomo unexpectedly present in Lite image')
    modules = list((root / 'lib/modules').glob('*'))
    require(len(modules) == 1 and modules[0].name.startswith('6.18.60'), 'unexpected kernel module directory')
    for module in modules[0].rglob('*.ko'):
        magic = run('modinfo', '-F', 'vermagic', module).strip()
        require(magic.split()[0] == modules[0].name, f'kernel vermagic mismatch for {module.name}')
    return {'elf_files_checked': elf_count, 'kernel_modules': modules[0].name,
            'rootfs_dependencies': 'passed', 'mihomo_runtime_version': '1.19.33' if full else 'not included'}


def check_kernel(openwrt, output):
    configs = list((openwrt / 'build_dir').glob('target-*/linux-airoha_an7581/linux-6.18.60/.config'))
    require(len(configs) == 1, 'cannot identify actual compiled kernel configuration')
    text = configs[0].read_text()
    selected = dict(line.split('=', 1) for line in text.splitlines() if line.startswith('CONFIG_') and '=' in line)
    builtins = ('CONFIG_ARM64', 'CONFIG_ARCH_AIROHA', 'CONFIG_CPU_FREQ_DEFAULT_GOV_ONDEMAND',
                'CONFIG_PCIE_MEDIATEK_GEN3', 'CONFIG_PHY_AIROHA_PCIE')
    for key in builtins:
        require(selected.get(key) == 'y', f'kernel feature missing: {key}')
    for key in ('CONFIG_NET_AIROHA', 'CONFIG_NET_AIROHA_NPU', 'CONFIG_NET_DSA_MT7530_MMIO',
                'CONFIG_I2C_MT7621', 'CONFIG_NVMEM_LAYOUT_ASCII_ENV'):
        require(selected.get(key) in ('y', 'm'), f'kernel driver missing: {key}')
    require(selected.get('CONFIG_NR_CPUS') == '4', 'kernel does not support all four CPU cores')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_name(output.stem + '-kernel.config').write_text(text)
    return {'kernel_version': '6.18.60', 'kernel_config_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'kernel_required_features': {k: selected[k] for k in builtins}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--flavour', choices=('full', 'lite'), required=True)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    full = args.flavour == 'full'
    openwrt = Path('openwrt')
    report = {'flavour': args.flavour, 'image_sha256': hashlib.file_digest(args.image.open('rb'), 'sha256').hexdigest(),
              'hardware_boot_test': 'not performed; RAM acceptance is required'}
    report.update(check_kernel(openwrt, args.output))
    with tempfile.TemporaryDirectory(dir='.') as directory:
        tmp = Path(directory).resolve()
        if full:
            meta = tmp / 'metadata.json'
            run(openwrt / 'staging_dir/host/bin/fwtool', '-i', meta, args.image)
            metadata = json.loads(meta.read_text())
            require(metadata.get('supported_devices') == ['gemtek,w1701k'], 'wrong sysupgrade target metadata')
            with tarfile.open(args.image) as archive:
                kernel = [m for m in archive if m.isfile() and m.name.endswith('/kernel')]
                roots = [m for m in archive if m.isfile() and m.name.endswith('/root')]
                require(len(kernel) == len(roots) == 1, 'unexpected sysupgrade tar contents')
                require(0 < kernel[0].size <= 16 * 1024 * 1024, 'kernel exceeds W1701K 16MiB partition')
                report.update(check_fit(archive.extractfile(kernel[0]).read(), False))
                squash = tmp / 'root.squashfs'
                squash.write_bytes(archive.extractfile(roots[0]).read())
            target = tmp / 'rootfs'
            run('unsquashfs', '-no-progress', '-d', target, squash)
            report.update(check_root(target, True))
            report['supported_devices'] = metadata['supported_devices']
        else:
            target = tmp / 'rootfs'
            report.update(check_fit(args.image.read_bytes(), True, target))
            report.update(check_root(target, False))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(f'PASS: {args.flavour} firmware architecture, dependencies, board layout and FIT integrity')


if __name__ == '__main__':
    main()
