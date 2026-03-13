#!/usr/bin/env python3
"""
main.py — Entry point for Royal Roots: The Card Game.

Usage:
    python main.py [player1 player2 player3 player4]

If no names are supplied, four default names are used.
The game supports 2–4 players (4-player recommended for full partner mechanics).
"""

import sys
from src.game import Game


def main() -> None:
    args = sys.argv[1:]
    if args:
        names = args
    else:
        names = ["Player 1", "Player 2", "Player 3", "Player 4"]

    print("=" * 60)
    print("         ROYAL ROOTS — The Card Game")
    print("=" * 60)
    print(f"Players: {', '.join(names)}")
    print("(Partners sit opposite: P1↔P3, P2↔P4)")
    print()

    game = Game(names)
    try:
        game.run()
    except KeyboardInterrupt:
        print("\n\nGame interrupted. Goodbye!")


if __name__ == "__main__":
    main()
