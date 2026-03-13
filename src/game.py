"""
game.py — GameState and turn loop for Royal Roots.

Turn structure
--------------
1. Active player draws 1 card from the draw pile.
2. Player optionally calls ROOT OUT! — must NAME the hand type they claim to hold.
3. Player selects cards from their hand to declare a combo.
4. The game auto-detects the best hand from the selected cards.
5. ROOT OUT! resolution (if declared):
     • claimed type == detected type → success: +25 pts, then execute effect.
     • mismatch or no valid hand     → failure: -10 pts, effects cancelled.
6. If combo is valid (and ROOT OUT! not failed), award base points + run effect.
7. Apply "play again" flag (Joker House).
8. Advance to the next player (wrap around).

Locked-suit mechanic (Royal Roots effect)
-----------------------------------------
gs.locked_suit / gs.locked_suit_turns track whether a suit is locked.
The main loop decrements locked_suit_turns each turn and clears it at 0.

Heart Joker shield
------------------
gs.shielded_player_idx tracks a player who is immune to the next forced draw.
It is consumed (set to -1) on first use and also cleared at the end of each turn.
"""

from __future__ import annotations

from typing import List, Optional

from .card import Card, Suit
from .deck import Deck
from .player import Player
from .hand_detector import detect_hand, HandResult, HandType
from .effects import apply_effect, resolve_root_out


# Hand-type labels shown to the player when they call ROOT OUT!
_CLAIMABLE_HAND_TYPES: List[HandType] = [
    HandType.ROYAL_DEAD_MAN,
    HandType.ROYAL_FLUSH,
    HandType.JOKER_CASCADE,
    HandType.DEAD_MANS_HAND,
    HandType.ROYAL_JOKER_HOUSE,
    HandType.ROYAL_ROOTS,
    HandType.JOKER_HOUSE,
    HandType.ROOTS,
    HandType.ALL_EVEN,
    HandType.CASCADE_HOUSE,
    HandType.STRAIGHT_FLUSH,
    HandType.STRAIGHT,
    HandType.FLUSH,
]


class GameState:
    """All mutable state shared across effect functions."""

    def __init__(self, players: List[Player], deck: Deck) -> None:
        self.players:             List[Player]   = players
        self.deck:                Deck           = deck
        self.turn_index:          int            = 0
        self.round_number:        int            = 1
        self.locked_suit:         Optional[Suit] = None
        self.locked_suit_turns:   int            = 0
        self.heart_joker_cancel:  bool           = False   # signals cascade skip
        self.shielded_player_idx: int            = -1      # Heart Joker forced-draw shield


