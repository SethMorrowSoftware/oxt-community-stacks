"""tools/scan.py with the engine: stacks that may be shared, stacks that
may not, and stacks that try to slip past."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fixtures  # noqa: E402
import scan  # noqa: E402


class Engine(unittest.TestCase):
    def setUp(self):
        fixtures.need_engine(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def scan(self, folder):
        return scan.scan_folder(folder, fixtures.ENGINE)

    def rules(self, report):
        return sorted({p['rule'] for p in report['problems']})

    # ---- stacks that can be shared

    def test_a_clean_stack(self):
        report = self.scan(fixtures.make_folder(self.root, script=fixtures.CLEAN_SCRIPT))
        self.assertTrue(report['ok'], report['problems'])
        self.assertEqual(report['uses'], [])
        self.assertEqual(report['notes'], [])
        self.assertEqual(report['listing']['title'], 'Test Stack')
        self.assertEqual(report['stacks'][0]['name'], 'Test Stack')
        self.assertEqual(sorted(f['kind'] for f in report['files']), ['data', 'listing', 'stack'])

    def test_badges_come_from_every_script_of_the_file(self):
        report = self.scan(fixtures.make_folder(
            self.root, script='on a\n   put url "https://example.org" into x\nend a',
            button='on mouseUp\n   put "x" into url "file:scores.txt"\nend mouseUp',
            substack='on b\n   do "beep()" as "JavaScript"\nend b'))
        self.assertTrue(report['ok'], report['problems'])
        self.assertEqual(report['uses'], ['files', 'internet', 'javascript'])
        self.assertEqual(report['stacks'][0]['substacks'], ['Sub'])
        wheres = {f['rule']: f['where'] for f in report['findings']}
        self.assertIn('the stack script', wheres['url'])
        self.assertIn('button "Go"', wheres['file'])
        self.assertIn('stack "Sub"', wheres['javascript'])

    def test_notes_for_the_reviewer(self):
        report = self.scan(fixtures.make_folder(
            self.root, script='on a\n   put url tU into x\n   do x\nend a'))
        self.assertTrue(report['ok'])
        self.assertEqual(report['notes'], ['could-fetch-script', 'do'])
        self.assertIn('could fetch script', scan.markdown(report))

    def test_a_script_only_stack(self):
        folder = fixtures.make_folder(self.root, script=fixtures.CLEAN_SCRIPT)
        os.remove(os.path.join(folder, 'Test Stack.oxtstack'))
        with open(os.path.join(folder, 'Test Stack.livecodescript'), 'w', encoding='utf-8') as f:
            f.write('script "Test Stack"\non mouseUp\n   answer file "Which?"\nend mouseUp\n')
        with open(os.path.join(folder, 'listing.json')) as f:
            data = json.load(f)
        data['main'] = 'Test Stack.livecodescript'
        with open(os.path.join(folder, 'listing.json'), 'w') as f:
            json.dump(data, f)
        report = self.scan(folder)
        self.assertTrue(report['ok'], report['problems'])
        self.assertEqual(report['uses'], ['files'])

    # ---- stacks that cannot

    def test_shell_in_the_stack_script(self):
        report = self.scan(fixtures.make_folder(
            self.root, script='on openStack\n   put shell("whoami") into x\nend openStack'))
        self.assertFalse(report['ok'])
        self.assertEqual(self.rules(report), ['process'])
        problem = report['problems'][0]
        self.assertEqual(problem['line'], 2)
        self.assertIn('shell', problem['code'])
        self.assertIn('the stack script', problem['where'])
        text = scan.markdown(report)
        self.assertIn('cannot be shared yet', text)
        self.assertIn(scan.ADVICE['process'], text)

    def test_refused_wherever_the_script_is(self):
        for where in ('button', 'substack'):
            with self.subTest(where=where):
                root = tempfile.mkdtemp(dir=self.root)
                report = self.scan(fixtures.make_folder(
                    root, script=fixtures.CLEAN_SCRIPT, **{where: 'on x\n   launch "calc.exe"\nend x'}))
                self.assertEqual(self.rules(report), ['process'])

    def test_native_externals(self):
        report = self.scan(fixtures.make_folder(self.root, script=fixtures.CLEAN_SCRIPT,
                                                externals='evil.dll'))
        self.assertEqual(self.rules(report), ['externals'])
        self.assertIn('evil.dll', report['problems'][0]['text'])

    def test_a_stack_that_takes_the_dump_scripts_name_is_still_read(self):
        # The engine keeps one stack of a name: without the made-up name
        # of each run, this stack's scripts would never be looked at
        report = self.scan(fixtures.make_folder(
            self.root, name='oxt_community_scan_dump',
            script='on openStack\n   put shell("whoami") into x\nend openStack'))
        self.assertEqual(self.rules(report), ['process'])

    def test_a_file_that_is_not_a_stack(self):
        folder = fixtures.make_folder(self.root, script=fixtures.CLEAN_SCRIPT)
        with open(os.path.join(folder, 'Test Stack.oxtstack'), 'wb') as f:
            f.write(b'REVO7000' + os.urandom(2000))
        report = self.scan(folder)
        self.assertEqual(self.rules(report), ['unreadable'])

    def test_a_truncated_stack(self):
        folder = fixtures.make_folder(self.root, script=fixtures.CLEAN_SCRIPT)
        path = os.path.join(folder, 'Test Stack.oxtstack')
        with open(path, 'rb') as f:
            data = f.read()
        with open(path, 'wb') as f:
            f.write(data[:len(data) // 2])
        self.assertEqual(self.rules(self.scan(folder)), ['unreadable'])

    def test_every_stack_file_of_the_folder_is_read(self):
        folder = fixtures.make_folder(self.root, script=fixtures.CLEAN_SCRIPT)
        fixtures.make_stack(os.path.join(folder, 'Library.livecode'), 'Library',
                            script='on libraryStack\n   open process "sh" for update\nend libraryStack')
        report = self.scan(folder)
        self.assertEqual(self.rules(report), ['process'])
        self.assertIn('Library.livecode', report['problems'][0]['where'])

    def test_stack_files_must_stay_in_the_folder(self):
        report = self.scan(fixtures.make_folder(self.root, script=fixtures.CLEAN_SCRIPT,
                                                stackfiles='Lib,/home/someone/Lib.livecode'))
        self.assertEqual(self.rules(report), ['stackfiles'])

    def test_suite_libraries_that_are_not_on_the_web(self):
        report = self.scan(fixtures.make_folder(self.root, script='on a\n   enInitialize\nend a'))
        self.assertEqual(self.rules(report), ['suite-not-on-web'])
        # ... unless the handler is the stack's own (in any of its scripts)
        root = tempfile.mkdtemp(dir=self.root)
        report = self.scan(fixtures.make_folder(
            root, script='on a\n   enInitialize\nend a', button='command enInitialize\nend enInitialize'))
        self.assertTrue(report['ok'], report['problems'])

    def test_main_must_be_a_stack(self):
        folder = fixtures.make_folder(self.root, script=fixtures.CLEAN_SCRIPT,
                                      listing={'main': 'screenshot.png'})
        self.assertEqual(self.rules(self.scan(folder)), ['listing'])

    def test_a_refused_file_is_not_looked_into(self):
        folder = fixtures.make_folder(self.root, script='on a\n   get shell(x)\nend a')
        with open(os.path.join(folder, 'tool.exe'), 'wb') as f:
            f.write(b'MZ')
        report = self.scan(folder)
        self.assertEqual(self.rules(report), ['files'])
        self.assertEqual(report['stacks'], [])

    def test_folder_names_are_checked(self):
        folder = fixtures.make_folder(self.root, slug='Bad_Name', version='v1', script=fixtures.CLEAN_SCRIPT)
        report = self.scan(folder)
        self.assertEqual(self.rules(report), ['listing'])
        self.assertEqual(len(report['problems']), 2)

    # ---- reading a stack runs none of it

    def test_reading_a_stack_runs_none_of_its_handlers(self):
        marker = os.path.join(self.root, 'ran.txt')
        write = '   put "ran" into url "file:%s"\n' % marker
        script = ''.join('on %s\n%send %s\n' % (name, write, name) for name in (
            'startup', 'preOpenStack', 'openStack', 'preOpenCard', 'openCard', 'libraryStack',
            'loadStack', 'resumeStack', 'newStack', 'idle', 'closeStack', 'shutdown',
            'shutdownRequest', 'closeStackRequest'))
        script += 'getProp script\n%s   pass script\nend script\n' % write
        script += 'getProp externals\n%s   pass externals\nend externals\n' % write
        folder = fixtures.make_folder(self.root, script=script, button=script, substack=script)
        report = self.scan(folder)
        self.assertFalse(os.path.exists(marker), 'the stack ran while it was being read')
        self.assertTrue(report['ok'], report['problems'])
        self.assertEqual(report['uses'], ['files'])

    def test_the_dump_gives_up_its_permissions(self):
        # (the dump script stops with FATAL, which is a ScanError here,
        # if the engine keeps a permission it was told to give up)
        folder = fixtures.make_folder(self.root, script=fixtures.CLEAN_SCRIPT)
        stacks = scan.dump_stack(fixtures.ENGINE, os.path.join(folder, 'Test Stack.oxtstack'))
        self.assertEqual(stacks[0]['name'], 'Test Stack')
        with open(scan.DUMP_SCRIPT, encoding='utf-8') as f:
            text = f.read()
        self.assertLess(text.index('set the securityPermissions to "disk"'),
                        text.index('put the short name of stack tFile'))
        self.assertLess(text.index('set the securityPermissions to empty'), text.index('scanStack the long id'))

    def test_no_network(self):
        if os.name == 'nt' or not shutil.which('unshare') or (os.geteuid() != 0 and not shutil.which('sudo')):
            self.skipTest('needs unshare, and root or sudo')
        folder = fixtures.make_folder(self.root, script=fixtures.CLEAN_SCRIPT)
        report = scan.scan_folder(folder, fixtures.ENGINE, no_network=True)
        self.assertTrue(report['ok'], report['problems'])

    def test_no_network_locks_the_reader_away(self):
        """What a crafted file would have if it ever took the engine
        over: no network, no other program in sight, the user "nobody",
        and no way to become anyone else."""
        if os.name == 'nt' or not shutil.which('unshare') or (os.geteuid() != 0 and not shutil.which('sudo')):
            self.skipTest('needs unshare, and root or sudo')
        done = subprocess.run(
            scan._isolation(True) + ['/bin/sh', '-c', 'id -u; id -g; tail -n +3 /proc/net/dev | cut -d: -f1 | tr "\\n" " "; echo; '
                                     'grep -E "^(NoNewPrivs|CapBnd|CapEff|CapPrm):" /proc/self/status; echo pid $$'],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = done.stdout.split('\n')
        self.assertEqual(lines[0:2], ['65534', '65534'], done.stdout)
        self.assertEqual(lines[2].split(), ['lo'], done.stdout)
        status = dict(line.split(':\t') for line in lines[3:7])
        self.assertEqual(status['NoNewPrivs'], '1', done.stdout)
        for name in ('CapBnd', 'CapEff', 'CapPrm'):
            self.assertEqual(int(status[name], 16), 0, done.stdout)
        self.assertEqual(lines[7], 'pid 1', done.stdout)
        self.assertEqual(scan._isolation(False), [])

    # ---- the command line

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = scan.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_exit_codes(self):
        good = fixtures.make_folder(self.root, script=fixtures.CLEAN_SCRIPT)
        bad = fixtures.make_folder(self.root, slug='bad-stack', script='on a\n   get shell(x)\nend a')
        report_path = os.path.join(self.root, 'report.json')
        code, out, _ = self.run_main(good, '--engine', fixtures.ENGINE, '--json', report_path,
                                     '--markdown', os.path.join(self.root, 'report.md'))
        self.assertEqual(code, 0)
        self.assertIn('can be shared', out)
        with open(report_path) as f:
            saved = json.load(f)
        self.assertTrue(saved['ok'])
        self.assertNotIn('_sources', saved)
        self.assertEqual(self.run_main(bad, '--engine', fixtures.ENGINE)[0], 1)
        # no engine is never a pass
        code, _, err = self.run_main(good, '--engine', os.path.join(self.root, 'no-engine'))
        self.assertEqual(code, 2)
        self.assertIn('could not run', err)


if __name__ == '__main__':
    unittest.main()
