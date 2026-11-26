# Test a move rule in Go

Give each test case a position, side to move, candidate move and expected result. Pair a move that violates the rule with a nearby legal move from the same position. A legality check that always returns false should fail the second case.

For example, given White’s king on e1 and rook on e2 facing a black rook on e8, with the black king on a8, the rook can keep blocking the e-file or expose its king. A Go test using the engine’s position parser and legality function could express the cases this way.

```go
func TestPinnedRook(t *testing.T) {
    const fen = "k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1"
    for _, tc := range []struct {
        name, move string
        wantLegal  bool
    }{
        {"opens the e-file", "e2f2", false},
        {"keeps blocking", "e2e3", true},
    } {
        t.Run(tc.name, func(t *testing.T) {
            pos, err := ParseFEN(fen)
            if err != nil {
                t.Fatal(err)
            }
            if got := pos.IsLegal(tc.move); got != tc.wantLegal {
                t.Errorf("%s legal = %t, want %t", tc.move, got, tc.wantLegal)
            }
        })
    }
}
```

Adapt the example to the engine’s public API. For a move generator, check membership in its legal move list. For a mutating API, also compare the position before and after rejection. Run the package tests with `go test ./...`.
