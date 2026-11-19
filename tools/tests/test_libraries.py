"""Script libraries: what one must be to be listed, what the checker says
about it, the package the gallery makes of it and the pages it gets.

A library is not played in a box as a stack is. People install it, and
it then runs as their own scripts do. So these tests hold the things
that stand in for the box: a library is plain text that can be read, it
takes nobody else's names, the package is made here from the text that
was checked, and the list the IDE reads is signed.
"""
import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout, redirect_stderr

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import accept  # noqa: E402
import build_site  # noqa: E402
import ed25519  # noqa: E402
import fixtures  # noqa: E402
import lcscan  # noqa: E402
import listing  # noqa: E402
import pr_scan  # noqa: E402
import scan  # noqa: E402
import sign  # noqa: E402
from test_build_site import fake_player  # noqa: E402

GOOD = {'title': 'Easing', 'author': 'A. Name', 'description': 'Curves for smooth movement.',
        'licence': 'MIT', 'main': 'easing.livecodescript'}
PATHS = {'listing.json', 'easing.livecodescript', 'Easing.oxtstack', 'notes/easing.livecodescript'}


class Listings(unittest.TestCase):
    """listing.json of a library."""

    def check(self, **changes):
        data = dict(GOOD)
        for key, value in changes.items():
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
        return listing.check(data, PATHS, 'library')

    def test_a_good_listing(self):
        out, problems = self.check(demo='easing-demo', tags=['animation'])
        self.assertEqual(problems, [])
        self.assertEqual(out['demo'], 'easing-demo')
        self.assertEqual(out['main'], 'easing.livecodescript')

    def test_the_licences_a_library_may_have(self):
        for licence in ('GPL-3.0-only', 'GPL-3.0-or-later', 'LGPL-3.0-only', 'LGPL-3.0-or-later', 'Apache-2.0',
                        'MIT', 'BSD-2-Clause', 'BSD-3-Clause'):
            with self.subTest(licence=licence):
                self.assertEqual(self.check(licence=licence)[1], [])
        # ones that cannot be used together with GPL 3, or that are no licence
        for licence in ('GPL-2.0-only', 'CC-BY-NC-4.0', 'Proprietary', 'mit', '', 3, 'All rights reserved'):
            with self.subTest(licence=licence):
                out, problems = self.check(licence=licence)
                self.assertIsNone(out)
                self.assertIn('can be used with it', problems[0])

    def test_a_stack_still_takes_gpl_3_only(self):
        """The wider choice is a library's. A stack plays with the GPL 3
        player and stays GPL 3."""
        data = dict(GOOD, main='Easing.oxtstack')
        self.assertIsNone(listing.check(data, PATHS, 'stack')[0])
        self.assertIsNone(listing.check(data, PATHS)[0])
        self.assertEqual(listing.check(dict(data, licence='GPL-3.0-only'), PATHS)[1], [])
        self.assertEqual(sorted(listing.licences()), ['GPL-3.0-only', 'GPL-3.0-or-later'])

    def test_main_is_the_script_file_at_the_top(self):
        for main in ('Easing.oxtstack', 'notes/easing.livecodescript', 'missing.livecodescript', 'listing.json'):
            with self.subTest(main=main):
                self.assertIsNone(self.check(main=main)[0])

    def test_demo_is_the_name_of_a_stack(self):
        for demo in ('Easing Demo', '../x', 'https://example.org', 'a', '', 7, 's/x/play.html'):
            with self.subTest(demo=demo):
                self.assertIsNone(self.check(demo=demo)[0])
        # and only a library has one
        out, problems = listing.check(dict(GOOD, main='Easing.oxtstack', licence='GPL-3.0-only',
                                           demo='easing-demo'), PATHS, 'stack')
        self.assertIsNone(out)
        self.assertIn('"demo"', problems[0])

    def test_the_words_are_held_to_the_stacks_rules(self):
        self.assertIsNone(self.check(title='<b>Easing</b>')[0])
        self.assertIsNone(self.check(description='See https://example.org for more.')[0])
        self.assertIsNone(self.check(extra='x')[0])
        self.assertIsNone(self.check(author=None)[0])

    def test_folder_names(self):
        self.assertEqual(listing.check_path('easing', '1.0', 'library'), [])
        self.assertIn('library', listing.check_path('Easing Lib', '1.0', 'library')[0])


