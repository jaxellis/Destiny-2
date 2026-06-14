# Wishlist — wishlist_maker

## Overview

This folder contains a small utility, `wishlist_maker.py`, that converts structured JSON data into a wishlist text file compatible with Destiny Item Manager (DIM).

## Contents

- `wishlist_maker.py` — script that reads JSON files from the `data/` directory and writes `wishlist.txt` in the repository root.
- `data/` — one JSON file per weapon type (or lists of items). See existing files for examples.
- `logs/` — runtime logs created by the script.

## Requirements

- Python 3.10 or newer (the code uses modern typing syntax).

## Usage

From the repository root run:

```bash
python wishlist/wishlist_maker.py
```

## Behavior

- The script scans `wishlist/data/` for `*.json` files and combines them.
- It writes a DIM-compatible `wishlist.txt` file in the script directory (near the repo root) and logs details to `wishlist/logs/wishlist_maker.log`.

## Data format

- Each JSON file may either be a dictionary mapping weapon groups to lists of items, or a top-level list of items. Each item should include `ids`, `perkcombo`, and optional `trash`/`trashcombos` entries — refer to the example JSON files in `data/` for the expected structure.

## Notes

- If no JSON files are present the script will log an error and exit.
- You can change the logging verbosity by adjusting `DEFAULT_LOG_LEVEL` inside `wishlist/wishlist_maker.py`.
