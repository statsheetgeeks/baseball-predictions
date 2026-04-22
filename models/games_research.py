"""
models/games_research.py
──────────────────────────────────────────────────────────────────────────────
Research-Based Stacked Ensemble — Chalk Line Labs
Extending Allen & Savala (2025)

Architecture:
  Base models  : Logistic Regression + XGBoost + MLP Neural Network
  Meta-learner : Logistic Regression on stacked base probabilities
  Calibration  : Isotonic regression → calibrated win probabilities

Season splits (no overlap):
  2015–2020  Train base models (out-of-fold)
  2021–2022  Train meta-learner
  2023–2024  Hold-out test set
  2025–curr  Live predictions

Caching:
  models/mlb_cache_v2/
    {TEAM}_{YEAR}_{h|p}.json   ← raw game log per team/season/group
                                  Historical seasons are permanently cached
                                  and committed to git. Current season is
                                  always re-fetched fresh.
    models_v2.pkl              ← all trained models + scaler + feature list
                                  Only rebuilt if missing or season changes.
──────────────────────────────────────────────────────────────────────────────
"""

import os, json, pickle, warnings
from datetime import date, timedelta, timezone, datetime

import numpy as np
import pandas as pd
import requests
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import MinMaxScaler
from sklearn.isotonic import IsotonicRegression
from xgboost import XGBClassifier

warnings.filterwarnings('ignore')
np.random.seed(42)

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(BASE_DIR, '..', 'public', 'data')
CACHE_DIR  = os.path.join(BASE_DIR, 'mlb_cache_v2')
MAIN_JSON  = os.path.join(DATA_DIR, 'games-research.json')
HIST_JSON  = os.path.join(DATA_DIR, 'games-research-history.json')
MODELS_PKL = os.path.join(CACHE_DIR, 'models_v2.pkl')

