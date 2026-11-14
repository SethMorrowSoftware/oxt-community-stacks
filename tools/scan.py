#!/usr/bin/env python3
"""Checks one shared stack: its listing, its files and its scripts.

    python3 tools/scan.py stacks/<name>/<version> --engine <OXT-Beyond engine>
        [--json report.json] [--markdown report.md] [--no-network]

A shared stack is a folder, stacks/<name>/<version>/, that holds

    listing.json     what the gallery says about it (tools/listing.py)
    the stack        the file listing.json calls "main"
    anything else it needs: pictures, sounds, text, more stacks

The check answers one question: may this be offered to strangers with a
Play button? It looks at three things, in this order, and stops trusting
the folder as soon as one fails:

  1. the listing and the files (names, sizes, kinds: no programs, no
     archives, nothing hidden);
  2. each stack file, read by the OXT-Beyond engine itself with
     tools/scan-dump.livecodescript, which never opens the stack and has
     given up every permission before it looks (see that file). A stack
     with a password, with native externals, or that the engine cannot
     read is refused;
  3. every script, with tools/lcscan.py: what it reaches (the badges), and
     what a shared stack may not do at all.

Exit code 0: the stack can be shared. 1: it is refused; the report says
why in plain words. 2: the check itself could not run (no engine, a
crash): never a pass.

Everything in the folder is somebody else's data. Nothing in it is ever
run, imported or unpacked by this script.
"""
import argparse
import base64
import binascii
import collections
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lcscan  # noqa: E402
import listing as listing_rules  # noqa: E402

DUMP_SCRIPT = os.path.join(HERE, 'scan-dump.livecodescript')

# ---------------------------------------------------------------- limits

MAX_FILES = 200
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_DEPTH = 4
ENGINE_SECONDS = 120
MAX_DUMP_BYTES = 64 * 1024 * 1024

STACK_EXTENSIONS = ('.oxtstack', '.livecode', '.rev', '.livecodescript')
# What a stack may bring with it: things to show, play and read. No
# programs, no libraries, no archives (an archive hides its files from
# this check).
DATA_EXTENSIONS = (
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg', '.webp', '.ico',
    '.wav', '.mp3', '.ogg', '.oga', '.aif', '.aiff', '.au', '.m4a', '.mid', '.midi',
    '.mp4', '.webm', '.mov', '.m4v',
    '.txt', '.md', '.json', '.csv', '.tsv', '.xml', '.html', '.htm', '.css', '.ini',
    '.ttf', '.otf', '.woff', '.woff2',
    '.sqlite', '.sqlite3', '.db',
)
# The first bytes of the files that are programs whatever they are called
PROGRAM_MAGIC = (
    (b'MZ', 'a Windows program or library'),
    (b'\x7fELF', 'a Linux program or library'),
    (b'\xfe\xed\xfa\xce', 'a Mac program or library'),
    (b'\xfe\xed\xfa\xcf', 'a Mac program or library'),
    (b'\xce\xfa\xed\xfe', 'a Mac program or library'),
    (b'\xcf\xfa\xed\xfe', 'a Mac program or library'),
    (b'\xca\xfe\xba\xbe', 'a Mac program or a Java class'),
    (b'PK\x03\x04', 'a zip archive'),
    (b'PK\x05\x06', 'a zip archive'),
    (b'\x1f\x8b', 'a compressed archive'),
    (b'7z\xbc\xaf\x27\x1c', 'a 7-Zip archive'),
    (b'Rar!', 'a RAR archive'),
    (b'\x00asm', 'a WebAssembly program'),
    (b'LCMD', 'a compiled extension'),
    (b'dex\n', 'an Android program'),
)

