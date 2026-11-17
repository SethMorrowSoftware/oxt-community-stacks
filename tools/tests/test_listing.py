"""tools/listing.py: what a listing.json may say."""
import json
import os
import re
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

import listing  # noqa: E402

PATHS = {'listing.json', 'Beat Box.oxtstack', 'shot.png', 'notes.txt'}
GOOD = {'title': 'Beat Box', 'author': 'A. Name', 'description': 'A drum machine with four tracks.',
        'licence': 'GPL-3.0-only', 'main': 'Beat Box.oxtstack', 'screenshot': 'shot.png', 'tags': ['music', 'game']}


def problems(**changes):
    data = dict(GOOD)
    for key, value in changes.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    return listing.check(data, PATHS)


class Listing(unittest.TestCase):
    def test_good(self):
        out, found = listing.check(GOOD, PATHS)
        self.assertEqual(found, [])
        self.assertEqual(out['title'], 'Beat Box')
        self.assertEqual(out['tags'], ['game', 'music'])

    def test_optional_fields_may_be_left_out(self):
        out, found = problems(screenshot=None, tags=None)
        self.assertEqual(found, [])
        self.assertEqual(out['tags'], [])
        self.assertNotIn('screenshot', out)

    def test_required_fields(self):
        for key in listing.REQUIRED:
            with self.subTest(key=key):
                out, found = problems(**{key: None})
                self.assertIsNone(out)
                self.assertTrue(any('"%s"' % key in p for p in found), found)

    def test_unknown_field(self):
        out, found = problems(homepage='x')
        self.assertIsNone(out)
        self.assertIn('homepage', found[0])

    def test_markup_and_links_are_refused(self):
        for key in ('title', 'author', 'description'):
            for value in ('<b>Beat</b> Box and more words', 'see https://example.org for more of it',
                          'visit www.example.org for more of it', 'a\x00b and more words here',
                          'x\x1b[31m and more words here'):
                with self.subTest(key=key, value=value):
                    out, found = problems(**{key: value})
                    self.assertIsNone(out)
                    self.assertEqual(len(found), 1)

    def test_lengths(self):
        self.assertIsNone(problems(title='B')[0])
        self.assertIsNone(problems(title='B' * 61)[0])
        self.assertIsNone(problems(description='short')[0])
        self.assertIsNone(problems(description='d' * 601)[0])
        self.assertIsNotNone(problems(description='d' * 600)[0])
        self.assertIsNone(problems(title=7)[0])

    def test_text_is_tidied(self):
        out, _ = problems(title='  Beat   Box ', description='One.\n\n\n\nTwo words more.  ')
        self.assertEqual(out['title'], 'Beat Box')
        self.assertEqual(out['description'], 'One.\n\nTwo words more.')

    def test_licence_must_be_on_the_list(self):
        self.assertIsNone(problems(licence='Proprietary')[0])
        self.assertIsNone(problems(licence=['GPL-3.0-only'])[0])
        for name in listing.LICENCES:
            self.assertIsNotNone(problems(licence=name)[0])

    def test_a_community_stack_is_gpl_3(self):
        # the engine and the player a stack plays on are GPL 3, so the
        # stack is too; the licences the gallery once took are refused
        self.assertEqual(set(listing.LICENCES), {'GPL-3.0-only', 'GPL-3.0-or-later'})
        for name in ('MIT', 'Apache-2.0', 'BSD-2-Clause', 'BSD-3-Clause', 'GPL-2.0-or-later',
                     'LGPL-3.0-or-later', 'MPL-2.0', 'CC0-1.0', 'CC-BY-4.0', 'CC-BY-SA-4.0', 'Unlicense'):
            out, found = problems(licence=name)
            self.assertIsNone(out, name)
            self.assertTrue(any('GPL 3' in p for p in found), found)

    def test_every_stack_here_is_gpl_3(self):
        root = os.path.join(os.path.dirname(TOOLS), 'stacks')
        seen = 0
        for slug in sorted(os.listdir(root)):
            for version in sorted(os.listdir(os.path.join(root, slug))):
                with open(os.path.join(root, slug, version, 'listing.json'), encoding='utf-8') as f:
                    self.assertIn(json.load(f)['licence'], listing.LICENCES, slug + ' ' + version)
                seen += 1
        self.assertGreater(seen, 0)

    def test_main_must_be_a_file_of_the_folder(self):
        self.assertIsNone(problems(main='Other.oxtstack')[0])
        self.assertIsNone(problems(main='listing.json')[0])
        self.assertIsNone(problems(main='../Beat Box.oxtstack')[0])

    def test_screenshot_must_be_a_picture_of_the_folder(self):
        self.assertIsNone(problems(screenshot='missing.png')[0])
        self.assertIsNone(problems(screenshot='notes.txt')[0])

    def test_tags(self):
        self.assertIsNone(problems(tags=['a', 'b', 'c', 'd', 'e', 'f'])[0])
        self.assertIsNone(problems(tags=['Has Capitals'])[0])
        self.assertIsNone(problems(tags='game')[0])
        self.assertIsNone(problems(tags=['<i>'])[0])

    def test_not_an_object(self):
        self.assertIsNone(listing.check(['x'], PATHS)[0])

    def test_folder_names(self):
        self.assertEqual(listing.check_path('beat-box', '1.0'), [])
        self.assertEqual(listing.check_path('beat-box-2', '12.0.3'), [])
        for slug in ('Beat-Box', 'be', 'beat_box', '-beat', 'beat--box', 'beat box', 'b' * 41, '..'):
            with self.subTest(slug=slug):
                self.assertEqual(len(listing.check_path(slug, '1')), 1)
        for version in ('v1', '1.', '1.0-beta', '', '1.2.3.4.5', '..'):
            with self.subTest(version=version):
                self.assertEqual(len(listing.check_path('beat-box', version)), 1)

    def test_versions_sort_as_numbers(self):
        versions = ['1.9', '1.10', '2', '1.2.3']
        self.assertEqual(sorted(versions, key=listing.version_key), ['1.2.3', '1.9', '1.10', '2'])

    def test_read(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'listing.json')
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(GOOD, f)
            self.assertEqual(listing.read(path, PATHS)[1], [])
            with open(path, 'w', encoding='utf-8') as f:
                f.write('{not json')
            self.assertIn('not valid JSON', listing.read(path, PATHS)[1][0])
            with open(path, 'wb') as f:
                f.write(b'\xff\xfe{}')
            self.assertIsNone(listing.read(path, PATHS)[0])
            with open(path, 'w', encoding='utf-8') as f:
                f.write(' ' * (listing.MAX_LISTING_BYTES + 1))
            self.assertIn('too big', listing.read(path, PATHS)[1][0])


