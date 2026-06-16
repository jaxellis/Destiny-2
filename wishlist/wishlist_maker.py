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
            for key, value in cast(Dict[str, Any], data).items():
                if isinstance(value, list):
                    combined_json.setdefault(str(key), []).extend(
                        cast(List[Dict[str, Any]], value)
                    )
                else:
                    logging.warning(
                        "Skipping key '%s' in file %s because value is not a list",
                        str(key),
                        json_file,
                    )
        elif isinstance(data, list):
            combined_json.setdefault(json_file.stem, []).extend(
                cast(List[Dict[str, Any]], data)
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
    entry: str = f"// {perk_name}\n" if perk_name else ""
    entry += f"{WISHLIST_PREFIX_ITEM}{item_id}"

    if perks is not None:
        entry += WISHLIST_PREFIX_PERK
        if perks:
            entry += ",".join(map(str, perks))

    if notes:
        entry += f"#notes: {notes}"

    return f"{entry}\n"


def load_perks_by_id(data_folder: Path) -> Dict[str, str]:
    """Load `perks_by_id.json` and return mapping id->name."""
    path = data_folder / "perks" / "perks_by_id.json"
    if not path.exists():
        logging.info("perks_by_id.json not found at %s; perk names will be empty", path)
        return {}
    try:
        with open(path, encoding="utf-8") as pf:
            data = json.load(pf)
            if isinstance(data, dict):
                data_dict: Dict[str, Any] = cast(Dict[str, Any], data)
                return {str(k): str(v) for k, v in data_dict.items()}
            logging.warning("perks_by_id.json does not contain an object; ignoring")
    except Exception as exc:
        logging.warning("Failed to load perks_by_id.json: %s", exc)
    return {}


def perk_ids_to_name(
    perks_by_id: Dict[str, str], perk_ids: Optional[List[int]], item_name: str
) -> str:
    """Return a joined name string for a list of perk ids, logging missing ids."""
    if not perk_ids:
        return ""
    names: List[str] = []
    for pid in perk_ids:
        pname = perks_by_id.get(str(pid))
        if pname is None:
            logging.warning(
                "Perk id %s not found in perks_by_id.json (item=%s)", pid, item_name
            )
            pname = ""
        names.append(pname)
    return ", ".join(n for n in names if n)


def format_item_block(item: Dict[str, Any], perks_by_id: Dict[str, str]) -> str:
    """Return the wishlist block for a single item, including all perk combos."""
    out = f"// {item.get('name', '')}\n\n"
    for item_id in cast(List[int], item.get("ids", [])):
        logging.debug("Processing item id %s (trash=%s)", item_id, item.get("trash"))
        if item.get("trash"):
            out += f"{WISHLIST_PREFIX_ITEM}-{item_id}\n"
            continue
        for perk in cast(List[Dict[str, Any]], item.get("perkcombo", [])):
            perk_ids: List[int] | None = (
                cast(List[int], perk.get("ids"))
                if perk.get("ids") is not None
                else None
            )
            perk_notes: str = str(perk.get("notes", ""))
            perk_name = perk_ids_to_name(perks_by_id, perk_ids, item.get("name", ""))
            out += create_item_entry(str(item_id), perk_ids, perk_notes, perk_name)
        for perk in cast(List[Dict[str, Any]], item.get("trashcombos", [])):
            perk_ids = (
                cast(List[int], perk.get("ids"))
                if perk.get("ids") is not None
                else None
            )
            perk_notes = str(perk.get("notes", ""))
            perk_name = perk_ids_to_name(perks_by_id, perk_ids, item.get("name", ""))
            out += create_item_entry(
                "-" + str(item_id), perk_ids, perk_notes, perk_name
            )
    out += "\n"
    return out


def verify_setup_integrity() -> None | Dict[str, List[Dict[str, Any]]]:
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
    return combine_json(json_files)


def main() -> None:
    setup_logging()
    wishlist_json: None | Dict[str, List[Dict[str, Any]]] = verify_setup_integrity()
    if not wishlist_json:
        logging.error("No valid JSON data found in data folder '%s'.", DATA_FOLDER)
        return
    perks_by_id: Dict[str, str] = load_perks_by_id(DATA_FOLDER)

    wishlist_data: str = ""
    logging.info("Processing %d weapon groups", len(wishlist_json))
    for weapon, weapon_items in wishlist_json.items():
        logging.info("Processing weapon '%s'", weapon)
        wishlist_data += create_weapon_type(weapon)
        for item in weapon_items:
            logging.debug("Processing item '%s'", item.get("name", ""))
            wishlist_data += format_item_block(item, perks_by_id)

    create_file(FILE_NAME_OUTPUT, wishlist_data)
    logging.info("Completed wishlist generation; output in %s", FILE_NAME_OUTPUT)


if __name__ == "__main__":
    main()
