"""
models/hitters_ml_hit.py
──────────────────────────────────────────────────────────────────────────────
Chalk Line Labs — ML Hit Probability Model  (v2)

Originally based on Alceo & Henriques (2020):
  "Beat the Streak: Prediction of MLB Base Hits Using Machine Learning"

v2 improvements over the original:
  • XGBoost replaces MLP as the primary classifier. scale_pos_weight handles
    class imbalance natively — random under-sampling (which discarded ~70% of
    training data) is eliminated entirely.
  • Statcast features added — batter xBA, xwOBA, exit velocity, hard-hit%,
    K%, BB%; pitcher xBA-allowed, hard-hit%-allowed, K%-allowed.
    Sourced from Baseball Savant expected-stats leaderboard CSV (same pipeline
    already used by hitters_ml_hr.py).
  • Platoon splits — bat_L, bat_R, sp_throws_L, platoon_adv. Handedness
    is fetched once from the MLB People endpoint and cached indefinitely.
  • Park hit factors — per-stadium 5-year hit-rate multiplier (1.00 = avg).

FEATURES (~40 total, dynamically determined at training time):
  Batter short-term  : roll7  BA, OBP, SLG, OPS, H/g, BB/g, SO/g, HR/g
  Batter long-term   : roll30 BA, OBP, SLG, OPS, H/g, BB/g, SO/g, HR/g
  Batter Statcast    : sc_xba, sc_xwoba, sc_exit_velo, sc_hard_hit_pct,
                       sc_k_pct, sc_bb_pct  (NaN-imputed when missing)
  Opposing pitcher   : P_era, P_whip, P_so, P_bb, P_h, P_hr, P_bf, P_ip
  Pitcher Statcast   : sp_sc_xba, sp_sc_hard_hit_pct, sp_sc_k_pct
  Context            : is_home, batting_order (default 5 pre-lineup)
  Handedness         : bat_L, bat_R, sp_throws_L, platoon_adv
  Park               : park_hit_factor

OUTPUT FIELDS (unchanged for frontend compatibility):
  p_mlp → now filled by XGBoost (primary sort key)
  p_lr  → Logistic Regression (class_weight='balanced')
  p_rf  → Random Forest       (class_weight='balanced')
  p_ens → simple average of all three

QUALIFICATION:
  Batter must have ≥ 50 plate appearances in the current season
  (falls back to prior season early in the year).

SP FALLBACK:
  When no starter is announced, defaults to league-average pitcher
  stats (ERA 4.50, WHIP 1.30, all counts 0, Statcast NaN).

CACHING:
  hit_pred_cache/
    schedule_{year}.json          all completed game PKs for a season
    box_{gamePk}.json             parsed box score (cached forever)
    records_{year}.pkl            assembled batter-game rows per season
    player_{id}_{today}_hitting.json   daily refresh
    player_{id}_{year}_pitching.json   yearly refresh
    roster_{teamId}_{today}.json       daily refresh
    statcast_batter_{year}.pkl    Savant expected-stats (cached forever)
    statcast_pitcher_{year}.pkl   Savant expected-stats (cached forever)
    player_hands.json             bat side + pitch hand (grows over time)

  models/mlb_cache_v2/
    ml_hit_models_v2.pkl          XGBoost + LR + RF + imputer + scaler +
                                  fitted_features list; rebuilt when missing
                                  or new season detected.

OUTPUTS:
  public/data/hitters-ml-hit.json
  public/data/hitters-ml-hit-history.json
──────────────────────────────────────────────────────────────────────────────
"""

import io
import os
import json
import pickle
import time
import warnings
from datetime import date, timedelta, timezone, datetime

import numpy as np
import pandas as pd
import requests
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import MinMaxScaler
from xgboost import XGBClassifier

warnings.filterwarnings('ignore')
np.random.seed(42)

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(BASE_DIR, '..', 'public', 'data')
CACHE_DIR  = os.path.join(BASE_DIR, '..', 'hit_pred_cache')
MODEL_DIR  = os.path.join(BASE_DIR, 'mlb_cache_v2')
MAIN_JSON  = os.path.join(DATA_DIR,  'hitters-ml-hit.json')
HIST_JSON  = os.path.join(DATA_DIR,  'hitters-ml-hit-history.json')
MODELS_PKL = os.path.join(MODEL_DIR, 'ml_hit_models_v2.pkl')   # v2 — forces retrain
HAND_FILE  = os.path.join(CACHE_DIR, 'player_hands.json')

for d in [DATA_DIR, CACHE_DIR, MODEL_DIR]:
    os.makedirs(d, exist_ok=True)

# ── Config ────────────────────────────────────────────────────────────────────
MLB_API       = 'https://statsapi.mlb.com/api/v1'
SAVANT_BASE   = 'https://baseballsavant.mlb.com'
CURRENT_YEAR  = date.today().year
TRAIN_SEASONS = [2022, 2023, 2024]
TEST_SEASON   = 2025
TOP_N         = 25
MIN_PA        = 50
ROLL_SHORT    = 7
ROLL_LONG     = 30
SLEEP_S       = 0.05

TODAY = date.today().strftime('%Y-%m-%d')

# ── Feature groups ────────────────────────────────────────────────────────────
BATTER_ROLL_FEATURES = [
    'roll7_BA',   'roll7_OBP',  'roll7_SLG',  'roll7_OPS',
    'roll7_B_h',  'roll7_B_bb', 'roll7_B_so', 'roll7_B_hr',
    'roll30_BA',  'roll30_OBP', 'roll30_SLG', 'roll30_OPS',
    'roll30_B_h', 'roll30_B_bb','roll30_B_so','roll30_B_hr',
]
PITCHER_COUNTING_FEATURES = ['P_era','P_whip','P_so','P_bb','P_h','P_hr','P_bf','P_ip']
CONTEXT_FEATURES          = ['is_home', 'batting_order']
HANDEDNESS_FEATURES       = ['bat_L', 'bat_R', 'sp_throws_L', 'platoon_adv']
PARK_FEATURES             = ['park_hit_factor']

# Statcast column names (after renaming from Savant CSV)
STATCAST_BATTER_COLS  = ['sc_xba', 'sc_xwoba', 'sc_exit_velo',
                          'sc_hard_hit_pct', 'sc_k_pct', 'sc_bb_pct']
STATCAST_PITCHER_COLS = ['sp_sc_xba', 'sp_sc_hard_hit_pct', 'sp_sc_k_pct']

# Base features always present (used as a floor; Statcast cols added dynamically)
BASE_FEATURES = (BATTER_ROLL_FEATURES + PITCHER_COUNTING_FEATURES +
                 CONTEXT_FEATURES + HANDEDNESS_FEATURES + PARK_FEATURES)

