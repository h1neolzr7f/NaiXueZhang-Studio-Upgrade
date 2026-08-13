"""Provider errors whose billing/retry outcome is known."""

from __future__ import annotations


class GenerationProviderError(ValueError):
    """A provider response whose billing/retry outcome is known."""

    def __init__(
        self,
        message: str,
        *,
        retry_safe: bool,
        billing_uncertain: bool,
        wait: float = 0.0,
        request_attempted: bool | None = None,
        error_code: str = "",
    ) -> None:
        super().__init__(message)
        self.retry_safe = bool(retry_safe)
        self.billing_uncertain = bool(billing_uncertain)
        self.wait = max(0.0, float(wait or 0.0))
        if request_attempted is None:
            self.request_attempted = bool(billing_uncertain)
        else:
            self.request_attempted = bool(request_attempted)
        self.error_code = str(error_code or "")
