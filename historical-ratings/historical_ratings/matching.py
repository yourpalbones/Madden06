"""Player identity matching that never silently assigns one player's data to another.

Records are plain dicts with ``id``, ``name``, ``team``, ``position`` and optional
``jersey``/``season``. Typical uses: confirming a Madden '95 source player
against a historical roster list, resolving a reviewer's "Barry Sanders, DET"
reference to a source id, and (later) pairing converted players with Madden 06
rows. Only ``matched`` and ``manual`` results may be applied.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

# Common given-name equivalents. Each set is symmetric; keep it conservative.
NICKNAMES = [
    {"steve", "steven", "stephen"}, {"mike", "michael"}, {"jim", "james", "jimmy"},
    {"bob", "robert", "rob", "bobby"}, {"bill", "william", "will", "billy"},
    {"dave", "david"}, {"tom", "thomas", "tommy"}, {"chris", "christopher"},
    {"joe", "joseph", "joey"}, {"dan", "daniel", "danny"}, {"ron", "ronald", "ronnie"},
    {"rick", "richard", "rich", "ricky", "dick"}, {"tony", "anthony"},
    {"ed", "edward", "eddie"}, {"ken", "kenneth", "kenny"}, {"tim", "timothy"},
    {"greg", "gregory"}, {"jeff", "jeffrey"}, {"matt", "matthew"}, {"pat", "patrick"},
    {"nick", "nicholas"}, {"sam", "samuel"}, {"andy", "andrew", "drew"},
    {"larry", "lawrence"}, {"charlie", "charles", "chuck"}, {"don", "donald"},
    {"fred", "frederick"}, {"ray", "raymond"}, {"gene", "eugene"}, {"jerry", "gerald"},
]
_NICK = {}
for group in NICKNAMES:
    for n in group:
        _NICK.setdefault(n, set()).update(group)

# 1994-era team naming. Values are canonical abbreviations.
TEAM_ALIASES = {
    "ari": "ARI", "arizona": "ARI", "arizona cardinals": "ARI", "phoenix": "ARI", "phx": "ARI",
    "phoenix cardinals": "ARI", "cardinals": "ARI",
    "atl": "ATL", "atlanta": "ATL", "falcons": "ATL", "atlanta falcons": "ATL",
    "buf": "BUF", "buffalo": "BUF", "bills": "BUF", "buffalo bills": "BUF",
    "chi": "CHI", "chicago": "CHI", "bears": "CHI", "chicago bears": "CHI",
    "cin": "CIN", "cincinnati": "CIN", "bengals": "CIN", "cincinnati bengals": "CIN",
    "cle": "CLE", "cleveland": "CLE", "browns": "CLE", "cleveland browns": "CLE",
    "dal": "DAL", "dallas": "DAL", "cowboys": "DAL", "dallas cowboys": "DAL",
    "den": "DEN", "denver": "DEN", "broncos": "DEN", "denver broncos": "DEN",
    "det": "DET", "detroit": "DET", "lions": "DET", "detroit lions": "DET",
    "gb": "GB", "gnb": "GB", "green bay": "GB", "packers": "GB", "green bay packers": "GB",
    "hou": "HOU", "houston": "HOU", "oilers": "HOU", "houston oilers": "HOU",
    "ind": "IND", "indianapolis": "IND", "colts": "IND", "indianapolis colts": "IND",
    "kc": "KC", "kan": "KC", "kansas city": "KC", "chiefs": "KC", "kansas city chiefs": "KC",
    "lar": "LARM", "la rams": "LARM", "los angeles rams": "LARM", "rams": "LARM", "ram": "LARM",
    "rai": "LARD", "lard": "LARD", "la raiders": "LARD", "los angeles raiders": "LARD", "raiders": "LARD",
    "mia": "MIA", "miami": "MIA", "dolphins": "MIA", "miami dolphins": "MIA",
    "min": "MIN", "minnesota": "MIN", "vikings": "MIN", "minnesota vikings": "MIN",
    "ne": "NE", "nwe": "NE", "new england": "NE", "patriots": "NE", "new england patriots": "NE",
    "no": "NO", "nor": "NO", "new orleans": "NO", "saints": "NO", "new orleans saints": "NO",
    "nyg": "NYG", "giants": "NYG", "new york giants": "NYG", "ny giants": "NYG",
    "nyj": "NYJ", "jets": "NYJ", "new york jets": "NYJ", "ny jets": "NYJ",
    "phi": "PHI", "philadelphia": "PHI", "eagles": "PHI", "philadelphia eagles": "PHI",
    "pit": "PIT", "pittsburgh": "PIT", "steelers": "PIT", "pittsburgh steelers": "PIT",
    "sd": "SD", "sdg": "SD", "san diego": "SD", "chargers": "SD", "san diego chargers": "SD",
    "sf": "SF", "sfo": "SF", "san francisco": "SF", "49ers": "SF", "niners": "SF", "san francisco 49ers": "SF",
    "sea": "SEA", "seattle": "SEA", "seahawks": "SEA", "seattle seahawks": "SEA",
    "tb": "TB", "tam": "TB", "tampa bay": "TB", "buccaneers": "TB", "bucs": "TB", "tampa bay buccaneers": "TB",
    "was": "WAS", "wash": "WAS", "washington": "WAS", "redskins": "WAS", "washington redskins": "WAS",
}

# Source positions/depth slots that may describe the same player.
POSITION_FAMILY = {
    "QB": "QB", "HB": "RB", "RB": "RB", "FB": "RB", "TB": "RB",
    "WR": "WR", "FL": "WR", "SE": "WR", "TE": "TE",
    "LT": "OL", "LG": "OL", "C": "OL", "RG": "OL", "RT": "OL", "T": "OL", "G": "OL", "OT": "OL", "OG": "OL", "OL": "OL",
    "LE": "DL", "RE": "DL", "DE": "DL", "LDE": "DL", "RDE": "DL", "DT": "DL", "LDT": "DL", "RDT": "DL", "NT": "DL", "DL": "DL",
    "LOLB": "LB", "ROLB": "LB", "OLB": "LB", "MLB": "LB", "ILB": "LB", "LILB": "LB", "RILB": "LB", "LB": "LB",
    "CB": "DB", "LCB": "DB", "RCB": "DB", "LCB1": "DB", "RCB1": "DB", "LCB2": "DB", "RCB2": "DB",
    "S": "DB", "FS": "DB", "SS": "DB", "DB": "DB",
    "K": "K", "P": "P", "KR": "RET", "PR": "RET",
}


def normalize_name(name: str) -> list[str]:
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9 ]", " ", text.lower().replace(".", ". ").replace("'", ""))
    tokens = [t for t in text.split() if t]
    while tokens and tokens[-1] in SUFFIXES:
        tokens.pop()
    return tokens


def canonical_team(team: str) -> str:
    key = re.sub(r"[^a-z0-9 ]", "", (team or "").lower()).strip()
    return TEAM_ALIASES.get(key, key.upper())


def position_family(pos: str) -> str:
    p = re.sub(r"\d+$", "", (pos or "").upper().strip())
    return POSITION_FAMILY.get(p, POSITION_FAMILY.get(pos.upper().strip(), p))


def _first_name_score(a: str, b: str) -> tuple[float, str]:
    if not a or not b:
        return 0.0, "first name missing"
    if a == b:
        return 2.0, "first name exact"
    if len(a) == 1 or len(b) == 1:
        return (1.0, "initial agrees") if a[0] == b[0] else (-3.0, "initial conflicts")
    if b in _NICK.get(a, ()):
        return 1.5, "nickname equivalent"
    if a.startswith(b) or b.startswith(a):
        return 1.0, "first name prefix"
    return -3.0, "first name conflicts"


@dataclass
class MatchResult:
    source_id: str
    status: str  # matched | manual | ambiguous | weak | unmatched | manual_rejected
    target_id: str | None
    score: float
    reasons: list[str] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)

    @property
    def applicable(self) -> bool:
        return self.status in ("matched", "manual")


def score_pair(src: dict, tgt: dict, *, require_team: bool = True) -> tuple[float, list[str]]:
    reasons: list[str] = []
    s_tokens, t_tokens = normalize_name(src.get("name", "")), normalize_name(tgt.get("name", ""))
    team_ok = canonical_team(src.get("team", "")) == canonical_team(tgt.get("team", ""))
    if require_team and not team_ok:
        return float("-inf"), ["team differs"]
    score = 2.0 if team_ok else 0.0
    reasons.append("team agrees" if team_ok else "team differs")
    if s_tokens and t_tokens:
        if s_tokens[-1] != t_tokens[-1]:
            return float("-inf"), reasons + ["last name differs"]
        score += 4.0
        reasons.append("last name exact")
        fs, why = _first_name_score(s_tokens[0] if len(s_tokens) > 1 else "", t_tokens[0] if len(t_tokens) > 1 else "")
        score += fs
        reasons.append(why)
    else:
        reasons.append("no name on one side; slot-only identification")
    sp, tp = position_family(src.get("position", "")), position_family(tgt.get("position", ""))
    if sp and tp:
        if sp == tp:
            score += 1.5
            reasons.append("position family agrees")
        elif "RET" in (sp, tp):
            reasons.append("returner slot; position not compared")
        else:
            score -= 2.0
            reasons.append(f"position family differs ({sp} vs {tp})")
    sj, tj = str(src.get("jersey", "")).strip(), str(tgt.get("jersey", "")).strip()
    if sj and tj:
        if sj.lstrip("0") == tj.lstrip("0"):
            score += 2.0
            reasons.append("jersey agrees")
        else:
            score -= 1.0
            reasons.append("jersey differs")
    ss, ts = str(src.get("season", "")).strip(), str(tgt.get("season", "")).strip()
    if ss and ts and ss != ts:
        score -= 2.0
        reasons.append(f"season differs ({ss} vs {ts})")
    return score, reasons


def match_records(
    sources: list[dict],
    targets: list[dict],
    *,
    manual: dict[str, str | None] | None = None,
    accept: float = 8.0,
    margin: float = 1.5,
    floor: float = 5.0,
    require_team: bool = True,
) -> list[MatchResult]:
    """Match each source to at most one target.

    ``matched`` needs score >= accept, a margin over the runner-up, a real name on
    both sides, and a target not claimed by another source. ``manual`` maps
    source id -> target id (or None for a confirmed non-match) and always wins.
    """
    manual = manual or {}
    by_team: dict[str, list[dict]] = {}
    for t in targets:
        by_team.setdefault(canonical_team(t.get("team", "")), []).append(t)
    results: list[MatchResult] = []
    for src in sources:
        sid = str(src["id"])
        if sid in manual:
            tid = manual[sid]
            results.append(MatchResult(sid, "manual" if tid else "manual_rejected", tid, 0.0, ["manual review decision"]))
            continue
        pool = by_team.get(canonical_team(src.get("team", "")), []) if require_team else targets
        scored = []
        for t in pool:
            sc, why = score_pair(src, t, require_team=require_team)
            if sc != float("-inf"):
                scored.append((sc, str(t["id"]), why, t))
        scored.sort(key=lambda x: (-x[0], x[1]))
        cands = [{"id": tid, "name": t.get("name", ""), "team": t.get("team", ""), "position": t.get("position", ""),
                  "jersey": t.get("jersey", ""), "score": round(sc, 2), "reasons": why} for sc, tid, why, t in scored[:5]]
        if not scored or scored[0][0] < floor:
            results.append(MatchResult(sid, "unmatched", None, scored[0][0] if scored else 0.0,
                                       ["no candidate above floor"], cands))
            continue
        best, second = scored[0], scored[1] if len(scored) > 1 else None
        named = bool(normalize_name(src.get("name", ""))) and bool(normalize_name(best[3].get("name", "")))
        if second and best[0] - second[0] < margin:
            status = "ambiguous"
        elif best[0] >= accept and named:
            status = "matched"
        else:
            status = "weak"
        results.append(MatchResult(sid, status, best[1] if status == "matched" else None, best[0], best[2], cands))
    # A target may be claimed by only one automatic match.
    claimed: dict[str, list[MatchResult]] = {}
    for r in results:
        if r.status in ("matched", "manual") and r.target_id:
            claimed.setdefault(r.target_id, []).append(r)
    for tid, rs in claimed.items():
        autos = [r for r in rs if r.status == "matched"]
        if len(rs) > 1:
            for r in autos:
                r.status, r.target_id = "ambiguous", None
                r.reasons = r.reasons + [f"target {tid} claimed by several sources"]
    return results
