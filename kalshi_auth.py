import time
import base64
import os
from typing import Dict, Optional
from pathlib import Path

# Try importing cryptography, or fall back to Crypto (pycryptodome)
try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

try:
    from Crypto.PublicKey import RSA
    from Crypto.Signature import pss
    from Crypto.Hash import SHA256
    HAS_PYCRYPTODOME = True
except ImportError:
    HAS_PYCRYPTODOME = False


class KalshiAuth:
    """
    Manages RSA-PSS signing and authentication headers for Kalshi API v2.
    Preloads and caches the RSA private key in memory for zero-latency signature generation.
    """

    def __init__(self, key_id: str = "", private_key_path: str = ""):
        self.key_id = key_id.strip()
        self.private_key_path = private_key_path.strip()
        self._crypto_private_key = None
        self._pycrypto_key = None
        self.is_configured = False

        if self.key_id and self.private_key_path:
            self._load_private_key()

    def _load_private_key(self):
        key_path = Path(self.private_key_path)
        if not key_path.exists():
            print(f"[KalshiAuth] Warning: Private key file not found at {self.private_key_path}")
            return

        key_bytes = key_path.read_bytes()

        if HAS_CRYPTOGRAPHY:
            try:
                self._crypto_private_key = serialization.load_pem_private_key(key_bytes, password=None)
                self.is_configured = True
                print("[KalshiAuth] Successfully loaded private key using cryptography.")
                return
            except Exception as e:
                print(f"[KalshiAuth] cryptography key load error: {e}")

        if HAS_PYCRYPTODOME:
            try:
                self._pycrypto_key = RSA.import_key(key_bytes)
                self.is_configured = True
                print("[KalshiAuth] Successfully loaded private key using pycryptodome.")
                return
            except Exception as e:
                print(f"[KalshiAuth] pycryptodome key load error: {e}")

    def sign_request(self, method: str, path: str) -> Dict[str, str]:
        """
        Signs the request using RSA-PSS SHA-256 according to Kalshi v2 specifications.
        Message = timestamp_ms + METHOD + path_without_query
        """
        if not self.is_configured:
            # Unauthenticated or simulation mode
            return {}

        timestamp_ms = str(int(time.time() * 1000))
        path_clean = path.split("?")[0]
        message_bytes = f"{timestamp_ms}{method.upper()}{path_clean}".encode("utf-8")

        if HAS_CRYPTOGRAPHY and self._crypto_private_key:
            signature = self._crypto_private_key.sign(
                message_bytes,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH
                ),
                hashes.SHA256()
            )
            sig_b64 = base64.b64encode(signature).decode("utf-8")
        elif HAS_PYCRYPTODOME and self._pycrypto_key:
            h = SHA256.new(message_bytes)
            signature = pss.new(self._pycrypto_key).sign(h)
            sig_b64 = base64.b64encode(signature).decode("utf-8")
        else:
            raise RuntimeError("No working RSA library available for signing")

        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
            "KALSHI-ACCESS-SIGNATURE": sig_b64,
            "Content-Type": "application/json"
        }
