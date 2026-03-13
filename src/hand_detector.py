"""
hand_detector.py — Hand detection and point calculation for Royal Roots.

Priority order (highest → lowest) ensures a hand is assigned to the best match.

Point table
-----------
Hand                Points      Notes
----                ------      -----
Royal Dead Man      1000        8+8+A+A+Black Joker, same black suit (double-deck pair)
Royal Flush         500         10-J-Q-K-A same suit, no Jokers
Royal Joker House   280         2 Aces + 3 Jokers
Joker Cascade (4x)  300         All 4 Jokers
Dead Man's Hand     300         8♠+8♣+A♠+A♣+(Spade or Club Joker)
Roots               75          J-Q-K-A-Joker, any suits
Royal Roots         120         J-Q-K-A-Joker, J/Q/K/A same suit
Joker House         100         3 Aces + 2 Jokers
All-Even            50          2-4-6-8-10 (one of each, any suits)
Cascade House       40          44499 or 44999
Straight Flush      60(+3)      5+ sequential, same suit  | +0 per ext (base 60)
Straight            20(+3)      5+ sequential, any suit   | +2 per card beyond 5
Flush               15(+3)      5+ same suit              | +3 first ext, +1 each after
ROOT OUT!           25 / -10    Called bet: +25 if valid hand shown, -10 if not

(+3) = partner earns +3 bonus points when the hand is played.
"""

from __future__ import annotations
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from collections import Counter, defaultdict

from .card import Card, Suit, JokerType, VALUE_ORDER, CARD_VALUES


class HandType(Enum):
    ROYAL_DEAD_MAN    = auto()   # 1000 pts — game over
    ROYAL_FLUSH       = auto()   # 500 pts  — instant win, round ends
    JOKER_CASCADE     = auto()   # 300 pts
    DEAD_MANS_HAND    = auto()   # 300 pts
    ROYAL_JOKER_HOUSE = auto()   # 280 pts
    ROYAL_ROOTS       = auto()   # 120 pts
    JOKER_HOUSE       = auto()   # 100 pts
    ROOTS             = auto()   # 75 pts
    ALL_EVEN          = auto()   # 50 pts
    CASCADE_HOUSE     = auto()   # 40 pts
    STRAIGHT_FLUSH    = auto()   # 60 pts base
    STRAIGHT          = auto()   # 20 pts base
    FLUSH             = auto()   # 15 pts base
    NONE              = auto()   # no valid hand


@dataclass
class HandResult:
    hand_type: HandType = HandType.NONE
    base_points: int = 0
    partner_bonus: int = 0          # the (+3) awarded to the partner
    card_count: int = 0             # relevant for Straight / Flush extensions
    matched_suit: Optional[Suit] = None    # for Flush / Royal Flush / Royal Roots
    description: str = ""

    @property
    def is_valid(self) -> bool:
        return self.hand_type is not HandType.NONE


# ─────────────────────────────────────────── helpers ──────────────────────────

def _jokers(cards: List[Card]) -> List[Card]:
    return [c for c in cards if c.is_joker]

def _regulars(cards: List[Card]) -> List[Card]:
    return [c for c in cards if not c.is_joker]

def _sorted_values(cards: List[Card]) -> List[int]:
    return sorted(c.numeric_value for c in cards if c.numeric_value is not None)


def _longest_run(values: List[int]) -> int:
    """Return length of the longest consecutive run in a sorted list (dupes ok)."""
    unique = sorted(set(values))
    if not unique:
        return 0
    best, run = 1, 1
    for i in range(1, len(unique)):
        if unique[i] == unique[i - 1] + 1:
            run += 1
            best = max(best, run)
        else:
            run = 1
    return best


# ─────────────────────────────────── point formulas ───────────────────────────

def straight_points(card_count: int) -> int:
    """20 base; +2 for each card beyond 5.  (6 cards → 22, 7 → 24, …)"""
    base = 20
    if card_count <= 5:
        return base
    return base + (card_count - 5) * 2


def flush_points(card_count: int) -> int:
    """15 base; 6-card flush → +3, then +1 per additional card.
    (5 → 15, 6 → 18, 7 → 19, 8 → 20, …)"""
    base = 15
    if card_count <= 5:
        return base
    return base + 3 + (card_count - 6)


def straight_flush_points(_card_count: int) -> int:
    """60 base — no per-card extension in the rules."""
    return 60


# ─────────────────────────────────── detectors ────────────────────────────────

