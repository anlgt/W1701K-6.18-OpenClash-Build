#!/usr/bin/env bash
# Revalidate immutable CI output; never rebuild, patch, rebrand, deploy or flash it.
set -Eeuo pipefail
umask 022
export PYTHONOPTIMIZE=0
: "${GH_TOKEN:?An ephemeral actions:read GitHub token is required}"
: "${GITHUB_WORKSPACE:?Run this helper from GitHub Actions}"
: "${GITHUB_SHA:?Missing validation commit}"
: "${GITHUB_RUN_ID:?Missing validation run}"
: "${GITHUB_RUN_ATTEMPT:?Missing validation attempt}"
[[ "$GITHUB_REPOSITORY" == anlgt/W1701K-6.18-OpenClash-Build ]]
[[ "$GITHUB_REF" == refs/heads/w1700k-slim-candidate-20261005 ]]
cd "$GITHUB_WORKSPACE"
[[ "$(git rev-parse HEAD)" == "$GITHUB_SHA" ]]
repo=anlgt/W1701K-6.18-OpenClash-Build
source_run=37296245728
source_build_commit=2dc471fdc382f693e22c5fb8b8e25c150585ce6d
source_commit=15490b469f68133da3d244881fb48dd5e42c1d87
source_url=https://github.com/OpenWRT-fanboy/OpenW1700k.git
fwtool_commit=04cd252e4e9394ffacd51f56f1f124abc534f715
image_sha256=437f30508d68e69968e9f6ececb89e9a380bc8be9f64a280c445eab9b4ffdcb2
image_bytes=43062084
image_artifact=11343750772
image_zip_sha256=92a215b167bc110ff8cc8d4c752fccdd6b9f330ddccf2ec217358719a843125c
logs_artifact=11343521178
logs_zip_sha256=a565f551523c4fdbd8ce4ff21a480d4c38ef1a4be3a3056ebdacefa5d6c34727
mihomo_url=https://github.com/MetaCubeX/mihomo/releases/download/v1.19.32/mihomo-linux-arm64-v1.19.32.gz
mihomo_sha256=9dd862e28b46ff7d775f169cceebc28deccaa0a9e804237d421cd2571e0caba0
node_url=https://unofficial-builds.nodejs.org/download/release/v24.21.0/node-v24.21.0-linux-arm64-musl.tar.xz
node_archive_sha256=4008018adb2b06d3050c3ea19dc747b5d533499a0a38686562d5a22002d33f7a
node_elf_sha256=fa2789559dbc3603794a229877c244d1c0d06625c124631611ca4e13eac765be
work=$(mktemp -d "${RUNNER_TEMP:-/tmp}/w1700k-retained.XXXXXXXX")
record="$GITHUB_WORKSPACE/output/build-record"
# Never merge a previous run's output into a fresh validation result.
[[ ! -e output ]]
mkdir -p "$record/original-build-record" "$record/validation-definitions"
printf '%s\n' 'INCOMPLETE: validation gates have not all passed; DO NOT FLASH.' > "$record/STATUS.txt"
exec 3>&1 4>&2
exec > >(tee "$record/validation.log") 2>&1
trap 'status=$?; if (( status != 0 )); then printf "FAILED: validation exited %s; DO NOT FLASH.\n" "$status" > "$record/STATUS.txt"; fi' EXIT
cp scripts/w1700k-validate-retained.sh .github/workflows/validate-retained-w1700k.yml "$record/validation-definitions/"
cp w1700k-slim/{verify_artifact.py,verify_config.py,verify_rootfs.py,prepare_source.py,sources.lock.json} "$record/validation-definitions/"