class Documents(unittest.TestCase):
    """What the README tells an author is what the rules are."""

    def setUp(self):
        root = os.path.dirname(TOOLS)
        with open(os.path.join(root, 'README.md'), encoding='utf-8') as f:
            self.readme = f.read()

    def test_the_readme_names_every_licence_and_no_other(self):
        row = [line for line in self.readme.split('\n') if line.startswith('| `licence`')]
        self.assertEqual(len(row), 1)
        named = set(re.findall(r'`([A-Za-z0-9.-]+)`', row[0])) - {'licence'}
        self.assertEqual(named, set(listing.LICENCES))

    def test_the_share_page_asks_for_gpl_3_and_no_other(self):
        with open(os.path.join(os.path.dirname(TOOLS), 'site', 'share.html'), encoding='utf-8') as f:
            page = f.read()
        self.assertIn('GPL 3', page)
        for word in ('MIT', 'BSD', 'Apache', 'CC0', 'Unlicense'):
            self.assertNotIn(word, page)

    def test_the_readme_gives_the_real_lengths(self):
        for name, (low, high) in listing.LENGTHS.items():
            row = [line for line in self.readme.split('\n') if line.startswith('| `%s`' % name)]
            self.assertEqual(len(row), 1, name)
            self.assertIn('%d to %d characters' % (low, high), row[0])

    def test_the_readmes_example_listing_is_a_good_one(self):
        example = re.search(r'```json\n(.*?)```', self.readme, re.S).group(1)
        data = json.loads(example)
        out, problems = listing.check(data, {data['main'], data['screenshot'], 'listing.json'})
        self.assertEqual(problems, [])


if __name__ == '__main__':
    unittest.main()