# What the reader of a refusal is told to do about it
ADVICE = {
    'listing': 'Fix listing.json and share the stack again.',
    'files': 'Take the file out, or save it in one of the kinds a stack may bring.',
    'password': 'Remove the password (in the stack\'s Inspector), save the stack and share it again. '
                'Everyone must be able to read a shared stack\'s scripts.',
    'externals': 'A shared stack cannot load native code. The libraries that come with OXT-Beyond\'s '
                 'web engine can be used without it.',
    'unreadable': 'Open the stack in OXT-Beyond, save it again and share that file.',
    'stackfiles': 'Keep the other stacks in the same folder and name them without a path.',
    'process': 'Shared stacks play in a web browser, where no other program can be run. '
               'Take that part out, or keep this stack for the desktop.',
    'other-language': 'In a web browser the only other language is "JavaScript".',
    'registry': 'There is no registry in a web browser.',
    'remote-code': 'Put the stack or the script in the folder you share, so that it can be checked '
                   'with the rest.',
    'suite-not-on-web': 'The web engine has SodiumXT, CoinXT, Box2Dxt and DataChannelXT, and the '
                        'NostrXT relay library. ENetXT, TorrentXT and OnionXT need the desktop.',
}

Problem = collections.namedtuple('Problem', 'rule text where line code')


class ScanError(Exception):
    """The check could not run. Never a pass."""


# ---------------------------------------------------------------- the files

_NAME_OK = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 ._()\'&,+!-]*$')


