#!/usr/bin/env bash
set -Eeuo pipefail

target=openwrt/bin/targets/airoha/an7581
mapfile -t images < <(find "$target" -maxdepth 1 -name '*gemtek_xr1710g-ubi-squashfs-sysupgrade.itb')
mapfile -t manifests < <(find "$target" -maxdepth 1 -name '*gemtek_xr1710g-ubi.manifest')
[[ ${#images[@]} == 1 && ${#manifests[@]} == 1 ]]
image=${images[0]}; manifest=${manifests[0]}
python3 scripts/xr1710g/verify-config.py "$manifest" --manifest
mkdir -p output/firmware output/build-record /tmp/xr1710g-image-check
openwrt/staging_dir/host/bin/fwtool -i output/build-record/sysupgrade-metadata.json "$image"
python3 scripts/xr1710g/verify-fit.py "$image" /tmp/xr1710g-image-check output/build-record/sysupgrade-metadata.json
# Data-only extraction: dev/console is not a regular file and is never executed.
# Keep the default fatal exit status for every non-excluded extraction error.
unsquashfs -excludes -d /tmp/xr1710g-root /tmp/xr1710g-image-check/rootfs.squashfs dev
root=/tmp/xr1710g-root
python3 scripts/xr1710g/verify-apps.py "$root"
XR_CONFIG_GENERATE_SOURCE="$root/bin/config_generate" python3 scripts/xr1710g/verify-network-defaults.py
cmp "$root/etc/uci-defaults/22_airoha-network-migrate-v4" xr1710g-files/etc/uci-defaults/22_airoha-network-migrate-v4
sh -n "$root/etc/uci-defaults/22_airoha-network-migrate-v4"
test -x "$root/usr/bin/xr1710g-link-report"
# Re-run migration behavior with the image's ACTUAL UCI and dynamic loader.
# All configuration files are isolated host fixtures; no device is contacted.
cat > /tmp/xr1710g-uci-test-wrapper <<'UCIWRAPPER'
#!/bin/sh
mkdir -p "$XR_MIGRATION_ROOT/tmp/uci-deltas"
exec qemu-aarch64 -L "$XR_TEST_FIRMWARE_ROOT" "$XR_TEST_FIRMWARE_ROOT/sbin/uci" \
  -c "$XR_MIGRATION_ROOT/etc/config" -t "$XR_MIGRATION_ROOT/tmp/uci-deltas" "$@"
UCIWRAPPER
chmod 0755 /tmp/xr1710g-uci-test-wrapper
XR_TEST_FIRMWARE_ROOT="$root" XR_TEST_UCI_WRAPPER=/tmp/xr1710g-uci-test-wrapper \
  XR_TEST_MIGRATION_SCRIPT="$root/etc/uci-defaults/22_airoha-network-migrate-v4" \
  python3 scripts/xr1710g/test_migration.py
file "$root/usr/bin/frpc" | grep -q 'ARM aarch64'
qemu-aarch64 "$root/usr/bin/frpc" --version | grep -Fx '0.70.1'
printf '%s\n' 'serverAddr = "127.0.0.1"' 'serverPort = 7000' > /tmp/frpc-verify.toml
# verify parses a fixture and exits; it does not connect to the server.
qemu-aarch64 "$root/usr/bin/frpc" verify -c /tmp/frpc-verify.toml
core="$root/etc/openclash/core/clash_meta"
test -x "$core"
file "$core" | grep -q 'ARM aarch64'
gzip -dc /tmp/mihomo.gz | cmp - "$core"
# The actual image must have both requested UIs and no provisioning/extra UI.
test -f "$root/www/luci-static/resources/view/airoha_npu/status.js"
test -f "$root/www/luci-static/resources/view/fan/status.js"
test ! -e "$root/www/luci-static/resources/view/airoha_flowsense"
test ! -e "$root/usr/libexec/rpcd/luci.airoha_flowsense"
test ! -e "$root/usr/libexec/npu-jitter-daemon"
test ! -e "$root/root/.ssh"
test ! -e "$root/etc/config/wireless"
if find "$root/etc/dropbear" -name 'dropbear_*_host_key' -print -quit 2>/dev/null | grep -q .; then
  echo 'Pre-generated SSH host key detected'; exit 1
fi
if find "$root/etc/openclash/config" -type f -print -quit 2>/dev/null | grep -q .; then
  echo 'Unexpected embedded OpenClash configuration'; exit 1
fi
# The owner explicitly requested reference out-of-box Wi-Fi and login defaults.
cmp "$root/etc/board.d/03_wifi_defaults" openwrt/package/network/config/airoha-an7581-mt7996-board/files/etc/board.d/03_wifi_defaults
cmp "$root/etc/uci-defaults/03_wireless" openwrt/package/network/config/airoha-an7581-mt7996-board/files/etc/uci-defaults/03_wireless
test "$(grep -c "disabled='0'" "$root/etc/uci-defaults/03_wireless")" = 3
grep -Fq 'gemtek,xr1710g-ubi' "$root/etc/board.d/05_compat-version"
kernel_config=$(find openwrt/build_dir/target-aarch64_cortex-a53_musl/linux-airoha_an7581 -path '*/linux-6.18.52/.config' -print -quit)
test -n "$kernel_config"
bash openwrt/scripts/check-gemtek-profile-isolation.sh --config openwrt/.config --kernel-config "$kernel_config" --manifest "$manifest"
cp "$image" "$manifest" output/firmware/
cp /tmp/xr1710g-image-check/fit-validation.json /tmp/xr1710g-image-check/device.dtb output/build-record/
cp "$kernel_config" output/build-record/kernel.config
mkdir -p output/build-record/pcs-source
cp "$(dirname "$kernel_config")"/drivers/net/pcs/airoha/pcs-{airoha-common,an7581}.c output/build-record/pcs-source/
cp "$(dirname "$kernel_config")"/drivers/net/pcs/airoha/pcs-airoha.h output/build-record/pcs-source/
for f in profiles.json feeds.buildinfo version.buildinfo config.buildinfo; do
  test -f "$target/$f" && cp "$target/$f" output/build-record/
done
cp openwrt/files/etc/xr1710g-build-info output/build-record/
cp .github/workflows/build-xr1710g-candidate.yml output/build-record/workflow.yml
cp scripts/xr1710g/*.py scripts/xr1710g/*.sh output/build-record/
git -C openwrt/package/OpenClash diff --binary > output/build-record/openclash-packaging.patch
for feed in packages luci routing telephony; do
  git -C "openwrt/feeds/$feed" diff --binary > "output/build-record/feed-$feed.patch"
done
printf '%s\n' "build_definition=$GITHUB_SHA" "source=$SOURCE_URL" "source_commit=$SOURCE_COMMIT" \
  "openclash_commit=$OPENCLASH_COMMIT" "argon_commit=$ARGON_COMMIT" "mihomo_sha256=$MIHOMO_SHA256" \
  'kernel=6.18.52' 'mt76_commit=be5ce7910521492d4a2e4ce7ee3843680a46c047' \
  'pcs_patch_sha256=8059da57402c1c975d0cc3997c7d902f0160746e733db33bf687444defceac4a' 'frpc_version=0.70.1' 'wan_hardware_retest=PENDING' \
  "ci_run=https://github.com/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID" \
  'status=BUILD CANDIDATE; HARDWARE NOT VALIDATED; NO FLASH RECOMMENDATION' \
  > output/build-record/provenance.txt
cat > output/READ-ME-FIRST.txt <<'EOF'
XR1710G UBI2 build candidate, not a hardware-validated release.
Only Gemtek/Brightspeed XR1710G. Never W1700K/W1701K/XG2010G.
The source uses the exact naoki reference build commit and matching feeds,
with native Linux 6.18.52 and MT76, plus an audited final PCS repair restoring
E2 calibration and XR1710G carrier safeguards from the working .44 lineage.
The previous 172d349 candidate failed hardware WAN testing (NO-CARRIER).
This new revision requires an actual WAN retest; CI success is not that retest.
Vendor, chainloader and reserved BMT partitions are read-only.
Compatibility version 2.0 retains the installed UBI2 layout contract;
it does not validate the actual device bootloader, partition map or backups.
Reference Wi-Fi SSIDs, broadcast/authentication, country and login defaults are
preserved at the owner's request. Change default credentials and select the
correct local Wi-Fi country after first login.
FRP client and native LuCI File Manager are included. FRP has no configured
server, token, sample tunnel or web-admin listener and boot start is disabled.
File Manager retains authenticated LuCI admin access; no WAN service is added.
No personal password, subscription or SSH host key is embedded.
Reference embedded root password is empty, but existing bootloader/environment
provisioning may supply Wi-Fi/admin credentials or SSH keys at first boot.

PASSED: source/feed pins, config/package gates, kernel repair and native MT76 prepare,
full compile, profile isolation, manifest, fwtool metadata, FIT payload hashes,
compiled DTB partition/boot contract, actual squashfs regular-file contents
(device nodes are not materialized), Mihomo checksum.
NOT RUN: boot, sysupgrade on the device, LAN/WAN, Wi-Fi 7, offload/OpenClash
interaction, temperature/fan response, reboot persistence, soak or recovery.

Before any flashing: verify actual device board, compatibility version,
MTD/UBI layout and chainloader; obtain and verify backups and a working rescue
procedure. Keep the installed known-working firmware and its SHA256 available.
Never use sysupgrade -F or write the vendor/chainloader/BMT partitions.
Do not assume a filename or a successful CI build proves safe migration.
EOF
(cd output && find firmware build-record -type f -exec sha256sum '{}' + | sort -k2 > SHA256SUMS && sha256sum -c SHA256SUMS)
echo 'Candidate static software/image checks passed. Hardware testing has NOT run.'
