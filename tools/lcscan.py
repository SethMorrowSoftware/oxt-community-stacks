#!/usr/bin/env python3
"""Reads xTalk script and says what it can reach.

This is the part of the scanner that looks at script text. It answers
with *findings*, each one a rule that matched a line of a script:

    Finding(rule, level, where, line, text)

`level` is what the rule means for a shared stack:

    "uses:internet"    the stack talks to other machines
    "uses:files"       it reads or writes files
    "uses:javascript"  it runs JavaScript in the page it plays in
    "refuse"           it cannot be shared (see RULES for each reason)
    "note"             something for the person who reviews it to look at

The "uses" levels become the badges on the stack's page. None of this is
proof of what a script will do: xTalk can build script at run time (do,
send, value), and a stack that wants to hide something can. That is why
shared stacks play inside a web browser, which is the wall that holds;
this file is for honest labels and for pointing a reviewer at the lines
worth reading. The "note" findings mark where the labels may be
incomplete.

Only the Python standard library is used.
"""
import collections
import json
import os
import re

Finding = collections.namedtuple('Finding', 'rule level where line text')

# rule -> (level, what to tell people). The text is shown to authors and
# reviewers, so it is in plain words.
RULES = collections.OrderedDict([
    # ---- refused
    ('process', ('refuse', 'runs other programs on the computer (shell, open process, launch)')),
    ('other-language', ('refuse', 'runs AppleScript or another scripting language of the computer')),
    ('registry', ('refuse', 'reads or changes the Windows registry')),
    ('externals', ('refuse', 'loads native code (an external or an extension of its own)')),
    ('remote-code', ('refuse', 'opens a stack or runs script fetched from an address')),
    ('suite-not-on-web', ('refuse', 'uses an xTalk Suite library that is not part of the web engine')),
    # ---- badges
    ('url', ('uses:internet', 'gets or sends data at an address (url)')),
    ('socket', ('uses:internet', 'opens network connections')),
    ('launch-url', ('uses:internet', 'opens web pages (launch url)')),
    ('net-library', ('uses:internet', 'uses a networking library')),
    ('net-setting', ('uses:internet', 'changes how the engine reaches the network')),
    ('database', ('uses:internet', 'connects to a database, which may be on another machine')),
    ('suite-network', ('uses:internet', 'uses an xTalk Suite networking library')),
    ('file', ('uses:files', 'reads or writes files')),
    ('file-dialog', ('uses:files', 'asks you to choose a file or a folder')),
    ('file-library', ('uses:files', 'uses a library that reads or writes files')),
    ('javascript', ('uses:javascript', 'runs JavaScript in the page it plays in')),
    # ---- for the reviewer
    ('do', ('note', 'runs script that it builds while it runs (do)')),
    ('send', ('note', 'sends a message whose name it works out while it runs')),
    ('value', ('note', 'evaluates an expression it builds while it runs (value, merge)')),
    ('set-script', ('note', 'changes the script of an object while it runs')),
    ('stackfiles', ('note', 'changes where the engine looks for other stacks')),
    ('desktop-only', ('note', 'uses something that only exists on the desktop')),
])

# ---------------------------------------------------------------- tokens

Token = collections.namedtuple('Token', 'kind text raw')   # kind: word, string, number, op

_WORD = re.compile(r'[A-Za-z_$][A-Za-z0-9_.]*')
_NUMBER = re.compile(r'\d+(?:\.\d+)?')


