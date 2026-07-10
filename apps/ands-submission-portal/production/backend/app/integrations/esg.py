from __future__ import annotations

from typing import Any, Protocol


class EsgAdapter(Protocol):
    mode: str

    def configure(self, config: dict[str, Any]) -> dict[str, Any]: ...

    def test_round_trip(self, config: dict[str, Any]) -> dict[str, Any]: ...

    def submit(self, package_ref: str, config: dict[str, Any]) -> dict[str, Any]: ...


class MockEsgAdapter:
    """Local simulator — same behaviour as the stdlib portal until AS2 is wired."""

    mode = "mock"

    def configure(self, config: dict[str, Any]) -> dict[str, Any]:
        return {"mode": self.mode, "configured": True, "config": config}

    def test_round_trip(self, config: dict[str, Any]) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "success": True,
            "message": "Simulated FDA ESG Test gateway round-trip (not live).",
            "config": config,
        }

    def submit(self, package_ref: str, config: dict[str, Any]) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "state": "SENT",
            "package_ref": package_ref,
            "message": "Simulated submit — wire TestEsgAdapter for real FDA ESG.",
        }


class TestEsgAdapter:
    """Placeholder for FDA ESG NextGen Test gateway (AS2 / WebTrader)."""

    mode = "test"

    def configure(self, config: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(
            "Test ESG adapter: implement AS2 client + FDA Test credentials"
        )

    def test_round_trip(self, config: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(
            "Test ESG adapter: implement mandatory test round-trip per REQ-003"
        )

    def submit(self, package_ref: str, config: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("Test ESG adapter: production submit not enabled")


def get_esg_adapter(mode: str) -> EsgAdapter:
    if mode == "test":
        return TestEsgAdapter()
    return MockEsgAdapter()
