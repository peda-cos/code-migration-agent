"""Coverage preservation gate."""

from __future__ import annotations

from .models import GateResult


class CoverageGate:
    def __init__(self, tolerance_pp: float = 2.0) -> None:
        self.tolerance_pp = tolerance_pp

    def check(self, base: float | None, final: float | None) -> GateResult:
        if base is None or final is None:
            return GateResult(
                status="unmeasured",
                delta=None,
                reason="coverage baseline or final measurement unavailable",
            )
        delta = final - base
        if delta < -self.tolerance_pp:
            return GateResult(
                status="regressed",
                delta=delta,
                reason=(
                    f"coverage dropped {abs(delta):.2f} pp "
                    f"({base:.2f}% -> {final:.2f}%), beyond the "
                    f"{self.tolerance_pp:.1f} pp tolerance"
                ),
            )
        return GateResult(
            status="passed",
            delta=delta,
            reason=f"coverage delta {delta:+.2f} pp within tolerance",
        )
