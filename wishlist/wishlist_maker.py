import json
from typing import Any, Dict, List, Optional

WISHLIST_PREFIX_ITEM = "dimwishlist:item="
WISHLIST_PREFIX_PERK = "&perks="
FILE_NAME_OUTPUT = "wishlist.txt"
FILE_NAME_INPUT = "wishlist_data.json"


def open_file_as_json(file_path: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Opens and loads the content of the file.
    Returns the loaded JSON data.
    """
    with open(file_path) as json_file:
        return json.load(json_file)


def create_file(file_path: str, data: str) -> None:
    """Creates a file with the provided data."""
    with open(file_path, "w") as output_file:
        output_file.write(data)


def create_weapon_type(name: str) -> str:
    """Creates a header for a weapon type."""
    return f"//////////////////////////\n// {name}\n//////////////////////////\n\n"


def create_item_entry(
    item_id: str, perks: Optional[List[int]], notes: str, perk_name: str
) -> str:
    """Creates an entry for a wishlist item."""
    entry: str = f"// {perk_name}\n" if perk_name else ""
    entry += f"{WISHLIST_PREFIX_ITEM}{item_id}"

    if perks is not None:
        entry += WISHLIST_PREFIX_PERK
        if perks:
            entry += ",".join(map(str, perks))
        if notes:
            entry += f"#notes: {notes}"

    return f"{entry}\n"


def main() -> None:
    try:
        wishlist_json: Any = open_file_as_json(FILE_NAME_INPUT)
    except FileNotFoundError:
        print(f"Error: File '{FILE_NAME_INPUT}' not found.")
        return
    except json.JSONDecodeError:
        print(f"Error: File '{FILE_NAME_INPUT}' is not a valid JSON file.")
        return

    wishlist_data: str = ""

    for weapon, items in wishlist_json.items():
        wishlist_data += create_weapon_type(weapon)
        for item in items:
            wishlist_data += f'// {item["name"]}\n\n'
            for item_id in item["ids"]:
                if item["trash"]:
                    wishlist_data += f"{WISHLIST_PREFIX_ITEM}-{item_id}\n"
                    continue
                if item["perkcombo"]:
                    for perk in item["perkcombo"]:
                        wishlist_data += create_item_entry(
                            str(item_id),
                            perk["ids"],
                            perk["notes"] if "notes" in perk else "",
                            perk["name"],
                        )
                if item["trashcombos"]:
                    for perk in item["trashcombos"]:
                        wishlist_data += create_item_entry(
                            "-" + str(item_id),
                            perk["ids"],
                            perk["notes"] if "notes" in perk else "",
                            perk["name"],
                        )
            wishlist_data += "\n"  # New line between weapons

    create_file(FILE_NAME_OUTPUT, wishlist_data)


if __name__ == "__main__":
    main()
