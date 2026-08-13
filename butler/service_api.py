"""Late-bound proxy onto :mod:`butler_service`."""

from __future__ import annotations

from typing import Any


class _ApiProxy:
    def __getattr__(self, name: str) -> Any:
        import butler_service

        return getattr(butler_service, name)

    def __setattr__(self, name: str, value: Any) -> None:
        import butler_service

        setattr(butler_service, name, value)

    def __delattr__(self, name: str) -> None:
        import butler_service

        delattr(butler_service, name)


api = _ApiProxy()
