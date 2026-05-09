"""
models/hitters_ml_hit.py
──────────────────────────────────────────────────────────────────────────────
Chalk Line Labs — ML Hit Probability Model  (v4)

v4 improvements over v3:
  1. BUG FIX: get_career_stats stored np.nan in JSON dict, causing json.dump
     to raise ValueError. Career stats were never cached and re-fetched every
     run. Fixed by storing None for missing values.

  2. BUG FIX: Career stats (career_ba, career_babip, career_obp) were listed
     in candidate_features but never joined to model_df, so they were silently
     excluded from fitted_features and had no effect on the model. Clarified
     as display-only context fields in the output JSON.

  3. BUG FIX: collect_season empty-DataFrame guard. An empty rows list
     (possible early in a season if no box scores are cached) produced an empty
     DataFrame with no columns, which always failed the REQUIRED_PKL_COLS check
     and caused an infinite rebuild loop.

  4. 14-game rolling window (ROLL_MID = 14) — sits between the noisy 7-game
     streak window and the stable 30-game form window. Captures players emerging
     from slumps or entering hot streaks. Added to build_rolling_features and
     build_batter_features. roll14_poisson_p_hit is a separate derived feature.

  5. XGBoost hyperparameter CV tuning via TimeSeriesSplit — a small grid of
     (max_depth, min_child_weight) combinations is evaluated using 2-fold
     temporal CV on the FIT_SEASONS data. Best params are logged and used for
     the final model. Results cached in the model PKL so CV only runs once per
     season.

  6. Probability calibration (Platt scaling) — XGBoost raw probabilities are
     compressed near the class-imbalance boundary. After the base model is
     trained on FIT_SEASONS [2022, 2023], it is calibrated using
     CalibratedClassifierCV(cv='prefit', method='sigmoid') fitted on CAL_SEASON
     [2024] data. The calibrated model is evaluated on TEST_SEASON [2025].
     This creates a clean train → calibrate → evaluate pipeline with no leakage.

DATA SPLIT:
  FIT_SEASONS  = [2022, 2023]  — base XGBoost training + CV tuning
  CAL_SEASON   = 2024          — Platt scaling calibration
  TRAIN_SEASONS = [2022, 2023, 2024]  — all historical data for feature eng.
  TEST_SEASON  = 2025          — hold-out accuracy reporting only

FEATURES (~54 total, dynamically determined at training time):
  Batter short-term  : roll7  BA, OBP, SLG, OPS, H/g, BB/g, SO/g, HR/g
  Batter mid-term    : roll14 BA, OBP, SLG, OPS, H/g, BB/g, SO/g, HR/g [NEW]
  Batter long-term   : roll30 BA, OBP, SLG, OPS, H/g, BB/g, SO/g, HR/g
  Batter derived     : poisson_p_hit (roll30), roll14_poisson_p_hit [NEW]
  Batter Statcast    : sc_xba, sc_xwoba, sc_exit_velo, sc_hard_hit_pct,
                       sc_k_pct, sc_bb_pct
  Opposing pitcher   : P_era, P_whip, P_so, P_bb, P_h, P_hr, P_bf, P_ip,
                       P_hit_rate
  Pitcher Statcast   : sp_sc_xba, sp_sc_hard_hit_pct, sp_sc_k_pct
  Context            : is_home, batting_order
  Handedness         : bat_L, bat_R, sp_throws_L, platoon_adv
  Park               : park_hit_factor

  Career stats (career_ba, career_babip, career_obp) are fetched for today's
  batters and included in the output JSON for display context, but are NOT model
  features — they are not present in the training DataFrame and therefore not in
  fitted_features.

OUTPUT FIELDS (unchanged for frontend compatibility):
  p_mlp -> calibrated XGBoost (primary sort key)
  p_lr  -> Logistic Regression (class_weight='balanced')
  p_rf  -> Random Forest       (class_weight='balanced')
  p_ens -> simple average of all three

QUALIFICATION:
  Batter must have >= 50 plate appearances in the current or prior season.

CACHING:
  hit_pred_cache/
    schedule_{year}.json                    all completed game PKs for a season
    box_{gamePk}.json                       parsed box score (cached forever)
    records_{year}.pkl                      assembled rows (auto-invalidated if stale)
    player_{id}_{today}_hitting.json        daily refresh
    player_{id}_{YEAR}_career_hitting.json  career stats (per-season cache)
    player_{id}_{year}_pitching.json        yearly refresh
    roster_{teamId}_{today}.json            daily refresh
    statcast_batter_{year}.pkl              Savant expected-stats (cached forever)
    statcast_pitcher_{year}.pkl             Savant expected-stats (cached forever)
    player_hands.json                       bat side + pitch hand

  models/mlb_cache_v2/
    ml_hit_models_v4.pkl   calibrated XGBoost + LR + RF + imputer + scaler +
                           fitted_features + best_xgb_params (v4 filename forces
                           a clean rebuild over v3)

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
from sklearn.metrics import log_loss
from sklearn.model_selection import TimeSeriesSplit
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
MODELS_PKL = os.path.join(MODEL_DIR, 'ml_hit_models_v4.pkl')  # v4 forces rebuild
HAND_FILE  = os.path.join(CACHE_DIR, 'player_hands.json')

for d in [DATA_DIR, CACHE_DIR, MODEL_DIR]:
    os.makedirs(d, exist_ok=True)

# ── Config ────────────────────────────────────────────────────────────────────
MLB_API       = 'https://statsapi.mlb.com/api/v1'
SAVANT_BASE   = 'https://baseballsavant.mlb.com'
CURRENT_YEAR  = date.today().year

# Three-way data split for train → calibrate → evaluate pipeline
FIT_SEASONS   = [2022, 2023]          # base XGBoost training + CV tuning
CAL_SEASON    = 2024                  # Platt scaling calibration
TRAIN_SEASONS = FIT_SEASONS + [CAL_SEASON]  # all historical data
TEST_SEASON   = 2025                  # hold-out evaluation only

TOP_N         = 25
MIN_PA        = 50
ROLL_SHORT    = 7
ROLL_MID      = 14    # NEW v4 — medium-term window
ROLL_LONG     = 30
SLEEP_S       = 0.05

TODAY = date.today().strftime('%Y-%m-%d')

# Columns required in season PKL. Missing any = stale; rebuild from box JSONs.
REQUIRED_PKL_COLS = {'home_team_name', 'sp_id'}

# ── XGBoost CV tuning grid (small to keep GitHub Actions runtime bounded) ─────
# 5 combinations × 2 folds × ~30 sec/fit ≈ 5 minutes
XGB_PARAM_GRID = [
    {'max_depth': 4, 'min_child_weight': 10},
    {'max_depth': 5, 'min_child_weight': 5},
    {'max_depth': 5, 'min_child_weight': 10},
    {'max_depth': 5, 'min_child_weight': 20},
    {'max_depth': 6, 'min_child_weight': 20},
]

# ── Feature groups ────────────────────────────────────────────────────────────
BATTER_ROLL7_FEATURES = [
    'roll7_BA',   'roll7_OBP',  'roll7_SLG',  'roll7_OPS',
    'roll7_B_h',  'roll7_B_bb', 'roll7_B_so', 'roll7_B_hr',
]
BATTER_ROLL14_FEATURES = [          # NEW v4
    'roll14_BA',   'roll14_OBP',  'roll14_SLG',  'roll14_OPS',
    'roll14_B_h',  'roll14_B_bb', 'roll14_B_so', 'roll14_B_hr',
]
BATTER_ROLL30_FEATURES = [
    'roll30_BA',  'roll30_OBP', 'roll30_SLG', 'roll30_OPS',
    'roll30_B_h', 'roll30_B_bb','roll30_B_so','roll30_B_hr',
]
BATTER_ROLL_FEATURES   = BATTER_ROLL7_FEATURES + BATTER_ROLL30_FEATURES
BATTER_DERIVED_FEATURES = ['poisson_p_hit', 'roll14_poisson_p_hit']  # v4 adds roll14

# P_hit_rate = P_h / P_bf
PITCHER_COUNTING_FEATURES = [
    'P_era', 'P_whip', 'P_so', 'P_bb', 'P_h', 'P_hr', 'P_bf', 'P_ip',
    'P_hit_rate',
]
CONTEXT_FEATURES    = ['is_home', 'batting_order']
HANDEDNESS_FEATURES = ['bat_L', 'bat_R', 'sp_throws_L', 'platoon_adv']
PARK_FEATURES       = ['park_hit_factor']

STATCAST_BATTER_COLS  = ['sc_xba', 'sc_xwoba', 'sc_exit_velo',
                          'sc_hard_hit_pct', 'sc_k_pct', 'sc_bb_pct']
STATCAST_PITCHER_COLS = ['sp_sc_xba', 'sp_sc_hard_hit_pct', 'sp_sc_k_pct']

# Dropna anchor — only roll7 and roll30; roll14 NaN is OK (imputed)
DROPNA_FEATURES = BATTER_ROLL_FEATURES

# ── Park hit factors (Baseball Reference 5-yr, normalized to 1.00) ────────────
PARK_HIT_FACTORS = {
    'Colorado Rockies'      : 1.12,
    'Boston Red Sox'        : 1.07,
    'Texas Rangers'         : 1.06,
    'Chicago Cubs'          : 1.04,
    'Cincinnati Reds'       : 1.04,
    'Milwaukee Brewers'     : 1.03,
    'Baltimore Orioles'     : 1.02,
    'Philadelphia Phillies' : 1.02,
    'Toronto Blue Jays'     : 1.01,
    'Houston Astros'        : 1.00,
    'New York Yankees'      : 1.00,
    'Detroit Tigers'        : 0.99,
    'Arizona Diamondbacks'  : 0.99,
    'Los Angeles Angels'    : 0.99,
    'Minnesota Twins'       : 0.98,
    'Atlanta Braves'        : 0.98,
    'St. Louis Cardinals'   : 0.98,
    'Cleveland Guardians'   : 0.98,
    'Kansas City Royals'    : 0.97,
    'Pittsburgh Pirates'    : 0.97,
    'Washington Nationals'  : 0.97,
    'Oakland Athletics'     : 0.97,
    'Athletics'             : 0.97,
    'Seattle Mariners'      : 0.97,
    'Chicago White Sox'     : 0.96,
    'San Francisco Giants'  : 0.96,
    'Tampa Bay Rays'        : 0.96,
    'Los Angeles Dodgers'   : 0.96,
    'New York Mets'         : 0.95,
    'Miami Marlins'         : 0.95,
    'San Diego Padres'      : 0.94,
}

DEFAULT_SP = {
    'P_era'     : 4.50,
    'P_whip'    : 1.30,
    'P_so'      : 0,
    'P_bb'      : 0,
    'P_h'       : 0,
    'P_hr'      : 0,
    'P_bf'      : 1,
    'P_ip'      : 0.0,
    'P_hit_rate': 0.245,
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
    """
    All completed regular-season game PKs for a season.

    Past seasons: cached forever (schedule is final).
    CURRENT_YEAR:  cached daily — new games complete every day so we
                   re-fetch the full list each morning to pick them up.
                   Old daily cache files are not cleaned up but are tiny.
    """
    if season == CURRENT_YEAR:
        cache = os.path.join(CACHE_DIR, f'schedule_{season}_{TODAY}.json')
    else:
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
    Parse one box score into batter-level records. Cached per game_pk forever.

    Required columns for valid PKL (checked in collect_season):
      home_team_name  -- park_hit_factor join
      sp_id           -- Statcast pitcher join
      P_hit_rate      -- hits allowed per BF
    """
    cache = os.path.join(CACHE_DIR, f'box_{game_pk}.json')
    if os.path.exists(cache):
        with open(cache) as f:
            data = json.load(f)
    else:
        try:
            data = _get(f'{MLB_API}/game/{game_pk}/boxscore')
        except Exception:
            return []
        with open(cache, 'w') as f:
            json.dump(data, f)
        time.sleep(SLEEP_S)

    records        = []
    teams_data     = data.get('teams', {})
    home_team_name = teams_data.get('home', {}).get('team', {}).get('name', 'Unknown')

    for side in ['away', 'home']:
        opp_side = 'home' if side == 'away' else 'away'
        is_home  = 1 if side == 'home' else 0

        team_obj  = teams_data.get(side, {})
        opp_obj   = teams_data.get(opp_side, {})
        team_name = team_obj.get('team', {}).get('name', 'Unknown')
        opp_name  = opp_obj.get('team', {}).get('name', 'Unknown')

        # ── Opposing starter stats ────────────────────────────────────────────
        opp_pitchers  = opp_obj.get('pitchers', [])
        opp_players   = opp_obj.get('players', {})
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
            bf  = max(_to_int(sp_stat.get('battersFaced', 1)), 1)
            ip  = max(ip_val, 0.1)
            starter_stats = {
                'sp_id'     : sp_pid,
                'P_ip'      : ip_val,
                'P_h'       : h,
                'P_er'      : er,
                'P_bb'      : bb,
                'P_so'      : _to_int(sp_stat.get('strikeOuts', 0)),
                'P_hr'      : _to_int(sp_stat.get('homeRuns', 0)),
                'P_era'     : _to_float(sp_stat.get('era',  er * 9 / ip)),
                'P_whip'    : _to_float(sp_stat.get('whip', (bb + h) / ip)),
                'P_bf'      : bf,
                'P_hit_rate': h / bf,
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
    """
    Load or fetch all batter-game records for one season.

    Past seasons (< CURRENT_YEAR): PKL cached forever after first build.
      Cache invalidation: PKL missing required columns is deleted and rebuilt.
      v4 bug fix: empty DataFrame guard avoids infinite rebuild loop.

    CURRENT_YEAR: never uses the PKL cache. The box_{pk}.json files accumulate
      daily (each game cached forever once fetched), so rebuilding from them
      each morning is fast (~35–162 files early-to-late in the season) and
      guarantees today's rolling features reflect actual 2026 game history.
    """
    cache_pkl = os.path.join(CACHE_DIR, f'records_{season}.pkl')

    if season != CURRENT_YEAR and os.path.exists(cache_pkl):
        df = pd.read_pickle(cache_pkl)
        if len(df) == 0:
            print(f'  {season}: cached empty dataset (early season)')
            return df
        missing = REQUIRED_PKL_COLS - set(df.columns)
        if missing:
            print(f'  {season}: PKL missing columns {missing} — rebuilding...')
            os.remove(cache_pkl)
        else:
            print(f'  {season}: loaded {len(df):,} records from cache')
            return df

    tag = 'live — no PKL' if season == CURRENT_YEAR else 'assembling from box JSONs'
    print(f'  {season}: {tag}...')
    pks  = get_season_game_pks(season)
    rows = []
    for i, pk in enumerate(pks):
        rows.extend(parse_boxscore(pk, season))
        if (i + 1) % 100 == 0:
            print(f'    {i+1}/{len(pks)} games processed...')
    df = pd.DataFrame(rows)
    if season != CURRENT_YEAR:
        df.to_pickle(cache_pkl)
        print(f'  {season}: saved {len(df):,} records')
    else:
        print(f'  {season}: {len(df):,} live records (not cached)')
    return df


# ═══════════════════════════════════════════════════════════════════════════════
#  STATCAST
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_statcast_csv(year, player_type='batter'):
    """
    Download Baseball Savant expected-stats leaderboard CSV. Cached forever
    for past seasons. For CURRENT_YEAR, cached daily — Savant updates xBA
    and other expected stats throughout the season.
    """
    if year == CURRENT_YEAR:
        cache = os.path.join(CACHE_DIR, f'statcast_{player_type}_{year}_{TODAY}.pkl')
    else:
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

    for id_col in ['player_id', 'playerid', 'mlbam_id']:
        if id_col in df.columns:
            df = df.rename(columns={id_col: 'player_id'})
            break
    if 'player_id' not in df.columns:
        return pd.DataFrame()
    df['player_id'] = pd.to_numeric(df['player_id'], errors='coerce')

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

def _poisson_p(ba, avg_ab):
    """P(>=1 hit) = 1 - (1 - BA)^avg_ab, with safe clipping."""
    ba  = max(min(float(ba),  0.999), 0.001)
    ab  = max(min(float(avg_ab), 6.0), 1.0)
    return 1.0 - (1.0 - ba) ** ab


def build_rolling_features(df):
    """
    Compute lagged rolling averages for each batter across their game history.
    shift(1) prevents data leakage (current game excluded from its own window).

    v4: adds ROLL_MID (14-game) window and roll14_poisson_p_hit.
    Dropna anchor remains BATTER_ROLL_FEATURES (roll7 + roll30 only) —
    roll14 NaN for early games is handled by the imputer.
    """
    df = df.sort_values(['player_id', 'game_pk']).copy()
    grp = df.groupby('player_id')

    for col in ['B_h', 'B_ab', 'B_bb', 'B_so', 'B_hr', 'B_pa', 'B_tb']:
        df[f'roll7_{col}']  = grp[col].transform(
            lambda s: s.shift(1).rolling(ROLL_SHORT, min_periods=2).mean())
        df[f'roll14_{col}'] = grp[col].transform(          # NEW v4
            lambda s: s.shift(1).rolling(ROLL_MID,   min_periods=5).mean())
        df[f'roll30_{col}'] = grp[col].transform(
            lambda s: s.shift(1).rolling(ROLL_LONG,  min_periods=5).mean())

    # roll7 rate stats
    df['roll7_BA']   = df['roll7_B_h']  / df['roll7_B_ab'].replace(0, np.nan)
    df['roll7_OBP']  = (df['roll7_B_h'] + df['roll7_B_bb']) / df['roll7_B_pa'].replace(0, np.nan)
    df['roll7_SLG']  = df['roll7_B_tb'] / df['roll7_B_ab'].replace(0, np.nan)
    df['roll7_OPS']  = df['roll7_OBP']  + df['roll7_SLG']

    # roll14 rate stats
    df['roll14_BA']  = df['roll14_B_h']  / df['roll14_B_ab'].replace(0, np.nan)
    df['roll14_OBP'] = (df['roll14_B_h'] + df['roll14_B_bb']) / df['roll14_B_pa'].replace(0, np.nan)
    df['roll14_SLG'] = df['roll14_B_tb'] / df['roll14_B_ab'].replace(0, np.nan)
    df['roll14_OPS'] = df['roll14_OBP']  + df['roll14_SLG']

    # roll30 rate stats
    df['roll30_BA']  = df['roll30_B_h']  / df['roll30_B_ab'].replace(0, np.nan)
    df['roll30_OBP'] = (df['roll30_B_h'] + df['roll30_B_bb']) / df['roll30_B_pa'].replace(0, np.nan)
    df['roll30_SLG'] = df['roll30_B_tb'] / df['roll30_B_ab'].replace(0, np.nan)
    df['roll30_OPS'] = df['roll30_OBP']  + df['roll30_SLG']

    # Poisson anchors — P(>=1 hit) from rolling BA × avg AB/game
    ba30 = df['roll30_BA'].clip(0.001, 0.999)
    ab30 = df['roll30_B_ab'].clip(1.0, 6.0)
    df['poisson_p_hit'] = 1.0 - (1.0 - ba30) ** ab30

    ba14 = df['roll14_BA'].clip(0.001, 0.999)   # NaN where roll14 not yet available
    ab14 = df['roll14_B_ab'].clip(1.0, 6.0)
    df['roll14_poisson_p_hit'] = 1.0 - (1.0 - ba14) ** ab14

    return df


# ═══════════════════════════════════════════════════════════════════════════════
#  MODEL TRAINING  (v4)
# ═══════════════════════════════════════════════════════════════════════════════

def _tune_xgb_params(X_fit, y_fit, spw):
    """
    Temporal CV over XGB_PARAM_GRID using TimeSeriesSplit(n_splits=2).
    Returns (best_params_dict, best_log_loss).
    Runs on the FIT_SEASONS data only, so leakage from CAL/TEST seasons
    is impossible.
    """
    tscv  = TimeSeriesSplit(n_splits=2)
    best  = None
    best_score = float('inf')

    print(f'  CV tuning over {len(XGB_PARAM_GRID)} param sets × 2 folds...')
    for params in XGB_PARAM_GRID:
        fold_scores = []
        for fold_i, (tr_idx, val_idx) in enumerate(tscv.split(X_fit)):
            X_tr, X_val = X_fit[tr_idx], X_fit[val_idx]
            y_tr, y_val = y_fit[tr_idx], y_fit[val_idx]
            m = XGBClassifier(
                n_estimators     = 300,
                learning_rate    = 0.05,
                subsample        = 0.8,
                colsample_bytree = 0.8,
                scale_pos_weight = spw,
                eval_metric      = 'logloss',
                use_label_encoder= False,
                random_state     = 42,
                n_jobs           = -1,
                **params,
            )
            m.fit(X_tr, y_tr,
                  eval_set=[(X_val, y_val)],
                  verbose=False)
            fold_scores.append(log_loss(y_val, m.predict_proba(X_val)[:, 1]))

        mean_ll = float(np.mean(fold_scores))
        print(f'    {params}  →  log-loss {mean_ll:.5f}')
        if mean_ll < best_score:
            best_score = mean_ll
            best  = params

    print(f'  Best params: {best}  (log-loss {best_score:.5f})')
    return best, best_score


class PlattCalibratedXGB:
    """
    Manual Platt scaling wrapper for XGBClassifier.

    sklearn's CalibratedClassifierCV dropped cv='prefit' support in v1.2.
    This class replicates the same math without any sklearn version dependency:
      1. Get raw XGBoost probabilities on the held-out CAL set.
      2. Fit a single LogisticRegression on those probabilities vs y_cal.
      3. At inference, transform XGBoost raw proba through the LR.

    The result is a drop-in replacement — predict() and predict_proba() have
    the same signatures as any sklearn estimator.
    """

    def __init__(self, xgb_base):
        self.xgb_base  = xgb_base
        self.platt_lr  = LogisticRegression(C=1.0, solver='lbfgs',
                                            max_iter=1000, random_state=42)

    def fit_calibration(self, X_cal, y_cal):
        """Fit the Platt scaler on held-out calibration data."""
        raw_proba = self.xgb_base.predict_proba(X_cal)[:, 1].reshape(-1, 1)
        self.platt_lr.fit(raw_proba, y_cal)
        return self

    def predict_proba(self, X):
        raw_proba = self.xgb_base.predict_proba(X)[:, 1].reshape(-1, 1)
        cal_pos   = self.platt_lr.predict_proba(raw_proba)[:, 1]
        return np.column_stack([1 - cal_pos, cal_pos])

    def predict(self, X):
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)



    """
    v4 training pipeline:
      1. CV-tune XGBoost on FIT_SEASONS data (temporal cross-validation).
      2. Train base XGBoost with best params on full FIT_SEASONS.
      3. Calibrate with Platt scaling on CAL_SEASON (held-out from training).
      4. Train LR and RF on all TRAIN_SEASONS (calibration not needed — LR
         probabilities are already well-calibrated).
      5. Report accuracy on TEST_SEASON hold-out.

    Returns: xgb_cal, lr, rf, imputer, scaler, best_xgb_params
    """
    fit_mask   = model_df['season'].isin(FIT_SEASONS)
    cal_mask   = model_df['season'] == CAL_SEASON
    train_mask = model_df['season'].isin(TRAIN_SEASONS)
    test_mask  = model_df['season'] == TEST_SEASON

    X_fit_raw   = model_df.loc[fit_mask,   fitted_features].values.astype(float)
    y_fit       = model_df.loc[fit_mask,   'hit'].values
    X_cal_raw   = model_df.loc[cal_mask,   fitted_features].values.astype(float)
    y_cal       = model_df.loc[cal_mask,   'hit'].values
    X_train_raw = model_df.loc[train_mask, fitted_features].values.astype(float)
    y_train     = model_df.loc[train_mask, 'hit'].values
    X_test_raw  = model_df.loc[test_mask,  fitted_features].values.astype(float)
    y_test      = model_df.loc[test_mask,  'hit'].values

    n_pos = y_fit.sum()
    n_neg = len(y_fit) - n_pos
    spw   = round(n_neg / max(n_pos, 1), 2)

    print(f'  FIT  ({FIT_SEASONS}): {len(X_fit_raw):,} samples  '
          f'hits {n_pos/len(y_fit)*100:.1f}%  spw={spw}')
    print(f'  CAL  ({CAL_SEASON}):  {len(X_cal_raw):,} samples')
    print(f'  TEST ({TEST_SEASON}): {len(X_test_raw):,} samples  '
          f'|  {len(fitted_features)} features')

    # Imputer and scaler fit on FIT data; transform all splits consistently
    imputer     = SimpleImputer(strategy='median')
    X_fit_imp   = imputer.fit_transform(X_fit_raw)
    X_cal_imp   = imputer.transform(X_cal_raw)
    X_train_imp = imputer.transform(X_train_raw)
    X_test_imp  = imputer.transform(X_test_raw)

    scaler      = MinMaxScaler()
    X_fit_sc    = scaler.fit_transform(X_fit_imp)
    X_train_sc  = scaler.transform(X_train_imp)
    X_test_sc   = scaler.transform(X_test_imp)

    # ── Step 1: CV-tune XGBoost on FIT data ──────────────────────────────────
    best_params, _ = _tune_xgb_params(X_fit_imp, y_fit, spw)

    # ── Step 2: Train base XGBoost on FIT data with best params ──────────────
    print('  Training base XGBoost on FIT seasons...')
    xgb_base = XGBClassifier(
        n_estimators     = 400,
        learning_rate    = 0.05,
        subsample        = 0.8,
        colsample_bytree = 0.8,
        scale_pos_weight = spw,
        eval_metric      = 'logloss',
        use_label_encoder= False,
        random_state     = 42,
        n_jobs           = -1,
        **best_params,
    )
    xgb_base.fit(X_fit_imp, y_fit,
                 eval_set=[(X_cal_imp, y_cal)],
                 verbose=False)

    # ── Step 3: Platt-scale calibration on CAL_SEASON ────────────────────────
    # Manual implementation — sklearn's cv='prefit' was removed in v1.2.
    print(f'  Calibrating on {CAL_SEASON} (Platt scaling)...')
    xgb_cal = PlattCalibratedXGB(xgb_base).fit_calibration(X_cal_imp, y_cal)

    # ── Step 4: LR and RF on all TRAIN_SEASONS ────────────────────────────────
    n_pos_all = y_train.sum()
    n_neg_all = len(y_train) - n_pos_all
    spw_all   = round(n_neg_all / max(n_pos_all, 1), 2)

    print('  Training Logistic Regression on TRAIN seasons...')
    lr = LogisticRegression(
        C=1.0, max_iter=1000, solver='lbfgs',
        class_weight='balanced', random_state=42,
    )
    lr.fit(X_train_sc, y_train)

    print('  Training Random Forest on TRAIN seasons...')
    rf = RandomForestClassifier(
        n_estimators     = 300,
        max_depth        = 10,
        min_samples_leaf = 20,
        class_weight     = 'balanced',
        random_state     = 42,
        n_jobs           = -1,
    )
    rf.fit(X_train_imp, y_train)

    # ── Step 5: Evaluate on TEST hold-out ─────────────────────────────────────
    for name, model, X_t in [
        ('XGBoost (calibrated)', xgb_cal, X_test_imp),
        ('LR',                   lr,      X_test_sc),
        ('RF',                   rf,      X_test_imp),
    ]:
        acc = (model.predict(X_t) == y_test).mean()
        ll  = log_loss(y_test, model.predict_proba(X_t)[:, 1])
        print(f'  {name}: acc={acc:.4f}  log-loss={ll:.5f}')

    return xgb_cal, lr, rf, imputer, scaler, best_params


