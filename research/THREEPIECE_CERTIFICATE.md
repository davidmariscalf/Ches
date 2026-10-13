# KQK/KRK exhaustive endgame certification — 13 October 2026

This calculation concerns **only** three-piece subgames: White king and
queen/rook versus Black king. Every placement and side to move must be legal
according to `python-chess`; there are no pawns, castling, en-passant rights or
history-dependent features in the state graph. A win claim applies when the
subgame is entered with the halfmove clock reset to **zero**, and no earlier
repetition of this material configuration.

## Audited enumeration

| Subgame | Legal positions | White forced wins | Draws | Checked legal moves | Max forced mate (plies) |
| :-- | --: | --: | --: | --: | --: |
| White K+Q vs Black K | 368,452 | 345,404 | 23,048 | 4,891,672 | 20 |
| White K+R vs Black K | 399,112 | 376,868 | 22,244 | 4,469,208 | 32 |
| **Total** | **767,564** | **722,272** | **45,292** | **9,360,880** | — |

The numbers above were recorded from
[GitHub Actions, initial complete audit](https://github.com/davidmariscalf/Ches/actions/runs/38474754729).

## Exact adversarial reasoning

1. The legal position graph is enumerated exhaustively.
2. Checkmated Black positions are established as terminal White wins (DTM 0).
3. A White-turn position becomes a proven White win when **at least one**
   successor is a proven White win.
4. A Black-turn position becomes a proven White win only when **all**
   legal successors are proven White wins. A capture of the remaining White
   major piece leads to bare kings, which is a draw and thus blocks that win.
5. The remaining positions form a closed drawing region:
   at White nodes **every** successor is in that region; at Black nodes
   **at least one** is.
6. A complete second pass regenerates each legal move list and checks the
   winning rank (distance to mate), terminal states and drawing closure.
7. All certified winning distances are < 100 semijugadas, so from a fresh
   halfmove clock the 50-move draw claim cannot block the shortest
   White-mate strategy. Winning-distance ranks strictly decrease on
   the chosen strategy and all defensive continuations, preventing repeat
   cycles from invalidating a win.

This is an exhaustive **computational** verification based on a shared
`python-chess` legal-move generator. It is not a Lean/Coq formal proof nor
an independent implementation of the entire FIDE move generator.

## Reproduce

```bash
python -m pip install -e ".[test]"
python -m ches.threepiece --piece queen --output queen.gz --manifest queen.json
python -m ches.threepiece --piece rook --output rook.gz --manifest rook.json
```

The generated binary has sorted little-endian `<Ih` records
(position key, signed distance; `-1` means draw). Each manifest specifies
the SHA-256 of the **uncompressed** records and the complete transition audit.

To use the tables as trusted exact leaves, `load_verified` re-enumerates
all legal positions, validates hashes and coverage, and rechecks every
transition **before** returning an oracle:

```bash
python -m ches.threshold_cli search --fen "7k/5K2/6Q1/8/8/8/8/8 w - - 0 1" \
  --depth 0 --queen-table queen.gz queen.json --out queen-proof.json
python -m ches.threshold_cli verify queen-proof.json \
  --queen-table queen.gz queen.json
```

## What this does not prove

- The value of the ordinary 32-piece initial position remains **UNKNOWN**.
- These tables do not solve arbitrary positions with 4–32 pieces.
- Table entries used as leaves with arbitrary historic halfmove clocks,
  en-passant/castling rights or repetition histories can be misleading; the
  loader refuses to use them unless its narrow assumptions hold.
- Free public standard GitHub Actions compute is not mathematically
  unbounded. The workflow uses one capped job per piece, not a continuous
  infinite search.
