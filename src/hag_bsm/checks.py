"""A single configuration check shown to the owner and summarised in the generated prompt."""

from dataclasses import dataclass

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"


@dataclass(frozen=True)
class Check:
    status: str
    title: str
    detail: str = ""
    fix: str = ""

    @property
    def symbol(self) -> str:
        return {OK: "✔", WARN: "⚠", FAIL: "✖", INFO: "ℹ"}[self.status]

    def text(self) -> str:
        out = f"{self.symbol} {self.title}"
        if self.detail:
            out += f": {self.detail}"
        if self.fix:
            out += f" → {self.fix}"
        return out
