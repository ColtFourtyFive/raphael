"""Broker credential encryption: KMS in AWS, a local Fernet key in dev.

Ciphertexts are tagged so a row encrypted locally is never mistaken for KMS output.
Decrypted credentials are only ever handed to a broker adapter; never log them.
"""

from __future__ import annotations

import json

from cryptography.fernet import Fernet

from atp.config import Settings, get_settings

_LOCAL = b"local:"
_KMS = b"kms:"


class CredentialsError(RuntimeError):
    pass


def encrypt_credentials(creds: dict[str, str], settings: Settings | None = None) -> bytes:
    s = settings or get_settings()
    plaintext = json.dumps(creds).encode()
    if s.aws_kms_key_arn:
        import boto3

        kms = boto3.client("kms")
        out = kms.encrypt(KeyId=s.aws_kms_key_arn, Plaintext=plaintext)
        return _KMS + bytes(out["CiphertextBlob"])
    return _LOCAL + _fernet(s).encrypt(plaintext)


def decrypt_credentials(blob: bytes, settings: Settings | None = None) -> dict[str, str]:
    s = settings or get_settings()
    if blob.startswith(_KMS):
        import boto3

        out = boto3.client("kms").decrypt(CiphertextBlob=blob[len(_KMS) :])
        data = out["Plaintext"]
    elif blob.startswith(_LOCAL):
        data = _fernet(s).decrypt(blob[len(_LOCAL) :])
    else:
        raise CredentialsError("unrecognised credential ciphertext")
    result: dict[str, str] = json.loads(data)
    return result


def _fernet(s: Settings) -> Fernet:
    key = s.local_encryption_key.get_secret_value()
    if not key:
        raise CredentialsError(
            "LOCAL_ENCRYPTION_KEY is not set; generate one with `atp keygen` (dev) "
            "or set AWS_KMS_KEY_ARN (AWS)"
        )
    return Fernet(key.encode())
