#!/usr/bin/env python3
"""The rules for listing.json, the few words the gallery shows for a stack.

    {
      "title": "Beat Box",
      "author": "A. Name",
      "description": "A drum machine with four tracks.",
      "licence": "MIT",
      "main": "Beat Box.oxtstack",
      "screenshot": "screenshot.png",        (optional)
      "tags": ["music", "game"]              (optional, at most five)
    }

The folder says the rest: stacks/<name>/<version>/. What the stack uses
(the internet, files) is not written here: the scanner reads it from the
scripts, so a listing cannot say less than the stack does.

Every value is text that strangers will read on a web page and in the
IDE, so it is kept short, plain and free of markup: no control
characters, no angle brackets, no links.
"""
import json
import os
import re

MAX_LISTING_BYTES = 16 * 1024

# The licences an author can choose: ones that let other people play,
# read and learn from the stack. The value is what the gallery shows.
LICENCES = {
    'MIT': 'MIT',
    'Apache-2.0': 'Apache 2.0',
    'BSD-2-Clause': 'BSD 2-Clause',
    'BSD-3-Clause': 'BSD 3-Clause',
    'GPL-3.0-only': 'GPL 3',
    'GPL-3.0-or-later': 'GPL 3 or later',
    'GPL-2.0-or-later': 'GPL 2 or later',
    'LGPL-3.0-or-later': 'LGPL 3 or later',
    'MPL-2.0': 'MPL 2.0',
    'CC0-1.0': 'Public domain (CC0)',
    'CC-BY-4.0': 'CC BY 4.0',
    'CC-BY-SA-4.0': 'CC BY-SA 4.0',
    'Unlicense': 'Public domain (Unlicense)',
}

SLUG = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
VERSION = re.compile(r'^[0-9]+(?:\.[0-9]+){0,3}$')
TAG = re.compile(r'^[a-z0-9]+(?:[ -][a-z0-9]+)*$')

REQUIRED = ('title', 'author', 'description', 'licence', 'main')
OPTIONAL = ('screenshot', 'tags')
LENGTHS = {'title': (2, 60), 'author': (2, 40), 'description': (10, 600)}
SCREENSHOT_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.webp')


def check_path(slug, version):
    """What is wrong with the folder's own names, as sentences."""
    problems = []
    if not SLUG.match(slug) or not 3 <= len(slug) <= 40:
        problems.append('The stack\'s folder name "%s" must be 3 to 40 lower-case letters, digits '
                        'and single hyphens, such as "beat-box".' % slug)
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


def check(data, paths):
    """(listing, [problem, ...]) for a parsed listing.json: the listing
    with every value cleaned up, or None when it cannot be used. `paths`
    is the set of the files in the folder, with "/" between folders."""
    problems = []
    if not isinstance(data, dict):
        return None, ['listing.json must be one { ... } object.']
    for key in data:
        if key not in REQUIRED + OPTIONAL:
            problems.append('listing.json has "%s", which is not one of its fields.' % key)
    for key in REQUIRED:
        if key not in data:
            problems.append('listing.json has no "%s".' % key)
    out = {}
    for key, (low, high) in LENGTHS.items():
        if key in data:
            out[key] = _plain(data[key], key, low, high, problems)
    if 'licence' in data:
        if not isinstance(data['licence'], str) or data['licence'] not in LICENCES:
            problems.append('"licence" must be one of: %s.' % ', '.join(sorted(LICENCES)))
        else:
            out['licence'] = data['licence']
    if 'main' in data:
        main = data['main']
        if not isinstance(main, str) or main not in paths or main == 'listing.json':
            problems.append('"main" must be the name of the stack file in the folder.')
        else:
            out['main'] = main
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


def read(path, paths):
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
    return check(data, paths)
