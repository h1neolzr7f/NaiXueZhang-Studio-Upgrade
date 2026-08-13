"""Late-bound proxy onto :mod:`nai_api`.

Implementation modules must look up patchable names and mutable state through
``api`` so ``patch.object(nai_api, ...)`` and ``nai_api._TOKEN_CURSOR = 0``
keep working after the package split.
"""

from __future__ import annotations

from typing import Any


class _ApiProxy:
    def __getattr__(self, name: str) -> Any:
        import nai_api

        return getattr(nai_api, name)

    def __setattr__(self, name: str, value: Any) -> None:
        import nai_api

        setattr(nai_api, name, value)

    def __delattr__(self, name: str) -> None:
        import nai_api

        delattr(nai_api, name)


api = _ApiProxy()
