#!/usr/bin/env python3
"""Fail-closed seed/expanded config and built package manifest gates."""
import re
import sys
from pathlib import Path

if not __debug__:
    raise RuntimeError('This gate must run without Python optimization')


REQUIRED = set('''fitblk fit-check-sign fwtool ubi-utils uboot-envtools
kmod-airoha-eth kmod-airoha-npu kmod-dsa-mt7530 kmod-dsa-mt7530-mmio
kmod-phy-realtek rtl826x-firmware rtl8261c-firmware kmod-hwmon-nct7802
airoha-en7581-mt7996-npu-firmware kmod-mt7996e kmod-mt7996-firmware
wireless-regdb wpad-openssl firewall4 kmod-nft-bridge kmod-nft-offload
luci-base luci-app-firewall luci-app-openclash luci-theme-argon
luci-app-upnp miniupnpd-nftables coreutils-nohup etherwake irqbalance
luci-app-irqbalance luci-app-filemanager luci-app-airoha-npu
luci-app-w1700k-fancontrol kmod-inet-diag kmod-nft-tproxy kmod-tun
dnsmasq-full ruby-yaml luci-i18n-base-zh-cn luci-i18n-firewall-zh-cn
luci-i18n-upnp-zh-cn luci-i18n-irqbalance-zh-cn luci-i18n-filemanager-zh-cn
luci-i18n-airoha-npu-zh-cn luci-i18n-w1700k-fancontrol-zh-cn'''.split())
FORBIDDEN = set('''fastfetch iperf3 librespeed-go luci-app-netspeedtest
luci-app-wol luci-i18n-wol-zh-cn ttyd luci-app-ttyd nano luci-app-attendedsysupgrade attendedsysupgrade-common
owut luci-app-airoha-flowsense luci-app-mlo luci-app-wifi7
luci-theme-bootstrap luci-theme-footstrap luci-app-package-manager
relayd luci-proto-relay kmod-wireguard wireguard-tools luci-proto-wireguard'''.split())
def frp(name):
    return bool(re.search(r'(^|-)frp[cs]?($|-)', name))

def check_packages(packages):
    missing = REQUIRED - packages
    banned = (FORBIDDEN & packages) | {p for p in packages if frp(p)}
    assert not missing, f'Missing required packages: {sorted(missing)}'
    assert not banned, f'Forbidden packages: {sorted(banned)}'

def check_config(content):
    values = dict(re.findall(r'^(CONFIG_[^=\s]+)=(.*)$', content, re.M))
    devices = {k for k, v in values.items() if '_DEVICE_' in k and v == 'y'}
    assert devices == {'CONFIG_TARGET_airoha_an7581_DEVICE_gemtek_w1700k-ubi'}, devices
    assert values.get('CONFIG_TARGET_airoha') == values.get('CONFIG_TARGET_airoha_an7581') == 'y'
    assert values.get('CONFIG_TARGET_ROOTFS_SQUASHFS') == 'y'
    assert values.get('CONFIG_TARGET_ROOTFS_INITRAMFS') != 'y'
    assert values.get('CONFIG_ALL_KMODS') != 'y'
    assert values.get('CONFIG_SIGNED_PACKAGES') == 'y'
    packages = {k[len('CONFIG_PACKAGE_'):] for k, v in values.items() if k.startswith('CONFIG_PACKAGE_') and v == 'y'}
    selected = {k[len('CONFIG_PACKAGE_'):] for k, v in values.items() if k.startswith('CONFIG_PACKAGE_') and v in ('y','m')}
    assert not any(frp(p) for p in selected), 'FRP may not even be built as an optional module'
    check_packages(packages)

if __name__ == '__main__':
    path = Path(sys.argv[1])
    if path.suffix == '.manifest':
        check_packages({line.split(' - ', 1)[0] for line in path.read_text().splitlines() if line})
    else:
        check_config(path.read_text())
    print('W1700K profile and package gate passed; this does not prove a build or hardware boot')