def _check_royal_dead_man(cards: List[Card]) -> Optional[HandResult]:
    """8+8+A+A+Black Joker where all four regular cards share the same black suit."""
    j = _jokers(cards)
    r = _regulars(cards)
    if len(j) != 1 or not j[0].is_black_joker or len(r) != 4:
        return None
    joker_suit = j[0].joker_type.suit  # type: ignore[union-attr]
    eights = [c for c in r if c.value == "8" and c.suit == joker_suit]
    aces   = [c for c in r if c.value == "A" and c.suit == joker_suit]
    if len(eights) == 2 and len(aces) == 2:
        return HandResult(
            hand_type=HandType.ROYAL_DEAD_MAN,
            base_points=1000,
            partner_bonus=0,
            description="ROYAL DEAD MAN — GAME OVER!"
        )
    return None


def _check_royal_flush(cards: List[Card]) -> Optional[HandResult]:
    """10-J-Q-K-A of the same suit, no Jokers."""
    if any(c.is_joker for c in cards) or len(cards) != 5:
        return None
    values = {c.value for c in cards}
    if values != {"10", "J", "Q", "K", "A"}:
        return None
    suits = {c.suit for c in cards}
    if len(suits) == 1:
        return HandResult(
            hand_type=HandType.ROYAL_FLUSH,
            base_points=500,
            partner_bonus=0,
            matched_suit=next(iter(suits)),
            description="Royal Flush — instant win!"
        )
    return None


def _check_joker_cascade(cards: List[Card]) -> Optional[HandResult]:
    """Exactly 4 Jokers in hand (may have additional cards)."""
    if len(_jokers(cards)) == 4:
        return HandResult(
            hand_type=HandType.JOKER_CASCADE,
            base_points=300,
            partner_bonus=0,
            description="Joker Cascade (4×) — all others draw 2; dismiss 4 from hand/partner"
        )
    return None


def _check_dead_mans_hand(cards: List[Card]) -> Optional[HandResult]:
    """8♠ + 8♣ + A♠ + A♣ + (Spade Joker or Club Joker)."""
    j = _jokers(cards)
    r = _regulars(cards)
    if len(j) != 1 or not j[0].is_black_joker or len(r) != 4:
        return None
    has_8s = (any(c.value == "8" and c.suit == Suit.SPADES for c in r) and
              any(c.value == "8" and c.suit == Suit.CLUBS  for c in r))
    has_As = (any(c.value == "A" and c.suit == Suit.SPADES for c in r) and
              any(c.value == "A" and c.suit == Suit.CLUBS  for c in r))
    if has_8s and has_As:
        return HandResult(
            hand_type=HandType.DEAD_MANS_HAND,
            base_points=300,
            partner_bonus=0,
            description="Dead Man's Hand — 8♠8♣A♠A♣ + Black Joker"
        )
    return None


def _check_royal_joker_house(cards: List[Card]) -> Optional[HandResult]:
    """2 Aces + 3 Jokers."""
    j = _jokers(cards)
    aces = [c for c in cards if not c.is_joker and c.value == "A"]
    if len(j) == 3 and len(aces) == 2:
        return HandResult(
            hand_type=HandType.ROYAL_JOKER_HOUSE,
            base_points=280,
            partner_bonus=0,
            description="Royal Joker House — draw 1, discard 1, all three Joker effects cascade"
        )
    return None


def _check_royal_roots(cards: List[Card]) -> Optional[HandResult]:
    """J-Q-K-A + one Joker, with J/Q/K/A all in the same suit."""
    j = _jokers(cards)
    r = _regulars(cards)
    if len(j) != 1 or len(r) != 4:
        return None
    if {c.value for c in r} != {"J", "Q", "K", "A"}:
        return None
    suits = {c.suit for c in r}
    if len(suits) == 1:
        return HandResult(
            hand_type=HandType.ROYAL_ROOTS,
            base_points=120,
            partner_bonus=0,
            matched_suit=next(iter(suits)),
            description="Royal Roots — optional: change & lock suit 1 turn; draw 1 from discard"
        )
    return None


def _check_joker_house(cards: List[Card]) -> Optional[HandResult]:
    """3 Aces + 2 Jokers."""
    j = _jokers(cards)
    aces = [c for c in cards if not c.is_joker and c.value == "A"]
    if len(j) == 2 and len(aces) == 3:
        return HandResult(
            hand_type=HandType.JOKER_HOUSE,
            base_points=100,
            partner_bonus=0,
            description="Joker House — draw 2, discard 2, play again; both Joker effects cascade"
        )
    return None


def _check_roots(cards: List[Card]) -> Optional[HandResult]:
    """J-Q-K-A + one Joker, any suits."""
    j = _jokers(cards)
    r = _regulars(cards)
    if len(j) != 1 or len(r) != 4:
        return None
    if {c.value for c in r} == {"J", "Q", "K", "A"}:
        return HandResult(
            hand_type=HandType.ROOTS,
            base_points=75,
            partner_bonus=0,
            description="Roots — pick two enemies; take 2 random cards, they each draw 2"
        )
    return None


