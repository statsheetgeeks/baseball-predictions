"""
models/pitchers_strikeout.py
──────────────────────────────────────────────────────────────────────────────
Strikeout Predictor — Chalk Line Labs
──────────────────────────────────────────────────────────────────────────────
Three models, same pattern as the games/hitters suite:
  1. Calculation Engine  — deterministic, formula-based (batter-K-rate x
                            pitcher-K-stuff matchup math, summed over a lineup)
  2. KNN                 — k-Nearest Neighbors regressor on engineered features
  3. Gradient Boosting   — XGBoost regressor on the same features
                            (labeled "Gradient Boosting" on the site to match
                            the games/xgboost page's use of the literal name)

Data sources:
  - Statcast pitch-by-pitch (via pybaseball) for K-stuff profiles: whiff%,
    called-strike%, CSW%, per-pitch-category splits. This is NEW relative to
    the rest of the site — no other model pulls Statcast pitch-level data.
  - MLB StatsAPI for schedule, probable pitchers, today's posted lineups,
    and (new) recent boxscores used to build an EXPECTED lineup when today's
    isn't posted yet.

Caching (mirrors hr_pred_cache / hit_pred_cache pattern, restored via
actions/cache in the GitHub Actions workflow):
  models/k_pred_cache/
    pitches.db              ← SQLite cache of Statcast pitches, keyed by
                               season_label. Historical seasons (immutable)
                               are pulled once; the current season is
                               refreshed incrementally (only new game_dates
                               since the last cached date), not re-pulled
                               from scratch each day.
    k_models.pkl             ← trained KNN + XGBoost models, scaler, and
                               feature fill-values. Retrained weekly (see
                               MODEL_RETRAIN_DAYS), not on every run.

OUTPUTS (auto-committed daily by GitHub Actions):
  public/data/pitchers-strikeout.json          — today's slate + projections
  public/data/pitchers-strikeout-history.json  — cumulative daily history
──────────────────────────────────────────────────────────────────────────────
"""

import os
import json
import time
import sqlite3
import pickle
import warnings
from collections import Counter
from datetime import date, timedelta, datetime

import numpy as np
import pandas as pd
import requests

from pybaseball import statcast

from sklearn.neighbors import KNeighborsRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from xgboost import XGBRegressor

warnings.filterwarnings('ignore')
np.random.seed(42)

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(BASE_DIR, '..', 'public', 'data')
CACHE_DIR  = os.path.join(BASE_DIR, 'k_pred_cache')
CACHE_DB   = os.path.join(CACHE_DIR, 'pitches.db')
MODELS_PKL = os.path.join(CACHE_DIR, 'k_models.pkl')
MAIN_JSON  = os.path.join(DATA_DIR, 'pitchers-strikeout.json')
HIST_JSON  = os.path.join(DATA_DIR, 'pitchers-strikeout-history.json')

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

MLB_API = 'https://statsapi.mlb.com/api/v1'
SLEEP_S = 0.15

# ── Season config ─────────────────────────────────────────────────────────────
TODAY     = date.today()
TODAY_STR = TODAY.strftime('%Y-%m-%d')
CURRENT_YEAR = TODAY.year

# Historical seasons pooled for the long-run "prior" profile. Immutable once
# the season is over, so these are cached forever and never re-pulled.
HISTORICAL_SEASONS = [
    # label              start         end            recency_weight
    (str(CURRENT_YEAR - 3), f'{CURRENT_YEAR-3}-03-25', f'{CURRENT_YEAR-3}-10-01', 1.0),
    (str(CURRENT_YEAR - 2), f'{CURRENT_YEAR-2}-03-25', f'{CURRENT_YEAR-2}-10-01', 2.0),
    (str(CURRENT_YEAR - 1), f'{CURRENT_YEAR-1}-03-25', f'{CURRENT_YEAR-1}-10-01', 3.0),
]

CURRENT_SEASON_LABEL = str(CURRENT_YEAR)
CURRENT_SEASON_START = f'{CURRENT_YEAR}-03-20'   # adjust if Opening Day shifts

# Retrain KNN + XGBoost once a week; daily runs in between just load the
# cached models and score today's slate. Keeps daily Actions runtime low.
MODEL_RETRAIN_DAYS = 7

# ── Pitch category mapping (same convention as the hitters models) ─────────
PITCH_MAP = {
    'FF': 'fastball', 'SI': 'fastball', 'FC': 'fastball',
    'SL': 'breaking', 'CU': 'breaking', 'KC': 'breaking',
    'SV': 'breaking', 'CS': 'breaking', 'ST': 'breaking',
    'CH': 'offspeed', 'FS': 'offspeed', 'FO': 'offspeed',
    'SC': 'offspeed',
}
PITCH_CATEGORIES = ['fastball', 'breaking', 'offspeed']

STRIKEOUT_EVENTS = ['strikeout', 'strikeout_double_play']
AB_EVENTS = ['single', 'double', 'triple', 'home_run', 'field_out', 'strikeout',
             'grounded_into_double_play', 'double_play', 'fielders_choice',
             'fielders_choice_out', 'triple_play']

WHIFF_DESCRIPTIONS = {'swinging_strike', 'swinging_strike_blocked', 'foul_tip'}
CALLED_STRIKE_DESCRIPTIONS = {'called_strike'}
SWING_DESCRIPTIONS = {
    'swinging_strike', 'swinging_strike_blocked', 'foul_tip', 'foul',
    'foul_bunt', 'hit_into_play', 'hit_into_play_no_out', 'hit_into_play_score',
}
OUT_OF_ZONE_CODES = {11, 12, 13, 14}

# Bayesian shrinkage thresholds (PAs per pitch category)
PA_FULL  = 30
PA_BLEND = 10

# Season blend: current year vs. pooled historical
WEIGHT_CURRENT = 0.70
WEIGHT_PRIOR   = 0.30

# League-average fallbacks — overwritten with real numbers once data loads
LEAGUE_AVG_K_RATE             = 0.225
LEAGUE_AVG_WHIFF_RATE         = 0.110
LEAGUE_AVG_CALLED_STRIKE_RATE = 0.165
LEAGUE_AVG_CSW_RATE           = 0.275
LEAGUE_AVG_CHASE_RATE         = 0.280

# XGBoost params — same conventions as games_xgboost.py / hitters_ml_hr.py
XGB_PARAMS = {
    'n_estimators':     400,
    'max_depth':        4,
    'learning_rate':    0.05,
    'subsample':        0.8,
    'colsample_bytree': 0.8,
    'min_child_weight': 5,
    'gamma':            0.1,
    'random_state':     42,
    'n_jobs':           -1,
    'verbosity':        0,
    'tree_method':      'hist',
}

FEATURE_COLUMNS = [
    'calculated_projected_ks',
    'expected_tbf',
    'games_pitched_before',
    'recent_3start_k_rate',
    'opposing_lineup_size',
]
LABEL_COLUMN = 'actual_ks'

CONFIDENCE_BANDS = [
    ('Low',    0.0, 1.0),
    ('Medium', 1.0, 2.0),
    ('High',   2.0, 99.0),
]

print('Configuration loaded.')
print(f'  Historical seasons: {[s[0] for s in HISTORICAL_SEASONS]}')
print(f'  Current season ({CURRENT_SEASON_LABEL}): {CURRENT_SEASON_START} -> {TODAY_STR}')


# ═══════════════════════════════════════════════════════════════════════════
# SECTION — STATCAST PULL / INCREMENTAL CACHE
# ═══════════════════════════════════════════════════════════════════════════
# Historical seasons are immutable once final, so each is pulled exactly
# once and cached forever. The current season is the only thing that needs
# a daily refresh, and that refresh only needs to cover the gap between the
# cache's most recent game_date and today — not the whole season — so a
# typical daily run pulls one day of pitches instead of three months of them.

