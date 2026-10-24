# Sportmonks Odds Fetcher (Streamlit)

Request **prematch odds** for 43 leagues (Sportmonks league IDs built in) for the next 1–30 days.

## Run locally
```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # add your token
streamlit run app.py
```

## Deploy (GitHub → Streamlit Community Cloud)
1. Push this folder to GitHub (`.streamlit/secrets.toml` is git-ignored).
2. share.streamlit.io → **New app** → repo, branch, main file `app.py`.
3. App **Settings → Secrets**: `SPORTMONKS_TOKEN = "your-token"`.

## Notes
- Requires the Sportmonks **Odds add-on** (and your plan must include the selected leagues).
- Standard feed: `/odds/pre-match/fixtures/{id}`. Premium feed (optional): `/odds/premium/fixtures/{id}?include=history` adds opening odds.
- Each fixture costs one odds request; rate limit is ~3,000/hour per entity. Hitting it keeps partial results – click Fetch again later.
