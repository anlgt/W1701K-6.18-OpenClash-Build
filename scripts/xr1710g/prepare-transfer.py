#!/usr/bin/env python3
"""Create verified, bounded transfer parts without changing the primary artifact."""
import hashlib
import os
import tarfile
from pathlib import Path

root, dest = Path('output'), Path('transfer')
dest.mkdir(exist_ok=True)
archive = dest/'candidate.tar'
with tarfile.open(archive, 'w') as tar:
    for path in sorted(root.rglob('*')):
        if path.is_dir():
            continue
        assert path.is_file() and not path.is_symlink(), path
        info = tar.gettarinfo(str(path), arcname=str(path.relative_to(root)))
        info.uid = info.gid = info.mtime = 0
        info.uname = info.gname = ''
        with path.open('rb') as source:
            tar.addfile(info, source)
hashes = [f'{hashlib.sha256(archive.read_bytes()).hexdigest()}  candidate.tar']
with archive.open('rb') as source:
    index = 0
    while data := source.read(20 * 1024 * 1024):
        assert index < 8, 'Candidate exceeds the bounded transfer-part allowance'
        name = f'candidate.part{index:02d}'
        (dest/name).write_bytes(data)
        hashes.append(f'{hashlib.sha256(data).hexdigest()}  {name}')
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as out:
                print(f'part{index:02d}=true', file=out)
        index += 1
(dest/'TRANSFER-SHA256SUMS').write_text('\n'.join(hashes) + '\n')
print(f'Validated output retained in {index} transfer parts; tar bytes={archive.stat().st_size}')
print('\n'.join(hashes))
