"""
game.py — GameState and turn loop for Royal Roots.

Turn structure
--------------
1. Active player draws 1 card from the draw pile.
2. Player optionally declares ROOT OUT! (bets they have a valid special hand).
3. Player optionally selects cards from their hand to declare a hand combo.
4. If ROOT OUT! was declared, validate it:
     • success → +25 pts, then execute hand effect.
     • failure → -10 pts, all combo effects cancelled, turn ends.
5. If combo is valid (no ROOT OUT! or ROOT OUT! passed), award points and run effect.
6. Apply any "play again" flag (Joker House).
7. Advance to the next player (wrap around).

Locked-suit mechanic (Royal Roots effect)
-----------------------------------------
gs.locked_suit / gs.locked_suit_turns track whether a suit is locked.
The game loop decrements locked_suit_turns each turn and clears it at 0.
"""

from __future__ import annotations

from typing import List, Optional

from .card import Card, Suit
from .deck import Deck
from .player import Player
from .hand_detector import detect_hand, HandResult, HandType
from .effects import apply_effect, resolve_root_out


class GameState:
    """All mutable state shared across effect functions."""

    def __init__(self, players: List[Player], deck: Deck) -> None:
        self.players:          List[Player]   = players
        self.deck:             Deck           = deck
        self.turn_index:       int            = 0
        self.round_number:     int            = 1
        self.locked_suit:      Optional[Suit] = None
        self.locked_suit_turns:int            = 0
        self.heart_joker_cancel: bool         = False   # set by Heart Joker effect


class Game:
    HAND_SIZE    = 7     # cards dealt to each player at start of round
    WIN_SCORE    = 500   # first player to reach this score wins the game

    def __init__(self, player_names: List[str]) -> None:
        if len(player_names) < 2:
            raise ValueError("Need at least 2 players.")
        self.player_names = player_names
        self.gs: Optional[GameState] = None

    # ------------------------------------------------------------------ setup

    def _new_round(self) -> None:
        deck    = Deck()
        players = [Player(name=n) for n in self.player_names]
        # Deal starting hands
        for p in players:
            p.hand = deck.draw_many(self.HAND_SIZE)
        self.gs = GameState(players, deck)
        round_num = (self.gs.round_number if self.gs else 1)
        print(f"\n{'='*60}")
        print(f"  Round {round_num} — {len(players)} players, {deck.remaining} cards left in deck.")
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

    # ------------------------------------------------------------------ input

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
            idxs = list(dict.fromkeys(int(t) for t in tokens))  # unique, ordered
            if all(0 <= i < len(hand) for i in idxs):
                return idxs
        except ValueError:
            pass
        print("    Invalid input — skipping declaration.")
        return []

    # ------------------------------------------------------------------ turn

    def _run_turn(self, gs: GameState) -> dict:
        """Execute one player's turn.  Returns control flags from apply_effect."""
        player = gs.players[gs.turn_index]
        n      = len(gs.players)

        print(f"\n--- {player.name}'s turn (score: {player.score}) ---")

        # 1. Draw a card
        card = gs.deck.draw()
        player.hand.append(card)
        print(f"  {player.name} draws {card}.")

        # 2. Show hand
        self._show_hand(player)

        # 3. Optionally call ROOT OUT!
        root_out_called = False
        raw = self._input("  Type 'root' to call ROOT OUT!, or press Enter: ").lower()
        if raw == "root":
            root_out_called = True
            print("  ROOT OUT! declared!")

        # 4. Optionally declare a hand combo
        idxs = self._pick_indices(
            "  Select cards to declare a combo (or Enter to skip):",
            player.hand,
        )

        ctrl = {"play_again": False, "round_over": False, "game_over": False, "skip_advance": False}

        if not idxs:
            if root_out_called:
                # Declared ROOT OUT! but selected no cards → automatic fail
                player.score = max(0, player.score - 10)
                print("  ROOT OUT! failed (no cards selected) — -10 pts.")
            return ctrl

        selected = [player.hand[i] for i in idxs]
        result   = detect_hand(selected)

        print(f"\n  Hand detected: {result.description}")

        root_out_failed = False
        if root_out_called:
            success = resolve_root_out(gs, gs.turn_index, result)
            root_out_failed = not success

        if result.is_valid:
            # Award base points
            if not root_out_failed:
                player.score += result.base_points
                print(f"  {player.name} earns {result.base_points} pts. "
                      f"Total: {player.score}.")

            # 5. Execute effect
            ctrl = apply_effect(result, gs, gs.turn_index, root_out_failed=root_out_failed)
        else:
            print("  No valid hand — no points awarded.")
            if root_out_called and not root_out_failed:
                # ROOT OUT! was confirmed (somehow) but hand is NONE — shouldn't happen,
                # but handle defensively.
                pass

        return ctrl

    # ------------------------------------------------------------------ locked-suit tick

    @staticmethod
    def _tick_locked_suit(gs: GameState) -> None:
        if gs.locked_suit_turns > 0:
            gs.locked_suit_turns -= 1
            if gs.locked_suit_turns == 0:
                print(f"  [Locked suit {gs.locked_suit.value} expired.]")
                gs.locked_suit = None

    # ------------------------------------------------------------------ main loop

    def run(self) -> None:
        """Main game loop."""
        self._new_round()
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
                # Start new round; preserve scores
                old_scores = {p.name: p.score for p in gs.players}
                gs.round_number += 1
                self._new_round()
                gs = self.gs
                assert gs is not None
                for p in gs.players:
                    p.score = old_scores.get(p.name, 0)

                # Check overall win condition
                winner = next((p for p in gs.players if p.score >= self.WIN_SCORE), None)
                if winner:
                    print(f"\n*** {winner.name} wins the game with {winner.score} pts! ***")
                    game_running = False
                continue

            # "play again" — same player gets another turn immediately
            if ctrl.get("play_again"):
                print(f"  (Joker House — {gs.players[gs.turn_index].name} plays again!)")
                # Re-run turn without advancing index
                continue

            # Advance turn
            self._tick_locked_suit(gs)
            gs.heart_joker_cancel = False
            gs.turn_index = (gs.turn_index + 1) % len(gs.players)

            # Quick win check after every turn
            winner = next((p for p in gs.players if p.score >= self.WIN_SCORE), None)
            if winner:
                print(f"\n*** {winner.name} reaches {winner.score} pts — GAME OVER! ***")
                self._show_scores(gs)
                game_running = False
