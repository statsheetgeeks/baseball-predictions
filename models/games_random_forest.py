"""
models/games_random_forest.py
──────────────────────────────────────────────────────────────────────────────
Standalone Random Forest Game Model — Chalk Line Labs  [v3]

CHANGES FROM v2 → v3:
  1. Probability calibration restored — Platt scaling (sigmoid) on held-out
     2024 season replaces the removed isotonic step.  Sigmoid is a smooth
     continuous transformation that spreads the compressed RF probabilities
     without collapsing them to a handful of discrete values.

  2. Starting pitcher features added at prediction time.  For each game the
     probable starter's season ERA, WHIP, and K/9 are fetched and blended
     into a post-calibration adjustment so today's pitching matchup actually
     influences the win probability.

  3. team_live_features now takes the most-recent single row (.iloc[-1])
     instead of averaging the last 15 rows.  The row already encodes all
     rolling windows (_r7, _r15, _exp, _std) — averaging them was
     double-smoothing recent form and blunting hot/cold streaks.

  4. MinMaxScaler removed.  Random Forest is invariant to monotonic feature
     transformations; the scaler added complexity without any model benefit.

  5. MODEL_VERSION added to the pickle cache key.  Bumping the string below
     automatically forces a retrain on the next run without manual file
     deletion.

Architecture:
  RandomForestClassifier(n_estimators=300, max_depth=12) trained on
  2015–2023, then Platt-scaling calibration fitted on the held-out 2024
  season.  At inference time a small starter-quality adjustment is blended
  onto the calibrated probability.

Data / caching:
  Shares the mlb_cache_v2/ game log cache with games_xgboost.py.
  New per-run pitcher cache: mlb_cache_v2/sp_{pitcher_id}_{date}.json
  Model file: mlb_cache_v2/rf_standalone_v3.pkl
──────────────────────────────────────────────────────────────────────────────
"""

import os, json, pickle, warnings, time
from datetime import date, timedelta, datetime

import numpy as np
import pandas as pd
import requests
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression

warnings.filterwarnings('ignore')
np.random.seed(42)

# ── Version / paths ───────────────────────────────────────────────────────────
MODEL_VERSION = 'v3'   # bump this string to force a retrain

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(BASE_DIR, '..', 'public', 'data')
CACHE_DIR  = os.path.join(BASE_DIR, 'mlb_cache_v2')
MAIN_JSON  = os.path.join(DATA_DIR, 'games-random-forest.json')
HIST_JSON  = os.path.join(DATA_DIR, 'games-random-forest-history.json')
MODELS_PKL = os.path.join(CACHE_DIR, 'rf_standalone_v3.pkl')