def add_derived_flags(sc):
    """Adds all boolean/category flags needed downstream to a raw Statcast df."""
    sc = sc.copy()
    sc['pitch_category'] = sc['pitch_type'].map(PITCH_MAP)
    sc['game_date']      = pd.to_datetime(sc['game_date']).dt.date
    sc = sc.dropna(subset=['batter', 'pitcher']).copy()
    sc['batter']  = sc['batter'].astype(int)
    sc['pitcher'] = sc['pitcher'].astype(int)

    desc = sc['description']
    sc['is_whiff']         = desc.isin(WHIFF_DESCRIPTIONS).astype(int)
    sc['is_called_strike'] = desc.isin(CALLED_STRIKE_DESCRIPTIONS).astype(int)
    sc['is_csw']           = (sc['is_whiff'] | sc['is_called_strike']).astype(int)
    sc['is_swing']         = desc.isin(SWING_DESCRIPTIONS).astype(int)

    if 'zone' in sc.columns:
        sc['is_out_of_zone'] = sc['zone'].isin(OUT_OF_ZONE_CODES).astype(int)
    else:
        sc['is_out_of_zone'] = np.nan
    sc['is_chase'] = ((sc['is_swing'] == 1) & (sc['is_out_of_zone'] == 1)).astype(int)
    sc.loc[sc['is_out_of_zone'].isna(), 'is_chase'] = np.nan

    sc['ends_in_strikeout'] = sc['events'].isin(STRIKEOUT_EVENTS).fillna(False).astype(int)
    sc['is_ab_event']       = sc['events'].isin(AB_EVENTS).fillna(False).astype(int)

    sc = sc[sc['pitch_category'].notna()].copy()
    return sc


def load_statcast_range(start_dt, end_dt, label='', max_retries=4, base_delay=20):
    """
    Pulls Statcast for a date range and adds derived flags. Raises if empty.

    Baseball Savant serves Statcast as scraped CSV, not a stable API —
    pybaseball splits a range into weekly chunks and fetches them with a
    thread pool, and under load Savant occasionally returns a truncated or
    non-CSV response (rate-limit page, timeout, empty body) instead of an
    error. pandas then raises ParserError trying to read it as a CSV. This
    retries with exponential backoff before giving up, since these failures
    are almost always transient.
    """
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            print(f'  Pulling Statcast {label} ({start_dt} -> {end_dt})'
                  f'{f" [attempt {attempt}/{max_retries}]" if attempt > 1 else ""}...')
            sc = statcast(start_dt=start_dt, end_dt=end_dt)
            if sc is None or len(sc) == 0:
                raise ValueError(f'No Statcast data returned for {start_dt} -> {end_dt}.')
            sc = add_derived_flags(sc)
            print(f'    -> {len(sc):,} pitches, {sc["game_pk"].nunique():,} games, '
                  f'{sc["pitcher"].nunique():,} pitchers')
            return sc
        except Exception as e:
            last_err = e
            is_transient = isinstance(e, (pd.errors.ParserError, ConnectionError, TimeoutError)) \
                or 'ParserError' in type(e).__name__ \
                or 'tokenizing' in str(e).lower()
            if attempt < max_retries and is_transient:
                delay = base_delay * attempt   # 20s, 40s, 60s, ...
                print(f'    WARN: transient fetch error ({type(e).__name__}: {e}). '
                      f'Retrying in {delay}s...')
                time.sleep(delay)
                continue
            raise

    raise last_err


def iter_month_ranges(start_dt, end_dt):
    """Splits a date range into calendar-month sub-ranges (inclusive), so a
    season pull can be cached incrementally instead of all-or-nothing."""
    start = datetime.strptime(start_dt, '%Y-%m-%d').date()
    end = datetime.strptime(end_dt, '%Y-%m-%d').date()
    ranges = []
    cur = start
    while cur <= end:
        if cur.month == 12:
            next_month_start = date(cur.year + 1, 1, 1)
        else:
            next_month_start = date(cur.year, cur.month + 1, 1)
        chunk_end = min(end, next_month_start - timedelta(days=1))
        ranges.append((cur.strftime('%Y-%m-%d'), chunk_end.strftime('%Y-%m-%d')))
        cur = chunk_end + timedelta(days=1)
    return ranges


def load_from_cache(season_label):
    """Read a cached season/window from the SQLite pitch cache, if present."""
    conn = sqlite3.connect(CACHE_DB)
    try:
        df = pd.read_sql_query(
            f"SELECT * FROM pitches WHERE season_label = '{season_label}'", conn
        )
    except Exception:
        df = pd.DataFrame()
    conn.close()
    if len(df) and 'game_date' in df.columns:
        df['game_date'] = pd.to_datetime(df['game_date']).dt.date
    return df


def get_cached_month_keys(season_label):
    """Returns the set of month-chunk labels already cached for a season,
    e.g. {'2023-03', '2023-04', ...}, by reading the chunk_label column."""
    conn = sqlite3.connect(CACHE_DB)
    try:
        df = pd.read_sql_query(
            f"SELECT DISTINCT chunk_label FROM pitches WHERE season_label = '{season_label}'",
            conn
        )
        keys = set(df['chunk_label'].dropna().tolist())
    except Exception:
        keys = set()
    conn.close()
    return keys


def append_to_cache(df, season_label, chunk_label=None):
    """Append new rows to the cache under a season label, tagged with the
    calendar-month chunk they came from (chunk_label) so a partially-pulled
    season can resume from the last completed month instead of restarting."""
    df = df.copy()
    df['season_label'] = season_label
    df['chunk_label'] = chunk_label
    df['game_date'] = df['game_date'].astype(str)
    conn = sqlite3.connect(CACHE_DB)
    df.to_sql('pitches', conn, if_exists='append', index=False)
    conn.close()
    tag = f' (chunk {chunk_label})' if chunk_label else ''
    print(f'  Cached {len(df):,} new rows under season_label="{season_label}"{tag}')


def get_historical_data():
    """
    Pulls (or loads from cache) each immutable historical season. Each season
    is pulled exactly once, ever, and in MONTHLY chunks rather than one
    multi-month call — each completed month is cached and tagged with its
    chunk_label immediately, so if a later month fails (even after retries),
    the next run resumes from the first un-cached month instead of
    re-pulling the whole season from scratch.
    """
    frames, weights_applied = [], []
    for season_label, start_dt, end_dt, recency_weight in HISTORICAL_SEASONS:
        cached = load_from_cache(season_label)
        cached_months = get_cached_month_keys(season_label)
        month_ranges = iter_month_ranges(start_dt, end_dt)
        all_months_cached = cached_months.issuperset(
            {f'{season_label}-{m_start[5:7]}' for m_start, _ in month_ranges}
        )

        if len(cached) > 0 and all_months_cached:
            print(f'  Loaded historical "{season_label}" from cache: {len(cached):,} rows '
                  f'({len(cached_months)} months)')
            sc_season = cached
        else:
            print(f'  Historical "{season_label}": {len(cached_months)}/{len(month_ranges)} '
                  f'months already cached — pulling the rest...')
            for m_start, m_end in month_ranges:
                chunk_label = f'{season_label}-{m_start[5:7]}'
                if chunk_label in cached_months:
                    continue   # already have this month, skip straight to the next
                sc_month = load_statcast_range(m_start, m_end, label=chunk_label)
                append_to_cache(sc_month, season_label, chunk_label=chunk_label)
            sc_season = load_from_cache(season_label)

        sc_season = sc_season.copy()
        sc_season['_recency_weight'] = recency_weight
        frames.append(sc_season)
        weights_applied.append((season_label, recency_weight, len(sc_season)))

    # Recency-weighted pooling — repeat each season's rows proportionally
    min_weight = min(w for _, w, _ in weights_applied)
    pooled = []
    for sc_season, (label, weight, n_rows) in zip(frames, weights_applied):
        repeat_factor = weight / min_weight
        whole = int(repeat_factor)
        frac = repeat_factor - whole
        pooled.extend([sc_season] * whole)
        if frac > 0:
            sample_n = int(len(sc_season) * frac)
            if sample_n > 0:
                pooled.append(sc_season.sample(n=sample_n, random_state=42))
        print(f'  Historical pool: {label} weighted {weight}x '
              f'(~{repeat_factor:.2f}x repetition, {n_rows:,} base rows)')

    pool = pd.concat(pooled, ignore_index=True)
    print(f'Historical pool assembled: {len(pool):,} pitches\n')
    return pool


