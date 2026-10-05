#!/usr/bin/env python3
"""Fail-closed, one-release publisher. Production entry point needs GitHub Actions.

Inputs, destination, source commit, binary hashes and notes hash are fixed.
A retry may add missing assets to our exact draft, never replace existing data.
No shell interpolation, credential persistence, forced refs or deletion APIs.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from urllib.parse import quote
import zipfile

REPO = "anlgt/W1701K-6.18-OpenClash-Build"
BRANCH = "w1700k-publish-candidate-20261005"
TAG = "w1700k-6.18.55-slim-candidate-r1"
SOURCE_COMMIT = "1cdd0d6d9f222ea83e1c500f43ba9c87c96ee90a"
BUILD_COMMIT = "2dc471fdc382f693e22c5fb8b8e25c150585ce6d"
VALIDATION_COMMIT = "f6315b7ee79a17b8d26f0c5cff8c399d3a52e25a"
BUILD_RUN = 37296245728
VALIDATION_RUN = 37308431238
VALIDATION_BRANCH = "w1700k-slim-candidate-20261005"
ARTIFACT_ID = 11345405048
ARTIFACT_NAME = "W1700K-Slim-validated-retained-37308431238-1"
ZIP_NAME = ARTIFACT_NAME + ".zip"
ZIP_SIZE = 45107958
ZIP_SHA = "9bf593eeea9311cd8e7ba62179a2b20de0085377fe64331483f4791de3c2acad"
BASE = "w1700k-slim-6.18.55-ubi2-r36860-15490b469f-airoha-an7581-gemtek_w1700k-ubi"
ITB_NAME = BASE + "-squashfs-sysupgrade.itb"
MANIFEST_NAME = BASE + ".manifest"
ITB_SIZE = 43062084
ITB_SHA = "437f30508d68e69968e9f6ececb89e9a380bc8be9f64a280c445eab9b4ffdcb2"
MANIFEST_SIZE = 7003
MANIFEST_SHA = "192066d7dfb56f8598775dd5a99a58c1a179b664d5998805f9adb1cabd7f819c"
TITLE = "W1700K Slim 6.18.55 UBI2 candidate r1 (hardware not validated)"
NOTES_SHA256 = "a7998e85fda499514f66a399d9afb774862cd796265235a9ae0eb3a01dd4902d"
NOTES_PATH = "release/w1700k-candidate-notes.md"
WORKFLOW_PATH = ".github/workflows/publish-w1700k-candidate.yml"
SCRIPT_PATH = "scripts/publish-w1700k-candidate.py"
DOC_PREFIX = "docs/w1700k-slim/"
DOC_NAMES = {"VALIDATED-CANDIDATE.md", "provenance.json", "SHA256SUMS"}
HELPER_PATHS = {NOTES_PATH, WORKFLOW_PATH, SCRIPT_PATH}
PRIVATE_LEGACY = {"w1700k-private/README.md", "w1700k-private/check-config-archive.py"}
FORBIDDEN_BASENAMES = {"private-config.b64", "config.diff", "99-w1700k-private-services"}
ASSET_NAMES = {ZIP_NAME, ITB_NAME, MANIFEST_NAME, "VALIDATED-CANDIDATE.md",
               "provenance.json", "RELEASE-NOTES.md", "SHA256SUMS"}
API_ROOT = "repos/" + REPO
API_VERSION = "2022-11-28"


class GateError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise GateError(message)


def sha256(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def verify_file(path, size, digest):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "Missing or nonregular file: " + path.name)
    require(path.stat().st_size == size, "Unexpected file size: " + path.name)
    require(sha256(path) == digest, "SHA256 mismatch: " + path.name)


def git(cwd, *args):
    p = subprocess.run(["git", "-C", str(cwd), *args], check=False,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(p.returncode == 0, "Read-only git command failed: " + args[0])
    return p.stdout


def tree(cwd, commit):
    entries = {}
    for raw in git(cwd, "ls-tree", "-r", "-z", "--full-tree", commit).split(b"\0"):
        if not raw:
            continue
        meta, name = raw.split(b"\t", 1)
        path = name.decode("utf-8")
        mode, kind, oid = meta.decode("ascii").split()
        require(path not in entries, "Duplicate git tree path")
        entries[path] = (mode, kind, oid)
    return entries


def validate_tree_paths(entries):
    require(bool(entries), "Source tree must not be empty")
    for path in entries:
        base = PurePosixPath(path).name.lower()
        require(base not in FORBIDDEN_BASENAMES, "Forbidden sensitive source path present")
        if path.lower().startswith("w1700k-private/"):
            require(path in PRIVATE_LEGACY, "Unexpected private-tree path present")
            require(entries[path][0] in ("100644", "100755") and entries[path][1] == "blob",
                    "Legacy private-tree documentation is not a regular file")
    docs = {p[len(DOC_PREFIX):] for p in entries if p.startswith(DOC_PREFIX)}
    require(docs == DOC_NAMES, "Unexpected public documentation tree")


def validate_checkout(root, source_root):
    require(git(root, "rev-parse", "HEAD").decode().strip() == os.environ["GITHUB_SHA"],
            "Helper checkout is not the workflow SHA")
    require(git(source_root, "rev-parse", "HEAD").decode().strip() == SOURCE_COMMIT,
            "Source checkout is not the fixed tag target")
    source_tree = tree(source_root, SOURCE_COMMIT)
    helper_tree = tree(root, "HEAD")
    validate_tree_paths(source_tree)
    validate_tree_paths(helper_tree)
    require({p: v for p, v in helper_tree.items() if p not in HELPER_PATHS} ==
            {p: v for p, v in source_tree.items() if p not in HELPER_PATHS},
            "Helper branch changes files outside the three authorized publisher paths")
    for path in HELPER_PATHS:
        require(path in helper_tree and helper_tree[path][0] in ("100644", "100755") and
                helper_tree[path][1] == "blob", "Unexpected publisher file mode or type")
        require((root / path).read_bytes() == git(root, "show", "HEAD:" + path),
                "Publisher working file differs from committed bytes")
    for name in DOC_NAMES:
        path = DOC_PREFIX + name
        require(source_tree[path][0] == "100644" and source_tree[path][1] == "blob",
                "Public documentation is not a regular file")
        expected = git(source_root, "show", SOURCE_COMMIT + ":" + path)
        require((root / path).read_bytes() == expected, "Documentation differs from fixed tag source")
        require((source_root / path).read_bytes() == expected, "Source working tree differs from tag bytes")
    return {"source_tree_paths_checked": len(source_tree), "helper_tree_paths_checked": len(helper_tree),
            "helper_changes_limited_to": sorted(HELPER_PATHS), "private_content_read": False}


def validate_environment():
    expected = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": REPO,
                "GITHUB_REF": "refs/heads/" + BRANCH, "GITHUB_EVENT_NAME": "push",
                "GITHUB_SERVER_URL": "https://github.com", "GITHUB_API_URL": "https://api.github.com"}
    for key, value in expected.items():
        require(os.environ.get(key) == value, "Unexpected execution environment: " + key)
    require(os.environ.get("GH_HOST", "github.com") == "github.com", "Unexpected GitHub API host")
    require(bool(os.environ.get("GH_TOKEN")), "Ephemeral workflow token is unavailable")
    require(re.fullmatch(r"[0-9a-f]{40}", os.environ.get("GITHUB_SHA", "")), "Invalid helper SHA")
    require(os.environ.get("GITHUB_WORKFLOW_REF") == REPO + "/" + WORKFLOW_PATH + "@refs/heads/" + BRANCH,
            "Unexpected executing workflow")
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    require(event.get("repository", {}).get("full_name") == REPO and
            event.get("ref") == "refs/heads/" + BRANCH and event.get("deleted") is False,
            "Unexpected push event")
    require(event.get("after") == os.environ["GITHUB_SHA"], "Push and checkout SHAs differ")


class GitHub:
    def _command(self, method, endpoint):
        require(method in ("GET", "POST", "PATCH"), "Unsupported API method")
        require(endpoint.startswith(API_ROOT + "/") or
                endpoint.startswith("https://uploads.github.com/" + API_ROOT + "/releases/"),
                "API target outside fixed repository")
        return ["gh", "api", "--method", method, endpoint,
                "-H", "X-GitHub-Api-Version: " + API_VERSION]

    def api(self, method, endpoint, body=None, allow404=False, input_file=None):
        command = self._command(method, endpoint)
        command += ["-H", "Accept: application/vnd.github+json"]
        data = None
        if body is not None:
            require(input_file is None, "Conflicting API input modes")
            command += ["--input", "-", "-H", "Content-Type: application/json"]
            data = json.dumps(body).encode()
        if input_file is not None:
            command += ["--input", str(input_file), "-H", "Content-Type: application/octet-stream"]
        p = subprocess.run(command, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if p.returncode:
            try:
                problem = json.loads(p.stdout)
            except (ValueError, UnicodeError):
                problem = {}
            status = problem.get("status") if isinstance(problem, dict) else None
            if not status:
                match = re.search(rb"HTTP (\d{3})", p.stderr)
                status = match.group(1).decode() if match else "unknown"
            if allow404 and p.returncode == 1 and str(status) == "404":
                return None
            raise GateError("GitHub API failed: " + method + " " + endpoint +
                            " (exit " + str(p.returncode) + ", status " + str(status) + ")")
        try:
            return json.loads(p.stdout)
        except (ValueError, UnicodeError) as exc:
            raise GateError("GitHub API did not return JSON") from exc

    def download(self, endpoint, destination):
        # Artifact ZIP requests use the Actions API's documented JSON media type
        # before following its redirect. Release-asset binary requests instead
        # require octet-stream. Do not use one Accept header for both APIs.
        if endpoint == f"{API_ROOT}/actions/artifacts/{ARTIFACT_ID}/zip":
            media = "application/vnd.github+json"
            label = "fixed_actions_artifact_zip"
        elif re.fullmatch(re.escape(API_ROOT) + r"/releases/assets/[1-9][0-9]*", endpoint):
            media = "application/octet-stream"
            label = "verified_release_asset"
        else:
            raise GateError("Binary download endpoint is outside the fixed release task")
        command = self._command("GET", endpoint)
        command += ["--allow-escape-sequences", "-H", "Accept: " + media]
        # Binary output goes directly to a file. stderr may contain signed URLs,
        # so retain it only in memory and report allowlisted classifications.
        with Path(destination).open("xb") as f:
            result = subprocess.run(command, stdout=f, stderr=subprocess.PIPE, check=False)
        if result.returncode:
            status = "unknown"
            match = re.search(rb"HTTP ([1-5][0-9]{2})\b", result.stderr)
            if match:
                status = match.group(1).decode("ascii")
            elif Path(destination).stat().st_size <= 16384:
                # gh can put a small API error JSON body on stdout; never echo it.
                try:
                    problem = json.loads(Path(destination).read_bytes())
                    candidate = str(problem.get("status", "")) if isinstance(problem, dict) else ""
                    if re.fullmatch(r"[1-5][0-9]{2}", candidate):
                        status = candidate
                except (ValueError, UnicodeError):
                    pass
            categories = {"401": "authentication_required", "403": "access_denied",
                          "404": "not_found_or_access_hidden", "406": "unsupported_media_type",
                          "410": "artifact_expired", "415": "unsupported_media_type",
                          "429": "rate_limited"}
            category = categories.get(status, "remote_server_error" if status.startswith("5") else "unclassified_failure")
            error = result.stderr.lower()
            if status == "unknown":
                if b"unknown flag: --allow-escape-sequences" in error:
                    category = "cli_option_unsupported"
                elif b"x509:" in error or b"certificate" in error:
                    category = "tls_verification_failure"
                elif b"timeout" in error or b"deadline exceeded" in error:
                    category = "transport_timeout"
                elif b"no such host" in error:
                    category = "dns_failure"
                elif b"connection reset" in error or b"connection refused" in error:
                    category = "transport_failure"
            raise GateError("GitHub binary download failed: " + label +
                            "; exit=" + str(result.returncode) + "; http_status=" + status +
                            "; category=" + category + "; bytes_written=" + str(Path(destination).stat().st_size))
        # No automatic retry, header fallback, credential change or alternate URL.

    def all_pages(self, endpoint):
        items = []
        for page in range(1, 101):
            batch = self.api("GET", endpoint + "?per_page=100&page=" + str(page))
            require(isinstance(batch, list), "Unexpected paginated API response")
            items.extend(batch)
            if len(batch) < 100:
                return items
        raise GateError("Pagination safety limit reached; refusing incomplete results")


def validate_run_artifact(run, artifact):
    require(run.get("id") == VALIDATION_RUN and run.get("run_attempt") == 1,
            "Wrong validation run or attempt")
    require(run.get("status") == "completed" and run.get("conclusion") == "success",
            "Validation run has not completed successfully")
    require(run.get("event") == "push" and run.get("head_sha") == VALIDATION_COMMIT and
            run.get("head_branch") == VALIDATION_BRANCH, "Validation run source identity mismatch")
    require(run.get("path") == ".github/workflows/validate-retained-w1700k.yml",
            "Unexpected validation workflow")
    for field in ("repository", "head_repository"):
        require(run.get(field, {}).get("full_name") == REPO, "Unexpected validation repository")
    require(run["repository"]["id"] == run["head_repository"]["id"], "Forked validation is not allowed")
    require(artifact.get("id") == ARTIFACT_ID and artifact.get("name") == ARTIFACT_NAME,
            "Validation artifact identity mismatch")
    require(artifact.get("expired") is False and artifact.get("size_in_bytes") == ZIP_SIZE and
            artifact.get("digest") == "sha256:" + ZIP_SHA, "Artifact digest, size or expiry mismatch")
    linked = artifact.get("workflow_run", {})
    require(linked.get("id") == VALIDATION_RUN and linked.get("head_sha") == VALIDATION_COMMIT and
            linked.get("head_branch") == VALIDATION_BRANCH, "Artifact belongs to another run")
    require(linked.get("repository_id") == run["repository"]["id"] and
            linked.get("head_repository_id") == run["head_repository"]["id"], "Artifact repository mismatch")


def safe_member(name):
    require(name and not name.startswith("/") and "\\" not in name and ":" not in name and
            all(ord(c) >= 32 and ord(c) != 127 for c in name), "Unsafe archive path")
    p = PurePosixPath(name)
    require(".." not in p.parts and "." not in p.parts and str(p) == name,
            "Noncanonical archive path")
    require(p.name.lower() not in FORBIDDEN_BASENAMES and
            not name.lower().startswith("w1700k-private/"), "Sensitive archive member path")
    return name


def parse_sums(content):
    result = {}
    for line in content.decode("utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?(.+)", line)
        require(match is not None, "Invalid SHA256SUMS line")
        digest, name = match.groups()
        name = safe_member(name)
        require(name not in result and name != "SHA256SUMS", "Duplicate or self-referencing checksum")
        result[name] = digest
    require(bool(result), "Empty checksum manifest")
    return result


def validate_provenance(provenance):
    require(provenance.get("status") == "OFFLINE SOFTWARE/IMAGE GATES PASSED; HARDWARE NOT VALIDATED",
            "Unexpected validation status")
    require(provenance.get("binary_unchanged") is True and provenance.get("private_config_inspected") is False and
            provenance.get("hardware_validation") == "NOT RUN" and provenance.get("router_access") is False,
            "Validation scope mismatch")
    build = provenance.get("binary_build", {})
    require(build.get("repository") == REPO and build.get("commit") == BUILD_COMMIT and
            build.get("run") == f"https://github.com/{REPO}/actions/runs/{BUILD_RUN}" and
            build.get("run_attempt") == 1 and build.get("compile") == "success", "Binary-build provenance mismatch")
    validation = provenance.get("validation_only", {})
    require(validation.get("commit") == VALIDATION_COMMIT and
            validation.get("run") == f"https://github.com/{REPO}/actions/runs/{VALIDATION_RUN}" and
            validation.get("run_attempt") == 1 and validation.get("rebuilt") is False and
            validation.get("branding_modified") is False and validation.get("actual_metadata_revision") == "r0-15490b4",
            "Validation-only provenance mismatch")
    retained = provenance.get("retained_artifact", {})
    require(retained.get("id") == 11343750772 and retained.get("image_bytes") == ITB_SIZE and
            retained.get("image_sha256") == ITB_SHA and retained.get("manifest_sha256") == MANIFEST_SHA,
            "Retained binary provenance mismatch")
    require(provenance.get("source", {}).get("commit") == "15490b469f68133da3d244881fb48dd5e42c1d87" and
            provenance.get("source", {}).get("patch_matches_original_build") is True,
            "Pinned firmware source provenance mismatch")


def validate_archive(path, assets):
    verify_file(path, ZIP_SIZE, ZIP_SHA)
    with zipfile.ZipFile(path) as z:
        members = z.infolist()
        require(len(members) == 47 and sum(i.file_size for i in members) == 45099752,
                "Unexpected archive membership or uncompressed size")
        names = set()
        for info in members:
            name = safe_member(info.filename)
            require(name not in names and not info.is_dir() and not info.flag_bits & 1,
                    "Duplicate, directory or encrypted archive member")
            mode = info.external_attr >> 16
            require(stat.S_IFMT(mode) in (0, stat.S_IFREG), "Archive contains a nonregular member")
            names.add(name)
        require("SHA256SUMS" in names, "Missing archive checksum manifest")
        checksums = parse_sums(z.read("SHA256SUMS"))
        require(set(checksums) == names - {"SHA256SUMS"}, "Incomplete internal checksum coverage")
        for name, digest in checksums.items():
            with z.open(name) as f:
                require(hashlib.file_digest(f, "sha256").hexdigest() == digest,
                        "Internal archive checksum mismatch: " + name)
        provenance = json.loads(z.read("build-record/provenance.json"))
        validate_provenance(provenance)
        require({n for n in names if n.startswith("firmware/")} ==
                {"firmware/" + ITB_NAME, "firmware/" + MANIFEST_NAME}, "Unexpected firmware files")
        for name, size, digest in ((ITB_NAME, ITB_SIZE, ITB_SHA), (MANIFEST_NAME, MANIFEST_SIZE, MANIFEST_SHA)):
            dest = assets / name
            with z.open("firmware/" + name) as incoming, dest.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)
            verify_file(dest, size, digest)
    return {"zip_sha256": ZIP_SHA, "files_verified": len(checksums), "provenance_verified": True}


def prepare_public_assets(root, assets):
    notes = (root / NOTES_PATH).read_bytes()
    require(hashlib.sha256(notes).hexdigest() == NOTES_SHA256, "Release notes are not the approved fixed bytes")
    text = notes.decode("utf-8")
    for required in (SOURCE_COMMIT, BUILD_COMMIT, VALIDATION_COMMIT, ITB_SHA, ZIP_SHA):
        require(required in text, "Release notes omit a required immutable identity")
    require(not any(x in text for x in ("/Users/", "/Volumes/", "/workspace/", "M5path")),
            "Release notes contain a local private location")
    public_docs = root / DOC_PREFIX
    doc_sums = parse_sums((public_docs / "SHA256SUMS").read_bytes())
    require(doc_sums == {ZIP_NAME: ZIP_SHA, ITB_NAME: ITB_SHA, MANIFEST_NAME: MANIFEST_SHA},
            "Source documentation records different firmware/artifact hashes")
    for name in ("VALIDATED-CANDIDATE.md", "provenance.json"):
        # Exact bytes were compared to git show SOURCE_COMMIT:path before staging.
        data = (public_docs / name).read_bytes()
        (assets / name).write_bytes(data)
    provenance = json.loads((assets / "provenance.json").read_text())
    validate_provenance(provenance)
    doc = provenance.get("documentation", {})
    require(doc.get("basis_commit") == VALIDATION_COMMIT and doc.get("firmware_rebuilt") is False and
            doc.get("firmware_bytes_modified") is False and doc.get("private_backup_locations_included") is False and
            doc.get("validated_artifact_id") == ARTIFACT_ID and
            doc.get("validated_artifact_zip_sha256") == ZIP_SHA and doc.get("validated_artifact_zip_bytes") == ZIP_SIZE,
            "Documentation provenance mismatch")
    # Both the asset and API body preserve the approved public notes exactly.
    (assets / "RELEASE-NOTES.md").write_bytes(notes)
    body = text
    names = {p.name for p in assets.iterdir()}
    require(names == ASSET_NAMES - {"SHA256SUMS"}, "Unexpected staged assets")
    (assets / "SHA256SUMS").write_text("".join(sha256(assets / n) + "  " + n + "\n" for n in sorted(names)))
    return body, {n: {"size": (assets / n).stat().st_size, "sha256": sha256(assets / n)}
                  for n in sorted(ASSET_NAMES)}


def verify_tag(api, allow_absent=False):
    ref = api.api("GET", API_ROOT + "/git/ref/tags/" + TAG, allow404=allow_absent)
    if ref is None:
        return None
    require(ref.get("ref") == "refs/tags/" + TAG and ref.get("object", {}).get("type") == "commit" and
            ref.get("object", {}).get("sha") == SOURCE_COMMIT, "Existing tag is not the exact lightweight target")
    return ref


def find_release(api):
    matches = [r for r in api.all_pages(API_ROOT + "/releases") if r.get("tag_name") == TAG]
    require(len(matches) <= 1, "More than one release uses the fixed tag")
    return matches[0] if matches else None


def verify_release(release, body, expected_draft=None):
    require(isinstance(release.get("id"), int) and release["id"] > 0, "Release ID is invalid")
    require(release.get("tag_name") == TAG and release.get("target_commitish") == SOURCE_COMMIT and
            release.get("name") == TITLE and release.get("body") == body and release.get("prerelease") is True,
            "Existing release is not this exact task-owned candidate")
    require(release.get("author", {}).get("login") == "github-actions[bot]" and
            release.get("author", {}).get("type") == "Bot", "Release is not owned by the Actions publisher")
    require(isinstance(release.get("draft"), bool), "Missing release draft flag")
    if expected_draft is not None:
        require(release["draft"] is expected_draft, "Unexpected release publication state")
    if not release["draft"]:
        require(release.get("html_url") == f"https://github.com/{REPO}/releases/tag/{TAG}",
                "Unexpected public release URL")
        require(bool(release.get("published_at")), "Published release lacks timestamp")


def verify_assets(api, release_id, expected, complete=False):
    assets = api.all_pages(f"{API_ROOT}/releases/{release_id}/assets")
    seen = {}
    for asset in assets:
        name = asset.get("name")
        require(name in expected and name not in seen, "Unexpected or duplicate release asset")
        wanted = expected[name]
        require(asset.get("state") == "uploaded" and asset.get("size") == wanted["size"] and
                asset.get("digest") == "sha256:" + wanted["sha256"], "Server asset size/digest mismatch: " + name)
        require(isinstance(asset.get("id"), int) and asset["id"] > 0, "Invalid asset ID")
        require(asset.get("browser_download_url") == f"https://github.com/{REPO}/releases/download/{TAG}/{name}",
                "Unexpected asset download URL")
        seen[name] = asset
    if complete:
        require(set(seen) == set(expected), "Release is missing expected assets")
    return seen


def ensure_not_latest(api, release_id):
    latest = api.api("GET", API_ROOT + "/releases/latest", allow404=True)
    require(latest is None or latest.get("id") != release_id, "Candidate was unexpectedly marked Latest")
    return latest.get("id") if latest else None


def publish(api, assets, body, expected):
    # Discover and validate existing remote state before making any changes.
    ref = verify_tag(api, allow_absent=True)
    release = find_release(api)
    if release:
        require(ref is not None, "An existing release has no verified fixed tag")
        verify_release(release, body)
        existing = verify_assets(api, release["id"], expected, complete=not release["draft"])
        ensure_not_latest(api, release["id"])
    else:
        existing = {}
    if ref is None:
        api.api("POST", API_ROOT + "/git/refs", {"ref": "refs/tags/" + TAG, "sha": SOURCE_COMMIT})
        verify_tag(api)
    if release is None:
        release = api.api("POST", API_ROOT + "/releases", {
            "tag_name": TAG, "target_commitish": SOURCE_COMMIT, "name": TITLE,
            "body": body, "draft": True, "prerelease": True,
            "make_latest": "false", "generate_release_notes": False,
        })
        verify_release(release, body, expected_draft=True)
        existing = verify_assets(api, release["id"], expected)
    release_id = release["id"]
    if release["draft"]:
        for name in sorted(expected):
            if name in existing:
                continue
            # Recheck draft and tag immediately before each mutation. Never clobber.
            current = api.api("GET", f"{API_ROOT}/releases/{release_id}")
            verify_release(current, body, expected_draft=True)
            verify_tag(api)
            existing = verify_assets(api, release_id, expected)
            if name in existing:
                continue
            endpoint = f"https://uploads.github.com/{API_ROOT}/releases/{release_id}/assets?name=" + quote(name, safe="")
            api.api("POST", endpoint, input_file=assets / name)
            existing = verify_assets(api, release_id, expected)
        verify_assets(api, release_id, expected, complete=True)
        verify_tag(api)
        current = api.api("GET", f"{API_ROOT}/releases/{release_id}")
        verify_release(current, body, expected_draft=True)
        # This is the only publication action, and every asset has already passed.
        api.api("PATCH", f"{API_ROOT}/releases/{release_id}", {
            "draft": False, "prerelease": True, "make_latest": "false",
        })
    # An exact already-published candidate is read-only verified; never modified.
    final = api.api("GET", f"{API_ROOT}/releases/{release_id}")
    verify_release(final, body, expected_draft=False)
    verify_tag(api)
    final_assets = verify_assets(api, release_id, expected, complete=True)
    latest_id = ensure_not_latest(api, release_id)
    with tempfile.TemporaryDirectory(prefix="w1700k-release-readback-") as temp:
        for name, asset in final_assets.items():
            path = Path(temp) / name
            api.download(f"{API_ROOT}/releases/assets/{asset['id']}", path)
            verify_file(path, expected[name]["size"], expected[name]["sha256"])
    return {"release_id": release_id, "url": final["html_url"], "tag": TAG,
            "tag_target": SOURCE_COMMIT, "draft": False, "prerelease": True,
            "make_latest_requested": False, "latest_release_id": latest_id,
            "is_latest": False, "asset_readback_verified": True,
            "assets": [{"name": n, "id": a["id"], "size": a["size"], "digest": a["digest"],
                        "browser_download_url": a["browser_download_url"]} for n, a in sorted(final_assets.items())]}


def main():
    validate_environment()
    root = Path.cwd()
    output = root / "output"
    output.mkdir(exist_ok=True)
    status = {"status": "running", "repository": REPO, "tag": TAG, "tag_target": SOURCE_COMMIT,
              "publisher_commit": os.environ["GITHUB_SHA"], "publisher_run": os.environ["GITHUB_RUN_ID"]}
    def stage(name):
        status["stage"] = name
        (output / "publisher-status.json").write_text(json.dumps(status, indent=2) + "\n")
    try:
        stage("validate_source_checkout")
        source_proof = validate_checkout(root, root / "_source")
        api = GitHub()
        stage("validate_successful_run_and_artifact")
        run = api.api("GET", f"{API_ROOT}/actions/runs/{VALIDATION_RUN}")
        artifact = api.api("GET", f"{API_ROOT}/actions/artifacts/{ARTIFACT_ID}")
        validate_run_artifact(run, artifact)
        assets = output / "assets"
        assets.mkdir(exist_ok=False)
        stage("download_and_validate_immutable_archive")
        api.download(f"{API_ROOT}/actions/artifacts/{ARTIFACT_ID}/zip", assets / ZIP_NAME)
        archive_proof = validate_archive(assets / ZIP_NAME, assets)
        stage("prepare_public_assets")
        body, expected = prepare_public_assets(root, assets)
        stage("publish_and_verify_fixed_prerelease")
        proof = publish(api, assets, body, expected)
        proof.update({"repository": REPO, "binary_build_commit": BUILD_COMMIT,
                      "binary_build_run": BUILD_RUN, "validation_commit": VALIDATION_COMMIT,
                      "validation_run": VALIDATION_RUN, "validated_artifact_id": ARTIFACT_ID,
                      "documentation_commit": SOURCE_COMMIT, "publisher_commit": os.environ["GITHUB_SHA"],
                      "publisher_run": os.environ["GITHUB_RUN_ID"], "source_checks": source_proof,
                      "archive_checks": archive_proof, "hardware_validation": "NOT RUN",
                      "firmware_rebuilt": False, "firmware_bytes_modified": False})
        (output / "release-verification.json").write_text(json.dumps(proof, indent=2) + "\n")
        status["status"] = "success"
        stage("complete")
        print("Verified fixed candidate prerelease: " + proof["url"])
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
                f.write("Verified prerelease: " + proof["url"] + "\n\nTag target: " + SOURCE_COMMIT +
                        "\n\nAll seven assets passed server SHA256 and downloaded-byte checks. Hardware not validated.\n")
    except Exception as exc:
        status.update({"status": "failed", "error_type": type(exc).__name__, "error": str(exc)})
        (output / "publisher-status.json").write_text(json.dumps(status, indent=2) + "\n")
        raise


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("STOP: " + str(exc), file=sys.stderr)
        sys.exit(1)
