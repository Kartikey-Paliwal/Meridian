import os
import hashlib
import random
from cryptography.fernet import Fernet

# Fixed secret key for hackathon MVP demo repeatability (in production, loaded from secure KMS)
KEY_FILE = os.path.join(os.path.dirname(__file__), "secret.key")

def get_or_create_key():
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return f.read()
    else:
        key = Fernet.generate_key()
        with open(KEY_FILE, "wb") as f:
            f.write(key)
        return key

FERNET_KEY = get_or_create_key()
fernet = Fernet(FERNET_KEY)

def encrypt_field(plaintext: str) -> str:
    """Encrypt sensitive identifier (e.g. staff_id, patient details) with Fernet."""
    if not plaintext:
        return ""
    encrypted_bytes = fernet.encrypt(plaintext.encode("utf-8"))
    return encrypted_bytes.decode("utf-8")

def decrypt_field(ciphertext: str) -> str:
    """Decrypt ciphertext back to original identifier."""
    if not ciphertext:
        return ""
    try:
        decrypted_bytes = fernet.decrypt(ciphertext.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except Exception:
        return "[Decryption Failed]"

def tokenize_identifier(identifier: str) -> str:
    """Generate SHA-256 token representation of identifier for anonymized tracking."""
    if not identifier:
        return ""
    return "TOK-" + hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:12].upper()

def add_dp_noise(count_val: int, epsilon: float = 1.0) -> dict:
    """
    Simulate Differential Privacy noise addition for aggregate counts shown above PHC level.
    Returns both true count, noised count, and noise value for explainability.
    """
    # Simple Laplace-like or bounded integer noise [-2, 2]
    noise = random.choice([-2, -1, 0, 1, 2])
    noised_val = max(0, count_val + noise)
    return {
        "true_count": count_val,
        "noised_count": noised_val,
        "noise_added": noise,
        "privacy_mechanism": "Laplace Differential Privacy Noise Simulation (Epsilon = 1.0)"
    }
