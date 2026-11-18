#!/usr/bin/env python3
"""The rules for listing.json, the few words the gallery shows for a stack.

    {
      "title": "Beat Box",
      "author": "A. Name",
      "description": "A drum machine with four tracks.",
      "licence": "GPL-3.0-only",
      "main": "Beat Box.oxtstack",
      "screenshot": "screenshot.png",        (optional)
      "tags": ["music", "game"]              (optional, at most five)
    }

The folder says the rest: stacks/<name>/<version>/. What the stack uses
(the internet, files) is not written here: the scanner reads it from the
scripts, so a listing cannot say less than the stack does.

A script library is listed the same way, in libraries/<name>/<version>/
(the folder says which of the two it is; a listing never does):

    {
      "title": "Easing",
      "author": "A. Name",
      "description": "Curves for smooth movement.",
      "licence": "MIT",
      "main": "easing.livecodescript",       the library: a script-only stack
      "demo": "easing-demo",                 (optional) a stack of this gallery
      "tags": ["animation"]                  that shows the library at work
    }

Every value is text that strangers will read on a web page and in the
IDE, so it is kept short, plain and free of markup: no control
characters, no angle brackets, no links.
"""
import json
import os
import re

MAX_LISTING_BYTES = 16 * 1024

# The licences an author can choose. A stack plays on OXT-Beyond's
# engine, which is GPL 3, and the gallery serves it with that engine's
# player, so a community stack is GPL 3 too: the licence of OXT-Beyond
# and of LiveCode Community before it. A published stack keeps the licence
# it was listed under; one that a rule now refuses is left out of the
# gallery with a warning. The value is what the gallery shows.
LICENCES = {
    'GPL-3.0-only': 'GPL 3',
    'GPL-3.0-or-later': 'GPL 3 or later',
}

# A library is built into other people's programs, so its author may
# also choose one of the short licences that ask less and that can be
# used together with GPL 3. Whatever a library's own licence, a program
# built with OXT-Beyond holds the GPL 3 engine and is shared under GPL 3
# as a whole; the gallery's pages say so.
LIBRARY_LICENCES = dict(LICENCES, **{
    'LGPL-3.0-only': 'LGPL 3',
    'LGPL-3.0-or-later': 'LGPL 3 or later',
    'Apache-2.0': 'Apache 2.0',
    'MIT': 'MIT',
    'BSD-2-Clause': 'BSD (2 clauses)',
    'BSD-3-Clause': 'BSD (3 clauses)',
})

# The two kinds of thing the gallery lists, by the folder each lives in
KINDS = {'stacks': 'stack', 'libraries': 'library'}
FOLDERS = {kind: folder for folder, kind in KINDS.items()}


def licences(kind='stack'):
    return LIBRARY_LICENCES if kind == 'library' else LICENCES


SLUG = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
VERSION = re.compile(r'^[0-9]+(?:\.[0-9]+){0,3}$')
TAG = re.compile(r'^[a-z0-9]+(?:[ -][a-z0-9]+)*$')

REQUIRED = ('title', 'author', 'description', 'licence', 'main')
OPTIONAL = ('screenshot', 'tags')
LENGTHS = {'title': (2, 60), 'author': (2, 40), 'description': (10, 600)}
SCREENSHOT_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.webp')


def check_path(slug, version, kind='stack'):
    """What is wrong with the folder's own names, as sentences."""
    problems = []
    if not SLUG.match(slug) or not 3 <= len(slug) <= 40:
        problems.append('The %s\'s folder name "%s" must be 3 to 40 lower-case letters, digits '
                        'and single hyphens, such as "beat-box".' % (kind, slug))
    if not VERSION.match(version) or len(version) > 20:
        problems.append('The version folder "%s" must be a number such as 1, 1.2 or 1.2.3.' % version)
    return problems


def version_key(version):
    """Sorts versions as numbers: 1.10 after 1.9."""
    return tuple(int(part) for part in version.split('.'))


