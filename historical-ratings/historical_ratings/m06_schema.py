"""Madden NFL 06 (USA PS2, SLUS-21213) target rating schema.

Every rating tag below was read from the shipped Madden06Editor v0.1.0-alpha
(``editing.RATING_FIELDS`` / ``editing.VERIFIED_RATING_FIELDS``). That editor's
``patch_player`` refuses any rating field whose bit width is not 7 and any value
outside 0..99, and its release validation compared all 21 labels against game
screens in PCSX2. Nothing here is a new or guessed field mapping.

Position codes are different: the editor only ever displays the raw numeric
``PPOS`` value. ``PPOS_CONVENTION`` is the community TDB convention used by
Madden 2004-2008 tools and is NOT verified for this disc. ``check_position_codes``
tests it against the real roster before any baseline is accepted.
"""

from __future__ import annotations

from statistics import median

# Order and labels are copied from editing.RATING_FIELDS.
RATING_FIELDS: dict[str, str] = {
    "PSPD": "Speed",
    "PACC": "Acceleration",
    "PSTR": "Strength",
    "PAGI": "Agility",
    "PAWR": "Awareness",
    "PTHP": "Throw power",
    "PTHA": "Throw accuracy",
    "PCTH": "Catching",
    "PTAK": "Tackling",
    "PCAR": "Carrying",
    "PJMP": "Jumping",
    "PBTK": "Break tackle",
    "PPBK": "Pass blocking",
    "PRBK": "Run blocking",
    "PKPR": "Kick power",
    "PKAC": "Kick accuracy",
    "PKRT": "Kick return",
    "PIMP": "Importance",
    "PSTA": "Stamina",
    "PINJ": "Injury",
    "PTGH": "Toughness",
}
TARGET_TAGS: tuple[str, ...] = tuple(RATING_FIELDS)
RATING_MIN = 0
RATING_MAX = 99
RATING_BITS = 7

SCHEMA_EVIDENCE = (
    "Madden06Editor v0.1.0-alpha: editing.RATING_FIELDS == VERIFIED_RATING_FIELDS "
    "(21 tags); patch_player enforces 7-bit width and 0..99; RELEASE_VALIDATION.md "
    "records the 21 labels compared against game screens in PCSX2."
)

# Read-only context fields used for baselines and identity. POVR is displayed by
# the editor but never recalculated by it.
CONTEXT_FIELDS: tuple[str, ...] = (
    "PGID", "POID", "TGID", "PPOS", "POVR", "PJEN",
    "PFNA", "PLNA", "PHGT", "PWGT", "PYRP",
)

# Community TDB convention -- UNVERIFIED on this disc until check_position_codes passes.
PPOS_CONVENTION: dict[int, str] = {
    0: "QB", 1: "HB", 2: "FB", 3: "WR", 4: "TE",
    5: "LT", 6: "LG", 7: "C", 8: "RG", 9: "RT",
    10: "LE", 11: "RE", 12: "DT",
    13: "LOLB", 14: "MLB", 15: "ROLB",
    16: "CB", 17: "FS", 18: "SS", 19: "K", 20: "P",
}

# Baseline groups pool mirror-image slots so each sample is large enough.
POSITION_GROUP: dict[str, str] = {
    "QB": "QB", "HB": "HB", "FB": "FB", "WR": "WR", "TE": "TE",
    "LT": "T", "RT": "T", "LG": "G", "RG": "G", "C": "C",
    "LE": "DE", "RE": "DE", "DT": "DT",
    "LOLB": "OLB", "ROLB": "OLB", "MLB": "MLB",
    "CB": "CB", "FS": "FS", "SS": "SS", "K": "K", "P": "P",
}
GROUPS: tuple[str, ...] = (
    "QB", "HB", "FB", "WR", "TE", "T", "G", "C",
    "DE", "DT", "OLB", "MLB", "CB", "FS", "SS", "K", "P",
)

# Typical starters per team, used only to label depth tiers in the baseline.
STARTERS_PER_TEAM: dict[str, int] = {
    "QB": 1, "HB": 1, "FB": 1, "WR": 3, "TE": 1, "T": 2, "G": 2, "C": 1,
    "DE": 2, "DT": 2, "OLB": 2, "MLB": 1, "CB": 2, "FS": 1, "SS": 1, "K": 1, "P": 1,
}


def clamp_rating(value: float) -> int:
    """Round half up and clamp to the verified 0..99 editor bounds."""
    rounded = int(value + 0.5) if value >= 0 else 0
    return max(RATING_MIN, min(RATING_MAX, rounded))


def group_for_code(code: int, convention: dict[int, str] | None = None) -> str | None:
    name = (convention or PPOS_CONVENTION).get(int(code))
    return POSITION_GROUP.get(name) if name else None


def check_position_codes(players: list[dict], convention: dict[int, str] | None = None) -> list[str]:
    """Return failures of data-driven sanity checks on a PPOS convention.

    Each check compares group medians in the real roster. A correct mapping
    should pass them all; an empty list means "consistent", not "proven".
    """
    convention = convention or PPOS_CONVENTION
    by_group: dict[str, list[dict]] = {}
    for p in players:
        g = group_for_code(p["PPOS"], convention)
        if g:
            by_group.setdefault(g, []).append(p)

    def med(group: str, tag: str) -> float:
        rows = by_group.get(group) or []
        return median(r[tag] for r in rows) if rows else float("nan")

    failures: list[str] = []
    missing = [g for g in GROUPS if g not in by_group]
    if missing:
        failures.append(f"No players mapped to groups: {', '.join(missing)}")
        return failures

    def highest(tag: str, expected: set[str], label: str) -> None:
        ranked = sorted(GROUPS, key=lambda g: med(g, tag), reverse=True)
        top = set(ranked[: len(expected)])
        if top != expected:
            failures.append(f"{label}: highest median {tag} groups are {sorted(top)}, expected {sorted(expected)}")

    highest("PTHP", {"QB"}, "Throw power")
    highest("PKPR", {"K", "P"}, "Kick power")
    highest("PPBK", {"T", "G", "C"}, "Pass blocking")
    highest("PCTH", {"WR"}, "Catching")
    for k in ("K", "P"):
        if med(k, "PKAC") <= med("QB", "PKAC"):
            failures.append(f"{k} median PKAC is not above QB median")
    for line in ("DE", "DT"):
        if med(line, "PSTR") <= med("CB", "PSTR"):
            failures.append(f"{line} median PSTR is not above CB median")
    return failures
