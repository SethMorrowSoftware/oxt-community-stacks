"""tools/ed25519.py against RFC 8032's test vectors (section 7.1), and
tools/sign.py around it."""
import base64
import binascii
import os
import subprocess
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)

import ed25519  # noqa: E402
import sign  # noqa: E402

# (seed, public key, message, signature), in hex: RFC 8032 7.1, TEST 1,
# 2, 3 and SHA(abc)
VECTORS = [
    ('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60',
     'd75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a',
     '',
     'e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155'
     '5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b'),
    ('4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb',
     '3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c',
     '72',
     '92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da'
     '085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00'),
    ('c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7',
     'fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025',
     'af82',
     '6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac'
     '18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a'),
    ('833fe62409237b9d62ec77587520911e9a759cec1d19755b7da901b96dca3d42',
     'ec172b93ad5e563bf4932c70e1245034c35467ef2efd4d64ebf819683467e2bf',
     'ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a'
     '2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f',
     'dc2a4459e7369633a52b1bf277839a00201009a3efbf3ecb69bea2186c26b589'
     '09351fc9ac90b3ecfdfbc7c66431e0303dca179c138ac17ad9bef1177331a704'),
]


class Ed25519(unittest.TestCase):
    def test_rfc_vectors(self):
        for seed, public, message, signature in VECTORS:
            seed, public, message, signature = map(binascii.unhexlify, (seed, public, message, signature))
            self.assertEqual(ed25519.public_key(seed), public)
            self.assertEqual(ed25519.sign(seed, message), signature)
            self.assertTrue(ed25519.verify(public, message, signature))

    def test_a_changed_message_signature_or_key_fails(self):
        seed, public, message, signature = map(binascii.unhexlify, VECTORS[2])
        self.assertFalse(ed25519.verify(public, message + b'x', signature))
        self.assertFalse(ed25519.verify(public, message[:-1], signature))
        for i in (0, 31, 32, 63):
            bad = bytearray(signature)
            bad[i] ^= 1
            self.assertFalse(ed25519.verify(public, message, bytes(bad)))
        other = binascii.unhexlify(VECTORS[1][1])
        self.assertFalse(ed25519.verify(other, message, signature))

    def test_malformed_input_is_false_not_an_error(self):
        seed, public, message, signature = map(binascii.unhexlify, VECTORS[0])
        self.assertFalse(ed25519.verify(public[:31], message, signature))
        self.assertFalse(ed25519.verify(public, message, signature[:63]))
        self.assertFalse(ed25519.verify(b'\xff' * 32, message, signature))
        # s must be below the group order: s + L signs the same otherwise
        s = int.from_bytes(signature[32:], 'little') + ed25519._L
        self.assertFalse(ed25519.verify(public, message, signature[:32] + s.to_bytes(32, 'little')))

    def test_seed_length(self):
        with self.assertRaises(ValueError):
            ed25519.public_key(b'short')