def _plain(value, name, low, high, problems):
    if not isinstance(value, str):
        problems.append('"%s" must be text.' % name)
        return None
    text = ' '.join(value.split()) if name != 'description' else value.strip()
    if any(ord(c) < 32 and c not in '\n' for c in text) or '\x7f' in text:
        problems.append('"%s" has characters that cannot be shown.' % name)
        return None
    if '<' in text or '>' in text:
        problems.append('"%s" cannot have < or > in it.' % name)
        return None
    if re.search(r'(?i)\b(?:https?|ftp)://|\bwww\.', text):
        problems.append('"%s" cannot have a web address in it.' % name)
        return None
    if name == 'description':
        text = re.sub(r'\n{3,}', '\n\n', text)
    if not low <= len(text) <= high:
        problems.append('"%s" must be %d to %d characters long (it is %d).' % (name, low, high, len(text)))
        return None
    return text


def check(data, paths, kind='stack'):
    """(listing, [problem, ...]) for a parsed listing.json: the listing
    with every value cleaned up, or None when it cannot be used. `paths`
    is the set of the files in the folder, with "/" between folders;
    `kind` is "stack" or "library"."""
    problems = []
    if not isinstance(data, dict):
        return None, ['listing.json must be one { ... } object.']
    optional = OPTIONAL + (('demo',) if kind == 'library' else ())
    for key in data:
        if key not in REQUIRED + optional:
            problems.append('listing.json has "%s", which is not one of its fields.' % key)
    for key in REQUIRED:
        if key not in data:
            problems.append('listing.json has no "%s".' % key)
    out = {}
    for key, (low, high) in LENGTHS.items():
        if key in data:
            out[key] = _plain(data[key], key, low, high, problems)
    if 'licence' in data:
        if not isinstance(data['licence'], str) or data['licence'] not in licences(kind):
            if kind == 'library':
                problems.append('"licence" must be GPL 3 or a licence that can be used with it: one of %s.'
                                % ', '.join(sorted(LIBRARY_LICENCES)))
            else:
                problems.append('"licence" must be GPL 3, like OXT-Beyond itself: one of %s.'
                                % ', '.join(sorted(LICENCES)))
        else:
            out['licence'] = data['licence']
    if 'main' in data:
        main = data['main']
        if not isinstance(main, str) or main not in paths or main == 'listing.json':
            problems.append('"main" must be the name of the %s file in the folder.' % kind)
        elif kind == 'library' and ('/' in main or not main.lower().endswith('.livecodescript')):
            problems.append('"main" must be the library itself: a script-only stack, a text file '
                            'whose name ends in .livecodescript, at the top of the folder.')
        else:
            out['main'] = main
    if 'demo' in data and kind == 'library':
        demo = data['demo']
        if not isinstance(demo, str) or not SLUG.match(demo) or not 3 <= len(demo) <= 40:
            problems.append('"demo" must be the folder name of a stack in this gallery that shows '
                            'the library at work, such as "beat-box".')
        else:
            out['demo'] = demo
    if 'screenshot' in data:
        shot = data['screenshot']
        if not isinstance(shot, str) or shot not in paths \
                or os.path.splitext(shot)[1].lower() not in SCREENSHOT_EXTENSIONS:
            problems.append('"screenshot" must be the name of a picture (PNG, JPEG, GIF or WebP) '
                            'in the folder.')
        else:
            out['screenshot'] = shot
    tags = data.get('tags', [])
    if not isinstance(tags, list) or len(tags) > 5 or not all(
            isinstance(t, str) and TAG.match(t) and len(t) <= 20 for t in tags):
        problems.append('"tags" must be at most five short lower-case words, such as ["game", "music"].')
    else:
        out['tags'] = sorted(set(tags))
    if problems:
        return None, problems
    return out, []


def read(path, paths, kind='stack'):
    """check() of a listing.json file."""
    try:
        if os.path.getsize(path) > MAX_LISTING_BYTES:
            return None, ['listing.json is too big.']
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, UnicodeError):
        return None, ['listing.json could not be read as UTF-8 text.']
    except ValueError as e:
        return None, ['listing.json is not valid JSON: %s.' % e]
    return check(data, paths, kind)
