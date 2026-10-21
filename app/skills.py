import csv
from functools import lru_cache
from hashlib import sha256
from pathlib import Path


ALIASES_PATH = Path(__file__).resolve().parents[1] / "config" / "skill_aliases.csv"


@lru_cache(maxsize=1)
def skill_aliases() -> dict[str, str]:
    with ALIASES_PATH.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    aliases = {}
    for row in rows:
        alias, canonical = row["alias"], row["canonical"]
        if not alias or not canonical or alias != alias.strip().casefold() or canonical != canonical.strip().casefold():
            raise ValueError("Skill aliases must be nonempty normalized strings")
        if alias in aliases:
            raise ValueError(f"Duplicate skill alias: {alias}")
        aliases[alias] = canonical
    if any(canonical in aliases for canonical in aliases.values()):
        raise ValueError("Chained skill aliases are not supported")
    return aliases


def normalize_skill(skill: str) -> str:
    value = skill.strip().casefold()
    return skill_aliases().get(value, value)


def aliases_sha256() -> str:
    return sha256(ALIASES_PATH.read_bytes()).hexdigest()
