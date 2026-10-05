#!/usr/bin/env bash
set -Eeuo pipefail
target=openwrt/bin/targets/airoha/an7581
mapfile -t images < <(find "$target" -maxdepth 1 -name '*gemtek_w1700k-ubi-squashfs-sysupgrade.itb')
mapfile -t manifests < <(find "$target" -maxdepth 1 -name '*gemtek_w1700k-ubi.manifest')
[[ ${#images[@]} == 1 && ${#manifests[@]} == 1 ]]
image=${images[0]}; manifest=${manifests[0]}
python3 w1700k-slim/verify_config.py "$manifest"
mkdir -p output/firmware output/build-record /tmp/w1700k-image-check
openwrt/staging_dir/host/bin/fwtool -i output/build-record/sysupgrade-metadata.json "$image"
python3 w1700k-slim/verify_artifact.py "$image" /tmp/w1700k-image-check output/build-record/sysupgrade-metadata.json --mode candidate --metadata-source fwtool
unsquashfs -excludes -d /tmp/w1700k-root /tmp/w1700k-image-check/rootfs.squashfs dev
root=/tmp/w1700k-root
core="$root/etc/openclash/core/clash_meta"
test -x "$core"
file "$core" | grep -q 'ARM aarch64'
gzip -dc /tmp/mihomo.gz | cmp - "$core"
qemu-aarch64 "$core" -v | tee output/build-record/mihomo-version.txt
grep -Fq 'v1.19.32' output/build-record/mihomo-version.txt
cat > /tmp/mihomo-test.yaml <<'EOF'
mixed-port: 17890
mode: direct
log-level: warning
ipv6: false
proxies: []
proxy-groups: []
rules:
  - MATCH,DIRECT
EOF
qemu-aarch64 "$core" -t -d /tmp/mihomo-test -f /tmp/mihomo-test.yaml 2>&1 | tee output/build-record/mihomo-config-test.txt
python3 w1700k-slim/verify_rootfs.py "$root" openwrt output/build-record/rootfs-validation.json
cp "$image" "$manifest" output/firmware/
cp /tmp/w1700k-image-check/fit-validation.json /tmp/w1700k-image-check/device.dtb output/build-record/
kernel_config=$(find openwrt/build_dir/target-aarch64_cortex-a53_musl/linux-airoha_an7581 -path '*/linux-6.18.55/.config' -print -quit)
test -n "$kernel_config"
cp "$kernel_config" output/build-record/kernel.config
for f in profiles.json feeds.buildinfo version.buildinfo config.buildinfo; do
  test -f "$target/$f" && cp "$target/$f" output/build-record/
done
cp w1700k-slim/sources.lock.json .github/workflows/build-w1700k-slim.yml output/build-record/
git -C openwrt/package/OpenClash diff --binary > output/build-record/openclash-packaging.patch
printf '%s\n' "build_definition=$GITHUB_SHA" "source=$SOURCE_URL" "source_commit=$SOURCE_COMMIT" \
  "ci_run=https://github.com/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID" \
  'status=BUILD CANDIDATE; HARDWARE NOT VALIDATED; NO FLASH RECOMMENDATION' > output/build-record/provenance.txt
cp w1700k-slim/CANDIDATE-NOTES.md output/READ-ME-FIRST.md
(cd output && find firmware build-record -type f -exec sha256sum '{}' + | sort -k2 > SHA256SUMS && sha256sum -c SHA256SUMS)
echo 'W1700K software/image gates passed. No hardware validation or flashing has run.'
