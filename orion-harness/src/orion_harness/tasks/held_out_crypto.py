"""Encrypted-at-rest storage for `held_out` tasks (§4, §8.1).

OF-TR-002 specifies `age` for this. `age` is a separate Go binary and was
not installed here -- per explicit instruction in this session, no new
tools are installed without asking first. `cryptography`'s Fernet
(AES-128-CBC + HMAC-SHA256, authenticated) was already present in this
environment and is used instead: same mechanism (opaque ciphertext on
disk, a key required to read it, release CI is the only holder of the
key), different tool. Files use the extension `.yaml.enc`, not
`.yaml.age`, specifically so nobody mistakes them for real
age-encrypted files or tries to decrypt them with the `age` CLI.
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken

HELD_OUT_KEY_ENV = "ORION_HELD_OUT_KEY"


class HeldOutKeyMissing(RuntimeError):
    pass


def _get_key() -> bytes:
    key = os.environ.get(HELD_OUT_KEY_ENV)
    if not key:
        raise HeldOutKeyMissing(
            f"{HELD_OUT_KEY_ENV} is not set -- held_out tasks cannot be decrypted "
            f"outside release CI (§8.1)"
        )
    return key.encode("utf-8")


def generate_key() -> str:
    """Release CI setup: generate a new key once, store it as a CI secret."""

    return Fernet.generate_key().decode("utf-8")


def encrypt(plaintext: bytes) -> bytes:
    return Fernet(_get_key()).encrypt(plaintext)


def decrypt(ciphertext: bytes) -> bytes:
    try:
        return Fernet(_get_key()).decrypt(ciphertext)
    except InvalidToken as e:
        raise ValueError(
            "held_out ciphertext could not be decrypted with the configured "
            f"{HELD_OUT_KEY_ENV} -- wrong key, or the file is corrupt"
        ) from e