def statements(script):
    """Yields (line number, [Token, ...]) for every statement of a script.

    Comments are dropped (--, #, // and /* */), a line that ends in a
    backslash goes on with the next one, and a semicolon or the words
    "then" and "else" start another statement on the same line. Words
    are lower-cased (xTalk does not tell case apart); strings keep their
    text, without the quotes.
    """
    tokens = []
    start = None
    in_block = False
    for number, line in enumerate(script.replace('\r\n', '\n').replace('\r', '\n').split('\n'), 1):
        i, n = 0, len(line)
        joined = False
        while i < n:
            c = line[i]
            if in_block:
                end = line.find('*/', i)
                if end < 0:
                    i = n
                else:
                    in_block = False
                    i = end + 2
                continue
            if c in ' \t':
                i += 1
            elif c == '"':
                end = line.find('"', i + 1)
                if end < 0:
                    end = n
                if start is None:
                    start = number
                tokens.append(Token('string', line[i + 1:end], line[i:end + 1]))
                i = end + 1
            elif line.startswith('--', i) or c == '#' or line.startswith('//', i):
                break
            elif line.startswith('/*', i):
                in_block = True
                i += 2
            elif c == '\\' and not line[i + 1:].strip(' \t'):
                joined = True
                break
            elif c == '\\':
                # a backslash that is followed by a comment also joins
                rest = line[i + 1:].lstrip(' \t')
                if rest.startswith('--') or rest.startswith('#') or rest.startswith('//'):
                    joined = True
                    break
                i += 1
            elif c == ';':
                if tokens:
                    yield start, tokens
                tokens, start = [], None
                i += 1
            else:
                m = _WORD.match(line, i)
                if m:
                    kind = 'word'
                else:
                    m = _NUMBER.match(line, i)
                    kind = 'number'
                if m:
                    if start is None:
                        start = number
                    tokens.append(Token(kind, m.group(0).lower(), m.group(0)))
                    i = m.end()
                else:
                    if start is None:
                        start = number
                    tokens.append(Token('op', c, c))
                    i += 1
        if joined:
            continue
        if tokens:
            yield start, tokens
        tokens, start = [], None
    if tokens:
        yield start, tokens


def _split_clauses(tokens):
    """A statement's clauses: "if x then A else B" is three, and each can
    start a command."""
    clause = []
    for t in tokens:
        if t.kind == 'word' and t.text in ('then', 'else'):
            if clause:
                yield clause
            clause = []
        else:
            clause.append(t)
    if clause:
        yield clause


# ---------------------------------------------------------------- handlers a script defines

_HANDLER_START = ('on', 'command', 'function', 'getprop', 'setprop', 'before', 'after')


def defined_handlers(script):
    """The names of the handlers a script defines, lower-cased."""
    names = set()
    for _, tokens in statements(script):
        words = [t for t in tokens]
        if words and words[0].kind == 'word' and words[0].text == 'private':
            words = words[1:]
        if len(words) >= 2 and words[0].kind == 'word' and words[0].text in _HANDLER_START \
                and words[1].kind == 'word':
            names.add(words[1].text)
    return names


# ---------------------------------------------------------------- the rules

_FILE_SCHEMES = ('file:', 'binfile:', 'resfile:')
_NET_SCHEMES = ('http:', 'https:', 'ftp:', 'ftps:', 'sftp:', 'ws:', 'wss:', 'mailto:', 'smtp:')

# functions, by name, wherever they are called
_FUNCTIONS = {
    'shell': 'process',
    'queryregistry': 'registry', 'setregistry': 'registry', 'deleteregistry': 'registry',
    'listregistry': 'registry',
    'files': 'file', 'folders': 'file', 'directories': 'file',
    'specialfolderpath': 'file', 'tempname': 'file',
    'hostnametoaddress': 'socket', 'hostaddresstoname': 'socket', 'hostaddress': 'socket',
    'peeraddress': 'socket', 'dnsservers': 'socket', 'opensockets': 'socket',
    'urlstatus': 'url', 'cachedurls': 'url',
    'value': 'value', 'merge': 'value',
}
# "the <name>" properties and functions
_THE = {
    'files': 'file', 'folders': 'file', 'directories': 'file',
    'defaultfolder': 'file', 'directory': 'file', 'tempname': 'file',
    'shellpath': 'process', 'shellcommand': 'process', 'hideconsolewindows': 'process',
    'httpproxy': 'net-setting', 'httpheaders': 'net-setting',
    'sslcertificates': 'net-setting', 'opensockets': 'socket', 'dnsservers': 'socket',
    'hostaddress': 'socket',
}
# library handlers, by the start of their name
_PREFIXES = (
    ('revzip', 'file-library'),
    ('revcopyfile', 'file-library'), ('revcopyfolder', 'file-library'),
    ('revdeletefolder', 'file-library'), ('revmovefolder', 'file-library'),
    ('revopendatabase', 'database'), ('revdb_connect', 'database'), ('revdatabase', 'database'),
    ('liburl', 'net-library'), ('tsnet', 'net-library'), ('revmail', 'net-library'),
    ('revgourl', 'launch-url'), ('revxmlrpc', 'net-library'),
    ('revbrowser', 'desktop-only'),
)
# the commands that open a stack or run script: with a url in the same
# statement they fetch code from an address
# what "read from", "write to" and "close" name
_CHANNELS = {'file': 'file', 'process': 'process', 'driver': 'process', 'socket': 'socket'}
_RUNS = ('go', 'modal', 'modeless', 'palette', 'toplevel', 'sheet', 'drawer', 'popup',
         'do', 'send', 'dispatch', 'call', 'insert', 'start')