class Scripts(unittest.TestCase):
    """What the checker reads in a library's script, with no engine."""

    def test_handlers(self):
        script = ('on mouseUp\nend mouseUp\ncommand Go pX\nend Go\nprivate function hid\nend hid\n'
                  'function  twice  pA, pB\nend twice\n-- function notOne\ngetProp cSize\nend cSize\n')
        self.assertEqual(lcscan.handlers(script), [
            ('command', 'mouseUp', False, 1), ('command', 'Go', False, 3), ('function', 'hid', True, 5),
            ('function', 'twice', False, 7), ('getprop', 'cSize', False, 10)])
        self.assertEqual([(h['name'], h['text']) for h in scan.public_handlers(script)], [
            ('mouseUp', 'on mouseUp'), ('Go', 'command Go pX'), ('twice', 'function twice pA, pB'),
            ('cSize', 'getProp cSize')])

    def test_what_puts_a_script_in_every_stacks_way(self):
        for line in ('insert the script of me into back', 'insert script of button 1 into front',
                     'start using stack "x"', 'if x then start using me'):
            with self.subTest(line=line):
                self.assertEqual(len(lcscan.message_path_lines('on a\n   %s\nend a' % line)), 1)
        for line in ('put "insert the script into back" into x', '-- start using me', 'start editing group 1',
                     'put the backScripts into x'):
            with self.subTest(line=line):
                self.assertEqual(lcscan.message_path_lines('on a\n   %s\nend a' % line), [])

    def test_names_a_library_may_call_itself(self):
        for name in ('anna.easing', 'easing', 'Tom_Lib', 'my-lib.v2', 'community.easing'):
            with self.subTest(name=name):
                self.assertIsNone(scan.library_name_problem(name))
        for name in ('ab', 'My Library', 'lib..x', '.lib', 'lib.', '2lib', 'x' * 61, 'li/b', 'lib"x', ''):
            with self.subTest(name=name):
                self.assertIn('letters and digits', scan.library_name_problem(name))
        # the names of the IDE's own stacks and libraries
        for name in ('revIDELibrary', 'REVmenubar', 'com.livecode.library.json', 'org.openxtalk.sodiumxt',
                     'Home', 'ide'):
            with self.subTest(name=name):
                self.assertIn('OXT-Beyond\'s own', scan.library_name_problem(name))

    def test_names_of_the_libraries_already_here(self):
        with tempfile.TemporaryDirectory() as root:
            fixtures.make_library(root, slug='older', version='1.0', name='tests.older',
                                  script='function olOld\nend olOld\n')
            fixtures.make_library(root, slug='older', version='1.10', name='tests.Older',
                                  script='function olNew\nend olNew\nprivate command olHid\nend olHid\n'
                                         'on extensionInitialize\nend extensionInitialize\n')
            fixtures.make_library(root, slug='other', name='tests.other', script='command otGo\nend otGo\n')
            # folders that are not libraries are passed over, not believed
            os.makedirs(os.path.join(root, 'libraries', 'empty'))
            broken = fixtures.make_library(root, slug='broken')
            with open(os.path.join(broken, 'listing.json'), 'w') as f:
                f.write('{"main": "../../other/1.0/other.livecodescript"}')
            libraries = os.path.join(root, 'libraries')
            taken, names = scan.library_names(libraries)
            # (the newest version's names, and no private handler)
            self.assertEqual(taken, {'olnew': 'older', 'otgo': 'other'})
            self.assertEqual(names, {'tests.older': 'older', 'tests.other': 'other'})
            self.assertEqual(scan.library_names(libraries, skip='older')[0], {'otgo': 'other'})
            self.assertEqual(scan.library_names(os.path.join(root, 'none')), ({}, {}))


