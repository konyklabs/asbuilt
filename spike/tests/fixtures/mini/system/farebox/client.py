"""A tiny invented client, added only to exercise check_consistency's
dotted-symbol code-carrier check (a "ClassName.member" location)."""


class PricingClient:
    def fetch_rate(self) -> float:
        return 0.15
