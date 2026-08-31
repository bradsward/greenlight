"""
json.loads() succeeds for any valid JSON value, not just objects -- a
bare "null", "42", "true", or "[1,2,3]" is valid JSON. record() used to
assume msg.get(...) would work, which crashes with AttributeError on
anything that isn't a dict.

Reproduced for real first: sent a literal `null` POST body through the
live HTTP proxy and it took down the request handler with an unhandled
exception (the stdio side's caller happens to swallow exceptions from
record(), so there it silently dropped the entry instead of crashing --
neither is correct). This test is the fast, isolated version of that
reproduction: no network, no subprocess, just record() directly against
every non-dict JSON shape.

Usage:
    .venv\\Scripts\\python.exe tests\\test_record_non_dict_json.py
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from greenlight.proxy import ProxySession  # noqa: E402

NON_DICT_JSON_LINES = ["null", "42", "true", "false", '"a bare string"', "[1, 2, 3]", "3.14"]


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "test.jsonl"
        session = ProxySession(log_path)

        for line in NON_DICT_JSON_LINES:
            # the actual property under test: this must not raise
            session.record("client->server", line)
        session.close()

        entries = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
        assert len(entries) == len(NON_DICT_JSON_LINES), (
            f"expected {len(NON_DICT_JSON_LINES)} entries, got {len(entries)}"
        )
        for entry, original in zip(entries, NON_DICT_JSON_LINES):
            assert entry["parsed"] is False, f"expected parsed=False for {original!r}, got {entry}"
            assert entry["raw"] == original, f"expected raw={original!r}, got {entry['raw']!r}"

    print(f"all {len(NON_DICT_JSON_LINES)} non-dict JSON shapes handled without crashing: "
          f"{NON_DICT_JSON_LINES}")


if __name__ == "__main__":
    main()