def _check_all_even(cards: List[Card]) -> Optional[HandResult]:
    """Exactly 2-4-6-8-10, one of each, any suits, no Jokers."""
    if len(cards) != 5 or any(c.is_joker for c in cards):
        return None
    if {c.value for c in cards} == {"2", "4", "6", "8", "10"}:
        return HandResult(
            hand_type=HandType.ALL_EVEN,
            base_points=50,
            partner_bonus=0,
            description="All-Even (Even Steven) — player & partner flush 2, pick 2 from discard"
        )
    return None


def _check_cascade_house(cards: List[Card]) -> Optional[HandResult]:
    """44499 (three 9s, two 4s) or 44999 (two 9s, three 4s), any suits."""
    if len(cards) != 5 or any(c.is_joker for c in cards):
        return None
    counts = Counter(c.value for c in cards)
    if (counts.get("4", 0) == 2 and counts.get("9", 0) == 3) or \
       (counts.get("4", 0) == 3 and counts.get("9", 0) == 2):
        return HandResult(
            hand_type=HandType.CASCADE_HOUSE,
            base_points=40,
            partner_bonus=0,
            description="Cascade House — all players pass their hand left or right (player's choice)"
        )
    return None


def _check_straight_flush(cards: List[Card]) -> Optional[HandResult]:
    """5+ sequential cards of the same suit (no Jokers needed).
    Points: 60 base, partner bonus +3."""
    r = _regulars(cards)
    by_suit: dict[Suit, list[int]] = defaultdict(list)
    for c in r:
        if c.suit and c.numeric_value is not None:
            by_suit[c.suit].append(c.numeric_value)

    best_len = 0
    best_suit: Optional[Suit] = None
    for suit, vals in by_suit.items():
        run = _longest_run(vals)
        if run > best_len:
            best_len = run
            best_suit = suit

    if best_len >= 5:
        pts = straight_flush_points(best_len)
        return HandResult(
            hand_type=HandType.STRAIGHT_FLUSH,
            base_points=pts,
            partner_bonus=3,
            card_count=best_len,
            matched_suit=best_suit,
            description=f"Straight Flush ({best_len} cards, {best_suit.value if best_suit else '?'}) — "
                        "all others draw 2; partner flushes 2 (solo: 1)"
        )
    return None


def _check_straight(cards: List[Card]) -> Optional[HandResult]:
    """5+ sequential cards, any suit (Jokers are excluded from the run).
    Points: 20 base + 2 per card beyond 5; partner bonus +3."""
    r = _regulars(cards)
    vals = _sorted_values(r)
    run = _longest_run(vals)
    if run >= 5:
        pts = straight_points(run)
        return HandResult(
            hand_type=HandType.STRAIGHT,
            base_points=pts,
            partner_bonus=3,
            card_count=run,
            description=f"Straight ({run} cards, {pts} pts) — "
                        "all others draw 2; partner safe; +2 per card beyond 5"
        )
    return None


def _check_flush(cards: List[Card]) -> Optional[HandResult]:
    """5+ cards of the same suit (Jokers match their own suit).
    Points: 15 base; 6-card → +3, each extra → +1; partner bonus +3.
    Effect: discard 1 card (flush 1); partner flushes 2 (solo: flush 2).
    Can only flush down to 1 card."""
    suit_counts: Counter = Counter()
    for c in cards:
        if c.effective_suit is not None:
            suit_counts[c.effective_suit] += 1

    best_suit = suit_counts.most_common(1)
    if not best_suit:
        return None
    suit, count = best_suit[0]
    if count >= 5:
        pts = flush_points(count)
        return HandResult(
            hand_type=HandType.FLUSH,
            base_points=pts,
            partner_bonus=3,
            card_count=count,
            matched_suit=suit,
            description=f"Flush ({count} cards, {suit.value}, {pts} pts) — "
                        "discard 1 (flush 1); partner flushes 2 (solo: flush 2); "
                        "can only flush down to 1 card; +1 per card beyond 6"
        )
    return None


# ─────────────────────────────────── public API ───────────────────────────────

# Detectors in priority order — first match wins
_DETECTORS = [
    _check_royal_dead_man,
    _check_royal_flush,
    _check_joker_cascade,
    _check_dead_mans_hand,
    _check_royal_joker_house,
    _check_royal_roots,
    _check_joker_house,
    _check_roots,
    _check_all_even,
    _check_cascade_house,
    _check_straight_flush,
    _check_straight,
    _check_flush,
]


def detect_hand(cards: List[Card]) -> HandResult:
    """Evaluate a list of cards and return the best matching HandResult."""
    for detector in _DETECTORS:
        result = detector(cards)
        if result is not None:
            return result
    return HandResult(hand_type=HandType.NONE, description="No valid hand detected.")
