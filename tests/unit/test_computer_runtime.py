import sys
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


@pytest.mark.asyncio
async def test_frame_callback_emits_after_observation_and_action(tmp_path: Path) -> None:
    emitted: list[tuple[str, str]] = []
    runtime = ComputerRuntime(
        tmp_path, backend=FakeBackend(), on_frame=lambda task, frame: emitted.append((task, frame.frame_id))
    )
    frame = await runtime.observe("task")
    await runtime.click("task", frame.frame_id, "Continue")
    assert [task for task, _ in emitted] == ["task", "task"]
    assert emitted[0][1] != emitted[1][1]


@pytest.mark.asyncio
async def test_continuous_monitor_starts_and_stops_with_task_lifecycle(tmp_path: Path) -> None:
    runtime = ComputerRuntime(tmp_path, backend=FakeBackend(), continuous=True)
    await runtime.observe("task")
    assert "task" in runtime._monitors
    await runtime.stop_monitor("task")
    assert "task" not in runtime._monitors


@pytest.mark.asyncio
async def test_flexible_coordinate_targeting(tmp_path: Path) -> None:
    backend = FakeBackend()
    runtime = ComputerRuntime(tmp_path, backend=backend)
    frame = await runtime.observe("task")

    for coord_str, expected in [
        ("@x=120, y=240", (120, 240)),
        ("x=300, y=400", (300, 400)),
        ("500, 600", (500, 600)),
        ("(750, 850)", (750, 850)),
        ("x: 100, y: 200", (100, 200)),
        ("900,1000", (900, 1000)),
    ]:
        fresh = await runtime.click("task", frame.frame_id, coord_str)
        assert ("click", expected) in backend.calls
        frame = fresh


@pytest.mark.asyncio
async def test_agent_s_grounding_role_prefix(tmp_path: Path) -> None:
    backend = FakeBackend()
    backend.elements = [
        A11yElement("AXStaticText", "Continue", x=10, y=10, width=50, height=20),
        A11yElement("AXButton", "Continue", x=100, y=100, width=80, height=30),
    ]
    runtime = ComputerRuntime(tmp_path, backend=backend)
    frame = await runtime.observe("task")
    # Role-prefixed target selects the button
    fresh = await runtime.click("task", frame.frame_id, "button:Continue")
    assert ("click", (140, 115)) in backend.calls
    assert fresh.frame_id != frame.frame_id


@pytest.mark.asyncio
async def test_agent_s_grounding_interactive_disambiguation(tmp_path: Path) -> None:
    backend = FakeBackend()
    backend.elements = [
        A11yElement("AXWindow", "Save Document Dialog", x=0, y=0, width=500, height=400),
        A11yElement("AXGroup", "Save Options", x=50, y=50, width=200, height=100),
        A11yElement("AXButton", "Save", x=300, y=350, width=60, height=25),
    ]
    runtime = ComputerRuntime(tmp_path, backend=backend)
    frame = await runtime.observe("task")
    # "Save" matches AXWindow, AXGroup, and AXButton, but AXButton is the only interactive control
    fresh = await runtime.click("task", frame.frame_id, "Save")
    assert ("click", (330, 362)) in backend.calls
    assert fresh.frame_id != frame.frame_id