def check_files(folder):
    """([{path, size, sha256, kind}], [Problem]) for every file under
    the folder. kind is "listing", "stack" or "data"."""
    files, problems = [], []
    total = 0
    real_root = os.path.realpath(folder)
    for root, dirs, names in os.walk(folder, followlinks=False):
        dirs.sort()
        rel_root = os.path.relpath(root, folder)
        depth = 0 if rel_root == '.' else rel_root.count(os.sep) + 1
        if depth > MAX_DEPTH:
            problems.append(Problem('files', 'Folders are nested too deeply (at most %d).' % MAX_DEPTH,
                                    rel_root.replace(os.sep, '/'), 0, ''))
            dirs[:] = []
            continue
        for d in list(dirs):
            full = os.path.join(root, d)
            if os.path.islink(full) or not _NAME_OK.match(d):
                problems.append(Problem('files', 'A folder has a name that cannot be shared, or is a link.',
                                        os.path.relpath(full, folder).replace(os.sep, '/'), 0, ''))
                dirs.remove(d)
        for name in sorted(names):
            full = os.path.join(root, name)
            rel = os.path.relpath(full, folder).replace(os.sep, '/')
            if os.path.islink(full) or not os.path.isfile(full) \
                    or not os.path.realpath(full).startswith(real_root + os.sep):
                problems.append(Problem('files', 'This is a link or a special file, not a file.', rel, 0, ''))
                continue
            if not _NAME_OK.match(name):
                problems.append(Problem('files', 'The file\'s name has characters that cannot be shared '
                                        '(use letters, digits, spaces and . _ - only, and start with a '
                                        'letter or a digit).', rel, 0, ''))
                continue
            size = os.path.getsize(full)
            total += size
            if len(files) >= MAX_FILES:
                problems.append(Problem('files', 'There are more than %d files.' % MAX_FILES, rel, 0, ''))
                return files, problems
            if size > MAX_FILE_BYTES:
                problems.append(Problem('files', 'The file is bigger than %d MB.'
                                        % (MAX_FILE_BYTES // 1048576), rel, 0, ''))
                continue
            ext = os.path.splitext(name)[1].lower()
            if rel == 'listing.json':
                kind = 'listing'
            elif ext in STACK_EXTENSIONS:
                kind = 'stack'
            elif ext in DATA_EXTENSIONS:
                kind = 'data'
            else:
                problems.append(Problem('files', 'Files of this kind ("%s") cannot come with a shared stack.'
                                        % (ext or 'no extension'), rel, 0, ''))
                continue
            digest = hashlib.sha256()
            with open(full, 'rb') as f:
                head = f.read(16)
                digest.update(head)
                for block in iter(lambda: f.read(1 << 20), b''):
                    digest.update(block)
            what = _program(head)
            if what:
                problems.append(Problem('files', 'The file is %s, whatever its name says.' % what, rel, 0, ''))
                continue
            files.append({'path': rel, 'size': size, 'sha256': digest.hexdigest(), 'kind': kind})
    if total > MAX_TOTAL_BYTES:
        problems.append(Problem('files', 'The files are bigger than %d MB together.'
                                % (MAX_TOTAL_BYTES // 1048576), '', 0, ''))
    return files, problems


def _program(head):
    for magic, what in PROGRAM_MAGIC:
        if head.startswith(magic):
            return what
    return None


# ---------------------------------------------------------------- the engine's dump

def _unb64(text):
    try:
        return base64.b64decode(text.encode('ascii'), validate=True).decode('utf-8')
    except (binascii.Error, UnicodeError, ValueError):
        raise ValueError('a field of the dump is not base64 of UTF-8')


def parse_dump(text):
    """The stacks of a dump: [{role, name, externals, stackFiles,
    password, scriptOnly, objects: [{type, id, name, path, readable,
    script, kind, behavior, fileName}]}]. Raises ValueError for anything that is not a
    whole, well-formed dump: a dump is believed entirely or not at all."""
    lines = text.split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    if not lines or lines[0] != 'OXTSCAN 1':
        raise ValueError('the dump does not start as one')
    if len(lines) < 2 or not lines[-1].startswith('END '):
        raise ValueError('the dump has no end: the engine stopped before it had read the stack')
    stacks = []
    objects = 0
    for line in lines[1:-1]:
        f = line.split('\t')
        if f[0] == 'stack' and len(f) == 7:
            if f[1] not in ('main', 'sub') or f[5] not in ('0', '1') or f[6] not in ('0', '1'):
                raise ValueError('a stack line of the dump is malformed')
            stacks.append({'role': f[1], 'name': _unb64(f[2]), 'externals': _unb64(f[3]),
                           'stackFiles': _unb64(f[4]), 'password': f[5] == '1',
                           'scriptOnly': f[6] == '1', 'objects': []})
        elif f[0] == 'object' and len(f) == 10 and stacks:
            if not re.match(r'^[a-zA-Z]+$', f[1]) or not f[2].isdigit() or f[5] not in ('0', '1'):
                raise ValueError('an object line of the dump is malformed')
            stacks[-1]['objects'].append({
                'type': f[1], 'id': int(f[2]), 'name': _unb64(f[3]), 'path': _unb64(f[4]),
                'readable': f[5] == '1', 'script': _unb64(f[6]), 'kind': _unb64(f[7]),
                'behavior': _unb64(f[8]), 'fileName': _unb64(f[9])})
            # (a script the engine will not give is a password's doing)
            if f[5] == '0':
                stacks[-1]['password'] = True
            objects += 1
        else:
            raise ValueError('the dump has a line that is not part of one')
    if lines[-1] != 'END %d %d' % (len(stacks), objects):
        raise ValueError('the dump\'s end does not match what came before it')
    if not stacks or stacks[0]['role'] != 'main':
        raise ValueError('the dump has no main stack')
    return stacks


# The user "nobody": it owns nothing and may do nothing.
NOBODY = 65534


def _isolation(no_network):
    """The command that starts the engine locked away, where this machine
    can do that (Linux, as root or with sudo): in a network of its own
    with nothing in it, unable to see other programs, as the user
    "nobody", and unable ever to become anyone else (so no sudo). Reading
    a stack runs none of its script, but the reader is a big C++ program
    and the file comes from a stranger: if a crafted file ever took the
    reader over, this is all it would have."""
    if not no_network:
        return []
    unshare, setpriv = shutil.which('unshare'), shutil.which('setpriv')
    if not unshare or not setpriv:
        raise ScanError('--no-network needs the unshare and setpriv programs (Linux)')
    command = []
    if os.geteuid() != 0:
        sudo = shutil.which('sudo')
        if not sudo:
            raise ScanError('--no-network needs sudo when not run as root')
        command = [sudo, '-n']
    return command + [unshare, '--net', '--ipc', '--pid', '--fork', '--kill-child', '--',
                      setpriv, '--reuid=%d' % NOBODY, '--regid=%d' % NOBODY, '--clear-groups',
                      '--no-new-privs', '--inh-caps=-all', '--bounding-set=-all', '--']


def dump_stack(engine, stack_path, no_network=False):
    """parse_dump() of what the engine reads from a stack file. Raises
    ValueError when the engine cannot read it as a stack, ScanError when
    the engine could not be run."""
    if not engine or not os.path.isfile(engine):
        raise ScanError('there is no engine at %r' % (engine,))
    work = os.path.realpath(tempfile.mkdtemp(prefix='oxt-scan-'))
    try:
        os.chmod(work, 0o755)
        # A copy under a plain name: the engine is never given a name
        # that somebody else chose
        ext = os.path.splitext(stack_path)[1].lower()
        copy = os.path.join(work, 'stack' + (ext if ext in STACK_EXTENSIONS else '.oxtstack'))
        shutil.copyfile(stack_path, copy)
        os.chmod(copy, 0o644)
        # The dump script under a name nobody can know beforehand: the
        # engine keeps one stack of a name, so a stack that called itself
        # what the dump script is called would be confused with it
        dump = os.path.join(work, 'dump.livecodescript')
        with open(DUMP_SCRIPT, encoding='utf-8') as f:
            text = f.read()
        first, rest = text.split('\n', 1)
        if first != 'script "oxt_community_scan_dump"':
            raise ScanError('tools/scan-dump.livecodescript does not start as expected')
        with open(dump, 'w', encoding='utf-8', newline='\n') as f:
            f.write('script "oxt_scan_%s"\n%s' % (binascii.hexlify(os.urandom(16)).decode('ascii'), rest))
        os.chmod(dump, 0o644)
        command = _isolation(no_network) + [
            '/usr/bin/env', '-i', 'OXT_SCAN_FILE=' + copy, 'HOME=' + work, 'TMPDIR=' + work,
            'PATH=/usr/bin:/bin', 'LANG=C.UTF-8', os.path.abspath(engine), '-ui', dump]
        try:
            done = subprocess.run(command, cwd=work, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, timeout=ENGINE_SECONDS)
        except subprocess.TimeoutExpired:
            raise ValueError('the engine took more than %d seconds to read the stack' % ENGINE_SECONDS)
        except OSError as e:
            raise ScanError('the engine could not be started: %s' % e)
        if no_network and done.returncode in (125, 126, 127) and not done.stdout:
            # (env's own words for "could not start it": as "nobody" the
            # engine must be in a folder that everyone can read)
            raise ScanError('the engine could not be started as the user "nobody": %s'
                            % done.stderr[:300].decode('utf-8', 'replace').strip())
        if done.returncode == 2 or b'FATAL' in done.stdout[:4096]:
            raise ScanError('the engine could not run the dump: %s'
                            % done.stdout[:300].decode('utf-8', 'replace').strip())
        if len(done.stdout) > MAX_DUMP_BYTES:
            raise ValueError('the stack\'s scripts are too big to check')
        if done.returncode != 0:
            raise ValueError('the engine could not read the file as a stack')
        try:
            text = done.stdout.decode('ascii')
        except UnicodeError:
            raise ValueError('the dump is not plain text')
        return parse_dump(text)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------- one folder

def object_label(obj):
    if obj['type'] == 'stack':
        return 'the stack script'
    name = obj['name']
    if name and name != '%s id %d' % (obj['type'], obj['id']):
        return '%s "%s" (%s)' % (obj['type'], name, obj['path'])
    return '%s id %d (%s)' % (obj['type'], obj['id'], obj['path'])


def _check_stack_files(stack, file_paths, where):
    """The stackFiles of a stack name files of the upload, without a
    path out of it."""
    problems = []
    for line in stack['stackFiles'].split('\n'):
        if not line.strip():
            continue
        path = line.split(',', 1)[1] if ',' in line else ''
        if not path or path.startswith('/') or '\\' in path or ':' in path \
                or '..' in path.split('/') or path not in file_paths:
            problems.append(Problem('stackfiles', 'The stack looks for another stack at "%s", which is '
                                    'not a file in the folder that was shared.' % path, where, 0, ''))
    return problems


def scan_folder(folder, engine, no_network=False, suite=None):
    """The report of one stacks/<name>/<version> folder, a dict (see
    main() for how it is printed). report['ok'] says whether the stack
    can be shared. Raises ScanError when the check could not run."""
    folder = os.path.abspath(folder)
    if suite is None:
        suite = lcscan.load_suite()
    version = os.path.basename(folder)
    slug = os.path.basename(os.path.dirname(folder))
    report = {'format': 1, 'slug': slug, 'version': version, 'ok': False, 'listing': None,
              'files': [], 'stacks': [], 'uses': [], 'problems': [], 'notes': [], 'findings': []}
    problems = []
    sources = []          # (file, stack name, label, script): for the source page

    for text in listing_rules.check_path(slug, version):
        problems.append(Problem('listing', text, '', 0, ''))
    if not os.path.isdir(folder):
        raise ScanError('%s is not a folder' % folder)

    files, file_problems = check_files(folder)
    problems += file_problems
    report['files'] = files
    paths = {f['path'] for f in files}

    listing = None
    listing_path = os.path.join(folder, 'listing.json')
    if 'listing.json' not in paths:
        if not any(p.where == 'listing.json' for p in problems):
            problems.append(Problem('listing', 'There is no listing.json in the folder.', '', 0, ''))
    else:
        listing, texts = listing_rules.read(listing_path, paths)
        problems += [Problem('listing', t, 'listing.json', 0, '') for t in texts]
    report['listing'] = listing

    findings = []
    notes = set()
    defined = set()
    dumps = []
    # The files are only read by the engine when they are files a stack
    # may bring: a refused file is not looked into
    if not file_problems:
        for f in files:
            if f['kind'] != 'stack':
                continue
            try:
                stacks = dump_stack(engine, os.path.join(folder, f['path']), no_network)
            except ValueError as e:
                problems.append(Problem('unreadable', 'The stack could not be read: %s.' % e, f['path'], 0, ''))
                continue
            dumps.append((f['path'], stacks))
            for stack in stacks:
                for obj in stack['objects']:
                    defined |= lcscan.defined_handlers(obj['script'])

    for path, stacks in dumps:
        entry = {'file': path, 'name': stacks[0]['name'],
                 'substacks': [s['name'] for s in stacks[1:]],
                 'objects': sum(len(s['objects']) for s in stacks),
                 'script_lines': 0, 'widgets': []}
        for stack in stacks:
            where = '%s, stack "%s"' % (path, stack['name'])
            if stack['password']:
                problems.append(Problem('password', 'The stack has a password, so its scripts cannot '
                                        'be read.', where, 0, ''))
            if stack['externals'].strip():
                problems.append(Problem('externals', 'The stack names native externals to load: %s.'
                                        % ', '.join(stack['externals'].split('\n')), where, 0, ''))
            problems += _check_stack_files(stack, paths, where)
            for obj in stack['objects']:
                label = '%s: %s' % (where, object_label(obj))
                if obj['type'] == 'widget':
                    if obj['kind'] not in entry['widgets']:
                        entry['widgets'].append(obj['kind'])
                    if obj['kind'] == 'com.livecode.widget.browser':
                        findings.append(lcscan.Finding('url', 'uses:internet', label, 0,
                                                       'a browser widget, which shows web pages'))
                if lcscan._scheme(obj['fileName']) == 'url':
                    findings.append(lcscan.Finding('url', 'uses:internet', label, 0,
                                                   'its file is at an address: ' + obj['fileName'][:120]))
                if not obj['script'].strip():
                    continue
                entry['script_lines'] += obj['script'].count('\n') + 1
                sources.append((path, stack['name'], object_label(obj), obj['script']))
                findings += lcscan.scan_script(obj['script'], label, suite, defined)
        report['stacks'].append(entry)

    if listing and listing.get('main') in paths and not any(
            p for p in problems if p.rule == 'unreadable' and p.where == listing['main']):
        if listing['main'] not in [d[0] for d in dumps] and not file_problems:
            problems.append(Problem('listing', '"main" must name the stack file to open.',
                                    'listing.json', 0, ''))

    uses, refused, note_rules = lcscan.summarize(findings)
    for f in findings:
        if f.level == 'refuse':
            problems.append(Problem(f.rule, 'The stack %s.' % lcscan.RULES[f.rule][1], f.where, f.line, f.text))
    notes |= set(note_rules)
    if 'internet' in uses and notes & {'do', 'value', 'set-script', 'send'}:
        notes.add('could-fetch-script')

    report['uses'] = uses
    report['notes'] = sorted(notes)
    report['problems'] = [p._asdict() for p in problems]
    report['findings'] = [f._asdict() for f in findings]
    report['ok'] = not problems
    report['_sources'] = sources
    return report


# ---------------------------------------------------------------- printing

USES_WORDS = collections.OrderedDict([
    ('internet', 'Uses the internet'),
    ('files', 'Opens or saves files'),
    ('javascript', 'Runs JavaScript in its page'),
])
NOTE_WORDS = dict((rule, text[1]) for rule, text in lcscan.RULES.items() if text[0] == 'note')
NOTE_WORDS['could-fetch-script'] = ('uses the internet and builds script while it runs: it could '
                                    'fetch script that was not checked here')


def md(text):
    """Text from a stack or a listing, made safe to put in Markdown that
    GitHub shows: nothing in it becomes a link, a picture, a mention or
    markup."""
    text = ' '.join(str(text).split())
    text = re.sub(r'([\\`*_{}\[\]()#+!|~-])', r'\\\1', text)
    text = text.replace('@', '@\u200b').replace('&', '&amp;')
    # (an entity, not a backslash: "\<img" still has "<img" in it for
    # anything that reads the comment as HTML)
    text = text.replace('<', '&lt;').replace('>', '&gt;')
    # (GitHub makes a link of a bare address too)
    return text.replace('://', ':\u200b//').replace('www.', 'www\u200b.')


def md_code(text):
    """The same for a line of script, shown as code."""
    text = ' '.join(str(text).split()).replace('`', "'")
    return '`%s`' % text if text else ''


def markdown(report):
    """The report as a person reads it (a pull request's summary).
    Everything that came out of the folder goes through md() or
    md_code()."""
    title = (report['listing'] or {}).get('title') or report['slug']
    out = ['## %s, version %s' % (md(title), md(report['version'])), '']
    if report['ok']:
        out.append('**This stack can be shared.**')
    else:
        out.append('**This stack cannot be shared yet.** What stands in the way:')
        out.append('')
        seen = set()
        for p in report['problems']:
            line = '- ' + md(p['text'])
            if p['where']:
                line += ' In %s' % md(p['where']) + (', line %d' % p['line'] if p['line'] else '') + '.'
            if p['code']:
                line += '\n  ' + md_code(p['code'])
            out.append(line)
            if p['rule'] in ADVICE and p['rule'] not in seen:
                seen.add(p['rule'])
                out.append('  ' + ADVICE[p['rule']])
    out.append('')
    if report['uses']:
        out.append('What it uses: ' + ', '.join(USES_WORDS[u] for u in report['uses']) + '.')
    elif report['ok']:
        out.append('It uses nothing outside itself: no internet, no files.')
    if report['notes']:
        out += ['', 'For the reviewer:']
        out += ['- It ' + NOTE_WORDS[n] + '.' for n in report['notes']]
    uses = [f for f in report['findings'] if f['level'] != 'refuse']
    if uses:
        out += ['', '<details><summary>The lines these come from (%d)</summary>' % len(uses), '']
        for f in uses[:200]:
            out.append('- %s: %s%s  %s' % (lcscan.RULES[f['rule']][1], md(f['where']),
                                          ', line %d' % f['line'] if f['line'] else '',
                                          md_code(f['text'])))
        if len(uses) > 200:
            out.append('- ... and %d more' % (len(uses) - 200))
        out += ['', '</details>']
    out.append('')
    for s in report['stacks']:
        out.append('- %s: stack "%s", %d objects, %d lines of script%s' % (
            md_code(s['file']), md(s['name']), s['objects'], s['script_lines'],
            ', substacks: ' + md(', '.join(s['substacks'])) if s['substacks'] else ''))
    return '\n'.join(out) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Check one shared stack.')
    parser.add_argument('folder', help='stacks/<name>/<version>')
    parser.add_argument('--engine', default=os.environ.get('OXT_ENGINE'),
                        help='the OXT-Beyond engine (LiveCode-Community); or set OXT_ENGINE')
    parser.add_argument('--json', help='write the whole report here')
    parser.add_argument('--markdown', help='write the report for people here')
    parser.add_argument('--no-network', action='store_true',
                        help='run the engine with no network (Linux; needs root or sudo)')
    args = parser.parse_args(argv)
    try:
        report = scan_folder(args.folder, args.engine, args.no_network)
    except ScanError as e:
        print('The check could not run: %s' % e, file=sys.stderr)
        return 2
    report.pop('_sources')
    text = markdown(report)
    if args.json:
        with open(args.json, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(report, f, indent=1, sort_keys=True)
            f.write('\n')
    if args.markdown:
        with open(args.markdown, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
    print(text)
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
