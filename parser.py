"""
parser.py — реальный парсер котировок Fonbet.by + Maxline.by
"""

import asyncio
import logging
import re
import aiohttp

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
    "Referer": "https://www.google.com/",
}

SPORT_IDS = {
    "football":   {"fn": 1,  "ml": 1},
    "basketball": {"fn": 3,  "ml": 3},
    "hockey":     {"fn": 2,  "ml": 2},
    "tennis":     {"fn": 5,  "ml": 5},
    "volleyball": {"fn": 8,  "ml": 8},
}


# ─────────────────────────────────────────────────────────
#  FONBET.BY
# ─────────────────────────────────────────────────────────

async def fetch_fonbet(session: aiohttp.ClientSession, sport: str) -> list[dict]:
    sid = SPORT_IDS[sport]["fn"]
    lines = []

    endpoints = [
        (f"https://www.fonbet.by/api/v1/events/getSportEvents/{sid}?locale=ru&timezone=Europe%2FMinsk", False),
        (f"https://fonbet.by/api/v1/events/live/sport/{sid}?locale=ru", True),
    ]

    for url, is_live in endpoints:
        try:
            async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=12)) as r:
                if r.status != 200:
                    continue
                data = await r.json(content_type=None)
                events = data.get("events") or data.get("data") or []

                for ev in events:
                    home = ev.get("team1") or ev.get("teamHome") or ev.get("home") or ""
                    away = ev.get("team2") or ev.get("teamAway") or ev.get("away") or ""
                    if not home or not away:
                        continue

                    league = ""
                    t = ev.get("tournament")
                    if isinstance(t, dict):
                        league = t.get("name", "")
                    else:
                        league = ev.get("leagueName") or ev.get("league") or str(t or "")

                    time_str = ev.get("startTime") or ev.get("start") or ev.get("date") or ""
                    markets = ev.get("markets") or ev.get("factors") or []

                    for total, over, under in _extract_totals(markets):
                        lines.append({
                            "book": "fonbet",
                            "home": home.strip(), "away": away.strip(),
                            "league": league.strip(),
                            "time": _fmt_time(time_str),
                            "is_live": is_live,
                            "total": total, "over": over, "under": under,
                        })

        except Exception as e:
            log.warning(f"[Fonbet/{sport}] {e}")

    log.info(f"[Fonbet/{sport}] {len(lines)} total lines")
    return lines


# ─────────────────────────────────────────────────────────
#  MAXLINE.BY
# ─────────────────────────────────────────────────────────

async def fetch_maxline(session: aiohttp.ClientSession, sport: str) -> list[dict]:
    sid = SPORT_IDS[sport]["ml"]
    lines = []

    endpoints = [
        (f"https://www.maxline.by/api/sport/{sid}/prematch", False),
        (f"https://www.maxline.by/api/sport/{sid}/live",     True),
    ]

    for url, is_live in endpoints:
        try:
            async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=12)) as r:
                if r.status != 200:
                    continue
                data = await r.json(content_type=None)
                events = (
                    data.get("events") or data.get("rows") or
                    data.get("items") or data.get("data") or
                    (data if isinstance(data, list) else [])
                )

                for ev in events:
                    home = (
                        ev.get("team1Name") or ev.get("teamName1") or
                        ev.get("home") or ev.get("homeTeam") or ""
                    )
                    away = (
                        ev.get("team2Name") or ev.get("teamName2") or
                        ev.get("away") or ev.get("awayTeam") or ""
                    )
                    if not home or not away:
                        continue

                    league  = ev.get("leagueName") or ev.get("league") or ev.get("tournament") or ""
                    time_str = ev.get("startTime") or ev.get("date") or ev.get("start") or ""
                    markets  = ev.get("markets") or ev.get("bets") or ev.get("groups") or []

                    for total, over, under in _extract_totals(markets):
                        lines.append({
                            "book": "maxline",
                            "home": home.strip(), "away": away.strip(),
                            "league": league.strip(),
                            "time": _fmt_time(time_str),
                            "is_live": is_live,
                            "total": total, "over": over, "under": under,
                        })

        except Exception as e:
            log.warning(f"[Maxline/{sport}/{url[-20:]}] {e}")

    log.info(f"[Maxline/{sport}] {len(lines)} total lines")
    return lines


# ─────────────────────────────────────────────────────────
#  ПАРСИНГ ТОТАЛОВ
# ─────────────────────────────────────────────────────────

