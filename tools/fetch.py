#!/usr/bin/env python3
"""Gets the pinned OXT-Beyond engine or Stack Player (tools/pins.json).

    python3 tools/fetch.py engine <folder>    prints the engine's path
    python3 tools/fetch.py player <folder>    prints the player's folder

The scanner reads stacks with OXT-Beyond's own engine, and the gallery
plays them in OXT-Beyond's Stack Player. Both come from one release of
OXT-Beyond, named in pins.json with the SHA-256 of each download: a file
that does not match is never unpacked. To move to a newer release, change
the tag, the asset names and the digests there (the release's SHA256SUMS
file has them), in a pull request of its own, so that the tests run with
it.

Downloads with gh where there is one that is signed in (GitHub's API,
which the runners reach most reliably), otherwise from the release's web
address.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))


def pins():
    with open(os.path.join(HERE, 'pins.json'), encoding='utf-8') as f:
        return json.load(f)


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def download(what, folder):
    """The pinned archive of `what`, in folder, checked."""
    all_pins = pins()
    pin = all_pins[what]
    os.makedirs(folder, exist_ok=True)
    archive = os.path.join(folder, pin['asset'])
    if os.path.isfile(archive) and _sha256(archive) == pin['sha256']:
        return archive, pin
    if os.path.exists(archive):
        os.remove(archive)
    got = False
    if shutil.which('gh') and (os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')):
        got = subprocess.run(['gh', 'release', 'download', pin['tag'], '--repo', all_pins['repository'],
                              '--pattern', pin['asset'], '--dir', folder, '--clobber']).returncode == 0
    if not got:
        url = 'https://github.com/%s/releases/download/%s/%s' % (all_pins['repository'], pin['tag'], pin['asset'])
        last = None
        for _ in range(3):
            try:
                with urllib.request.urlopen(url, timeout=120) as r, open(archive, 'wb') as f:
                    shutil.copyfileobj(r, f)
                last = None
                break
            except OSError as e:
                last = e
        if last is not None:
            raise SystemExit('could not download %s: %s' % (url, last))
    found = _sha256(archive)
    if found != pin['sha256']:
        os.remove(archive)
        raise SystemExit('%s is not the pinned file: SHA-256 %s, expected %s'
                         % (pin['asset'], found, pin['sha256']))
    return archive, pin


def _inside(base, name):
    target = os.path.realpath(os.path.join(base, name))
    return target == base or target.startswith(base + os.sep)


def fetch(what, folder):
    """The path of the unpacked engine, or of the player's folder."""
    folder = os.path.realpath(folder)
    archive, pin = download(what, folder)
    out = os.path.join(folder, what + '-' + pin['sha256'][:12])
    member = os.path.join(out, *pin['member'].split('/'))
    if os.path.exists(member):
        return member
    partial = out + '.partial'
    shutil.rmtree(partial, ignore_errors=True)
    os.makedirs(partial)
    base = os.path.realpath(partial)
    if archive.endswith('.zip'):
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                if not _inside(base, info.filename):
                    raise SystemExit('the archive has a path that leaves its folder: ' + info.filename)
            z.extractall(partial)
    else:
        with tarfile.open(archive) as t:
            for info in t.getmembers():
                # (a symbolic link is named from its own folder, a hard
                # link from the archive's top)
                bad = not _inside(base, info.name)
                if info.issym():
                    bad = bad or not _inside(base, os.path.join(os.path.dirname(info.name), info.linkname))
                elif info.islnk():
                    bad = bad or not _inside(base, info.linkname)
                elif not (info.isfile() or info.isdir()):
                    bad = True
                if bad:
                    raise SystemExit('the archive has a path that leaves its folder: ' + info.name)
            # (Python 3.12 and later: the "tar" filter also refuses what
            # the loop above refuses)
            if hasattr(tarfile, 'tar_filter'):
                t.extractall(partial, filter='tar')
            else:
                t.extractall(partial)
    os.rename(partial, out)
    if not os.path.exists(member):
        raise SystemExit('the archive has no ' + pin['member'])
    return member


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ('engine', 'player'):
        sys.exit(__doc__)
    print(fetch(sys.argv[1], sys.argv[2]))


if __name__ == '__main__':
    main()
