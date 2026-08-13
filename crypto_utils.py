from cryptography.fernet import Fernet

from config import SESSION_ENCRYPTION_KEY

fernet = Fernet(SESSION_ENCRYPTION_KEY.encode())


def encrypt_session(session: str) -> str:
    return fernet.encrypt(session.encode()).decode()


def decrypt_session(token: str) -> str:
    return fernet.decrypt(token.encode()).decode()
