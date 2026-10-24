"""Thin client + helpers for the Sportmonks Football API v3."""
import datetime as dt
import time

import pandas as pd
import requests

BASE_URL = "https://api.sportmonks.com/v3/football"
DEFAULT_MARKET_IDS = [1, 2, 14, 80]  # Fulltime result, Double chance, BTTS, Goals over/under


class ApiError(Exception):
    pass


class RateLimited(ApiError):
    pass


class SportmonksClient:
    def __init__(self, token):
        self.s = requests.Session()
        self.s.headers.update({"Authorization": token})
        self.rate = {}

    def get(self, path, params=None, allow_404=False, retries=4):
        for _ in range(retries):
            r = self.s.get(BASE_URL + path, params=params, timeout=45)
            try:
                j = r.json()
            except ValueError:
                j = {}
            if isinstance(j.get("rate_limit"), dict):
                self.rate = j["rate_limit"]
            if r.status_code == 429:
                wait = int((j.get("rate_limit") or {}).get("resets_in_seconds", 30)) + 1
                if wait > 90:
                    raise RateLimited(f"Hourly rate limit reached; resets in ~{wait // 60} min. "
                                      "Partial results are kept – run again later.")
                time.sleep(wait)
                continue
            if r.status_code == 404 and allow_404:
                return None
            if r.status_code >= 400:
                raise ApiError(f"{r.status_code}: {j.get('message') or r.text[:200]}")
            return j
        raise RateLimited("Too many rate-limit retries")

    def paginate(self, path, params=None, per_page=50):
        page, out = 1, []
        while True:
            j = self.get(path, {**(params or {}), "page": page, "per_page": per_page}) or {}
            out += j.get("data") or []
            if not (j.get("pagination") or {}).get("has_more"):
                return out
            page += 1

    # ---- reference data ----
    def bookmakers(self):
        return {b["id"]: b["name"] for b in self.paginate("/bookmakers")}

    def markets(self):
        return {m["id"]: m["name"] for m in self.paginate("/markets")}

    # ---- fixtures ----
    def fixtures_between(self, start, end, league_ids):
        return self.paginate(f"/fixtures/between/{start}/{end}", {
            "include": "participants;scores;state;season",
            "filters": "fixtureLeagues:" + ",".join(map(str, league_ids))})

    # ---- odds ----
    def odds(self, fixture_id, bookmaker_ids=None, market_ids=None, premium=False):
        filt = []
        if bookmaker_ids:
            filt.append("bookmakers:" + ",".join(map(str, bookmaker_ids)))
        if market_ids:
            filt.append("markets:" + ",".join(map(str, market_ids)))
        params = {"filters": ";".join(filt)} if filt else {}
        if premium:
            params["include"] = "history"
        feed = "premium" if premium else "pre-match"
        rows, page = [], 1
        while True:
            j = self.get(f"/odds/{feed}/fixtures/{fixture_id}", {**params, "page": page, "per_page": 500},
                         allow_404=True)
            if j is None:
                return None
            rows += j.get("data") or []
            if not (j.get("pagination") or {}).get("has_more"):
                return rows
            page += 1


# ---------- helpers ----------
def parse_fixture(f):
    home = away = None
    for p in f.get("participants") or []:
        loc = (p.get("meta") or {}).get("location")
        if loc == "home":
            home = p["name"]
        elif loc == "away":
            away = p["name"]
    hg = ag = None
    for sc in f.get("scores") or []:
        if sc.get("description") == "CURRENT":
            g = (sc.get("score") or {})
            if g.get("participant") == "home":
                hg = g.get("goals")
            elif g.get("participant") == "away":
                ag = g.get("goals")
    season = f.get("season") or {}
    return {"fixture_id": f["id"], "league_id": f.get("league_id"),
            "season": season.get("name", f.get("season_id")), "kickoff_utc": f.get("starting_at"),
            "home": home, "away": away, "state": (f.get("state") or {}).get("short_name"),
            "home_goals": hg, "away_goals": ag, "has_odds": f.get("has_odds", True)}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def flatten_odds(rows, bookmaker_names=None, premium=False):
    out = []
    for o in rows or []:
        rec = {"fixture_id": o.get("fixture_id"), "bookmaker_id": o.get("bookmaker_id"),
               "bookmaker": (bookmaker_names or {}).get(o.get("bookmaker_id"), o.get("bookmaker_id")),
               "market_id": o.get("market_id"), "market": o.get("market_description"),
               "selection": o.get("label") or o.get("name"), "total": o.get("total"),
               "handicap": o.get("handicap"), "value": _f(o.get("value")),
               "probability": o.get("probability"), "winning": o.get("winning"),
               "latest_bookmaker_update": o.get("latest_bookmaker_update")}
        if premium:
            hist = o.get("history") or []
            if hist:
                first = min(hist, key=lambda h: h.get("bookmaker_update") or "")
                rec["opening"] = _f(first.get("value"))
            else:
                rec["opening"] = rec["value"]
            rec["n_updates"] = len(hist)
        out.append(rec)
    return out


def to_wide(df, premium=False):
    if df.empty:
        return df
    key = (df.bookmaker.astype(str) + "|" + df.market.astype(str) + "|" + df.selection.astype(str)
           + "|" + df.total.fillna("").astype(str) + "|" + df.handicap.fillna("").astype(str))
    d = df.assign(col=key)
    wide = d.pivot_table(index="fixture_id", columns="col", values="value", aggfunc="first")
    if premium and "opening" in d:
        op = d.pivot_table(index="fixture_id", columns="col", values="opening", aggfunc="first")
        op.columns = [c + "|opening" for c in op.columns]
        wide = wide.join(op)
    return wide.reset_index()