# The token is used only for read-only GitHub API calls. It is never persisted.
gh api "repos/$repo/actions/runs/$source_run" > "$record/original-run.json"
gh api "repos/$repo/actions/runs/$source_run/jobs?filter=latest&per_page=100" > "$record/original-jobs.json"
gh api "repos/$repo/actions/artifacts/$image_artifact" > "$record/original-image-artifact.json"
gh api "repos/$repo/actions/artifacts/$logs_artifact" > "$record/original-logs-artifact.json"
python3 - "$record" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
run = json.loads((p/'original-run.json').read_text())
commit = '2dc471fdc382f693e22c5fb8b8e25c150585ce6d'
branch = 'w1700k-slim-candidate-20261005'
assert run['id'] == 37296245728 and run['run_attempt'] == 1
assert run['head_sha'] == commit and run['head_branch'] == branch
assert run['repository']['full_name'] == 'anlgt/W1701K-6.18-OpenClash-Build'
assert run['head_repository']['full_name'] == run['repository']['full_name']
assert run['path'] == '.github/workflows/build-w1700k-slim.yml'
assert run['status'] == 'completed' and run['conclusion'] == 'failure'
jobs = json.loads((p/'original-jobs.json').read_text())
assert jobs['total_count'] == len(jobs['jobs']) == 1
job = jobs['jobs'][0]
assert job['run_id'] == run['id'] and job['head_sha'] == commit
assert job['status'] == 'completed' and job['conclusion'] == 'failure'
steps = {s['name']: s for s in job['steps']}
assert len(steps) == len(job['steps'])
for name in ('Fetch exact W1700K source and guarded changes',
             'Pin feeds and requested applications',
             'Resolve only W1700K hardware and selected components',
             'Strict source download gate', 'Native kernel and wireless patch preflight',
             'Build W1700K candidate', 'Upload diagnostics',
             'Retain completed but unvalidated image for diagnosis',
             'Upload unvalidated diagnostic image'):
    assert steps[name]['conclusion'] == 'success', name
failed = [s['name'] for s in job['steps'] if s['conclusion'] == 'failure']
assert failed == ['Validate actual firmware and rootfs'], failed
for filename, aid, name, digest, size in (
    ('original-image-artifact.json', 11343750772,
     'W1700K-UNVALIDATED-DIAGNOSTIC-37296245728-1',
     '92a215b167bc110ff8cc8d4c752fccdd6b9f330ddccf2ec217358719a843125c', 43070297),
    ('original-logs-artifact.json', 11343521178,
     'W1700K-Slim-logs-37296245728-1',
     'a565f551523c4fdbd8ce4ff21a480d4c38ef1a4be3a3056ebdacefa5d6c34727', 126718),
):
    artifact = json.loads((p/filename).read_text())
    assert artifact['id'] == aid and artifact['name'] == name
    assert artifact['digest'] == 'sha256:' + digest
    assert artifact['size_in_bytes'] == size and artifact['expired'] is False
    arun = artifact['workflow_run']
    assert arun['id'] == run['id'] and arun['head_sha'] == commit
    assert arun['head_branch'] == branch
    assert arun['repository_id'] == run['repository']['id']
    assert arun['head_repository_id'] == run['head_repository']['id']
(p/'original-job-id.txt').write_text(str(job['id'])+'\n')
print('Original run, successful compile, sole failed gate, and immutable artifact identities verified')
PY
original_job=$(cat "$record/original-job-id.txt")
gh api "repos/$repo/actions/jobs/$original_job/logs" > "$record/original-job.log"
gh api -H 'Accept: application/vnd.github.raw+json' \
  "repos/$repo/contents/.github/workflows/build-w1700k-slim.yml?ref=$source_build_commit" \
  > "$record/original-build-w1700k-slim.yml"
gh api -H 'Accept: application/vnd.github.raw+json' \
  "repos/$repo/contents/w1700k-slim/sources.lock.json?ref=$source_build_commit" \
  > "$record/original-sources.lock.json"