def load_or_train_models(model_df, fitted_features):
    """Load cached v4 models if they match the current season; else retrain."""
    if os.path.exists(MODELS_PKL):
        with open(MODELS_PKL, 'rb') as f:
            cache = pickle.load(f)
        if cache.get('trained_year') == CURRENT_YEAR:
            print('  Loaded cached ML models (v4).')
            return (cache['xgb'], cache['lr'], cache['rf'],
                    cache['imputer'], cache['scaler'],
                    cache['fitted_features'], cache.get('best_xgb_params', {}))
        else:
            print(f'  New season ({CURRENT_YEAR}) — retraining...')

    print('  Training models (first run this season — ~10 min for CV + calibration)...')
    xgb, lr, rf, imputer, scaler, best_params = train_models(model_df, fitted_features)

    with open(MODELS_PKL, 'wb') as f:
        pickle.dump({
            'trained_year'   : CURRENT_YEAR,
            'xgb'            : xgb,
            'lr'             : lr,
            'rf'             : rf,
            'imputer'        : imputer,
            'scaler'         : scaler,
            'fitted_features': fitted_features,
            'best_xgb_params': best_params,
        }, f)
    print('  Models trained and cached.')
    return xgb, lr, rf, imputer, scaler, fitted_features, best_params


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
                'game_pk'       : g['gamePk'],
                'game_date'     : g.get('gameDate', ''),
                'away_team'     : g['teams']['away']['team']['name'],
                'home_team'     : g['teams']['home']['team']['name'],
                'away_team_id'  : g['teams']['away']['team']['id'],
                'home_team_id'  : g['teams']['home']['team']['id'],
                'away_team_abbr': g['teams']['away']['team'].get('abbreviation', '?'),
                'home_team_abbr': g['teams']['home']['team'].get('abbreviation', '?'),
                'away_sp'       : None,
                'home_sp'       : None,
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


