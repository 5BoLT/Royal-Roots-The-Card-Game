"""
effects.py — Effect resolution for all Royal Roots hand types.

Design principles (no-freeze guarantee):
  • Every effect function receives the full GameState so it can read/write
    player hands, the deck, and the discard pile directly.
  • Player decisions are gathered via _prompt_choice() / _prompt_yes_no(),
    which always have a default and validate input in a loop — they never
    hang indefinitely.
  • Multi-step cascades (Joker House, Royal Joker House) use only the jokers
    from the declared hand (passed as declared_cards), not all jokers the
    player happens to hold.
  • Heart Joker (in a cascade) sets a skip_next flag that suppresses the
    immediately following cascade step — no freeze, no infinite loop.
  • Heart Joker (standalone) sets gs.shielded_player_idx; the next "force
    draw" loop that would hit that player skips them (one-time use).
  • ROOT OUT! cancellation is checked at the top of apply_effect() — if
    root_out_failed is True the function exits immediately without applying
    any combo effect.
  • After every effect returns, the caller (game.py) is responsible for
    advancing the turn index — effects themselves do NOT manipulate turn order
    except where "play again" is explicitly part of the rule.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, List, Optional

from .hand_detector import HandType, HandResult
from .card import Card, Suit

if TYPE_CHECKING:
    from .game import GameState


# ──────────────────────────────────────── I/O helpers ─────────────────────────

def _prompt_choice(prompt: str, options: List[str], default: int = 0) -> int:
    """Ask the active player to pick from a numbered list.  Always returns a valid index."""
    print(prompt)
    for i, opt in enumerate(options):
        print(f"  [{i}] {opt}")
    while True:
        raw = input(f"  Enter choice (default {default}): ").strip()
        if raw == "":
            return default
        if raw.isdigit() and 0 <= int(raw) < len(options):
            return int(raw)
        print(f"  Invalid — enter 0 to {len(options) - 1}.")


def _prompt_yes_no(prompt: str, default: bool = True) -> bool:
    """Ask a yes/no question; returns True for yes."""
    yn = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{prompt} [{yn}]: ").strip().lower()
        if raw == "":
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Enter y or n.")


def _prompt_card_indices(
    prompt: str,
    hand: List[Card],
    min_count: int,
    max_count: int,
) -> List[int]:
    """Ask the player to select card indices from their hand.  Enforces min/max bounds."""
    print(prompt)
    for i, c in enumerate(hand):
        print(f"  [{i}] {c}")
    while True:
        raw = input(f"  Enter {min_count}–{max_count} indices separated by spaces: ").strip()
        tokens = raw.split()
        try:
            idxs = [int(t) for t in tokens]
        except ValueError:
            print("  Numbers only.")
            continue
        if any(i < 0 or i >= len(hand) for i in idxs):
            print(f"  Index out of range (0–{len(hand) - 1}).")
            continue
        if len(set(idxs)) != len(idxs):
            print("  Duplicate indices — pick distinct cards.")
            continue
        if min_count <= len(idxs) <= max_count:
            return idxs
        print(f"  Pick between {min_count} and {max_count} cards.")


def _flush_cards(player_idx: int, count: int, gs: "GameState", label: str = "") -> None:
    """Have a player discard `count` cards, but never below 1 card in hand."""
    player = gs.players[player_idx]
    hand = player.hand
    if len(hand) <= 1:
        print(f"  {player.name}{label}: only 1 card in hand — cannot flush.")
        return
    max_flush = min(count, len(hand) - 1)  # must keep at least 1
    idxs = _prompt_card_indices(
        f"  {player.name}{label}: choose {max_flush} card(s) to flush (discard):",
        hand,
        max_flush,
        max_flush,
    )
    for i in sorted(idxs, reverse=True):
        gs.deck.discard(hand.pop(i))


def _force_draw(player_idx: int, count: int, gs: "GameState") -> None:
    """Force a player to draw `count` cards, respecting the Heart Joker shield."""
    p = gs.players[player_idx]
    if gs.shielded_player_idx == player_idx:
        print(f"  {p.name} is shielded by Heart Joker — forced draw cancelled.")
        gs.shielded_player_idx = -1   # one-time use
        return
    for _ in range(count):
        p.hand.append(gs.deck.draw())
    print(f"    {p.name} draws {count}.")


# ──────────────────────────────────── joker effects ───────────────────────────

# Individual Joker effects applied in cascade order (Joker House / Royal Joker House).
# The jokers are those from the DECLARED hand, not all jokers the player holds.

def _apply_single_joker_effect(
    joker: Card,
    gs: "GameState",
    player_idx: int,
) -> None:
    """Apply the individual effect of one Joker card.
    Returns without hanging if the pile is empty or input is invalid."""
    from .card import JokerType

    jt     = joker.joker_type
    player = gs.players[player_idx]
    n      = len(gs.players)

    if jt == JokerType.SPADE_JOKER:
        # All opponents each draw 1 card
        print(f"  [Spade Joker] All opponents draw 1 card.")
        for i in range(n):
            if i != player_idx:
                _force_draw(i, 1, gs)

    elif jt == JokerType.CLUB_JOKER:
        # Pick one opponent to discard 1 card
        opponents  = [i for i in range(n) if i != player_idx]
        opp_names  = [gs.players[i].name for i in opponents]
        choice     = _prompt_choice(
            f"  [Club Joker] {player.name}: pick an opponent to discard 1 card:",
            opp_names,
        )
        target_idx = opponents[choice]
        target     = gs.players[target_idx]
        if len(target.hand) > 1:
            idxs = _prompt_card_indices(
                f"  {target.name}: choose 1 card to discard (Club Joker):",
                target.hand, 1, 1,
            )
            gs.deck.discard(target.hand.pop(idxs[0]))
            print(f"    {target.name} discards 1.")
        else:
            print(f"  {target.name} has only 1 card — cannot discard.")

    elif jt == JokerType.HEART_JOKER:
        # Active player picks ONE other player to shield from the next forced draw.
        # Also signals the cascade loop to skip the immediately following joker effect.
        others      = [i for i in range(n) if i != player_idx]
        other_names = [gs.players[i].name for i in others]
        idx = _prompt_choice(
            f"  [Heart Joker] {player.name}: pick a player to shield from the next forced draw:",
            other_names,
        )
        gs.shielded_player_idx = others[idx]
        gs.heart_joker_cancel  = True   # tells cascade loop to skip the next step
        print(f"  {gs.players[gs.shielded_player_idx].name} is shielded from the next forced draw.")

    elif jt == JokerType.DIAMOND_JOKER:
        # Active player draws up to 2 cards from the discard pile
        print(f"  [Diamond Joker] {player.name} draws up to 2 cards from discard.")
        for _ in range(2):
            try:
                card = gs.deck.draw_from_discard()
                player.hand.append(card)
                print(f"    {player.name} draws {card} from discard.")
            except RuntimeError:
                print("    Discard pile empty — no more cards available.")
                break


def _run_joker_cascade(
    declared_jokers: List[Card],
    gs: "GameState",
    player_idx: int,
) -> None:
    """Cascade the effects of declared Jokers in order.
    Heart Joker sets gs.heart_joker_cancel which skips the NEXT joker in the cascade."""
    for joker in declared_jokers:
        if gs.heart_joker_cancel:
            gs.heart_joker_cancel = False
            print(f"  [{joker}] effect skipped by Heart Joker.")
            continue
        print(f"  Cascading [{joker}] effect:")
        _apply_single_joker_effect(joker, gs, player_idx)


# ─────────────────────────────────── main dispatcher ─────────────────────────

def apply_effect(
    result: HandResult,
    gs: "GameState",
    player_idx: int,
    root_out_failed: bool = False,
    declared_cards: Optional[List[Card]] = None,
) -> dict:
    """
    Apply the effect of a detected hand to the game state.

    declared_cards — the exact cards the player selected for this combo; used to
    determine which Jokers participate in a Joker House / Royal Joker House cascade.

    Returns a dict with control flags:
      "play_again"    — True if the active player takes another turn immediately
      "round_over"    — True if the round should end
      "game_over"     — True if the entire game should end
      "skip_advance"  — True if turn advancement is handled here (play_again case)
    """
    ctrl = {"play_again": False, "round_over": False, "game_over": False, "skip_advance": False}

    # ROOT OUT! failure → cancel all combo effects immediately
    if root_out_failed:
        print("  ROOT OUT! failed — all combo effects cancelled this turn.")
        return ctrl

    ht      = result.hand_type
    player  = gs.players[player_idx]
    n       = len(gs.players)
    partner = gs.players[(player_idx + 2) % n]   # partner sits opposite
    enemies = [gs.players[(player_idx + 1) % n], gs.players[(player_idx + 3) % n]]
    is_solo = (n <= 2)

    # Jokers from the declared hand — used for cascade effects
    declared_jokers: List[Card] = [c for c in (declared_cards or []) if c.is_joker]

    # ── award partner bonus ────────────────────────────────────────────────────
    if result.partner_bonus and not is_solo:
        partner.score += result.partner_bonus
        print(f"  {partner.name} earns +{result.partner_bonus} partner bonus pts.")

    # ── per-hand effects ───────────────────────────────────────────────────────

    if ht == HandType.ROYAL_DEAD_MAN:
        print("  *** ROYAL DEAD MAN — GAME OVER! ***")
        ctrl["game_over"] = True

    elif ht == HandType.ROYAL_FLUSH:
        print("  *** Royal Flush — instant win! Round ends. ***")
        ctrl["round_over"] = True

    elif ht == HandType.JOKER_CASCADE:
        # All others draw 2; active player + partner dismiss 4 from their combined hand
        print(f"  Joker Cascade (4×): all others draw 2.")
        for i in range(n):
            if i != player_idx:
                _force_draw(i, 2, gs)
        print(f"  {player.name} & partner dismiss 4 cards total.")
        total_dismiss = 4
        for target in ([player] if is_solo else [player, partner]):
            if total_dismiss <= 0:
                break
            avail = min(total_dismiss, max(0, len(target.hand) - 1))
            if avail > 0:
                idxs = _prompt_card_indices(
                    f"  {target.name}: dismiss up to {avail} card(s) from hand:",
                    target.hand, 1, avail,
                )
                for i in sorted(idxs, reverse=True):
                    gs.deck.discard(target.hand.pop(i))
                total_dismiss -= len(idxs)

    elif ht == HandType.DEAD_MANS_HAND:
        # Points only — no additional board effect
        print("  Dead Man's Hand — 8♠8♣A♠A♣ + Black Joker. Points awarded.")

    elif ht == HandType.ROYAL_JOKER_HOUSE:
        # Draw 1, discard 1; cascade all three declared Joker effects in order
        print(f"  Royal Joker House: {player.name} draws 1, then discards 1.")
        player.hand.append(gs.deck.draw())
        idxs = _prompt_card_indices(
            f"  {player.name}: choose 1 card to discard:", player.hand, 1, 1
        )
        gs.deck.discard(player.hand.pop(idxs[0]))
        # Use only the 3 Jokers from the declared hand (in declared order)
        cascade = declared_jokers[:3] if len(declared_jokers) >= 3 else declared_jokers
        if not cascade:
            print("  (No declared Jokers found to cascade — skipping.)")
        else:
            _run_joker_cascade(cascade, gs, player_idx)

    elif ht == HandType.ROYAL_ROOTS:
        # Optional: change & lock suit for 1 turn; draw 1 from discard
        if _prompt_yes_no(f"  {player.name}: lock a suit for 1 turn?"):
            suit_names = [s.value for s in Suit]
            idx = _prompt_choice("  Choose suit to lock:", suit_names)
            gs.locked_suit        = list(Suit)[idx]
            gs.locked_suit_turns  = 1
            print(f"  Suit locked to {gs.locked_suit.value} for 1 turn.")
        try:
            drawn = gs.deck.draw_from_discard()
            player.hand.append(drawn)
            print(f"  {player.name} draws {drawn} from discard.")
        except RuntimeError:
            print("  Discard pile empty — no card drawn.")

    elif ht == HandType.JOKER_HOUSE:
        # Draw 2, discard 2; cascade both declared Joker effects; play again
        print(f"  Joker House: {player.name} draws 2, then discards 2.")
        for _ in range(2):
            player.hand.append(gs.deck.draw())
        idxs = _prompt_card_indices(
            f"  {player.name}: choose 2 cards to discard:", player.hand, 2, 2
        )
        for i in sorted(idxs, reverse=True):
            gs.deck.discard(player.hand.pop(i))
        # Use only the 2 Jokers from the declared hand (in declared order)
        cascade = declared_jokers[:2] if len(declared_jokers) >= 2 else declared_jokers
        if not cascade:
            print("  (No declared Jokers found to cascade — skipping.)")
        else:
            _run_joker_cascade(cascade, gs, player_idx)
        ctrl["play_again"]   = True
        ctrl["skip_advance"] = True
        print(f"  {player.name} plays again!")

    elif ht == HandType.ROOTS:
        # Pick 2 enemy players; take 2 random cards from each; each enemy draws 2
        print(f"  Roots: {player.name} picks 2 enemies.")
        targets: List = []
        if len(enemies) <= 2:
            targets = enemies[:2]
        else:
            remaining = list(enemies)
            for _ in range(2):
                names = [e.name for e in remaining]
                idx = _prompt_choice("  Pick an enemy:", names)
                targets.append(remaining.pop(idx))
        for target in targets:
            if len(target.hand) >= 2:
                stolen_idxs = random.sample(range(len(target.hand)), 2)
                stolen = [target.hand[i] for i in stolen_idxs]
                for i in sorted(stolen_idxs, reverse=True):
                    target.hand.pop(i)
                # Stolen cards go to discard; enemy redraws 2
                gs.deck.discard_many(stolen)
                print(f"  {player.name} reveals {stolen} from {target.name} (sent to discard).")
                _force_draw(gs.players.index(target), 2, gs)
            else:
                print(f"  {target.name} has fewer than 2 cards — no steal.")

    elif ht == HandType.ALL_EVEN:
        # Player and partner each flush 2 cards; then each picks 2 from discard
        print(f"  All-Even: {player.name} and partner each flush 2 cards.")
        pair = [player_idx] if is_solo else [player_idx, (player_idx + 2) % n]
        for ti in pair:
            _flush_cards(ti, 2, gs, label=" (All-Even flush)")
        print(f"  {player.name} and partner each pick 2 cards from the discard pile.")
        for ti in pair:
            target = gs.players[ti]
            for pick_num in range(1, 3):
                if not gs.deck.discard_pile:
                    print(f"  Discard pile empty — {target.name} cannot draw more.")
                    break
                top = gs.deck.peek_discard(min(3, len(gs.deck.discard_pile)))
                opt_labels = [str(c) for c in top] + ["Skip"]
                idx = _prompt_choice(
                    f"  {target.name}: pick card #{pick_num} from discard (top shown):",
                    opt_labels,
                )
                if idx < len(top):
                    chosen = top[idx]
                    gs.deck.discard_pile.remove(chosen)
                    target.hand.append(chosen)
                    print(f"  {target.name} picks {chosen} from discard.")

    elif ht == HandType.CASCADE_HOUSE:
        # All players pass their entire hand left or right — simultaneous swap
        direction_idx = _prompt_choice(
            f"  {player.name}: which direction should everyone pass their hand?",
            ["Left (each player receives hand from their right neighbour)",
             "Right (each player receives hand from their left neighbour)"],
        )
        direction = "left" if direction_idx == 0 else "right"
        snapshot = [p.hand[:] for p in gs.players]
        if direction == "left":
            for i, p in enumerate(gs.players):
                p.hand = snapshot[(i + 1) % n]   # receive from right, pass to left
        else:
            for i, p in enumerate(gs.players):
                p.hand = snapshot[(i - 1) % n]   # receive from left, pass to right
        print(f"  All players passed hands to the {direction}.")

    elif ht == HandType.STRAIGHT_FLUSH:
        # All others draw 2; partner flushes 2 (solo: active player flushes 1)
        print(f"  Straight Flush: all others draw 2.")
        for i in range(n):
            if i != player_idx:
                _force_draw(i, 2, gs)
        if is_solo:
            print(f"  Solo: {player.name} flushes 1 card.")
            _flush_cards(player_idx, 1, gs, label=" (SF flush)")
        else:
            partner_idx = (player_idx + 2) % n
            print(f"  {partner.name} flushes 2 cards.")
            _flush_cards(partner_idx, 2, gs, label=" (SF flush)")

    elif ht == HandType.STRAIGHT:
        # All others draw 2; partner is safe (excluded from draw)
        print(f"  Straight: all others draw 2; partner is safe.")
        partner_idx = (player_idx + 2) % n
        for i in range(n):
            if i != player_idx and (is_solo or i != partner_idx):
                _force_draw(i, 2, gs)

    elif ht == HandType.FLUSH:
        # Active player flushes 1; partner flushes 2 (solo: active flushes 2).
        # Can only flush down to 1 card in hand.
        if is_solo:
            print(f"  Flush (solo): {player.name} flushes 2 cards (min 1 remaining).")
            _flush_cards(player_idx, 2, gs, label=" (flush solo)")
        else:
            print(f"  Flush: {player.name} flushes 1 card; {partner.name} flushes 2.")
            _flush_cards(player_idx,                1, gs, label=" (flush)")
            _flush_cards((player_idx + 2) % n,     2, gs, label=" (flush partner)")

    return ctrl


# ──────────────────────────────────── ROOT OUT! ────────────────────────────────

def resolve_root_out(
    gs: "GameState",
    caller_idx: int,
    claimed_type: HandType,
    detected_result: HandResult,
) -> bool:
    """
    Resolve a ROOT OUT! call.

    The player must have correctly named their hand type BEFORE the cards were
    revealed.  This function compares claimed_type (what the player said) against
    detected_result.hand_type (what the selected cards actually form).

    Returns True  → ROOT OUT! succeeded; caller earns +25 pts.
    Returns False → ROOT OUT! failed;    caller loses 10 pts, effects cancelled.
    """
    caller = gs.players[caller_idx]

    if detected_result.is_valid and detected_result.hand_type == claimed_type:
        caller.score += 25
        print(f"  ROOT OUT! succeeded — {caller.name} earns +25 pts.")
        return True
    else:
        caller.score = max(0, caller.score - 10)
        actual_name = (detected_result.hand_type.name.replace("_", " ").title()
                       if detected_result.is_valid else "No valid hand")
        print(
            f"  ROOT OUT! FAILED — {caller.name} loses 10 pts.  "
            f"Claimed: {claimed_type.name.replace('_', ' ').title()}, "
            f"Actual: {actual_name}.  All combo effects cancelled."
        )
        return False