python3 - "$record" <<'PY'
import json, re, sys
from pathlib import Path
p = Path(sys.argv[1])
log = (p/'original-job.log').read_text()
lines = [re.sub(r'^\d{4}-\d\d-\d\dT\S+\s+', '', line).strip() for line in log.splitlines()]
failures = [line for line in lines if line.startswith('FAIL:')]
assert failures == ['FAIL: Wrong pinned source revision'], failures
assert '##[group]Run bash w1700k-slim/package_output.sh' in lines
workflow = (p/'original-build-w1700k-slim.yml').read_text()
assert 'SOURCE_COMMIT: 15490b469f68133da3d244881fb48dd5e42c1d87' in workflow
assert 'test "$(git -C openwrt rev-parse HEAD)" = "$SOURCE_COMMIT"' in workflow
assert 'python3 w1700k-slim/prepare_source.py openwrt --apply' in workflow
lock = json.loads((p/'original-sources.lock.json').read_text())
assert lock['source']['commit'] == '15490b469f68133da3d244881fb48dd5e42c1d87'
assert lock['source']['url'] == 'https://github.com/OpenWRT-fanboy/OpenW1700k.git'
expected_feeds = {'packages':'349c2ca5c8a058b30d42c537faa4c9e94e997106',
                  'luci':'aa3d48836e90ae0706c8d8f9b46b8371e45cfe1f',
                  'routing':'4b9891b9136259f93294a424507ed24c5e8c1cbd'}
assert {f['name']:f['sha'] for f in lock['feeds']} == expected_feeds
assert lock['plugins']['openclash']['commit'] == 'c3a33c1d3407956fdf8f0e0b7c1a4c52e6ad9593'
assert lock['plugins']['argon']['commit'] == '2a28799ca063aba7edc3314143b93c8325c86df4'
assert lock['mt76']['commit'] == '01367e60db433534ad0aa3d3b6c886de8cb7d44c'
current = json.loads(Path('w1700k-slim/sources.lock.json').read_text())
for section in ('source', 'profile', 'feeds', 'plugins', 'mt76'):
    assert current[section] == lock[section], 'Changed pinned input: ' + section
(p/'original-failure-confirmed.txt').write_text(
    'Original compilation and preceding source/patch/config gates: PASS\n'
    'Only failed step: Validate actual firmware and rootfs\n'
    'Exact gate failure: FAIL: Wrong pinned source revision\n'
    'Shallow source metadata revision: r0-15490b4; full source SHA verified separately.\n')
print('Original failure is exclusively the incorrectly expected source revision')
PY

gh api "repos/$repo/actions/artifacts/$image_artifact/zip" > "$work/original-image.zip"
gh api "repos/$repo/actions/artifacts/$logs_artifact/zip" > "$record/original-logs.zip"
printf '%s  %s\n' "$image_zip_sha256" "$work/original-image.zip" "$logs_zip_sha256" "$record/original-logs.zip" | sha256sum -c -
[[ "$(stat -c %s "$work/original-image.zip")" == 43070297 ]]
[[ "$(stat -c %s "$record/original-logs.zip")" == 126718 ]]
python3 - "$work" "$record" <<'PY'
import hashlib, json, stat, sys, zipfile
from pathlib import Path, PurePosixPath
work, record = map(Path, sys.argv[1:])
def inspect_zip(path):
    z = zipfile.ZipFile(path)
    entries = z.infolist()
    assert len(entries) == len({i.filename for i in entries})
    assert sum(i.file_size for i in entries) < 256 * 1024 * 1024
    for i in entries:
        p = PurePosixPath(i.filename)
        assert not p.is_absolute() and '..' not in p.parts and '\\' not in i.filename
        assert not stat.S_ISLNK(i.external_attr >> 16)
    return z
