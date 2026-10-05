"""Provider catalog loader and validator."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from lilly.domain.caps import Cap
from lilly.domain.errors import ConfigurationError
from lilly.domain.labels import Label
from lilly.domain.settings import ModelSpec, Settings

CATALOG_PATH = Path(__file__).resolve().parent / "catalog.json"

Confidence = Literal["documented", "observed", "unknown"]
ToolCallingSupport = Literal["native", "protocol", "none", "unknown"]


@dataclass(frozen=True, slots=True)
class FreeTier:
    rpm: int | None = None
    rpd: int | None = None
    tpm: int | None = None
    tpd: int | None = None
    notes: str = ""


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    id: str
    name: str
    provider: str
    model_id: str
    base_url: str
    openai_compatible: bool
    starter: bool = False
    enabled: bool = True
    local: bool = False
    lane: int = 1
    tags: tuple[str, ...] = ()
    caps: tuple[str, ...] = ()
    key_ref: str | None = None
    free_tier: FreeTier = field(default_factory=FreeTier)
    tools: ToolCallingSupport = "unknown"
    max_context_tokens: int | None = None
    source_url: str = ""
    verified_on: str | None = None
    confidence: Confidence = "unknown"


def _parse_entry(d: dict[str, Any]) -> CatalogEntry:
    entry_id = str(d.get("id", ""))
    source_url = str(d.get("source_url", "")).strip()
    if not source_url:
        raise ConfigurationError(f"catalog entry {entry_id!r} is missing required source_url")

    confidence = d.get("confidence", "unknown")
    if confidence not in ("documented", "observed", "unknown"):
        raise ConfigurationError(f"catalog entry {entry_id!r} has invalid confidence {confidence!r}")

    ft_dict = d.get("free_tier", {})
    ft = FreeTier(
        rpm=ft_dict.get("rpm"),
        rpd=ft_dict.get("rpd"),
        tpm=ft_dict.get("tpm"),
        tpd=ft_dict.get("tpd"),
        notes=str(ft_dict.get("notes", "")),
    )

    caps = tuple(str(c) for c in d.get("caps", ()))
    tags = tuple(str(t) for t in d.get("tags", ()))

    tools_val = d.get("tools", "unknown")
    if tools_val not in ("native", "protocol", "none", "unknown"):
        tools_val = "unknown"

    return CatalogEntry(
        id=entry_id,
        name=str(d.get("name", entry_id)),
        provider=str(d.get("provider", "")),
        model_id=str(d.get("model_id", "")),
        base_url=str(d.get("base_url", "")),
        openai_compatible=bool(d.get("openai_compatible", True)),
        starter=bool(d.get("starter", False)),
        enabled=bool(d.get("enabled", True)),
        local=bool(d.get("local", False)),
        lane=int(d.get("lane", 1)),
        tags=tags,
        caps=caps,
        key_ref=d.get("key_ref"),
        free_tier=ft,
        tools=tools_val,
        max_context_tokens=d.get("max_context_tokens"),
        source_url=source_url,
        verified_on=d.get("verified_on"),
        confidence=confidence,
    )


def load_catalog(path: Path | None = None) -> list[CatalogEntry]:
    """Load and validate all entries from catalog.json."""
    target = path or CATALOG_PATH
    if not target.exists():
        raise ConfigurationError(f"catalog file not found: {target}")
    with open(target, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    if not isinstance(raw, list):
        raise ConfigurationError("catalog.json must contain a list of model entries")
    return [_parse_entry(item) for item in raw]


def default_settings_from_catalog(catalog: list[CatalogEntry] | None = None) -> Settings:
    """Generate default Settings from catalog entries with starter: true."""
    entries = catalog if catalog is not None else load_catalog()
    models: list[ModelSpec] = []
    for e in entries:
        if not e.starter:
            continue
        caps = Cap.NONE
        for c in e.caps:
            try:
                caps |= Cap[c]
            except KeyError:
                pass
        max_lbl = Label.PERSONAL if e.local else Label.PUBLIC
        models.append(
            ModelSpec(
                name=e.name,
                provider=e.provider,
                model_id=e.model_id,
                local=e.local,
                enabled=e.enabled,
                caps=caps,
                max_label=max_lbl,
                rpm=e.free_tier.rpm,
                rpd=e.free_tier.rpd,
                tpm=e.free_tier.tpm,
                tpd=e.free_tier.tpd,
                key_ref=e.key_ref,
                trains=not e.local,
                base_url=e.base_url if e.local else None,
                quick="quick" in e.tags,
                lane=e.lane,
                tags=e.tags,
                tools=e.tools,
                max_context_tokens=e.max_context_tokens,
            )
        )
    return Settings(models=tuple(models))
