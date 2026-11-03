#!/usr/bin/env python3
"""Restore the tested W1701K layout on the current Airoha source tree."""
import re
import subprocess
from pathlib import Path


def legacy(path):
    return subprocess.check_output([
        'git', 'show', '465633077348b8015e5282193af2b9427b6a8b78:' + Path(path).as_posix()
    ]).decode()


airoha = Path('target/linux/airoha')
dts = airoha / 'dts/an7581-w1701k.dts'
if dts.exists():
    raise SystemExit('Review upstream W1701K support before replacing its DTS')
dts.write_text(legacy(str(dts)) + '''

/* W1701K ATF may lack AVS SMC; register resources for the stock PLL fallback. */
&cpufreq {
	reg = <0x0 0x1fa20000 0x0 0x2c0>, <0x0 0x1efbe000 0x0 0x800>;
	reg-names = "chip-scu", "mcucfg";
};
''', newline='\n')
patch = (Path(__file__).resolve().parents[1] / 'patches/001-w1701k-pcie-x2-6.18.patch').read_text().encode()
subprocess.run(['git', 'apply', '--check'], input=patch, check=True)
subprocess.run(['git', 'apply'], input=patch, check=True)

image = airoha / 'image/an7581.mk'
text = image.read_text()
if 'define Device/gemtek_w1701k\n' in text:
    raise SystemExit('Review upstream W1701K image layout before replacing it')
old = legacy(str(image))
block = re.search(r'define Device/gemtek_w1701k\n.*?TARGET_DEVICES \+= gemtek_w1701k\n', old, re.S).group()
block = block.replace('  $(call Device/FitImageLzma)\n', '''  $(call Device/FitImageLzma)
  DEVICE_DTS := an7581-w1701k
  KERNEL_INITRAMFS := kernel-bin | lzma | \\
\tfit lzma $$(KDIR)/image-$$(firstword $$(DEVICE_DTS)).dtb with-initrd | pad-to 128k
''')
block = block.replace('DEVICE_PACKAGES :=  kmod-i2c-an7581', 'DEVICE_PACKAGES :=')
block = block.replace('  IMAGE/sysupgrade.bin', '  KERNEL_SIZE := 16384k\n  IMAGE/sysupgrade.bin')
image.write_text(text + '\n' + block, newline='\n')

target = airoha / 'Makefile'
text = target.read_text()
if ' ramdisk ' not in text:
    raise SystemExit('Unexpected Airoha RAM disk feature selection')
target.write_text(text.replace(' ramdisk ', ' separate_ramdisk '), newline='\n')

network = airoha / 'an7581/base-files/etc/board.d/02_network'
text = network.read_text()
anchor = '\tgemtek,w1700k-ubi)'
assert text.count(anchor) == 1
text = text.replace(anchor, '\tgemtek,w1701k)\n\t\tucidef_set_interfaces_lan_wan "lan" "wan"\n\t\t;;\n' + anchor)
network.write_text(text, newline='\n')

# This board uses NAND sysupgrade tar, not the UBI/FIT upgrade path of W1700K.
# Do not ask sysupgrade to copy utilities that its image does not install/use.
platform = airoha / 'an7581/base-files/lib/upgrade/platform.sh'
text = platform.read_text()
anchor = "RAMFS_COPY_BIN='fitblk fit_check_sign'"
assert text.count(anchor) == 1
text = text.replace(anchor, anchor + '''
case "$(board_name)" in
gemtek,w1701k) RAMFS_COPY_BIN='' ;;
esac''')
platform.write_text(text, newline='\n')

caldata = airoha / 'base-files/lib/preinit/90_extract_caldata'
assert not caldata.exists()
caldata.write_text(legacy(str(caldata)), newline='\n')

# Keep the board fix with the mt76 package so it is applied to both images.
mt76_patches = Path('package/kernel/mt76/patches')
fem_patch = Path(__file__).resolve().parents[1] / 'patches/mt76/120-w1701k-mixed-fem.patch'
assert not (mt76_patches / fem_patch.name).exists()
(mt76_patches / fem_patch.name).write_bytes(fem_patch.read_bytes())
kernel_patches = sorted((Path(__file__).resolve().parents[1] / 'patches/kernel').glob('*.patch'))
assert len(kernel_patches) == 2
for source in kernel_patches:
    dest = airoha / 'patches-6.18' / source.name
    assert not dest.exists()
    dest.write_bytes(source.read_bytes())
    subprocess.run(['git', 'add', '-N', str(dest)], check=True)

# The new PHY sensor uses hwmon from a module: make the dependency explicit.
modules = Path('package/kernel/linux/modules/netdevices.mk')
text = modules.read_text()
match = re.search(r'define KernelPackage/phy-airoha-en8811h\n.*?\nendef', text, re.S)
assert match and match.group().count('+kmod-libphy') == 1
block = match.group().replace('+kmod-libphy', '+kmod-libphy +kmod-hwmon-core')
modules.write_text(text[:match.start()] + block + text[match.end():], newline='\n')
subprocess.run(['git', 'add', '-N', str(dts), str(caldata)], check=True)
subprocess.run(['git', 'add', '-N', str(mt76_patches / fem_patch.name)], check=True)
subprocess.run(['git', 'diff', '--check'], check=True)
print('Restored W1701K: original NAND layout, PCIe x2, LAN/WAN and calibration')