def _strings(tokens):
    return [t.text for t in tokens if t.kind == 'string']


def _has(tokens, *names):
    return any(t.kind == 'word' and t.text in names for t in tokens)


def _index(tokens, name, start=0):
    for i in range(start, len(tokens)):
        if tokens[i].kind == 'word' and tokens[i].text == name:
            return i
    return -1


def _scheme(text):
    low = text.strip().lower()
    for s in _FILE_SCHEMES:
        if low.startswith(s):
            return 'file'
    for s in _NET_SCHEMES:
        if low.startswith(s):
            return 'url'
    return None


def _url_rules(tokens):
    """What a statement with the word "url" in it reaches: files when
    every address in it is a file: one, the internet otherwise (also
    when the address is worked out at run time and cannot be read here).
    """
    found = {_scheme(s) for s in _strings(tokens)} - {None}
    if found == {'file'}:
        return ['file']
    if found == {'file', 'url'}:
        return ['file', 'url']
    return ['url']


def scan_script(script, where='', suite=None, defined=None, _depth=0):
    """The findings of one script. `suite` is load_suite()'s index of the
    xTalk Suite's handlers; `defined` the handler names the whole upload defines (a
    stack that carries its own copy of a pure-script library is calling
    its own handlers)."""
    out = []
    suite_names = suite or {}
    defined = defined or set()

    def add(rule, line, tokens):
        text = ' '.join(t.raw for t in tokens)
        if len(text) > 200:
            text = text[:197] + '...'
        out.append(Finding(rule, RULES[rule][0], where, line, text))

    for line, tokens in statements(script):
        seen = set()

        def hit(rule, line=line, tokens=tokens):
            if rule and rule not in seen:
                seen.add(rule)
                add(rule, line, tokens)

        # ---- anywhere in the statement
        for i, t in enumerate(tokens):
            if t.kind != 'word':
                continue
            nxt = tokens[i + 1] if i + 1 < len(tokens) else None
            prev = tokens[i - 1] if i else None
            if nxt is not None and nxt.kind == 'op' and nxt.text == '(' and t.text in _FUNCTIONS:
                hit(_FUNCTIONS[t.text])
            if prev is not None and prev.kind == 'word' and prev.text in ('the', 'detailed', 'long') \
                    and t.text in _THE:
                hit(_THE[t.text])
            if t.text == 'url':
                for rule in _url_rules(tokens):
                    hit(rule)
            for prefix, rule in _PREFIXES:
                if t.text.startswith(prefix):
                    if rule == 'database' and any('sqlite' in s.lower() for s in _strings(tokens)):
                        rule = 'file-library'
                    hit(rule)
                    break
            member = suite_names.get(t.text)
            if member and t.text not in defined:
                hit('suite-not-on-web' if member[1] == 'blocked' else 'suite-network')

        # ---- commands, at the start of each clause
        for clause in _split_clauses(tokens):
            if clause[0].kind != 'word':
                continue
            cmd = clause[0].text
            rest = clause[1:]
            first = rest[0].text if rest and rest[0].kind == 'word' else ''
            if cmd == 'open':
                if first in ('file',):
                    hit('file')
                elif first in ('process', 'elevated', 'driver'):
                    hit('process')
                elif first in ('socket', 'secure', 'datagram'):
                    hit('socket')
            elif cmd == 'launch':
                if first == 'url':
                    hit('launch-url')
                else:
                    hit('process')
            elif cmd == 'kill':
                hit('process')
            elif cmd == 'accept':
                hit('socket')
            elif cmd in ('read', 'write'):
                for i, t in enumerate(rest[:-1]):
                    if t.kind == 'word' and t.text in ('from', 'to') and rest[i + 1].kind == 'word':
                        hit(_CHANNELS.get(rest[i + 1].text))
            elif cmd == 'close':
                hit(_CHANNELS.get(first))
            elif cmd == 'delete':
                if first in ('file', 'folder', 'directory'):
                    hit('file')
            elif cmd == 'create':
                if first in ('folder', 'directory', 'alias'):
                    hit('file')
            elif cmd == 'rename':
                hit('file')
            elif cmd in ('answer', 'ask'):
                if first in ('file', 'files', 'folder', 'directory'):
                    hit('file-dialog')
            elif cmd == 'save':
                hit('file')
            elif cmd in ('export', 'import'):
                if _has(rest, 'file'):
                    hit('file')
            elif cmd == 'load':
                if first == 'extension':
                    hit('externals')
            elif cmd == 'post':
                hit('url')
            elif cmd == 'do':
                at = _last_as(rest)
                if at >= 0:
                    language = rest[at + 1] if at + 1 < len(rest) else None
                    if language is not None and language.kind == 'string' \
                            and language.text.strip().lower() == 'javascript':
                        hit('javascript')
                    else:
                        hit('other-language')
                else:
                    # (one string and nothing else is script that can
                    # be read here, and is: do "delete file x")
                    if len(rest) == 1 and rest[0].kind == 'string':
                        if _depth < 3:
                            out.extend(f._replace(line=line) for f in
                                       scan_script(rest[0].text, where, suite, defined, _depth + 1))
                    else:
                        hit('do')
            elif cmd in ('send', 'call', 'dispatch'):
                args = rest
                if cmd == 'dispatch' and first in ('command', 'function'):
                    args = rest[1:]
                # send "showRow" && tRow to me: the message is named in
                # the script, whatever is added to it; read the string as
                # the statement it is
                if args and args[0].kind == 'string':
                    if _depth < 3:
                        out.extend(f._replace(line=line) for f in
                                   scan_script(args[0].text, where, suite, defined, _depth + 1))
                else:
                    hit('send')
            elif cmd == 'set':
                if rest and rest[0].kind == 'word' and rest[0].text == 'the':
                    prop = rest[1].text if len(rest) > 1 and rest[1].kind == 'word' else ''
                    if prop == 'script':
                        hit('set-script')
                    elif prop in ('externals', 'externalpackages'):
                        hit('externals')
                    elif prop == 'stackfiles':
                        hit('stackfiles')
                    elif prop == 'filename' and 'url' in {_scheme(x) for x in _strings(rest)}:
                        hit('url')
            if cmd in _RUNS or (cmd == 'set' and len(rest) > 1 and rest[1].kind == 'word'
                                and rest[1].text == 'script'):
                if _has(rest, 'url') and cmd != 'launch':
                    # (go url, do url, set the script to url ...; "start
                    # using" and "insert" only with a url in them)
                    hit('remote-code')
    return out


def _last_as(tokens):
    """Where the "as" of "do <script> as <language>" is: the last "as"
    that is not inside brackets."""
    depth = 0
    at = -1
    for i, t in enumerate(tokens):
        if t.kind == 'op' and t.text == '(':
            depth += 1
        elif t.kind == 'op' and t.text == ')':
            depth -= 1
        elif depth == 0 and t.kind == 'word' and t.text == 'as':
            at = i
    return at


def load_suite(path=None):
    """suite-handlers.json as handler name (lower case) -> (member,
    "blocked" | "internet")"""
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'suite-handlers.json')
    with open(path, encoding='utf-8') as f:
        members = json.load(f)['members']
    index = {}
    for member, entry in members.items():
        for name in entry['handlers']:
            index[name.lower()] = (member, entry['does'])
    return index


def summarize(findings):
    """(uses, refused, notes): the badges, sorted; the rules that refuse
    the stack; the reviewer's rules. Each as a sorted list of names."""
    uses, refused, notes = set(), set(), set()
    for f in findings:
        if f.level.startswith('uses:'):
            uses.add(f.level[5:])
        elif f.level == 'refuse':
            refused.add(f.rule)
        else:
            notes.add(f.rule)
    return sorted(uses), sorted(refused), sorted(notes)
