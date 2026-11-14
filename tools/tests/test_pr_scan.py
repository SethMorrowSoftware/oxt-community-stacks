"""tools/pr_scan.py: what a pull request may do to the stacks."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fixtures  # noqa: E402
import pr_scan  # noqa: E402
import scan  # noqa: E402


def added(*paths):
    return [{'filename': p, 'status': 'added'} for p in paths]


class Classify(unittest.TestCase):
    def test_paths(self):
        changed = added('stacks/a/1.0/listing.json', 'stacks/a/1.0/art/x.png', 'README.md', 'stacks/note.txt',
                        'stacks/a/loose.txt') + [
            {'filename': 'stacks/b/2/x.oxtstack', 'status': 'removed'},
            {'filename': 'stacks/c/1/new.oxtstack', 'status': 'renamed', 'previous_filename': 'stacks/d/1/old.oxtstack'},
            {'filename': 'tools/scan.py', 'status': 'modified'}]
        shared, removed, other = pr_scan.classify(changed)
        self.assertEqual(shared, {('a', '1.0'), ('c', '1')})
        self.assertEqual(removed, {('b', '2'), ('d', '1')})
        self.assertEqual(other, ['README.md', 'stacks/a/loose.txt', 'stacks/note.txt', 'tools/scan.py'])


class PullRequests(unittest.TestCase):
    def setUp(self):
        fixtures.need_engine(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = os.path.join(self.tmp.name, 'base')
        self.pr = os.path.join(self.tmp.name, 'pr')
        os.makedirs(os.path.join(self.base, 'stacks'))
        os.makedirs(os.path.join(self.pr, 'stacks'))

    def run_pr(self, changed):
        return pr_scan.run(changed, self.pr, fixtures.ENGINE, os.path.join(self.base, 'stacks'))

    def test_a_good_stack(self):
        fixtures.make_folder(self.pr, slug='good', script=fixtures.CLEAN_SCRIPT)
        ok, text = self.run_pr(added('stacks/good/1.0/listing.json', 'stacks/good/1.0/Test Stack.oxtstack'))
        self.assertTrue(ok, text)
        self.assertIn('Every stack in this pull request can be shared', text)
        self.assertTrue(text.startswith(pr_scan.MARKER))

    def test_a_refused_stack(self):
        fixtures.make_folder(self.pr, slug='bad', script='on a\n   get shell("x")\nend a')
        ok, text = self.run_pr(added('stacks/bad/1.0/listing.json'))
        self.assertFalse(ok)
        self.assertIn('runs other programs', text)
        self.assertIn('Something stands in the way', text)

    def test_one_refused_stack_among_good_ones(self):
        fixtures.make_folder(self.pr, slug='good', script=fixtures.CLEAN_SCRIPT)
        fixtures.make_folder(self.pr, slug='bad', script='on a\n   get shell("x")\nend a')
        ok, _ = self.run_pr(added('stacks/good/1.0/listing.json', 'stacks/bad/1.0/listing.json'))
        self.assertFalse(ok)

    def test_nothing_to_scan(self):
        ok, text = self.run_pr(added('tools/scan.py', 'README.md'))
        self.assertTrue(ok)
        self.assertIn('nothing to scan', text)

    def test_a_stack_with_other_files_is_refused(self):
        fixtures.make_folder(self.pr, slug='good', script=fixtures.CLEAN_SCRIPT)
        for other in ('tools/scan.py', '.github/workflows/scan.yml', 'stacks/good/loose.txt', 'stacks/x.txt'):
            with self.subTest(other=other):
                ok, text = self.run_pr(added('stacks/good/1.0/listing.json', other))
                self.assertFalse(ok)
                self.assertIn('other files', text)
                self.assertIn(other, text)

    def test_a_takedown(self):
        ok, text = self.run_pr([{'filename': 'stacks/old/1.0/listing.json', 'status': 'removed'}])
        self.assertTrue(ok)
        self.assertIn('Removes old version 1.0', text)

    def test_a_published_version_cannot_be_changed(self):
        fixtures.make_folder(self.base, slug='good', script=fixtures.CLEAN_SCRIPT)
        fixtures.make_folder(self.pr, slug='good', script=fixtures.CLEAN_SCRIPT)
        ok, text = self.run_pr([{'filename': 'stacks/good/1.0/Test Stack.oxtstack', 'status': 'modified'}])
        self.assertFalse(ok)
        self.assertIn('already published', text)

    def test_a_new_version_must_be_higher(self):
        fixtures.make_folder(self.base, slug='good', version='1.10', script=fixtures.CLEAN_SCRIPT)
        for version, fine in (('1.9', False), ('1.10.1', True), ('2', True), ('0.5', False)):
            with self.subTest(version=version):
                pr = tempfile.mkdtemp(dir=self.tmp.name)
                fixtures.make_folder(pr, slug='good', version=version, script=fixtures.CLEAN_SCRIPT)
                ok, text = pr_scan.run(added('stacks/good/%s/listing.json' % version), pr, fixtures.ENGINE,
                                       os.path.join(self.base, 'stacks'))
                self.assertEqual(ok, fine, text)
                if fine:
                    self.assertIn('same author', text)
                else:
                    self.assertIn('must be higher than 1.10', text)

    def test_a_folder_github_lists_but_the_checkout_lacks(self):
        ok, text = self.run_pr(added('stacks/ghost/1.0/listing.json'))
        self.assertFalse(ok)

    def test_too_many(self):
        changed = added(*['stacks/s%d/1.0/listing.json' % i for i in range(pr_scan.MAX_STACKS + 1)])
        ok, text = self.run_pr(changed)
        self.assertFalse(ok)
        self.assertIn('Too many', text)

    def test_names_from_a_pull_request_cannot_write_markdown(self):
        evil = 'x](http://example.org) @someone <img src=x>'
        ok, text = self.run_pr([{'filename': 'stacks/%s/1.0/a' % evil.replace('/', '%'), 'status': 'removed'}])
        self.assertNotIn('](http', text)
        self.assertNotIn('@someone', text)
        self.assertNotIn('<img', text)
        fixtures.make_folder(self.pr, slug='named', script=fixtures.CLEAN_SCRIPT,
                             button='on mouseUp\n   put url "https://example.org/`x`" into y -- @someone\nend mouseUp',
                             name='[click](http://example.org) @someone')
        ok, text = self.run_pr(added('stacks/named/1.0/listing.json'))
        self.assertTrue(ok, text)
        self.assertNotIn('[click](http', text)
        self.assertNotIn('@someone', text)

    def test_command_line(self):
        fixtures.make_folder(self.pr, slug='bad', script='on a\n   get shell("x")\nend a')
        changed = os.path.join(self.tmp.name, 'changed.json')
        report = os.path.join(self.tmp.name, 'report.md')

        def main(data, engine=fixtures.ENGINE):
            with open(changed, 'w') as f:
                json.dump(data, f)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                return pr_scan.main(['--changed', changed, '--pr', self.pr, '--engine', engine,
                                     '--markdown', report])
        self.assertEqual(main(added('README.md')), 0)
        self.assertEqual(main(added('stacks/bad/1.0/listing.json')), 1)
        with open(report, encoding='utf-8') as f:
            self.assertIn('runs other programs', f.read())
        # a check that cannot run approves nothing
        self.assertEqual(main({'not': 'a list'}), 2)
        self.assertEqual(main(added('stacks/bad/1.0/listing.json'), os.path.join(self.tmp.name, 'none')), 2)
        with open(report, encoding='utf-8') as f:
            self.assertIn('could not run', f.read())

    def test_command_line_says_what_kind_of_pull_request_it_was(self):
        fixtures.make_folder(self.pr, slug='bad', script='on a\n   get shell("x")\nend a')
        fixtures.make_folder(self.pr, slug='good', script=fixtures.CLEAN_SCRIPT)
        changed = os.path.join(self.tmp.name, 'changed.json')
        report = os.path.join(self.tmp.name, 'report.md')
        kind = os.path.join(self.tmp.name, 'kind')

        def main(data, *more):
            with open(changed, 'w') as f:
                json.dump(data, f)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = pr_scan.main(['--changed', changed, '--pr', self.pr, '--engine', fixtures.ENGINE,
                                     '--markdown', report, '--kind', kind] + list(more))
            with open(kind, encoding='ascii') as f:
                return code, f.read().strip()
        self.assertEqual(main(added('README.md')), (0, 'none'))
        self.assertEqual(main(added('stacks/good/1.0/listing.json')), (0, 'ok'))
        self.assertEqual(main(added('stacks/bad/1.0/listing.json')), (1, 'refused'))
        self.assertEqual(main([{'filename': 'stacks/good/1.0/listing.json', 'status': 'removed'}]), (0, 'ok'))
        # GitHub's list must be the whole pull request: one that is cut
        # short (it stops at 3000 files) approves nothing
        self.assertEqual(main(added('stacks/good/1.0/listing.json'), '--count', '1'), (0, 'ok'))
        self.assertEqual(main(added('stacks/good/1.0/listing.json'), '--count', '3001'), (2, 'error'))
        with open(report, encoding='utf-8') as f:
            text = f.read()
        self.assertIn('could not run', text)
        self.assertTrue(text.startswith(pr_scan.MARKER))


if __name__ == '__main__':
    unittest.main()