def _extract_totals(markets: list) -> list[tuple[float, float, float]]:
    res = []
    if not isinstance(markets, list):
        return res

    for m in markets:
        mname = str(
            m.get("name") or m.get("marketName") or
            m.get("type") or m.get("groupName") or ""
        ).lower()

        if "тотал" not in mname and "total" not in mname:
            continue

        outs = (
            m.get("outcomes") or m.get("bets") or m.get("runners") or
            m.get("selections") or m.get("factors") or []
        )

        over = under = tval = None

        for o in outs:
            n = str(o.get("name") or o.get("outcomeName") or o.get("type") or "").lower().strip()
            odd   = _f(o.get("odd") or o.get("factor") or o.get("price") or o.get("coef") or 0)
            param = abs(_f(o.get("param") or o.get("handicap") or o.get("line") or o.get("total") or 0))

            if odd < 1.01:
                continue

            is_o = (
                n in ("б", "o", "over", "больше") or
                n.startswith("over") or
                n.startswith("б(") or n.startswith("б ") or
                (re.match(r"^б[\s\d(]", n) is not None)
            )
            is_u = (
                n in ("м", "u", "under", "меньше") or
                n.startswith("under") or
                n.startswith("м(") or n.startswith("м ") or
                (re.match(r"^м[\s\d(]", n) is not None)
            )

            if is_o:
                over = odd
                if param > 0:
                    tval = param
            if is_u:
                under = odd
                if param > 0 and not tval:
                    tval = param

        # Параметр тотала иногда в самом маркете
        if not tval:
            p = abs(_f(m.get("param") or m.get("total") or m.get("handicap") or 0))
            if p > 0:
                tval = p

        if over and under and tval:
            res.append((round(tval, 2), round(over, 2), round(under, 2)))

    return res


def _f(v) -> float:
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def _fmt_time(ts) -> str:
    if not ts:
        return ""
    try:
        s = str(ts).strip()
        if re.match(r"^\d{9,13}$", s):
            import datetime
            v = int(s)
            if v > 1e10:
                v //= 1000
            d = datetime.datetime.fromtimestamp(v)
            return d.strftime("%d.%m %H:%M")
        return s[:16].replace("T", " ")
    except Exception:
        return str(ts)[:16]


# ─────────────────────────────────────────────────────────
#  МАТЧИНГ И КОРИДОРЫ
# ─────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    s = str(s).lower().strip()
    s = re.sub(r"[^a-zа-яё0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _sim(a: str, b: str) -> float:
    wa = set(w for w in _norm(a).split() if len(w) > 1)
    wb = set(w for w in _norm(b).split() if len(w) > 1)
    if not wa or not wb:
        return 0.0
    inter = len(wa & wb)
    return inter / max(len(wa), len(wb))


def match_and_build(fn_lines: list, ml_lines: list) -> list[dict]:
    """Сопоставляет линии Fonbet и Maxline, считает коридоры."""
    events = []
    used_ml = set()

    for fn in fn_lines:
        best_ml  = None
        best_sc  = 0.0
        best_idx = -1

        for idx, ml in enumerate(ml_lines):
            if idx in used_ml:
                continue
            sh = _sim(fn["home"], ml["home"])
            sa = _sim(fn["away"], ml["away"])
            sc = (sh + sa) / 2
            if sc > best_sc:
                best_sc  = sc
                best_ml  = ml
                best_idx = idx

        if not best_ml or best_sc < 0.5:
            continue

        used_ml.add(best_idx)
        cors = _calc_corridors(fn, best_ml)

        events.append({
            "home":     fn["home"],
            "away":     fn["away"],
            "league":   fn["league"] or best_ml["league"],
            "time":     fn["time"]   or best_ml["time"],
            "is_live":  fn["is_live"] or best_ml["is_live"],
            "fn_total": fn["total"],
            "fn_over":  fn["over"],
            "fn_under": fn["under"],
            "ml_total": best_ml["total"],
            "ml_over":  best_ml["over"],
            "ml_under": best_ml["under"],
            "match_sc": round(best_sc, 2),
            "cors":     cors,
        })

    return events


def _calc_corridors(fn: dict, ml: dict) -> list[dict]:
    cors = []

    # A: Fonbet Б + Maxline М (ml_total > fn_total)
    if ml["total"] > fn["total"]:
        w   = round(ml["total"] - fn["total"], 3)
        s1  = 100 / fn["over"]
        s2  = 100 / ml["under"]
        roi = round((100 - (s1 + s2)) / (s1 + s2) * 100, 2)
        cors.append({
            "oBook": "fonbet",  "oLabel": "Fonbet.by",
            "oLine": fn["total"], "oOdds": fn["over"],
            "uBook": "maxline", "uLabel": "Maxline.by",
            "uLine": ml["total"], "uOdds": ml["under"],
            "width": w, "roi": roi,
            "s1": round(s1, 1), "s2": round(s2, 1),
        })

    # B: Maxline Б + Fonbet М (fn_total > ml_total)
    if fn["total"] > ml["total"]:
        w   = round(fn["total"] - ml["total"], 3)
        s1  = 100 / ml["over"]
        s2  = 100 / fn["under"]
        roi = round((100 - (s1 + s2)) / (s1 + s2) * 100, 2)
        cors.append({
            "oBook": "maxline", "oLabel": "Maxline.by",
            "oLine": ml["total"], "oOdds": ml["over"],
            "uBook": "fonbet",  "uLabel": "Fonbet.by",
            "uLine": fn["total"], "uOdds": fn["under"],
            "width": w, "roi": roi,
            "s1": round(s1, 1), "s2": round(s2, 1),
        })

    return sorted(cors, key=lambda c: -c["width"])