with inspect_zip(work/'original-image.zip') as z:
    names = z.namelist()
    images = [n for n in names if n.endswith('gemtek_w1700k-ubi-squashfs-sysupgrade.itb')]
    manifests = [n for n in names if n.endswith('gemtek_w1700k-ubi.manifest')]
    assert len(images) == len(manifests) == 1
    assert set(names) == {images[0], manifests[0], 'UNVALIDATED.txt', 'DIAGNOSTIC-SHA256SUMS'}
    assert all('/' not in n for n in names)
    image = z.read(images[0])
    assert len(image) == 43062084
    assert hashlib.sha256(image).hexdigest() == '437f30508d68e69968e9f6ececb89e9a380bc8be9f64a280c445eab9b4ffdcb2'
    dest = work/'retained'
    dest.mkdir()
    checksums = {}
    for line in z.read('DIAGNOSTIC-SHA256SUMS').decode().splitlines():
        digest, name = line.split('  ', 1)
        assert name in {images[0], manifests[0]} and name not in checksums
        checksums[name] = digest
    assert set(checksums) == {images[0], manifests[0]}
    for name, digest in checksums.items():
        data = z.read(name)
        assert hashlib.sha256(data).hexdigest() == digest
        (dest/name).write_bytes(data)
    for name in ('UNVALIDATED.txt', 'DIAGNOSTIC-SHA256SUMS'):
        (record/('original-'+name)).write_bytes(z.read(name))
with inspect_zip(record/'original-logs.zip') as z:
    for name in ('resolved.config', 'resolved.diffconfig', 'source-changes.patch', 'sysupgrade-metadata.json'):
        (record/'original-build-record'/name).write_bytes(z.read('output/build-record/'+name))
