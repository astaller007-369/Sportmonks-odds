import datetime as dt
import os

import pandas as pd
import streamlit as st

from leagues import LEAGUES, label
from sportmonks import (DEFAULT_MARKET_IDS, ApiError, RateLimited, SportmonksClient,
                        flatten_odds, parse_fixture, to_wide)

st.set_page_config(page_title="Sportmonks Odds Fetcher", page_icon="⚽", layout="wide")
st.title("⚽ Sportmonks odds fetcher")
st.caption("Data: Sportmonks Football API v3 · pre-match odds (needs the Odds add-on)")


def get_token():
    try:
        if "SPORTMONKS_TOKEN" in st.secrets:
            return st.secrets["SPORTMONKS_TOKEN"]
    except Exception:
        pass
    return os.environ.get("SPORTMONKS_TOKEN", "")


with st.sidebar:
    st.header("Settings")
    token = get_token() or st.text_input("Sportmonks API token", type="password")

if not token:
    st.info("Enter your API token in the sidebar (or set SPORTMONKS_TOKEN as a secret).")
    st.stop()

client = SportmonksClient(token)
S = st.session_state
S.setdefault("matches", pd.DataFrame())
S.setdefault("odds_cache", {})
S.setdefault("no_odds", set())


@st.cache_data(ttl=86400, show_spinner="Loading bookmakers…")
def load_bookmakers(_tok):
    try:
        return SportmonksClient(_tok).bookmakers()
    except ApiError:
        return {}


@st.cache_data(ttl=86400, show_spinner="Loading markets…")
def load_markets(_tok):
    try:
        return SportmonksClient(_tok).markets()
    except ApiError:
        return {}


bk_names, mk_names = load_bookmakers(token), load_markets(token)

with st.sidebar:
    if bk_names:
        bk_sel = st.multiselect("Bookmakers (none = all)", list(bk_names), format_func=lambda i: bk_names[i])
    else:
        raw = st.text_input("Bookmaker IDs (comma-separated, blank = all)", "")
        bk_sel = [int(x) for x in raw.split(",") if x.strip().isdigit()]
    all_mk = st.checkbox("All markets", value=False)
    if all_mk:
        mk_sel = []
    elif mk_names:
        mk_sel = st.multiselect("Markets", list(mk_names), default=[m for m in DEFAULT_MARKET_IDS if m in mk_names],
                                format_func=lambda i: f"{mk_names[i]} ({i})")
    else:
        raw = st.text_input("Market IDs (comma-separated)", ",".join(map(str, DEFAULT_MARKET_IDS)))
        mk_sel = [int(x) for x in raw.split(",") if x.strip().isdigit()]
    premium = st.checkbox("Premium odds feed (adds opening odds)", value=False,
                          help="Needs the Premium Odds add-on. Adds each price's opening value so you can see line movement.")
    layout = st.radio("Output layout", ["Long (one row per price)", "Wide (one row per match)"])

labels = [label(*l) for l in LEAGUES]
lookup = {lab: l for lab, l in zip(labels, LEAGUES)}
select_all = st.checkbox("Select all leagues", value=False)
chosen = st.multiselect("Leagues", labels, default=labels if select_all else [], key=f"lg_{select_all}")

days = st.slider("Upcoming matches: days ahead", 1, 30, 7)

# ---------- step 1 ----------
if st.button("1️⃣ Find matches", type="primary", disabled=not chosen):
    ids = [lookup[c][0] for c in chosen]
    names = {l[0]: label(*l) for l in LEAGUES}
    raw_fx, errors = [], []
    try:
        now = dt.datetime.now(dt.timezone.utc)
        raw_fx = client.fixtures_between(now.date().isoformat(),
                                         (now.date() + dt.timedelta(days=days)).isoformat(), ids)
    except RateLimited as e:
        errors.append(str(e))
    except ApiError as e:
        errors.append(str(e))

    rows = {}
    for f in raw_fx:
        r = parse_fixture(f)
        if r["league_id"] not in names:
            continue
        r["league"] = names[r["league_id"]]
        if r["state"] != "NS":
            continue
        rows[r["fixture_id"]] = r
    df = pd.DataFrame(list(rows.values()))
    if not df.empty:
        df = df.sort_values(["league", "kickoff_utc"]).drop(columns=["league_id"])
    S.matches = df
    for e in errors:
        st.warning(e)

mdf = S.matches
if not mdf.empty:
    n_odds = int(mdf.has_odds.sum())
    st.success(f"{len(mdf)} matches found · {n_odds} flagged with odds (1 API request each)")
    st.dataframe(mdf, use_container_width=True, hide_index=True)

    cap = st.number_input("Max matches to fetch odds for", 1, max(n_odds, 1), min(n_odds, 200) or 1,
                          help="Sportmonks limits each entity to ~3,000 requests per hour.")
    if st.button("2️⃣ Fetch odds"):
        todo = [i for i in mdf[mdf.has_odds].fixture_id.tolist()
                if (i, premium) not in S.odds_cache and i not in S.no_odds][: int(cap)]
        prog = st.progress(0.0)
        try:
            for k, fid in enumerate(todo):
                prog.progress((k + 1) / max(len(todo), 1), text=f"{k + 1}/{len(todo)} · fixture {fid}")
                rows = client.odds(fid, bk_sel, mk_sel, premium)
                if rows is None:
                    S.no_odds.add(fid)
                else:
                    S.odds_cache[(fid, premium)] = flatten_odds(rows, bk_names, premium)
        except RateLimited as e:
            st.error(str(e))
        except ApiError as e:
            st.error(str(e))
        prog.empty()

    long_rows = [r for fid in mdf.fixture_id for r in S.odds_cache.get((fid, premium), [])]
    if long_rows:
        long_df = pd.DataFrame(long_rows)
        if bk_sel:
            long_df = long_df[long_df.bookmaker_id.isin(bk_sel)]
        if mk_sel:
            long_df = long_df[long_df.market_id.isin(mk_sel)]
        out = to_wide(long_df, premium) if layout.startswith("Wide") else long_df
        out = mdf.drop(columns=["has_odds"]).merge(out, on="fixture_id", how="inner")
        st.subheader(f"Odds ({len(out)} rows)")
        st.dataframe(out, use_container_width=True, hide_index=True)
        st.download_button("⬇️ Download CSV", out.to_csv(index=False).encode(),
                           file_name="sportmonks_prematch_odds.csv", mime="text/csv")

if client.rate:
    st.sidebar.caption(f"Rate limit remaining: {client.rate.get('remaining', '?')} "
                       f"({client.rate.get('requested_entity', '')})")
