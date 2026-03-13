"""
deck.py — Deck management for Royal Roots.

Builds a double-deck (104 regular cards) plus the four suit-matched Jokers (108 total).
"""

from __future__ import annotations
import random
from typing import List

from .card import Card, Suit, JokerType, CARD_VALUES


def _build_full_deck() -> List[Card]:
    """Return one complete 108-card Royal Roots deck (shuffled)."""
    cards: List[Card] = []

    # Two copies of the standard 52-card deck
    for _ in range(2):
        for suit in Suit:
            for value in CARD_VALUES:
                cards.append(Card(value=value, suit=suit))

    # Four suit-matched Jokers (one per suit)
    for jt in JokerType:
        cards.append(Card(joker_type=jt))

    random.shuffle(cards)
    return cards


class Deck:
    def __init__(self) -> None:
        self._cards: List[Card] = _build_full_deck()
        self.discard_pile: List[Card] = []

    # ------------------------------------------------------------------ props
    @property
    def remaining(self) -> int:
        return len(self._cards)

    def is_empty(self) -> bool:
        return len(self._cards) == 0

    # ------------------------------------------------------------------ ops
    def draw(self) -> Card:
        """Draw the top card; reshuffles discard pile if draw pile is exhausted."""
        if self.is_empty():
            if not self.discard_pile:
                raise RuntimeError("Both draw and discard piles are empty.")
            self._cards = self.discard_pile[:]
            self.discard_pile.clear()
            random.shuffle(self._cards)
            print("[Deck] Draw pile exhausted — reshuffled discard pile.")
        return self._cards.pop()

    def draw_many(self, n: int) -> List[Card]:
        return [self.draw() for _ in range(n)]

    def discard(self, card: Card) -> None:
        self.discard_pile.append(card)

    def discard_many(self, cards: List[Card]) -> None:
        self.discard_pile.extend(cards)

    def draw_from_discard(self) -> Card:
        """Take the top card of the discard pile."""
        if not self.discard_pile:
            raise RuntimeError("Discard pile is empty.")
        return self.discard_pile.pop()

    def peek_discard(self, n: int = 1) -> List[Card]:
        """View the top n cards of the discard pile without removing them."""
        return self.discard_pile[-n:][::-1]
