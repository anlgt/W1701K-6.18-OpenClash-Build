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
unsquashfs -d /tmp/xr1710g-root /tmp/xr1710g-image-check/rootfs.squashfs
root=/tmp/xr1710g-root
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
for f in profiles.json feeds.buildinfo version.buildinfo config.buildinfo; do
  test -f "$target/$f" && cp "$target/$f" output/build-record/
done
cp openwrt/files/etc/xr1710g-build-info output/build-record/
cp .github/workflows/build-xr1710g-candidate.yml output/build-record/workflow.yml
cp scripts/xr1710g/*.py scripts/xr1710g/package-output.sh output/build-record/
for feed in packages luci routing telephony; do
  git -C "openwrt/feeds/$feed" diff --binary > "output/build-record/feed-$feed.patch"
done
printf '%s\n' "build_definition=$GITHUB_SHA" "source=$SOURCE_URL" "source_commit=$SOURCE_COMMIT" \
  "openclash_commit=$OPENCLASH_COMMIT" "argon_commit=$ARGON_COMMIT" "mihomo_sha256=$MIHOMO_SHA256" \
  'kernel=6.18.52' 'mt76_commit=be5ce7910521492d4a2e4ce7ee3843680a46c047' \
  "ci_run=https://github.com/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID" \
  'status=BUILD CANDIDATE; HARDWARE NOT VALIDATED; NO FLASH RECOMMENDATION' \
  > output/build-record/provenance.txt
cat > output/READ-ME-FIRST.txt <<'EOF'
XR1710G UBI2 build candidate, not a hardware-validated release.
Only Gemtek/Brightspeed XR1710G. Never W1700K/W1701K/XG2010G.
The source uses the exact naoki reference build commit and matching feeds,
with the native Linux 6.18.52 and MT76 patch sets unchanged.
Vendor, chainloader and reserved BMT partitions are read-only.
Compatibility version 2.0 retains the installed UBI2 layout contract;
it does not validate the actual device bootloader, partition map or backups.
Reference Wi-Fi SSIDs, broadcast/authentication, country and login defaults are
preserved at the owner's request. Change default credentials and select the
correct local Wi-Fi country after first login.
No private password, subscription or SSH host key is embedded.

PASSED: source/feed pins, config/package gates, native kernel and MT76 prepare,
full compile, profile isolation, manifest, fwtool metadata, FIT payload hashes,
compiled DTB partition/boot contract, actual squashfs contents, Mihomo checksum.
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
