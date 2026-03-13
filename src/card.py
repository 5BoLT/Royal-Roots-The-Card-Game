"""
card.py — Card primitives for Royal Roots.

The game uses TWO standard 52-card decks plus FOUR suit-matched Jokers:
  Spade Joker (black), Club Joker (black), Heart Joker (red), Diamond Joker (red).
Total deck: 108 cards.
"""

from __future__ import annotations
from enum import Enum
from typing import Optional
from dataclasses import dataclass


class Suit(Enum):
    SPADES   = "Spades"
    HEARTS   = "Hearts"
    DIAMONDS = "Diamonds"
    CLUBS    = "Clubs"

    @property
    def is_black(self) -> bool:
        return self in (Suit.SPADES, Suit.CLUBS)

    @property
    def symbol(self) -> str:
        return {"Spades": "♠", "Hearts": "♥", "Diamonds": "♦", "Clubs": "♣"}[self.value]


class JokerType(Enum):
    SPADE_JOKER   = "Spade Joker"
    CLUB_JOKER    = "Club Joker"
    HEART_JOKER   = "Heart Joker"
    DIAMOND_JOKER = "Diamond Joker"

    @property
    def is_black(self) -> bool:
        return self in (JokerType.SPADE_JOKER, JokerType.CLUB_JOKER)

    @property
    def suit(self) -> Suit:
        return {
            JokerType.SPADE_JOKER:   Suit.SPADES,
            JokerType.CLUB_JOKER:    Suit.CLUBS,
            JokerType.HEART_JOKER:   Suit.HEARTS,
            JokerType.DIAMOND_JOKER: Suit.DIAMONDS,
        }[self]


# Ordered card values (index = numeric rank 0–12)
CARD_VALUES = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
VALUE_ORDER: dict[str, int] = {v: i for i, v in enumerate(CARD_VALUES)}

EVEN_VALUES      = frozenset({"2", "4", "6", "8", "10"})
FACE_HIGH_VALUES = frozenset({"J", "Q", "K", "A"})


@dataclass(frozen=True)
class Card:
    """Immutable playing card.  Either (value + suit) for regular cards or joker_type for Jokers."""
    value:      Optional[str]       = None   # "2"–"A", None for Jokers
    suit:       Optional[Suit]      = None
    joker_type: Optional[JokerType] = None

    # ------------------------------------------------------------------ props
    @property
    def is_joker(self) -> bool:
        return self.joker_type is not None

    @property
    def is_black_joker(self) -> bool:
        return self.is_joker and self.joker_type.is_black  # type: ignore[union-attr]

    @property
    def is_black(self) -> bool:
        if self.is_joker:
            return self.joker_type.is_black   # type: ignore[union-attr]
        return self.suit is not None and self.suit.is_black

    @property
    def numeric_value(self) -> Optional[int]:
        return None if self.is_joker else VALUE_ORDER.get(self.value or "")

    @property
    def effective_suit(self) -> Optional[Suit]:
        if self.is_joker:
            return self.joker_type.suit       # type: ignore[union-attr]
        return self.suit

    # ------------------------------------------------------------------ display
    def __str__(self) -> str:
        if self.is_joker:
            return self.joker_type.value      # type: ignore[union-attr]
        sym = self.suit.symbol if self.suit else "?"
        return f"{self.value}{sym}"

    def __repr__(self) -> str:
        return str(self)
