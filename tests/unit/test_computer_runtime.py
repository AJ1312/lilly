from pathlib import Path

import pytest

from lilly.domain.errors import ToolError
from lilly.tools.computer_runtime import A11yElement, ComputerRuntime


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.elements = [A11yElement("button", "Continue", x=10, y=20, width=20, height=10)]

    async def observe(self, screenshot_path: Path | None):
        self.calls.append(("observe", screenshot_path))
        return "Demo", "Window", self.elements

    async def click(self, x: int, y: int) -> None:
        self.calls.append(("click", (x, y)))

    async def type_text(self, text: str) -> None:
        self.calls.append(("type", text))

    async def press(self, key: str) -> None:
        self.calls.append(("press", key))

    async def move(self, x: int, y: int) -> None:
        self.calls.append(("move", (x, y)))

    async def scroll(self, amount: int) -> None:
        self.calls.append(("scroll", amount))

    async def drag(self, start_x: int, start_y: int, end_x: int, end_y: int) -> None:
        self.calls.append(("drag", (start_x, start_y, end_x, end_y)))


@pytest.mark.asyncio
async def test_action_requires_fresh_frame_and_returns_a_new_frame(tmp_path: Path) -> None:
    backend = FakeBackend()
    runtime = ComputerRuntime(tmp_path, backend=backend)
    first = await runtime.observe("task")
    second = await runtime.click("task", first.frame_id, "Continue", expected="Demo")

    assert second.frame_id != first.frame_id
    assert ("click", (20, 25)) in backend.calls

    with pytest.raises(ToolError, match="unknown|observe"):
        await runtime.press("task", first.frame_id, "Enter")


@pytest.mark.asyncio
async def test_semantic_grounding_rejects_ambiguous_targets(tmp_path: Path) -> None:
    backend = FakeBackend()
    backend.elements.append(A11yElement("button", "Continue later", x=40, y=20, width=20, height=10))
    runtime = ComputerRuntime(tmp_path, backend=backend)
    frame = await runtime.observe("task")

    with pytest.raises(ToolError, match="ambiguous"):
        await runtime.click("task", frame.frame_id, "Continue")


@pytest.mark.asyncio
async def test_verification_failure_returns_an_error_after_fresh_observation(tmp_path: Path) -> None:
    runtime = ComputerRuntime(tmp_path, backend=FakeBackend())
    frame = await runtime.observe("task")

    with pytest.raises(ToolError, match="verification"):
        await runtime.click("task", frame.frame_id, "Continue", expected="Missing")
    assert runtime.is_ambiguous("task")
    runtime.confirm_recovery("task")
    assert not runtime.is_ambiguous("task")


@pytest.mark.asyncio
async def test_visual_grounding_is_used_before_coordinate_fallback(tmp_path: Path) -> None:
    async def ground(_frame: object, target: str, _task_id: str) -> tuple[int, int] | None:
        return (70, 80) if target == "icon" else None

    backend = FakeBackend()
    runtime = ComputerRuntime(tmp_path, backend=backend, vision_grounder=ground)
    frame = await runtime.observe("task")
    await runtime.click("task", frame.frame_id, "icon")
    assert ("click", (70, 80)) in backend.calls


@pytest.mark.asyncio
async def test_frames_survive_runtime_restart_and_render_environment(tmp_path: Path) -> None:
    class Devbox:
        async def status(self) -> dict[str, str]:
            return {"state": "running"}

    first = ComputerRuntime(tmp_path, backend=FakeBackend(), devbox=Devbox())
    frame = await first.observe("task")
    restored = ComputerRuntime(tmp_path, backend=FakeBackend())
    assert restored.current(frame.frame_id, "task").frame_id == frame.frame_id
    assert '"frame_id"' in restored.render(frame)
    assert frame.devbox == {"state": "running"}


@pytest.mark.asyncio
async def test_pointer_scroll_and_drag_follow_the_same_fresh_frame_contract(tmp_path: Path) -> None:
    backend = FakeBackend()
    backend.elements.append(A11yElement("button", "Drop", x=100, y=20, width=20, height=10))
    runtime = ComputerRuntime(tmp_path, backend=backend)
    frame = await runtime.observe("task")
    frame = await runtime.move("task", frame.frame_id, "Continue")
    frame = await runtime.scroll("task", frame.frame_id, -2)
    await runtime.drag("task", frame.frame_id, "Continue", "Drop")
    assert ("move", (20, 25)) in backend.calls
    assert ("scroll", -2) in backend.calls
    assert ("drag", (20, 25, 110, 25)) in backend.calls


@pytest.mark.asyncio
async def test_typing_press_and_coordinate_fallback_are_observed(tmp_path: Path) -> None:
    backend = FakeBackend()
    runtime = ComputerRuntime(tmp_path, backend=backend)
    frame = await runtime.observe("task")
    frame = await runtime.type_text("task", frame.frame_id, "@x=70,y=80", "hello", expected="Continue")
    await runtime.press("task", frame.frame_id, "Enter", expected="Demo")
    assert ("click", (70, 80)) in backend.calls
    assert ("type", "hello") in backend.calls
    assert ("press", "Enter") in backend.calls


@pytest.mark.asyncio
async def test_unknown_target_and_unbounded_accessibility_target_are_rejected(tmp_path: Path) -> None:
    backend = FakeBackend()
    backend.elements = [A11yElement("button", "NoBounds")]
    runtime = ComputerRuntime(tmp_path, backend=backend)
    frame = await runtime.observe("task")
    with pytest.raises(ToolError, match="bounds"):
        await runtime.click("task", frame.frame_id, "NoBounds")
    with pytest.raises(ToolError, match="not found"):
        await runtime.click("task", frame.frame_id, "Missing")


@pytest.mark.asyncio
async def test_dom_provider_is_included_in_fresh_frames(tmp_path: Path) -> None:
    async def dom(task_id: str) -> dict[str, str]:
        return {"task": task_id, "url": "https://example.test"}

    runtime = ComputerRuntime(tmp_path, backend=FakeBackend(), dom_provider=dom)
    frame = await runtime.observe("task")
    assert frame.dom == {"task": "task", "url": "https://example.test"}