metadata = json.loads((record/'original-build-record/sysupgrade-metadata.json').read_text())
assert metadata['version']['revision'] == 'r0-15490b4'
print('Verified ZIP digests and retained image byte identity; extracted only named evidence')
PY
mapfile -t images < <(find "$work/retained" -maxdepth 1 -type f -name '*gemtek_w1700k-ubi-squashfs-sysupgrade.itb')
mapfile -t manifests < <(find "$work/retained" -maxdepth 1 -type f -name '*gemtek_w1700k-ubi.manifest')
[[ ${#images[@]} == 1 && ${#manifests[@]} == 1 ]]
image=${images[0]}
manifest=${manifests[0]}
chmod a-w "$image" "$manifest"
python3 -m py_compile w1700k-slim/*.py
python3 -m unittest discover -s w1700k-slim -p 'test_*.py' -v
python3 w1700k-slim/verify_config.py w1700k-slim/w1700k-slim.config
python3 w1700k-slim/verify_config.py "$record/original-build-record/resolved.config"
python3 w1700k-slim/verify_config.py "$manifest"

clone_pinned() {
  git init "$3"
  git -C "$3" remote add origin "$1"
  git -C "$3" fetch --depth 1 origin "$2"
  git -C "$3" checkout --detach FETCH_HEAD
  [[ "$(git -C "$3" rev-parse HEAD)" == "$2" ]]
}
source="$work/openwrt"
clone_pinned "$source_url" "$source_commit" "$source"
[[ "$(cd "$source" && ./scripts/getver.sh)" == r0-15490b4 ]]
python3 w1700k-slim/prepare_source.py "$source" --apply > "$record/source-preparation.json"
for app in luci-app-airoha-npu luci-app-w1700k-fancontrol; do
  cp -a "w1700k-slim/translations/$app/zh_Hans" "$source/package/$app/po/"
done
git -C "$source" apply --check "$GITHUB_WORKSPACE/w1700k-slim/translations/source-localization.patch"
git -C "$source" apply "$GITHUB_WORKSPACE/w1700k-slim/translations/source-localization.patch"
git -C "$source" diff --binary > "$record/reconstructed-source-changes.patch"
cmp "$record/original-build-record/source-changes.patch" "$record/reconstructed-source-changes.patch"
git -C "$source" diff --exit-code -- scripts/patch-kernel.sh \
  target/linux/generic/kernel-6.18 target/linux/generic/backport-6.18 \
  target/linux/generic/pending-6.18 target/linux/generic/hack-6.18 \
  target/linux/airoha/patches-6.18 target/linux/airoha/dts package/kernel/mt76 \
  package/network/config/wifi-scripts package/base-files/files/etc/shadow
# Official fwtool is standard C; no OpenWrt toolchain or firmware rebuild is used.
clone_pinned https://github.com/openwrt/fwtool.git "$fwtool_commit" "$work/fwtool"
cmake -S "$work/fwtool" -B "$work/fwtool-build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$work/fwtool-build" --parallel 2
"$work/fwtool-build/fwtool" -i "$record/sysupgrade-metadata.json" "$image"
python3 - "$record" <<'PY'
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
assert json.loads((p/'sysupgrade-metadata.json').read_text()) == json.loads(
    (p/'original-build-record/sysupgrade-metadata.json').read_text())
PY
python3 w1700k-slim/verify_artifact.py "$image" "$work/image-check" \
  "$record/sysupgrade-metadata.json" --mode candidate --metadata-source fwtool
unsquashfs -excludes -d "$work/rootfs" "$work/image-check/rootfs.squashfs" dev
root="$work/rootfs"
core="$root/etc/openclash/core/clash_meta"
[[ -x "$core" ]]
file "$core" | grep -q 'ARM aarch64'
curl --fail --location --retry 4 --proto '=https' --tlsv1.2 "$mihomo_url" -o "$work/mihomo.gz"
printf '%s  %s\n' "$mihomo_sha256" "$work/mihomo.gz" | sha256sum -c -
gzip -t "$work/mihomo.gz"
gzip -dc "$work/mihomo.gz" | cmp - "$core"
timeout 60 qemu-aarch64 "$core" -v | tee "$record/mihomo-version.txt"
grep -Fq 'v1.19.32' "$record/mihomo-version.txt"
cat > "$work/mihomo-test.yaml" <<'YAML'
mixed-port: 17890
mode: direct
log-level: warning
ipv6: false
proxies: []
proxy-groups: []
rules:
  - MATCH,DIRECT
YAML
timeout 90 qemu-aarch64 "$core" -t -d "$work/mihomo-test" -f "$work/mihomo-test.yaml" 2>&1 | tee "$record/mihomo-config-test.txt"
python3 w1700k-slim/verify_rootfs.py "$root" "$source" "$record/rootfs-validation.json"

# Inspect only these public ELF libraries and package metadata, never user configs.
python3 - "$root" "$manifest" "$record" <<'PY'
import hashlib, json, os, re, struct, subprocess, sys
from pathlib import Path, PurePosixPath
root, manifest, record = map(Path, sys.argv[1:])
packages = {}
for block in (root/'lib/apk/db/installed').read_text().split('\n\n'):
    fields = {l[0]:l[2:] for l in block.splitlines() if len(l)>1 and l[1]==':' and l[0] in 'PV'}
    if 'P' in fields:
        assert fields['P'] not in packages
        packages[fields['P']] = fields['V']
versions = {}
for line in manifest.read_text().splitlines():
    if line:
        name, version = line.split(' - ', 1)
        assert name not in versions
        versions[name] = version
expected_versions = {'libc':'1.2.6-r5', 'libgcc1':'14.4.0-r5', 'procd':'2026.09.27~675942be-r1'}
for package, version in expected_versions.items():
    assert packages.get(package) == versions.get(package) == version, package
loader = root/'lib/ld-musl-aarch64.so.1'
assert loader.is_symlink(), 'Missing musl interpreter symlink'
assert os.readlink(loader) in ('libc.so', '/lib/libc.so'), 'Unexpected musl interpreter target'
def guest_file(name):
    seen = set()
    for _ in range(8):
        path = root/name
        assert name not in seen, 'Symlink cycle'
        seen.add(name)
        if not path.is_symlink():
            assert path.is_file(), str(path)
            return path
        target = os.readlink(path)
        relative = target.lstrip('/') if target.startswith('/') else str(PurePosixPath(name).parent/target)
        name = os.path.normpath(relative)
        assert not name.startswith('../') and not Path(name).is_absolute()
    raise AssertionError('Excessive symlinks')
libs = {}
for name in ('lib/libc.so', 'lib/libgcc_s.so.1', 'lib/libsetlbf.so'):
    path = guest_file(name)
    data = path.read_bytes()
    assert data[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H', data, 18)[0] == 183
    assert struct.unpack_from('<H', data, 16)[0] == 3, 'Expected shared ELF object'
    details = subprocess.check_output(['readelf', '-h', '-l', '-d', str(path)], text=True)
    needed = set(re.findall(r'\(NEEDED\).*?\[(.*?)\]', details))
    expected_needed = {'lib/libc.so':set(), 'lib/libgcc_s.so.1':{'libc.so'},
                       'lib/libsetlbf.so':{'libc.so', 'libgcc_s.so.1'}}
    assert needed == expected_needed[name], (name, needed)
    (record/(Path(name).name+'.readelf.txt')).write_text(details)
    libs['/'+name] = {'resolved_path':'/'+str(path.relative_to(root)),
                     'sha256':hashlib.sha256(data).hexdigest(), 'bytes':len(data),
                     'arch':'AArch64', 'needed':sorted(needed)}
report = {'status':'PASS', 'libraries':libs, 'interpreter':'/lib/ld-musl-aarch64.so.1',
          'interpreter_symlink':os.readlink(loader),
          'manifest_versions':{p:versions[p] for p in ('libc','libgcc1','procd')},
          'scope':'Static actual-rootfs prerequisites only; no Homebridge, plugins, router or hardware test',
          'private_config_inspected':False}
(record/'homebridge-runtime-prerequisites.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2))
PY

# Optional-runtime evidence: a public, pinned Node binary is kept OUTSIDE the image
# and final artifact. This checks dynamic loading/crypto/TLS only, with no network.
curl --fail --location --retry 4 --proto '=https' --tlsv1.2 "$node_url" -o "$work/node.tar.xz"
printf '%s  %s\n' "$node_archive_sha256" "$work/node.tar.xz" | sha256sum -c -
mkdir "$work/node"
tar -xJf "$work/node.tar.xz" -C "$work/node" --strip-components=2 \
  node-v24.21.0-linux-arm64-musl/bin/node
node="$work/node/node"
printf '%s  %s\n' "$node_elf_sha256" "$node" | sha256sum -c -
readelf -h -l -d "$node" > "$record/node.readelf.txt"
python3 - "$record/node.readelf.txt" <<'PY'
import re, sys
from pathlib import Path
text = Path(sys.argv[1]).read_text()
assert 'AArch64' in text
assert '[Requesting program interpreter: /lib/ld-musl-aarch64.so.1]' in text
assert set(re.findall(r'\(NEEDED\).*?\[(.*?)\]', text)) == {'libc.so', 'libgcc_s.so.1'}
PY
env -i PATH="$PATH" HOME="$work" OPENSSL_CONF=/dev/null \
  timeout 90 qemu-aarch64 -L "$root" "$node" --version | tee "$record/node-version.txt"
grep -Fxq 'v24.21.0' "$record/node-version.txt"
cat > "$work/node-smoke.js" <<'JS'
'use strict';
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const tls = require('node:tls');
assert.equal(process.version, 'v24.21.0');
assert.equal(crypto.createHash('sha256').update('abc').digest('hex'),
  'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
assert.equal(crypto.randomBytes(32).length, 32);
const context = tls.createSecureContext({minVersion:'TLSv1.2'});
assert.ok(context.context);
console.log(JSON.stringify({status:'PASS', node:process.version, arch:process.arch,
  openssl:process.versions.openssl, checks:['version','SHA256','randomBytes','TLS context'],
  rootfs:'actual retained firmware libraries via qemu-aarch64 -L',
  network_connections:0, homebridge_tested:false, plugins_tested:false, hardware_tested:false}));
JS
env -i PATH="$PATH" HOME="$work" OPENSSL_CONF=/dev/null \
  timeout 120 qemu-aarch64 -L "$root" "$node" "$work/node-smoke.js" | tee "$record/node-runtime-smoke.json"
cp "$work/node-smoke.js" "$record/"

# The binary and manifest must still be byte-for-byte identical after every gate.
printf '%s  %s\n' "$image_sha256" "$image" | sha256sum -c -
[[ "$(stat -c %s "$image")" == "$image_bytes" ]]
(cd "$work/retained" && sha256sum -c "$record/original-DIAGNOSTIC-SHA256SUMS")
mkdir -p output/firmware
cp "$image" "$manifest" output/firmware/
cp "$work/image-check/fit-validation.json" "$work/image-check/device.dtb" "$record/"
cp w1700k-slim/CANDIDATE-NOTES.md output/ORIGINAL-CANDIDATE-NOTES.md
cat > output/READ-ME-FIRST.md <<'TEXT'
# W1700K Slim retained candidate: offline software checks passed

中文摘要：本次仅重新验证原构建产物，固件字节、品牌和文件名均未修改，也未重新编译。
原检查错误地要求元数据版本为 r36860-15490b469f；固定源码的浅克隆实际生成
r0-15490b4。完整源码提交已通过原构建证据和本次源码重建比对单独核实。
离线镜像、软件包、根文件系统及模拟运行检查通过；Node 测试仅验证运行库及本地
加密/TLS 初始化，不代表 Homebridge 或插件兼容。未进行路由器启动、Wi-Fi、NPU、
风扇、温度或刷机测试，不建议仅凭这些离线结果刷机或发布。

This is the byte-for-byte original image built by run 37296245728 at repository
commit 2dc471fdc382f693e22c5fb8b8e25c150585ce6d. It was not rebuilt or rebranded.
The original gate wrongly expected r36860-15490b469f (old_expected_metadata_revision);
this pinned shallow checkout correctly records r0-15490b4 (actual_metadata_revision). The full source commit is independently
bound by the successful original build steps, immutable build recipe, source pins,
and reconstructed source patch. The short revision alone does not prove provenance.

The fresh validator checks official fwtool metadata extraction, trailer CRC,
FIT payload hashes, compiled board layout/DTB, kernel 6.18.55, resolved config,
manifest, actual rootfs, kernel-module ABI package dependencies, exact official
Mihomo core bytes and its QEMU version/config smoke checks. Public libc/libgcc/
procd runtime prerequisites and a separate pinned public Node executable were
checked against actual image libraries. Node/Homebridge are not bundled.

Node crypto/TLS-context smoke checks are not Homebridge/plugin compatibility,
a network test, a router boot test, or hardware validation. Wi-Fi, NPU, fan,
thermals and sysupgrade on a physical router remain untested. Do not flash or
release this candidate based solely on these offline checks. There is no flash
recommendation; no router access, deployment, merge or release occurred.

See build-record/provenance.json for distinct build and validation identities,
source URLs/pins, immutable retained artifact IDs/digests and exact limitations.
SHA256SUMS covers every delivered file except itself. The original diagnostic
warning is retained as historical evidence and does not replace this validation
record. Any later file change invalidates these checksums.
TEXT
python3 - "$record" <<'PY'
import hashlib, json, os
from pathlib import Path
import sys
record = Path(sys.argv[1])
image = next(Path('output/firmware').glob('*.itb'))
manifest = next(Path('output/firmware').glob('*.manifest'))
report = {
 'status':'OFFLINE SOFTWARE/IMAGE GATES PASSED; HARDWARE NOT VALIDATED',
 'binary_unchanged':True,
 'binary_build':{'repository':'anlgt/W1701K-6.18-OpenClash-Build',
  'commit':'2dc471fdc382f693e22c5fb8b8e25c150585ce6d',
  'run':'https://github.com/anlgt/W1701K-6.18-OpenClash-Build/actions/runs/37296245728',
  'run_attempt':1, 'compile':'success',
  'original_failure':'FAIL: Wrong pinned source revision'},
 'retained_artifact':{'id':11343750772,
  'url':'https://github.com/anlgt/W1701K-6.18-OpenClash-Build/actions/runs/37296245728/artifacts/11343750772',
  'zip_sha256':'92a215b167bc110ff8cc8d4c752fccdd6b9f330ddccf2ec217358719a843125c',
  'zip_bytes':43070297, 'image_bytes':image.stat().st_size,
  'image_sha256':hashlib.sha256(image.read_bytes()).hexdigest(),
  'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()},
 'original_logs_artifact':{'id':11343521178,
  'zip_sha256':'a565f551523c4fdbd8ce4ff21a480d4c38ef1a4be3a3056ebdacefa5d6c34727'},
 'validation_only':{'commit':os.environ['GITHUB_SHA'],
  'run':'https://github.com/'+os.environ['GITHUB_REPOSITORY']+'/actions/runs/'+os.environ['GITHUB_RUN_ID'],
  'run_attempt':int(os.environ['GITHUB_RUN_ATTEMPT']), 'rebuilt':False,
  'branding_modified':False,
  'old_expected_metadata_revision':'r36860-15490b469f',
  'actual_metadata_revision':'r0-15490b4',
  'revision_expectation':'r0-15490b4'},
 'source':{'url':'https://github.com/OpenWRT-fanboy/OpenW1700k.git',
  'commit':'15490b469f68133da3d244881fb48dd5e42c1d87',
  'patch_matches_original_build':True,
  'revision_note':'image-commands.mk uses REVISION from shallow getver.sh, not CONFIG_VERSION_CODE'},
 'fwtool':{'url':'https://github.com/openwrt/fwtool.git',
  'commit':'04cd252e4e9394ffacd51f56f1f124abc534f715', 'fresh_metadata_extraction':True},
 'mihomo':{'url':'https://github.com/MetaCubeX/mihomo/releases/download/v1.19.32/mihomo-linux-arm64-v1.19.32.gz',
  'gzip_sha256':'9dd862e28b46ff7d775f169cceebc28deccaa0a9e804237d421cd2571e0caba0',
  'core_bytes_match':True, 'qemu_version_and_config_test':'PASS'},
 'node_runtime_smoke':{'url':'https://unofficial-builds.nodejs.org/download/release/v24.21.0/node-v24.21.0-linux-arm64-musl.tar.xz',
  'archive_sha256':'4008018adb2b06d3050c3ea19dc747b5d533499a0a38686562d5a22002d33f7a',
  'elf_sha256':'fa2789559dbc3603794a229877c244d1c0d06625c124631611ca4e13eac765be',
  'bundled_in_image_or_deliverable':False, 'actual_rootfs_qemu':'PASS',
  'scope':'Version and local crypto/TLS context only; no network, Homebridge or plugin test'},
 'private_config_inspected':False, 'hardware_validation':'NOT RUN',
 'router_access':False, 'flash_or_release_recommendation':False,
}
(record/'provenance.json').write_text(json.dumps(report, indent=2)+'\n')
PY
printf '%s\n' 'PASS: offline software/image gates only; HARDWARE NOT VALIDATED; DO NOT FLASH.' > "$record/STATUS.txt"
# Stop tee before hashing so validation.log cannot change after its checksum.
echo 'All retained-image offline gates passed; original image SHA256 remains unchanged.'
exec 1>&3 2>&4 3>&- 4>&-
wait
(cd output && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS && sha256sum -c SHA256SUMS >/dev/null)
