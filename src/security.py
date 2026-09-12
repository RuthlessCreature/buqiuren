import base64
import hashlib
import hmac
import re
import secrets

USERNAME_RE = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff]{3,32}$")
PBKDF2_ITERATIONS = 60_000


def validate_username(username: str) -> str:
    username = (username or "").strip()
    if not USERNAME_RE.fullmatch(username):
        raise ValueError("用户名需为 3–32 位中文、字母、数字、下划线或短横线")
    return username


def validate_password(password: str) -> None:
    if not isinstance(password, str) or len(password) < 8:
        raise ValueError("密码至少 8 位")
    if len(password) > 128:
        raise ValueError("密码过长")


def _material(password: str, pepper: str) -> bytes:
    return (password + "\x00" + pepper).encode("utf-8")


def _pbkdf2_sha256(password_material: bytes, salt: bytes, iterations: int, dklen: int = 32) -> bytes:
    """PBKDF2-HMAC-SHA256 with a pure-Python fallback for Pyodide/Workers.

    Cloudflare Python Workers run on Pyodide, where OpenSSL-backed hashlib helpers
    can be unavailable. We prefer CPython's optimized implementation whenever it
    exists and fall back to the RFC 8018 construction using hmac+sha256.
    """
    try:
        fn = getattr(hashlib, "pbkdf2_hmac")
        return fn("sha256", password_material, salt, iterations, dklen=dklen)
    except (AttributeError, NotImplementedError, RuntimeError):
        pass

    hlen = hashlib.sha256().digest_size
    blocks = (dklen + hlen - 1) // hlen
    derived = bytearray()
    for block_index in range(1, blocks + 1):
        u = hmac.new(password_material, salt + block_index.to_bytes(4, "big"), hashlib.sha256).digest()
        acc = bytearray(u)
        for _ in range(1, iterations):
            u = hmac.new(password_material, u, hashlib.sha256).digest()
            for i, b in enumerate(u):
                acc[i] ^= b
        derived.extend(acc)
    return bytes(derived[:dklen])


def hash_password(password: str, pepper: str) -> str:
    validate_password(password)
    salt = secrets.token_bytes(16)
    digest = _pbkdf2_sha256(_material(password, pepper), salt, PBKDF2_ITERATIONS, 32)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode().rstrip("="),
        base64.urlsafe_b64encode(digest).decode().rstrip("="),
    )


def verify_password(password: str, encoded: str, pepper: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_b64 + "=" * (-len(salt_b64) % 4))
        expected = base64.urlsafe_b64decode(digest_b64 + "=" * (-len(digest_b64) % 4))
        actual = _pbkdf2_sha256(_material(password, pepper), salt, int(iterations), len(expected))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def token_hash(token: str, pepper: str) -> str:
    return hmac.new(pepper.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def ip_hash(ip: str, pepper: str) -> str:
    return hmac.new(pepper.encode("utf-8"), (ip or "unknown").encode("utf-8"), hashlib.sha256).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest((a or "").encode(), (b or "").encode())