def get_current_season_data():
    """
    Incrementally refreshes the current season's cache. Only pulls the gap
    between the cache's most recent game_date and today, then appends —
    never re-pulls the whole season. First-ever run (cold start, e.g. early
    in the season or first deploy) also chunks by month so a mid-pull
    failure doesn't lose everything already fetched.
    """
    cached = load_from_cache(CURRENT_SEASON_LABEL)
    cached_months = get_cached_month_keys(CURRENT_SEASON_LABEL)

    if len(cached) == 0:
        month_ranges = iter_month_ranges(CURRENT_SEASON_START, TODAY_STR)
        print(f'  No cache for {CURRENT_SEASON_LABEL} — pulling {len(month_ranges)} '
              f'month(s) to date.')
        for m_start, m_end in month_ranges:
            chunk_label = f'{CURRENT_SEASON_LABEL}-{m_start[5:7]}'
            if chunk_label in cached_months:
                continue
            sc_month = load_statcast_range(m_start, m_end, label=chunk_label)
            append_to_cache(sc_month, CURRENT_SEASON_LABEL, chunk_label=chunk_label)
        return load_from_cache(CURRENT_SEASON_LABEL)

    cached_max_date = pd.to_datetime(cached['game_date']).max().date()
    days_stale = (TODAY - cached_max_date).days
    print(f'  Cached current-season data found, most recent date: {cached_max_date} '
          f'({days_stale} day(s) stale)')

    if days_stale <= 0:
        print('  Cache already up to date for today.')
        return cached

    # Pull only the new gap (day after the cache's last date, through today).
    # This is always a small window (days, not months) so it's left as a
    # single retry-wrapped call rather than further chunked.
    gap_start = (cached_max_date + timedelta(days=1)).strftime('%Y-%m-%d')
    gap_chunk_label = f'{CURRENT_SEASON_LABEL}-{TODAY_STR[5:7]}-gap-{TODAY_STR}'
    try:
        sc_gap = load_statcast_range(gap_start, TODAY_STR, label=f'{CURRENT_SEASON_LABEL}-gap')
        append_to_cache(sc_gap, CURRENT_SEASON_LABEL, chunk_label=gap_chunk_label)
        combined = pd.concat([cached, sc_gap], ignore_index=True)
        dedup_cols = [c for c in ['game_pk', 'at_bat_number', 'pitch_number', 'pitcher']
                      if c in combined.columns]
        if dedup_cols:
            combined = combined.drop_duplicates(subset=dedup_cols)
        return combined
    except ValueError as e:
        # No new games in the gap (e.g. off-day) — just use what's cached
        print(f'  No new pitches in gap ({e}); using cached data as-is.')
        return cached


def recompute_league_averages(sc):
    """Recomputes LEAGUE_AVG_* constants from real pulled data."""
    sc_pa = sc[sc['events'].notna()]
    final_pitch_idx = (
        sc_pa.groupby(['game_pk', 'at_bat_number', 'batter'])['pitch_number'].idxmax()
    )
    final_pitches = sc_pa.loc[final_pitch_idx]

    chase = sc['is_chase'].mean()
    return {
        'k_rate': final_pitches['ends_in_strikeout'].mean(),
        'whiff_rate': sc['is_whiff'].mean(),
        'called_strike_rate': sc['is_called_strike'].mean(),
        'csw_rate': sc['is_csw'].mean(),
        'chase_rate': chase if pd.notna(chase) else LEAGUE_AVG_CHASE_RATE,
    }


# ═══════════════════════════════════════════════════════════════════════════
# SECTION — BATTER K-VULNERABILITY PROFILE
# ═══════════════════════════════════════════════════════════════════════════

def build_batter_k_profile(sc):
    """Per (batter, pitch_category): K rate + sample size, with Bayesian
    shrinkage toward league average applied at lookup time, not here."""
    sc_pa = sc[sc['events'].notna()].copy()
    if len(sc_pa) == 0:
        return pd.DataFrame(columns=['batter', 'pitch_category', 'k_rate', 'n_pa'])

    final_pitch_idx = (
        sc_pa.groupby(['game_pk', 'at_bat_number', 'batter'])['pitch_number'].idxmax()
    )
    final_pitches = sc_pa.loc[final_pitch_idx]

    profile = (
        final_pitches.groupby(['batter', 'pitch_category'])
        .agg(k_rate=('ends_in_strikeout', 'mean'), n_pa=('ends_in_strikeout', 'size'))
        .reset_index()
    )
    return profile


def index_batter_profile(batter_profile):
    """
    Converts the batter_profile DataFrame into a dict keyed by
    (batter_id, category) for O(1) lookups. Without this, every call to
    bayesian_batter_k_rate does a full boolean-mask scan over the whole
    profile table — fine for a handful of live-slate lookups, but ruinous
    when called tens of thousands of times while building the training
    table (9 batters x 3 categories x thousands of historical games).
    """
    if len(batter_profile) == 0:
        return {}
    return {
        (row.batter, row.pitch_category): (row.k_rate, row.n_pa)
        for row in batter_profile.itertuples(index=False)
    }


def bayesian_batter_k_rate(batter_id, category, batter_profile_index, league_avg_k):
    """Shrinks a batter's observed K rate toward league average based on
    sample size — full weight at PA_FULL+, blended below that, pure league
    average below PA_BLEND.

    batter_profile_index must be the dict produced by index_batter_profile
    (NOT the raw DataFrame) — O(1) lookup instead of a per-call table scan.
    """
    hit = batter_profile_index.get((batter_id, category))
    if hit is None:
        return league_avg_k, 0

    observed, n_pa = hit
    n_pa = int(n_pa)
    observed = float(observed)

    if n_pa >= PA_FULL:
        return observed, n_pa
    elif n_pa >= PA_BLEND:
        weight = (n_pa - PA_BLEND) / (PA_FULL - PA_BLEND)
        blended = observed * (0.6 * weight + 0.4) + league_avg_k * (1 - (0.6 * weight + 0.4))
        return blended, n_pa
    else:
        return league_avg_k, n_pa


# ═══════════════════════════════════════════════════════════════════════════
# SECTION — PITCHER K-STUFF PROFILE (current/prior blend)
# ═══════════════════════════════════════════════════════════════════════════

def build_pitcher_k_profile(sc):
    sc_pa = sc[sc['events'].notna()].copy()
    if len(sc_pa) == 0:
        empty_splits = pd.DataFrame(columns=['pitcher', 'pitch_category', 'k_rate',
                                              'n_pa', 'whiff_rate', 'called_strike_rate',
                                              'csw_rate', 'n_pitches'])
        empty_usage = pd.DataFrame(columns=['pitcher', 'pitch_category', 'usage_pct'])
        return empty_splits, empty_usage

    final_pitch_idx = (
        sc_pa.groupby(['game_pk', 'at_bat_number', 'pitcher'])['pitch_number'].idxmax()
    )
    final_pitches = sc_pa.loc[final_pitch_idx]

    k_table = (
        final_pitches.groupby(['pitcher', 'pitch_category'])
        .agg(k_rate=('ends_in_strikeout', 'mean'), n_pa=('ends_in_strikeout', 'size'))
        .reset_index()
    )
    pitch_table = (
        sc.groupby(['pitcher', 'pitch_category'])
        .agg(whiff_rate=('is_whiff', 'mean'),
             called_strike_rate=('is_called_strike', 'mean'),
             csw_rate=('is_csw', 'mean'),
             n_pitches=('is_whiff', 'size'))
        .reset_index()
    )
    splits = k_table.merge(pitch_table, on=['pitcher', 'pitch_category'], how='outer')

    usage = (
        sc.groupby(['pitcher', 'pitch_category']).size()
          .groupby(level=0).transform(lambda x: x / x.sum())
          .reset_index(name='usage_pct')
    )
    return splits, usage