@pytest.mark.asyncio
async def test_failsafe_emergency_stop_triggered(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from lilly.tools import computer_runtime

    class FakePoint:
        x = 2
        y = 3

    class FakeQuartz:
        @staticmethod
        def CGEventCreate(_: object) -> object:
            return object()

        @staticmethod
        def CGEventGetLocation(_: object) -> FakePoint:
            return FakePoint()

    monkeypatch.setattr(computer_runtime, "Quartz", FakeQuartz, raising=False)
    monkeypatch.setattr(computer_runtime, "_HAS_PYOBJC", True)

    with pytest.raises(ToolError, match="Emergency stop triggered: cursor moved to failsafe corner"):
        computer_runtime.check_emergency_stop()


@pytest.mark.asyncio
async def test_pyautogui_failsafe_exception_wrapped_in_toolerror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lilly.tools.computer_runtime import PyAutoGUIComputerBackend

    class FakePyAutoGUI:
        class FailSafeException(Exception):
            pass

        @staticmethod
        def click(x: int, y: int) -> None:
            raise FakePyAutoGUI.FailSafeException("cursor at 0, 0")

    monkeypatch.setattr("lilly.tools.computer_runtime._pyautogui_mod", lambda: FakePyAutoGUI)
    backend = PyAutoGUIComputerBackend()
    with pytest.raises(ToolError, match="Emergency stop triggered"):
        await backend.click(10, 10)


@pytest.mark.asyncio
async def test_screenshot_missing_raises_toolerror_instead_of_swallowing(tmp_path: Path) -> None:
    from lilly.tools.computer_runtime import PyAutoGUIComputerBackend

    backend = PyAutoGUIComputerBackend()
    backend._screencapture = None  # disable screencapture to test error path
    non_existent = tmp_path / "not_created.png"

    with pytest.raises(ToolError, match="Desktop screenshot observation failed"):
        await backend.observe(non_existent)


@pytest.mark.asyncio
async def test_mac_backend_screen_permission_missing_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from lilly.tools import computer_runtime

    monkeypatch.setattr(computer_runtime.sys, "platform", "darwin")
    monkeypatch.setattr(computer_runtime, "_HAS_PYOBJC", True)
    monkeypatch.setattr(computer_runtime, "check_macos_screen_capture_permission", lambda: False)
    backend = computer_runtime.MacNativeComputerBackend()
    with pytest.raises(ToolError, match="Screen Recording permission is missing"):
        await backend.observe(tmp_path / "shot.png")


@pytest.mark.asyncio
async def test_mac_backend_ax_permission_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from lilly.tools import computer_runtime

    monkeypatch.setattr(computer_runtime.sys, "platform", "darwin")
    monkeypatch.setattr(computer_runtime, "_HAS_PYOBJC", True)
    monkeypatch.setattr(computer_runtime, "check_macos_accessibility_permission", lambda: False)
    backend = computer_runtime.MacNativeComputerBackend()
    with pytest.raises(ToolError, match="Accessibility permission is missing"):
        await backend.observe(None)


@pytest.mark.asyncio
async def test_mac_backend_input_actions_with_mock_quartz(monkeypatch: pytest.MonkeyPatch) -> None:
    from lilly.tools import computer_runtime

    events_created = []

    class MockQuartz:
        kCGEventMouseMoved = 5
        kCGEventLeftMouseDown = 1
        kCGEventLeftMouseUp = 2
        kCGEventLeftMouseDragged = 6
        kCGEventScrollWheel = 22
        kCGScrollEventUnitLine = 0
        kCGHIDEventTap = 0
        kCGMouseButtonLeft = 0
        kCGEventFlagMaskCommand = 0x100000

        @staticmethod
        def CGPoint(x, y):
            return (x, y)

        @staticmethod
        def CGEventCreate(_):
            class Pt:
                x = 500
                y = 500

            return Pt()

        @staticmethod
        def CGEventGetLocation(ev):
            return ev

        @staticmethod
        def CGEventCreateMouseEvent(source, event_type, point, mouse_button):
            events_created.append(("mouse", event_type, point))
            return object()

        @staticmethod
        def CGEventCreateScrollWheelEvent(source, units, count, amount):
            events_created.append(("scroll", amount))
            return object()

        @staticmethod
        def CGEventCreateKeyboardEvent(source, keycode, down):
            events_created.append(("key", keycode, down))
            return object()

        @staticmethod
        def CGEventSetFlags(ev, flags):
            pass

        @staticmethod
        def CGEventPost(tap, ev):
            pass

        @staticmethod
        def CGEventKeyboardSetUnicodeString(ev, length, s):
            events_created.append(("unicode", s))

    monkeypatch.setattr(computer_runtime, "Quartz", MockQuartz, raising=False)
    monkeypatch.setattr(computer_runtime, "_HAS_PYOBJC", True)

    backend = computer_runtime.MacNativeComputerBackend()
    await backend.move(100, 200)
    await backend.click(100, 200)
    await backend.type_text("hello")
    await backend.press("enter")
    await backend.press("cmd+c")
    await backend.scroll(5)
    await backend.drag(10, 10, 50, 50)

    assert any(e[0] == "mouse" for e in events_created)
    assert any(e[0] == "scroll" for e in events_created)
    assert any(e[0] == "unicode" and e[1] == "hello" for e in events_created)


def test_default_computer_backend_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    from lilly.tools import computer_runtime

    monkeypatch.setattr(sys, "platform", "linux")
    backend_linux = computer_runtime.default_computer_backend()
    assert isinstance(backend_linux, computer_runtime.PyAutoGUIComputerBackend)

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(computer_runtime, "_HAS_PYOBJC", False)
    backend_no_objc = computer_runtime.default_computer_backend()
    assert isinstance(backend_no_objc, computer_runtime.PyAutoGUIComputerBackend)


@pytest.mark.asyncio
async def test_runtime_actions_without_frame_id(tmp_path: Path) -> None:
    backend = FakeBackend()
    backend.elements.append(A11yElement("button", "Drop", x=100, y=20, width=20, height=10))
    runtime = ComputerRuntime(tmp_path, backend=backend)

    # All actions can run seamlessly without passing frame_id
    await runtime.click("task", "Continue")
    assert ("click", (20, 25)) in backend.calls

    await runtime.type_text("task", "search text")
    assert ("type", "search text") in backend.calls

    await runtime.press("task", "return")
    assert ("press", "return") in backend.calls

    await runtime.move("task", "Continue")
    assert ("move", (20, 25)) in backend.calls

    await runtime.scroll("task", -5)
    assert ("scroll", -5) in backend.calls

    f6 = await runtime.drag("task", "Continue", "Drop")
    assert ("drag", (20, 25, 110, 25)) in backend.calls

    # Lookup tests
    assert runtime.current("task").frame_id == f6.frame_id
    assert runtime.current(f6.frame_id).frame_id == f6.frame_id
    assert runtime.current(f6.frame_id, "task").frame_id == f6.frame_id

    await runtime.close()


@pytest.mark.asyncio
async def test_pyautogui_backend_methods(monkeypatch: pytest.MonkeyPatch) -> None:
    from lilly.tools.computer_runtime import PyAutoGUIComputerBackend

    actions: list[tuple[str, object]] = []

    class MockPyAuto:
        @staticmethod
        def click(x: int, y: int) -> None:
            actions.append(("click", (x, y)))

        @staticmethod
        def moveTo(x: int, y: int) -> None:
            actions.append(("move", (x, y)))

        @staticmethod
        def dragTo(x: int, y: int, duration: float, **kwargs: object) -> None:
            actions.append(("drag", (x, y)))

        @staticmethod
        def scroll(amount: int) -> None:
            actions.append(("scroll", amount))

        @staticmethod
        def write(text: str, interval: float) -> None:
            actions.append(("write", text))

        @staticmethod
        def press(key: str) -> None:
            actions.append(("press", key))

    monkeypatch.setattr("lilly.tools.computer_runtime._pyautogui_mod", lambda: MockPyAuto)

    backend = PyAutoGUIComputerBackend()
    await backend.click(10, 20)
    await backend.move(30, 40)
    await backend.drag(10, 20, 50, 60)
    await backend.scroll(3)
    await backend.type_text("test")
    await backend.press("enter")

    assert ("click", (10, 20)) in actions
    assert ("move", (30, 40)) in actions
    assert ("drag", (50, 60)) in actions
    assert ("scroll", 300) in actions
    assert ("write", "test") in actions
    assert ("press", "enter") in actions

