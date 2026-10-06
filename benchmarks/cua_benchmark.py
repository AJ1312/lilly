"""Small reproducible benchmark for Lilly's CUA contract.

This measures the local grounding/observation contract without controlling a real
desktop. External CUA frameworks can be compared by supplying the same target
cases and reporting success, stale-state rejection, and verification latency.
"""
from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

from lilly.tools.computer_runtime import A11yElement, ComputerRuntime


class BenchmarkBackend:
    async def observe(self, screenshot_path: Path | None) -> tuple[str, str, tuple[A11yElement, ...]]:
        if screenshot_path is not None:
            screenshot_path.write_bytes(b"benchmark-frame")
        return "BenchmarkApp", "Benchmark window", (
            A11yElement("AXButton", "Continue", "", 10, 20, 100, 40),
        )

    async def click(self, x: int, y: int) -> None:
        assert (x, y) == (60, 40)

    async def type_text(self, text: str) -> None:
        return None

    async def press(self, key: str) -> None:
        return None


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="lilly-cua-benchmark-") as folder:
        runtime = ComputerRuntime(Path(folder), backend=BenchmarkBackend())
        started = time.perf_counter()
        frame = await runtime.observe("benchmark")
        fresh = await runtime.click("benchmark", frame.frame_id, "Continue", expected="Continue")
        elapsed_ms = (time.perf_counter() - started) * 1000
        print(f"semantic_observation_and_action_ms={elapsed_ms:.2f}")
        print(f"fresh_frame={fresh.frame_id != frame.frame_id}")
        print("stale_state_rejection=covered_by_tests/unit/test_computer_runtime.py")
        print("comparison_note=external frameworks must beat this contract before adoption")


if __name__ == "__main__":
    asyncio.run(main())