def blend_pitcher_k_profiles(splits_a, usage_a, splits_b, usage_b, sc_a, sc_b,
                              w_a=WEIGHT_CURRENT, w_b=WEIGHT_PRIOR):
    """Sample-proportional blend. Suffix 'a' = current season, 'b' = historical."""
    metrics = ['k_rate', 'whiff_rate', 'called_strike_rate', 'csw_rate']

    merged = splits_a.merge(
        splits_b, on=['pitcher', 'pitch_category'], suffixes=('_a', '_b'), how='outer'
    )
    ratio = w_b / w_a if w_a > 0 else 1.0
    merged['n_pa_a'] = merged['n_pa_a'].fillna(0)
    merged['n_pa_b'] = merged['n_pa_b'].fillna(0)
    merged['w_a_eff'] = merged['n_pa_a'] / (merged['n_pa_a'] + merged['n_pa_b'] * ratio)
    merged['w_a_eff'] = merged['w_a_eff'].fillna(1.0)

    for m in metrics:
        ca, cb_, cblend = f'{m}_a', f'{m}_b', f'{m}_blended'
        merged[cblend] = merged[ca].fillna(0) * merged['w_a_eff'] + \
                          merged[cb_].fillna(0) * (1 - merged['w_a_eff'])
        merged.loc[merged[ca].isna(), cblend] = merged[cb_]
        merged.loc[merged[cb_].isna(), cblend] = merged[ca]

    keep = ['pitcher', 'pitch_category', 'n_pa_a', 'n_pa_b'] + [f'{m}_blended' for m in metrics]
    pitcher_splits = merged[keep].copy()

    usage_merged = usage_a.merge(
        usage_b, on=['pitcher', 'pitch_category'], suffixes=('_a', '_b'), how='outer'
    )
    pc_a = sc_a.groupby('pitcher').size().rename('n_pitches_a')
    pc_b = sc_b.groupby('pitcher').size().rename('n_pitches_b')
    usage_merged = usage_merged.join(pc_a, on='pitcher').join(pc_b, on='pitcher')
    usage_merged['n_pitches_a'] = usage_merged['n_pitches_a'].fillna(0)
    usage_merged['n_pitches_b'] = usage_merged['n_pitches_b'].fillna(0)
    usage_merged['wu_a'] = usage_merged['n_pitches_a'] / \
        (usage_merged['n_pitches_a'] + usage_merged['n_pitches_b'] * ratio)
    usage_merged['wu_a'] = usage_merged['wu_a'].fillna(1.0)
    usage_merged['usage_pct_blended'] = (
        usage_merged['usage_pct_a'].fillna(0) * usage_merged['wu_a']
        + usage_merged['usage_pct_b'].fillna(0) * (1 - usage_merged['wu_a'])
    )
    usage_merged['usage_pct_blended'] = usage_merged.groupby('pitcher')['usage_pct_blended'].transform(
        lambda x: x / x.sum() if x.sum() > 0 else x
    )
    pitcher_usage = usage_merged[['pitcher', 'pitch_category', 'usage_pct_blended']].copy()
    return pitcher_splits, pitcher_usage


def index_pitcher_profile(pitcher_splits, pitcher_usage):
    """
    Converts pitcher_splits/pitcher_usage into dicts keyed by
    (pitcher_id, category) for O(1) lookups, for the same reason as
    index_batter_profile — get_pitcher_k_vals is called 3x per batter x 9
    batters x thousands of historical games while building the training
    table, and a per-call boolean-mask scan at that volume is what causes
    the function to silently run for hours.
    """
    splits_idx = {}
    if len(pitcher_splits) > 0:
        for row in pitcher_splits.itertuples(index=False):
            splits_idx[(row.pitcher, row.pitch_category)] = (
                row.k_rate_blended, row.whiff_rate_blended,
                row.called_strike_rate_blended, row.csw_rate_blended,
            )
    usage_idx = {}
    if len(pitcher_usage) > 0:
        for row in pitcher_usage.itertuples(index=False):
            usage_idx[(row.pitcher, row.pitch_category)] = row.usage_pct_blended
    return splits_idx, usage_idx


def get_pitcher_k_vals(pitcher_id, category, pitcher_splits_index, pitcher_usage_index):
    """Returns (k_rate, whiff_rate, called_strike_rate, csw_rate, usage_pct)
    for a pitcher x pitch category, with league-average fallback.

    pitcher_splits_index / pitcher_usage_index must be the dicts produced
    by index_pitcher_profile (NOT the raw DataFrames) — O(1) lookup instead
    of a per-call table scan.
    """
    hit = pitcher_splits_index.get((pitcher_id, category))
    if hit is not None:
        k_rate, whiff, cs, csw = (float(v) for v in hit)
    else:
        k_rate, whiff, cs, csw = (LEAGUE_AVG_K_RATE, LEAGUE_AVG_WHIFF_RATE,
                                   LEAGUE_AVG_CALLED_STRIKE_RATE, LEAGUE_AVG_CSW_RATE)
    usage_hit = pitcher_usage_index.get((pitcher_id, category))
    usage = float(usage_hit) if usage_hit is not None else (1 / 3)
    return k_rate, whiff, cs, csw, usage


# ═══════════════════════════════════════════════════════════════════════════
# SECTION — CALCULATION ENGINE: game-level strikeout projection
# ═══════════════════════════════════════════════════════════════════════════
# Formula per opposing batter, per pitch category:
#   matchup_k_rate(cat) = (batter_k_rate(cat) * pitcher_k_rate(cat)) / league_avg_k_rate
# Summed across categories weighted by pitcher usage% gives one batter's
# expected K probability against this pitcher. Multiplied by that batter's
# expected PAs in the game, then SUMMED across the lineup for the pitcher's
# projected strikeout total.

def estimate_expected_tbf(pitcher_id, sc, lookback_games=10, default_tbf=22.0):
    """Estimates a starting pitcher's expected Total Batters Faced for a
    game, based on his recent per-start TBF trend."""
    p_pitches = sc[sc['pitcher'] == pitcher_id]
    if len(p_pitches) == 0:
        return default_tbf, 0

    tbf_per_game = (
        p_pitches.groupby('game_pk')['at_bat_number']
        .nunique()
        .sort_index()
    )
    if len(tbf_per_game) == 0:
        return default_tbf, 0

    recent = tbf_per_game.tail(lookback_games)
    return float(recent.mean()), len(recent)


def batting_order_pa_weights():
    """Relative PA weight by batting-order slot, normalized to sum to 1.0."""
    raw = {1: 1.13, 2: 1.10, 3: 1.08, 4: 1.03, 5: 1.00,
           6: 0.97, 7: 0.94, 8: 0.91, 9: 0.88}
    total = sum(raw.values())
    return {slot: w / total for slot, w in raw.items()}


BATTING_ORDER_WEIGHTS = batting_order_pa_weights()


def calculate_batter_k_probability(batter_id, pitcher_id, batter_profile_index,
                                    pitcher_splits_index, pitcher_usage_index,
                                    league_avg_k=None):
    """One batter's expected strikeout probability against one pitcher,
    summed across pitch categories weighted by the PITCHER's usage%.

    batter_profile_index / pitcher_splits_index / pitcher_usage_index must
    be the dicts produced by index_batter_profile / index_pitcher_profile
    — NOT the raw DataFrames. This function is called 9x per game (once
    per lineup slot) and thousands of times while building the training
    table, so per-call DataFrame scans here are what previously caused the
    pipeline to silently run for hours.
    """
    league_avg_k = LEAGUE_AVG_K_RATE if league_avg_k is None else league_avg_k
    k_matchup = 0.0
    usage_total = 0.0

    for cat in PITCH_CATEGORIES:
        batter_k, _ = bayesian_batter_k_rate(batter_id, cat, batter_profile_index, league_avg_k)
        pitcher_k, _, _, _, usage = get_pitcher_k_vals(
            pitcher_id, cat, pitcher_splits_index, pitcher_usage_index
        )
        cat_k = (batter_k * pitcher_k) / league_avg_k if league_avg_k > 0 else 0.0
        k_matchup += cat_k * usage
        usage_total += usage

    if usage_total > 0:
        k_matchup /= usage_total

    return float(np.clip(k_matchup, 0.0, 0.85))


def calculate_game_k_projection(pitcher_id, opposing_lineup_batter_ids,
                                 batter_profile_index, pitcher_splits_index,
                                 pitcher_usage_index, sc_for_tbf, league_avg_k=None):
    """
    CALCULATION ENGINE — top-level function.
    Projects a starting pitcher's total strikeouts for a game against a
    specific opposing lineup (list of batter_ids in batting-order sequence).

    batter_profile_index / pitcher_splits_index / pitcher_usage_index must
    be pre-built via index_batter_profile() / index_pitcher_profile() —
    build them ONCE outside any per-game loop and pass the same dicts to
    every call, rather than re-indexing (or worse, re-scanning) per game.
    """
    expected_tbf, n_games_used = estimate_expected_tbf(pitcher_id, sc_for_tbf)

    n_slots = len(opposing_lineup_batter_ids)
    if n_slots == 0:
        return {'projected_ks': np.nan, 'expected_tbf': expected_tbf, 'breakdown': []}

    slot_numbers = [(i % 9) + 1 for i in range(n_slots)]
    raw_weights = [BATTING_ORDER_WEIGHTS[s] for s in slot_numbers]
    weight_sum = sum(raw_weights)
    pa_per_slot = [expected_tbf * (w / weight_sum) for w in raw_weights]

    breakdown = []
    total_ks = 0.0
    for batter_id, slot, expected_pa in zip(opposing_lineup_batter_ids, slot_numbers, pa_per_slot):
        k_prob = calculate_batter_k_probability(
            batter_id, pitcher_id, batter_profile_index, pitcher_splits_index,
            pitcher_usage_index, league_avg_k
        )
        batter_expected_ks = k_prob * expected_pa
        total_ks += batter_expected_ks
        breakdown.append({
            'batter': batter_id, 'batting_order': slot,
            'k_probability': round(k_prob, 3),
            'expected_pa': round(expected_pa, 2),
            'expected_ks': round(batter_expected_ks, 3),
        })

    return {
        'projected_ks': round(total_ks, 2),
        'expected_tbf': round(expected_tbf, 1),
        'n_recent_games_used': n_games_used,
        'breakdown': breakdown,
    }


