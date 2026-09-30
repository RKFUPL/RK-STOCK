from decimal import Decimal, InvalidOperation

import requests


SUPPORTED_CURRENCIES = ("INR", "USD", "EUR", "GBP", "AED")


class FxProviderError(RuntimeError):
    pass


class FxProvider:
    """Server-side exchange-rate provider. INR remains the source currency."""

    def __init__(self, base_url="", api_key="", timeout=5):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.timeout = timeout

    @property
    def configured(self):
        return bool(self.base_url)

    def rates(self, base="INR", symbols=None):
        base = str(base or "INR").upper()
        symbols = [str(symbol).upper() for symbol in (symbols or SUPPORTED_CURRENCIES)]
        if base not in SUPPORTED_CURRENCIES or any(symbol not in SUPPORTED_CURRENCIES for symbol in symbols):
            raise FxProviderError("Unsupported currency")
        if base != "INR":
            raise FxProviderError("INR is the only authoritative base currency")
        if not self.configured:
            raise FxProviderError("FX provider is not configured")
        params = {"base": base, "symbols": ",".join(symbols)}
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = requests.get(self.base_url, params=params, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
            rates = payload.get("rates") or {}
            if not isinstance(rates, dict):
                raise FxProviderError("FX provider returned invalid rates")
            return {currency: Decimal(str(rates[currency])) for currency in symbols if currency in rates}
        except (requests.RequestException, ValueError, KeyError, InvalidOperation) as exc:
            raise FxProviderError("FX provider request failed") from exc

    def convert(self, amount, target, rates=None):
        target = str(target or "").upper()
        if target not in SUPPORTED_CURRENCIES:
            raise FxProviderError("Unsupported currency")
        try:
            amount = Decimal(str(amount))
        except InvalidOperation as exc:
            raise FxProviderError("Invalid amount") from exc
        if target == "INR":
            return amount.quantize(Decimal("0.01"))
        rates = rates if rates is not None else self.rates("INR", [target])
        if target not in rates:
            raise FxProviderError("FX provider did not return the requested currency")
        return (amount * Decimal(str(rates[target]))).quantize(Decimal("0.01"))
