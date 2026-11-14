"""tools/accept.py: a stack that came as a package from a stranger."""
import io
import os
import stat
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import accept  # noqa: E402
import fixtures  # noqa: E402
import scan  # noqa: E402


def package_of(folder_root, out):
    """A package of everything under <folder_root>/stacks, as OXT-Beyond's
    File > Share Stack... makes one."""
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(os.path.join(folder_root, 'stacks')):
            dirs.sort()
            for name in sorted(files):
                full = os.path.join(root, name)
                z.write(full, os.path.relpath(full, folder_root).replace(os.sep, '/'))
    return out


def package_with(out, entries):
    """A package of made-up entries: (name, bytes) or (ZipInfo, bytes)."""
    with zipfile.ZipFile(out, 'w') as z:
        for name, data in entries:
            z.writestr(name, data)
    return out


class Plans(unittest.TestCase):
    """What a package may hold, read from its list of names alone."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, 'p.zip')

    def plan(self, entries):
        package_with(self.out, entries)
        with zipfile.ZipFile(self.out) as z:
            return accept.plan(z)

    def refused(self, entries, words):
        with self.assertRaises(accept.Refused) as caught:
            self.plan(entries)
        self.assertIn(words, str(caught.exception))

    def test_a_good_package(self):
        slug, version, files = self.plan([
            ('stacks/', b''), ('stacks/beat-box/', b''), ('stacks/beat-box/1.2/', b''),
            ('stacks/beat-box/1.2/listing.json', b'{}'), ('stacks/beat-box/1.2/Beat Box.oxtstack', b'x'),
            ('stacks/beat-box/1.2/art/drum.png', b'y')])
        self.assertEqual((slug, version), ('beat-box', '1.2'))
        self.assertEqual([rel for _, rel in files], ['listing.json', 'Beat Box.oxtstack', 'art/drum.png'])

    def test_paths_that_leave_the_folder(self):
        # (zipfile itself cuts a name at a NUL, writing and reading)
        for name in ('../evil.txt', 'stacks/a-b/1.0/../../../evil.txt', '/etc/passwd', 'stacks/a-b/1.0//x',
                     'stacks\\a-b\\1.0\\x', 'C:/x', 'stacks/a-b/1.0/./x'):
            with self.subTest(name=name):
                self.refused([('stacks/a-b/1.0/listing.json', b'{}'), (name, b'x')], 'path that cannot be used')

    def test_files_outside_the_one_folder(self):
        self.refused([('README.md', b'x')], 'inside one folder')
        self.refused([('stacks/loose.txt', b'x')], 'inside one folder')
        self.refused([('stacks/a-b/loose.txt', b'x')], 'inside one folder')
        self.refused([('tools/scan.py', b'x'), ('stacks/a-b/1.0/listing.json', b'{}')], 'inside one folder')
        self.refused([('.github/workflows/scan.yml', b'x')], 'inside one folder')

    def test_one_stack_only(self):
        self.refused([('stacks/a-b/1.0/listing.json', b'{}'), ('stacks/c-d/1.0/listing.json', b'{}')],
                     'more than one stack folder')
        self.refused([('stacks/a-b/1.0/listing.json', b'{}'), ('stacks/a-b/2.0/listing.json', b'{}')],
                     'more than one stack folder')

    def test_names_of_the_folder(self):
        self.refused([('stacks/Beat Box/1.0/listing.json', b'{}')], 'lower-case')
        self.refused([('stacks/beat-box/latest/listing.json', b'{}')], 'version folder')

    def test_links_and_special_files(self):
        link = zipfile.ZipInfo('stacks/a-b/1.0/passwd.txt')
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.refused([('stacks/a-b/1.0/listing.json', b'{}'), (link, b'/etc/passwd')], 'link or a special file')
        pipe = zipfile.ZipInfo('stacks/a-b/1.0/pipe')
        pipe.external_attr = (stat.S_IFIFO | 0o644) << 16
        self.refused([(pipe, b'')], 'link or a special file')

    def test_the_same_name_twice(self):
        self.refused([('stacks/a-b/1.0/listing.json', b'{}'), ('stacks/a-b/1.0/Listing.JSON', b'{}')], 'twice')

    def test_empty_and_too_many(self):
        self.refused([], 'empty')
        self.refused([('stacks/', b''), ('stacks/a-b/', b''), ('stacks/a-b/1.0/', b'')], 'no stack folder')
        many = [('stacks/a-b/1.0/f%d.txt' % i, b'') for i in range(accept.MAX_ENTRIES + 1)]
        self.refused(many, 'too many files')

    def test_sizes_the_package_claims(self):
        big = b'\0' * (scan.MAX_FILE_BYTES + 1)
        with zipfile.ZipFile(self.out, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('stacks/a-b/1.0/big.txt', big)
        with zipfile.ZipFile(self.out) as z:
            with self.assertRaises(accept.Refused) as caught:
                accept.plan(z)
        self.assertIn('too big', str(caught.exception))


class Packages(unittest.TestCase):
    def setUp(self):
        fixtures.need_engine(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = os.path.join(self.tmp.name, 'src')
        self.stacks = os.path.join(self.tmp.name, 'repo', 'stacks')
        os.makedirs(self.stacks)
        self.zip = os.path.join(self.tmp.name, 'package.zip')

    def accept(self):
        return accept.accept(self.zip, fixtures.ENGINE, self.stacks)

    def everything_under(self, folder):
        return sorted(os.path.relpath(os.path.join(root, name), folder).replace(os.sep, '/')
                      for root, _, files in os.walk(folder) for name in files)

    def test_a_good_stack_is_put_in_its_folder(self):
        fixtures.make_folder(self.src, slug='hello', version='1.0', script=fixtures.CLEAN_SCRIPT)
        package_of(self.src, self.zip)
        ok, text = self.accept()
        self.assertTrue(ok, text)
        self.assertIn('This stack can be shared', text)
        self.assertIn('Accepted', text)
        self.assertEqual(self.everything_under(self.stacks),
                         ['hello/1.0/Test Stack.oxtstack', 'hello/1.0/listing.json', 'hello/1.0/screenshot.png'])
        # and what was put there is, byte for byte, what was sent
        for name in ('Test Stack.oxtstack', 'listing.json', 'screenshot.png'):
            with open(os.path.join(self.src, 'stacks', 'hello', '1.0', name), 'rb') as a, \
                    open(os.path.join(self.stacks, 'hello', '1.0', name), 'rb') as b:
                self.assertEqual(a.read(), b.read(), name)

    def test_a_stack_the_checker_refuses_adds_nothing(self):
        fixtures.make_folder(self.src, slug='bad', script='on openStack\n   get shell("id")\nend openStack')
        package_of(self.src, self.zip)
        ok, text = self.accept()
        self.assertFalse(ok)
        self.assertIn('runs other programs', text)
        self.assertIn('nothing was added', text)
        self.assertEqual(self.everything_under(self.stacks), [])
        self.assertFalse(os.path.exists(os.path.join(self.stacks, 'bad')))

    def test_a_published_version_is_never_replaced(self):
        fixtures.make_folder(self.src, slug='hello', version='1.0', script=fixtures.CLEAN_SCRIPT)
        package_of(self.src, self.zip)
        self.assertTrue(self.accept()[0])
        before = self.everything_under(self.stacks)
        ok, text = self.accept()
        self.assertFalse(ok)
        self.assertIn('already here', text)
        self.assertEqual(self.everything_under(self.stacks), before)

    def test_a_new_version_must_be_higher(self):
        fixtures.make_folder(self.src, slug='hello', version='1.2', script=fixtures.CLEAN_SCRIPT)
        package_of(self.src, self.zip)
        self.assertTrue(self.accept()[0])
        older = os.path.join(self.tmp.name, 'older')
        fixtures.make_folder(older, slug='hello', version='1.1', script=fixtures.CLEAN_SCRIPT)
        package_of(older, self.zip)
        ok, text = self.accept()
        self.assertFalse(ok)
        self.assertIn('must be higher than 1.2', text.replace('\\', ''))
        newer = os.path.join(self.tmp.name, 'newer')
        fixtures.make_folder(newer, slug='hello', version='1.10', script=fixtures.CLEAN_SCRIPT)
        package_of(newer, self.zip)
        ok, text = self.accept()
        self.assertTrue(ok, text)
        self.assertIn('same author', text)

    def test_a_package_that_unpacks_to_more_than_it_says(self):
        """A .zip's list of sizes is the sender's word. Here it says a
        file is small, and the file is not."""
        fixtures.make_folder(self.src, slug='hello', version='1.0', script=fixtures.CLEAN_SCRIPT)
        package_of(self.src, self.zip)
        with zipfile.ZipFile(self.zip, 'a', zipfile.ZIP_DEFLATED) as z:
            z.writestr('stacks/hello/1.0/notes.txt', b'\0' * 4096)
        limit = scan.MAX_FILE_BYTES
        scan.MAX_FILE_BYTES = 1024
        try:
            with zipfile.ZipFile(self.zip) as z:
                files = [(info, info.filename.split('/', 3)[3]) for info in z.infolist()]
                with self.assertRaises(accept.Refused) as caught:
                    accept.unpack(z, files, os.path.join(self.tmp.name, 'out'))
        finally:
            scan.MAX_FILE_BYTES = limit
        self.assertIn('more than it says', str(caught.exception))

    def test_what_is_not_a_package(self):
        with open(self.zip, 'wb') as f:
            f.write(b'this is not a zip file')
        ok, text = self.accept()
        self.assertFalse(ok)
        self.assertIn('not a .zip', text)
        package_with(self.zip, [('stacks/a-b/1.0/../../../../evil.txt', b'x')])
        ok, text = self.accept()
        self.assertFalse(ok)
        self.assertIn('path that cannot be used', text)
        self.assertEqual(self.everything_under(self.tmp.name + '/repo'), [])
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, 'evil.txt')))

    def test_a_link_in_the_package_is_never_followed(self):
        fixtures.make_folder(self.src, slug='hello', version='1.0', script=fixtures.CLEAN_SCRIPT)
        package_of(self.src, self.zip)
        link = zipfile.ZipInfo('stacks/hello/1.0/secret.txt')
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(self.zip, 'a') as z:
            z.writestr(link, '/etc/passwd')
        ok, text = self.accept()
        self.assertFalse(ok)
        self.assertIn('link or a special file', text)
        self.assertEqual(self.everything_under(self.stacks), [])

    def test_names_from_a_package_cannot_write_markdown(self):
        package_with(self.zip, [('stacks/a-b/1.0/listing.json', b'{}'),
                                ('stacks/<img src=x>/1.0/[x](http://example.org)', b'x')])
        ok, text = self.accept()
        self.assertFalse(ok)
        self.assertNotIn('<img', text)
        self.assertNotIn('](http', text)

    def test_command_line(self):
        fixtures.make_folder(self.src, slug='hello', version='1.0', script=fixtures.CLEAN_SCRIPT)
        package_of(self.src, self.zip)

        def main(*args):
            out = io.StringIO()
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                code = accept.main(list(args))
            return code, out.getvalue()
        code, text = main(self.zip, '--engine', fixtures.ENGINE, '--stacks', self.stacks)
        self.assertEqual(code, 0, text)
        self.assertIn('Accepted', text)
        code, text = main(self.zip, '--engine', fixtures.ENGINE, '--stacks', self.stacks)
        self.assertEqual(code, 1)
        # a check that cannot run accepts nothing
        other = os.path.join(self.tmp.name, 'other')
        fixtures.make_folder(other, slug='second', version='1.0', script=fixtures.CLEAN_SCRIPT)
        package_of(other, self.zip)
        code, text = main(self.zip, '--engine', os.path.join(self.tmp.name, 'no-engine'), '--stacks', self.stacks)
        self.assertEqual(code, 2)
        self.assertFalse(os.path.exists(os.path.join(self.stacks, 'second')))


if __name__ == '__main__':
    unittest.main()