# ═══════════════════════════════════════════════════════════════════════════
# SECTION — LINEUPS: posted (today) and EXPECTED (fallback when not posted)
# ═══════════════════════════════════════════════════════════════════════════
# This section is the new piece that didn't exist in the original notebook.
# When today's lineup isn't posted yet (usually unavailable until 1-3 hours
# before first pitch), we build an "expected" lineup from the team's recent
# games instead of falling back to an empty list / Calculation-Engine-only
# projection. This lets KNN and XGBoost run for every pitcher on every slate,
# all day, not just in the hour before first pitch.

LOOKBACK_GAMES_FOR_LINEUP = 5   # how many recent boxscores to sample from


def get_posted_lineup(game_pk):
    """Returns {'home': [batter_ids in order], 'away': [...]} for a single
    game, or empty lists per side if lineups aren't posted yet."""
    url = f'{MLB_API}/game/{game_pk}/boxscore'
    r = requests.get(url, timeout=15).json()
    lineups = {'home': [], 'away': []}
    for side in ['home', 'away']:
        players = r.get('teams', {}).get(side, {}).get('players', {})
        ordered = []
        for p in players.values():
            order = p.get('battingOrder')
            if not order:
                continue
            slot = int(str(order)[:1])
            ordered.append((slot, p['person']['id'], p['person'].get('fullName', '')))
        ordered.sort(key=lambda x: x[0])
        lineups[side] = [(pid, name) for _, pid, name in ordered]
    return lineups


def get_team_recent_completed_games(team_id, before_date_str, n_games=LOOKBACK_GAMES_FOR_LINEUP):
    """Fetches a team's last n completed game_pks strictly before a given
    date, most recent first."""
    end = datetime.strptime(before_date_str, '%Y-%m-%d').date()
    start = end - timedelta(days=21)   # generous window to ensure n_games found
    url = (f'{MLB_API}/schedule?sportId=1&teamId={team_id}'
           f'&startDate={start.strftime("%Y-%m-%d")}&endDate={end.strftime("%Y-%m-%d")}')
    try:
        r = requests.get(url, timeout=15).json()
    except Exception as e:
        print(f'    WARN schedule lookup team {team_id}: {e}')
        return []

    game_pks = []
    for d in r.get('dates', []):
        for g in d.get('games', []):
            if g.get('status', {}).get('detailedState') != 'Final':
                continue
            game_pks.append((d['date'], g['gamePk']))

    game_pks.sort(key=lambda x: x[0], reverse=True)
    return [pk for _, pk in game_pks[:n_games]]


def build_expected_lineup(team_id, before_date_str, n_games=LOOKBACK_GAMES_FOR_LINEUP):
    """
    Builds a 9-man expected batting order for a team from its last n
    completed games, when today's actual lineup isn't posted yet.

    Method: for each of the last n games, pull the team's posted lineup.
    For each batting-order slot (1-9), take the most frequently used
    player in that slot across those games (ties broken by most recent
    appearance). This is more robust than "just use last night's lineup"
    since it smooths out a single game's matchup-specific lineup tweaks
    (e.g. resting a player against a tough same-handed starter) while
    still tracking real changes (e.g. a new everyday player gets there
    fast since recency is the tiebreaker).

    Returns a list of (batter_id, name) tuples in slot order 1-9, or an
    empty list if no recent games / lineup data could be found at all
    (extremely rare — would require a brand new team with zero games).
    """
    recent_pks = get_team_recent_completed_games(team_id, before_date_str, n_games)
    if not recent_pks:
        return []

    # slot -> list of (batter_id, name) seen in that slot, most recent first
    slot_appearances = {slot: [] for slot in range(1, 10)}

    for game_pk in recent_pks:
        try:
            lineups = get_posted_lineup(game_pk)
        except Exception:
            continue
        # Need to know which side (home/away) this team was
        try:
            box_url = f'{MLB_API}/game/{game_pk}/boxscore'
            box = requests.get(box_url, timeout=15).json()
            home_id = box.get('teams', {}).get('home', {}).get('team', {}).get('id')
            side = 'home' if home_id == team_id else 'away'
        except Exception:
            continue

        for slot_idx, (pid, name) in enumerate(lineups.get(side, [])[:9], start=1):
            slot_appearances[slot_idx].append((pid, name))
        time.sleep(SLEEP_S)

    expected = []
    for slot in range(1, 10):
        appearances = slot_appearances[slot]
        if not appearances:
            continue
        # Most frequent player in this slot; ties broken by most recent
        # (appearances list is already most-recent-first, so Counter's
        # first-seen-wins-on-tie behavior naturally favors recency)
        counts = Counter(pid for pid, _ in appearances)
        best_pid, _ = counts.most_common(1)[0]
        best_name = next(name for pid, name in appearances if pid == best_pid)
        expected.append((best_pid, best_name))

    return expected


def get_lineup_for_game(team_id, opponent_game_pk, game_date_str,
                         today_posted_lineup=None):
    """
    Single entry point: returns (lineup, source) where source is
    'posted' or 'expected'. Tries the real posted lineup first; falls
    back to the expected lineup built from recent games if not posted.
    """
    if today_posted_lineup:
        return today_posted_lineup, 'posted'

    expected = build_expected_lineup(team_id, game_date_str)
    if expected:
        return expected, 'expected'

    return [], 'none'


# ═══════════════════════════════════════════════════════════════════════════
# SECTION — HISTORICAL TRAINING TABLE (for KNN + XGBoost)
# ═══════════════════════════════════════════════════════════════════════════
# Builds one row per (pitcher, game) with the ACTUAL strikeout count as the
# label, and features computed using ONLY data available BEFORE that game's
# date (as-of-date rolling profiles) to avoid leakage. Training always uses
# the REAL historical opposing lineup (it's known after the fact) — the
# expected-lineup fallback is a live/today-only concern, never a training
# concern.

def get_starting_pitchers_by_game(sc):
    """
    Identifies the starting pitcher for each (game_pk, side) using the
    "early at-bat, high pitch-count" heuristic (robust proxy when boxscore
    cross-referencing isn't worth the API cost for bulk historical data).
    """
    early_pitchers = sc[sc['at_bat_number'] <= 3][['game_pk', 'pitcher']].drop_duplicates()
    pitch_counts = sc.groupby(['game_pk', 'pitcher']).size().rename('pitch_count').reset_index()
    candidates = early_pitchers.merge(pitch_counts, on=['game_pk', 'pitcher'])

    candidates = candidates.sort_values(['game_pk', 'pitch_count'], ascending=[True, False])
    starters = candidates.groupby('game_pk').head(2).copy()

    game_dates = sc.groupby('game_pk')['game_date'].first().reset_index()
    starters = starters.merge(game_dates, on='game_pk', how='left')
    return starters[['game_pk', 'game_date', 'pitcher']]


def get_actual_lineup_for_game(sc, game_pk, pitcher_id):
    """Returns the list of batter_ids who actually faced this pitcher in
    this game, in approximate batting-order-of-appearance sequence."""
    g = sc[(sc['game_pk'] == game_pk) & (sc['pitcher'] == pitcher_id)]
    seen = (
        g.sort_values('at_bat_number')[['at_bat_number', 'batter']]
        .drop_duplicates(subset='at_bat_number')['batter']
        .tolist()
    )
    return seen


