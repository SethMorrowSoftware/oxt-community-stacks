#!/usr/bin/env python3
"""Checks what a pull request does to the stacks, for the Scan workflow.

    python3 tools/pr_scan.py --changed changed.json --pr <the pull request's files>
        --engine <engine> --markdown report.md [--no-network]

changed.json is GitHub's own list of the files the pull request changes
(GET /repos/.../pulls/N/files: "filename", "status", and for a renamed
file "previous_filename"). This script and the stacks/ folder it stands
beside are the repository's own, from the branch the pull request wants
to join; --pr is a folder holding the pull request's stacks/, which is
somebody else's data and is only ever read.

What a pull request may do:

  - Share: add one or more new stacks/<name>/<version>/ folders, and
    nothing else. Each is checked with tools/scan.py. A version that is
    already published cannot be changed (share a higher version instead),
    and a new version must be higher than the ones there.
  - Take down: remove stacks, and nothing else.
  - Change the repository itself (tools, pages, workflows), with no
    stack in the same pull request. There is nothing to scan then; the
    Checks workflow tests it, and an admin reads it.

A pull request that mixes sharing with anything else is refused: the
person who approves a stack should have nothing else to read.

Exit code 0: nothing stands in the way. 1: something does; the report
says what. 2: the check could not run.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import listing as listing_rules  # noqa: E402
import scan  # noqa: E402

MARKER = '<!-- oxt-community-stacks scan -->'
MAX_STACKS = 10
STACK_PATH = re.compile(r'^stacks/([^/]+)/([^/]+)/(.+)$')


def classify(changed):
    """(shared, removed, other): shared and removed are sets of (slug,
    version) with files added or changed, or with files removed; other
    the changed paths that are not a stack's."""
    shared, removed, other = set(), set(), []
    for item in changed:
        paths = [(item['filename'], item.get('status', 'modified'))]
        if item.get('previous_filename'):
            paths.append((item['previous_filename'], 'removed'))
        for path, status in paths:
            m = STACK_PATH.match(path)
            if not m:
                other.append(path)
            elif status == 'removed':
                removed.add((m.group(1), m.group(2)))
            else:
                shared.add((m.group(1), m.group(2)))
    return shared, removed, sorted(other)


def published_versions(base_stacks, slug):
    folder = os.path.join(base_stacks, slug)
    if not os.path.isdir(folder):
        return []
    return sorted((v for v in os.listdir(folder)
                   if os.path.isdir(os.path.join(folder, v)) and listing_rules.VERSION.match(v)),
                  key=listing_rules.version_key)


def run(changed, pr_dir, engine, base_stacks=None, no_network=False):
    """(ok, markdown) for a pull request."""
    if base_stacks is None:
        base_stacks = os.path.join(ROOT, 'stacks')
    shared, removed, other = classify(changed)
    out = [MARKER, '# The stack check', '']
    if not shared and not removed:
        out += ['This pull request shares no stack and removes none, so there is nothing to scan. '
                'It changes the repository itself, which the Checks workflow tests and an admin reads.', '']
        return True, '\n'.join(out)
    if other:
        out += ['**This pull request cannot be merged as it is.** It changes stacks and other files '
                'together. A pull request that shares or removes a stack may change nothing outside '
                '`stacks/`. The other files:', '']
        out += ['- ' + scan.md_code(p) for p in other[:30]]
        if len(other) > 30:
            out.append('- ... and %d more' % (len(other) - 30))
        return False, '\n'.join(out) + '\n'

    ok = True
    # (a version with both removed and added files is a changed one)
    for slug, version in sorted(removed - shared):
        out += ['- Removes %s version %s. Taking a stack down is an admin\'s decision.'
                % (scan.md(slug), scan.md(version)), '']
    if len(shared) > MAX_STACKS:
        out += ['**Too many stacks in one pull request** (%d; at most %d).' % (len(shared), MAX_STACKS), '']
        return False, '\n'.join(out)
    for slug, version in sorted(shared):
        before = published_versions(base_stacks, slug)
        if os.path.isdir(os.path.join(base_stacks, slug, version)):
            ok = False
            out += ['## %s, version %s' % (scan.md(slug), scan.md(version)), '',
                    '**This version is already published and cannot be changed.** People may have it '
                    'already. Share your changes as a higher version, in a new folder.', '']
            continue
        if before and listing_rules.VERSION.match(version) \
                and listing_rules.version_key(version) <= listing_rules.version_key(before[-1]):
            ok = False
            out += ['## %s, version %s' % (scan.md(slug), scan.md(version)), '',
                    '**The version must be higher than %s**, the newest one published.' % before[-1], '']
            continue
        folder = os.path.join(pr_dir, 'stacks', slug, version)
        if not os.path.isdir(folder) or os.path.islink(folder):
            ok = False
            out += ['## %s, version %s' % (scan.md(slug), scan.md(version)), '',
                    '**The folder is not in the pull request** as GitHub lists it.', '']
            continue
        report = scan.scan_folder(folder, engine, no_network)
        ok = ok and report['ok']
        out.append(scan.markdown(report))
        if report['ok'] and before:
            out += ['For the reviewer: this is a new version of a stack that is already here '
                    '(newest so far: %s). Check that it comes from the same author.' % before[-1], '']
    out.append('**Every stack in this pull request can be shared.** An admin will look at it before it '
               'is listed.' if ok else
               '**Something stands in the way** (see above). Change the stack and push again; '
               'this check runs again by itself.')
    return ok, '\n'.join(out) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Check what a pull request does to the stacks.')
    parser.add_argument('--changed', required=True)
    parser.add_argument('--pr', required=True)
    parser.add_argument('--engine', default=os.environ.get('OXT_ENGINE'))
    parser.add_argument('--markdown', required=True)
    parser.add_argument('--kind', help='write one word here: none (no stack in the pull request), '
                                       'ok, refused or error')
    parser.add_argument('--count', type=int, help='how many files GitHub says the pull request changes')
    parser.add_argument('--no-network', action='store_true')
    args = parser.parse_args(argv)

    def finish(kind, text, code):
        # (GitHub takes a comment of at most 65536 characters)
        if len(text) > 60000:
            text = text[:60000] + '\n\n(the report is longer than a comment can be; the rest is in the job\'s log)\n'
        with open(args.markdown, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        if args.kind:
            with open(args.kind, 'w', encoding='ascii', newline='\n') as f:
                f.write(kind + '\n')
        print(text, file=sys.stderr if code == 2 else sys.stdout)
        return code

    try:
        with open(args.changed, encoding='utf-8') as f:
            changed = json.load(f)
        if not isinstance(changed, list) or not all(
                isinstance(c, dict) and isinstance(c.get('filename'), str) for c in changed):
            raise ValueError('not a list of changed files')
        # (GitHub lists at most 3000 files of a pull request; one with
        # more could keep a stack out of sight)
        if args.count is not None and len(changed) != args.count:
            raise ValueError('GitHub lists %d changed files, and the pull request has %d'
                             % (len(changed), args.count))
        ok, text = run(changed, args.pr, args.engine, no_network=args.no_network)
    except (scan.ScanError, OSError, ValueError) as e:
        return finish('error', '%s\n# The stack check\n\nThe check could not run, so nothing was approved: %s\n'
                      % (MARKER, scan.md(e)), 2)
    shared, removed, _ = classify(changed)
    return finish(('ok' if ok else 'refused') if shared or removed else 'none', text, 0 if ok else 1)


if __name__ == '__main__':
    sys.exit(main())