# ── Park hit factors (Baseball Reference 5-yr multi-year, normalized to 1.00) ─
PARK_HIT_FACTORS = {
    'Colorado Rockies'       : 1.12,
    'Boston Red Sox'         : 1.07,
    'Texas Rangers'          : 1.06,
    'Chicago Cubs'           : 1.04,
    'Cincinnati Reds'        : 1.04,
    'Milwaukee Brewers'      : 1.03,
    'Baltimore Orioles'      : 1.02,
    'Philadelphia Phillies'  : 1.02,
    'Toronto Blue Jays'      : 1.01,
    'Houston Astros'         : 1.00,
    'New York Yankees'       : 1.00,
    'Detroit Tigers'         : 0.99,
    'Arizona Diamondbacks'   : 0.99,
    'Los Angeles Angels'     : 0.99,
    'Minnesota Twins'        : 0.98,
    'Atlanta Braves'         : 0.98,
    'St. Louis Cardinals'    : 0.98,
    'Cleveland Guardians'    : 0.98,
    'Kansas City Royals'     : 0.97,
    'Pittsburgh Pirates'     : 0.97,
    'Washington Nationals'   : 0.97,
    'Oakland Athletics'      : 0.97,
    'Athletics'              : 0.97,
    'Seattle Mariners'       : 0.97,
    'Chicago White Sox'      : 0.96,
    'San Francisco Giants'   : 0.96,
    'Tampa Bay Rays'         : 0.96,
    'Los Angeles Dodgers'    : 0.96,
    'New York Mets'          : 0.95,
    'Miami Marlins'          : 0.95,
    'San Diego Padres'       : 0.94,
}

DEFAULT_SP = {
    'P_era': 4.50, 'P_whip': 1.30, 'P_so': 0, 'P_bb': 0,
    'P_h': 0, 'P_hr': 0, 'P_bf': 1, 'P_ip': 0.0,
}


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _to_float(val):
    try:
        return float(str(val).replace('-.--', 'nan').replace('--', 'nan'))
    except:
        return np.nan

def _to_int(val):
    try:    return int(val)
    except: return 0

def _get(url, timeout=20):
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


# ═══════════════════════════════════════════════════════════════════════════════
#  DATA COLLECTION
# ═══════════════════════════════════════════════════════════════════════════════

def get_season_game_pks(season):
    """All completed regular-season game PKs for a season (cached forever)."""
    cache = os.path.join(CACHE_DIR, f'schedule_{season}.json')
    if os.path.exists(cache):
        with open(cache) as f:
            return json.load(f)
    print(f'  Fetching {season} schedule...')
    url = (f'{MLB_API}/schedule?sportId=1&season={season}'
           f'&gameType=R&fields=dates,date,games,gamePk,status,codedGameState')
    pks = []
    for d in _get(url).get('dates', []):
        for g in d.get('games', []):
            if g.get('status', {}).get('codedGameState') == 'F':
                pks.append(g['gamePk'])
    with open(cache, 'w') as f:
        json.dump(pks, f)
    print(f'    {season}: {len(pks)} completed games')
    return pks


def parse_boxscore(game_pk, season):
    """
    Parse one box score into batter-level records.
    Returns list of dicts. Result is cached per game_pk forever.

    v2 additions: sp_id (for Statcast pitcher join), home_team_name (for park factor).
    """
    cache = os.path.join(CACHE_DIR, f'box_{game_pk}.json')
    if os.path.exists(cache):
        with open(cache) as f:
            data = json.load(f)
    else:
        try:
            data = _get(f'{MLB_API}/game/{game_pk}/boxscore')
        except Exception as e:
            return []
        with open(cache, 'w') as f:
            json.dump(data, f)
        time.sleep(SLEEP_S)

    records = []
    teams_data = data.get('teams', {})
    home_team_name = teams_data.get('home', {}).get('team', {}).get('name', 'Unknown')

    for side in ['away', 'home']:
        opp_side = 'home' if side == 'away' else 'away'
        is_home  = 1 if side == 'home' else 0

        team_obj  = teams_data.get(side, {})
        opp_obj   = teams_data.get(opp_side, {})
        team_name = team_obj.get('team', {}).get('name', 'Unknown')
        opp_name  = opp_obj.get('team', {}).get('name', 'Unknown')

        # ── Opposing starter stats ────────────────────────────────────────────
        opp_pitchers = opp_obj.get('pitchers', [])
        opp_players  = opp_obj.get('players', {})
        starter_stats = {'sp_id': None}
        starter_stats.update(DEFAULT_SP)

        if opp_pitchers:
            sp_pid  = opp_pitchers[0]
            sp_key  = f'ID{sp_pid}'
            sp_stat = opp_players.get(sp_key, {}).get('stats', {}).get('pitching', {})
            ip_str  = str(sp_stat.get('inningsPitched', '0.0'))
            try:
                parts  = ip_str.split('.')
                ip_val = float(parts[0]) + float(parts[1] if len(parts) > 1 else 0) / 3
            except:
                ip_val = 0.0
            er  = _to_int(sp_stat.get('earnedRuns', 0))
            bb  = _to_int(sp_stat.get('baseOnBalls', 0))
            h   = _to_int(sp_stat.get('hits', 0))
            ip  = max(ip_val, 0.1)
            starter_stats = {
                'sp_id' : sp_pid,
                'P_ip'  : ip_val,
                'P_h'   : h,
                'P_er'  : er,
                'P_bb'  : bb,
                'P_so'  : _to_int(sp_stat.get('strikeOuts', 0)),
                'P_hr'  : _to_int(sp_stat.get('homeRuns', 0)),
                'P_era' : _to_float(sp_stat.get('era',  er * 9 / ip)),
                'P_whip': _to_float(sp_stat.get('whip', (bb + h) / ip)),
                'P_bf'  : _to_int(sp_stat.get('battersFaced', 0)),
            }

        # ── Batter records ────────────────────────────────────────────────────
        batters       = team_obj.get('batters', [])
        players       = team_obj.get('players', {})
        batting_order = team_obj.get('battingOrder', [])
        order_pos     = {pid: i + 1 for i, pid in enumerate(batting_order)}

        for pid in batters:
            key    = f'ID{pid}'
            bstats = players.get(key, {}).get('stats', {}).get('batting', {})
            pa = _to_int(bstats.get('plateAppearances', 0))
            if pa == 0:
                continue
            ab = _to_int(bstats.get('atBats', 0))
            h  = _to_int(bstats.get('hits', 0))
            bb = _to_int(bstats.get('baseOnBalls', 0))
            so = _to_int(bstats.get('strikeOuts', 0))
            hr = _to_int(bstats.get('homeRuns', 0))
            tb = _to_int(bstats.get('totalBases', 0))
            rec = {
                'game_pk'       : game_pk,
                'season'        : season,
                'player_id'     : pid,
                'player_name'   : players.get(key, {}).get('person', {}).get('fullName', ''),
                'team'          : team_name,
                'opponent'      : opp_name,
                'home_team_name': home_team_name,
                'is_home'       : is_home,
                'batting_order' : order_pos.get(pid, 9),
                'B_pa': pa, 'B_ab': ab, 'B_h': h, 'B_bb': bb,
                'B_so': so, 'B_hr': hr, 'B_tb': tb,
                'B_ba' : h / ab if ab > 0 else 0.0,
                'B_obp': (h + bb) / pa if pa > 0 else 0.0,
                'B_slg': tb / ab if ab > 0 else 0.0,
                'hit'  : 1 if h > 0 else 0,
            }
            rec.update(starter_stats)
            records.append(rec)

    return records


