from lilly.core.shortlist import CONTROL_TOOLS, discover
from lilly.domain.labels import Risk
from lilly.domain.tools_registry import ToolSpec


def test_discovery_matches_namespaces_and_descriptions() -> None:
    specs = {
        "spotify.search": ToolSpec(Risk.R0, module="music", doc="Search music services"),
        "browser.find": ToolSpec(Risk.R0, module="browser", doc="Find page elements"),
        "agent.discover": ToolSpec(Risk.R0, doc="Discover capabilities"),
    }

    assert discover(specs, "music") == ["spotify.search"]
    assert discover(specs, "page", namespace="browser") == ["browser.find"]
    assert "agent.discover" in CONTROL_TOOLS
    assert discover(specs, "capabilities") == []
