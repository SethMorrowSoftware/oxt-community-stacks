#!/usr/bin/env python3
"""Writes suite-handlers.json: the public handlers of the xTalk Suite
libraries that the scanner needs to tell apart.

    python3 tools/make_suite_handlers.py <xtalk-suite checkout>

Shared stacks play in a web browser, where only some of the suite exists
(OXT-Beyond's tools/web-ide/xtalk_web_libraries.py, KNOWN). A stack that
calls a library the web engine does not have cannot work there, and the
scanner says so by name instead of leaving the author with "handler not
found". The libraries that reach the network get the "internet" badge.

Run it again when the suite gains or loses a public handler; the file
records the suite commit it was made from.
"""
import json
import os
import re
import subprocess
import sys

# member -> (source files, what the scanner does with a call)
#   "blocked":  not in the web engine: a stack that calls it is refused
#   "internet": in the web engine, and it talks to other machines
MEMBERS = {
    'enetxt': (['enetxt/src/enet.lcb'], 'blocked'),
    'torrentxt': (['torrentxt/src/torrent.lcb'], 'blocked'),
    'onionxt': (['onionxt/src/onionxt.livecodescript',
                 'onionxt/src/onion-httpd.livecodescript'], 'blocked'),
    'datachannelxt': (['datachannelxt/src/datachannel.lcb'], 'internet'),
    'nostrxt-relay': (['nostrxt/src/nostr-relay.livecodescript'], 'internet'),
}

LCB = re.compile(r'^public\s+handler\s+([A-Za-z_][A-Za-z0-9_]*)', re.M)
LCS = re.compile(r'^(?:command|function|on)\s+([A-Za-z_][A-Za-z0-9_]*)', re.M)
# The engine's own messages, which a library handles but does not own
ENGINE = {'socketerror', 'socketclosed', 'sockettimeout', 'librarystack',
          'releasestack', 'extensioninitialize', 'extensionfinalize'}


def handlers(path):
    with open(path, encoding='utf-8') as f:
        text = f.read()
    names = (LCB if path.endswith('.lcb') else LCS).findall(text)
    return sorted({n for n in names if n.lower() not in ENGINE}, key=str.lower)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    suite = sys.argv[1]
    commit = subprocess.run(['git', '-C', suite, 'rev-parse', 'HEAD'],
                            capture_output=True, text=True, check=True).stdout.strip()
    out = {'suite_commit': commit, 'members': {}}
    for member, (files, what) in MEMBERS.items():
        names = []
        for rel in files:
            names += handlers(os.path.join(suite, rel))
        if not names:
            sys.exit('no public handlers found for ' + member)
        out['members'][member] = {'does': what, 'handlers': sorted(set(names), key=str.lower)}
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, 'suite-handlers.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(out, f, indent=1, sort_keys=True)
        f.write('\n')
    for member, entry in out['members'].items():
        print('%-14s %-8s %d handlers' % (member, entry['does'], len(entry['handlers'])))


if __name__ == '__main__':
    main()