def get_career_stats(player_id):
    """
    Fetch career hitting stats. Cached once per season (stable data).

    v4 bug fix: v3 stored np.nan in the result dict before json.dump, causing
    ValueError (NaN is not valid JSON). Career stats were never cached and
    re-fetched on every run. Fixed by storing None for missing values; None
    serializes as JSON null and is handled by the imputer downstream.

    NOTE: Career stats are display-only context in the output JSON. They are
    NOT model features because they are not joined to the training DataFrame.
    """
    cache = os.path.join(CACHE_DIR,
                         f'player_{player_id}_{CURRENT_YEAR}_career_hitting.json')
    if os.path.exists(cache):
        with open(cache) as f:
            return json.load(f)
    try:
        url    = f'{MLB_API}/people/{player_id}/stats?stats=career&group=hitting'
        splits = _get(url).get('stats', [])
        s      = splits[0].get('splits', [{}])[0].get('stat', {}) if splits else {}
        if not s:
            return {}

        ab  = max(_to_int(s.get('atBats', 0)), 1)
        h   = _to_int(s.get('hits', 0))
        hr  = _to_int(s.get('homeRuns', 0))
        so  = _to_int(s.get('strikeOuts', 0))
        bb  = _to_int(s.get('baseOnBalls', 0))
        pa  = max(_to_int(s.get('plateAppearances', 0)), ab + bb)

        career_ba   = _to_float(s.get('avg',  h / ab))
        career_obp  = _to_float(s.get('obp',  (h + bb) / max(pa, 1)))
        babip_denom = max(ab - so - hr, 1)
        career_babip = _to_float(s.get('babip', (h - hr) / babip_denom))

        # Use None (not np.nan) so json.dump succeeds — v4 bug fix
        def _safe_val(v):
            return None if (v != v) else float(v)  # v != v is True only for NaN

        result = {
            'career_ba'   : _safe_val(career_ba),
            'career_babip': _safe_val(career_babip),
            'career_obp'  : _safe_val(career_obp),
        }
        with open(cache, 'w') as f:
            json.dump(result, f)
        time.sleep(SLEEP_S)
        return result
    except:
        return {}


