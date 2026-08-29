# Greenlight - Day 8 notes

## Closed the gap between source and published package

Three real fixes from the last session (unreachable target, SSE CRLF
boundary, concurrent write lock) existed only in source, not in the
0.2.0 release on PyPI. Bumped to 0.2.1, rebuilt, and before calling it
done, actually installed the built wheel into a throwaway venv and
checked `greenlight.__version__` against it.

It said 0.1.0.

## The version string bug

`__init__.py` had `__version__ = "0.1.0"` hardcoded since day one.
Every version bump since (0.2.0, then 0.2.1) updated `pyproject.toml`
but not this file, because nothing ever pointed at it and nothing ever
checked it. It's the same category of gap as the CRLF chunk-boundary
bug: fine on the happy path, wrong the moment anything actually
depended on the value being correct. Fixed by deriving it from
installed package metadata (`importlib.metadata.version`) instead of
maintaining a second hand-written copy of a fact that already exists
in `pyproject.toml`. Can't drift again because there's nothing left to
keep in sync.

Found this specifically because "did I actually verify the built
artifact, not just that the build command exited zero" is now a
standing habit from the last several releases, not a one-off check. It
paid off again.

## Also added: --version / -V

Noticed while fixing the above that the CLI never had this at all --
about as standard a convention as a CLI has, and it was just missing.
Small, but it's the kind of gap that's invisible until someone goes
looking for it, same as the CI badge and the demo GIF placement earlier.

## Three patch releases in one sitting, not one

0.2.1 (the three bug fixes) got tagged and released before the
`--version` idea came up. Rather than quietly editing an already-tagged
release, bumped again to 0.2.2 for it. A tag should mean what it says
it means.

## Status

v0.2.2 tagged and released on GitHub, CI green on both platforms at
every step along the way. Not yet on PyPI -- needs the maintainer's
token from their own terminal, same constraint as every release before
this one. Built, twine-checked, and wheel-verified either way, so
publishing it is one command whenever that happens.
