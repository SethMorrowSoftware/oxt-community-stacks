"""tools/build_site.py: what the gallery holds, and what it never does."""
import base64
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
import zipfile

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import build_site  # noqa: E402
import ed25519  # noqa: E402
import fixtures  # noqa: E402
import sign  # noqa: E402

# What the builder needs of a Stack Player: a play page that keeps to its
# own site, and files beside it
PLAY_PAGE = '<!doctype html>\n<html>\n<head>\n<title>p</title>\n</head>\n<body><script>function sameSite(p){}</script></body></html>\n'


def fake_player(root):
    player = os.path.join(root, 'StackPlayer')
    os.makedirs(os.path.join(player, 'play'))
    os.makedirs(os.path.join(player, 'assets'))
    os.makedirs(os.path.join(player, 'samples'))
    for rel, text in (('play/index.html', PLAY_PAGE), ('index.html', 'home'), ('engine.js', 'js'),
                      ('engine.wasm', 'wasm'), ('standalone.zip', 'zip'), ('assets/logo.png', 'png'),
                      ('samples/samples.json', '[]')):
        with open(os.path.join(player, *rel.split('/')), 'w') as f:
            f.write(text)
    return player


class Site(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (fixtures.ENGINE and os.path.isfile(fixtures.ENGINE)):
            if os.environ.get('OXT_REQUIRE_ENGINE') == '1':
                raise AssertionError('OXT_ENGINE is not an engine, and OXT_REQUIRE_ENGINE=1')
            raise unittest.SkipTest('no engine: set OXT_ENGINE')
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = cls.tmp.name
        # two versions of one stack, one stack with awkward words, one
        # that is refused, one whose "screenshot" is not a picture
        fixtures.make_folder(cls.root, slug='alpha', version='1.0', title='Alpha',
                             script='on a\n   put url "https://example.org" into x\nend a')
        fixtures.make_folder(cls.root, slug='alpha', version='1.10', title='Alpha',
                             script='on a\n   save this stack\nend a -- </pre><script>alert(1)</script>')
        fixtures.make_folder(cls.root, slug='alpha', version='1.9', title='Alpha', script=fixtures.CLEAN_SCRIPT)
        fixtures.make_folder(cls.root, slug='tricky', title='Tom & "Jerry"', screenshot=False,
                             file='Tricky.oxtstack', name='Tricky',
                             listing={'author': "O'Neil & Co", 'tags': ['game']},
                             script=fixtures.CLEAN_SCRIPT)
        fixtures.make_folder(cls.root, slug='refused', title='Refused',
                             script='on a\n   get shell("x")\nend a')
        folder = fixtures.make_folder(cls.root, slug='notpicture', title='Not Picture',
                                      script=fixtures.CLEAN_SCRIPT)
        with open(os.path.join(folder, 'screenshot.png'), 'wb') as f:
            f.write(b'<html><script>alert(1)</script></html>')
        with open(os.path.join(folder, 'page.html'), 'w') as f:
            f.write('<script>alert(1)</script>')
        cls.player = fake_player(cls.root)
        cls.seed = os.urandom(32)
        cls.out = os.path.join(cls.root, 'site')
        cls.log = []
        cls.public = os.path.join(cls.root, 'signing-key.pub')
        with open(cls.public, 'w') as f:
            f.write(base64.b64encode(ed25519.public_key(cls.seed)).decode() + '\n')
        cls.old_public = sign.PUBLIC_KEY_FILE
        sign.PUBLIC_KEY_FILE = cls.public
        sign.read_public.__defaults__ = (cls.public,)
        cls.index, cls.refused = build_site.build(
            os.path.join(cls.root, 'stacks'), fixtures.ENGINE, cls.player, cls.out, log=cls.log.append,
            env={sign.SECRET_ENV: base64.b64encode(cls.seed).decode()})

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'old_public'):
            sign.PUBLIC_KEY_FILE = cls.old_public
            sign.read_public.__defaults__ = (cls.old_public,)
        if hasattr(cls, 'tmp'):
            cls.tmp.cleanup()

    def read(self, rel, mode='r'):
        with open(os.path.join(self.out, *rel.split('/')), mode, **({} if 'b' in mode else {'encoding': 'utf-8'})) as f:
            return f.read()

    def all_files(self):
        found = []
        for root, _, names in os.walk(self.out):
            for name in names:
                found.append(os.path.relpath(os.path.join(root, name), self.out).replace(os.sep, '/'))
        return sorted(found)

    def test_the_refused_stack_is_left_out_and_named(self):
        self.assertEqual([(s, v) for s, v, _ in self.refused], [('refused', '1.0')])
        self.assertTrue(any('refused 1.0 is left out' in line for line in self.log))
        self.assertFalse(any(path.startswith('s/refused/') for path in self.all_files()))
        self.assertNotIn('Refused', self.read('index.html'))
        self.assertEqual([s['slug'] for s in self.index['stacks']], ['alpha', 'notpicture', 'tricky'])

    def test_strict_fails_on_a_refused_stack(self):
        with self.assertRaises(build_site.BuildError):
            build_site.build(os.path.join(self.root, 'stacks'), fixtures.ENGINE, self.player,
                             os.path.join(self.root, 'strict'), strict=True, log=lambda line: None, env={})

    def test_the_newest_version_is_the_one_shown(self):
        alpha = self.index['stacks'][0]
        self.assertEqual(alpha['version'], '1.10')
        self.assertEqual([v['version'] for v in alpha['versions']], ['1.10', '1.9', '1.0'])
        self.assertEqual(alpha['uses'], ['files'])
        self.assertEqual(alpha['versions'][2]['uses'], ['internet'])
        self.assertIn('alpha-1.10.zip', self.read('s/alpha/play.html'))
        page = self.read('s/alpha/index.html')
        self.assertIn('Earlier versions', page)
        self.assertIn('alpha-1.9.zip', page)

    def test_only_these_kinds_of_file_are_published(self):
        # Nothing a stack brought is served as itself: its files are in
        # its .zip, its picture under a name made here
        for path in self.all_files():
            if path.startswith('s/'):
                self.assertRegex(path, r'^s/[a-z0-9-]+/(index\.html|play\.html|[0-9.]+/'
                                       r'([a-z0-9-]+-[0-9.]+\.zip|source\.html|screenshot\.(png|jpg|jpeg|gif|webp)))$')
        self.assertNotIn('s/notpicture/1.0/page.html', self.all_files())

    def test_a_screenshot_that_is_not_a_picture_is_left_out(self):
        self.assertNotIn('s/notpicture/1.0/screenshot.png', self.all_files())
        entry = [s for s in self.index['stacks'] if s['slug'] == 'notpicture'][0]
        self.assertIsNone(entry['screenshot'])
        self.assertIn('s/alpha/1.10/screenshot.png', self.all_files())

    def test_the_zip_is_the_stacks_files_and_matches_the_index(self):
        alpha = self.index['stacks'][0]
        data = self.read(alpha['download'], 'rb')
        self.assertEqual(hashlib.sha256(data).hexdigest(), alpha['sha256'])
        self.assertEqual(len(data), alpha['size'])
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertEqual(sorted(z.namelist()), ['Alpha.oxtstack', 'screenshot.png'])
            for f in alpha['versions'][0]['files']:
                self.assertEqual(hashlib.sha256(z.read(f['path'])).hexdigest(), f['sha256'])
        self.assertEqual(alpha['main'], 'Alpha.oxtstack')

    def test_the_zip_is_the_same_every_time(self):
        entry = self.index['stacks'][0]
        folder = os.path.join(self.root, 'stacks', 'alpha', '1.10')
        files, _ = build_site.scan.check_files(folder)
        self.assertEqual(hashlib.sha256(build_site.make_zip(folder, files)).hexdigest(), entry['sha256'])

    def test_words_from_a_listing_are_escaped(self):
        for rel in ('index.html', 's/tricky/index.html', 's/tricky/play.html', 's/tricky/1.0/source.html'):
            text = self.read(rel)
            self.assertIn('Tom &amp; &quot;Jerry&quot;', text, rel)
            self.assertNotIn('Tom & "Jerry"', text, rel)
        self.assertIn('O&#x27;Neil &amp; Co', self.read('index.html'))

    def test_script_text_is_escaped_on_the_source_page(self):
        text = self.read('s/alpha/1.10/source.html')
        self.assertIn('&lt;/pre&gt;&lt;script&gt;alert(1)&lt;/script&gt;', text)
        self.assertNotIn('<script>alert(1)</script>', text)
        self.assertIn('save this stack', text)

    def test_the_playing_stack_is_boxed_in(self):
        text = self.read('s/alpha/play.html')
        frames = re.findall(r'<iframe[^>]*>', text)
        self.assertEqual(len(frames), 1)
        sandbox = re.search(r'sandbox="([^"]*)"', frames[0]).group(1).split()
        self.assertIn('allow-scripts', sandbox)
        self.assertNotIn('allow-same-origin', sandbox)
        self.assertNotIn('allow-top-navigation', sandbox)
        self.assertNotIn('allow-top-navigation-by-user-activation', sandbox)
        self.assertIn('src="../../player/play/index.html?stack=../../s/alpha/1.10/alpha-1.10.zip"', frames[0])

    def test_no_page_but_the_play_page_has_a_frame(self):
        for path in self.all_files():
            if path.endswith('.html') and not path.endswith('/play.html') and not path.startswith('player/'):
                self.assertNotIn('<iframe', self.read(path), path)

    def test_the_player_only_plays_in_a_box(self):
        text = self.read('player/play/index.html')
        self.assertIn(build_site.GUARD, text)
        self.assertLess(text.index(build_site.GUARD), text.index('<title>'))
        self.assertIn('self.origin!=="null"', build_site.GUARD)
        files = self.all_files()
        self.assertNotIn('player/index.html', files)
        self.assertFalse(any(p.startswith('player/samples/') for p in files))
        for needed in ('player/engine.js', 'player/engine.wasm', 'player/standalone.zip', 'player/assets/logo.png'):
            self.assertIn(needed, files)

    def test_a_player_that_changed_is_not_published(self):
        for text in (PLAY_PAGE.replace('<head>', '<HEAD>'), PLAY_PAGE.replace('sameSite', 'anySite')):
            root = tempfile.mkdtemp(dir=self.root)
            player = fake_player(root)
            with open(os.path.join(player, 'play', 'index.html'), 'w') as f:
                f.write(text)
            with self.assertRaises(build_site.BuildError):
                build_site.copy_player(player, os.path.join(root, 'out'))

    def test_the_index_is_signed(self):
        text = self.read('index.json', 'rb')
        self.assertEqual(json.loads(text.decode('utf-8')), self.index)
        public = ed25519.public_key(self.seed)
        self.assertTrue(sign.verify_bytes(public, text, self.read('index.sig')))
        self.assertFalse(sign.verify_bytes(public, text + b' ', self.read('index.sig')))

    def test_without_a_key_it_says_so_and_with_the_wrong_one_it_stops(self):
        log = []
        out = os.path.join(self.root, 'unsigned')
        build_site.build(os.path.join(self.root, 'stacks'), fixtures.ENGINE, self.player, out,
                         log=log.append, env={})
        self.assertFalse(os.path.exists(os.path.join(out, 'index.sig')))
        self.assertTrue(any('not signed' in line for line in log))
        with self.assertRaises(build_site.BuildError):
            build_site.build(os.path.join(self.root, 'stacks'), fixtures.ENGINE, self.player,
                             os.path.join(self.root, 'wrongkey'), log=lambda line: None,
                             env={sign.SECRET_ENV: base64.b64encode(os.urandom(32)).decode()})

    def test_the_index_has_what_the_ide_needs(self):
        for entry in self.index['stacks']:
            for key in ('slug', 'title', 'author', 'description', 'licence', 'tags', 'uses', 'version',
                        'main', 'page', 'play', 'download', 'source', 'size', 'sha256', 'screenshot',
                        'script_lines', 'versions'):
                self.assertIn(key, entry)
            for rel in (entry['page'], entry['play'], entry['download'], entry['source']):
                self.assertTrue(os.path.isfile(os.path.join(self.out, *rel.split('/'))), rel)
        self.assertEqual(self.index['format'], 1)

    def test_the_static_pages(self):
        for rel in ('safety.html', 'share.html', '404.html', 'assets/site.css', 'assets/mark.svg', '.nojekyll'):
            self.assertIn(rel, self.all_files())
        self.assertNotIn('@REPOSITORY@', self.read('share.html'))
        self.assertNotIn('@FORUM@', self.read('safety.html'))

    def test_every_link_of_the_site_leads_somewhere(self):
        files = set(self.all_files())
        for path in files:
            if not path.endswith('.html') or path.startswith('player/'):
                continue
            for link in re.findall(r'(?:href|src)="([^"]*)"', self.read(path)):
                link = link.replace('&amp;', '&')
                if re.match(r'^[a-z]+:', link) or link.startswith('#'):
                    continue
                target = os.path.normpath(os.path.join(os.path.dirname(path), link.split('?')[0].split('#')[0]))
                self.assertIn(target.replace(os.sep, '/'), files, '%s links to %s' % (path, link))

    def test_an_out_folder_with_something_in_it_is_refused(self):
        with self.assertRaises(build_site.BuildError):
            build_site.build(os.path.join(self.root, 'stacks'), fixtures.ENGINE, self.player, self.out,
                             log=lambda line: None, env={})


class Empty(unittest.TestCase):
    def test_a_gallery_with_no_stacks(self):
        fixtures.need_engine(self)
        with tempfile.TemporaryDirectory() as root:
            player = fake_player(root)
            index, refused = build_site.build(os.path.join(root, 'stacks'), fixtures.ENGINE, player,
                                              os.path.join(root, 'site'), log=lambda line: None, env={})
            self.assertEqual(index['stacks'], [])
            with open(os.path.join(root, 'site', 'index.html'), encoding='utf-8') as f:
                self.assertIn('Nothing has been shared yet', f.read())


if __name__ == '__main__':
    unittest.main()