os.makedirs(DATA_DIR,  exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

# ── Season config ─────────────────────────────────────────────────────────────
CURRENT_YEAR       = date.today().year
BASE_TRAIN_SEASONS = list(range(2015, 2021))   # 2015–2020
META_TRAIN_SEASONS = [2021, 2022]
TEST_SEASONS       = [2023, 2024]
PREDICT_SEASONS    = [2025, CURRENT_YEAR] if CURRENT_YEAR > 2025 else [2025]
ALL_SEASONS        = BASE_TRAIN_SEASONS + META_TRAIN_SEASONS + TEST_SEASONS + PREDICT_SEASONS

MLB_API = 'https://statsapi.mlb.com/api/v1'

ROLL7  = 7
ROLL15 = 15

MLB_TEAMS = [
    'ARI','ATL','BAL','BOS','CHC','CHW','CIN','CLE',
    'COL','DET','HOU','KCR','LAA','LAD','MIA','MIL',
    'MIN','NYM','NYY','OAK','PHI','PIT','SDP','SEA',
    'SFG','STL','TBR','TEX','TOR','WSN',
]

NAME2ABBR = {
    'Arizona Diamondbacks':   'ARI', 'Atlanta Braves':        'ATL',
    'Baltimore Orioles':      'BAL', 'Boston Red Sox':        'BOS',
    'Chicago Cubs':           'CHC', 'Chicago White Sox':     'CHW',
    'Cincinnati Reds':        'CIN', 'Cleveland Guardians':   'CLE',
    'Colorado Rockies':       'COL', 'Detroit Tigers':        'DET',
    'Houston Astros':         'HOU', 'Kansas City Royals':    'KCR',
    'Los Angeles Angels':     'LAA', 'Los Angeles Dodgers':   'LAD',
    'Miami Marlins':          'MIA', 'Milwaukee Brewers':     'MIL',
    'Minnesota Twins':        'MIN', 'New York Mets':         'NYM',
    'New York Yankees':       'NYY', 'Oakland Athletics':     'OAK',
    'Philadelphia Phillies':  'PHI', 'Pittsburgh Pirates':    'PIT',
    'San Diego Padres':       'SDP', 'Seattle Mariners':      'SEA',
    'San Francisco Giants':   'SFG', 'St. Louis Cardinals':   'STL',
    'Tampa Bay Rays':         'TBR', 'Texas Rangers':         'TEX',
    'Toronto Blue Jays':      'TOR', 'Washington Nationals':  'WSN',
    # Aliases
    'Athletics':              'OAK', 'Sacramento Athletics':  'OAK',
    'Guardians':              'CLE',
}

XGB_PARAMS = {
    'n_estimators':    400,
    'max_depth':       4,
    'learning_rate':   0.05,
    'subsample':       0.8,
    'colsample_bytree':0.8,
    'eval_metric':     'logloss',
    'random_state':    42,
    'verbosity':       0,
    'tree_method':     'hist',
}

CONFIDENCE_BANDS = [
    ('50-59%', 0.50, 0.60),
    ('60-69%', 0.60, 0.70),
    ('70-79%', 0.70, 0.80),
    ('80%+',   0.80, 1.01),
]

# ── Helpers ───────────────────────────────────────────────────────────────────
def _safe(v):
    try:    return float(str(v).replace('-.--', 'nan'))
    except: return np.nan

def _ip(v):
    try:
        p = str(v).split('.')
        return int(p[0]) + (int(p[1]) / 3 if len(p) > 1 else 0)
    except: return np.nan

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
        return f"{hour}:{dt_et.minute:02d} {suffix} ET"
    except Exception:
        return 'TBD'

# ── Team ID map ───────────────────────────────────────────────────────────────
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

# ── Game log fetch (with caching) ─────────────────────────────────────────────
def fetch_game_log(team, year, group, team_ids):
    """
    Fetch per-game stats for one team/season/group.
    Historical seasons are permanently cached. Current season is always
    re-fetched so today's rolling stats are accurate.
    """
    is_current = (year == CURRENT_YEAR)
    path = os.path.join(CACHE_DIR, f'{team}_{year}_{group[0]}.json')

    # Use cache for historical seasons
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
        splits = r.json().get('stats', [{}])[0].get('splits', [])
        # Only write cache for historical (complete) seasons
        if not is_current:
            with open(path, 'w') as f:
                json.dump(splits, f)
        return splits
    except Exception as e:
        print(f'  WARN: {team} {year} {group}: {e}')
        return []

# ── Data collection ───────────────────────────────────────────────────────────
def collect_seasons(teams, seasons, team_ids):
    bat_rows, pit_rows = [], []
    for yr in seasons:
        print(f'  Collecting {yr}...', end=' ', flush=True)
        for tm in teams:
            for sp in fetch_game_log(tm, yr, 'hitting', team_ids):
                s = sp.get('stat', {})
                bat_rows.append({
                    'team': tm, 'season': yr,
                    'date': sp.get('date'),
                    'is_home': int(sp.get('isHome', False)),
                    'won':     int(sp.get('isWin', False)),
                    'opp_id':  sp.get('opponent', {}).get('id'),
                    'B_AB':  s.get('atBats'),       'B_H':   s.get('hits'),
                    'B_BB':  s.get('baseOnBalls'),  'B_SO':  s.get('strikeOuts'),
                    'B_PA':  s.get('plateAppearances'),
                    'B_AVG': _safe(s.get('avg')),   'B_OBP': _safe(s.get('obp')),
                    'B_SLG': _safe(s.get('slg')),   'B_OPS': _safe(s.get('ops')),
                    'B_HR':  s.get('homeRuns'),     'B_RBI': s.get('rbi'),
                    'B_R':   s.get('runs'),         'B_LOB': s.get('leftOnBase'),
                    'B_TB':  s.get('totalBases'),   'B_SB':  s.get('stolenBases'),
                })
            for sp in fetch_game_log(tm, yr, 'pitching', team_ids):
                s = sp.get('stat', {})
                pit_rows.append({
                    'team': tm, 'season': yr,
                    'date': sp.get('date'),
                    'is_home': int(sp.get('isHome', False)),
                    'won':     int(sp.get('isWin', False)),
                    'opp_id':  sp.get('opponent', {}).get('id'),
                    'P_IP':   _ip(s.get('inningsPitched', 0)),
                    'P_H':    s.get('hits'),         'P_BB':  s.get('baseOnBalls'),
                    'P_SO':   s.get('strikeOuts'),   'P_HR':  s.get('homeRuns'),
                    'P_ERA':  _safe(s.get('era')),   'P_WHIP':_safe(s.get('whip')),
                    'P_BF':   s.get('battersFaced'), 'P_R':   s.get('runs'),
                    'P_ER':   s.get('earnedRuns'),   'P_GB':  s.get('groundOuts'),
                    'P_FB':   s.get('airOuts'),      'P_WP':  s.get('wildPitches'),
                    'P_HBP':  s.get('hitByPitch'),
                })
        print('done')
    return pd.DataFrame(bat_rows), pd.DataFrame(pit_rows)

# ── Feature engineering ───────────────────────────────────────────────────────
def engineer_team(games, stat_cols):
    """
    Compute 4 feature variants per stat (std, exp, r7, r15) for each team/season.
    Uses shift(1) throughout — zero data leakage.

    exp variant uses pandas ewm() with com=19 (equivalent to lambda=0.95 decay
    per game), replacing the original O(n²) Python loop with a vectorized call.
    """
    rows = []
    MK = ['team', 'season', 'date', 'is_home', 'won', 'opp_id']
    for (team, season), grp in games.groupby(['team', 'season'], sort=False):
        grp   = grp.sort_values('date').reset_index(drop=True)
        stats = grp[stat_cols].apply(pd.to_numeric, errors='coerce')

        # Season-to-date cumulative mean (shift 1 = only past games)
        std = stats.expanding().mean().shift(1)

        # Exponentially-decayed weighted mean — vectorized, same as lambda=0.95
        # com=19 gives decay factor 1/(1+1/19) ≈ 0.95 per game
        exp = stats.ewm(com=19, adjust=True).mean().shift(1)

        # Rolling windows
        r7  = stats.rolling(ROLL7,  min_periods=1).mean().shift(1)
        r15 = stats.rolling(ROLL15, min_periods=1).mean().shift(1)

        meta = grp[MK].reset_index(drop=True)
        std.columns = [f'{c}_std'  for c in stat_cols]
        exp.columns = [f'{c}_exp'  for c in stat_cols]
        r7.columns  = [f'{c}_r7'   for c in stat_cols]
        r15.columns = [f'{c}_r15'  for c in stat_cols]

        combined = pd.concat([meta, std, exp, r7, r15], axis=1)
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
            features[f'pythag{sfx}'] = rs**2 / (rs**2 + ra**2 + 1e-9)
    return features

def make_matchups(feat_df, stat_cols, eng_cols):
    """Pair home and away features into one row per game."""
    home = feat_df[feat_df['is_home'] == 1].copy()
    away = feat_df[feat_df['is_home'] == 0].copy()

    h_rename = {c: f'H_{c}' for c in eng_cols if c in feat_df.columns}
    a_rename = {c: f'A_{c}' for c in eng_cols if c in feat_df.columns}
    home = home.rename(columns=h_rename)
    away = away.rename(columns=a_rename)

    home_m = home[['team','season','date','won','opp_id'] +
                  [c for c in home.columns if c.startswith('H_')]].copy()
    away_m = away[['team','season','date','opp_id'] +
                  [c for c in away.columns if c.startswith('A_')]].copy()
    away_m = away_m.rename(columns={'team':'away_team', 'opp_id':'away_opp_id'})

    merged = home_m.merge(away_m, on=['season','date'], how='inner')
    merged = merged[merged['team'] != merged['away_team']].copy()

    # Pairwise differentials
    for sfx in ['_std', '_exp', '_r7', '_r15']:
        for base in stat_cols + ['pythag', 'win_pct']:
            hc = f'H_{base}{sfx}'
            ac = f'A_{base}{sfx}'
            if hc in merged.columns and ac in merged.columns:
                merged[f'D_{base}{sfx}'] = merged[hc] - merged[ac]

    # Log5
    wp_h  = merged.get('H_win_pct', pd.Series(0.5, index=merged.index)).fillna(0.5)
    wp_a  = merged.get('A_win_pct', pd.Series(0.5, index=merged.index)).fillna(0.5)
    denom = wp_h + wp_a - 2 * wp_h * wp_a
    merged['log5']      = np.where(denom.abs() < 1e-9, 0.5, (wp_h - wp_h * wp_a) / denom)
    merged['home_field'] = 1
    merged['season']     = merged['season'].astype(int)
    merged['label']      = merged['won'].astype(int)

    return merged.reset_index(drop=True)

def select_features(matchups):
    H_COLS  = [c for c in matchups.columns if c.startswith('H_')]
    A_COLS  = [c for c in matchups.columns if c.startswith('A_')]
    D_COLS  = [c for c in matchups.columns if c.startswith('D_')]
    CTX     = ['log5', 'home_field']
    cands   = H_COLS + A_COLS + D_COLS + CTX
    return [
        c for c in cands
        if c in matchups.columns
        and pd.api.types.is_numeric_dtype(matchups[c])
        and matchups[c].nunique() > 1
    ]

# ── Model training ────────────────────────────────────────────────────────────
def train_models(X_base, y_base, X_meta, y_meta):
    print('  Training Logistic Regression...')
    logr = LogisticRegression(max_iter=1000, C=1.0, solver='saga',
                              random_state=42, n_jobs=-1)
    logr.fit(X_base, y_base)

    print('  Training XGBoost...')
    xgb = XGBClassifier(**XGB_PARAMS)
    xgb.fit(X_base, y_base)

    print('  Training MLP...')
    mlp = MLPClassifier(
        hidden_layer_sizes=(128, 64, 32),
        activation='relu',
        solver='adam',
        max_iter=300,
        early_stopping=True,
        validation_fraction=0.1,
        random_state=42,
    )
    mlp.fit(X_base, y_base)

    print('  Training meta-learner...')
    p_logr = logr.predict_proba(X_meta)[:, 1]
    p_xgb  = xgb.predict_proba(X_meta)[:, 1]
    p_mlp  = mlp.predict_proba(X_meta)[:, 1]
    X_meta_stacked = np.column_stack([p_logr, p_xgb, p_mlp])
    meta = LogisticRegression(max_iter=500, C=1.0, solver='saga',
                              random_state=42, n_jobs=1)
    meta.fit(X_meta_stacked, y_meta)

    print('  Fitting isotonic calibrator...')
    raw_meta = meta.predict_proba(X_meta_stacked)[:, 1]
    calibrator = IsotonicRegression(out_of_bounds='clip')
    calibrator.fit(raw_meta, y_meta)

    return logr, xgb, mlp, meta, calibrator

def predict_pipeline(X_scaled, models):
    logr, xgb, mlp, meta, calibrator = models
    p_logr = logr.predict_proba(X_scaled)[:, 1]
    p_xgb  = xgb.predict_proba(X_scaled)[:, 1]
    p_mlp  = mlp.predict_proba(X_scaled)[:, 1]
    stacked = np.column_stack([p_logr, p_xgb, p_mlp])
    raw     = meta.predict_proba(stacked)[:, 1]
    cal     = calibrator.predict(raw)
    return cal, p_logr, p_xgb, p_mlp

# ── Live feature vector for today's games ─────────────────────────────────────
def team_live_features(team_abbr, is_home, features, window=15):
    CURR = CURRENT_YEAR
    PREV = CURRENT_YEAR - 1

    cur  = features[(features['team'] == team_abbr) & (features['season'] == CURR)]
    prev = features[(features['team'] == team_abbr) & (features['season'] == PREV)]

    if len(cur) >= 5:
        src = cur.sort_values('date').tail(window)
    elif len(prev) > 0:
        print(f'    {team_abbr}: {len(cur)} {CURR} games → using {PREV} fallback')
        src = prev.sort_values('date').tail(window)
    else:
        print(f'    No data for {team_abbr}')
        return None

    prefix = 'H_' if is_home else 'A_'
    row = {}
    eng_cols = [c for c in src.columns if any(
        c.endswith(s) for s in ['_std', '_exp', '_r7', '_r15']
    ) or c in ['win_pct', 'cum_wins']]

    for c in eng_cols:
        if c in src.columns:
            row[f'{prefix}{c}'] = pd.to_numeric(src[c], errors='coerce').mean()

    return row

def build_matchup_vector(home_abbr, away_abbr, features, all_feat, stat_cols):
    hf = team_live_features(home_abbr, True,  features)
    af = team_live_features(away_abbr, False, features)
    if hf is None or af is None:
        return None

    row = {**hf, **af}

    # Differentials
    for sfx in ['_std', '_exp', '_r7', '_r15']:
        for base in stat_cols + ['pythag', 'win_pct']:
            hc = f'H_{base}{sfx}'
            ac = f'A_{base}{sfx}'
            if hc in row and ac in row:
                row[f'D_{base}{sfx}'] = row[hc] - row[ac]

    # Log5
    wp_h  = row.get('H_win_pct', 0.5) or 0.5
    wp_a  = row.get('A_win_pct', 0.5) or 0.5
    denom = wp_h + wp_a - 2 * wp_h * wp_a
    row['log5']      = (wp_h - wp_h * wp_a) / denom if abs(denom) > 1e-9 else 0.5
    row['home_field'] = 1

    vec = np.array([row.get(c, 0.0) for c in all_feat], dtype=float)
    return np.nan_to_num(vec, nan=0.0)

# ── Schedule fetch ────────────────────────────────────────────────────────────
def get_today_schedule():
    today = date.today().strftime('%Y-%m-%d')
    url   = f'{MLB_API}/schedule?sportId=1&date={today}&hydrate=team'
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        out = []
        for entry in r.json().get('dates', []):
            for g in entry.get('games', []):
                out.append({
                    'away':     g['teams']['away']['team']['name'],
                    'home':     g['teams']['home']['team']['name'],
                    'game_time': get_game_time(g.get('gameDate', '')),
                })
        return out
    except Exception as e:
        print(f'  WARN schedule: {e}')
        return []

# ── History & results (mirrors games_log5.py) ─────────────────────────────────
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

    yday_api = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')
    url = f'{MLB_API}/schedule?sportId=1&date={yday_api}'
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        results = []
        for entry in r.json().get('dates', []):
            results.extend(entry.get('games', []))
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
        winner = away_name if away_score > home_score else home_name
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
        b = band_for(g['confidence'])
        bands[b][0] += w
        bands[b][1] += l
    by_conf = []
    for label, _, _ in CONFIDENCE_BANDS:
        bw, bl = bands[label]
        by_conf.append({'band': label, 'wins': bw, 'losses': bl, 'total': bw + bl})
    return {
        'total': {'wins': total_w, 'losses': total_l, 'total': total_w + total_l},
        'by_confidence': by_conf,
    }

# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    today     = date.today().strftime('%Y-%m-%d')
    yesterday = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')

    # ── 1. Load or train models ───────────────────────────────────────────────
    team_ids = get_team_id_map()   # cached after first fetch
    retrain = not os.path.exists(MODELS_PKL)
    if not retrain:
        with open(MODELS_PKL, 'rb') as f:
            cache = pickle.load(f)
        if cache.get('trained_year') != CURRENT_YEAR:
            print('New season detected — retraining models...')
            retrain = True
        else:
            print('Loaded cached models.')
            scaler     = cache['scaler']
            all_feat   = cache['all_feat']
            stat_cols  = cache['stat_cols']
            eng_cols   = cache['eng_cols']
            models     = (cache['logr'], cache['xgb'], cache['mlp'],
                          cache['meta'], cache['calibrator'])

    if retrain:
        print('Collecting game log data...')
        bat_raw, pit_raw = collect_seasons(MLB_TEAMS, ALL_SEASONS, team_ids)

        print('Merging batting + pitching...')
        MK = ['team','season','date','is_home','won','opp_id']
        bat_raw['date'] = pd.to_datetime(bat_raw['date'], errors='coerce')
        pit_raw['date'] = pd.to_datetime(pit_raw['date'], errors='coerce')
        BCOLS = [c for c in bat_raw.columns if c.startswith('B_')] + MK
        PCOLS = [c for c in pit_raw.columns if c.startswith('P_')] + MK
        games = bat_raw[BCOLS].merge(pit_raw[PCOLS], on=MK, how='inner')
        games = games.dropna(subset=['won']).copy()
        games['won'] = games['won'].astype(int)
        games = games.sort_values(['team','season','date']).reset_index(drop=True)
        stat_cols = [c for c in games.columns if c.startswith('B_') or c.startswith('P_')]

        print('Engineering features...')
        features = engineer_team(games, stat_cols)
        features = add_pythag(features, stat_cols)
        eng_cols = [c for c in features.columns
                    if any(c.endswith(s) for s in ['_std','_exp','_r7','_r15'])
                    or c in ['win_pct','cum_wins']]

        print('Building matchups...')
        matchups = make_matchups(features, stat_cols, eng_cols)
        all_feat = select_features(matchups)

        # Clean
        matchups_clean = matchups.dropna(
            subset=all_feat, thresh=int(len(all_feat) * 0.7)
        ).copy()
        for c in all_feat:
            matchups_clean[c] = matchups_clean[c].fillna(matchups_clean[c].median())

        # Season splits
        base_df = matchups_clean[matchups_clean['season'].isin(BASE_TRAIN_SEASONS)]
        meta_df = matchups_clean[matchups_clean['season'].isin(META_TRAIN_SEASONS)]

        # Scale
        scaler  = MinMaxScaler()
        X_base  = scaler.fit_transform(base_df[all_feat].values)
        y_base  = base_df['label'].values
        X_meta  = scaler.transform(meta_df[all_feat].values)
        y_meta  = meta_df['label'].values

        print('Training models...')
        logr, xgb, mlp, meta_model, calibrator = train_models(X_base, y_base, X_meta, y_meta)
        models = (logr, xgb, mlp, meta_model, calibrator)

        # Cache everything
        with open(MODELS_PKL, 'wb') as f:
            pickle.dump({
                'trained_year': CURRENT_YEAR,
                'scaler':       scaler,
                'all_feat':     all_feat,
                'stat_cols':    stat_cols,
                'eng_cols':     eng_cols,
                'logr':         logr,
                'xgb':          xgb,
                'mlp':          mlp,
                'meta':         meta_model,
                'calibrator':   calibrator,
            }, f)
        print('✓ Models trained and cached.')

    # ── 2. Build live features for today ─────────────────────────────────────
    # Re-fetch current season data (always fresh)
    print('Fetching current season data...')
    bat_raw, pit_raw = collect_seasons(MLB_TEAMS, PREDICT_SEASONS, team_ids)

    MK = ['team','season','date','is_home','won','opp_id']
    bat_raw['date'] = pd.to_datetime(bat_raw['date'], errors='coerce')
    pit_raw['date'] = pd.to_datetime(pit_raw['date'], errors='coerce')
    BCOLS = [c for c in bat_raw.columns if c.startswith('B_')] + MK
    PCOLS = [c for c in pit_raw.columns if c.startswith('P_')] + MK
    live_games = bat_raw[BCOLS].merge(pit_raw[PCOLS], on=MK, how='inner')
    live_games = live_games.dropna(subset=['won']).copy()
    live_games = live_games.sort_values(['team','season','date']).reset_index(drop=True)

    live_features = engineer_team(live_games, stat_cols)
    live_features = add_pythag(live_features, stat_cols)

    # ── 3. Today's schedule & predictions ────────────────────────────────────
    print('Fetching today\'s schedule...')
    schedule = get_today_schedule()
    print(f'  → {len(schedule)} games today')

    logr, xgb, mlp, meta_model, calibrator = models
    today_preds = []

    for g in schedule:
        ha = resolve_name(g['home'])
        aa = resolve_name(g['away'])
        if not ha or not aa:
            print(f'  SKIP (unresolved): {g}')
            continue

        vec = build_matchup_vector(ha, aa, live_features, all_feat, stat_cols)
        if vec is None:
            continue

        vec_sc = scaler.transform(vec.reshape(1, -1))
        cal, p_logr, p_xgb, p_mlp = predict_pipeline(vec_sc, models)

        home_prob = float(cal[0])
        away_prob = 1.0 - home_prob
        pick      = g['home'] if home_prob >= 0.5 else g['away']
        confidence = max(home_prob, away_prob)

        today_preds.append({
            'game_time':      g['game_time'],
            'away_team':      g['away'],
            'home_team':      g['home'],
            'away_prob':      round(away_prob, 4),
            'home_prob':      round(home_prob, 4),
            'base_logr_home': round(float(p_logr[0]), 4),
            'base_xgb_home':  round(float(p_xgb[0]), 4),
            'base_mlp_home':  round(float(p_mlp[0]), 4),
            'pick':           pick,
            'confidence':     round(confidence, 4),
            'actual_winner':  None,
            'correct':        None,
        })

    # ── 4. History & grading ──────────────────────────────────────────────────
    print('Grading yesterday\'s picks...')
    history = load_history()
    grade_yesterday(history)

    existing = next((r for r in history['records'] if r['date'] == today), None)
    if existing:
        existing['games'] = today_preds
    else:
        history['records'].append({'date': today, 'games': today_preds})

    history['records'].sort(key=lambda r: r['date'], reverse=True)
    save_history(history)

    # ── 5. Stats ──────────────────────────────────────────────────────────────
    all_graded = [
        g for r in history['records']
        for g in r['games']
        if r['date'] != today and g.get('correct') is not None
    ]
    alltime_stats = compute_stats(all_graded)

    yday_record = next((r for r in history['records'] if r['date'] == yesterday), None)
    yday_stats  = compute_stats(yday_record['games'] if yday_record else [])

    # ── 6. Write output JSON ──────────────────────────────────────────────────
    output = {
        'updated':     datetime.now(timezone.utc).isoformat(),
        'date':        today,
        'predictions': today_preds,
        'yesterday':   {'date': yesterday, **yday_stats},
        'alltime':     alltime_stats,
    }
    with open(MAIN_JSON, 'w') as f:
        json.dump(output, f, indent=2)

    print(f'✓ Wrote {len(today_preds)} predictions → games-research.json')
    print(f'  All-time: {alltime_stats["total"]["wins"]}-{alltime_stats["total"]["losses"]}')

if __name__ == '__main__':
    run()