def collect_season(season):
    """Load or fetch all batter-game records for one season (cached)."""
    cache_pkl = os.path.join(CACHE_DIR, f'records_{season}.pkl')
    if os.path.exists(cache_pkl):
        df = pd.read_pickle(cache_pkl)
        print(f'  {season}: loaded {len(df):,} records from cache')
        return df
    print(f'  {season}: fetching box scores...')
    pks  = get_season_game_pks(season)
    rows = []
    for i, pk in enumerate(pks):
        rows.extend(parse_boxscore(pk, season))
        if (i + 1) % 100 == 0:
            print(f'    {i+1}/{len(pks)} games processed...')
    df = pd.DataFrame(rows)
    df.to_pickle(cache_pkl)
    print(f'  {season}: saved {len(df):,} records')
    return df


# ═══════════════════════════════════════════════════════════════════════════════
#  STATCAST  (Baseball Savant expected-stats leaderboard CSV)
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_statcast_csv(year, player_type='batter'):
    """
    Download Baseball Savant expected-stats leaderboard CSV for batters or
    pitchers. Returns a DataFrame indexed by player_id. Cached forever.
    Column naming mirrors hitters_ml_hr.py so both models share the convention.
    """
    cache = os.path.join(CACHE_DIR, f'statcast_{player_type}_{year}.pkl')
    if os.path.exists(cache):
        return pd.read_pickle(cache)

    url = (f'{SAVANT_BASE}/leaderboard/expected_statistics'
           f'?type={player_type}&year={year}&position=&team=&min=25&csv=true')
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
    except Exception as e:
        print(f'  WARN Statcast {player_type} {year}: {e}')
        return pd.DataFrame()

    df.columns = [c.strip().lower() for c in df.columns]

    # Normalise the player ID column name across Savant CSV variants
    for id_col in ['player_id', 'playerid', 'mlbam_id']:
        if id_col in df.columns:
            df = df.rename(columns={id_col: 'player_id'})
            break
    if 'player_id' not in df.columns:
        return pd.DataFrame()
    df['player_id'] = pd.to_numeric(df['player_id'], errors='coerce')

    # Rename Savant columns to internal names
    col_map = {
        'xba'              : 'sc_xba',
        'xwoba'            : 'sc_xwoba',
        'exit_velocity_avg': 'sc_exit_velo',
        'avg_hit_speed'    : 'sc_exit_velo',
        'hard_hit_percent' : 'sc_hard_hit_pct',
        'k_percent'        : 'sc_k_pct',
        'bb_percent'       : 'sc_bb_pct',
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    # Pitcher columns get the sp_sc_ prefix so they don't clash with batter cols
    if player_type == 'pitcher':
        df = df.rename(columns={c: c.replace('sc_', 'sp_sc_', 1)
                                 for c in df.columns if c.startswith('sc_')})

    keep = ['player_id'] + [c for c in df.columns
                            if c.startswith('sc_') or c.startswith('sp_sc_')]
    df = (df[[c for c in keep if c in df.columns]]
            .drop_duplicates('player_id')
            .set_index('player_id'))
    df.to_pickle(cache)
    print(f'  Statcast {player_type} {year}: {len(df):,} players')
    return df


# ═══════════════════════════════════════════════════════════════════════════════
#  HANDEDNESS
# ═══════════════════════════════════════════════════════════════════════════════

def load_hand_cache():
    if os.path.exists(HAND_FILE):
        with open(HAND_FILE) as f:
            return json.load(f)
    return {}

def save_hand_cache(cache):
    with open(HAND_FILE, 'w') as f:
        json.dump(cache, f)

def get_player_hand(player_id, hand_cache):
    """Fetch bat side and pitch hand for a player; cache indefinitely."""
    key = str(player_id)
    if key in hand_cache:
        return hand_cache[key]
    try:
        p    = _get(f'{MLB_API}/people/{player_id}').get('people', [{}])[0]
        info = {
            'bat_side'  : p.get('batSide',   {}).get('code', 'R'),
            'pitch_hand': p.get('pitchHand', {}).get('code', 'R'),
        }
        hand_cache[key] = info
        time.sleep(0.03)
        return info
    except:
        return {'bat_side': 'R', 'pitch_hand': 'R'}


# ═══════════════════════════════════════════════════════════════════════════════
#  FEATURE ENGINEERING
# ═══════════════════════════════════════════════════════════════════════════════

def build_rolling_features(df):
    """
    Compute lagged rolling averages for each batter across their game history.
    shift(1) ensures no data leakage (current game excluded from its own features).
    """
    df = df.sort_values(['player_id', 'game_pk']).copy()
    grp = df.groupby('player_id')

    for col in ['B_h','B_ab','B_bb','B_so','B_hr','B_pa','B_tb']:
        df[f'roll7_{col}']  = grp[col].transform(
            lambda s: s.shift(1).rolling(ROLL_SHORT, min_periods=2).mean())
        df[f'roll30_{col}'] = grp[col].transform(
            lambda s: s.shift(1).rolling(ROLL_LONG,  min_periods=5).mean())

    df['roll7_BA']   = df['roll7_B_h']  / df['roll7_B_ab'].replace(0, np.nan)
    df['roll7_OBP']  = (df['roll7_B_h'] + df['roll7_B_bb']) / df['roll7_B_pa'].replace(0, np.nan)
    df['roll7_SLG']  = df['roll7_B_tb'] / df['roll7_B_ab'].replace(0, np.nan)
    df['roll7_OPS']  = df['roll7_OBP']  + df['roll7_SLG']

    df['roll30_BA']  = df['roll30_B_h']  / df['roll30_B_ab'].replace(0, np.nan)
    df['roll30_OBP'] = (df['roll30_B_h'] + df['roll30_B_bb']) / df['roll30_B_pa'].replace(0, np.nan)
    df['roll30_SLG'] = df['roll30_B_tb'] / df['roll30_B_ab'].replace(0, np.nan)
    df['roll30_OPS'] = df['roll30_OBP']  + df['roll30_SLG']

    return df


# ═══════════════════════════════════════════════════════════════════════════════
#  MODEL TRAINING  (v2 — XGBoost primary, LR + RF secondary)
# ═══════════════════════════════════════════════════════════════════════════════

def train_models(model_df, fitted_features):
    """
    Train XGBoost (primary), Logistic Regression, and Random Forest on
    TRAIN_SEASONS data. Evaluates on TEST_SEASON hold-out.

    v2 changes vs v1:
      • XGBoost replaces MLP. scale_pos_weight=neg/pos handles imbalance.
      • LR and RF use class_weight='balanced' — no undersampling needed.
      • MinMaxScaler retained only for LR (XGBoost is scale-invariant).
      • All training data is used (no rows discarded).
    """
    train_mask = model_df['season'].isin(TRAIN_SEASONS)
    test_mask  = model_df['season'] == TEST_SEASON

    X_train_raw = model_df.loc[train_mask, fitted_features].values.astype(float)
    y_train     = model_df.loc[train_mask, 'hit'].values
    X_test_raw  = model_df.loc[test_mask,  fitted_features].values.astype(float)
    y_test      = model_df.loc[test_mask,  'hit'].values

    n_pos  = y_train.sum()
    n_neg  = len(y_train) - n_pos
    spw    = round(n_neg / max(n_pos, 1), 2)
    print(f'  Train: {len(X_train_raw):,} samples  |  '
          f'hits: {n_pos:,} ({n_pos/len(y_train)*100:.1f}%)  |  '
          f'scale_pos_weight: {spw}')
    print(f'  Test:  {len(X_test_raw):,} samples')

    # Impute missing values (Statcast NaNs for players without Savant data)
    imputer      = SimpleImputer(strategy='median')
    X_train_imp  = imputer.fit_transform(X_train_raw)
    X_test_imp   = imputer.transform(X_test_raw)

    # Scale for LR (XGBoost and RF don't require it but scaling won't hurt RF)
    scaler        = MinMaxScaler()
    X_train_sc    = scaler.fit_transform(X_train_imp)
    X_test_sc     = scaler.transform(X_test_imp)

    print('  Training XGBoost (primary)...')
    xgb = XGBClassifier(
        n_estimators      = 400,
        max_depth         = 5,
        learning_rate     = 0.05,
        subsample         = 0.8,
        colsample_bytree  = 0.8,
        scale_pos_weight  = spw,       # handles class imbalance
        eval_metric       = 'logloss',
        use_label_encoder = False,
        random_state      = 42,
        n_jobs            = -1,
    )
    xgb.fit(
        X_train_imp, y_train,
        eval_set=[(X_test_imp, y_test)],
        verbose=False,
    )

    print('  Training Logistic Regression...')
    lr = LogisticRegression(
        C=1.0, max_iter=1000, solver='lbfgs',
        class_weight='balanced', random_state=42,
    )
    lr.fit(X_train_sc, y_train)

    print('  Training Random Forest...')
    rf = RandomForestClassifier(
        n_estimators    = 300,
        max_depth       = 10,
        min_samples_leaf= 20,
        class_weight    = 'balanced',
        random_state    = 42,
        n_jobs          = -1,
    )
    rf.fit(X_train_imp, y_train)

    # Quick evaluation on hold-out
    for name, model, X_t in [
        ('XGBoost', xgb, X_test_imp),
        ('LR',      lr,  X_test_sc),
        ('RF',      rf,  X_test_imp),
    ]:
        acc = (model.predict(X_t) == y_test).mean()
        print(f'  {name} test accuracy: {acc:.4f}')

    return xgb, lr, rf, imputer, scaler


def load_or_train_models(model_df, fitted_features):
    """Load cached v2 models if they exist and match the current season; else retrain."""
    if os.path.exists(MODELS_PKL):
        with open(MODELS_PKL, 'rb') as f:
            cache = pickle.load(f)
        if cache.get('trained_year') == CURRENT_YEAR:
            print('  Loaded cached ML models (v2).')
            return (cache['xgb'], cache['lr'], cache['rf'],
                    cache['imputer'], cache['scaler'], cache['fitted_features'])
        else:
            print(f'  New season detected ({CURRENT_YEAR}) — retraining...')

    print('  Training models (first run this season)...')
    xgb, lr, rf, imputer, scaler = train_models(model_df, fitted_features)

    with open(MODELS_PKL, 'wb') as f:
        pickle.dump({
            'trained_year'  : CURRENT_YEAR,
            'xgb'           : xgb,
            'lr'            : lr,
            'rf'            : rf,
            'imputer'       : imputer,
            'scaler'        : scaler,
            'fitted_features': fitted_features,
        }, f)
    print('  ✓ Models trained and cached.')
    return xgb, lr, rf, imputer, scaler, fitted_features


# ═══════════════════════════════════════════════════════════════════════════════
#  TODAY'S DATA
# ═══════════════════════════════════════════════════════════════════════════════

def get_todays_games():
    """Fetch today's schedule with probable starters and team IDs."""
    url = (f'{MLB_API}/schedule?sportId=1&date={TODAY}'
           f'&hydrate=probablePitcher,team&gameType=R')
    games = []
    for entry in _get(url).get('dates', []):
        for g in entry.get('games', []):
            info = {
                'game_pk'        : g['gamePk'],
                'game_date'      : g.get('gameDate', ''),
                'away_team'      : g['teams']['away']['team']['name'],
                'home_team'      : g['teams']['home']['team']['name'],
                'away_team_id'   : g['teams']['away']['team']['id'],
                'home_team_id'   : g['teams']['home']['team']['id'],
                'away_team_abbr' : g['teams']['away']['team'].get('abbreviation', '?'),
                'home_team_abbr' : g['teams']['home']['team'].get('abbreviation', '?'),
                'away_sp'        : None,
                'home_sp'        : None,
            }
            for side in ['away', 'home']:
                sp = g['teams'][side].get('probablePitcher')
                if sp:
                    info[f'{side}_sp'] = {
                        'id'  : sp['id'],
                        'name': sp.get('fullName', 'TBD'),
                    }
            games.append(info)
    return games


def get_game_time_et(game_date_str):
    if not game_date_str:
        return 'TBD'
    try:
        dt_utc = datetime.strptime(game_date_str[:16], '%Y-%m-%dT%H:%M')
        dt_et  = dt_utc - timedelta(hours=4)
        hour   = dt_et.hour % 12 or 12
        ampm   = 'AM' if dt_et.hour < 12 else 'PM'
        return f'{hour}:{dt_et.minute:02d} {ampm} ET'
    except:
        return 'TBD'


def get_active_roster(team_id):
    """Active non-pitcher roster, cached daily."""
    cache = os.path.join(CACHE_DIR, f'roster_{team_id}_{TODAY}.json')
    if os.path.exists(cache):
        with open(cache) as f:
            return json.load(f)
    try:
        url     = f'{MLB_API}/teams/{team_id}/roster?rosterType=active&season={CURRENT_YEAR}'
        players = []
        for p in _get(url).get('roster', []):
            pos = p.get('position', {}).get('abbreviation', 'UNK')
            if pos not in ('P', 'SP', 'RP', 'TWP'):
                players.append({
                    'id'      : p['person']['id'],
                    'name'    : p['person']['fullName'],
                    'position': pos,
                })
        with open(cache, 'w') as f:
            json.dump(players, f)
        return players
    except Exception as e:
        print(f'    WARN roster {team_id}: {e}')
        return []


def get_player_season_stats(player_id, season, group='hitting'):
    """Season-to-date stats. Hitting cached daily; pitching cached yearly."""
    suffix = TODAY if group == 'hitting' else season
    cache  = os.path.join(CACHE_DIR, f'player_{player_id}_{suffix}_{group}.json')
    if os.path.exists(cache):
        with open(cache) as f:
            return json.load(f)
    try:
        url    = (f'{MLB_API}/people/{player_id}/stats'
                  f'?stats=season&group={group}&season={season}')
        splits = _get(url).get('stats', [])
        data   = splits[0].get('splits', [{}])[0].get('stat', {}) if splits else {}
        with open(cache, 'w') as f:
            json.dump(data, f)
        time.sleep(SLEEP_S)
        return data
    except:
        return {}


def get_pitcher_features(pitcher_id, sc_pit):
    """
    Build pitcher feature dict from season-to-date counting stats + Statcast.
    sc_pit: dict of {year: DataFrame} from fetch_statcast_csv('pitcher').
    """
    s = get_player_season_stats(pitcher_id, CURRENT_YEAR, 'pitching')
    if not s:
        s = get_player_season_stats(pitcher_id, CURRENT_YEAR - 1, 'pitching')
    if not s:
        return DEFAULT_SP.copy()

    ip_str = str(s.get('inningsPitched', '0.0'))
    try:
        parts  = ip_str.split('.')
        ip_val = float(parts[0]) + float(parts[1] if len(parts) > 1 else 0) / 3
    except:
        ip_val = 0.1

    bf   = max(_to_int(s.get('battersFaced', 1)), 1)
    ip   = max(ip_val, 0.1)
    so   = _to_int(s.get('strikeOuts', 0))
    bb   = _to_int(s.get('baseOnBalls', 0))
    h    = _to_int(s.get('hits', 0))
    hr   = _to_int(s.get('homeRuns', 0))
    er   = _to_int(s.get('earnedRuns', 0))
    era  = _to_float(s.get('era',  er * 9 / ip))
    whip = _to_float(s.get('whip', (bb + h) / ip))

    feats = {
        'P_era' : era  if era  == era  else 4.50,
        'P_whip': whip if whip == whip else 1.30,
        'P_so': so, 'P_bb': bb, 'P_h': h,
        'P_hr': hr, 'P_bf': bf, 'P_ip': ip_val,
    }

    # Statcast pitcher: try current year then fall back one year
    for yr in [CURRENT_YEAR, CURRENT_YEAR - 1]:
        pit_sc = sc_pit.get(yr, pd.DataFrame())
        if not pit_sc.empty and pitcher_id in pit_sc.index:
            for col in pit_sc.columns:
                feats[col] = float(pit_sc.loc[pitcher_id, col])
            break

    return feats


def build_batter_features(player_id, model_df):
    """
    Build rolling feature dict for a batter from historical model_df.
    Falls back to API season stats if fewer than 5 historical games.
    Returns None if batter is unqualified (< MIN_PA).
    """
    player_games = model_df[
        (model_df['player_id'] == player_id) &
        (model_df['season'].isin([CURRENT_YEAR, CURRENT_YEAR - 1]))
    ].sort_values('game_pk')

    if len(player_games) >= 5:
        def _roll(df, n):
            tail = df.tail(n)
            ab = tail['B_ab'].sum(); pa = tail['B_pa'].sum()
            h  = tail['B_h'].sum();  bb = tail['B_bb'].sum()
            so = tail['B_so'].sum(); hr = tail['B_hr'].sum()
            tb = tail['B_tb'].sum(); ng = len(tail)
            ab = max(ab, 1); pa = max(pa, 1)
            return {
                'BA' : h / ab,          'OBP': (h + bb) / pa,
                'SLG': tb / ab,         'OPS': (h + bb) / pa + tb / ab,
                'h'  : h / ng,          'bb' : bb / ng,
                'so' : so / ng,         'hr' : hr / ng,
            }
        r7  = _roll(player_games, ROLL_SHORT)
        r30 = _roll(player_games, ROLL_LONG)
        return {
            'roll7_BA'   : r7['BA'],   'roll7_OBP' : r7['OBP'],
            'roll7_SLG'  : r7['SLG'],  'roll7_OPS' : r7['OPS'],
            'roll7_B_h'  : r7['h'],    'roll7_B_bb': r7['bb'],
            'roll7_B_so' : r7['so'],   'roll7_B_hr': r7['hr'],
            'roll30_BA'  : r30['BA'],  'roll30_OBP': r30['OBP'],
            'roll30_SLG' : r30['SLG'], 'roll30_OPS': r30['OPS'],
            'roll30_B_h' : r30['h'],   'roll30_B_bb':r30['bb'],
            'roll30_B_so': r30['so'],  'roll30_B_hr':r30['hr'],
        }

    # API fallback — use season totals when box score history is thin
    s  = get_player_season_stats(player_id, CURRENT_YEAR, 'hitting')
    pa = _to_int(s.get('plateAppearances', 0))
    if pa < MIN_PA:
        s  = get_player_season_stats(player_id, CURRENT_YEAR - 1, 'hitting')
        pa = _to_int(s.get('plateAppearances', 0))
        if pa < MIN_PA:
            return None

    ab  = max(_to_int(s.get('atBats', 1)), 1)
    pa  = max(pa, 1)
    h   = _to_int(s.get('hits', 0))
    bb  = _to_int(s.get('baseOnBalls', 0))
    so  = _to_int(s.get('strikeOuts', 0))
    hr  = _to_int(s.get('homeRuns', 0))
    tb  = _to_int(s.get('totalBases', 0))
    gp  = max(_to_int(s.get('gamesPlayed', 1)), 1)
    ba  = h / ab;      obp = (h + bb) / pa
    slg = tb / ab;     ops = obp + slg
    return {
        'roll7_BA'   : ba,    'roll7_OBP' : obp,   'roll7_SLG' : slg,   'roll7_OPS' : ops,
        'roll7_B_h'  : h/gp,  'roll7_B_bb': bb/gp, 'roll7_B_so': so/gp, 'roll7_B_hr': hr/gp,
        'roll30_BA'  : ba,    'roll30_OBP': obp,   'roll30_SLG': slg,   'roll30_OPS': ops,
        'roll30_B_h' : h/gp,  'roll30_B_bb':bb/gp,'roll30_B_so': so/gp,'roll30_B_hr': hr/gp,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  HISTORY AND AUTO-GRADING
# ═══════════════════════════════════════════════════════════════════════════════

def load_history():
    if os.path.exists(HIST_JSON):
        try:
            with open(HIST_JSON) as f:
                return json.load(f)
        except:
            pass
    return {'records': []}

def save_history(hist):
    with open(HIST_JSON, 'w') as f:
        json.dump(hist, f, indent=2)

def grade_yesterday(history, yesterday_str):
    record = next((r for r in history['records'] if r['date'] == yesterday_str), None)
    if not record or record.get('graded'):
        return

    print(f'  Grading picks for {yesterday_str}...')
    try:
        sched_meta = requests.get(
            f'{MLB_API}/schedule',
            params={'sportId': 1, 'date': yesterday_str},
            timeout=20,
        ).json()
    except Exception as e:
        print(f'    WARN fetching schedule: {e}')
        return

    hit_lookup = {}
    for d in sched_meta.get('dates', []):
        for g in d.get('games', []):
            pk = g.get('gamePk')
            if not pk:
                continue
            try:
                box = _get(f'{MLB_API}/game/{pk}/boxscore')
                for side in ['away', 'home']:
                    for pid, pdata in box.get('teams', {}).get(side, {}).get('players', {}).items():
                        h = _to_int(pdata.get('stats', {}).get('batting', {}).get('hits', 0))
                        name = pdata.get('person', {}).get('fullName', '')
                        if name:
                            hit_lookup[name] = hit_lookup.get(name, 0) + h
            except Exception as e:
                print(f'    WARN box score pk={pk}: {e}')
                continue

    for pred in record.get('predictions', []):
        hits = hit_lookup.get(pred.get('player', ''), 0)
        pred['actual_hits'] = hits
        pred['correct']     = hits > 0

    record['graded'] = True

    played  = [p for p in record['predictions'] if p.get('actual_hits') is not None]
    hit     = [p for p in played if p['correct']]
    buckets = {'75%+': [], '65-74%': [], '55-64%': [], '<55%': []}
    for p in played:
        prob = p.get('p_mlp', 0)  # p_mlp is now XGBoost probability
        b    = '75%+' if prob >= 0.75 else '65-74%' if prob >= 0.65 else '55-64%' if prob >= 0.55 else '<55%'
        buckets[b].append(p['correct'])
    record['summary'] = {
        'total'       : len(played),
        'hit_count'   : len(hit),
        'hit_rate_pct': round(len(hit) / max(len(played), 1) * 100, 1),
        'hit_players' : [p['player'] for p in hit],
        'by_bucket'   : {
            k: {'predicted': len(v), 'hits': sum(v),
                'rate_pct': round(sum(v) / max(len(v), 1) * 100, 1)}
            for k, v in buckets.items() if v
        },
    }
    save_history(history)
    print(f'    ✓ {len(hit)}/{len(played)} got a hit')


def compute_alltime_stats(history, today_str):
    buckets  = {'75%+': [0,0], '65-74%': [0,0], '55-64%': [0,0], '<55%': [0,0]}
    total    = hit_total = 0
    for rec in history['records']:
        if rec['date'] == today_str or not rec.get('graded'):
            continue
        for p in rec.get('predictions', []):
            if p.get('actual_hits') is None:
                continue
            h = 1 if p['correct'] else 0
            total += 1; hit_total += h
            prob = p.get('p_mlp', 0)
            b    = '75%+' if prob >= 0.75 else '65-74%' if prob >= 0.65 else '55-64%' if prob >= 0.55 else '<55%'
            buckets[b][0] += 1; buckets[b][1] += h
    return {
        'total'       : total,
        'hit_count'   : hit_total,
        'hit_rate_pct': round(hit_total / max(total, 1) * 100, 1),
        'by_bucket'   : {
            k: {'predicted': buckets[k][0], 'hits': buckets[k][1],
                'rate_pct': round(buckets[k][1] / max(buckets[k][0], 1) * 100, 1)}
            for k in buckets if buckets[k][0] > 0
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

def run():
    today_str     = date.today().isoformat()
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()

    print(f'\n══ ML Hit Model v2 — {today_str} ══')
    print(f'   Train: {TRAIN_SEASONS}  |  Test: {TEST_SEASON}  |  MIN_PA: {MIN_PA}')

    # ── 1. Load history and grade yesterday ───────────────────────────────────
    history = load_history()
    grade_yesterday(history, yesterday_str)

    # ── 2. Load box score data ─────────────────────────────────────────────────
    print('\nLoading historical box scores...')
    all_dfs = []
    for season in TRAIN_SEASONS + [TEST_SEASON]:
        all_dfs.append(collect_season(season))
    raw_df = pd.concat(all_dfs, ignore_index=True)

    # ── 3. Statcast CSVs ──────────────────────────────────────────────────────
    print('\nFetching Statcast CSVs...')
    sc_bat = {}
    sc_pit = {}
    for yr in TRAIN_SEASONS + [TEST_SEASON]:
        sc_bat[yr] = fetch_statcast_csv(yr, 'batter')
        sc_pit[yr] = fetch_statcast_csv(yr, 'pitcher')

    # ── 4. Handedness ─────────────────────────────────────────────────────────
    print('\nLoading handedness cache...')
    hand_cache  = load_hand_cache()
    all_pids    = raw_df['player_id'].dropna().astype(int).unique().tolist()
    sp_ids      = raw_df['sp_id'].dropna().astype(int).unique().tolist() \
                  if 'sp_id' in raw_df.columns else []
    missing_ids = [p for p in set(all_pids + sp_ids) if str(p) not in hand_cache]
    print(f'  Fetching handedness for {len(missing_ids)} new players...')
    for i, pid in enumerate(missing_ids):
        get_player_hand(pid, hand_cache)
        if (i + 1) % 100 == 0:
            save_hand_cache(hand_cache)
            print(f'    Handedness: {i+1}/{len(missing_ids)} fetched...')
    save_hand_cache(hand_cache)

    # ── 5. Build rolling features ─────────────────────────────────────────────
    print('\nEngineering features...')
    model_df = build_rolling_features(raw_df)
    model_df = model_df.dropna(subset=BATTER_ROLL_FEATURES).copy()

    # Handedness: batter bat side
    model_df['bat_side'] = model_df['player_id'].apply(
        lambda pid: hand_cache.get(str(int(pid)), {}).get('bat_side', 'R')
    )
    model_df['bat_L'] = (model_df['bat_side'] == 'L').astype(int)
    model_df['bat_R'] = (model_df['bat_side'] == 'R').astype(int)

    # Handedness: SP pitch hand + platoon advantage
    if 'sp_id' in model_df.columns:
        model_df['sp_hand'] = model_df['sp_id'].apply(
            lambda pid: hand_cache.get(str(int(pid)), {}).get('pitch_hand', 'R')
            if pd.notna(pid) else 'R'
        )
        model_df['sp_throws_L'] = (model_df['sp_hand'] == 'L').astype(int)
        model_df['platoon_adv'] = (
            (model_df['bat_side'] != model_df['sp_hand']) &
            (model_df['bat_side'] != 'S')
        ).astype(int)
    else:
        model_df['sp_throws_L'] = 0
        model_df['platoon_adv'] = 0

    # Park hit factor
    model_df['park_hit_factor'] = model_df['home_team_name'].map(
        lambda t: PARK_HIT_FACTORS.get(t, 1.00)
    )

    # Statcast — batter: join by player_id + season
    for yr in TRAIN_SEASONS + [TEST_SEASON]:
        bsc = sc_bat.get(yr, pd.DataFrame())
        if bsc.empty:
            continue
        mask = model_df['season'] == yr
        for col in bsc.columns:
            if col not in model_df.columns:
                model_df[col] = np.nan
            model_df.loc[mask & model_df['player_id'].isin(bsc.index), col] = \
                model_df.loc[mask & model_df['player_id'].isin(bsc.index), 'player_id'].map(bsc[col])

    # Statcast — pitcher: join by sp_id + season
    if 'sp_id' in model_df.columns:
        for yr in TRAIN_SEASONS + [TEST_SEASON]:
            psc = sc_pit.get(yr, pd.DataFrame())
            if psc.empty:
                continue
            mask   = model_df['season'] == yr
            sp_map = model_df.loc[mask, 'sp_id'].dropna().astype(int)
            valid  = sp_map.isin(psc.index)
            for col in psc.columns:
                if col not in model_df.columns:
                    model_df[col] = np.nan
                model_df.loc[mask & valid.reindex(model_df.index, fill_value=False), col] = \
                    sp_map[valid].map(psc[col]).values

    # Fill missing pitcher counting stats with median
    for col in PITCHER_COUNTING_FEATURES:
        if col in model_df.columns:
            model_df[col] = model_df[col].fillna(model_df[col].median())

    # Determine fitted_features = only columns that actually exist in the df
    candidate_features = (
        BATTER_ROLL_FEATURES + PITCHER_COUNTING_FEATURES +
        CONTEXT_FEATURES + HANDEDNESS_FEATURES + PARK_FEATURES +
        STATCAST_BATTER_COLS + STATCAST_PITCHER_COLS
    )
    fitted_features = list(dict.fromkeys(
        [f for f in candidate_features if f in model_df.columns]
    ))
    print(f'  Model dataset: {len(model_df):,} batter-game records  '
          f'|  {len(fitted_features)} features')

    # ── 6. Load or train models ───────────────────────────────────────────────
    print('\nLoading models...')
    xgb, lr, rf, imputer, scaler, fitted_features = \
        load_or_train_models(model_df, fitted_features)

    # ── 7. Today's schedule ───────────────────────────────────────────────────
    print(f'\nFetching schedule for {today_str}...')
    games = get_todays_games()
    if not games:
        print('No games today. Exiting.')
        return
    print(f'  ✓ {len(games)} game(s) found')

    # ── 8. Build feature vectors for today's batters ──────────────────────────
    print("\nBuilding today's predictions...")
    today_records   = []
    skipped_no_qual = 0

    for game in games:
        away_abbr  = game['away_team_abbr']
        home_abbr  = game['home_team_abbr']
        home_team  = game['home_team']
        matchup    = f'{away_abbr} @ {home_abbr}'
        game_time  = get_game_time_et(game.get('game_date', ''))

        park_hit_factor = PARK_HIT_FACTORS.get(home_team, 1.00)

        # SP features (home SP faces AWAY batters; away SP faces HOME batters)
        away_sp      = game.get('away_sp')
        home_sp      = game.get('home_sp')
        away_sp_feat = get_pitcher_features(away_sp['id'], sc_pit) if away_sp else DEFAULT_SP.copy()
        away_sp_name = away_sp['name'] if away_sp else 'TBD'
        away_sp_id   = away_sp['id']   if away_sp else None
        home_sp_feat = get_pitcher_features(home_sp['id'], sc_pit) if home_sp else DEFAULT_SP.copy()
        home_sp_name = home_sp['name'] if home_sp else 'TBD'
        home_sp_id   = home_sp['id']   if home_sp else None

        print(f'  {matchup} ({game_time}) · park_hit_factor={park_hit_factor:.2f} · '
              f'SP vs {home_abbr}: {away_sp_name} | SP vs {away_abbr}: {home_sp_name}')

        sides = [
            {
                'team_id'    : game['home_team_id'],
                'team_abbr'  : home_abbr,
                'opp_abbr'   : away_abbr,
                'opp_sp_feat': away_sp_feat,
                'opp_sp_name': away_sp_name,
                'opp_sp_id'  : away_sp_id,
                'is_home'    : 1,
            },
            {
                'team_id'    : game['away_team_id'],
                'team_abbr'  : away_abbr,
                'opp_abbr'   : home_abbr,
                'opp_sp_feat': home_sp_feat,
                'opp_sp_name': home_sp_name,
                'opp_sp_id'  : home_sp_id,
                'is_home'    : 0,
            },
        ]

        for side in sides:
            roster = get_active_roster(side['team_id'])
            for player in roster:
                pid  = player['id']
                name = player['name']
                pos  = player['position']

                roll = build_batter_features(pid, model_df)
                if roll is None:
                    skipped_no_qual += 1
                    continue

                # Batter Statcast: prefer current year, fall back one year
                bat_sc = {}
                for yr in [CURRENT_YEAR, CURRENT_YEAR - 1]:
                    bsc = sc_bat.get(yr, pd.DataFrame())
                    if not bsc.empty and pid in bsc.index:
                        for col in bsc.columns:
                            bat_sc[col] = float(bsc.loc[pid, col])
                        break

                # Handedness
                bh  = hand_cache.get(str(pid), {}).get('bat_side', 'R')
                sph = hand_cache.get(str(side['opp_sp_id']), {}).get('pitch_hand', 'R') \
                      if side['opp_sp_id'] else 'R'

                rec = {
                    'player_id'    : pid,
                    'player_name'  : name,
                    'position'     : pos,
                    'team'         : side['team_abbr'],
                    'opponent'     : side['opp_abbr'],
                    'opp_sp'       : side['opp_sp_name'],
                    'is_home'      : side['is_home'],
                    'batting_order': 5,          # pre-game default
                    'game'         : matchup,
                    'game_time'    : game_time,
                    'bat_L'        : int(bh == 'L'),
                    'bat_R'        : int(bh == 'R'),
                    'sp_throws_L'  : int(sph == 'L'),
                    'platoon_adv'  : int(bh != sph and bh != 'S'),
                    'park_hit_factor': park_hit_factor,
                }
                rec.update(roll)
                rec.update(bat_sc)
                rec.update(side['opp_sp_feat'])
                today_records.append(rec)

    print(f'  Qualified batters: {len(today_records)}  '
          f'|  Skipped (<{MIN_PA} PA): {skipped_no_qual}')

    if not today_records:
        print('No qualified batters found. Exiting.')
        return

    today_df = pd.DataFrame(today_records)

    # Align columns to exactly what the model trained on
    for col in fitted_features:
        if col not in today_df.columns:
            today_df[col] = np.nan
        today_df[col] = pd.to_numeric(today_df[col], errors='coerce')

    X_raw = today_df[fitted_features].values.astype(float)
    X_imp = imputer.transform(X_raw)
    X_sc  = scaler.transform(X_imp)    # for LR

    # ── 9. Predict ────────────────────────────────────────────────────────────
    # p_mlp field now carries XGBoost probability (frontend-compatible naming)
    xgb_proba = xgb.predict_proba(X_imp)[:, 1]
    lr_proba  = lr.predict_proba(X_sc)[:, 1]
    rf_proba  = rf.predict_proba(X_imp)[:, 1]
    ens_proba = (xgb_proba + lr_proba + rf_proba) / 3

    today_df['p_mlp'] = np.round(xgb_proba, 4)   # XGBoost in the p_mlp slot
    today_df['p_lr']  = np.round(lr_proba,  4)
    today_df['p_rf']  = np.round(rf_proba,  4)
    today_df['p_ens'] = np.round(ens_proba,  4)

    today_df = today_df.sort_values('p_mlp', ascending=False).reset_index(drop=True)

    # ── 10. Build top-25 output records ───────────────────────────────────────
    def _safe(row, col):
        v = row.get(col, np.nan)
        return None if (v is None or (isinstance(v, float) and np.isnan(v))) else round(float(v), 4)

    top_n = []
    for i, (_, row) in enumerate(today_df.head(TOP_N).iterrows()):
        top_n.append({
            'rank'         : i + 1,
            'player'       : row['player_name'],
            'position'     : row['position'],
            'team'         : row['team'],
            'game'         : row['game'],
            'game_time'    : row['game_time'],
            'opposing_team': row['opponent'],
            'opp_sp'       : row['opp_sp'],
            # Probabilities (p_mlp = XGBoost; label kept for frontend compat)
            'p_mlp'        : float(row['p_mlp']),
            'p_lr'         : float(row['p_lr']),
            'p_rf'         : float(row['p_rf']),
            'p_ens'        : float(row['p_ens']),
            # Rolling stats
            'roll7_ba'     : _safe(row, 'roll7_BA'),
            'roll30_ba'    : _safe(row, 'roll30_BA'),
            'roll7_ops'    : _safe(row, 'roll7_OPS'),
            'roll30_ops'   : _safe(row, 'roll30_OPS'),
            # New: Statcast
            'sc_xba'       : _safe(row, 'sc_xba'),
            'sc_hard_hit_pct': _safe(row, 'sc_hard_hit_pct'),
            # SP counting
            'sp_era'       : _safe(row, 'P_era'),
            'sp_whip'      : _safe(row, 'P_whip'),
            # Platoon
            'platoon_adv'  : int(row.get('platoon_adv', 0)),
            'sp_throws_L'  : int(row.get('sp_throws_L', 0)),
            # Park
            'park_hit_factor': round(float(row.get('park_hit_factor', 1.0)), 3),
            'is_home'      : int(row['is_home']),
            # Grading placeholders
            'actual_hits'  : None,
            'correct'      : None,
        })

    print(f'\n✓ Top {len(top_n)} predictions generated')

    # ── 11. Write history ─────────────────────────────────────────────────────
    yday_record = next((r for r in history['records'] if r['date'] == yesterday_str), None)
    yday_summary = yday_record.get('summary', {}) if yday_record else {}
    alltime      = compute_alltime_stats(history, today_str)

    today_record = next((r for r in history['records'] if r['date'] == today_str), None)
    if today_record is None:
        history['records'].append({'date': today_str, 'graded': False, 'predictions': top_n})
    else:
        today_record['predictions'] = top_n
    save_history(history)

    # ── 12. Write main output JSON ─────────────────────────────────────────────
    output = {
        'updated'    : datetime.now(timezone.utc).isoformat(),
        'date'       : today_str,
        'model_version': 'v2-xgboost',
        'predictions': top_n,
        'yesterday'  : {'date': yesterday_str, **yday_summary},
        'alltime'    : alltime,
    }
    with open(MAIN_JSON, 'w') as f:
        json.dump(output, f, indent=2)

    print(f'✓ Wrote {len(top_n)} predictions → {MAIN_JSON}')
    if alltime['total'] > 0:
        print(f'  All-time: {alltime["hit_count"]}/{alltime["total"]} '
              f'got a hit ({alltime["hit_rate_pct"]} %)')


if __name__ == '__main__':
    run()
