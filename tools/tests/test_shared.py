"""The stacks and libraries shared in this repository: each listing that
is here passes tools/listing.py, in a folder with a good name.

This needs no engine and no browser, so a listing that the gallery would
refuse (a tag too long, a "fill" that is not true or false, a main file
that is not there) fails here, in the first seconds of a run, and names
the folder. What the scanner reads in a stack, and whether it plays,
are the build's and browser-check.js's (.github/workflows/checks.yml).
"""
import os
import sys
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

import listing  # noqa: E402


def shared(top):
    """(slug, version, folder) of every version folder under top."""
    base = os.path.join(ROOT, top)
    for slug in sorted(os.listdir(base)):
        if not os.path.isdir(os.path.join(base, slug)):
            continue
        for version in sorted(os.listdir(os.path.join(base, slug))):
            folder = os.path.join(base, slug, version)
            if os.path.isdir(folder):
                yield slug, version, folder


def files(folder):
    out = set()
    for here, _dirs, names in os.walk(folder):
        for name in names:
            out.add(os.path.relpath(os.path.join(here, name), folder).replace(os.sep, '/'))
    return out


class Shared(unittest.TestCase):
    def check(self, top, kind):
        seen = 0
        for slug, version, folder in shared(top):
            with self.subTest(folder='%s/%s/%s' % (top, slug, version)):
                self.assertEqual(listing.check_path(slug, version, kind), [])
                out, problems = listing.read(os.path.join(folder, 'listing.json'), files(folder), kind)
                self.assertEqual(problems, [])
                seen += 1
        return seen

    def test_every_stack_listing_passes(self):
        self.assertGreater(self.check('stacks', 'stack'), 0)

    def test_every_library_listing_passes(self):
        self.assertGreater(self.check('libraries', 'library'), 0)

    def test_ember_bricks_fills_the_window(self):
        # A game that lays itself out for whatever window it has (its
        # arena as large as fits, the score beside it or over it): at
        # its own size, 900 by 640, it would sit small in a big window.
        folder = os.path.join(ROOT, 'stacks', 'ember-bricks', '1.0')
        out, problems = listing.read(os.path.join(folder, 'listing.json'), files(folder))
        self.assertEqual(problems, [])
        self.assertIs(out.get('fill'), True)
        self.assertEqual(out['main'], 'Ember Bricks.oxtstack')
        self.assertEqual(out['licence'], 'GPL-3.0-only')


if __name__ == '__main__':
    unittest.main()