class Engine(unittest.TestCase):
    """tools/scan.py on libraries, with the engine: ones that can be
    shared, and one for every rule that refuses."""

    def setUp(self):
        fixtures.need_engine(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def scan(self, folder, **more):
        return scan.scan_folder(folder, fixtures.ENGINE, **more)

    def rules(self, report):
        return sorted({p['rule'] for p in report['problems']})

    def library(self, script, **more):
        return self.scan(fixtures.make_library(self.root, script=script, **more))

    # ---- libraries that can be shared

    def test_a_good_library(self):
        report = self.library(fixtures.LIBRARY_SCRIPT)
        self.assertTrue(report['ok'], report['problems'])
        self.assertEqual(report['kind'], 'library')
        self.assertEqual(report['uses'], [])
        self.assertEqual(report['notes'], [])
        library = report['library']
        self.assertEqual(library['name'], 'tests.testlibrary')
        self.assertEqual(library['file'], 'test-library.livecodescript')
        # the private handler is not something it offers
        self.assertEqual([(h['kind'], h['name'], h['text']) for h in library['handlers']],
                         [('function', 'tlTwice', 'function tlTwice pValue')])
        self.assertTrue(library['wrapped'])
        text = scan.markdown(report)
        self.assertIn('This library can be shared', text)
        self.assertIn('`tlTwice`', text)
        self.assertIn('not played in a box', text)

    def test_the_folder_says_it_is_a_library(self):
        """Nothing in a listing can make a library be checked as a
        stack: the kind is where it lies."""
        folder = fixtures.make_library(self.root, script=fixtures.LIBRARY_SCRIPT)
        self.assertEqual(self.scan(folder)['kind'], 'library')
        with open(os.path.join(folder, 'listing.json')) as f:
            data = json.load(f)
        data['kind'] = 'stack'
        with open(os.path.join(folder, 'listing.json'), 'w') as f:
            json.dump(data, f)
        report = self.scan(folder)
        self.assertEqual(report['kind'], 'library')
        self.assertFalse(report['ok'])

    def test_badges_and_notes(self):
        report = self.library('function tlGet pUrl\n   return url pUrl\nend tlGet\n'
                              'command tlSave pText\n   put pText into url "file:notes.txt"\nend tlSave\n'
                              'on openStack\n   pass openStack\nend openStack\n'
                              'on keyDown pKey\n   pass keyDown\nend keyDown\n'
                              'command tlStart\n   insert the script of me into back\nend tlStart\n'
                              'command tlRun pScript\n   do pScript\nend tlRun\n')
        self.assertTrue(report['ok'], report['problems'])
        self.assertEqual(report['uses'], ['files', 'internet'])
        self.assertEqual(report['notes'], ['catches-messages', 'could-fetch-script', 'do', 'message-path'])
        self.assertEqual(report['library']['messages'], ['keyDown', 'openStack'])
        # the engine's messages are not handlers it offers
        self.assertEqual([h['name'] for h in report['library']['handlers']], ['tlGet', 'tlSave', 'tlStart', 'tlRun'])
        text = scan.markdown(report)
        self.assertIn('from every stack', text)
        self.assertIn('`openStack`', text)

    def test_a_library_with_its_own_load_handlers_is_not_wrapped(self):
        report = self.library(fixtures.LIBRARY_SCRIPT
                              + 'on extensionInitialize\n   insert the script of me into back\n'
                                'end extensionInitialize\n'
                                'on extensionFinalize\n   remove the script of me from back\nend extensionFinalize\n')
        self.assertTrue(report['ok'], report['problems'])
        self.assertFalse(report['library']['wrapped'])
        self.assertEqual([h['name'] for h in report['library']['handlers']], ['tlTwice'])
        self.assertEqual(report['notes'], ['message-path'])

    def test_text_and_pictures_may_come_with_it(self):
        folder = fixtures.make_library(self.root, script=fixtures.LIBRARY_SCRIPT)
        with open(os.path.join(folder, 'README.md'), 'w') as f:
            f.write('# How to use it\n')
        report = self.scan(folder)
        self.assertTrue(report['ok'], report['problems'])

    # ---- libraries that cannot

    def test_a_stack_that_is_not_script_only(self):
        """A library must be text that anyone can read and compare: a
        stack with cards and controls is not."""
        folder = fixtures.make_library(self.root, file='lib.livecodescript')
        os.remove(os.path.join(folder, 'lib.livecodescript'))
        fixtures.make_stack(os.path.join(folder, 'lib.livecodescript'), 'tests.binary',
                            script=fixtures.LIBRARY_SCRIPT)
        report = self.scan(folder)
        self.assertFalse(report['ok'])
        self.assertEqual(self.rules(report), ['library'])
        self.assertIn('script-only stack', report['problems'][0]['text'])
        self.assertIsNone(report['library'])

    def test_a_binary_stack_named_as_main(self):
        folder = fixtures.make_library(self.root)
        fixtures.make_stack(os.path.join(folder, 'Lib.oxtstack'), 'tests.binary', script=fixtures.LIBRARY_SCRIPT)
        with open(os.path.join(folder, 'listing.json')) as f:
            data = json.load(f)
        data['main'] = 'Lib.oxtstack'
        with open(os.path.join(folder, 'listing.json'), 'w') as f:
            json.dump(data, f)
        report = self.scan(folder)
        self.assertFalse(report['ok'])
        self.assertIn('listing', self.rules(report))

    def test_more_than_one_script_file(self):
        folder = fixtures.make_library(self.root, script=fixtures.LIBRARY_SCRIPT)
        with open(os.path.join(folder, 'helper.livecodescript'), 'w') as f:
            f.write('script "tests.helper"\nfunction thHelp\nend thHelp\n')
        report = self.scan(folder)
        self.assertFalse(report['ok'])
        self.assertEqual(self.rules(report), ['library'])
        self.assertIn('one script file', report['problems'][0]['text'])

    def test_a_file_with_no_first_line(self):
        report = self.library(fixtures.LIBRARY_SCRIPT, header=False)
        self.assertFalse(report['ok'])
        self.assertIn(self.rules(report)[0], ('unreadable', 'library'))

    def test_names_it_may_not_call_itself(self):
        for name, words in (('revIDELibrary', 'OXT-Beyond\'s own'), ('com.livecode.library.json', 'OXT-Beyond\'s own'),
                            ('My Library', 'letters and digits')):
            with self.subTest(name=name):
                report = self.scan(fixtures.make_library(self.root, slug='n%d' % len(name), name=name,
                                                         script=fixtures.LIBRARY_SCRIPT))
                self.assertFalse(report['ok'])
                self.assertEqual(self.rules(report), ['library-name'])
                self.assertIn(words, report['problems'][0]['text'])
                self.assertIn('first line', scan.markdown(report))

    def test_a_name_that_another_library_has(self):
        folder = fixtures.make_library(self.root, name='tests.same', script=fixtures.LIBRARY_SCRIPT)
        report = self.scan(folder, names={'tests.same': 'older'})
        self.assertEqual(self.rules(report), ['library-name'])
        self.assertIn('"older"', report['problems'][0]['text'])
        # (names are told apart as the engine tells them: not by case)
        self.assertFalse(self.scan(folder, names={'tests.same': 'older'}, taken={})['ok'])
        self.assertTrue(self.scan(folder, names={'tests.other': 'older'})['ok'])

    def test_a_handler_that_another_library_has(self):
        folder = fixtures.make_library(self.root, script=fixtures.LIBRARY_SCRIPT)
        report = self.scan(folder, taken={'tltwice': 'older'})
        self.assertFalse(report['ok'])
        self.assertEqual(self.rules(report), ['name-taken'])
        problem = report['problems'][0]
        self.assertIn('"tlTwice"', problem['text'])
        self.assertIn('"older"', problem['text'])
        # (the line in the file, below its first line)
        self.assertEqual(problem['line'], 2)
        self.assertIn('prefix', scan.markdown(report))
        # a private handler is nobody else's business
        self.assertTrue(self.scan(folder, taken={'tlhidden': 'older'})['ok'])

    def test_a_handler_of_the_xtalk_suite(self):
        suite = lcscan.load_suite()
        name = sorted(suite)[0]
        report = self.library('function %s\n   return 1\nend %s\n' % (name, name))
        self.assertFalse(report['ok'])
        self.assertEqual(self.rules(report), ['name-taken'])
        self.assertIn('xTalk Suite', report['problems'][0]['text'])

    def test_nothing_to_call(self):
        for script in ('private function tlHidden\n   return 1\nend tlHidden\n',
                       'on openStack\n   pass openStack\nend openStack\n', '-- nothing\n',
                       'getProp cSize\n   return 1\nend cSize\n'):
            with self.subTest(script=script):
                report = self.scan(fixtures.make_library(self.root, slug='s%d' % len(script), script=script))
                self.assertFalse(report['ok'])
                self.assertEqual(self.rules(report), ['library'])
                self.assertIn('no command or function', report['problems'][0]['text'])

    def test_only_one_of_the_two_load_handlers(self):
        report = self.library(fixtures.LIBRARY_SCRIPT + 'on extensionInitialize\nend extensionInitialize\n')
        self.assertFalse(report['ok'])
        self.assertEqual(self.rules(report), ['library'])
        self.assertIn('only one of', report['problems'][0]['text'])

    def test_what_a_stack_may_not_do_a_library_may_not(self):
        for script, rule in (('function tlRun\n   return shell("x")\nend tlRun\n', 'process'),
                             ('command tlLoad\n   load extension from file "x.lcm"\nend tlLoad\n', 'externals'),
                             ('command tlGo\n   do url "https://example.org/x"\nend tlGo\n', 'remote-code'),
                             ('command tlAs\n   do "x" as "AppleScript"\nend tlAs\n', 'other-language')):
            with self.subTest(rule=rule):
                report = self.scan(fixtures.make_library(self.root, slug='r-' + rule, script=script))
                self.assertFalse(report['ok'])
                self.assertIn(rule, self.rules(report))
                self.assertIn('The library ', [p for p in report['problems'] if p['rule'] == rule][0]['text'])

    def test_a_program_beside_it(self):
        folder = fixtures.make_library(self.root, script=fixtures.LIBRARY_SCRIPT)
        with open(os.path.join(folder, 'helper.txt'), 'wb') as f:
            f.write(b'MZ\x90\x00 not text at all')
        with open(os.path.join(folder, 'module.lcm'), 'wb') as f:
            f.write(b'LCMD\x00')
        report = self.scan(folder)
        self.assertFalse(report['ok'])
        self.assertEqual(self.rules(report), ['files'])

    def test_a_licence_that_cannot_be_used_with_gpl_3(self):
        report = self.scan(fixtures.make_library(self.root, script=fixtures.LIBRARY_SCRIPT,
                                                 listing={'licence': 'CC-BY-NC-4.0'}))
        self.assertFalse(report['ok'])
        self.assertEqual(self.rules(report), ['listing'])

    def test_a_stack_folder_is_not_held_to_the_librarys_rules(self):
        report = self.scan(fixtures.make_folder(self.root, script=fixtures.CLEAN_SCRIPT))
        self.assertTrue(report['ok'], report['problems'])
        self.assertEqual(report['kind'], 'stack')
        self.assertNotIn('library', report)

    def test_command_line(self):
        fixtures.make_library(self.root, slug='older', name='tests.older', script=fixtures.LIBRARY_SCRIPT)
        folder = fixtures.make_library(self.root, slug='newer', name='tests.newer', script=fixtures.LIBRARY_SCRIPT)
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = scan.main([folder, '--engine', fixtures.ENGINE])
        # (the other library in the folder beside it has the handler)
        self.assertEqual(code, 1)
        self.assertIn('already here', out.getvalue())


class Package(unittest.TestCase):
    """The package the gallery makes of a checked library, and what the
    engine makes of the package."""

    def setUp(self):
        fixtures.need_engine(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def package(self, script, **more):
        folder = fixtures.make_library(self.root, script=script, title='Tom & "Jerry"', **more)
        with open(os.path.join(folder, 'README.md'), 'w') as f:
            f.write('# Read me\n')
        report = scan.scan_folder(folder, fixtures.ENGINE)
        self.assertTrue(report['ok'], report['problems'])
        return folder, report, scan.library_package(folder, report)

    def test_what_is_in_it(self):
        folder, report, files = self.package(fixtures.LIBRARY_SCRIPT)
        self.assertEqual([path for path, _ in files], ['manifest.xml', 'README.md', 'test-library.livecodescript'])
        manifest = files[0][1].decode('utf-8')
        self.assertIn('<name>tests.testlibrary</name>', manifest)
        self.assertIn('<title>Tom &amp; &quot;Jerry&quot;</title>', manifest)
        self.assertIn('<version>1.0</version>', manifest)
        self.assertIn('<type>library</type>', manifest)
        self.assertIn('<author>Test Author</author>', manifest)
        # the listing is the gallery's, not the package's
        self.assertNotIn('listing.json', [path for path, _ in files])
        # the library is the author's bytes, with the gallery's lines after them
        with open(os.path.join(folder, 'test-library.livecodescript'), 'rb') as f:
            written = f.read()
        packed = dict(files)['test-library.livecodescript']
        self.assertTrue(packed.startswith(written))
        self.assertEqual(packed[len(written):].decode('ascii').lstrip('\n'), scan.LIBRARY_WRAPPER.lstrip('\n'))

    def test_a_library_with_its_own_load_handlers_is_packed_as_it_is(self):
        script = (fixtures.LIBRARY_SCRIPT + 'on extensionInitialize\n   insert the script of me into back\n'
                  'end extensionInitialize\non extensionFinalize\n   remove the script of me from back\n'
                  'end extensionFinalize\n')
        folder, report, files = self.package(script)
        with open(os.path.join(folder, 'test-library.livecodescript'), 'rb') as f:
            self.assertEqual(dict(files)['test-library.livecodescript'], f.read())

    def test_a_manifest_of_its_own_is_not_the_one_packed(self):
        folder = fixtures.make_library(self.root, script=fixtures.LIBRARY_SCRIPT)
        with open(os.path.join(folder, 'manifest.xml'), 'w') as f:
            f.write('<package><name>revIDELibrary</name></package>')
        report = scan.scan_folder(folder, fixtures.ENGINE)
        if report['ok']:
            files = scan.library_package(folder, report)
            self.assertEqual([path for path, _ in files].count('manifest.xml'), 1)
            self.assertIn(b'<name>tests.testlibrary</name>', files[0][1])

    def test_the_same_bytes_every_time(self):
        _, _, files = self.package(fixtures.LIBRARY_SCRIPT)
        first = build_site.make_package(files)
        self.assertEqual(first, build_site.make_package(files))
        with zipfile.ZipFile(io.BytesIO(first)) as z:
            # (the Extension Manager refuses a package whose first entry is not at its top)
            self.assertEqual(z.namelist()[0], 'manifest.xml')
            self.assertEqual(z.read('README.md'), b'# Read me\n')

    def test_the_engine_loads_the_packed_library_as_the_ide_does(self):
        """The IDE loads a script library by sending it
        extensionInitialize. A library that has no such handler gets the
        gallery's, and must then answer a call from any other stack, once
        however many times it is loaded, and stop when it is let go."""
        _, _, files = self.package(fixtures.LIBRARY_SCRIPT)
        packed = os.path.join(self.root, 'packed.livecodescript')
        with open(packed, 'wb') as f:
            f.write(dict(files)['test-library.livecodescript'])
        driver = os.path.join(self.root, 'driver.livecodescript')
        with open(driver, 'w') as f:
            f.write('''script "oxt_library_test_driver"
on startup
   local tOut, tLib, tError
   put $OXT_TEST_LIBRARY into tLib
   try
      put the short name of stack tLib & return into tOut
      send "extensionInitialize" to stack tLib
      send "extensionInitialize" to stack tLib
      put the number of lines of the backScripts & return after tOut
      put tlTwice(21) & return after tOut
      send "extensionFinalize" to stack tLib
      put the number of lines of the backScripts & return after tOut
   catch tError
      put "ERROR" && line 1 of tError & return after tOut
   end try
   try
      put tlTwice(21) & return after tOut
   catch tError
      put "gone" & return after tOut
   end try
   write tOut to stdout
   quit 0
end startup
''')
        done = subprocess.run([fixtures.ENGINE, '-ui', driver], env=dict(os.environ, OXT_TEST_LIBRARY=packed),
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.stdout.split('\n')[:5], ['tests.testlibrary', '1', '42', '0', 'gone'], done.stdout)


class PullRequests(unittest.TestCase):
    def setUp(self):
        fixtures.need_engine(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = os.path.join(self.tmp.name, 'base')
        self.pr = os.path.join(self.tmp.name, 'pr')
        os.makedirs(os.path.join(self.base, 'stacks'))
        os.makedirs(os.path.join(self.pr, 'stacks'))

    def run_pr(self, *paths, status='added'):
        changed = [{'filename': p, 'status': status} for p in paths]
        return pr_scan.run(changed, self.pr, fixtures.ENGINE, os.path.join(self.base, 'stacks'))

    def test_paths(self):
        changed = [{'filename': p, 'status': 'added'} for p in (
            'libraries/a/1.0/a.livecodescript', 'stacks/b/1.0/listing.json', 'libraries/loose.txt',
            'library/c/1.0/x', 'libraries/d/1.0')]
        shared, removed, other = pr_scan.classify(changed)
        self.assertEqual(shared, {('libraries', 'a', '1.0'), ('stacks', 'b', '1.0')})
        self.assertEqual(other, ['libraries/d/1.0', 'libraries/loose.txt', 'library/c/1.0/x'])

    def test_a_good_library(self):
        fixtures.make_library(self.pr, slug='good')
        ok, text = self.run_pr('libraries/good/1.0/listing.json', 'libraries/good/1.0/good.livecodescript')
        self.assertTrue(ok, text)
        self.assertIn('This library can be shared', text)
        self.assertIn('Every library in this pull request can be shared', text)

    def test_a_refused_library(self):
        fixtures.make_library(self.pr, slug='bad', script='function tlRun\n   return shell("x")\nend tlRun\n')
        ok, text = self.run_pr('libraries/bad/1.0/listing.json')
        self.assertFalse(ok)
        self.assertIn('runs other programs', text)

    def test_a_library_with_other_files_is_refused(self):
        fixtures.make_library(self.pr, slug='good')
        for other in ('tools/scan.py', 'libraries/good/loose.txt', '.github/workflows/scan.yml'):
            with self.subTest(other=other):
                ok, text = self.run_pr('libraries/good/1.0/listing.json', other)
                self.assertFalse(ok)
                self.assertIn('other files', text)

    def test_a_handler_of_a_library_that_is_already_here(self):
        fixtures.make_library(self.base, slug='older', name='tests.older', script=fixtures.LIBRARY_SCRIPT)
        fixtures.make_library(self.pr, slug='newer', name='tests.newer', script=fixtures.LIBRARY_SCRIPT)
        ok, text = self.run_pr('libraries/newer/1.0/listing.json')
        self.assertFalse(ok)
        self.assertIn('already here', text)
        self.assertIn('older', text)

    def test_two_libraries_of_one_pull_request_with_one_name(self):
        fixtures.make_library(self.pr, slug='first', name='tests.first', script=fixtures.LIBRARY_SCRIPT)
        fixtures.make_library(self.pr, slug='second', name='tests.second', script=fixtures.LIBRARY_SCRIPT)
        ok, text = self.run_pr('libraries/first/1.0/listing.json', 'libraries/second/1.0/listing.json')
        self.assertFalse(ok)
        self.assertEqual(text.count('This library can be shared'), 1)
        self.assertEqual(text.count('This library cannot be shared yet'), 1)

    def test_a_new_version_keeps_its_own_names(self):
        fixtures.make_library(self.base, slug='mine', name='tests.mine', script=fixtures.LIBRARY_SCRIPT)
        fixtures.make_library(self.pr, slug='mine', version='1.1', name='tests.mine',
                              script=fixtures.LIBRARY_SCRIPT)
        ok, text = self.run_pr('libraries/mine/1.1/listing.json')
        self.assertTrue(ok, text)
        self.assertIn('new version of a library', text)
        self.assertIn('same author', text)

    def test_a_published_version_is_never_changed(self):
        fixtures.make_library(self.base, slug='mine')
        fixtures.make_library(self.pr, slug='mine')
        ok, text = self.run_pr('libraries/mine/1.0/mine.livecodescript', status='modified')
        self.assertFalse(ok)
        self.assertIn('already published', text)

    def test_a_stack_and_a_library_together(self):
        fixtures.make_folder(self.pr, slug='demo', script=fixtures.CLEAN_SCRIPT)
        fixtures.make_library(self.pr, slug='good', listing={'demo': 'demo'})
        ok, text = self.run_pr('stacks/demo/1.0/listing.json', 'libraries/good/1.0/listing.json')
        self.assertTrue(ok, text)
        self.assertIn('Every stack and library', text)

    def test_removing_a_library(self):
        ok, text = self.run_pr('libraries/gone/1.0/listing.json', status='removed')
        self.assertTrue(ok)
        self.assertIn('Taking a library down', text)


class Accepting(unittest.TestCase):
    """A library that came as a package (tools/accept.py)."""

    def setUp(self):
        fixtures.need_engine(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = os.path.join(self.tmp.name, 'src')
        self.stacks = os.path.join(self.tmp.name, 'repo', 'stacks')
        os.makedirs(self.stacks)
        self.libraries = os.path.join(self.tmp.name, 'repo', 'libraries')
        self.zip = os.path.join(self.tmp.name, 'package.zip')

    def pack(self, root):
        with zipfile.ZipFile(self.zip, 'w', zipfile.ZIP_DEFLATED) as z:
            for folder, _, names in os.walk(root):
                for name in names:
                    full = os.path.join(folder, name)
                    z.write(full, os.path.relpath(full, root).replace(os.sep, '/'))

    def test_a_good_library(self):
        fixtures.make_library(self.src, slug='easing', name='tests.easing')
        self.pack(self.src)
        ok, text = accept.accept(self.zip, fixtures.ENGINE, self.stacks)
        self.assertTrue(ok, text)
        self.assertIn('libraries/easing/1.0/', text)
        self.assertTrue(os.path.isfile(os.path.join(self.libraries, 'easing', '1.0', 'easing.livecodescript')))
        self.assertEqual(os.listdir(self.stacks), [])
        # the same version again is refused
        ok, text = accept.accept(self.zip, fixtures.ENGINE, self.stacks)
        self.assertFalse(ok)
        self.assertIn('already here', text)

    def test_a_refused_library_adds_nothing(self):
        fixtures.make_library(self.src, slug='bad', script='function tlRun\n   return shell("x")\nend tlRun\n')
        self.pack(self.src)
        ok, text = accept.accept(self.zip, fixtures.ENGINE, self.stacks)
        self.assertFalse(ok)
        self.assertIn('runs other programs', text)
        self.assertFalse(os.path.exists(self.libraries))

    def test_names_of_the_libraries_here_are_kept(self):
        fixtures.make_library(os.path.dirname(self.stacks), slug='older', name='tests.older')
        fixtures.make_library(self.src, slug='newer', name='tests.newer')
        self.pack(self.src)
        ok, text = accept.accept(self.zip, fixtures.ENGINE, self.stacks)
        self.assertFalse(ok)
        self.assertIn('already here', text)
        self.assertEqual(os.listdir(self.libraries), ['older'])

    def test_one_folder_only(self):
        with zipfile.ZipFile(self.zip, 'w') as z:
            z.writestr('libraries/a-b/1.0/listing.json', '{}')
            z.writestr('stacks/a-b/1.0/listing.json', '{}')
        ok, text = accept.accept(self.zip, fixtures.ENGINE, self.stacks)
        self.assertFalse(ok)
        self.assertIn('more than one', text)
        with zipfile.ZipFile(self.zip, 'w') as z:
            z.writestr('extensions/a-b/1.0/listing.json', '{}')
        ok, text = accept.accept(self.zip, fixtures.ENGINE, self.stacks)
        self.assertFalse(ok)
        self.assertIn('inside one folder', text)


class Site(unittest.TestCase):
    """The libraries' part of the gallery."""

    @classmethod
    def setUpClass(cls):
        if not (fixtures.ENGINE and os.path.isfile(fixtures.ENGINE)):
            if os.environ.get('OXT_REQUIRE_ENGINE') == '1':
                raise AssertionError('OXT_ENGINE is not an engine, and OXT_REQUIRE_ENGINE=1')
            raise unittest.SkipTest('no engine: set OXT_ENGINE')
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = cls.tmp.name
        fixtures.make_folder(cls.root, slug='alpha-demo', title='Alpha Demo', script=fixtures.CLEAN_SCRIPT)
        # two versions of one library, with a demo that is in the gallery
        fixtures.make_library(cls.root, slug='alpha', version='1.0', title='Alpha', name='tests.alpha',
                              script='function alOld\n   return 1\nend alOld\n')
        fixtures.make_library(cls.root, slug='alpha', version='1.10', title='Alpha', name='tests.alpha',
                              listing={'demo': 'alpha-demo', 'tags': ['maths'], 'licence': 'Apache-2.0'},
                              script='function alNew pA, pB -- </code><script>alert(1)</script>\n'
                                     '   return url "https://example.org"\nend alNew\n'
                                     'on openCard\n   pass openCard\nend openCard\n')
        # awkward words, and a demo that is not in the gallery
        fixtures.make_library(cls.root, slug='tricky', title='Tom & "Jerry"', name='tests.tricky',
                              listing={'author': "O'Neil & Co", 'demo': 'not-here'},
                              script='command trGo\nend trGo\n')
        # one that is refused, and one that takes alpha's handler
        fixtures.make_library(cls.root, slug='refused', title='Refused', name='tests.refused',
                              script='function rfRun\n   return shell("x")\nend rfRun\n')
        fixtures.make_library(cls.root, slug='copycat', title='Copycat', name='tests.copycat',
                              script='function alNew\n   return 2\nend alNew\n')
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
        with open(os.path.join(cls.out, 'libraries.json'), encoding='utf-8') as f:
            cls.libraries = json.load(f)

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

    def entry(self, slug):
        return [e for e in self.libraries['libraries'] if e['slug'] == slug][0]

    def test_the_list(self):
        self.assertEqual(self.libraries['format'], 1)
        self.assertEqual([e['slug'] for e in self.libraries['libraries']], ['alpha', 'tricky'])
        alpha = self.entry('alpha')
        self.assertEqual(alpha['version'], '1.10')
        self.assertEqual([v['version'] for v in alpha['versions']], ['1.10', '1.0'])
        self.assertEqual(alpha['name'], 'tests.alpha')
        self.assertEqual(alpha['licence'], 'Apache-2.0')
        self.assertEqual(alpha['uses'], ['internet'])
        self.assertEqual([h['name'] for h in alpha['handlers']], ['alNew'])
        self.assertEqual(alpha['messages'], ['openCard'])
        self.assertEqual(alpha['demo'], 'alpha-demo')
        self.assertEqual(alpha['download'], 'l/alpha/1.10/alpha-1.10.lce')
        # nothing of the builder's own notes is in what the IDE reads
        self.assertFalse([key for key in alpha if key.startswith('_')])

    def test_the_list_of_stacks_is_what_it_was(self):
        """IDEs that are already out there read index.json. A library
        changes nothing in it."""
        index = json.loads(self.read('index.json'))
        self.assertEqual(sorted(index), ['format', 'name', 'stacks'])
        self.assertEqual(index['format'], 1)
        self.assertEqual([s['slug'] for s in index['stacks']], ['alpha-demo'])
        self.assertEqual(index, self.index)
        self.assertNotIn('tests.alpha', self.read('index.json'))

    def test_the_refused_are_left_out_and_named(self):
        self.assertEqual(sorted(slug for slug, _, _ in self.refused), ['copycat', 'refused'])
        self.assertTrue(any('library refused 1.0 is left out' in line for line in self.log))
        self.assertTrue(any('library copycat 1.0 is left out' in line for line in self.log))
        for slug in ('refused', 'copycat'):
            self.assertFalse(os.path.exists(os.path.join(self.out, 'l', slug)))
        self.assertNotIn('Copycat', self.read('libraries.html'))

    def test_strict_fails_on_a_refused_library(self):
        with self.assertRaises(build_site.BuildError):
            build_site.build(os.path.join(self.root, 'stacks'), fixtures.ENGINE, self.player,
                             os.path.join(self.root, 'strict'), strict=True, log=lambda line: None, env={})

    def test_both_lists_are_signed(self):
        public = ed25519.public_key(self.seed)
        for name in ('index', 'libraries'):
            with self.subTest(name=name):
                data = self.read(name + '.json', 'rb')
                self.assertTrue(sign.verify_bytes(public, data, self.read(name + '.sig')))
                self.assertFalse(sign.verify_bytes(public, data + b' ', self.read(name + '.sig')))
        # one list's signature is not the other's
        self.assertFalse(sign.verify_bytes(public, self.read('libraries.json', 'rb'), self.read('index.sig')))

    def test_no_signature_without_the_key(self):
        out = os.path.join(self.root, 'unsigned')
        build_site.build(os.path.join(self.root, 'stacks'), fixtures.ENGINE, self.player, out,
                         log=lambda line: None, env={})
        self.assertTrue(os.path.isfile(os.path.join(out, 'libraries.json')))
        self.assertFalse(os.path.exists(os.path.join(out, 'libraries.sig')))

    def test_the_package_is_the_one_the_list_names(self):
        for entry in self.libraries['libraries']:
            for version in entry['versions']:
                with self.subTest(slug=entry['slug'], version=version['version']):
                    data = self.read(version['download'], 'rb')
                    self.assertEqual(len(data), version['size'])
                    self.assertEqual(hashlib.sha256(data).hexdigest(), version['sha256'])
                    with zipfile.ZipFile(io.BytesIO(data)) as z:
                        self.assertEqual(z.namelist()[0], 'manifest.xml')
                        self.assertEqual(z.namelist(), [f['path'] for f in version['files']])
                        for f in version['files']:
                            self.assertEqual(hashlib.sha256(z.read(f['path'])).hexdigest(), f['sha256'])
                        self.assertIn(('<name>%s</name>' % version['name']).encode(), z.read('manifest.xml'))
        alpha = self.entry('alpha')
        self.assertEqual((alpha['size'], alpha['sha256']),
                         (alpha['versions'][0]['size'], alpha['versions'][0]['sha256']))

    def test_the_pages(self):
        listing_page = self.read('libraries.html')
        self.assertIn('l/alpha/index.html', listing_page)
        self.assertIn('not a stack you play', listing_page)
        self.assertIn('aria-current="page">Libraries', listing_page)
        page = self.read('l/alpha/index.html')
        self.assertIn('no box around it', page)
        self.assertIn('Read the script', page)
        self.assertIn('alpha-1.10.lce', page)
        self.assertIn('Extension Manager', page)
        # the IDE's own way to install it (File > Community Stacks..., Libraries)
        self.assertIn('<b>File &gt; Community Stacks...</b>: choose <b>Libraries</b>', page)
        self.assertIn('Uses the internet', page)
        self.assertIn('Listens to every stack', page)
        self.assertIn('<code>openCard</code>', page)
        self.assertIn('Apache 2.0', page)
        self.assertIn('GPL 3', page)
        self.assertIn('Earlier versions', page)
        self.assertIn('alpha-1.0.lce', page)
        # every page of the site has the way to the libraries
        for rel in ('index.html', 'safety.html', 'share.html', 's/alpha-demo/index.html'):
            self.assertIn('libraries.html">Libraries</a>', self.read(rel))
        self.assertIn('id="libraries"', self.read('safety.html'))
        self.assertIn('href="share-library.html"', self.read('share.html'))
        share = self.read('share-library.html')
        self.assertNotIn('@FORUM@', share)
        self.assertNotIn('@REPOSITORY@', share)
        # every licence a library may have is named to its author, and no other
        for words in sorted(set(w.split(' (')[0].replace(' or later', '') for w in listing.LIBRARY_LICENCES.values())):
            self.assertIn(words, share)
        self.assertIn('href="share-library.html"', self.read('libraries.html'))

    def test_a_demo_is_a_stack_of_the_gallery_or_nothing(self):
        self.assertIn('href="../../s/alpha-demo/play.html"', self.read('l/alpha/index.html'))
        self.assertNotIn('demo', self.entry('tricky'))
        page = self.read('l/tricky/index.html')
        self.assertNotIn('play.html', page)
        self.assertNotIn('not-here', page)
        self.assertTrue(any('tricky' in line and 'not-here' in line for line in self.log))

    def test_words_from_a_library_cannot_write_the_page(self):
        page = self.read('l/alpha/index.html')
        self.assertNotIn('<script>alert(1)</script>', page)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', page)
        source = self.read('l/alpha/1.10/source.html')
        self.assertNotIn('<script>alert(1)</script>', source)
        self.assertIn('return url &quot;https://example.org&quot;', source)
        tricky = self.read('l/tricky/index.html')
        self.assertIn('Tom &amp; &quot;Jerry&quot;', tricky)
        self.assertIn('O&#x27;Neil &amp; Co', tricky)
        self.assertNotIn('Tom & "Jerry"', self.read('libraries.html'))

    def test_the_source_page_shows_what_the_gallery_added(self):
        source = self.read('l/alpha/1.10/source.html')
        self.assertIn('Added by the gallery', source)
        self.assertIn('on extensionInitialize', source)
        self.assertIn('href="../../../libraries.html">Libraries</a>', source)

    def test_nothing_a_library_brings_is_served_but_its_package(self):
        found = []
        for root, _, names in os.walk(os.path.join(self.out, 'l')):
            found += [name for name in names]
        self.assertEqual(sorted(set(os.path.splitext(name)[1] for name in found)), ['.html', '.lce'])

    def test_a_gallery_with_no_libraries(self):
        root = os.path.join(self.root, 'bare')
        fixtures.make_folder(root, slug='only', title='Only', script=fixtures.CLEAN_SCRIPT)
        out = os.path.join(root, 'site')
        build_site.build(os.path.join(root, 'stacks'), fixtures.ENGINE, self.player, out,
                         log=lambda line: None, env={})
        with open(os.path.join(out, 'libraries.json'), encoding='utf-8') as f:
            self.assertEqual(json.load(f)['libraries'], [])
        with open(os.path.join(out, 'libraries.html'), encoding='utf-8') as f:
            self.assertIn('No library has been shared yet', f.read())


class Repository(unittest.TestCase):
    """The libraries that are in this repository."""

    def test_every_library_here_can_be_shared(self):
        fixtures.need_engine(self)
        libraries = os.path.join(os.path.dirname(TOOLS), 'libraries')
        found = build_site.find_versions(libraries) if os.path.isdir(libraries) else []
        # (a gallery may have no library yet: the first is shared in a pull
        # request of its own, which the checker reads with these tools)
        collected, refused = build_site.collect_libraries(libraries, fixtures.ENGINE, log=lambda line: None)
        self.assertEqual([(slug, version, report['problems']) for slug, version, report in refused], [])
        self.assertEqual(sorted(collected), sorted({slug for slug, _, _ in found}))

    def test_a_demo_carries_its_library_word_for_word(self):
        """A demo plays on its own, so it carries the library. The copy
        must be the library that is listed, or the demo shows something
        else than what people install."""
        root = os.path.dirname(TOOLS)
        libraries = os.path.join(root, 'libraries')
        if not os.path.isdir(libraries):
            return
        for slug, version, folder in build_site.find_versions(libraries):
            with open(os.path.join(folder, 'listing.json'), encoding='utf-8') as f:
                data = json.load(f)
            if 'demo' not in data:
                continue
            with self.subTest(library=slug, version=version):
                with open(os.path.join(folder, data['main']), encoding='utf-8') as f:
                    body = f.read().split('\n', 1)[1].strip()
                demo = os.path.join(root, 'stacks', data['demo'])
                self.assertTrue(os.path.isdir(demo), 'the demo "%s" is not in stacks/' % data['demo'])
                newest = max(os.listdir(demo), key=listing.version_key)
                with open(os.path.join(demo, newest, 'listing.json'), encoding='utf-8') as f:
                    main = json.load(f)['main']
                with open(os.path.join(demo, newest, main), 'rb') as f:
                    stack = f.read().decode('utf-8', 'replace').replace('\r\n', '\n').replace('\r', '\n')
                # (only the newest version of a library is held to its demo)
                newest_library = max(os.listdir(os.path.join(libraries, slug)), key=listing.version_key)
                if version == newest_library:
                    self.assertIn(body, stack)


if __name__ == '__main__':
    unittest.main()
