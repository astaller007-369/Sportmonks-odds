import os, time, io
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
import streamlit as st

BASE = "https://api.sportmonks.com/api/v3/football"

LEAGUES = [
    (453, "Poland", "Ekstraklasa"), (648, "Brazil", "Serie A"),
    (82, "Germany", "Bundesliga"), (85, "Germany", "2. Bundesliga"),
    (301, "France", "Ligue 1"), (304, "France", "Ligue 2"),
    (462, "Portugal", "Liga Portugal"), (564, "Spain", "La Liga"),
    (567, "Spain", "La Liga 2"), (72, "Netherlands", "Eredivisie"),
    (74, "Netherlands", "Eerste Divisie"), (573, "Sweden", "Allsvenskan"),
    (325, "Greece", "Super League"), (591, "Switzerland", "Super League"),
    (1034, "South Korea", "K League 1"), (181, "Austria", "Admiral Bundesliga"),
    (486, "Russia", "Premier League"), (384, "Italy", "Serie A"),
    (387, "Italy", "Serie B"), (271, "Denmark", "Superliga"),
    (672, "Colombia", "Liga BetPlay"), (600, "Turkey", "Super Lig"),
    (360, "Republic of Ireland", "Premier Division"), (8, "England", "Premier League"),
    (9, "England", "Championship"), (968, "Japan", "J1 League"),
    (208, "Belgium", "Pro League"), (531, "Serbia", "Super Liga"),
    (501, "Scotland", "Premiership"), (444, "Norway", "Eliteserien"),
    (609, "Ukraine", "Premier League"), (830, "Egypt", "Premier League"),
    (806, "South Africa", "Premier League"), (1064, "Thailand", "Thai Premier League"),
    (743, "Mexico", "Liga MX"), (334, "Hungary", "NB 1"),
    (944, "Saudi Arabia", "Pro League"), (696, "Ecuador", "Liga Pro"),
    (474, "Romania", "Superliga"), (229, "Bulgaria", "First League"),
    (465, "Portugal", "Liga Portugal 2"), (244, "Croatia", "1. HNL"),
    (262, "Czech Republic", "Chance Liga"),
]
LEAGUE_LABEL = {lid: f"{c} - {n} ({lid})" for lid, c, n in LEAGUES}

st.set_page_config(page_title="Sportmonks Odds", page_icon="⚽", layout="wide")


