"""Compatibility import for integrations written before Lilly 2.0.

There is one inference implementation now: :class:`ModelBroker`. New code must
import it directly; this name remains temporarily so installed integrations and
the historical rate-limit reproduction can be run during the migration.
"""
from __future__ import annotations

from lilly.providers.model_broker import ModelBroker

ModelRouter = ModelBroker

__all__ = ["ModelRouter"]
