#!/usr/bin/env python3
"""Check resolved configuration or the actually built manifest, never the seed."""
import sys
from pathlib import Path
required = '''apk-mbedtls luci-base luci-mod-admin-full luci-app-firewall luci-compat luci-i18n-base-zh-cn luci-i18n-firewall-zh-cn luci-theme-argon luci-app-openclash bash ca-bundle curl dnsmasq-full ip-full kmod-inet-diag kmod-nft-tproxy kmod-tun ruby ruby-yaml unzip luci-app-upnp luci-i18n-upnp-zh-cn miniupnpd-nftables coreutils-nohup etherwake irqbalance luci-app-irqbalance luci-i18n-irqbalance-zh-cn luci-app-airoha luci-i18n-airoha-zh-cn luci-app-airoha-fancontrol luci-i18n-airoha-fancontrol-zh-cn airoha-an7581-mt7996-board airoha-en7581-mt7996-npu-firmware fitblk kmod-hwmon-nct7802 kmod-airoha-i2c kmod-mt7996e kmod-mt7996-firmware kmod-nft-offload kmod-phy-realtek rtl826x-firmware wpad-mbedtls'''.split()
forbidden = '''luci-theme-bootstrap luci-theme-glass luci-app-argon-config luci-app-package-manager luci-app-airoha-factory luci-app-airoha-recovery luci-app-airoha-flowsense luci-app-mlo luci-app-attendedsysupgrade ethtool-full iperf3 kmod-airoha-net-debug mdio-tools openssh-sftp-server phytool tcpdump btop kmod-wireguard wireguard-tools luci-proto-wireguard airoha-pon-manager airoha-pon-firmware kmod-airoha-xpon-en757x wpad-basic-mbedtls'''.split()
text = Path(sys.argv[1]).read_text()
manifest = '--manifest' in sys.argv
selected = {line.split(' - ', 1)[0] for line in text.splitlines()} if manifest else {line[len('CONFIG_PACKAGE_'):-2] for line in text.splitlines() if line.startswith('CONFIG_PACKAGE_') and line.endswith('=y')}
errors = [f'Missing required package: {p}' for p in required if p not in selected]
errors += [f'Forbidden package: {p}' for p in forbidden if p in selected]
if not manifest:
    for symbol in ('TARGET_airoha', 'TARGET_airoha_an7581', 'TARGET_airoha_an7581_DEVICE_gemtek_xr1710g-ubi', 'USE_APK', 'TARGET_ROOTFS_SQUASHFS', 'BUSYBOX_CONFIG_DEVMEM', 'DRIVER_11BE_SUPPORT', 'PACKAGE_dnsmasq_full_nftset'):
        if f'CONFIG_{symbol}=y' not in text.splitlines(): errors.append(f'Missing required config: {symbol}')
    if 'CONFIG_TARGET_ROOTFS_INITRAMFS=y' in text: errors.append('Unexpected initramfs enabled')
    targets = [line for line in text.splitlines() if line.startswith('CONFIG_TARGET_') and '_DEVICE_' in line and line.endswith('=y')]
    if targets != ['CONFIG_TARGET_airoha_an7581_DEVICE_gemtek_xr1710g-ubi=y']: errors.append(f'Wrong target device selection: {targets}')
else:
    import re
    if not re.search(r'^kernel - 6\.18\.52[~+\-\s]', text, re.M): errors.append('Wrong kernel version')
if {p for p in selected if p.startswith('luci-theme-')} != {'luci-theme-argon'}: errors.append('Argon is not the sole theme')
if errors: raise SystemExit('\n'.join(errors))
print(f'{"Manifest" if manifest else "Resolved config"} required/excluded package checks passed')
