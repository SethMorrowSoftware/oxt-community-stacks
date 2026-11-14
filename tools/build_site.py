#!/usr/bin/env python3
"""Builds the gallery: the web site that lists the shared stacks and plays
them.

    python3 tools/build_site.py --engine <engine> --player <StackPlayer folder>
        --out _site [--stacks stacks] [--no-network] [--strict]

Every stack is checked again here, with tools/scan.py, whatever checked
it before: the site only ever holds what this run of the scanner passed.
A stack the scanner refuses is left out and named in a warning (--strict
makes that an error instead).

What it writes:

    index.html                      the gallery
    s/<name>/index.html             a stack's own page
    s/<name>/play.html              the stack, playing
    s/<name>/<version>/<name>-<version>.zip    the stack and its files
    s/<name>/<version>/source.html  every script of it, to read
    s/<name>/<version>/screenshot.* its picture
    safety.html, share.html, 404.html
    index.json                      the same list, for the IDE's gallery
    index.sig                       index.json's signature, when the
                                    signing key is there (tools/sign.py)
    player/                         OXT-Beyond's Stack Player

How a stack is kept in its box. The stack plays in OXT-Beyond's Stack
Player, in a frame that the page marks sandbox="allow-scripts ..."
without allow-same-origin. The browser then treats the frame as a site of
its own that nobody else has ever visited: the stack's script, and any
JavaScript it runs, cannot read this site's storage or cookies, cannot
see another stack's saved data, cannot move the page it is on somewhere
else, and has no disk, no programs and no native code at all. The
player's own page is changed in one way (GUARD below): opened outside
such a frame it goes back to the gallery instead of playing, so there is
no address at which a stack runs as this site.

Nothing a stack brings is ever served as a page of this site: its files
go into one .zip, and the pictures are served under names made here.
Every word that came from a listing or a script is escaped.
"""
import argparse
import html
import io
import json
import os
import re
import shutil
import sys
import urllib.parse
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import listing as listing_rules  # noqa: E402
import scan  # noqa: E402
import sign  # noqa: E402

SITE_ASSETS = os.path.join(ROOT, 'site')
# Where this repository lives. GitHub's workflows say (GITHUB_REPOSITORY),
# so the pages keep pointing at it when it moves to another owner.
_REPOSITORY = os.environ.get('GITHUB_REPOSITORY', '')
if not re.match(r'^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+$', _REPOSITORY):
    _REPOSITORY = 'SethMorrowSoftware/oxt-community-stacks'
REPOSITORY_URL = 'https://github.com/' + _REPOSITORY
FORUM_URL = 'https://openxtalk.org/forum/'
OXT_URL = 'https://github.com/SethMorrowSoftware/OpenXTalk-Beyond'

# What the frame around a playing stack may do. Never allow-same-origin
# (see the top of this file), never allow-top-navigation.
SANDBOX = 'allow-scripts allow-downloads allow-popups allow-popups-to-escape-sandbox allow-pointer-lock'

# Put at the top of the player's own page: only ever play in a frame
# that the browser has boxed in (there the page's origin is "null").
GUARD = ('<script data-cfasync="false">if(self.origin!=="null"||self===top)'
         '{location.replace("../../")}</script>')

IMAGE_MAGIC = {
    '.png': (b'\x89PNG\r\n\x1a\n',),
    '.jpg': (b'\xff\xd8\xff',), '.jpeg': (b'\xff\xd8\xff',),
    '.gif': (b'GIF87a', b'GIF89a'),
    '.webp': (b'RIFF',),
}

BADGES = [
    # key, words, what it means in a sentence
    ('internet', 'Uses the internet', 'It gets or sends information over the internet.'),
    ('files', 'Opens or saves files', 'It keeps things in files. In your browser these stay inside the '
     'page and are gone when you close it.'),
    ('javascript', 'Runs JavaScript', 'It runs JavaScript in its own boxed-in page, for example to make sound.'),
]


class BuildError(Exception):
    pass


def esc(text):
    return html.escape(str(text), quote=True)


def url(path):
    return urllib.parse.quote(path, safe='/')


# ---------------------------------------------------------------- collecting

def find_versions(stacks_dir):
    """[(slug, version, folder)] of every stacks/<slug>/<version>, names
    as they are on disk (the scanner judges them)."""
    found = []
    if not os.path.isdir(stacks_dir):
        return found
    for slug in sorted(os.listdir(stacks_dir)):
        folder = os.path.join(stacks_dir, slug)
        if not os.path.isdir(folder) or os.path.islink(folder):
            continue
        for version in sorted(os.listdir(folder)):
            sub = os.path.join(folder, version)
            if os.path.isdir(sub) and not os.path.islink(sub):
                found.append((slug, version, sub))
    return found