class Sign(unittest.TestCase):
    def test_sign_and_verify_bytes(self):
        seed = binascii.unhexlify(VECTORS[0][0])
        public = ed25519.public_key(seed)
        text = sign.sign_bytes(seed, b'index')
        self.assertEqual(len(base64.b64decode(text)), 64)
        self.assertTrue(sign.verify_bytes(public, b'index', text))
        self.assertTrue(sign.verify_bytes(public, b'index', text + '\n'))
        self.assertFalse(sign.verify_bytes(public, b'index2', text))
        self.assertFalse(sign.verify_bytes(public, b'index', 'not base64!'))
        self.assertFalse(sign.verify_bytes(public, b'index', ''))

    def test_secret_from_the_environment(self):
        seed = os.urandom(32)
        self.assertIsNone(sign.secret_seed({}))
        self.assertIsNone(sign.secret_seed({sign.SECRET_ENV: '  '}))
        self.assertEqual(sign.secret_seed({sign.SECRET_ENV: base64.b64encode(seed).decode() + '\n'}), seed)
        with self.assertRaises(sign.KeyError_):
            sign.secret_seed({sign.SECRET_ENV: 'abcd'})

    def test_the_repository_public_key_is_a_key(self):
        # signing-key.pub is what the IDE is given to check index.sig
        # with: one line, the base64 of a point on the curve. A file
        # that is anything else would make every signature fail there.
        if not os.path.isfile(sign.PUBLIC_KEY_FILE):
            self.skipTest('no signing key has been made yet')
        with open(sign.PUBLIC_KEY_FILE, 'rb') as f:
            raw = f.read()
        self.assertRegex(raw, rb'\A[A-Za-z0-9+/]{43}=\n\Z')
        public = sign.read_public()
        self.assertEqual(len(public), 32)
        self.assertIsNotNone(ed25519._decompress(public))
        # and the secret half is nowhere in the repository
        root = os.path.dirname(sign.PUBLIC_KEY_FILE)
        self.assertEqual([n for n in os.listdir(root) if n.endswith('.secret')], [])

    def test_new_key_never_prints_the_secret(self):
        with tempfile.TemporaryDirectory() as folder:
            # a copy of the tools, so the repository's own signing-key.pub
            # is not touched
            tools = os.path.join(folder, 'tools')
            os.mkdir(tools)
            for name in ('sign.py', 'ed25519.py'):
                with open(os.path.join(TOOLS, name), 'rb') as src, open(os.path.join(tools, name), 'wb') as dst:
                    dst.write(src.read())
            secret = os.path.join(folder, 'secret.txt')
            done = subprocess.run([sys.executable, os.path.join(tools, 'sign.py'), 'new-key', '--secret-out', secret],
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            with open(secret, encoding='ascii') as f:
                secret_text = f.read().strip()
            self.assertNotIn(secret_text, done.stdout + done.stderr)
            with open(os.path.join(folder, 'signing-key.pub'), encoding='ascii') as f:
                public_text = f.read().strip()
            self.assertIn(public_text, done.stdout)
            self.assertEqual(base64.b64encode(ed25519.public_key(base64.b64decode(secret_text))).decode(),
                             public_text)
            # it does not write over a key that is there
            again = subprocess.run([sys.executable, os.path.join(tools, 'sign.py'), 'new-key', '--secret-out', secret],
                                   capture_output=True, text=True)
            self.assertNotEqual(again.returncode, 0)
            # sign and verify, as the command line does them
            data = os.path.join(folder, 'index.json')
            with open(data, 'w') as f:
                f.write('{}\n')
            env = dict(os.environ, **{sign.SECRET_ENV: secret_text})
            sig = os.path.join(folder, 'index.sig')
            self.assertEqual(subprocess.run([sys.executable, os.path.join(tools, 'sign.py'), 'sign', data, sig],
                                            env=env).returncode, 0)
            good = subprocess.run([sys.executable, os.path.join(tools, 'sign.py'), 'verify', data, sig],
                                  capture_output=True, text=True)
            self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
            with open(data, 'a') as f:
                f.write(' ')
            bad = subprocess.run([sys.executable, os.path.join(tools, 'sign.py'), 'verify', data, sig],
                                 capture_output=True, text=True)
            self.assertEqual(bad.returncode, 1)
            # a key that is not the committed one signs nothing
            other = base64.b64encode(bytes(range(32))).decode()
            sig2 = os.path.join(folder, 'other.sig')
            wrong = subprocess.run([sys.executable, os.path.join(tools, 'sign.py'), 'sign', data, sig2],
                                   env=dict(os.environ, **{sign.SECRET_ENV: other}), capture_output=True, text=True)
            self.assertNotEqual(wrong.returncode, 0)
            self.assertFalse(os.path.exists(sig2))
            self.assertNotIn(other, wrong.stdout + wrong.stderr)


if __name__ == '__main__':
    unittest.main()
