from importlib.metadata import PackageNotFoundError, version

try:
    # Single source of truth: whatever was actually installed, per pip's
    # own metadata. Was previously a hardcoded string here that drifted
    # out of sync with pyproject.toml starting at the very first version
    # bump (0.2.0) and nobody noticed until 0.2.1's release verification
    # caught greenlight.__version__ still reporting 0.1.0 from a freshly
    # installed 0.2.1 wheel. Deriving it removes the possibility of that
    # happening again, rather than just fixing the string this once.
    __version__ = version("greenlight-mcp")
except PackageNotFoundError:
    # running from source with no install at all (not even editable)
    __version__ = "0.0.0+unknown"
