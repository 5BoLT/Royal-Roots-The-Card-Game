"""
player.py — Player data for Royal Roots.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List

from .card import Card


@dataclass
class Player:
    name: str
    hand: List[Card] = field(default_factory=list)
    score: int = 0

    def show_hand(self) -> str:
        if not self.hand:
            return "(empty hand)"
        return "  " + "  ".join(f"[{i}] {c}" for i, c in enumerate(self.hand))

    def remove_cards(self, indices: List[int]) -> List[Card]:
        """Remove cards at given indices (sorted descending) and return them."""
        removed = []
        for i in sorted(indices, reverse=True):
            removed.append(self.hand.pop(i))
        return removed