class Game:
    HAND_SIZE = 7     # cards dealt to each player at start of round
    WIN_SCORE = 500   # first player to reach this score wins the game

    def __init__(self, player_names: List[str]) -> None:
        if len(player_names) < 2:
            raise ValueError("Need at least 2 players.")
        self.player_names = player_names
        self.gs: Optional[GameState] = None

    # ------------------------------------------------------------------ setup

    def _new_round(self, round_number: int = 1) -> None:
        deck    = Deck()
        players = [Player(name=n) for n in self.player_names]
        for p in players:
            p.hand = deck.draw_many(self.HAND_SIZE)
        self.gs = GameState(players, deck)
        self.gs.round_number = round_number
        print(f"\n{'='*60}")
        print(f"  Round {round_number} — {len(players)} players, {deck.remaining} cards left in deck.")
        print(f"{'='*60}\n")

    # ------------------------------------------------------------------ display

    @staticmethod
    def _show_scores(gs: GameState) -> None:
        print("\n  Scores:")
        for p in gs.players:
            print(f"    {p.name}: {p.score} pts")

    @staticmethod
    def _show_hand(player: Player) -> None:
        print(f"\n  {player.name}'s hand:")
        print(player.show_hand())

    # ------------------------------------------------------------------ input helpers

    @staticmethod
    def _input(prompt: str) -> str:
        return input(prompt).strip()

    @staticmethod
    def _pick_indices(prompt: str, hand: List[Card]) -> List[int]:
        """Ask the player to type card indices (space-separated). Returns [] on skip."""
        print(prompt)
        for i, c in enumerate(hand):
            print(f"    [{i}] {c}")
        raw = input("    Indices (space-separated) or Enter to skip: ").strip()
        if not raw:
            return []
        tokens = raw.split()
        try:
            idxs = list(dict.fromkeys(int(t) for t in tokens))   # unique, order-preserving
            if all(0 <= i < len(hand) for i in idxs):
                return idxs
        except ValueError:
            pass
        print("    Invalid input — skipping declaration.")
        return []

    @staticmethod
    def _prompt_claimed_hand_type() -> HandType:
        """Ask the ROOT OUT! caller to name the hand type they believe they hold."""
        print("  ROOT OUT! — what hand are you claiming?")
        for i, ht in enumerate(_CLAIMABLE_HAND_TYPES):
            label = ht.name.replace("_", " ").title()
            print(f"    [{i}] {label}")
        while True:
            raw = input(f"    Enter choice (0–{len(_CLAIMABLE_HAND_TYPES)-1}): ").strip()
            if raw.isdigit() and 0 <= int(raw) < len(_CLAIMABLE_HAND_TYPES):
                chosen = _CLAIMABLE_HAND_TYPES[int(raw)]
                print(f"  Claimed hand: {chosen.name.replace('_', ' ').title()}")
                return chosen
            print("    Invalid — enter a number from the list.")

    # ------------------------------------------------------------------ turn

    def _run_turn(self, gs: GameState) -> dict:
        """Execute one player's turn.  Returns control flags from apply_effect."""
        player = gs.players[gs.turn_index]

        print(f"\n--- {player.name}'s turn (score: {player.score}) ---")
        if gs.locked_suit:
            print(f"  [Suit locked: {gs.locked_suit.value} for {gs.locked_suit_turns} more turn(s)]")

        # 1. Draw a card
        drawn = gs.deck.draw()
        player.hand.append(drawn)
        print(f"  {player.name} draws {drawn}.")

        # 2. Show hand
        self._show_hand(player)

        # 3. Optionally call ROOT OUT! (must commit to a claimed hand type BEFORE seeing detection)
        root_out_called = False
        claimed_type: Optional[HandType] = None
        raw = self._input("  Type 'root' to call ROOT OUT!, or press Enter: ").lower()
        if raw == "root":
            root_out_called = True
            claimed_type = self._prompt_claimed_hand_type()

        # 4. Select cards to declare a combo
        idxs = self._pick_indices(
            "  Select cards to declare a combo (or Enter to skip):",
            player.hand,
        )

        ctrl = {"play_again": False, "round_over": False, "game_over": False, "skip_advance": False}

        if not idxs:
            if root_out_called:
                # ROOT OUT! declared but no cards selected → automatic fail
                player.score = max(0, player.score - 10)
                print("  ROOT OUT! failed (no cards selected) — -10 pts.")
            return ctrl

        # 5. Detect the best hand from the selected cards
        selected = [player.hand[i] for i in idxs]
        result   = detect_hand(selected)

        print(f"\n  Hand detected: {result.description or result.hand_type.name}")

        # 6. Resolve ROOT OUT! if called
        root_out_failed = False
        if root_out_called and claimed_type is not None:
            success        = resolve_root_out(gs, gs.turn_index, claimed_type, result)
            root_out_failed = not success

        # 7. Award points and apply effect (unless ROOT OUT! failed)
        if result.is_valid:
            if not root_out_failed:
                player.score += result.base_points
                print(f"  {player.name} earns {result.base_points} pts.  Total: {player.score}.")

            ctrl = apply_effect(
                result,
                gs,
                gs.turn_index,
                root_out_failed=root_out_failed,
                declared_cards=selected,
            )
        else:
            print("  No valid hand detected — no points awarded.")
            if root_out_called and not root_out_failed:
                # Calling ROOT OUT! with genuinely no valid hand is an automatic fail
                player.score = max(0, player.score - 10)
                print("  ROOT OUT! failed (no valid hand) — -10 pts.")

        return ctrl

    # ------------------------------------------------------------------ locked-suit tick

    @staticmethod
    def _tick_locked_suit(gs: GameState) -> None:
        if gs.locked_suit_turns > 0:
            gs.locked_suit_turns -= 1
            if gs.locked_suit_turns == 0:
                print(f"  [Locked suit {gs.locked_suit.value} has expired.]")
                gs.locked_suit = None

    # ------------------------------------------------------------------ main loop

    def run(self) -> None:
        """Main game loop."""
        self._new_round(round_number=1)
        gs = self.gs
        assert gs is not None

        game_running = True
        while game_running:
            ctrl = self._run_turn(gs)

            if ctrl.get("game_over"):
                print("\n*** GAME OVER — ROYAL DEAD MAN played! ***")
                self._show_scores(gs)
                break

            if ctrl.get("round_over"):
                print("\n*** Round over — Royal Flush played! ***")
                self._show_scores(gs)
                old_scores = {p.name: p.score for p in gs.players}
                next_round = gs.round_number + 1
                self._new_round(round_number=next_round)
                gs = self.gs
                assert gs is not None
                for p in gs.players:
                    p.score = old_scores.get(p.name, 0)
                winner = next((p for p in gs.players if p.score >= self.WIN_SCORE), None)
                if winner:
                    print(f"\n*** {winner.name} wins the game with {winner.score} pts! ***")
                    game_running = False
                continue

            # "play again" — same player gets another full turn immediately
            if ctrl.get("play_again"):
                print(f"  (Joker House — {gs.players[gs.turn_index].name} plays again!)")
                continue

            # End-of-turn housekeeping
            self._tick_locked_suit(gs)
            gs.heart_joker_cancel  = False   # clear any stale cascade flag
            gs.shielded_player_idx = -1      # clear unused Heart Joker shield

            gs.turn_index = (gs.turn_index + 1) % len(gs.players)

            # Win check
            winner = next((p for p in gs.players if p.score >= self.WIN_SCORE), None)
            if winner:
                print(f"\n*** {winner.name} reaches {winner.score} pts — GAME OVER! ***")
                self._show_scores(gs)
                game_running = False
