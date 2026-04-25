# Proofs

Cryptographic timestamps proving that the source code in this repository
existed at a specific point in time, anchored to the Bitcoin blockchain via
[OpenTimestamps](https://opentimestamps.org/).

## Why

Each `.tar.gz` is a `git archive` snapshot of the repository at a given commit.
Its `.ots` companion is a proof that the SHA-256 hash of that tarball was
submitted to public OTS calendars (and ultimately committed to a Bitcoin
block). Together they let anyone verify, years later, that the code existed
on or before the proof's timestamp — without trusting GitHub, the author, or
this repository.

## Files

```
snapshot-<YYYY-MM-DD>-<commit>.tar.gz       # Reproducible repo snapshot
snapshot-<YYYY-MM-DD>-<commit>.tar.gz.ots   # Proof file
stamp.sh                                     # Helper: create a new proof
```

## Verify an existing proof

```bash
# Install once
python3 -m venv ~/.local/ots-venv
~/.local/ots-venv/bin/pip install opentimestamps-client

# Wait at least a few hours after stamping, then upgrade the proof
~/.local/ots-venv/bin/ots upgrade proofs/snapshot-2026-04-26-342ea35.tar.gz.ots

# Verify against Bitcoin (uses public block explorers)
~/.local/ots-venv/bin/ots verify proofs/snapshot-2026-04-26-342ea35.tar.gz.ots
```

`ots verify` outputs the block height and Unix time at which the hash was
included in Bitcoin — the legal "no later than" timestamp.

## Create a new proof (milestones, releases)

```bash
bash proofs/stamp.sh           # label = today's date
bash proofs/stamp.sh v1.0      # custom label
```

Commit both the `.tar.gz` and `.ots` files. After ~1–24 hours run
`ots upgrade <file>.ots` and commit again — this attaches the actual
Bitcoin block confirmation (otherwise the proof is "pending").