# ---------- API helpers ----------
def api_get(path, token, params=None, retries=3):
    p = {"api_token": token, **(params or {})}
    for i in range(retries):
        r = requests.get(f"{BASE}/{path}", params=p, timeout=30)
        if r.status_code == 429:
            time.sleep(5 * (i + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("Rate limited by Sportmonks (429). Try again later or reduce scope.")


def paginate(path, token, params=None, max_pages=200):
    out, page = [], 1
    while page <= max_pages:
        j = api_get(path, token, {**(params or {}), "page": page})
        d = j.get("data") or []
        out += d if isinstance(d, list) else [d]
        if not (j.get("pagination") or {}).get("has_more"):
            break
        page += 1
    return out


@st.cache_data(ttl=86400, show_spinner=False)
def load_markets(token):
    return {m["id"]: m["name"] for m in paginate("odds/markets", token, {"per_page": 50})}


@st.cache_data(ttl=86400, show_spinner=False)
def load_bookmakers(token):
    return {b["id"]: b["name"] for b in paginate("odds/bookmakers", token, {"per_page": 50})}


@st.cache_data(ttl=600, show_spinner=False)
def load_fixtures(token, start, end, league_ids):
    data = paginate(
        f"fixtures/between/{start}/{end}", token,
        {"include": "participants;league", "filters": f"fixtureLeagues:{','.join(map(str, league_ids))}",
         "per_page": 50},
    )
    rows = []
    for f in data:
        parts = f.get("participants") or []
        home = next((p["name"] for p in parts if (p.get("meta") or {}).get("location") == "home"), "")
        away = next((p["name"] for p in parts if (p.get("meta") or {}).get("location") == "away"), "")
        lg = f.get("league") or {}
        rows.append({"fixture_id": f["id"], "league_id": f.get("league_id"), "league": lg.get("name", ""),
                     "kickoff_utc": f.get("starting_at"), "home": home, "away": away,
                     "state_id": f.get("state_id")})
    return pd.DataFrame(rows)


def fetch_fixture_odds(token, fid, market_ids, bookmaker_ids):
    path = f"odds/pre-match/fixtures/{fid}"
    params = {"per_page": 50}
    flt = []
    if market_ids:
        flt.append(f"markets:{','.join(map(str, market_ids))}")
    if bookmaker_ids:
        flt.append(f"bookmakers:{','.join(map(str, bookmaker_ids))}")
    if flt:
        params["filters"] = ";".join(flt)
    odds = paginate(path, token, params)
    # client-side safety net in case a filter is ignored
    return [o for o in odds
            if (not market_ids or o.get("market_id") in market_ids)
            and (not bookmaker_ids or o.get("bookmaker_id") in bookmaker_ids)]


# ---------- Shaping ----------
def selection_name(o):
    s = str(o.get("label") or o.get("name") or "")
    for k in ("handicap", "total"):
        if o.get(k) not in (None, ""):
            s += f" {o[k]}"
    return s.strip()


def to_long(fixtures, odds_by_fid, markets, bookmakers):
    fx = fixtures.set_index("fixture_id")
    rows = []
    for fid, odds in odds_by_fid.items():
        f = fx.loc[fid]
        for o in odds:
            try:
                val = float(o.get("value"))
            except (TypeError, ValueError):
                continue
            rows.append({
                "fixture_id": fid, "kickoff_utc": f.kickoff_utc, "league": f.league,
                "home": f.home, "away": f.away,
                "market_id": o.get("market_id"),
                "market": markets.get(o.get("market_id"), o.get("market_description", "")),
                "bookmaker_id": o.get("bookmaker_id"),
                "bookmaker": bookmakers.get(o.get("bookmaker_id"), ""),
                "selection": selection_name(o), "odds": val,
                "probability": o.get("probability"), "stopped": o.get("stopped"),
                "updated_at": o.get("latest_bookmaker_update"),
            })
    return pd.DataFrame(rows)


ID_COLS = ["fixture_id", "kickoff_utc", "league", "home", "away"]


def shape(df, layout, drop_stopped):
    if df.empty:
        return df
    if drop_stopped:
        df = df[df["stopped"].fillna(False) == False]  # noqa: E712
    keys = ID_COLS + ["market", "selection"]
    if layout == "Long (one row per selection per bookmaker)":
        return df.sort_values(["kickoff_utc", "fixture_id", "market", "bookmaker"])
    if layout == "Best odds (one row per selection, best bookmaker)":
        g = df.groupby(keys)
        best = df.loc[g["odds"].idxmax()][keys + ["bookmaker", "odds"]].rename(
            columns={"bookmaker": "best_bookmaker", "odds": "best_odds"})
        agg = g["odds"].agg(avg_odds="mean", n_bookmakers="count").round(3).reset_index()
        return best.merge(agg, on=keys).sort_values(["kickoff_utc", "fixture_id", "market"])
    # Wide
    multi_bk = df["bookmaker"].nunique() > 1
    df = df.copy()
    df["col"] = df["market"] + " | " + df["selection"]
    if multi_bk:
        df["col"] = df["bookmaker"] + " | " + df["col"]
    w = df.pivot_table(index=ID_COLS, columns="col", values="odds", aggfunc="first").reset_index()
    w.columns.name = None
    return w.sort_values(["kickoff_utc", "fixture_id"])


# ---------- UI ----------
st.title("⚽ Sportmonks Prematch Odds")

token = st.secrets.get("SPORTMONKS_TOKEN", None) if hasattr(st, "secrets") else None
token = token or os.getenv("SPORTMONKS_TOKEN", "")
with st.sidebar:
    st.header("Settings")
    if not token:
        token = st.text_input("Sportmonks API token", type="password")
    else:
        st.success("API token loaded")
    max_req = st.number_input("Max API requests per run (safety cap)", 10, 5000, 300, 10)
    workers = st.slider("Parallel requests", 1, 8, 4)
    st.caption("Fixture times are UTC. Odds need ≥1 call per fixture.")

if not token:
    st.info("Add your Sportmonks token in the sidebar or as `SPORTMONKS_TOKEN` secret.")
    st.stop()

try:
    markets = load_markets(token)
    bookmakers = load_bookmakers(token)
except Exception as e:
    st.error(f"Could not load markets/bookmakers (check token & plan): {e}")
    st.stop()

c1, c2 = st.columns(2)
with c1:
    st.subheader("1. Leagues")
    countries = sorted({c for _, c, _ in LEAGUES})
    quick = st.multiselect("Quick-add whole countries", countries)
    default = [lid for lid, c, _ in LEAGUES if c in quick]
    sel_leagues = st.multiselect("Leagues", list(LEAGUE_LABEL), default=default,
                                 format_func=LEAGUE_LABEL.get, key=f"lg_{'-'.join(quick)}")
    if st.checkbox("Select all leagues"):
        sel_leagues = list(LEAGUE_LABEL)
with c2:
    st.subheader("2. Period")
    d_from = st.date_input("From", date.today())
    d_to = st.date_input("Odds until", date.today() + timedelta(days=7), min_value=d_from)
    only_ns = st.checkbox("Only matches not started", True)

st.subheader("3. Markets & bookmakers")
m1, m2 = st.columns(2)
with m1:
    sel_markets = st.multiselect("Markets", list(markets), format_func=lambda i: f"{markets[i]} ({i})")
with m2:
    sel_books = st.multiselect("Bookmakers (empty = all)", list(bookmakers),
                               format_func=lambda i: f"{bookmakers[i]} ({i})")

st.subheader("4. CSV format")
f1, f2, f3, f4 = st.columns(4)
layout = f1.selectbox("Layout", [
    "Long (one row per selection per bookmaker)",
    "Wide (one row per match, one column per selection)",
    "Best odds (one row per selection, best bookmaker)"])
delim = f2.selectbox("Delimiter", [",", ";", "\\t"])
decimal = f3.selectbox("Decimal separator", [".", ","])
drop_stopped = f4.checkbox("Drop suspended odds", True)

if st.button("Fetch odds", type="primary", disabled=not (sel_leagues and sel_markets)):
    try:
        with st.spinner("Loading fixtures…"):
            fx = load_fixtures(token, str(d_from), str(d_to), tuple(sel_leagues))
        if only_ns and not fx.empty:
            fx = fx[fx["state_id"] == 1]
        st.session_state["fx_n"] = len(fx)
        if fx.empty:
            st.session_state.pop("raw", None)
            st.warning("No fixtures found (check dates, or leagues not in your plan).")
        elif len(fx) > max_req:
            st.session_state.pop("raw", None)
            st.error(f"{len(fx)} fixtures needs ≥{len(fx)} requests (cap {max_req}). "
                     "Narrow the period/leagues or raise the cap.")
        else:
            odds_by_fid, errors = {}, []
            bar = st.progress(0.0, text=f"Fetching odds for {len(fx)} fixtures…")
            with ThreadPoolExecutor(workers) as ex:
                futs = {ex.submit(fetch_fixture_odds, token, int(fid), sel_markets, sel_books): fid
                        for fid in fx["fixture_id"]}
                for i, fut in enumerate(as_completed(futs), 1):
                    try:
                        odds_by_fid[futs[fut]] = fut.result()
                    except Exception as e:
                        errors.append(f"Fixture {futs[fut]}: {e}")
                    bar.progress(i / len(futs))
            bar.empty()
            st.session_state["raw"] = to_long(fx, odds_by_fid, markets, bookmakers)
            st.session_state["errors"] = errors
    except Exception as e:
        st.error(f"Request failed: {e}")

raw = st.session_state.get("raw")
if raw is not None:
    for e in st.session_state.get("errors", [])[:10]:
        st.warning(e)
    if raw.empty:
        st.warning("Fixtures found, but no odds published yet for that market/bookmaker.")
    else:
        out = shape(raw, layout, drop_stopped)
        st.success(f"{raw['fixture_id'].nunique()} matches · {len(out)} rows")
        st.dataframe(out, use_container_width=True, height=400)
        sep = "\t" if delim == "\\t" else delim
        csv = out.to_csv(index=False, sep=sep, decimal=decimal)
        st.download_button("⬇️ Download CSV", csv.encode("utf-8-sig"),
                           file_name=f"odds_{d_from}_{d_to}.csv", mime="text/csv")
