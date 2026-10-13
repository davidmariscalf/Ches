# Ches — verified adversarial chess research

This is the **public** repository for bounded, reproducible chess-game analysis.
It does **not** solve standard 32-piece chess. No content or commit history from
the private `Chess` repository is required.

## What is proved, and what is not

- White viewpoint: `-1` means Black wins, `0` draw, `+1` White wins.
- Every uncertain subtree retains the interval **`[-1,+1]`**.
- At White turns, intervals propagate by **maximum**; at Black turns, by
  **minimum**. For each expanded node all legal actions, including optional
  draw claims, must appear in the saved certificate.
- Real terminal checkmates and automatic draws are verified against chess rules.
- External **Syzygy WDL** files are optional, and are a **trusted computational
  assumption, not a formally verified proof**. Their WDL entries are used
  conservatively only with a zero halfmove clock, no repeat history,
  no castling/en-passant rights and at most seven pieces. Cursed/blessed results
  count as draws under the 50-move rule. A missing table never proves anything.

## Run the full suite

```bash
python -m pip install -e ".[test]"
python -m pytest -q
```

Generate a real finite-horizon proof and verify it without trusting the
prover's recorded minimax value:

```bash
python -m ches.cli analyze --fen "7k/Q7/8/6K1/8/8/8/1R6 w - - 0 1" --depth 1 --out mate.json
python -m ches.cli verify mate.json
```

The winning White continuation on this artificial chess position is sufficient
for a `[1,1]` bound even though its siblings remain unknown.

Check the actual starting position without guessing past unsearched frontiers:

```bash
python -m ches.cli analyze --depth 2 --max-nodes 1000 --out initial.json
python -m ches.cli verify initial.json
```

The expected root interval is `[-1,1]`. This is not a 2-ply solution;
it is a certificate that the rest of the game remains unclassified.

For optional exact 3–7-piece lookups, download a matching, licensed Syzygy WDL
collection separately, verify its provenance/checksums, then pass
`--syzygy-dir /path/to/tables` to both `analyze` and `verify`.
Never use a tablebase file merely because a program printed `win`.
The JSON carries its proof tree, not the bytes of the external oracle; the
verifier must have access to the **same trusted oracle data**.

## GitHub Actions

`.github/workflows/verify.yml` executes pytest and regenerates two small
proofs, uploads JSON evidence, and verifies the unknown root. GitHub-hosted
standard runners generally have free unlimited **minutes** for public repos,
but do **not** have unlimited concurrency, job duration, storage, or
API allowances. No infinite compute loop is configured.

## Limitations

This program builds a **finite game tree** only. It has neither complete
7-piece Syzygy datasets bundled nor a proven full-game strategy. The
verifier shares the `python-chess` rules library with the prover, so it is
independent of the prover's choice and score propagation, but **not**
independent of the chess move generator. It cannot guarantee unrestricted
game-theoretic values outside the evidence described above.
