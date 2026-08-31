"""
Property-based test for ProxySession.record(): for any string at all --
valid JSON-RPC, valid-but-non-dict JSON, or complete garbage -- it must
never raise. This is the general form of the non-dict-JSON bug fixed in
tests/test_record_non_dict_json.py, generated rather than enumerated by
hand.

Usage:
    .venv\\Scripts\\python.exe tests\\test_record_fuzz.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hypothesis import given, settings, strategies as st  # noqa: E402

from greenlight.proxy import ProxySession  # noqa: E402

# Mix of realistic-shaped JSON-RPC text and pure noise -- both matter.
# A real server's output can be either.
ARBITRARY_TEXT = st.text(min_size=0, max_size=200)
JSON_LIKE = st.recursive(
    st.none() | st.booleans() | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(max_size=20),
    lambda children: st.lists(children, max_size=5) | st.dictionaries(st.text(max_size=10), children, max_size=5),
    max_leaves=10,
)


@given(st.one_of(ARBITRARY_TEXT, JSON_LIKE.map(lambda v: __import__("json").dumps(v))))
@settings(max_examples=300)
def check_record_never_raises(line: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        session = ProxySession(Path(tmp) / "test.jsonl")
        try:
            session.record("client->server", line)
        finally:
            session.close()


if __name__ == "__main__":
    check_record_never_raises()
    print("hypothesis: record() never raised across 300 generated inputs "
          "(arbitrary text + arbitrary JSON shapes)")
