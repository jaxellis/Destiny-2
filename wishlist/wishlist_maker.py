import json
from typing import Any, Dict, List, Optional, Iterable, TextIO, cast
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

WISHLIST_PREFIX_ITEM = (
    "dimwishlist:item="  # Prefix for item entries in the wishlist, required by DIM
)
WISHLIST_PREFIX_PERK = "&perks="  # Separator for perks, required by DIM
FILE_NAME_OUTPUT = "wishlist.txt"  # Output file name for the generated wishlist
DATA_FOLDER = (
    Path(__file__).resolve().parent / "data"  # Folder containing input JSON files
)
DEFAULT_LOG_LEVEL = "INFO"  # Change to "DEBUG" for more verbose logging
LOG_BACKUP_COUNT = 1  # Number of backup log files to keep
LOG_MAX_BYTES = 2_000_000  # Max size of log file in bytes before rotation (2MB)


def setup_logging() -> None:
    log_dir: Path = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file: Path = log_dir / "wishlist_maker.log"

    logger: logging.Logger = logging.getLogger()
    logger.setLevel(DEFAULT_LOG_LEVEL)

    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    console_handler: logging.StreamHandler[TextIO] = logging.StreamHandler()
    console_handler.setLevel(DEFAULT_LOG_LEVEL)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        log_file, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setLevel(DEFAULT_LOG_LEVEL)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logging.getLogger().info("Logging initialized (level=%s)", DEFAULT_LOG_LEVEL)


def combine_json(file_paths: Iterable[Path]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Load and combine JSON data from an iterable of file paths.
    Each file may contain either a dict mapping weapon type to lists
    or a list of items (will be stored under the file stem).
    """
    file_paths_list = list(file_paths)
    combined_json: Dict[str, List[Dict[str, Any]]] = {}
    logging.debug("combine_json: starting with %d files", len(file_paths_list))

    def load_json_file(p: Path) -> Any:
        with open(p, encoding="utf-8") as json_file:
            data = json.load(json_file)
            logging.debug("Loaded JSON file %s (type=%s)", p, type(data).__name__)
            return data

    for json_file in sorted(file_paths_list):
        logging.debug("Processing file %s", json_file)
        try:
            data = load_json_file(json_file)
        except json.JSONDecodeError as exc:
            logging.error("File '%s' is not a valid JSON file: %s", json_file, exc)
            continue
        if isinstance(data, dict):
            for key, value in cast(dict[str, Any], data).items():
                if isinstance(value, list):
                    combined_json.setdefault(str(key), []).extend(
                        cast(list[Dict[str, Any]], value)
                    )
                else:
                    logging.warning(
                        "Skipping key '%s' in file %s because value is not a list",
                        str(key),
                        json_file,
                    )
        elif isinstance(data, list):
            combined_json.setdefault(json_file.stem, []).extend(
                cast(list[Dict[str, Any]], data)
            )
        else:
            logging.warning(
                "File %s contains unsupported JSON root type %s",
                json_file,
                type(data).__name__,
            )
    logging.debug("combine_json: combined keys=%s", list(combined_json.keys()))
    for k, v in combined_json.items():
        logging.debug("combine_json: key '%s' has %d entries", k, len(v))
    return combined_json


def create_file(file_path: str, data: str) -> None:
    """Creates a file with the provided data in the script's directory."""
    out_path = Path(file_path)
    if not out_path.is_absolute():
        out_path = Path(__file__).resolve().parent / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(out_path, "w", encoding="utf-8") as output_file:
            output_file.write(data)
        logging.info("Wrote output file %s (%d bytes)", out_path, len(data))
    except Exception as exc:  # pragma: no cover - defensive logging
        logging.exception("Failed to write output file %s: %s", out_path, exc)


def create_weapon_type(name: str) -> str:
    """Creates a header for a weapon type."""
    return f"//////////////////////////\n// {name}\n//////////////////////////\n\n"


def create_item_entry(
    item_id: str, perks: Optional[List[int]], notes: str, perk_name: str
) -> str:
    """Creates an entry for a wishlist item."""
    logging.debug(
        "create_item_entry: item_id=%s perks=%s notes_len=%d perk_name=%s",
        item_id,
        perks,
        len(notes),
        perk_name,
    )
    entry = f"{WISHLIST_PREFIX_ITEM}{item_id}"

    if perks is not None:
        entry += WISHLIST_PREFIX_PERK
        if perks:
            entry += ",".join(map(str, perks))

    if notes:
        entry += f"#notes: {notes}"

    return f"{entry}\n"


def main() -> None:
    setup_logging()
    logging.info("Starting wishlist_maker.py")
    if not DATA_FOLDER.exists():
        logging.error("Data folder '%s' not found.", DATA_FOLDER)
        return
    if not DATA_FOLDER.is_dir():
        logging.error("Data path '%s' is not a directory.", DATA_FOLDER)
        return
    json_files = sorted(DATA_FOLDER.glob("*.json"))
    if not json_files:
        logging.error("No JSON files found in data folder '%s'.", DATA_FOLDER)
        return
    logging.info("Found %d JSON files in %s", len(json_files), DATA_FOLDER)
    wishlist_json: Any = combine_json(json_files)
    if not wishlist_json:
        logging.error("No valid JSON data found in data folder '%s'.", DATA_FOLDER)
        return
    wishlist_data: str = ""
    logging.info("Processing %d weapon groups", len(wishlist_json))
    for weapon, weapon_items in wishlist_json.items():
        logging.info("Processing weapon '%s'", weapon)
        wishlist_data += create_weapon_type(weapon)
        if not isinstance(weapon_items, list):
            logging.warning(
                "Skipping weapon '%s' because its value is not a list", weapon
            )
            continue
        for item in cast(list[dict[str, Any]], weapon_items):
            logging.debug("Processing item '%s'", item.get("name", ""))
            wishlist_data += f"// {item.get('name', '')}\n\n"
            for item_id in cast(list[int], item.get("ids", [])):
                logging.debug(
                    "Processing item id %s (trash=%s)", item_id, item.get("trash")
                )
                if item.get("trash"):
                    wishlist_data += f"{WISHLIST_PREFIX_ITEM}-{item_id}\n"
                    continue
                for perk in cast(list[dict[str, Any]], item.get("perkcombo", [])):
                    perk_ids: list[int] | None = (
                        cast(list[int], perk.get("ids"))
                        if perk.get("ids") is not None
                        else None
                    )
                    perk_notes: str = str(perk.get("notes", ""))
                    perk_name: str = str(perk.get("name", ""))
                    wishlist_data += create_item_entry(
                        str(item_id), perk_ids, perk_notes, perk_name
                    )
                for perk in cast(list[dict[str, Any]], item.get("trashcombos", [])):
                    perk_ids = (
                        cast(list[int], perk.get("ids"))
                        if perk.get("ids") is not None
                        else None
                    )
                    perk_notes = str(perk.get("notes", ""))
                    perk_name = str(perk.get("name", ""))
                    wishlist_data += create_item_entry(
                        "-" + str(item_id), perk_ids, perk_notes, perk_name
                    )
            wishlist_data += "\n"
    create_file(FILE_NAME_OUTPUT, wishlist_data)
    logging.info("Completed wishlist generation; output in %s", FILE_NAME_OUTPUT)


if __name__ == "__main__":
    main()
