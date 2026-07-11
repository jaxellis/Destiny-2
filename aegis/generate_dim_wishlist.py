#!/usr/bin/env python3
"""Build a strict DIM wishlist from Aegis' Endgame Analysis workbook.

The workbook contains newline-separated recommended options in the Barrel, Mag,
Perk 1, Perk 2, and Origin Trait columns.  This program resolves those names
against the Destiny manifest, then writes DIM's ``dimwishlist:item=`` format.

The strict matching policy intentionally follows the PPC selector convention in
charlesxcaliber/DIMAegisWeaponWishlist:

* Barrel, Mag, and Origin Trait are optional bonuses.
* Perk 1 and Perk 2 are the required columns.
* A required column contributes every two-perk combination.  If it has a
  single recommended perk, that one perk is required instead.

Consequently, a weapon with P1=[A, B, C] and P2=[D, E, F] produces nine core
entries: (A,B) x (D,E), (A,B) x (D,F), ... (B,C) x (E,F).  DIM evaluates each
entry independently, so a hit cannot be produced by a partial core pair.

The provided manifest.json is Bungie's manifest *index*, not the inventory item
definitions themselves.  On its first run this script downloads the referenced
English DestinyInventoryItemDefinition file into .manifest-cache/.  Later runs
reuse that cache, making normal generation fully local.
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import re
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

import pandas as pd

SCRIPT_DIR = Path(__file__).parent
DEFAULT_WORKBOOK = SCRIPT_DIR / "Destiny 2_ Endgame Analysis.xlsx"
DEFAULT_MANIFEST = SCRIPT_DIR / "manifest.json"
DEFAULT_OUTPUT = "aegis_strict_dim_wishlist.txt"
CORE_COLUMNS = ("Perk 1", "Perk 2")
BONUS_COLUMNS = ("Barrel", "Mag", "Origin Trait")
REQUIRED_PERKS_PER_COLUMN = 2
ACTIVE_TIERS = frozenset({"S", "A"})
TIER_ORDER = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6}


@dataclass(frozen=True)
class SpreadsheetWeapon:
    """One ranked weapon row from a worksheet."""

    sheet: str
    name: str
    tier: str
    notes: str
    perks: dict[str, tuple[str, ...]]


@dataclass
class ManifestIndex:
    """Name indexes built from DestinyInventoryItemDefinition."""

    weapons: Mapping[str, tuple[int, ...]]
    plugs: Mapping[str, tuple[int, ...]]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spreadsheet", type=Path, default=Path(DEFAULT_WORKBOOK))
    parser.add_argument("--manifest", type=Path, default=Path(DEFAULT_MANIFEST))
    parser.add_argument("--output", type=Path, default=Path(DEFAULT_OUTPUT))
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".manifest-cache"),
        help="Directory used for the downloaded inventory definition cache.",
    )
    parser.add_argument(
        "--required-perks-per-column",
        type=int,
        default=REQUIRED_PERKS_PER_COLUMN,
        help="Required Perk 1/Perk 2 recommendations per DIM entry (default: 2).",
    )
    parser.add_argument(
        "--sheet",
        action="append",
        dest="sheets",
        help="Only process this worksheet; specify more than once for multiple sheets.",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def normalise_name(value: str) -> str:
    """Normalise display names without losing meaningful punctuation."""

    value = value.replace("\u2019", "'").replace("\u2018", "'")
    value = re.sub(r"\s+", " ", value.strip())
    return value.casefold()


def weapon_name_candidates(name: str) -> Iterator[str]:
    """Yield exact and worksheet-only aliases in preference order."""

    cleaned = re.sub(r"\s+", " ", name.replace("\n", " ")).strip()
    yield cleaned

    # Aegis uses labels such as "Edge Transit\nBRAVE version" to distinguish
    # sources.  They are not part of Bungie's item display name.
    without_version = re.sub(
        r"\s*[\[(](?:pantheon|brave|rotn)\s+version[\])]|\s+(?:pantheon|brave|rotn)\s+version$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    if without_version and without_version != cleaned:
        yield without_version


def as_cell_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def split_recommendations(value: Any) -> tuple[str, ...]:
    """Return unique spreadsheet recommendations, preserving sheet order."""

    text = as_cell_text(value)
    if not text or text.casefold() in {"n/a", "na", "none", "-"}:
        return ()
    items = (part.strip() for part in re.split(r"[\r\n]+", text))
    return tuple(dict.fromkeys(item for item in items if item))


def canonical_tier(value: Any) -> str:
    """Map A+/A- notation to the A-to-F/S threshold used by the generator."""

    match = re.fullmatch(r"\s*([SABCDEF])(?:[+-])?\s*", as_cell_text(value).upper())
    return match.group(1) if match else ""


def find_header_row(raw: pd.DataFrame) -> int | None:
    """Find the row that contains the Aegis weapon-table field names."""

    required = {"name", "perk 1", "perk 2", "tier"}
    for row_number in range(min(len(raw.index), 8)):
        found = {normalise_name(as_cell_text(value)) for value in raw.iloc[row_number]}
        if required.issubset(found):
            return row_number
    return None


def read_spreadsheet(
    path: Path, requested_sheets: Sequence[str] | None
) -> list[SpreadsheetWeapon]:
    """Read current Aegis weapon tabs and return rows with an explicit tier."""

    workbook = pd.ExcelFile(path)
    available = workbook.sheet_names
    if requested_sheets:
        missing = sorted(set(requested_sheets) - set(available))
        if missing:
            raise ValueError(f"Worksheet(s) not found: {', '.join(missing)}")
        sheets = list(requested_sheets)
    else:
        # Old tabs are historical snapshots, not the current tier list.
        sheets = [sheet for sheet in available if "(old)" not in sheet.casefold()]

    weapons: list[SpreadsheetWeapon] = []
    for sheet in sheets:
        raw = pd.read_excel(path, sheet_name=sheet, header=None, dtype=object)
        header_row = find_header_row(raw)
        if header_row is None:
            continue

        table = raw.iloc[header_row + 1 :].copy()
        table.columns = [as_cell_text(cell) for cell in raw.iloc[header_row]]
        # Some workbook tabs have a duplicate blank column.  It is never a
        # recommendation field, and pandas lets us safely retain the named one.
        table = table.loc[:, ~table.columns.duplicated()]
        required = {"Name", "Perk 1", "Perk 2", "Tier"}
        if not required.issubset(table.columns):
            logging.warning("Skipping %s: missing columns after header parsing", sheet)
            continue

        for _, row in table.iterrows():
            name = as_cell_text(row["Name"])
            tier = canonical_tier(row["Tier"])
            if not name or tier not in TIER_ORDER:
                continue
            perks = {
                column: split_recommendations(row[column])
                if column in table.columns
                else ()
                for column in (*BONUS_COLUMNS, *CORE_COLUMNS)
            }
            weapons.append(
                SpreadsheetWeapon(
                    sheet=sheet,
                    name=name,
                    tier=tier,
                    notes=as_cell_text(row["Notes"])
                    if "Notes" in table.columns
                    else "",
                    perks=perks,
                )
            )
    return weapons


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    logging.info("Downloading Destiny inventory definitions to %s", destination)
    try:
        with (
            urllib.request.urlopen(url, timeout=120) as response,
            temporary.open("wb") as output,
        ):
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def inventory_definitions(manifest_path: Path, cache_dir: Path) -> Mapping[str, Any]:
    """Load a full item-definition file or resolve a Bungie manifest index."""

    with manifest_path.open(encoding="utf-8") as source:
        manifest = json.load(source)

    if "DestinyInventoryItemDefinition" in manifest:
        definitions = manifest["DestinyInventoryItemDefinition"]
        if not isinstance(definitions, Mapping):
            raise ValueError("DestinyInventoryItemDefinition is not an object")
        return definitions

    response = manifest.get("Response", manifest)
    try:
        relative_url = response["jsonWorldComponentContentPaths"]["en"][
            "DestinyInventoryItemDefinition"
        ]
    except (KeyError, TypeError) as error:
        raise ValueError(
            "Manifest must be a full item-definition JSON or a Bungie manifest index."
        ) from error

    if not isinstance(relative_url, str) or not relative_url.endswith(".json"):
        raise ValueError("Manifest inventory-definition URL is invalid")
    cache_file = cache_dir / Path(relative_url).name
    if not cache_file.exists():
        download(f"https://www.bungie.net{relative_url}", cache_file)
    with cache_file.open(encoding="utf-8") as source:
        definitions = json.load(source)
    if not isinstance(definitions, Mapping):
        raise ValueError("Downloaded inventory definitions are not an object")
    return definitions


def build_manifest_index(definitions: Mapping[str, Any]) -> ManifestIndex:
    weapons: dict[str, list[int]] = defaultdict(list)
    plugs: dict[str, list[int]] = defaultdict(list)
    for raw_hash, definition in definitions.items():
        if not isinstance(definition, Mapping):
            continue
        display = definition.get("displayProperties")
        if not isinstance(display, Mapping):
            continue
        name = as_cell_text(display.get("name"))
        if not name:
            continue
        try:
            item_hash = int(raw_hash)
        except (TypeError, ValueError):
            continue
        key = normalise_name(name)
        item_type = definition.get("itemType")
        if item_type == 3:
            if item_hash not in weapons[key]:
                weapons[key].append(item_hash)
        # Item type 19 is a Destiny plug (weapon perk, barrel, magazine, or
        # origin trait).  Indexing every non-weapon item creates name collisions
        # with triumphs, cosmetics, and lore entries and explodes the Cartesian
        # product of combinations.
        elif item_type == 19:
            # DIM normalises enhanced perks to their normal version.  Keeping
            # both hashes would turn every enhanced/non-enhanced duplicate into
            # an artificial extra recommendation and produce millions of lines.
            tier_label = as_cell_text(definition.get("itemTypeAndTierDisplayName"))
            if "enhanced" not in tier_label.casefold() and key not in plugs:
                # Manifest order consistently puts the canonical plug ahead of
                # duplicate compatibility plugs with the same visible name.
                plugs[key].append(item_hash)
    return ManifestIndex(
        weapons={name: tuple(hashes) for name, hashes in weapons.items()},
        plugs={name: tuple(hashes) for name, hashes in plugs.items()},
    )


def resolve_weapon_hashes(name: str, index: ManifestIndex) -> tuple[int, ...]:
    for candidate in weapon_name_candidates(name):
        hashes = index.weapons.get(normalise_name(candidate))
        if hashes:
            return hashes
    return ()


def resolve_perk_hashes(
    names: Iterable[str], index: ManifestIndex, weapon_name: str
) -> tuple[int, ...]:
    hashes: list[int] = []
    for name in names:
        matched = index.plugs.get(normalise_name(name), ())
        if not matched:
            logging.warning("%s: perk not found in manifest: %s", weapon_name, name)
            continue
        hashes.extend(matched)
    return tuple(dict.fromkeys(hashes))


def constrained_combinations(
    perks: Sequence[int], required: int
) -> tuple[tuple[int, ...], ...]:
    """Return exact-sized combinations, with the single-option exception."""

    if not perks:
        return ()
    count = 1 if len(perks) == 1 else required
    if len(perks) < count:
        # The sheet has fewer recommendations than the requested strictness.
        # It is still safest to require every available recommendation.
        count = len(perks)
    return tuple(itertools.combinations(perks, count))


def optional_variants(bonus_perks: Sequence[int]) -> tuple[tuple[int, ...], ...]:
    """Include all optional bonus subsets so missing bonuses do not block a hit."""

    return tuple(
        combination
        for length in range(len(bonus_perks) + 1)
        for combination in itertools.combinations(bonus_perks, length)
    )


def active_perk_sets(
    weapon: SpreadsheetWeapon, index: ManifestIndex, required_perks: int
) -> tuple[tuple[int, ...], ...]:
    """Create every strict core combination plus optional bonus variants."""

    core = [
        constrained_combinations(
            resolve_perk_hashes(weapon.perks[column], index, weapon.name),
            required_perks,
        )
        for column in CORE_COLUMNS
    ]
    if not all(core):
        missing = [
            column
            for column, combinations in zip(CORE_COLUMNS, core)
            if not combinations
        ]
        logging.warning(
            "%s: omitted from active list; no resolvable %s",
            weapon.name,
            ", ".join(missing),
        )
        return ()

    bonus = tuple(
        dict.fromkeys(
            hash_value
            for column in BONUS_COLUMNS
            for hash_value in resolve_perk_hashes(
                weapon.perks[column], index, weapon.name
            )
        )
    )
    entries = {
        tuple((*core_one, *core_two, *optional))
        for core_one, core_two, optional in itertools.product(
            *core, optional_variants(bonus)
        )
    }
    # The most complete roll first, then a stable deterministic order.
    return tuple(sorted(entries, key=lambda entry: (-len(entry), entry)))


def write_wishlist(
    output: Path,
    weapons: Sequence[SpreadsheetWeapon],
    index: ManifestIndex,
    required_perks: int,
) -> tuple[int, int, int]:
    active_entries = 0
    trash_entries = 0
    unresolved_weapons = 0
    lines = [
        "title: Aegis Strict Endgame Wishlist",
        "description: S/A active rolls; B-F weapons explicitly marked as trash. "
        f"Requires {required_perks} recommended Perk 1 and Perk 2 options per entry "
        "(one when only one recommendation exists).",
        "",
    ]

    for sheet, group in itertools.groupby(weapons, key=lambda weapon: weapon.sheet):
        lines.extend(
            (
                "//////////////////////////",
                f"// {sheet}",
                "//////////////////////////",
                "",
            )
        )
        for weapon in group:
            hashes = resolve_weapon_hashes(weapon.name, index)
            if not hashes:
                unresolved_weapons += 1
                logging.warning("%s: weapon not found in manifest", weapon.name)
                continue

            if weapon.tier in ACTIVE_TIERS:
                combinations = active_perk_sets(weapon, index, required_perks)
                if not combinations:
                    continue
                note = f"{weapon.tier}-Tier"
                if weapon.notes:
                    note += f". {weapon.notes}"
                lines.extend((f"// {weapon.name}", f"//notes: {note}"))
                for weapon_hash in hashes:
                    for perks in combinations:
                        lines.append(
                            f"dimwishlist:item={weapon_hash}&perks={','.join(map(str, perks))}"
                        )
                        active_entries += 1
            else:
                note = f"{weapon.tier}-Tier"
                if weapon.notes:
                    note += f". {weapon.notes}"
                lines.extend((f"// {weapon.name}", f"//notes: {note}"))
                for weapon_hash in hashes:
                    lines.append(f"dimwishlist:item=-{weapon_hash}")
                    trash_entries += 1
            lines.append("")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    return active_entries, trash_entries, unresolved_weapons


def main() -> int:
    args = parse_arguments()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    if args.required_perks_per_column < 1:
        raise ValueError("--required-perks-per-column must be at least 1")
    if not args.spreadsheet.exists() or not args.manifest.exists():
        missing = [
            str(path) for path in (args.spreadsheet, args.manifest) if not path.exists()
        ]
        raise FileNotFoundError(f"Input file(s) not found: {', '.join(missing)}")

    weapons = read_spreadsheet(args.spreadsheet, args.sheets)
    if not weapons:
        raise ValueError(
            "No ranked weapon rows were found in the selected worksheet(s)"
        )
    definitions = inventory_definitions(args.manifest, args.cache_dir)
    index = build_manifest_index(definitions)
    active, trash, unresolved = write_wishlist(
        args.output, weapons, index, args.required_perks_per_column
    )
    logging.info(
        "Wrote %s (%d active entries, %d trash entries, %d unresolved weapons)",
        args.output,
        active,
        trash,
        unresolved,
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        logging.error("Generation failed: %s", error)
        raise SystemExit(1) from error