def build_training_table(sc_all, starters_df, batter_profile, pitcher_splits,
                          pitcher_usage, min_games_history=3, progress_every=250):
    """
    One row per (pitcher, game_pk):
      - actual_ks               : label
      - calculated_projected_ks : Calc Engine's own projection (becomes a
                                   feature, so ML can learn to correct it)
      - expected_tbf
      - games_pitched_before    : pitcher's start count prior to this game
                                   (as-of-date, no leakage)
      - recent_3start_k_rate    : pitcher's K rate over his last 3 starts
                                   STRICTLY before this game's date
      - opposing_lineup_size

    PERFORMANCE NOTE: the naive version of this function re-scanned the
    ENTIRE multi-season sc_all DataFrame (millions of rows) once per
    (pitcher, game) row, AND re-scanned the batter/pitcher profile tables
    with boolean masking on every lookup inside calculate_game_k_projection
    (9 batters x 3 categories x thousands of historical games). With
    thousands of starter-games across 3+ seasons, that combination is what
    silently ran for hours with no console output. This version (a) groups
    sc_all by pitcher ONCE up front, and (b) indexes the profile tables
    into O(1) dicts ONCE up front, then prints progress every
    `progress_every` rows so a real hang is never silent again.
    """
    t_start = time.time()
    rows = []

    # Pre-group: pitcher_id -> that pitcher's full pitch log, sorted by date.
    # Avoids re-filtering the full multi-million-row sc_all per game.
    print(f'  Pre-grouping {len(sc_all):,} pitches by pitcher...')
    pitcher_groups = {
        pid: g.sort_values('game_date')
        for pid, g in sc_all.groupby('pitcher')
    }
    print(f'  Grouped into {len(pitcher_groups):,} pitcher logs.')

    # Pre-index the profile tables ONCE — turns every downstream lookup
    # from an O(n) DataFrame scan into an O(1) dict access.
    print('  Indexing batter/pitcher profile tables for fast lookup...')
    batter_profile_index = index_batter_profile(batter_profile)
    pitcher_splits_index, pitcher_usage_index = index_pitcher_profile(pitcher_splits, pitcher_usage)
    print(f'  Indexed {len(batter_profile_index):,} batter-category entries, '
          f'{len(pitcher_splits_index):,} pitcher-category entries.')

    pitcher_game_dates = (
        starters_df.sort_values('game_date')
        .groupby('pitcher')['game_date']
        .apply(list)
        .to_dict()
    )

    n_total = len(starters_df)
    print(f'  Building training rows for {n_total:,} (pitcher, game) candidates...')

    for i, (_, srow) in enumerate(starters_df.iterrows(), start=1):
        if i % progress_every == 0 or i == n_total:
            elapsed = time.time() - t_start
            rate = i / elapsed if elapsed > 0 else 0
            eta = (n_total - i) / rate if rate > 0 else float('nan')
            print(f'    ...{i:,}/{n_total:,} candidates processed '
                  f'({len(rows):,} kept, {elapsed:.0f}s elapsed, ETA {eta:.0f}s)')

        pitcher_id = srow['pitcher']
        game_pk    = srow['game_pk']
        game_date  = srow['game_date']

        pitcher_log = pitcher_groups.get(pitcher_id)
        if pitcher_log is None:
            continue

        # As-of-date history: strictly before this game — now scanning only
        # this pitcher's own (small) log, not the full multi-season table.
        history = pitcher_log[pitcher_log['game_date'] < game_date]
        prior_game_dates = [d for d in pitcher_game_dates.get(pitcher_id, []) if d < game_date]
        games_pitched_before = len(prior_game_dates)

        if games_pitched_before < min_games_history:
            continue   # not enough history yet for a meaningful row

        # Actual lineup faced (known after the fact — fine for training).
        # Pulled from the pitcher's own log + game_pk filter (small slice).
        game_rows = pitcher_log[pitcher_log['game_pk'] == game_pk]
        if len(game_rows) == 0:
            continue
        lineup = (
            game_rows.sort_values('at_bat_number')[['at_bat_number', 'batter']]
            .drop_duplicates(subset='at_bat_number')['batter']
            .tolist()
        )
        if not lineup:
            continue

        # Actual strikeouts that game (label)
        actual_ks = int(game_rows['ends_in_strikeout'].sum())

        # Calc Engine projection, using only as-of-date history for TBF/profiles
        calc_result = calculate_game_k_projection(
            pitcher_id, lineup, batter_profile_index, pitcher_splits_index,
            pitcher_usage_index, history
        )
        if pd.isna(calc_result['projected_ks']):
            continue

        # Recent-3-start K rate, strictly before this game
        recent_dates = sorted(prior_game_dates)[-3:]
        recent_pitches = history[history['game_date'].isin(recent_dates)]
        recent_k_rate = np.nan
        if len(recent_pitches) > 0:
            rp_pa = recent_pitches[recent_pitches['events'].notna()]
            if len(rp_pa) > 0:
                fp_idx = rp_pa.groupby(['game_pk', 'at_bat_number'])['pitch_number'].idxmax()
                recent_k_rate = rp_pa.loc[fp_idx, 'ends_in_strikeout'].mean()

        rows.append({
            'pitcher': pitcher_id,
            'game_pk': game_pk,
            'game_date': game_date,
            'actual_ks': actual_ks,
            'calculated_projected_ks': calc_result['projected_ks'],
            'expected_tbf': calc_result['expected_tbf'],
            'games_pitched_before': games_pitched_before,
            'recent_3start_k_rate': recent_k_rate,
            'opposing_lineup_size': len(lineup),
        })

    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION — TRAIN/TEST SPLIT (time-based, no leakage)
# ═══════════════════════════════════════════════════════════════════════════

def time_based_split(training_table, test_frac=0.2):
    tt = training_table.sort_values('game_date').reset_index(drop=True)
    n_test = max(1, int(len(tt) * test_frac))
    train_df = tt.iloc[:-n_test].copy()
    test_df  = tt.iloc[-n_test:].copy()
    print(f'  Time-based split: {len(train_df)} train rows '
          f'(through {train_df["game_date"].max()}), '
          f'{len(test_df)} test rows '
          f'({test_df["game_date"].min()} to {test_df["game_date"].max()})')
    return train_df, test_df


def prepare_features(df, feature_columns=FEATURE_COLUMNS, fill_value=None):
    """Extracts the feature matrix, filling missing values with column
    medians computed from TRAIN data only (passed via fill_value) to avoid
    leaking test-set statistics into imputation."""
    X = df[feature_columns].copy()
    if fill_value is None:
        fill_value = X.median(numeric_only=True)
    X = X.fillna(fill_value)
    return X, fill_value


# ═══════════════════════════════════════════════════════════════════════════
# SECTION — MODELS: Calculation Engine (baseline) / KNN / XGBoost
# ═══════════════════════════════════════════════════════════════════════════

