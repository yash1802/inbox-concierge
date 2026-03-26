from cryptography.fernet import Fernet, InvalidToken


def encrypt_secret(fernet: Fernet, value: str) -> str:
    return fernet.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(fernet: Fernet, token: str) -> str:
    try:
        return fernet.decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as e:
        raise ValueError("Invalid encrypted token") from e