def get_pitcher_features(pitcher_id, sc_pit):
    """Build pitcher feature dict from season-to-date counting stats + Statcast."""
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
        'P_era'     : era  if era  == era  else 4.50,
        'P_whip'    : whip if whip == whip else 1.30,
        'P_so'      : so,
        'P_bb'      : bb,
        'P_h'       : h,
        'P_hr'      : hr,
        'P_bf'      : bf,
        'P_ip'      : ip_val,
        'P_hit_rate': h / bf,
    }

    for yr in [CURRENT_YEAR, CURRENT_YEAR - 1]:
        pit_sc = sc_pit.get(yr, pd.DataFrame())
        if not pit_sc.empty and pitcher_id in pit_sc.index:
            for col in pit_sc.columns:
                feats[col] = float(pit_sc.loc[pitcher_id, col])
            break

    return feats


def build_batter_features(player_id, model_df):
    """
    Build rolling + career context dict for a batter from historical model_df.
    Falls back to API season stats when box score history is thin.
    Returns None if batter is unqualified (< MIN_PA).

    v4: adds roll14 features and roll14_poisson_p_hit.
    Career stats (career_ba, career_babip, career_obp) are returned as
    display context but are NOT in fitted_features.
    """
    player_games = model_df[
        (model_df['player_id'] == player_id) &
        (model_df['season'].isin([CURRENT_YEAR, CURRENT_YEAR - 1]))
    ].sort_values('game_pk')

    career = get_career_stats(player_id)

    if len(player_games) >= 5:
        def _roll(df, n):
            tail   = df.tail(n)
            ab     = tail['B_ab'].sum(); pa = tail['B_pa'].sum()
            h      = tail['B_h'].sum();  bb = tail['B_bb'].sum()
            so     = tail['B_so'].sum(); hr = tail['B_hr'].sum()
            tb     = tail['B_tb'].sum(); ng = len(tail)
            ab     = max(ab, 1); pa = max(pa, 1)
            ba     = h / ab
            return {
                'BA': ba, 'OBP': (h + bb) / pa,
                'SLG': tb / ab, 'OPS': (h + bb) / pa + tb / ab,
                'h': h / ng, 'bb': bb / ng, 'so': so / ng, 'hr': hr / ng,
                'avg_ab': ab / ng,
            }

        r7  = _roll(player_games, ROLL_SHORT)
        r14 = _roll(player_games, ROLL_MID)
        r30 = _roll(player_games, ROLL_LONG)

        return {
            # roll7
            'roll7_BA'    : r7['BA'],   'roll7_OBP'   : r7['OBP'],
            'roll7_SLG'   : r7['SLG'],  'roll7_OPS'   : r7['OPS'],
            'roll7_B_h'   : r7['h'],    'roll7_B_bb'  : r7['bb'],
            'roll7_B_so'  : r7['so'],   'roll7_B_hr'  : r7['hr'],
            # roll14 (new v4)
            'roll14_BA'   : r14['BA'],  'roll14_OBP'  : r14['OBP'],
            'roll14_SLG'  : r14['SLG'], 'roll14_OPS'  : r14['OPS'],
            'roll14_B_h'  : r14['h'],   'roll14_B_bb' : r14['bb'],
            'roll14_B_so' : r14['so'],  'roll14_B_hr' : r14['hr'],
            'roll14_poisson_p_hit': _poisson_p(r14['BA'], r14['avg_ab']),
            # roll30
            'roll30_BA'   : r30['BA'],  'roll30_OBP'  : r30['OBP'],
            'roll30_SLG'  : r30['SLG'], 'roll30_OPS'  : r30['OPS'],
            'roll30_B_h'  : r30['h'],   'roll30_B_bb' : r30['bb'],
            'roll30_B_so' : r30['so'],  'roll30_B_hr' : r30['hr'],
            'poisson_p_hit': _poisson_p(r30['BA'], r30['avg_ab']),
            # display-only context (not in fitted_features)
            'career_ba'   : career.get('career_ba'),
            'career_babip': career.get('career_babip'),
            'career_obp'  : career.get('career_obp'),
        }

    # API fallback
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
    ba  = h / ab
    obp = (h + bb) / pa
    slg = tb / ab
    ops = obp + slg
    avg_ab = ab / gp
    pp     = _poisson_p(ba, avg_ab)

    return {
        'roll7_BA'    : ba,    'roll7_OBP'   : obp,  'roll7_SLG'   : slg,  'roll7_OPS'   : ops,
        'roll7_B_h'   : h/gp,  'roll7_B_bb'  : bb/gp,'roll7_B_so'  : so/gp,'roll7_B_hr'  : hr/gp,
        'roll14_BA'   : ba,    'roll14_OBP'  : obp,  'roll14_SLG'  : slg,  'roll14_OPS'  : ops,
        'roll14_B_h'  : h/gp,  'roll14_B_bb' : bb/gp,'roll14_B_so' : so/gp,'roll14_B_hr' : hr/gp,
        'roll14_poisson_p_hit': pp,
        'roll30_BA'   : ba,    'roll30_OBP'  : obp,  'roll30_SLG'  : slg,  'roll30_OPS'  : ops,
        'roll30_B_h'  : h/gp,  'roll30_B_bb' : bb/gp,'roll30_B_so' : so/gp,'roll30_B_hr' : hr/gp,
        'poisson_p_hit': pp,
        'career_ba'   : career.get('career_ba'),
        'career_babip': career.get('career_babip'),
        'career_obp'  : career.get('career_obp'),
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
                    for pdata in box.get('teams', {}).get(side, {}).get('players', {}).values():
                        h    = _to_int(pdata.get('stats', {}).get('batting', {}).get('hits', 0))
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
        prob = p.get('p_mlp', 0)
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
    print(f'    {len(hit)}/{len(played)} got a hit')


def compute_alltime_stats(history, today_str):
    buckets   = {'75%+': [0,0], '65-74%': [0,0], '55-64%': [0,0], '<55%': [0,0]}
    total     = hit_total = 0
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

    print(f'\n== ML Hit Model v4 -- {today_str} ==')
    print(f'   Fit: {FIT_SEASONS}  Cal: {CAL_SEASON}  '
          f'Test: {TEST_SEASON}  MIN_PA: {MIN_PA}')

    # ── 1. Load history and grade yesterday ───────────────────────────────────
    history = load_history()
    grade_yesterday(history, yesterday_str)

    # ── 2. Load box scores ────────────────────────────────────────────────────
    # TRAIN_SEASONS + TEST_SEASON: permanently cached PKLs (complete seasons).
    # CURRENT_YEAR: rebuilt daily from accumulated box JSONs — this is what
    # gives batter rolling features their current-season form rather than
    # stale end-of-last-season stats.
    print('\nLoading historical box scores...')
    _load_seasons = list(dict.fromkeys(TRAIN_SEASONS + [TEST_SEASON, CURRENT_YEAR]))
    all_dfs = []
    for season in _load_seasons:
        all_dfs.append(collect_season(season))
    raw_df = pd.concat([d for d in all_dfs if len(d) > 0], ignore_index=True)

    # ── 3. Statcast CSVs ──────────────────────────────────────────────────────
    print('\nFetching Statcast CSVs...')
    sc_bat = {}
    sc_pit = {}
    for yr in list(dict.fromkeys(TRAIN_SEASONS + [TEST_SEASON, CURRENT_YEAR])):
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

    # ── 5. Feature engineering ────────────────────────────────────────────────
    print('\nEngineering features...')
    model_df = build_rolling_features(raw_df)
    # Anchor dropna on roll7+roll30 only; roll14 NaN is handled by imputer
    model_df = model_df.dropna(subset=DROPNA_FEATURES).copy()

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
    if 'home_team_name' in model_df.columns:
        model_df['park_hit_factor'] = model_df['home_team_name'].map(
            lambda t: PARK_HIT_FACTORS.get(t, 1.00)
        )
    else:
        print('  WARN: home_team_name missing — park factor defaulted to 1.00')
        model_df['park_hit_factor'] = 1.00

    # P_hit_rate — compute from raw counts if not already in df
    if 'P_hit_rate' not in model_df.columns:
        if 'P_h' in model_df.columns and 'P_bf' in model_df.columns:
            model_df['P_hit_rate'] = (
                model_df['P_h'] / model_df['P_bf'].replace(0, np.nan)
            )
        else:
            model_df['P_hit_rate'] = DEFAULT_SP['P_hit_rate']

    # Statcast — batter: join by player_id + season
    for yr in list(dict.fromkeys(TRAIN_SEASONS + [TEST_SEASON, CURRENT_YEAR])):
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
        for yr in list(dict.fromkeys(TRAIN_SEASONS + [TEST_SEASON, CURRENT_YEAR])):
            psc = sc_pit.get(yr, pd.DataFrame())
            if psc.empty:
                continue
            mask   = model_df['season'] == yr
            sp_map = model_df.loc[mask, 'sp_id'].dropna().astype(int)
            valid  = sp_map.isin(psc.index)
            for col in psc.columns:
                if col not in model_df.columns:
                    model_df[col] = np.nan
                model_df.loc[
                    mask & valid.reindex(model_df.index, fill_value=False), col
                ] = sp_map[valid].map(psc[col]).values

    # Fill missing pitcher counting stats with median
    for col in PITCHER_COUNTING_FEATURES:
        if col in model_df.columns:
            model_df[col] = model_df[col].fillna(model_df[col].median())

    # Determine fitted_features — career stats are intentionally excluded
    # (not in model_df; they're display-only fetched at inference time)
    candidate_features = (
        BATTER_ROLL7_FEATURES + BATTER_ROLL14_FEATURES + BATTER_ROLL30_FEATURES +
        BATTER_DERIVED_FEATURES + PITCHER_COUNTING_FEATURES +
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
    xgb, lr, rf, imputer, scaler, fitted_features, best_params = \
        load_or_train_models(model_df, fitted_features)
    print(f'  XGBoost params: {best_params}')

    # ── 7. Today's schedule ───────────────────────────────────────────────────
    print(f'\nFetching schedule for {today_str}...')
    games = get_todays_games()
    if not games:
        print('No games today. Exiting.')
        return
    print(f'  {len(games)} game(s) found')

    # ── 8. Build feature vectors for today's batters ──────────────────────────
    print("\nBuilding today's predictions...")
    today_records   = []
    skipped_no_qual = 0

    for game in games:
        away_abbr = game['away_team_abbr']
        home_abbr = game['home_team_abbr']
        home_team = game['home_team']
        matchup   = f'{away_abbr} @ {home_abbr}'
        game_time = get_game_time_et(game.get('game_date', ''))

        park_hit_factor = PARK_HIT_FACTORS.get(home_team, 1.00)

        away_sp      = game.get('away_sp')
        home_sp      = game.get('home_sp')
        away_sp_feat = get_pitcher_features(away_sp['id'], sc_pit) if away_sp else DEFAULT_SP.copy()
        away_sp_name = away_sp['name'] if away_sp else 'TBD'
        away_sp_id   = away_sp['id']   if away_sp else None
        home_sp_feat = get_pitcher_features(home_sp['id'], sc_pit) if home_sp else DEFAULT_SP.copy()
        home_sp_name = home_sp['name'] if home_sp else 'TBD'
        home_sp_id   = home_sp['id']   if home_sp else None

        print(f'  {matchup} ({game_time}) park={park_hit_factor:.2f} | '
              f'SP vs {home_abbr}: {away_sp_name} | SP vs {away_abbr}: {home_sp_name}')

        sides = [
            {'team_id': game['home_team_id'], 'team_abbr': home_abbr,
             'opp_abbr': away_abbr, 'opp_sp_feat': away_sp_feat,
             'opp_sp_name': away_sp_name, 'opp_sp_id': away_sp_id, 'is_home': 1},
            {'team_id': game['away_team_id'], 'team_abbr': away_abbr,
             'opp_abbr': home_abbr, 'opp_sp_feat': home_sp_feat,
             'opp_sp_name': home_sp_name, 'opp_sp_id': home_sp_id, 'is_home': 0},
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

                bat_sc = {}
                for yr in [CURRENT_YEAR, CURRENT_YEAR - 1]:
                    bsc = sc_bat.get(yr, pd.DataFrame())
                    if not bsc.empty and pid in bsc.index:
                        for col in bsc.columns:
                            bat_sc[col] = float(bsc.loc[pid, col])
                        break

                bh  = hand_cache.get(str(pid), {}).get('bat_side', 'R')
                sph = hand_cache.get(str(side['opp_sp_id']), {}).get('pitch_hand', 'R') \
                      if side['opp_sp_id'] else 'R'

                rec = {
                    'player_id'      : pid,
                    'player_name'    : name,
                    'position'       : pos,
                    'team'           : side['team_abbr'],
                    'opponent'       : side['opp_abbr'],
                    'opp_sp'         : side['opp_sp_name'],
                    'is_home'        : side['is_home'],
                    'batting_order'  : 5,
                    'game'           : matchup,
                    'game_time'      : game_time,
                    'bat_L'          : int(bh == 'L'),
                    'bat_R'          : int(bh == 'R'),
                    'sp_throws_L'    : int(sph == 'L'),
                    'platoon_adv'    : int(bh != sph and bh != 'S'),
                    'park_hit_factor': park_hit_factor,
                }
                rec.update(roll)                  # rolling + poisson + career (display)
                rec.update(bat_sc)                # Statcast batter
                rec.update(side['opp_sp_feat'])   # pitcher counts + Statcast
                today_records.append(rec)

    print(f'  Qualified batters: {len(today_records)}  '
          f'|  Skipped (<{MIN_PA} PA): {skipped_no_qual}')

    if not today_records:
        print('No qualified batters found. Exiting.')
        return

    today_df = pd.DataFrame(today_records)

    for col in fitted_features:
        if col not in today_df.columns:
            today_df[col] = np.nan
        today_df[col] = pd.to_numeric(today_df[col], errors='coerce')

    X_raw = today_df[fitted_features].values.astype(float)
    X_imp = imputer.transform(X_raw)
    X_sc  = scaler.transform(X_imp)

    # ── 9. Predict ────────────────────────────────────────────────────────────
    # xgb is already calibrated (CalibratedClassifierCV); uses X_imp not X_sc
    xgb_proba = xgb.predict_proba(X_imp)[:, 1]
    lr_proba  = lr.predict_proba(X_sc)[:, 1]
    rf_proba  = rf.predict_proba(X_imp)[:, 1]
    ens_proba = (xgb_proba + lr_proba + rf_proba) / 3

    today_df['p_mlp'] = np.round(xgb_proba, 4)
    today_df['p_lr']  = np.round(lr_proba,  4)
    today_df['p_rf']  = np.round(rf_proba,  4)
    today_df['p_ens'] = np.round(ens_proba,  4)

    today_df = today_df.sort_values('p_mlp', ascending=False).reset_index(drop=True)

    # ── 10. Build top-25 output records ───────────────────────────────────────
    def _safe(row, col, decimals=4):
        v = row.get(col)
        if v is None:
            return None
        try:
            f = float(v)
            return None if np.isnan(f) else round(f, decimals)
        except:
            return None

    top_n = []
    for i, (_, row) in enumerate(today_df.head(TOP_N).iterrows()):
        top_n.append({
            'rank'                 : i + 1,
            'player'               : row['player_name'],
            'position'             : row['position'],
            'team'                 : row['team'],
            'game'                 : row['game'],
            'game_time'            : row['game_time'],
            'opposing_team'        : row['opponent'],
            'opp_sp'               : row['opp_sp'],
            # Probabilities (p_mlp = calibrated XGBoost)
            'p_mlp'                : float(row['p_mlp']),
            'p_lr'                 : float(row['p_lr']),
            'p_rf'                 : float(row['p_rf']),
            'p_ens'                : float(row['p_ens']),
            # Rolling stats
            'roll7_ba'             : _safe(row, 'roll7_BA'),
            'roll14_ba'            : _safe(row, 'roll14_BA'),    # new v4
            'roll30_ba'            : _safe(row, 'roll30_BA'),
            'roll7_ops'            : _safe(row, 'roll7_OPS'),
            'roll14_ops'           : _safe(row, 'roll14_OPS'),   # new v4
            'roll30_ops'           : _safe(row, 'roll30_OPS'),
            # Poisson anchors
            'poisson_p_hit'        : _safe(row, 'poisson_p_hit'),
            'roll14_poisson_p_hit' : _safe(row, 'roll14_poisson_p_hit'),  # new v4
            # Career context (display only)
            'career_ba'            : _safe(row, 'career_ba'),
            'career_babip'         : _safe(row, 'career_babip'),
            # Statcast
            'sc_xba'               : _safe(row, 'sc_xba'),
            'sc_hard_hit_pct'      : _safe(row, 'sc_hard_hit_pct'),
            # Pitcher
            'sp_era'               : _safe(row, 'P_era',      2),
            'sp_whip'              : _safe(row, 'P_whip',     2),
            'sp_hit_rate'          : _safe(row, 'P_hit_rate',  3),
            # Context
            'platoon_adv'          : int(row.get('platoon_adv', 0)),
            'sp_throws_L'          : int(row.get('sp_throws_L', 0)),
            'park_hit_factor'      : round(float(row.get('park_hit_factor', 1.0)), 3),
            'is_home'              : int(row['is_home']),
            # Grading
            'actual_hits'          : None,
            'correct'              : None,
        })

    print(f'\n  Top {len(top_n)} predictions generated')

    # ── 11. Write history ─────────────────────────────────────────────────────
    yday_record  = next((r for r in history['records'] if r['date'] == yesterday_str), None)
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
        'updated'      : datetime.now(timezone.utc).isoformat(),
        'date'         : today_str,
        'model_version': 'v4-xgboost-calibrated',
        'predictions'  : top_n,
        'yesterday'    : {'date': yesterday_str, **yday_summary},
        'alltime'      : alltime,
    }
    with open(MAIN_JSON, 'w') as f:
        json.dump(output, f, indent=2)

    print(f'  Wrote {len(top_n)} predictions -> {MAIN_JSON}')
    if alltime['total'] > 0:
        print(f'  All-time: {alltime["hit_count"]}/{alltime["total"]} '
              f'got a hit ({alltime["hit_rate_pct"]} %)')


if __name__ == '__main__':
    run()
