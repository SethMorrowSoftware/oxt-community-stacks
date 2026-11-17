"""Small stacks for the tests, made with the engine itself.

The tests that read a stack need OXT-Beyond's engine: set OXT_ENGINE to
it (tools/fetch.py engine <folder> prints where it is). Without one
those tests are skipped, loudly; with OXT_REQUIRE_ENGINE=1, as in CI,
a missing engine is a failure instead: a skipped test passes whatever
the scanner does.
"""
import json
import os
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
MAKE = os.path.join(HERE, 'make-fixture.livecodescript')
ENGINE = os.environ.get('OXT_ENGINE', '')

PNG = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
       b'\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82')

CLEAN_SCRIPT = 'on mouseUp\n   put "Hello" into field 1\nend mouseUp\n'


def need_engine(test):
    """Skips a test without an engine, or fails it where one is required."""
    if ENGINE and os.path.isfile(ENGINE):
        return
    if os.environ.get('OXT_REQUIRE_ENGINE') == '1':
        test.fail('OXT_ENGINE is not an engine, and OXT_REQUIRE_ENGINE=1 says there must be one')
    raise unittest.SkipTest('no engine: set OXT_ENGINE (tools/fetch.py engine <folder>)')


def make_stack(out, name, script=None, button=None, substack=None, externals=None, stackfiles=None):
    """Saves a stack file `out` named `name`; the scripts are text."""
    env = dict(os.environ, OXT_FIXTURE_OUT=out, OXT_FIXTURE_NAME=name)
    folder = os.path.dirname(out)
    for key, text in (('SCRIPT', script), ('BUTTON', button), ('SUBSTACK', substack)):
        if text is not None:
            path = os.path.join(folder, '_%s_%s.txt' % (os.path.basename(out), key.lower()))
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(text)
            env['OXT_FIXTURE_' + key] = path
    if externals:
        env['OXT_FIXTURE_EXTERNALS'] = externals
    if stackfiles:
        env['OXT_FIXTURE_STACKFILES'] = stackfiles
    done = subprocess.run([ENGINE, '-ui', MAKE], env=env, capture_output=True, text=True, timeout=120)
    for key in ('SCRIPT', 'BUTTON', 'SUBSTACK'):
        path = env.get('OXT_FIXTURE_' + key)
        if path:
            os.remove(path)
    if done.returncode != 0 or not os.path.isfile(out):
        raise RuntimeError('the fixture stack could not be made: %s %s' % (done.stdout, done.stderr))


def make_folder(root, slug='test-stack', version='1.0', title='Test Stack', listing=None, screenshot=True,
                **stack):
    """A stacks/<slug>/<version> folder under root, with one stack made
    by make_stack(**stack), in the file `file` (the title, by default).
    Returns the folder."""
    folder = os.path.join(root, 'stacks', slug, version)
    os.makedirs(folder)
    main = stack.pop('file', title + '.oxtstack')
    make_stack(os.path.join(folder, main), stack.pop('name', title), **stack)
    data = {'title': title, 'author': 'Test Author', 'description': 'A stack that the tests made.',
            'licence': 'GPL-3.0-only', 'main': main}
    if screenshot:
        with open(os.path.join(folder, 'screenshot.png'), 'wb') as f:
            f.write(PNG)
        data['screenshot'] = 'screenshot.png'
    if listing:
        data.update(listing)
    with open(os.path.join(folder, 'listing.json'), 'w', encoding='utf-8') as f:
        json.dump(data, f)
    return folder
