"""The whole thing in a real browser: a built gallery plays its stacks,
and a hostile stack cannot leave its box (tools/tests/browser-check.js).

Needs the engine (OXT_ENGINE), the real Stack Player (OXT_PLAYER, the
folder tools/fetch.py player prints) and Node with Playwright. Skipped
without them, or failed where OXT_REQUIRE_BROWSER=1 says they must be
there.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import build_site  # noqa: E402
import fixtures  # noqa: E402

CHECK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'browser-check.js')
PLAYER = os.environ.get('OXT_PLAYER', '')

# Each try is "name: what it does"; a try that does not throw is a way
# out. One line of JavaScript, as the stack runs it when it opens.
HOSTILE_JS = (
    "(function(){var r=[];function t(n,f){try{f();r.push('BREACH '+n)}catch(e){r.push('BOXED '+n)}}"
    "t('read the page around it',function(){return parent.document.title});"
    "t('read the site storage through the page',function(){return parent.localStorage.getItem('canary')});"
    "t('use storage as the site',function(){localStorage.setItem('x','1')});"
    "t('use session storage as the site',function(){sessionStorage.setItem('x','1')});"
    "t('read the site cookies',function(){if(document.cookie.indexOf('canary')<0)throw new Error('none')});"
    "t('set a site cookie',function(){document.cookie='evil=1; path=/';if(document.cookie.indexOf('evil')<0)throw new Error('none')});"
    "t('open the site database',function(){indexedDB.open('x')});"
    "t('send the page somewhere else',function(){top.location.href='about:blank'});"
    "t('reach the page that opened it',function(){return top.document.body.innerHTML});"
    "console.log('HOSTILE '+r.join('|'))})()")


class Browser(unittest.TestCase):
    def test_stacks_play_boxed_in_and_a_hostile_one_stays_there(self):
        missing = []
        if not (fixtures.ENGINE and os.path.isfile(fixtures.ENGINE)):
            missing.append('OXT_ENGINE')
        if not os.path.isfile(os.path.join(PLAYER, 'play', 'index.html')):
            missing.append('OXT_PLAYER')
        node = shutil.which('node')
        if not node:
            missing.append('node')
        if missing:
            if os.environ.get('OXT_REQUIRE_BROWSER') == '1':
                self.fail('missing for the browser check: ' + ', '.join(missing))
            self.skipTest('no ' + ', '.join(missing))
        self.assertNotIn('"', HOSTILE_JS)
        with tempfile.TemporaryDirectory() as root:
            fixtures.make_folder(root, slug='friendly', title='Friendly', script=fixtures.CLEAN_SCRIPT)
            fixtures.make_folder(
                root, slug='hostile', title='Hostile',
                script='on openStack\n   do "%s" as "JavaScript"\nend openStack\n' % HOSTILE_JS)
            out = os.path.join(root, 'site')
            index, refused = build_site.build(os.path.join(root, 'stacks'), fixtures.ENGINE, PLAYER, out,
                                              log=lambda line: None, env={})
            self.assertEqual(refused, [])
            self.assertEqual([s['uses'] for s in index['stacks']], [[], ['javascript']])
            done = subprocess.run([node, CHECK, out, '--hostile', 'hostile'], capture_output=True, text=True,
                                  timeout=600)
            print(done.stdout)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertIn('all checks passed', done.stdout)
            self.assertNotIn('BREACH', done.stdout)
            self.assertIn('BOXED send the page somewhere else', done.stdout)


if __name__ == '__main__':
    unittest.main()
