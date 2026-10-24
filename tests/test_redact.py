"""
Redaction is what makes --capture-payloads defensible, so it's tested on
its own: known key names, known secret shapes, things that must NOT be
touched, blobs, truncation, and a Hypothesis property that a secret
planted under a secret-looking key never survives, whatever surrounds it.

Best effort is the honest description: it can't catch a secret in free
text that matches no known shape, and this file doesn't pretend otherwise.

Usage:
    .venv\\Scripts\\python.exe tests\\test_redact.py
"""
import json
import sys
from pathlib import Path

from hypothesis import assume, given, settings
from hypothesis import strategies as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from greenlight.redact import REDACTED, redact, redact_text, to_payload  # noqa: E402

FAKE_KEYS = {
    "openai/anthropic style": "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUv",
    "github token": "ghp_" + "a1B2c3D4e5" * 4,
    "aws key id": "AKIAIOSFODNN7EXAMPLE",
    "slack token": "xoxb-1234567890-abcdefghij",
    "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r",
    "bearer": "Bearer abcdefghijklmnopqrstuvwx12345",
}


def test_secret_looking_keys_are_redacted() -> None:
    data = {
        "api_key": "k1", "apiKey": "k2", "X-API-Key": "k3", "Authorization": "Basic abc",
        "password": "p", "client_secret": "s", "accessToken": "t", "cookie": "c=1",
        "nested": {"headers": {"authorization": "x"}, "list": [{"private_key": "pk"}]},
    }
    out = json.dumps(redact(data))
    for leaked in ("k1", "k2", "k3", "Basic abc", '"p"', '"s"', '"t"', "c=1", '"x"', '"pk"'):
        assert leaked not in out, (leaked, out)
    assert out.count(REDACTED) == 10, out
    print("secret-looking keys: ok (any nesting, any casing/separator)")


def test_known_secret_shapes_are_redacted_inside_text() -> None:
    for name, secret in FAKE_KEYS.items():
        text = f"calling the api with {secret} as the credential, then retrying"
        out = redact_text(text)
        assert secret not in out, (name, out)
        assert "calling the api" in out and "then retrying" in out, f"{name}: surrounding text lost: {out}"
    url = redact_text("postgres://admin:hunter2@db.internal:5432/app")
    assert "hunter2" not in url and "db.internal" in url, url
    pem = redact_text("-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nabc\n-----END RSA PRIVATE KEY----- done")
    assert "MIIEow" not in pem and pem.endswith("done"), pem
    print(f"secret shapes: ok ({len(FAKE_KEYS)} token formats, URL credentials, PEM key)")


def test_harmless_values_are_left_alone() -> None:
    data = {
        "author": "Alice", "max_tokens": 100, "token_count": 5, "enabled": True, "nothing": None,
        "text": "hello world, this is a normal sentence with no secrets in it",
        "path": "/home/user/project/src/main.py", "ratio": 0.5,
    }
    assert redact(data) == data
    print("harmless values: ok (numbers under token-ish keys, 'author', paths and prose untouched)")


def test_base64_blobs_collapse_but_prose_does_not() -> None:
    assert redact("A" * 300) == "<300 chars, base64-like>"
    image = {"type": "image", "data": "iVBORw0KGgo" * 100, "mimeType": "image/png"}
    out = redact(image)
    assert out["data"].startswith("<1100 chars") and out["mimeType"] == "image/png", out
    prose = "word " * 100
    assert redact(prose) == prose
    print("blobs: ok (base64-like data collapses to a size note, spaced prose untouched)")


def test_to_payload_truncates_and_never_raises() -> None:
    text, truncated = to_payload({"k": "v"}, 1000)
    assert text == '{"k":"v"}' and truncated is False, text
    text, truncated = to_payload({"k": "x y " * 5000}, 100)
    assert len(text) == 100 and truncated is True
    assert to_payload({"s": {1, 2}}, 100) == ("<unserializable>", False)
    deep: object = "leaf"
    for _ in range(200):
        deep = {"d": deep}
    text, _ = to_payload(deep, 100000)  # must not blow the recursion limit
    assert "nested too deeply" in text
    print("to_payload: ok (compact, truncation flagged, unserializable and 200-deep input survive)")


json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False, allow_infinity=False) | st.text(),
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=12), inner, max_size=4),
    max_leaves=25,
)
SECRET_KEYS = ["api_key", "apiKey", "X-API-Key", "password", "Authorization", "client_secret",
               "accessToken", "refresh_token", "private-key", "Cookie"]


@settings(max_examples=250, deadline=None)
@given(value=json_values)
def test_property_redact_never_raises_and_stays_serializable(value) -> None:
    json.dumps(redact(value))


@settings(max_examples=250, deadline=None)
@given(
    secret=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=8, max_size=40),
    key=st.sampled_from(SECRET_KEYS),
    around=st.dictionaries(st.text(alphabet="abcdefgh", min_size=1, max_size=6), json_values, max_size=4),
    depth=st.integers(0, 4),
)
def test_property_a_planted_secret_never_survives(secret, key, around, depth) -> None:
    assume(secret not in json.dumps(around))
    value = {key: secret, **around}
    for _ in range(depth):
        value = {"wrapper": [value], "other": 1}
    assert secret not in json.dumps(redact(value))


if __name__ == "__main__":
    test_secret_looking_keys_are_redacted()
    test_known_secret_shapes_are_redacted_inside_text()
    test_harmless_values_are_left_alone()
    test_base64_blobs_collapse_but_prose_does_not()
    test_to_payload_truncates_and_never_raises()
    test_property_redact_never_raises_and_stays_serializable()
    test_property_a_planted_secret_never_survives()
    print("hypothesis: ok (250 + 250 generated cases)")
    print("\nALL CHECKS PASSED -- redaction does what it claims, and no more than it claims.")
