#!/usr/bin/env python3
"""Takes a stack that somebody sent as a package, and puts it where a
pull request can share it.

    python3 tools/accept.py <package.zip> [--engine <engine>] [--no-network]
        [--stacks stacks]

Not everybody who makes a stack uses GitHub. OXT-Beyond's File > Share
Stack... packs a stack, its listing and a screenshot into one .zip, which
its author posts on the forum. An admin gives that file to this tool. It
unpacks the package into stacks/<name>/<version>/ only when everything
about it is in order, and prints the checker's report either way. Then
the admin opens a pull request with the new folder, as for any stack.

A package is a .zip holding exactly one folder, laid out as it will be
here:

    stacks/<name>/<version>/listing.json
    stacks/<name>/<version>/<the stack>
    stacks/<name>/<version>/screenshot.png      (and any other files)

The package comes from a stranger, so nothing in it is believed:

  - Every name in it must be a plain path below that one folder: no
    absolute path, no "..", no backslash, no link, no name twice.
  - It is unpacked into a folder of its own first, a file at a time, and
    never more than the limits allow whatever sizes the .zip claims.
  - The unpacked folder goes through tools/scan.py, as a pull request's
    does. Only a stack that can be shared is moved into stacks/.

Exit code 0: the stack is in stacks/. 1: it was refused; the report says
why, and nothing was added. 2: the check could not run.
"""
import argparse
import os
import shutil
import stat
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import listing as listing_rules  # noqa: E402
import scan  # noqa: E402

# A .zip of the most a stack may be compresses to less than this
MAX_PACKAGE_BYTES = scan.MAX_TOTAL_BYTES + 4 * 1024 * 1024
# (the files, and the folders above and among them)
MAX_ENTRIES = scan.MAX_FILES + 50


class Refused(Exception):
    """The package is not one this tool unpacks; str() says why, in
    words for its author."""