os.makedirs(DATA_DIR,  exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

# ── Season config ─────────────────────────────────────────────────────────────
CURRENT_YEAR    = date.today().year
CALIB_SEASON    = [CURRENT_YEAR - 1]                    # most recent complete season: Platt calibration
TRAIN_SEASONS   = list(range(2015, CURRENT_YEAR - 1))   # 2015–(CURRENT_YEAR-2): train RF
PREDICT_SEASONS = [CURRENT_YEAR - 1, CURRENT_YEAR] if CURRENT_YEAR > 2025 else [2025]
ALL_SEASONS     = TRAIN_SEASONS + CALIB_SEASON + [
    s for s in PREDICT_SEASONS if s not in TRAIN_SEASONS + CALIB_SEASON
]

ROLL7   = 7
ROLL15  = 15
SLEEP_S = 0.15
MLB_API = 'https://statsapi.mlb.com/api/v1'

# ── RF hyperparameters ────────────────────────────────────────────────────────
# max_depth=12 (was None) — limits tree depth to reduce variance and slightly
# spread probability outputs away from 0.5, which aids the calibration step.
RF_PARAMS = {
    'n_estimators':      300,
    'max_depth':         12,
    'min_samples_split': 10,
    'min_samples_leaf':  5,
    'max_features':      'sqrt',
    'n_jobs':            -1,
    'random_state':      42,
    'oob_score':         True,
}

# ── Starting-pitcher adjustment constants ─────────────────────────────────────
# Applied after Platt calibration.  Small cap prevents a single dominant
# starter from swinging the number more than ~6 percentage points.
LEAGUE_AVG_ERA = 4.20   # approximate MLB-wide ERA used as neutral baseline
SP_ADJ_SCALE   = 0.015  # probability shift per 1.0 ERA difference
SP_ADJ_CAP     = 0.06   # maximum total SP adjustment in either direction

# ── Confidence bands ──────────────────────────────────────────────────────────
CONFIDENCE_BANDS = [
    ('50–55%', 0.50, 0.55),
    ('55–60%', 0.55, 0.60),
    ('60–65%', 0.60, 0.65),
    ('65–70%', 0.65, 0.70),
    ('70–75%', 0.70, 0.75),
    ('75–80%', 0.75, 0.80),
    ('80%+',   0.80, 1.01),
]

# ── Team list ─────────────────────────────────────────────────────────────────
MLB_TEAMS = [
    'ARI','ATL','BAL','BOS','CHC','CHW','CIN','CLE',
    'COL','DET','HOU','KCR','LAA','LAD','MIA','MIL',
    'MIN','NYM','NYY','OAK','PHI','PIT','SDP','SEA',
    'SFG','STL','TBR','TEX','TOR','WSN',
]

# Full team-name → abbreviation lookup
NAME2ABBR = {
    'Arizona Diamondbacks': 'ARI', 'Atlanta Braves': 'ATL',
    'Baltimore Orioles': 'BAL',    'Boston Red Sox': 'BOS',
    'Chicago Cubs': 'CHC',         'Chicago White Sox': 'CHW',
    'Cincinnati Reds': 'CIN',      'Cleveland Guardians': 'CLE',
    'Colorado Rockies': 'COL',     'Detroit Tigers': 'DET',
    'Houston Astros': 'HOU',       'Kansas City Royals': 'KCR',
    'Los Angeles Angels': 'LAA',   'Los Angeles Dodgers': 'LAD',
    'Miami Marlins': 'MIA',        'Milwaukee Brewers': 'MIL',
    'Minnesota Twins': 'MIN',      'New York Mets': 'NYM',
    'New York Yankees': 'NYY',     'Oakland Athletics': 'OAK',
    'Philadelphia Phillies': 'PHI','Pittsburgh Pirates': 'PIT',
    'San Diego Padres': 'SDP',     'Seattle Mariners': 'SEA',
    'San Francisco Giants': 'SFG', 'St. Louis Cardinals': 'STL',
    'Tampa Bay Rays': 'TBR',       'Texas Rangers': 'TEX',
    'Toronto Blue Jays': 'TOR',    'Washington Nationals': 'WSN',
    'Athletics': 'OAK',
}


# ══════════════════════════════════════════════════════════════════════════════
#  UTILITY HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _safe(val):
    try:   return float(val)
    except: return np.nan

def _ip_to_float(ip_str):
    try:
        p = str(ip_str).split('.')
        return int(p[0]) + (int(p[1]) / 3 if len(p) > 1 else 0)
    except:
        return np.nan

def resolve_name(name):
    if name in NAME2ABBR:
        return NAME2ABBR[name]
    for full, abbr in NAME2ABBR.items():
        if full.split()[-1].lower() in name.lower():
            return abbr
    return None

def band_for(confidence):
    for label, lo, hi in CONFIDENCE_BANDS:
        if lo <= confidence < hi:
            return label
    return '80%+'

def get_game_time(raw):
    if not raw:
        return 'TBD'
    try:
        dt_utc = datetime.strptime(raw[:19], '%Y-%m-%dT%H:%M:%S')
        dt_et  = dt_utc - timedelta(hours=4)
        suffix = 'AM' if dt_et.hour < 12 else 'PM'
        hour   = dt_et.hour % 12 or 12
        return f'{hour}:{dt_et.minute:02d} {suffix} ET'
    except:
        return 'TBD'


# ══════════════════════════════════════════════════════════════════════════════
#  MLB API HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_team_id_map():
    cache = os.path.join(CACHE_DIR, 'team_ids.json')
    if os.path.exists(cache):
        with open(cache) as f:
            return json.load(f)
    r = requests.get(f'{MLB_API}/teams?sportId=1&season=2024', timeout=15)
    r.raise_for_status()
    mlb_map = {t['abbreviation']: t['id'] for t in r.json()['teams']}
    REMAP = {'ARI':'AZ','CHW':'CWS','KCR':'KC','SDP':'SD',
             'SFG':'SF','TBR':'TB','WSN':'WSH'}
    result = {}
    for bbr, mlb_abbr in REMAP.items():
        if mlb_abbr in mlb_map:
            result[bbr] = mlb_map[mlb_abbr]
    for abbr, tid in mlb_map.items():
        if abbr not in REMAP.values():
            result[abbr] = tid
    with open(cache, 'w') as f:
        json.dump(result, f, indent=2)
    return result


def fetch_game_log(team, year, group, team_ids):
    """Fetch (or load from cache) a team's seasonal game log."""
    is_current = (year == CURRENT_YEAR)
    path = os.path.join(CACHE_DIR, f'{team}_{year}_{group[0]}.json')

    if not is_current and os.path.exists(path):
        with open(path) as f:
            return json.load(f)

    tid = team_ids.get(team)
    if not tid:
        return []

    url = f'{MLB_API}/teams/{tid}/stats?stats=gameLog&group={group}&season={year}'
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        splits = r.json().get('stats', [])
        data   = splits[0].get('splits', []) if splits else []
    except Exception as e:
        print(f'  WARN {team} {year} {group}: {e}')
        return []

    if not is_current:
        with open(path, 'w') as f:
            json.dump(data, f)
    return data


def collect_seasons(teams, seasons, team_ids):
    """
    Pull batting and pitching game logs for all teams across all seasons.
    Returns two DataFrames: bat_raw, pit_raw.
    """
    bat_rows, pit_rows = [], []

    for team in teams:
        for year in seasons:
            # ── Batting ───────────────────────────────────────────────────────
            bat_splits = fetch_game_log(team, year, 'hitting', team_ids)
            for sp in bat_splits:
                s = sp.get('stat', {})
                opp = sp.get('opponent', {})
                is_home = sp.get('isHome', False)
                won = sp.get('isWin')
                bat_rows.append({
                    'team': team, 'season': year,
                    'date': sp.get('date', ''),
                    'is_home': int(is_home),
                    'won': int(won) if won is not None else np.nan,
                    'opp_id': opp.get('id'),
                    'B_H': s.get('hits'),      'B_R':  s.get('runs'),
                    'B_HR': s.get('homeRuns'), 'B_RBI': s.get('rbi'),
                    'B_BB': s.get('baseOnBalls'),
                    'B_SO': s.get('strikeOuts'),
                    'B_AB': s.get('atBats'),   'B_TB': s.get('totalBases'),
                    'B_AVG': _safe(s.get('avg')),
                    'B_OBP': _safe(s.get('obp')),
                    'B_SLG': _safe(s.get('slg')),
                    'B_OPS': _safe(s.get('ops')),
                    'B_LOB': s.get('leftOnBase'),
                })

            # ── Pitching ──────────────────────────────────────────────────────
            pit_splits = fetch_game_log(team, year, 'pitching', team_ids)
            for sp in pit_splits:
                s = sp.get('stat', {})
                opp = sp.get('opponent', {})
                is_home = sp.get('isHome', False)
                won = sp.get('isWin')
                pit_rows.append({
                    'team': team, 'season': year,
                    'date': sp.get('date', ''),
                    'is_home': int(is_home),
                    'won': int(won) if won is not None else np.nan,
                    'opp_id': opp.get('id'),
                    'P_IP':   _ip_to_float(s.get('inningsPitched', '0')),
                    'P_H':    s.get('hits'),   'P_SO':  s.get('strikeOuts'),
                    'P_HR':   s.get('homeRuns'),'P_R':   s.get('runs'),
                    'P_ER':   s.get('earnedRuns'),
                    'P_BB':   s.get('baseOnBalls'),
                    'P_ERA':  _safe(s.get('era')),
                    'P_WHIP': _safe(s.get('whip')),
                    'P_BF':   s.get('battersFaced'),
                    'P_GB':   s.get('groundOuts'),
                    'P_FB':   s.get('airOuts'),
                    'P_WP':   s.get('wildPitches'),
                    'P_HBP':  s.get('hitByPitch'),
                })
        print(f'  {team} ✓', end=' ', flush=True)
    print('done')
    return pd.DataFrame(bat_rows), pd.DataFrame(pit_rows)


# ══════════════════════════════════════════════════════════════════════════════
#  STARTING PITCHER FEATURES  (prediction-time only)
# ══════════════════════════════════════════════════════════════════════════════

def fetch_starter_stats(pitcher_id):
    """
    Fetch season pitching stats for a probable starter.
    Returns a dict with era, whip, k9, bb9.  Falls back to league averages
    if the pitcher has no data (e.g. injury return, TBD).
    Results are cached daily.
    """
    today_str = date.today().strftime('%Y-%m-%d')
    cache_path = os.path.join(CACHE_DIR, f'sp_{pitcher_id}_{today_str}.json')
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            return json.load(f)

    DEFAULTS = {'era': LEAGUE_AVG_ERA, 'whip': 1.30, 'k9': 8.5, 'bb9': 3.2}
    try:
        url = (f'{MLB_API}/people/{pitcher_id}/stats'
               f'?stats=season&group=pitching&season={CURRENT_YEAR}')
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        splits = r.json().get('stats', [])
        stat   = splits[0].get('splits', [{}])[0].get('stat', {}) if splits else {}
        time.sleep(SLEEP_S)

        if not stat:
            # Try previous season as fallback
            url2 = (f'{MLB_API}/people/{pitcher_id}/stats'
                    f'?stats=season&group=pitching&season={CURRENT_YEAR - 1}')
            r2   = requests.get(url2, timeout=15)
            stat = r2.json().get('stats', [{}])[0].get('splits', [{}])[0].get('stat', {})
            time.sleep(SLEEP_S)

        ip = _ip_to_float(stat.get('inningsPitched', '0'))
        if ip < 10:
            result = DEFAULTS.copy()
        else:
            so  = float(stat.get('strikeOuts', 0) or 0)
            bb  = float(stat.get('baseOnBalls', 0) or 0)
            result = {
                'era':  _safe(stat.get('era'))  or LEAGUE_AVG_ERA,
                'whip': _safe(stat.get('whip')) or 1.30,
                'k9':   (so / ip * 9) if ip > 0 else 8.5,
                'bb9':  (bb / ip * 9) if ip > 0 else 3.2,
            }
    except Exception as e:
        print(f'    WARN SP stats {pitcher_id}: {e}')
        result = DEFAULTS.copy()

    with open(cache_path, 'w') as f:
        json.dump(result, f)
    return result


def starter_prob_adjustment(home_sp_id, away_sp_id):
    """
    Compute a signed probability adjustment for the home team based on
    how each starter's ERA compares to the league average.

    Positive → home team benefits (home starter is better than away starter).
    Negative → away team benefits.

    The adjustment is capped at ±SP_ADJ_CAP to prevent a single elite
    starter from overwhelming the team-level model signal.
    """
    if home_sp_id is None and away_sp_id is None:
        return 0.0

    home_stats = fetch_starter_stats(home_sp_id) if home_sp_id else None
    away_stats = fetch_starter_stats(away_sp_id) if away_sp_id else None

    home_era = home_stats['era'] if home_stats else LEAGUE_AVG_ERA
    away_era = away_stats['era'] if away_stats else LEAGUE_AVG_ERA

    # A better home starter (lower ERA) → positive adjustment
    # A worse home starter (higher ERA) → negative adjustment
    # ERA difference relative to league avg:
    #   home is 1 run better than league avg → +SP_ADJ_SCALE
    #   away is 1 run better than league avg → -SP_ADJ_SCALE
    home_edge = (LEAGUE_AVG_ERA - home_era) * SP_ADJ_SCALE
    away_edge = (LEAGUE_AVG_ERA - away_era) * SP_ADJ_SCALE
    raw_adj   = home_edge - away_edge

    return float(np.clip(raw_adj, -SP_ADJ_CAP, SP_ADJ_CAP))


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURE ENGINEERING
# ══════════════════════════════════════════════════════════════════════════════

def engineer_team(games, stat_cols):
    """
    For each (team, season) group build lagged rolling/expanding features.
    shift(1) ensures no same-game leakage into any feature.
    """
    rows = []
    MK   = ['team', 'season', 'date', 'is_home', 'won', 'opp_id']
    for (team, season), grp in games.groupby(['team', 'season'], sort=False):
        grp   = grp.sort_values('date').reset_index(drop=True)
        stats = grp[stat_cols].apply(pd.to_numeric, errors='coerce')

        std = stats.expanding().mean().shift(1)
        exp = stats.ewm(com=19, adjust=True).mean().shift(1)
        r7  = stats.rolling(ROLL7,  min_periods=1).mean().shift(1)
        r15 = stats.rolling(ROLL15, min_periods=1).mean().shift(1)

        meta        = grp[MK].reset_index(drop=True)
        std.columns = [f'{c}_std'  for c in stat_cols]
        exp.columns = [f'{c}_exp'  for c in stat_cols]
        r7.columns  = [f'{c}_r7'   for c in stat_cols]
        r15.columns = [f'{c}_r15'  for c in stat_cols]

        combined              = pd.concat([meta, std, exp, r7, r15], axis=1)
        combined['cum_wins']  = grp['won'].cumsum().shift(1).fillna(0)
        combined['cum_games'] = np.arange(len(grp))
        combined['win_pct']   = combined['cum_wins'] / combined['cum_games'].replace(0, np.nan)
        rows.append(combined)

    return pd.concat(rows, ignore_index=True)


def add_pythag(features, stat_cols):
    for sfx in ['_std', '_exp', '_r7', '_r15']:
        rs_col = f'B_R{sfx}'
        ra_col = f'P_R{sfx}'
        if rs_col in features.columns and ra_col in features.columns:
            rs = features[rs_col]
            ra = features[ra_col]
            features[f'pythag{sfx}'] = rs ** 2 / (rs ** 2 + ra ** 2 + 1e-9)
    return features


def make_matchups(feat_df, stat_cols, eng_cols):
    home = feat_df[feat_df['is_home'] == 1].copy()
    away = feat_df[feat_df['is_home'] == 0].copy()

    h_rename = {c: f'H_{c}' for c in eng_cols if c in feat_df.columns}
    a_rename = {c: f'A_{c}' for c in eng_cols if c in feat_df.columns}
    home = home.rename(columns=h_rename)
    away = away.rename(columns=a_rename)

    home_m = home[['team', 'season', 'date', 'won', 'opp_id'] +
                  [c for c in home.columns if c.startswith('H_')]].copy()
    away_m = away[['team', 'season', 'date', 'opp_id'] +
                  [c for c in away.columns if c.startswith('A_')]].copy()
    away_m = away_m.rename(columns={'team': 'away_team', 'opp_id': 'away_opp_id'})

    merged = home_m.merge(away_m, on=['season', 'date'], how='inner')
    merged = merged[merged['team'] != merged['away_team']].copy()

    # D_ differential features — the directional signal most RF trees care about.
    # H_ and A_ features are retained so the model can learn asymmetries
    # (e.g. home ERA historically matters differently than away ERA).
    for sfx in ['_std', '_exp', '_r7', '_r15']:
        for base in stat_cols + ['pythag', 'win_pct']:
            hc = f'H_{base}{sfx}'
            ac = f'A_{base}{sfx}'
            if hc in merged.columns and ac in merged.columns:
                merged[f'D_{base}{sfx}'] = merged[hc] - merged[ac]

    wp_h  = merged.get('H_win_pct', pd.Series(0.5, index=merged.index)).fillna(0.5)
    wp_a  = merged.get('A_win_pct', pd.Series(0.5, index=merged.index)).fillna(0.5)
    denom = wp_h + wp_a - 2 * wp_h * wp_a
    merged['log5']       = np.where(denom.abs() < 1e-9, 0.5, (wp_h - wp_h * wp_a) / denom)
    merged['home_field'] = 1
    merged['season']     = merged['season'].astype(int)
    merged['label']      = merged['won'].astype(int)

    return merged.reset_index(drop=True)


def select_features(matchups):
    cands = (
        [c for c in matchups.columns if c.startswith('H_')] +
        [c for c in matchups.columns if c.startswith('A_')] +
        [c for c in matchups.columns if c.startswith('D_')] +
        ['log5', 'home_field']
    )
    return [
        c for c in cands
        if c in matchups.columns
        and pd.api.types.is_numeric_dtype(matchups[c])
        and matchups[c].nunique() > 1
    ]


# ══════════════════════════════════════════════════════════════════════════════
#  MODEL TRAINING
# ══════════════════════════════════════════════════════════════════════════════

def train_model(X_train, y_train, X_calib, y_calib):
    """
    1. Train a RandomForestClassifier on the 2015–2023 seasons.
    2. Apply Platt scaling (sigmoid calibration) on the held-out 2024 season.

    Sigmoid calibration is a smooth monotonic S-curve that spreads the
    compressed RF probabilities (which cluster around 0.50 due to vote
    averaging) into a wider, more useful range without collapsing them
    to a few discrete values — the failure mode of isotonic regression
    on a narrow input distribution.
    """
    print('  Training Random Forest (2015–2023)...')
    rf = RandomForestClassifier(**RF_PARAMS)
    rf.fit(X_train, y_train)
    print(f'  OOB score: {rf.oob_score_:.4f}')

    print('  Calibrating with Platt scaling on 2024 hold-out...')
    # Manual Platt scaling: fit a logistic regression on the raw RF probabilities
    # from the held-out calibration set.  This is exactly what
    # CalibratedClassifierCV(method='sigmoid') does internally, without
    # requiring a specific scikit-learn version.
    raw_calib = rf.predict_proba(X_calib)[:, 1].reshape(-1, 1)
    platt     = LogisticRegression(C=1.0, solver='lbfgs', max_iter=1000)
    platt.fit(raw_calib, y_calib)

    # Sanity check on calibrated output spread
    calibrated_probs = platt.predict_proba(raw_calib)[:, 1]
    print(f'  Calibrated prob range: '
          f'{calibrated_probs.min():.3f} – {calibrated_probs.max():.3f}  '
          f'std={calibrated_probs.std():.3f}')

    return rf, platt


# ══════════════════════════════════════════════════════════════════════════════
#  LIVE FEATURE VECTOR
# ══════════════════════════════════════════════════════════════════════════════

def team_live_features(team_abbr, is_home, features):
    """
    Extract the feature row for a team from the current-season feature table.

    FIX (v3): uses .iloc[-1] on the sorted frame — the single most-recent row.
    The row already encodes _r7, _r15, _exp, _std windows correctly.
    The previous approach of averaging the last 15 rows double-smoothed those
    windows and muted hot/cold-streak signals.

    Falls back to the previous season if fewer than 5 current-season games
    are available (e.g. early April).
    """
    CURR = CURRENT_YEAR
    PREV = CURRENT_YEAR - 1

    cur  = features[(features['team'] == team_abbr) & (features['season'] == CURR)]
    prev = features[(features['team'] == team_abbr) & (features['season'] == PREV)]

    if len(cur) >= 5:
        src = cur.sort_values('date').iloc[-1]
    elif len(prev) > 0:
        print(f'    {team_abbr}: {len(cur)} {CURR} games → using {PREV} fallback')
        src = prev.sort_values('date').iloc[-1]
    else:
        print(f'    No data for {team_abbr}')
        return None

    prefix   = 'H_' if is_home else 'A_'
    eng_cols = [c for c in src.index if any(
        c.endswith(s) for s in ['_std', '_exp', '_r7', '_r15']
    ) or c in ['win_pct', 'cum_wins']]

    return {f'{prefix}{c}': pd.to_numeric(src[c], errors='coerce') for c in eng_cols}


def build_matchup_vector(home_abbr, away_abbr, features, all_feat, stat_cols):
    hf = team_live_features(home_abbr, True,  features)
    af = team_live_features(away_abbr, False, features)
    if hf is None or af is None:
        return None

    row = {**hf, **af}

    # D_ differentials
    for sfx in ['_std', '_exp', '_r7', '_r15']:
        for base in stat_cols + ['pythag', 'win_pct']:
            hc = f'H_{base}{sfx}'
            ac = f'A_{base}{sfx}'
            if hc in row and ac in row:
                row[f'D_{base}{sfx}'] = row[hc] - row[ac]

    # Log5 & home field
    wp_h  = row.get('H_win_pct', 0.5) or 0.5
    wp_a  = row.get('A_win_pct', 0.5) or 0.5
    denom = wp_h + wp_a - 2 * wp_h * wp_a
    row['log5']       = (wp_h - wp_h * wp_a) / denom if abs(denom) > 1e-9 else 0.5
    row['home_field'] = 1

    vec = np.array([row.get(c, 0.0) for c in all_feat], dtype=float)
    return np.nan_to_num(vec, nan=0.0)


# ══════════════════════════════════════════════════════════════════════════════
#  SCHEDULE FETCH  (with probable pitchers)
# ══════════════════════════════════════════════════════════════════════════════

def get_today_schedule():
    """
    Fetch today's regular-season schedule including probable starters.
    Returns a list of game dicts.
    """
    today_str = date.today().strftime('%Y-%m-%d')
    url = (f'{MLB_API}/schedule?sportId=1&date={today_str}'
           f'&hydrate=probablePitcher,team&gameType=R')
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        out = []
        for entry in r.json().get('dates', []):
            for g in entry.get('games', []):
                home_sp = g['teams']['home'].get('probablePitcher')
                away_sp = g['teams']['away'].get('probablePitcher')
                out.append({
                    'away':        g['teams']['away']['team']['name'],
                    'home':        g['teams']['home']['team']['name'],
                    'game_time':   get_game_time(g.get('gameDate', '')),
                    'home_sp_id':  home_sp['id'] if home_sp else None,
                    'away_sp_id':  away_sp['id'] if away_sp else None,
                    'home_sp_name': home_sp.get('fullName', 'TBD') if home_sp else 'TBD',
                    'away_sp_name': away_sp.get('fullName', 'TBD') if away_sp else 'TBD',
                })
        return out
    except Exception as e:
        print(f'  WARN schedule: {e}')
        return []


# ══════════════════════════════════════════════════════════════════════════════
#  HISTORY / GRADING
# ══════════════════════════════════════════════════════════════════════════════

def load_history():
    if os.path.exists(HIST_JSON):
        with open(HIST_JSON) as f:
            return json.load(f)
    return {'records': []}

def save_history(history):
    with open(HIST_JSON, 'w') as f:
        json.dump(history, f, indent=2)

def grade_yesterday(history):
    yesterday = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')
    record = next((r for r in history['records'] if r['date'] == yesterday), None)
    if not record:
        return
    if all(g.get('correct') is not None for g in record['games']):
        return

    url = f'{MLB_API}/schedule?sportId=1&date={yesterday}'
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        results = [g for e in r.json().get('dates', []) for g in e.get('games', [])]
    except Exception as e:
        print(f'  WARN grading: {e}')
        return

    winner_lookup = {}
    for game in results:
        status = game.get('status', {}).get('detailedState', '')
        if status not in ('Final', 'Game Over', 'Completed Early'):
            continue
        away_score = game['teams']['away'].get('score')
        home_score = game['teams']['home'].get('score')
        if away_score is None or home_score is None:
            continue
        away_name = game['teams']['away']['team']['name']
        home_name = game['teams']['home']['team']['name']
        winner    = away_name if away_score > home_score else home_name
        winner_lookup[(away_name, home_name)] = winner

    for g in record['games']:
        actual = winner_lookup.get((g['away_team'], g['home_team']))
        if actual is not None:
            g['actual_winner'] = actual
            g['correct']       = (actual == g['pick'])

def compute_stats(games_list):
    total_w = total_l = 0
    bands = {label: [0, 0] for label, _, _ in CONFIDENCE_BANDS}
    for g in games_list:
        if g.get('correct') is None:
            continue
        w = 1 if g['correct'] else 0
        l = 0 if g['correct'] else 1
        total_w += w
        total_l += l
        bands[band_for(g['confidence'])][0] += w
        bands[band_for(g['confidence'])][1] += l
    by_conf = []
    for label, _, _ in CONFIDENCE_BANDS:
        bw, bl = bands[label]
        by_conf.append({'band': label, 'wins': bw, 'losses': bl, 'total': bw + bl})
    return {
        'total':         {'wins': total_w, 'losses': total_l, 'total': total_w + total_l},
        'by_confidence': by_conf,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def run():
    today     = date.today().strftime('%Y-%m-%d')
    team_ids  = get_team_id_map()

    # ── 1. Load or train model ─────────────────────────────────────────────────
    retrain = not os.path.exists(MODELS_PKL)
    if not retrain:
        with open(MODELS_PKL, 'rb') as f:
            cache = pickle.load(f)
        stale_year    = cache.get('trained_year') != CURRENT_YEAR
        stale_version = cache.get('model_version') != MODEL_VERSION
        if stale_year or stale_version:
            reason = 'new season' if stale_year else f'model version → {MODEL_VERSION}'
            print(f'Retraining Random Forest ({reason})...')
            retrain = True
        else:
            print('Loaded cached Random Forest model.')
            all_feat  = cache['all_feat']
            stat_cols = cache['stat_cols']
            rf        = cache['rf']
            platt     = cache['platt']

    if retrain:
        print('Collecting historical game log data...')
        bat_raw, pit_raw = collect_seasons(MLB_TEAMS, ALL_SEASONS, team_ids)

        print('Merging batting + pitching...')
        MK = ['team', 'season', 'date', 'is_home', 'won', 'opp_id']
        bat_raw['date'] = pd.to_datetime(bat_raw['date'], errors='coerce')
        pit_raw['date'] = pd.to_datetime(pit_raw['date'], errors='coerce')
        BCOLS = [c for c in bat_raw.columns if c.startswith('B_')] + MK
        PCOLS = [c for c in pit_raw.columns if c.startswith('P_')] + MK
        games = bat_raw[BCOLS].merge(pit_raw[PCOLS], on=MK, how='inner')
        games = games.dropna(subset=['won']).copy()
        games['won'] = games['won'].astype(int)
        games = games.sort_values(['team', 'season', 'date']).reset_index(drop=True)
        stat_cols = [c for c in games.columns if c.startswith('B_') or c.startswith('P_')]

        print('Engineering features...')
        features = engineer_team(games, stat_cols)
        features = add_pythag(features, stat_cols)
        eng_cols = [c for c in features.columns
                    if any(c.endswith(s) for s in ['_std', '_exp', '_r7', '_r15'])
                    or c in ['win_pct', 'cum_wins']]

        print('Building matchups...')
        matchups = make_matchups(features, stat_cols, eng_cols)
        all_feat = select_features(matchups)

        # Clean
        matchups = matchups.dropna(subset=all_feat, thresh=int(len(all_feat) * 0.7)).copy()
        for c in all_feat:
            matchups[c] = matchups[c].fillna(matchups[c].median())

        # Split: train on 2015-2023, calibrate on 2024
        # NOTE: No MinMaxScaler — RF is tree-based and scale-invariant.
        train_df = matchups[matchups['season'].isin(TRAIN_SEASONS)].copy()
        calib_df = matchups[matchups['season'].isin(CALIB_SEASON)].copy()

        X_train = train_df[all_feat].values
        y_train = train_df['label'].values
        X_calib = calib_df[all_feat].values
        y_calib = calib_df['label'].values

        print(f'  Train: {len(X_train):,} rows | Calibration: {len(X_calib):,} rows')
        rf, platt = train_model(X_train, y_train, X_calib, y_calib)

        with open(MODELS_PKL, 'wb') as f:
            pickle.dump({
                'model_version': MODEL_VERSION,
                'trained_year':  CURRENT_YEAR,
                'all_feat':      all_feat,
                'stat_cols':     stat_cols,
                'rf':            rf,
                'platt':         platt,
            }, f)
        print('✓ Random Forest model trained and cached.')

    # ── 2. Current-season live features ───────────────────────────────────────
    print('Fetching current season data...')
    bat_raw, pit_raw = collect_seasons(MLB_TEAMS, PREDICT_SEASONS, team_ids)

    MK = ['team', 'season', 'date', 'is_home', 'won', 'opp_id']
    bat_raw['date'] = pd.to_datetime(bat_raw['date'], errors='coerce')
    pit_raw['date'] = pd.to_datetime(pit_raw['date'], errors='coerce')
    BCOLS = [c for c in bat_raw.columns if c.startswith('B_')] + MK
    PCOLS = [c for c in pit_raw.columns if c.startswith('P_')] + MK
    live_games = bat_raw[BCOLS].merge(pit_raw[PCOLS], on=MK, how='inner')
    live_games = live_games.dropna(subset=['won']).copy()
    live_games = live_games.sort_values(['team', 'season', 'date']).reset_index(drop=True)

    live_features = engineer_team(live_games, stat_cols)
    live_features = add_pythag(live_features, stat_cols)

    # ── 3. Today's predictions ─────────────────────────────────────────────────
    print("Fetching today's schedule...")
    schedule    = get_today_schedule()
    today_preds = []

    for g in schedule:
        ha = resolve_name(g['home'])
        aa = resolve_name(g['away'])
        if not ha or not aa:
            print(f'  SKIP (unresolved): {g["home"]} vs {g["away"]}')
            continue

        vec = build_matchup_vector(ha, aa, live_features, all_feat, stat_cols)
        if vec is None:
            continue

        # Two-step prediction: raw RF → Platt calibration
        raw_prob      = rf.predict_proba(vec.reshape(1, -1))[0, 1]
        home_prob_raw = float(platt.predict_proba([[raw_prob]])[0, 1])

        # Starting pitcher adjustment (post-calibration blend)
        sp_adj    = starter_prob_adjustment(g.get('home_sp_id'), g.get('away_sp_id'))
        home_prob = float(np.clip(home_prob_raw + sp_adj, 0.35, 0.80))
        away_prob = 1.0 - home_prob

        pick       = g['home'] if home_prob >= 0.5 else g['away']
        confidence = max(home_prob, away_prob)

        today_preds.append({
            'game_time':     g['game_time'],
            'away_team':     g['away'],
            'home_team':     g['home'],
            'away_sp':       g.get('away_sp_name', 'TBD'),
            'home_sp':       g.get('home_sp_name', 'TBD'),
            'away_prob':     round(away_prob, 4),
            'home_prob':     round(home_prob, 4),
            'pick':          pick,
            'confidence':    round(confidence, 4),
            'actual_winner': None,
            'correct':       None,
        })

    print(f'  → {len(today_preds)} predictions generated')

    # ── 4. History & grading ──────────────────────────────────────────────────
    print("Grading yesterday's picks...")
    history = load_history()
    grade_yesterday(history)

    existing = next((r for r in history['records'] if r['date'] == today), None)
    if existing:
        existing['games'] = today_preds
    else:
        history['records'].append({'date': today, 'games': today_preds})

    history['records'].sort(key=lambda r: r['date'], reverse=True)
    save_history(history)

    # ── 5. Compute stats & write main JSON ────────────────────────────────────
    yesterday_str = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')
    yest_record   = next((r for r in history['records'] if r['date'] == yesterday_str), None)
    yest_stats    = compute_stats(yest_record['games']) if yest_record else None

    all_graded = [g for r in history['records'] for g in r['games']
                  if g.get('correct') is not None]
    alltime_stats = compute_stats(all_graded)

    output = {
        'date':        today,
        'updated':     datetime.utcnow().isoformat() + 'Z',
        'predictions': today_preds,
        'yesterday':   {**(yest_stats or {}), 'date': yesterday_str},
        'alltime':     alltime_stats,
    }
    with open(MAIN_JSON, 'w') as f:
        json.dump(output, f, indent=2)

    print(f'✓ Wrote {MAIN_JSON}')
    return output


if __name__ == '__main__':
    run()
