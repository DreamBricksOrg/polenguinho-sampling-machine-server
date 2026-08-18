import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
INVENTORY_FILE = BASE_DIR / "static" / "sample" / "assets" / "inventory.json"


class InventoryRepository:
    def __init__(self, file_path: Path = INVENTORY_FILE):
        self.file_path = file_path

    def load(self) -> dict:
        try:
            with self.file_path.open("r", encoding="utf-8") as file:
                return json.load(file)
        except FileNotFoundError:
            return {}

    def save(self, data: dict) -> None:
        with self.file_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=4, ensure_ascii=False)
