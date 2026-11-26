# Verify king safety

A sliding piece can move along an open rank or file, yet a move that exposes its own king to attack is illegal. When planning move generation, separate the piece’s movement rules from the king-safety check. Apply a candidate move to a copy of the position, then test whether the opponent attacks the moving side’s king.

Use this four-piece position with White to move and every other square empty.

| Side | King | Rook |
| --- | --- | --- |
| White | e1 | e2 |
| Black | a8 | e8 |

White’s rook on e2 blocks the black rook’s line down the e-file. Moving e2–f2 opens the line to e1, so the move must be rejected. Moving e2–e3 keeps the rook on that line and is legal. These two cases distinguish checking king safety from rejecting every move by a pinned piece.

The FEN is `k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1`. Verify that rejecting the illegal move preserves both the board and the side to move.
