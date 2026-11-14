"""tools/lcscan.py: every rule against a line that must set it off and
lines that must not."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lcscan  # noqa: E402

SUITE = lcscan.load_suite()


def rules(script, defined=None):
    return sorted({f.rule for f in lcscan.scan_script(script, 'test', SUITE, defined)})


# rule -> scripts that must set it off (and nothing that refuses, unless
# the rule itself refuses)
HITS = {
    'process': ['put shell("ls") into x', 'open process "cmd" for read', 'launch "calc.exe"',
                'launch document "a.pdf"', 'kill process "x"', 'open elevated process "x"',
                'if x then put SHELL ( "dir" ) into y', 'read from process "x" until eof',
                'set the shellPath to "/bin/zsh"', 'do "get shell(x)"'],
    'other-language': ['do tScript as "AppleScript"', 'do x as tLanguage', 'do "x" as "vbscript"'],
    'registry': ['get queryRegistry("HKEY_CURRENT_USER\\x")', 'get setRegistry(k, v)'],
    'externals': ['set the externals of this stack to "x.dll"', 'load extension from file tFile',
                  'load extension with data tData'],
    'remote-code': ['go stack url "http://example.org/a.livecode"', 'go url tAddress',
                    'do url "https://example.org/x.txt"', 'set the script of me to url tWhere',
                    'start using stack url "http://example.org/lib"',
                    'send "x" && url tU to me'],
    'suite-not-on-web': ['enInitialize', 'get btAddMagnet(tSession, tLink)', 'oxSetSocksPort 9050'],
    'url': ['put url "https://example.org" into x', 'put url tAddress into x', 'post tData to url tU',
            'load url "http://example.org/a.png"', 'delete url "ftp://example.org/a"',
            'set the fileName of image 1 to "https://example.org/a.png"',
            'get url ("http://" & tHost)'],
    'socket': ['open socket to "example.org:80"', 'accept connections on port 8080 with message "x"',
               'open secure socket to tHost', 'read from socket tSock until return',
               'write tData to socket tSock', 'get hostNameToAddress("example.org")',
               'close socket tSock', 'get the openSockets'],
    'launch-url': ['launch url "https://example.org"', 'revGoURL "https://example.org"'],
    'net-library': ['libURLSetCustomHTTPHeaders tH', 'get tsNetGet(tUrl, tH, tR, tB, tC)',
                    'revMail "a@example.org"'],
    'net-setting': ['set the httpHeaders to tH', 'set the httpProxy to "p:80"'],
    'database': ['put revOpenDatabase("mysql", tHost, tDb, tUser, tPass) into c'],
    'suite-network': ['dcCreatePeer tConfig', 'nxrConnect tRelay'],
    'file': ['open file tPath for read', 'put url ("file:" & tPath) into x',
             'put x into url "binfile:out.bin"', 'delete file tPath', 'create folder tPath',
             'rename file a to b', 'get the files', 'get files(tFolder)', 'get the detailed files',
             'put specialFolderPath("documents") into x', 'set the defaultFolder to tPath',
             'save this stack', 'export snapshot from rect r to file tPath as PNG',
             'write x to file tPath', 'close file tPath', 'delete folder tPath',
             'create alias tA to file tF', 'get tempName()', 'get the folders'],
    'file-dialog': ['answer file "Choose a picture"', 'ask file "Save as"', 'answer folder "Where?"',
                    'answer files "Choose"'],
    'file-library': ['revZipOpenArchive tPath, "read"', 'revCopyFile a, b',
                     'put revOpenDatabase("sqlite", tPath) into c', 'revDeleteFolder tPath'],
    'javascript': ['do "alert(1)" as "JavaScript"', 'do tJs as "javascript"',
                   'do ("a(" & x & ")") as "JavaScript"'],
    'do': ['do tScript', 'do "put" && x', 'do (the cScript of me)'],
    'send': ['send tMessage to me', 'dispatch tName to button 1', 'call tHandler of stack "x"',
             'dispatch function tName to me'],
    'value': ['put value(tExpression) into x', 'put merge(tTemplate) into x'],
    'set-script': ['set the script of button 1 to tScript'],
    'stackfiles': ['set the stackFiles of this stack to tList'],
    'desktop-only': ['revBrowserOpen tWindow, tUrl'],
}

# lines that look like the above to a careless reader, and set nothing off
QUIET = [
    'put "shell(x)" into tText',
    '-- put shell("ls") into x',
    '# open process "x"',
    '// launch "calc"',
    '/* put shell("x")\n   open socket to "a" */ put 1 into x',
    'put 1 into x -- then delete file tPath',
    'put "open file" into field 1',
    'put the short name of me into x',
    'send "mouseUp" to button 1',
    'send "update" && tRow to me in 500 milliseconds',
    'dispatch "refresh" to card 1 with tA, tB',
    'dispatch command "refresh" to me',
    'call "setup" of stack "Lib"',
    'do "put 1 into x"',
    'put urlEncode(tText) into x',
    'put the number of lines of tFiles into x',
    'answer "Delete the file?" with "No" or "Yes"',
    'ask "What is your name?"',
    'put shellfish into x',
    'put tOpen into x',
    'delete line 1 of tList',
    'create button "New"',
    'open printing',
    'close printing',
    'go card 2',
    'go stack "Help"',
    'start using stack "Lib"',
    'insert the script of button "Lib" into back',
    'launchRocket',
    'put myShell(3) into x',
    'set the fileName of image 1 to "picture.png"',
    'put "http://example.org" into field "Link"',
    'if the platform is "HTML5" then put 1 into x else put 2 into x',
    'import snapshot from rect the rect of me',
    'read from stdin until eof',
    'write x to stdout',
    'put the value of scrollbar 1 into x',
    'get sxRandomBytes(32)',
    'b2kStep',
]


class Tokens(unittest.TestCase):
    def lines(self, script):
        return [(n, [t.text for t in tokens]) for n, tokens in lcscan.statements(script)]

    def test_comments_and_strings(self):
        self.assertEqual(self.lines('put "a -- b" into x -- c\n# d\nput 1 // e'),
                         [(1, ['put', 'a -- b', 'into', 'x']), (3, ['put', '1'])])

    def test_block_comment_over_lines(self):
        self.assertEqual(self.lines('put 1 /* a\nb */ into x'), [(1, ['put', '1']), (2, ['into', 'x'])])

    def test_continuation_joins_lines(self):
        self.assertEqual(self.lines('put shell \\\n  ("x") into y'),
                         [(1, ['put', 'shell', '(', 'x', ')', 'into', 'y'])])
        self.assertEqual(self.lines('put 1 \\ -- why\n into x'), [(1, ['put', '1', 'into', 'x'])])

    def test_semicolon_separates(self):
        self.assertEqual(self.lines('put 1 into x; put 2 into y'),
                         [(1, ['put', '1', 'into', 'x']), (1, ['put', '2', 'into', 'y'])])

    def test_case_is_folded_but_strings_are_kept(self):
        self.assertEqual(self.lines('PUT Shell("LS")'), [(1, ['put', 'shell', '(', 'LS', ')'])])

    def test_unclosed_string_ends_with_its_line(self):
        self.assertEqual(self.lines('put "abc\nput shell(x)')[1], (2, ['put', 'shell', '(', 'x', ')']))

    def test_defined_handlers(self):
        script = 'on mouseUp\nend mouseUp\nprivate command enConnect pX\nend enConnect\nfunction Foo\nend Foo'
        self.assertEqual(lcscan.defined_handlers(script), {'mouseup', 'enconnect', 'foo'})


class Rules(unittest.TestCase):
    def test_every_rule_has_a_line_that_sets_it_off(self):
        self.assertEqual(sorted(HITS), sorted(lcscan.RULES),
                         'a rule without a test would pass whatever it did')

    def test_hits(self):
        for rule, scripts in HITS.items():
            for script in scripts:
                with self.subTest(rule=rule, script=script):
                    self.assertIn(rule, rules(script))

    def test_hits_inside_a_handler_and_a_condition(self):
        for rule, scripts in HITS.items():
            script = scripts[0]
            wrapped = 'on mouseUp\n   if tReady then %s\nend mouseUp' % script
            with self.subTest(rule=rule):
                self.assertIn(rule, rules(wrapped))

    def test_quiet_lines_set_nothing_off(self):
        for script in QUIET:
            with self.subTest(script=script):
                self.assertEqual(rules(script), [])

    def test_a_refusing_rule_does_not_hide_behind_else(self):
        self.assertIn('process', rules('if x then put 1 into y else open process "sh"'))

    def test_file_and_internet_urls_are_told_apart(self):
        self.assertEqual(rules('put url ("file:" & p) into x'), ['file'])
        self.assertEqual(rules('put url "https://example.org" into x'), ['url'])
        self.assertEqual(rules('put url tUnknown into x'), ['url'])
        self.assertEqual(rules('put url "file:a.txt" into url "https://example.org/up"'), ['file', 'url'])

    def test_javascript_is_only_the_literal_language(self):
        self.assertEqual(rules('do x as "JavaScript"'), ['javascript'])
        self.assertEqual(rules('do x as ("Java" & "Script")'), ['other-language'])

    def test_literal_script_is_read(self):
        self.assertEqual(rules('do "delete file tPath"'), ['file'])
        self.assertEqual(rules('send "launch tApp" to me'), ['process'])
        self.assertEqual(rules('dispatch "open process x" to me'), ['process'])

    def test_a_stack_may_define_a_name_the_suite_also_has(self):
        self.assertEqual(rules('enInitialize'), ['suite-not-on-web'])
        self.assertEqual(rules('enInitialize', defined={'eninitialize'}), [])

    def test_line_numbers(self):
        found = lcscan.scan_script('on mouseUp\n   put 1 into x\n   put shell("x") \\\n     into y\nend mouseUp',
                                   'here', SUITE)
        self.assertEqual([(f.rule, f.line, f.where) for f in found], [('process', 3, 'here')])

    def test_summarize(self):
        found = lcscan.scan_script('put url tU into x\ndo tS\nput shell(x)\nsave this stack', '', SUITE)
        self.assertEqual(lcscan.summarize(found), (['files', 'internet'], ['process'], ['do']))

    def test_suite_table_has_every_member(self):
        members = {m for m, _ in SUITE.values()}
        self.assertEqual(members, {'enetxt', 'torrentxt', 'onionxt', 'datachannelxt', 'nostrxt-relay'})
        self.assertEqual({d for _, d in SUITE.values()}, {'blocked', 'internet'})


if __name__ == '__main__':
    unittest.main()