def train_models(X_train, y_train):
    """Trains the KNN regressor and XGBoost regressor. Returns
    (knn_model, scaler, xgb_model)."""
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)

    knn_k = max(1, min(15, len(X_train) // 3)) if len(X_train) > 0 else 1
    knn_model = KNeighborsRegressor(n_neighbors=knn_k, weights='distance')
    if len(X_train) > 0:
        knn_model.fit(X_train_scaled, y_train)
    print(f'  KNN fit with k={knn_k} neighbors.')

    print('  Training XGBoost...')
    xgb_model = XGBRegressor(**XGB_PARAMS)
    if len(X_train) >= 5:
        xgb_model.fit(X_train, y_train, verbose=False)
    else:
        print('  Too few training rows to fit XGBoost meaningfully — skipping fit.')

    return knn_model, scaler, xgb_model


def evaluate_predictions(y_true, y_pred, label):
    """Backtest metrics for one model's predictions vs. actual strikeouts."""
    mask = ~np.isnan(y_pred)
    if mask.sum() == 0:
        print(f'  {label}: no valid predictions to evaluate.')
        return None
    yt, yp = np.asarray(y_true)[mask], np.asarray(y_pred)[mask]
    mae  = mean_absolute_error(yt, yp)
    rmse = mean_squared_error(yt, yp) ** 0.5
    r2   = r2_score(yt, yp) if len(yt) > 1 else np.nan
    print(f'  {label:20s}  MAE={mae:.3f}  RMSE={rmse:.3f}  R2={r2:.3f}  n={mask.sum()}')
    return {'mae': mae, 'rmse': rmse, 'r2': r2, 'n': int(mask.sum())}


def load_or_train_models(training_table):
    """
    Loads cached KNN + XGBoost models if they're fresh (trained within the
    last MODEL_RETRAIN_DAYS), otherwise retrains from the full training
    table and caches the result. Keeps daily Actions runtime low — only
    one run per week pays the full training cost.
    """
    if os.path.exists(MODELS_PKL):
        with open(MODELS_PKL, 'rb') as f:
            cache = pickle.load(f)
        trained_date = cache.get('trained_date')
        if trained_date:
            days_old = (TODAY - datetime.strptime(trained_date, '%Y-%m-%d').date()).days
            if days_old < MODEL_RETRAIN_DAYS:
                print(f'  Loaded cached models (trained {days_old} day(s) ago).')
                return cache

    print(f'  Training new models ({len(training_table)} historical rows)...')
    train_df, test_df = time_based_split(training_table, test_frac=0.2)
    X_train, train_fill_values = prepare_features(train_df)
    y_train = train_df[LABEL_COLUMN].values
    X_test, _ = prepare_features(test_df, fill_value=train_fill_values)
    y_test = test_df[LABEL_COLUMN].values

    knn_model, scaler, xgb_model = train_models(X_train, y_train)

    print('\n  Backtest (most recent 20% of historical games, time-based hold-out):')
    evaluate_predictions(y_test, test_df['calculated_projected_ks'].values, 'Calculation Engine')
    if len(X_test) > 0:
        knn_preds = knn_model.predict(scaler.transform(X_test))
        evaluate_predictions(y_test, knn_preds, 'KNN')
    if len(X_test) >= 5:
        xgb_preds = xgb_model.predict(X_test)
        evaluate_predictions(y_test, xgb_preds, 'XGBoost (Gradient Boosting)')

    cache = {
        'trained_date': TODAY_STR,
        'knn_model': knn_model,
        'scaler': scaler,
        'xgb_model': xgb_model,
        'train_fill_values': train_fill_values,
        'feature_columns': FEATURE_COLUMNS,
    }
    with open(MODELS_PKL, 'wb') as f:
        pickle.dump(cache, f)
    print('  ✓ Models cached.')
    return cache


# ═══════════════════════════════════════════════════════════════════════════
# SECTION — LIVE MODE: TODAY'S SLATE
# ═══════════════════════════════════════════════════════════════════════════
# Every probable starter gets all three predictions (Calc Engine, KNN,
# XGBoost), regardless of whether today's lineup is posted. If it isn't,
# we substitute the EXPECTED lineup (built from recent games) and tag the
# row with lineup_source so the site can show "Confirmed" vs "Projected".

def get_todays_schedule(date_str):
    url = (f'{MLB_API}/schedule?sportId=1&date={date_str}'
           f'&hydrate=probablePitcher,team,lineups')
    r = requests.get(url, timeout=15).json()
    games = []
    for d in r.get('dates', []):
        for g in d.get('games', []):
            home = g['teams']['home']
            away = g['teams']['away']
            games.append({
                'game_pk':            g['gamePk'],
                'game_date':          d['date'],
                'home_team_id':       home['team']['id'],
                'home_team_name':     home['team']['name'],
                'home_team_abbr':     home['team'].get('abbreviation', '?'),
                'away_team_id':       away['team']['id'],
                'away_team_name':     away['team']['name'],
                'away_team_abbr':     away['team'].get('abbreviation', '?'),
                'home_pitcher_id':    home.get('probablePitcher', {}).get('id'),
                'home_pitcher_name':  home.get('probablePitcher', {}).get('fullName', 'TBD'),
                'away_pitcher_id':    away.get('probablePitcher', {}).get('id'),
                'away_pitcher_name':  away.get('probablePitcher', {}).get('fullName', 'TBD'),
            })
    return games


def predict_todays_slate(games, batter_profile, pitcher_splits, pitcher_usage,
                          sc_for_tbf, model_cache):
    """
    Runs the Calculation Engine (always) plus KNN and XGBoost (always —
    using a posted or expected lineup, whichever is available) for every
    probable starter on today's slate.
    """
    knn_model        = model_cache['knn_model']
    scaler           = model_cache['scaler']
    xgb_model        = model_cache['xgb_model']
    train_fill_values = model_cache['train_fill_values']
    feature_columns  = model_cache['feature_columns']

    # Index once for fast O(1) lookups inside the per-pitcher loop below
    # (same fix applied to build_training_table — see its docstring).
    batter_profile_index = index_batter_profile(batter_profile)
    pitcher_splits_index, pitcher_usage_index = index_pitcher_profile(pitcher_splits, pitcher_usage)

    rows = []
    for game in games:
        try:
            posted = get_posted_lineup(game['game_pk'])
        except Exception:
            posted = {'home': [], 'away': []}

        matchups = [
            ('home', game['home_pitcher_id'], game['home_pitcher_name'],
             game['away_team_id'], game['away_team_abbr'], game['home_team_abbr'],
             posted.get('away', [])),
            ('away', game['away_pitcher_id'], game['away_pitcher_name'],
             game['home_team_id'], game['home_team_abbr'], game['away_team_abbr'],
             posted.get('home', [])),
        ]

        for side, pitcher_id, pitcher_name, opp_team_id, opp_abbr, team_abbr, posted_lineup in matchups:
            if pitcher_id is None:
                continue
            pitcher_id = int(pitcher_id)

            lineup_pairs, lineup_source = get_lineup_for_game(
                opp_team_id, game['game_pk'], game['game_date'],
                today_posted_lineup=posted_lineup if posted_lineup else None,
            )
            lineup_ids = [pid for pid, _name in lineup_pairs]

            calc_result = calculate_game_k_projection(
                pitcher_id, lineup_ids, batter_profile_index, pitcher_splits_index,
                pitcher_usage_index, sc_for_tbf
            )

            row = {
                'pitcher_id':          pitcher_id,
                'pitcher_name':        pitcher_name,
                'team':                team_abbr,
                'opponent':            opp_abbr,
                'game_time':           get_game_time_et(game.get('game_date', '')),
                'lineup_source':       lineup_source,      # 'posted' | 'expected' | 'none'
                'lineup_posted':       lineup_source == 'posted',
                'calculated_projected_ks': calc_result['projected_ks'],
                'expected_tbf':        calc_result['expected_tbf'],
                'knn_projected_ks':    np.nan,
                'gbm_projected_ks':    np.nan,
            }

            if lineup_ids:
                games_pitched_before = sc_for_tbf[sc_for_tbf['pitcher'] == pitcher_id]['game_pk'].nunique()
                pitcher_hist = sc_for_tbf[sc_for_tbf['pitcher'] == pitcher_id]
                recent_game_pks = (
                    pitcher_hist.groupby('game_pk')['game_date'].first()
                    .sort_values().tail(3).index.tolist()
                )
                recent_pitches = pitcher_hist[pitcher_hist['game_pk'].isin(recent_game_pks)]
                recent_k_rate = np.nan
                if len(recent_pitches) > 0:
                    rp_pa = recent_pitches[recent_pitches['events'].notna()]
                    if len(rp_pa) > 0:
                        fp_idx = rp_pa.groupby(['game_pk', 'at_bat_number'])['pitch_number'].idxmax()
                        recent_k_rate = rp_pa.loc[fp_idx, 'ends_in_strikeout'].mean()

                feat_row = pd.DataFrame([{
                    'calculated_projected_ks': calc_result['projected_ks'],
                    'expected_tbf': calc_result['expected_tbf'],
                    'games_pitched_before': games_pitched_before,
                    'recent_3start_k_rate': recent_k_rate,
                    'opposing_lineup_size': len(lineup_ids),
                }])[feature_columns]

                if train_fill_values is not None:
                    feat_row = feat_row.fillna(train_fill_values)

                try:
                    feat_scaled = scaler.transform(feat_row)
                    row['knn_projected_ks'] = round(float(knn_model.predict(feat_scaled)[0]), 2)
                except Exception as e:
                    print(f'    WARN KNN predict for pitcher {pitcher_id}: {e}')

                try:
                    row['gbm_projected_ks'] = round(float(xgb_model.predict(feat_row)[0]), 2)
                except Exception as e:
                    print(f'    WARN XGBoost predict for pitcher {pitcher_id}: {e}')

            rows.append(row)

    return pd.DataFrame(rows)


def get_game_time_et(game_date_str):
    if not game_date_str:
        return 'TBD'
    try:
        dt_utc = datetime.strptime(game_date_str[:16], '%Y-%m-%dT%H:%M')
        dt_et  = dt_utc - timedelta(hours=4)
        hour   = dt_et.hour % 12 or 12
        ampm   = 'AM' if dt_et.hour < 12 else 'PM'
        return f'{hour}:{dt_et.minute:02d} {ampm} ET'
    except Exception:
        return 'TBD'


# ═══════════════════════════════════════════════════════════════════════════
# SECTION — HISTORY / GRADING (mirrors hitters_hr_model.py's pattern)
# ═══════════════════════════════════════════════════════════════════════════

def load_history():
    if os.path.exists(HIST_JSON):
        with open(HIST_JSON) as f:
            return json.load(f)
    return {'records': []}


def save_history(history):
    with open(HIST_JSON, 'w') as f:
        json.dump(history, f, indent=2)


def get_actual_ks_for_pitcher(pitcher_id, game_date_str):
    """Looks up a pitcher's actual strikeout total for a completed game,
    via the MLB StatsAPI game log (lightweight — no Statcast needed)."""
    try:
        url = (f'{MLB_API}/people/{pitcher_id}/stats'
               f'?stats=gameLog&group=pitching&season={CURRENT_YEAR}')
        r = requests.get(url, timeout=10).json()
        splits = r.get('stats', [{}])[0].get('splits', [])
        for s in splits:
            if s.get('date') == game_date_str:
                return int(s.get('stat', {}).get('strikeOuts', 0) or 0)
    except Exception:
        pass
    return None


def grade_yesterday(history, yesterday_str):
    """Backfills actual strikeout totals for yesterday's predictions and
    computes simple per-model error stats."""
    record = next((r for r in history['records'] if r['date'] == yesterday_str), None)
    if not record or record.get('graded'):
        return

    errors = {'calc': [], 'knn': [], 'gbm': []}
    for p in record.get('predictions', []):
        actual = get_actual_ks_for_pitcher(p['pitcher_id'], yesterday_str)
        if actual is None:
            continue
        p['actual_ks'] = actual
        if p.get('calculated_projected_ks') is not None:
            errors['calc'].append(abs(actual - p['calculated_projected_ks']))
        if p.get('knn_projected_ks') is not None and not pd.isna(p.get('knn_projected_ks')):
            errors['knn'].append(abs(actual - p['knn_projected_ks']))
        if p.get('gbm_projected_ks') is not None and not pd.isna(p.get('gbm_projected_ks')):
            errors['gbm'].append(abs(actual - p['gbm_projected_ks']))
        time.sleep(SLEEP_S)

    record['summary'] = {
        'calc_mae': round(np.mean(errors['calc']), 3) if errors['calc'] else None,
        'knn_mae':  round(np.mean(errors['knn']), 3) if errors['knn'] else None,
        'gbm_mae':  round(np.mean(errors['gbm']), 3) if errors['gbm'] else None,
        'n_graded': sum(1 for p in record['predictions'] if 'actual_ks' in p),
    }
    record['graded'] = True
    print(f'  Graded {yesterday_str}: {record["summary"]}')


# ═══════════════════════════════════════════════════════════════════════════
# SECTION — MAIN
# ═══════════════════════════════════════════════════════════════════════════

def run():
    yesterday_str = (TODAY - timedelta(days=1)).strftime('%Y-%m-%d')

    # ── 1. Load history and grade yesterday ────────────────────────────────
    history = load_history()
    grade_yesterday(history, yesterday_str)

    # ── 2. Statcast pull (historical pool cached forever, current season
    #       refreshed incrementally) ────────────────────────────────────────
    print('\nLoading historical Statcast pool...')
    sc_historical_pool = get_historical_data()

    print('Refreshing current-season Statcast data...')
    sc_current = get_current_season_data()

    sc_all = pd.concat([sc_historical_pool, sc_current], ignore_index=True)
    print(f'Combined pool: {len(sc_all):,} pitches total\n')

    league_avgs = recompute_league_averages(sc_current)
    global LEAGUE_AVG_K_RATE, LEAGUE_AVG_WHIFF_RATE, LEAGUE_AVG_CALLED_STRIKE_RATE
    global LEAGUE_AVG_CSW_RATE, LEAGUE_AVG_CHASE_RATE
    LEAGUE_AVG_K_RATE             = league_avgs['k_rate']
    LEAGUE_AVG_WHIFF_RATE         = league_avgs['whiff_rate']
    LEAGUE_AVG_CALLED_STRIKE_RATE = league_avgs['called_strike_rate']
    LEAGUE_AVG_CSW_RATE           = league_avgs['csw_rate']
    LEAGUE_AVG_CHASE_RATE         = league_avgs['chase_rate']

    # ── 3. Build batter + pitcher profiles ──────────────────────────────────
    print('Building batter K-vulnerability profile...')
    batter_profile = build_batter_k_profile(sc_all)

    print('Building pitcher K-stuff profile (current + historical blend)...')
    pitcher_splits_current, pitcher_usage_current = build_pitcher_k_profile(sc_current)
    pitcher_splits_prior, pitcher_usage_prior = build_pitcher_k_profile(sc_historical_pool)
    pitcher_splits, pitcher_usage = blend_pitcher_k_profiles(
        pitcher_splits_current, pitcher_usage_current,
        pitcher_splits_prior, pitcher_usage_prior,
        sc_current, sc_historical_pool
    )
    print(f'  Blended profiles for {pitcher_splits["pitcher"].nunique():,} pitchers\n')

    # ── 4. Build training table + load/train models ────────────────────────
    print('Identifying starting pitchers across historical pool...')
    starters_df = get_starting_pitchers_by_game(sc_all)

    print('Building training table (as-of-date features, no leakage)...')
    training_table = build_training_table(
        sc_all, starters_df, batter_profile, pitcher_splits, pitcher_usage
    )
    print(f'  Training table: {len(training_table):,} (pitcher, game) rows\n')

    model_cache = load_or_train_models(training_table)

    # ── 5. Today's schedule + live predictions ──────────────────────────────
    print(f"\nFetching today's ({TODAY_STR}) schedule...")
    games = get_todays_schedule(TODAY_STR)
    print(f'  {len(games)} games found')

    if not games:
        print(f'No games scheduled for {TODAY_STR}.')
        slate_df = pd.DataFrame()
    else:
        slate_df = predict_todays_slate(
            games, batter_profile, pitcher_splits, pitcher_usage, sc_all, model_cache
        )

    # ── 6. Write output JSON ─────────────────────────────────────────────────
    predictions = []
    if not slate_df.empty:
        for _, row in slate_df.sort_values('calculated_projected_ks', ascending=False).iterrows():
            predictions.append({
                'pitcher_id':               int(row['pitcher_id']),
                'pitcher_name':              row['pitcher_name'],
                'team':                      row['team'],
                'opponent':                  row['opponent'],
                'game_time':                 row['game_time'],
                'lineup_source':             row['lineup_source'],
                'lineup_posted':             bool(row['lineup_posted']),
                'calculated_projected_ks':   None if pd.isna(row['calculated_projected_ks']) else round(float(row['calculated_projected_ks']), 2),
                'knn_projected_ks':          None if pd.isna(row['knn_projected_ks']) else round(float(row['knn_projected_ks']), 2),
                'gbm_projected_ks':          None if pd.isna(row['gbm_projected_ks']) else round(float(row['gbm_projected_ks']), 2),
                'expected_tbf':              None if pd.isna(row['expected_tbf']) else round(float(row['expected_tbf']), 1),
            })

    output = {
        'updated':     datetime.utcnow().isoformat() + 'Z',
        'date':        TODAY_STR,
        'predictions': predictions,
    }
    with open(MAIN_JSON, 'w') as f:
        json.dump(output, f, indent=2)
    print(f'\n✓ Written: {MAIN_JSON}')

    # ── 7. Update + write history ────────────────────────────────────────────
    existing = next((r for r in history['records'] if r['date'] == TODAY_STR), None)
    if existing:
        existing['predictions'] = predictions
        existing['graded'] = False
    else:
        history['records'].append({
            'date': TODAY_STR,
            'predictions': predictions,
            'graded': False,
        })
    save_history(history)
    print(f'✓ Written: {HIST_JSON}')


if __name__ == '__main__':
    run()