def make_zip(folder, files):
    """The bytes of a .zip of a stack's files (not its listing), the same
    bytes for the same files every time."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in sorted(files, key=lambda f: f['path']):
            if f['kind'] == 'listing':
                continue
            info = zipfile.ZipInfo(f['path'], date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(os.path.join(folder, *f['path'].split('/')), 'rb') as src:
                z.writestr(info, src.read())
    return buffer.getvalue()


def collect(stacks_dir, engine, no_network=False, log=print):
    """(stacks, refused): stacks is {slug: [version records, newest
    first]}, each record the scanner's report plus 'folder'; refused is
    [(slug, version, report)]."""
    stacks, refused = {}, []
    for slug, version, folder in find_versions(stacks_dir):
        report = scan.scan_folder(folder, engine, no_network)
        if not report['ok']:
            refused.append((slug, version, report))
            log('::warning::%s %s is left out: %s' % (slug, version, report['problems'][0]['text']))
            continue
        report['folder'] = folder
        stacks.setdefault(slug, []).append(report)
    for versions in stacks.values():
        versions.sort(key=lambda r: listing_rules.version_key(r['version']), reverse=True)
    return stacks, refused


# ---------------------------------------------------------------- pages

def page(title, body, root='', description=''):
    """One whole HTML page. `root` is the way from the page to the top
    of the site ('' or '../../')."""
    return '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>%(title)s</title>
%(description)s<link rel="stylesheet" href="%(root)sassets/site.css">
<link rel="icon" type="image/svg+xml" href="%(root)sassets/mark.svg">
</head>
<body>
<header class="top">
  <a class="brand" href="%(root)sindex.html"><img src="%(root)sassets/mark.svg" alt="" width="36" height="36"><span>OXT Community Stacks</span></a>
  <nav>
    <a href="%(root)sindex.html">All stacks</a>
    <a href="%(root)sshare.html">Share a stack</a>
    <a href="%(root)ssafety.html">Is it safe?</a>
  </nav>
</header>
<main>
%(body)s
</main>
<footer>
  <p>Stacks made with <a href="%(oxt)s">OXT-Beyond</a>, shared by the people who made them. Each stack belongs to its author, under the licence on its page.</p>
</footer>
</body>
</html>
''' % {'title': esc(title), 'body': body, 'root': root, 'oxt': OXT_URL,
       'description': '<meta name="description" content="%s">\n' % esc(description) if description else ''}


def badges_html(uses):
    if not uses:
        return '<ul class="badges"><li class="badge quiet">Keeps to itself</li></ul>'
    return '<ul class="badges">%s</ul>' % ''.join(
        '<li class="badge">%s</li>' % esc(words) for key, words, _ in BADGES if key in uses)


def screenshot_html(record, root, cls='shot'):
    if record.get('screenshot_url'):
        return '<img class="%s" src="%s%s" alt="" loading="lazy">' % (cls, root, url(record['screenshot_url']))
    return '<div class="%s none" aria-hidden="true"></div>' % cls


def gallery_page(entries):
    if not entries:
        body = '''<section class="hero"><h1>Stacks to play, made by people like you</h1>
<p>Nothing has been shared yet. <a href="share.html">Be the first to share a stack.</a></p></section>'''
        return page('OXT Community Stacks', body)
    cards = []
    for e in entries:
        cards.append('''<li class="card" data-find="%(find)s">
  <a class="shotlink" href="s/%(slug)s/index.html" tabindex="-1" aria-hidden="true">%(shot)s</a>
  <h2><a href="s/%(slug)s/index.html">%(title)s</a></h2>
  <p class="by">by %(author)s</p>
  <p class="what">%(description)s</p>
  %(badges)s
  <a class="play" href="s/%(slug)s/play.html">Play<span class="sr"> %(title)s</span></a>
</li>''' % {'slug': e['slug'], 'title': esc(e['title']), 'author': esc(e['author']),
            'description': esc(first_sentence(e['description'])), 'badges': badges_html(e['uses']),
            'shot': screenshot_html(e, ''),
            'find': esc(' '.join([e['title'], e['author'], e['description']] + e['tags']).lower())})
    body = '''<section class="hero">
  <h1>Stacks to play, made by people like you</h1>
  <p>Press <b>Play</b> and a stack opens right here in your browser. There is nothing to install, and a stack cannot reach your files or your computer. <a href="safety.html">How that works.</a></p>
  <label class="find"><span>Find a stack</span><input id="find" type="search" autocomplete="off" placeholder="a name, a word, an author"></label>
</section>
<ul class="cards" id="cards">
%s
</ul>
<p id="none" hidden>No stack matches that. Try another word.</p>
<script>
(function () {
  var box = document.getElementById('find'), none = document.getElementById('none');
  var cards = [].slice.call(document.querySelectorAll('#cards .card'));
  box.addEventListener('input', function () {
    var words = box.value.toLowerCase().split(/\\s+/).filter(Boolean), shown = 0;
    cards.forEach(function (c) {
      var text = c.getAttribute('data-find');
      var on = words.every(function (w) { return text.indexOf(w) >= 0; });
      c.hidden = !on;
      if (on) shown++;
    });
    none.hidden = shown > 0;
  });
})();
</script>''' % '\n'.join(cards)
    return page('OXT Community Stacks', body,
                description='Stacks made with OXT-Beyond, to play in your browser.')


def first_sentence(text, limit=160):
    text = ' '.join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(' ', 1)[0]
    return cut.rstrip('.,;:') + '...'


def stack_page(e):
    root = '../../'
    meanings = ''.join('<li><b>%s.</b> %s</li>' % (esc(words), esc(meaning))
                       for key, words, meaning in BADGES if key in e['uses'])
    if not meanings:
        meanings = '<li><b>Keeps to itself.</b> It uses no internet and no files.</li>'
    older = ''
    if len(e['versions']) > 1:
        older = '<h2>Earlier versions</h2><ul class="plain">%s</ul>' % ''.join(
            '<li>Version %s: <a href="%s%s" download>download</a>, <a href="%s%s">scripts</a></li>'
            % (esc(v['version']), root, url(v['download']), root, url(v['source']))
            for v in e['versions'][1:])
    paragraphs = ''.join('<p>%s</p>' % esc(p) for p in e['description'].split('\n') if p.strip())
    report = '%s/issues/new?title=%s' % (REPOSITORY_URL, urllib.parse.quote('Report: ' + e['slug']))
    body = '''<article class="stack">
  <div class="lead">
    %(shot)s
    <div>
      <h1>%(title)s</h1>
      <p class="by">by %(author)s</p>
      <a class="play big" href="play.html">Play</a>
      %(badges)s
    </div>
  </div>
  <div class="about">%(paragraphs)s</div>
  <h2>What this stack uses</h2>
  <ul class="plain">%(meanings)s</ul>
  <p>It plays inside a boxed-in part of this page and cannot reach your files or your computer. <a href="%(root)ssafety.html">How that works.</a></p>
  <h2>Look inside</h2>
  <ul class="plain">
    <li><a href="%(root)s%(source)s">Read its scripts</a> (%(lines)s lines)</li>
    <li><a href="%(root)s%(download)s" download>Download it</a> (%(size)s) to open in OXT-Beyond. A stack you open on your own computer is no longer boxed in: it can do what any program can. Open stacks only from people you trust, and read the scripts first.</li>
  </ul>
  <p class="small">Version %(version)s. Licence: %(licence)s. %(tags)s</p>
  <p class="small"><a href="%(report)s">Report a problem with this stack</a>, or tell us on the <a href="%(forum)s">OpenXTalk forum</a>.</p>
  %(older)s
</article>''' % {
        'shot': screenshot_html(e, root, 'shot large'), 'title': esc(e['title']), 'author': esc(e['author']),
        'badges': badges_html(e['uses']), 'paragraphs': paragraphs, 'meanings': meanings, 'root': root,
        'source': url(e['source']), 'download': url(e['download']), 'lines': e['script_lines'],
        'size': human_size(e['size']), 'version': esc(e['version']),
        'licence': esc(listing_rules.LICENCES[e['licence']]),
        'tags': 'Tags: %s.' % esc(', '.join(e['tags'])) if e['tags'] else '',
        'report': esc(report), 'forum': FORUM_URL, 'older': older}
    return page('%s - OXT Community Stacks' % e['title'], body, root, first_sentence(e['description']))


def human_size(size):
    if size < 1024 * 1024:
        return '%d KB' % max(1, round(size / 1024))
    return '%.1f MB' % (size / 1048576)


def play_page(e):
    """The page a stack plays on: a slim bar, and the player in its box."""
    root = '../../'
    frame = '%splayer/play/index.html?stack=%s' % (root, urllib.parse.quote('../../' + e['download'], safe='/.'))
    return '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="referrer" content="no-referrer">
<title>%(title)s - OXT Community Stacks</title>
<link rel="stylesheet" href="%(root)sassets/site.css">
<link rel="icon" type="image/svg+xml" href="%(root)sassets/mark.svg">
</head>
<body class="playing">
<header class="bar">
  <a class="back" href="%(root)sindex.html">&larr; All stacks</a>
  <p class="now"><b>%(title)s</b> <span>by %(author)s</span></p>
  <a class="more" href="index.html">About this stack</a>
  <button id="full" type="button">Full screen</button>
</header>
<iframe id="stack" title="%(title)s" sandbox="%(sandbox)s" allow="fullscreen; autoplay; gamepad" allowfullscreen src="%(frame)s"></iframe>
<script>
(function () {
  var frame = document.getElementById('stack'), full = document.getElementById('full');
  if (!frame.requestFullscreen) { full.hidden = true; return; }
  full.addEventListener('click', function () { frame.requestFullscreen(); });
})();
</script>
</body>
</html>
''' % {'title': esc(e['title']), 'author': esc(e['author']), 'root': root, 'sandbox': SANDBOX, 'frame': esc(frame)}


def source_page(e, version, sources):
    root = '../../../'
    parts = []
    for file, stack, label, script in sources:
        parts.append('<section><h2>%s</h2><p class="small">%s, stack &quot;%s&quot;</p><pre>%s</pre></section>'
                     % (esc(label), esc(file), esc(stack), esc(script)))
    if not parts:
        parts.append('<p>This stack has no scripts.</p>')
    body = '''<article class="source">
<h1>The scripts of %s</h1>
<p>Version %s. <a href="../index.html">Back to the stack</a>. These are the scripts exactly as they are in the stack that plays here.</p>
%s
</article>''' % (esc(e['title']), esc(version), '\n'.join(parts))
    return page('Scripts of %s - OXT Community Stacks' % e['title'], body, root)


# ---------------------------------------------------------------- building

def entry_of(slug, versions):
    """A stack's line of the index, from its checked versions (newest
    first)."""
    latest = versions[0]
    listing = latest['listing']
    entry = {'slug': slug, 'title': listing['title'], 'author': listing['author'],
             'description': listing['description'], 'licence': listing['licence'],
             'tags': listing.get('tags', []), 'uses': latest['uses'], 'notes': latest['notes'],
             'version': latest['version'], 'main': listing['main'],
             'page': 's/%s/index.html' % slug, 'play': 's/%s/play.html' % slug,
             'script_lines': sum(s['script_lines'] for s in latest['stacks']),
             'versions': []}
    for report in versions:
        base = 's/%s/%s/' % (slug, report['version'])
        entry['versions'].append({
            'version': report['version'], 'main': report['listing']['main'], 'uses': report['uses'],
            'download': base + '%s-%s.zip' % (slug, report['version']),
            'source': base + 'source.html',
            'files': [{'path': f['path'], 'size': f['size'], 'sha256': f['sha256']}
                      for f in report['files'] if f['kind'] != 'listing']})
    return entry


def copy_player(player, out):
    """OXT-Beyond's Stack Player, with only what playing one stack needs,
    and the guard at the top of its page."""
    play = os.path.join(player, 'play', 'index.html')
    if not os.path.isfile(play):
        raise BuildError('%s is not a Stack Player: it has no play/index.html' % player)
    dest = os.path.join(out, 'player')
    os.makedirs(os.path.join(dest, 'play'))
    for name in sorted(os.listdir(player)):
        full = os.path.join(player, name)
        # (the player's own home page and its samples stay behind: on
        # this site a stack is only ever played in its box)
        if name in ('index.html', 'samples', 'play') or os.path.islink(full):
            continue
        if os.path.isdir(full):
            shutil.copytree(full, os.path.join(dest, name))
        else:
            shutil.copyfile(full, os.path.join(dest, name))
    with open(play, encoding='utf-8') as f:
        text = f.read()
    if text.count('<head>') != 1:
        raise BuildError('the Stack Player\'s play page has changed: no single <head> to put the guard in')
    if 'function sameSite(' not in text:
        raise BuildError('the Stack Player\'s play page has changed: it no longer keeps to its own site')
    text = text.replace('<head>', '<head>\n' + GUARD, 1)
    with open(os.path.join(dest, 'play', 'index.html'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


def static_page(name, root=''):
    with open(os.path.join(SITE_ASSETS, name), encoding='utf-8') as f:
        text = f.read()
    title, body = text.split('\n', 1)
    return page(title.strip(), body.replace('@REPOSITORY@', REPOSITORY_URL).replace('@FORUM@', FORUM_URL)
                .replace('@OXT@', OXT_URL), root)


def build(stacks_dir, engine, player, out, no_network=False, strict=False, log=print, env=None):
    """Builds the site into `out` (which must not exist or be empty).
    Returns (index, refused)."""
    if os.path.exists(out) and os.listdir(out):
        raise BuildError('%s is not empty' % out)
    os.makedirs(out, exist_ok=True)
    stacks, refused = collect(stacks_dir, engine, no_network, log)
    if strict and refused:
        raise BuildError('%d stack(s) were refused' % len(refused))

    entries = []
    for slug in sorted(stacks):
        versions = stacks[slug]
        entry = entry_of(slug, versions)
        for report, record in zip(versions, entry['versions']):
            data = make_zip(report['folder'], report['files'])
            target = os.path.join(out, *record['download'].split('/'))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, 'wb') as f:
                f.write(data)
            record['size'] = len(data)
            record['sha256'] = scan.hashlib.sha256(data).hexdigest()
            shot = report['listing'].get('screenshot')
            record['screenshot'] = None
            if shot:
                ext = os.path.splitext(shot)[1].lower()
                with open(os.path.join(report['folder'], *shot.split('/')), 'rb') as f:
                    picture = f.read()
                # (served under a name made here, and only when it starts
                # as a picture of its kind does)
                if any(picture.startswith(m) for m in IMAGE_MAGIC.get(ext, ())):
                    record['screenshot'] = 's/%s/%s/screenshot%s' % (slug, report['version'], ext)
                    with open(os.path.join(out, *record['screenshot'].split('/')), 'wb') as f:
                        f.write(picture)
                else:
                    log('::warning::%s %s: the screenshot is not a picture of its kind, left out'
                        % (slug, report['version']))
        latest = entry['versions'][0]
        entry.update({'download': latest['download'], 'source': latest['source'], 'size': latest['size'],
                      'sha256': latest['sha256'], 'screenshot': latest['screenshot']})
        entry['screenshot_url'] = entry['screenshot']
        entries.append(entry)
        for report, record in zip(versions, entry['versions']):
            write(os.path.join(out, *record['source'].split('/')),
                  source_page(entry, report['version'], report['_sources']))
        write(os.path.join(out, 's', slug, 'index.html'), stack_page(entry))
        write(os.path.join(out, 's', slug, 'play.html'), play_page(entry))

    entries.sort(key=lambda e: (e['title'].lower(), e['slug']))
    write(os.path.join(out, 'index.html'), gallery_page(entries))
    for name in ('safety.html', 'share.html', '404.html'):
        write(os.path.join(out, name), static_page(name))
    shutil.copytree(os.path.join(SITE_ASSETS, 'assets'), os.path.join(out, 'assets'))
    write(os.path.join(out, '.nojekyll'), '')
    copy_player(player, out)

    index = {'format': 1, 'name': 'OXT Community Stacks', 'stacks': []}
    for e in entries:
        item = dict(e)
        item.pop('screenshot_url')
        item.pop('notes')
        index['stacks'].append(item)
    text = json.dumps(index, indent=1, sort_keys=True, ensure_ascii=True) + '\n'
    write(os.path.join(out, 'index.json'), text)

    seed = sign.secret_seed(env)
    public = sign.read_public()
    if seed is not None:
        if public is None or sign.ed25519.public_key(seed) != public:
            raise BuildError('the signing key is not the one signing-key.pub names')
        write(os.path.join(out, 'index.sig'), sign.sign_bytes(seed, text.encode('utf-8')) + '\n')
        log('index.json is signed')
    else:
        # (the Publish workflow signs in a job of its own, which is the
        # only one that holds the key)
        log('index.json is not signed in this run: there is no signing key here (tools/sign.py)')
    return index, refused


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build the gallery site.')
    parser.add_argument('--stacks', default=os.path.join(ROOT, 'stacks'))
    parser.add_argument('--engine', default=os.environ.get('OXT_ENGINE'), required=not os.environ.get('OXT_ENGINE'))
    parser.add_argument('--player', required=True, help='the unpacked StackPlayer folder (tools/fetch.py player)')
    parser.add_argument('--out', required=True)
    parser.add_argument('--no-network', action='store_true')
    parser.add_argument('--strict', action='store_true', help='fail when a stack is refused')
    args = parser.parse_args(argv)
    try:
        index, refused = build(args.stacks, args.engine, args.player, args.out, args.no_network, args.strict)
    except (BuildError, scan.ScanError, sign.KeyError_) as e:
        print('The site could not be built: %s' % e, file=sys.stderr)
        return 2
    print('%d stack(s) in the gallery, %d left out' % (len(index['stacks']), len(refused)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
