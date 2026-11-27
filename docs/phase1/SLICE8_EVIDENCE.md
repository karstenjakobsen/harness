# Slice 8 acceptance evidence

Run `docs/phase1/SLICE8_EVIDENCE.sh` from the repository root with the workspace dependencies installed and Codex signed in. The script uses temporary workspaces. [Evidence script](SLICE8_EVIDENCE.sh) · [Acceptance criteria](SLICE8_TODO.md#acceptance)

The advisory session proposed a plan and saved zero children. Operator 1 used grant 1 to save five direct draft children under goal 1. Each child’s first revision links to its committing call in run 2. The parent stayed active at revision 1.

| Child | Goal ID | Committing call in run 2 |
| --- | --- | --- |
| Represent chess positions and apply moves | 2 | 6 |
| Generate legal moves and enforce king safety | 3 | 7 |
| Implement castling, en passant, and promotion | 4 | 8 |
| Detect game outcomes | 5 | 9 |
| Play a complete local two-player game | 6 | 10 |

The offline checks cover concurrent retries, interrupted replies, and audit outcomes after a child is committed or retrieved. The MCP checks exercise direct calls, discovery after withdrawal and regrant, and closure of a planning run.

## Captured output

````text

Owner request
Break my “Build a chess game in Go” goal into subgoals and save them for review. For each subgoal, say how we could tell it was done.

Advisory reply (zero children saved)
**Build a chess game in Go** (goal #1) is active and has no saved subgoals. The draft below is ready for review. It hasn’t been saved because this turn is advisory. I’ve assumed a local two-player terminal game.

| Proposed subgoal | How to tell it’s done |
|---|---|
| Represent the board and game state | Tests verify the starting position and confirm that applying a move updates the board and switches the side to move. |
| Generate legal moves and enforce king safety | Table-driven tests cover movement, captures, blocked paths, and check. With White’s king on e1 and rook on e2, and Black’s king on a8 and rook on e8, `e2f2` is rejected without changing the board or turn, and `e2e3` is accepted. |
| Implement castling, en passant, and promotion | Tests verify that castling moves both pieces and is blocked through check, en passant expires after one reply, and promotion supports all four choices. |
| Detect wins and draws | Tests verify checkmate and stalemate, draw claims for threefold repetition and the 50-move rule, and automatic draws in dead positions and at the fivefold repetition and 75-move thresholds. |
| Make the game playable in a terminal | Two players can complete a game from the starting position. The terminal displays the board and whose turn it is, lets a player retry an invalid move, and announces the result. `go test ./...` passes. |

**Suggested first step.** Write a Go test for the starting position and verify that applying `e2e4` puts the pawn on e4 and gives Black the turn.

Delegated reply
Saved and verified five draft subgoals under **Build a chess game in Go** (goal #1, active). I scoped the first playable version to local two-player chess in the terminal.

| Saved subgoal | How to tell it’s done |
|---|---|
| #2 · Draft · Represent chess positions and apply moves | Go tests verify the standard starting board, White moving first, and the correct square and turn updates after a regular move or capture. |
| #3 · Draft · Generate legal moves and enforce king safety | Table-driven Go tests cover all six piece types, blocked paths, captures, and responses to check. In the saved pinned-rook position, `e2f2` is rejected with the board and turn unchanged, while `e2e3` is accepted. |
| #4 · Draft · Implement castling, en passant, and promotion | Go tests accept legal castling and reject it through check or after rights are lost, verify that en passant works only on the immediate reply and removes the captured pawn, and exercise all four promotion choices. |
| #5 · Draft · Detect game outcomes | Go tests distinguish ongoing play, checkmate, and stalemate, verify the checkmate winner, and cover dead positions plus claimable and automatic draws by repetition and move count. |
| #6 · Draft · Play a complete local two-player game | A scripted terminal session displays turns, rejects an illegal move without advancing the turn, then plays `f2f3 e7e5 g2g4 d8h4` and announces Black wins by checkmate. `go test ./...` passes. |

Open goal #1’s tree to review each draft and its saved success criteria. A small first step is to write the test for the starting board and White’s first turn.

/goals/1/history?view=activity → /runs/2
Operator 1, grant 1, parent 1 at revision 1 (active)
Call 6 → /goals/2/history?view=activity → revision 1, draft: Represent chess positions and apply moves
  Go tests verify the standard starting layout and White to move, and that applying a quiet move or capture updates the expected squares and flips the turn.
Call 7 → /goals/3/history?view=activity → revision 1, draft: Generate legal moves and enforce king safety
  Table-driven Go tests cover all six piece types, blocked paths, captures, and both legal and illegal responses to check. In FEN k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1, reject e2f2 with the board and turn unchanged, and accept e2e3.
Call 8 → /goals/4/history?view=activity → revision 1, draft: Implement castling, en passant, and promotion
  Go tests accept legal castling and reject castling through check or after rights are lost, allow en passant only on the immediate reply and verify removal of the captured pawn, and verify promotion to queen, rook, bishop, and knight.
Call 9 → /goals/5/history?view=activity → revision 1, draft: Detect game outcomes
  Go tests distinguish checkmate, stalemate, and ongoing play, verify the winner on checkmate, and exercise dead positions plus claimable and automatic draws by repetition and move count at their respective thresholds.
Call 10 → /goals/6/history?view=activity → revision 1, draft: Play a complete local two-player game
  A scripted terminal session starts from the initial board, displays turns, rejects an illegal move without advancing the turn, then accepts f2f3, e7e5, g2g4, d8h4 and announces Black wins by checkmate. Run go test ./... successfully.
Call 2 list_skills → [{'id': 'chess-rules', 'revision': 1}, {'id': 'go-testing', 'revision': 1}]
Call 3 read_skill → [{'id': 'chess-rules', 'revision': 1}]
Call 5 read_skill → [{'id': 'go-testing', 'revision': 1}]
....Processing request of type ListToolsRequest
Processing request of type CallToolRequest
Tool 'create_subgoal' not listed, no validation will be performed
Processing request of type ListToolsRequest
Processing request of type CallToolRequest
Tool 'create_subgoal' not listed, no validation will be performed
Processing request of type ListToolsRequest
Processing request of type CallToolRequest
Tool 'revise_goal' not listed, no validation will be performed
Processing request of type CallToolRequest
Processing request of type CallToolRequest
Processing request of type CallToolRequest
Processing request of type CallToolRequest
Processing request of type CallToolRequest
.Processing request of type ListToolsRequest
Processing request of type ListToolsRequest
Processing request of type ListToolsRequest
Processing request of type CallToolRequest
Tool 'create_subgoal' not listed, no validation will be performed
Processing request of type CallToolRequest
Processing request of type CallToolRequest
Processing request of type ListToolsRequest
Processing request of type ListToolsRequest
Processing request of type CallToolRequest
.
6 passed in 61.07s (0:01:01)
````
