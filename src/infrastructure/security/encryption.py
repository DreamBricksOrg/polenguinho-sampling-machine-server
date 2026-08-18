from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from base64 import b64encode, b64decode
from typing import Union

def encrypt(value: str, public_key_pem: Union[str, bytes]) -> str:
    if isinstance(public_key_pem, str):
        public_key_pem = public_key_pem.encode()
    public_key = serialization.load_pem_public_key(public_key_pem)
    ciphertext = public_key.encrypt(
        value.encode(),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )
    return b64encode(ciphertext).decode()

def decrypt(encrypted_value: str, private_key_pem: Union[str, bytes]) -> str:
    if isinstance(private_key_pem, str):
        private_key_pem = private_key_pem.encode()
    private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    decrypted = private_key.decrypt(
        b64decode(encrypted_value.encode()),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )
    return decrypted.decode()
