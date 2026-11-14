#!/usr/bin/env python3
"""The repository's signing key, and signing with it.

    python3 tools/sign.py new-key --secret-out <file>
        Makes a key. The secret half goes into <file> and is never
        printed; the public half is printed, and written to
        signing-key.pub at the top of the repository. Paste the file's one
        line into the repository's secret STACKS_SIGNING_KEY (Settings >
        Secrets and variables > Actions), then delete the file.

    python3 tools/sign.py public
        Prints the public half of the key in $STACKS_SIGNING_KEY.

    python3 tools/sign.py sign <file> <signature file>
        Signs a file with the key in $STACKS_SIGNING_KEY.

    python3 tools/sign.py verify <file> <signature file> [<public key file>]
        Checks a signature; exit code 0 when it is good.

The key is an Ed25519 key (tools/ed25519.py). The secret is the base64 of
its 32-byte seed, the public key the base64 of its 32 bytes, and a
signature the base64 of its 64 bytes, each on one line. They are
libsodium's: in OXT-Beyond, SodiumXT's sxSignVerifyDetached checks the
signature of the gallery's index before the IDE believes it.
"""
import base64
import binascii
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ed25519  # noqa: E402

PUBLIC_KEY_FILE = os.path.join(os.path.dirname(HERE), 'signing-key.pub')
SECRET_ENV = 'STACKS_SIGNING_KEY'


class KeyError_(Exception):
    pass


def _decode(text, size, what):
    try:
        raw = base64.b64decode(text.strip().encode('ascii'), validate=True)
    except (binascii.Error, UnicodeError, ValueError):
        raise KeyError_('%s is not base64' % what)
    if len(raw) != size:
        raise KeyError_('%s is %d bytes, not %d' % (what, len(raw), size))
    return raw


def secret_seed(env=None):
    """The seed in $STACKS_SIGNING_KEY, or None when there is no key."""
    text = (os.environ if env is None else env).get(SECRET_ENV, '').strip()
    if not text:
        return None
    return _decode(text, 32, 'the signing key')


def read_public(path=PUBLIC_KEY_FILE):
    """The committed public key, or None when there is none yet."""
    if not os.path.isfile(path):
        return None
    with open(path, encoding='ascii') as f:
        return _decode(f.read(), 32, 'the public key')


def sign_bytes(seed, data):
    return base64.b64encode(ed25519.sign(seed, data)).decode('ascii')


def verify_bytes(public, data, signature_text):
    try:
        signature = _decode(signature_text, 64, 'the signature')
    except KeyError_:
        return False
    return ed25519.verify(public, data, signature)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv[:1] == ['new-key'] and len(argv) == 3 and argv[1] == '--secret-out':
            out = argv[2]
            if os.path.exists(out):
                sys.exit('%s is already there; choose a new file name' % out)
            seed = os.urandom(32)
            fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w', encoding='ascii', newline='\n') as f:
                f.write(base64.b64encode(seed).decode('ascii') + '\n')
            public = base64.b64encode(ed25519.public_key(seed)).decode('ascii')
            with open(PUBLIC_KEY_FILE, 'w', encoding='ascii', newline='\n') as f:
                f.write(public + '\n')
            print('The secret key is in %s (not shown here).' % out)
            print('The public key, also written to signing-key.pub:')
            print(public)
            return 0
        if argv == ['public']:
            seed = secret_seed()
            if seed is None:
                sys.exit('set %s to the secret key' % SECRET_ENV)
            print(base64.b64encode(ed25519.public_key(seed)).decode('ascii'))
            return 0
        if argv[:1] == ['sign'] and len(argv) == 3:
            seed = secret_seed()
            if seed is None:
                sys.exit('set %s to the secret key' % SECRET_ENV)
            # (a signature nobody can check is worse than none: the key
            # must be the one whose public half is committed)
            if read_public() != ed25519.public_key(seed):
                sys.exit('the signing key is not the one signing-key.pub names')
            with open(argv[1], 'rb') as f:
                data = f.read()
            with open(argv[2], 'w', encoding='ascii', newline='\n') as f:
                f.write(sign_bytes(seed, data) + '\n')
            return 0
        if argv[:1] == ['verify'] and len(argv) in (3, 4):
            public = read_public(argv[3]) if len(argv) == 4 else read_public()
            if public is None:
                sys.exit('there is no public key')
            with open(argv[1], 'rb') as f:
                data = f.read()
            with open(argv[2], encoding='ascii') as f:
                good = verify_bytes(public, data, f.read())
            print('good signature' if good else 'BAD signature')
            return 0 if good else 1
    except KeyError_ as e:
        sys.exit(str(e))
    sys.exit(__doc__)


if __name__ == '__main__':
    sys.exit(main())
