#!/usr/bin/env python3
"""Ed25519 signatures (RFC 8032) in plain Python, nothing to install.

    public = public_key(seed)             32-byte seed -> 32-byte public key
    signature = sign(seed, message)       64 bytes
    verify(public, message, signature)    True or False

The same signatures as libsodium's crypto_sign_detached, so SodiumXT's
sxSignVerifyDetached checks them in the IDE (libsodium's 64-byte secret
key is seed + public key).

This is the arithmetic of RFC 8032 section 6, written for clearness, not
speed, and it does not run in constant time: fine for signing a list of
shared stacks on a build machine, not for a server that signs what
strangers send it. tools/tests/test_ed25519.py holds it to the RFC's own
test vectors.
"""
import hashlib

_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _inv(x):
    return pow(x, _P - 2, _P)


def _recover_x(y, sign):
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _I % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_BY = 4 * _inv(5) % _P
_BX = _recover_x(_BY, 0)
_B = (_BX, _BY, 1, _BX * _BY % _P)      # extended coordinates (X, Y, Z, T)
_ZERO = (0, 1, 1, 0)


def _add(p, q):
    a = (p[1] - p[0]) * (q[1] - q[0]) % _P
    b = (p[1] + p[0]) * (q[1] + q[0]) % _P
    c = 2 * p[3] * q[3] * _D % _P
    d = 2 * p[2] * q[2] % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(s, p):
    q = _ZERO
    while s > 0:
        if s & 1:
            q = _add(q, p)
        p = _add(p, p)
        s >>= 1
    return q


def _equal(p, q):
    return (p[0] * q[2] - q[0] * p[2]) % _P == 0 and (p[1] * q[2] - q[1] * p[2]) % _P == 0


def _compress(p):
    zinv = _inv(p[2])
    x, y = p[0] * zinv % _P, p[1] * zinv % _P
    return (y | ((x & 1) << 255)).to_bytes(32, 'little')


def _decompress(s):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, 'little')
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


def _h(data):
    return int.from_bytes(hashlib.sha512(data).digest(), 'little')


def _expand(seed):
    if len(seed) != 32:
        raise ValueError('an Ed25519 seed is 32 bytes')
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], 'little')
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_key(seed):
    a, _ = _expand(seed)
    return _compress(_mul(a, _B))


def sign(seed, message):
    a, prefix = _expand(seed)
    public = _compress(_mul(a, _B))
    r = _h(prefix + message) % _L
    big_r = _compress(_mul(r, _B))
    h = _h(big_r + public + message) % _L
    s = (r + h * a) % _L
    return big_r + s.to_bytes(32, 'little')


def verify(public, message, signature):
    if len(public) != 32 or len(signature) != 64:
        return False
    a = _decompress(public)
    big_r = _decompress(signature[:32])
    if a is None or big_r is None:
        return False
    s = int.from_bytes(signature[32:], 'little')
    if s >= _L:
        return False
    h = _h(signature[:32] + public + message) % _L
    return _equal(_mul(s, _B), _add(big_r, _mul(h, a)))