def plan(archive):
    """((top folder, slug, version), [(ZipInfo, relative path)]) for an
    open ZipFile whose every entry is in order; the top folder is
    "stacks" or "libraries". Raises Refused."""
    infos = archive.infolist()
    if not infos:
        raise Refused('The package is empty.')
    if len(infos) > MAX_ENTRIES:
        raise Refused('The package has too many files (%d; at most %d).' % (len(infos), scan.MAX_FILES))
    where, files, seen, total = None, [], set(), 0
    for info in infos:
        name = info.filename
        if '\\' in name or '\x00' in name or name.startswith('/') or (len(name) > 1 and name[1] == ':'):
            raise Refused('The package has a file with a path that cannot be used: %r.' % name)
        is_dir = name.endswith('/')
        parts = name.rstrip('/').split('/')
        if any(p in ('', '.', '..') for p in parts):
            raise Refused('The package has a file with a path that cannot be used: %r.' % name)
        # (the type a Unix zip records: a link is a file whose content is
        # where it points, and is never unpacked)
        # (many zip programs record the permissions and no type at all)
        kind = stat.S_IFMT(info.external_attr >> 16)
        if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise Refused('The package has a link or a special file: %r.' % name)
        if info.flag_bits & 0x1:
            raise Refused('The package is locked with a password.')
        if parts[0] not in listing_rules.KINDS or (len(parts) < 4 and not is_dir):
            raise Refused('Everything in the package must be inside one folder, stacks/<name>/<version>/ '
                          'or libraries/<name>/<version>/. This is not: %r.' % name)
        if len(parts) >= 3:
            if where is None:
                where = (parts[0], parts[1], parts[2])
            elif where != (parts[0], parts[1], parts[2]):
                raise Refused('The package holds more than one stack folder: %s/%s/%s and %s/%s/%s.'
                              % (where + (parts[0], parts[1], parts[2])))
        key = name.rstrip('/').lower()
        if key in seen:
            raise Refused('The package has the same name twice: %r.' % name)
        seen.add(key)
        if is_dir or len(parts) < 4:
            continue
        total += info.file_size
        if info.file_size > scan.MAX_FILE_BYTES or total > scan.MAX_TOTAL_BYTES:
            raise Refused('The package is too big: a stack\'s files may be %d MB each and %d MB together.'
                          % (scan.MAX_FILE_BYTES // 1048576, scan.MAX_TOTAL_BYTES // 1048576))
        files.append((info, '/'.join(parts[3:])))
    if where is None or not files:
        raise Refused('The package has no stack folder, stacks/<name>/<version>/, and no library '
                      'folder, libraries/<name>/<version>/.')
    problems = listing_rules.check_path(where[1], where[2], listing_rules.KINDS[where[0]])
    if problems:
        raise Refused(' '.join(problems))
    return where, files


def unpack(archive, files, folder):
    """Writes the planned files below `folder`, never more bytes than a
    stack may have, whatever the package says its files hold."""
    total = 0
    for info, rel in files:
        target = os.path.join(folder, *rel.split('/'))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        written = 0
        with archive.open(info) as src, open(target, 'xb') as dst:
            while True:
                block = src.read(1 << 20)
                if not block:
                    break
                written += len(block)
                total += len(block)
                if written > scan.MAX_FILE_BYTES or total > scan.MAX_TOTAL_BYTES:
                    raise Refused('The package unpacks to more than it says it holds.')
                dst.write(block)
        os.chmod(target, 0o644)


def accept(package, engine, stacks_dir=None, no_network=False):
    """(accepted, text): unpacks `package` into stacks/<name>/<version>/
    when the stack in it can be shared. `text` is the report, as
    Markdown. Raises scan.ScanError when the check cannot run."""
    if stacks_dir is None:
        stacks_dir = os.path.join(ROOT, 'stacks')
    try:
        if os.path.getsize(package) > MAX_PACKAGE_BYTES:
            raise Refused('The package is too big (more than %d MB).' % (MAX_PACKAGE_BYTES // 1048576))
        archive = zipfile.ZipFile(package)
    except Refused as e:
        return False, '**The package was not accepted.** %s\n' % scan.md(e)
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
        return False, '**The package was not accepted.** It is not a .zip file that can be read.\n'
    work = tempfile.mkdtemp(prefix='oxt-accept-')
    try:
        with archive:
            try:
                (top, slug, version), files = plan(archive)
                kind = listing_rules.KINDS[top]
                # (libraries/ stands beside stacks/)
                base = stacks_dir if top == 'stacks' else os.path.join(os.path.dirname(stacks_dir), top)
                final = os.path.join(base, slug, version)
                if os.path.lexists(final):
                    raise Refused('Version %s of "%s" is already here. A published version is never changed: '
                                  'share the changes as a higher version.' % (version, slug))
                before = [v for v in (os.listdir(os.path.join(base, slug))
                                      if os.path.isdir(os.path.join(base, slug)) else [])
                          if listing_rules.VERSION.match(v)]
                if any(listing_rules.version_key(version) <= listing_rules.version_key(v) for v in before):
                    raise Refused('The version must be higher than %s, the newest one of "%s" here.'
                                  % (max(before, key=listing_rules.version_key), slug))
                folder = os.path.join(work, top, slug, version)
                os.makedirs(folder)
                unpack(archive, files, folder)
            except Refused as e:
                return False, '**The package was not accepted.** %s\n' % scan.md(e)
            except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, ValueError):
                # (zipfile's own words for a damaged or unusual package)
                return False, '**The package was not accepted.** It is damaged, or packed in a way that cannot be read.\n'
        taken = names = None
        if kind == 'library':
            taken, names = scan.library_names(base, skip=slug)
        report = scan.scan_folder(folder, engine, no_network, kind=kind, taken=taken, names=names)
        text = scan.markdown(report)
        if not report['ok']:
            return False, text + '\n**The package was not accepted**, and nothing was added.\n'
        os.makedirs(os.path.dirname(final), exist_ok=True)
        shutil.move(folder, final)
        note = ''
        if before:
            note = ('\nFor the reviewer: this is a new version of a %s that is already here. '
                    'Check that it comes from the same author.\n' % kind)
        return True, text + note + '\n**Accepted** into `%s/%s/%s/`. Open a pull request with that folder.\n' % (
            top, slug, version)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Take a stack that was sent as a package.')
    parser.add_argument('package', help='the .zip that File > Share Stack... made')
    parser.add_argument('--engine', default=os.environ.get('OXT_ENGINE'),
                        help='the OXT-Beyond engine (LiveCode-Community); or set OXT_ENGINE')
    parser.add_argument('--stacks', default=os.path.join(ROOT, 'stacks'))
    parser.add_argument('--no-network', action='store_true',
                        help='run the engine with no network (Linux; needs root or sudo)')
    args = parser.parse_args(argv)
    try:
        ok, text = accept(args.package, args.engine, args.stacks, args.no_network)
    except scan.ScanError as e:
        print('The check could not run, so nothing was accepted: %s' % e, file=sys.stderr)
        return 2
    print(text)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
