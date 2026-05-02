"""
models/hitters_ml_hit.py
──────────────────────────────────────────────────────────────────────────────
Chalk Line Labs — ML Hit Probability Model

Based on Alceo & Henriques (2020):
  "Beat the Streak: Prediction of MLB Base Hits Using Machine Learning"

Trains an ensemble of MLP, Logistic Regression, and Random Forest on
2022–2024 box score history, evaluates on the 2025 hold-out season,
then predicts today's qualified batters vs their probable starters.

Primary sort: MLP probability (paper's best model, 81% pick ratio).
Ensemble: average of MLP, LR, and RF probabilities.

FEATURES (26 total):
  Batter short-term  : roll7 BA, OBP, SLG, OPS, H/g, BB/g, SO/g, HR/g
  Batter long-term   : roll30 BA, OBP, SLG, OPS, H/g, BB/g, SO/g, HR/g
  Opposing pitcher   : ERA, WHIP, SO, BB, H, HR, BF, IP
  Context            : is_home, batting_order (default 5 pre-lineup)

QUALIFICATION:
  Batter must have ≥ 50 plate appearances in the current season
  (falls back to prior season early in the year).

SP FALLBACK:
  When no starter is announced, defaults to league-average pitcher
  stats (ERA 4.50, WHIP 1.30, all counts 0).

CACHING:
  hit_pred_cache/          box scores, schedules, player stats (gitignored)
    schedule_{year}.json   all game PKs for a season
    box_{gamePk}.json      parsed box score (one per game)
    records_{year}.pkl     assembled batter-game rows for a season
    player_{id}_{today}_hitting.json   today's season stats (refreshes daily)
    player_{id}_{year}_pitching.json   SP season stats (refreshes yearly)
    roster_{teamId}_{today}.json       active roster (refreshes daily)

  models/mlb_cache_v2/
    ml_hit_models.pkl      trained models + preprocessing objects
                           rebuilt only when missing or new season detected

OUTPUTS:
  public/data/hitters-ml-hit.json
  public/data/hitters-ml-history.json
──────────────────────────────────────────────────────────────────────────────
"""

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
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import MinMaxScaler

warnings.filterwarnings('ignore')
np.random.seed(42)

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
DATA_DIR      = os.path.join(BASE_DIR, '..', 'public', 'data')
CACHE_DIR     = os.path.join(BASE_DIR, '..', 'hit_pred_cache')
MODEL_DIR     = os.path.join(BASE_DIR, 'mlb_cache_v2')
MAIN_JSON     = os.path.join(DATA_DIR,  'hitters-ml-hit.json')
HIST_JSON     = os.path.join(DATA_DIR,  'hitters-ml-hit-history.json')
MODELS_PKL    = os.path.join(MODEL_DIR, 'ml_hit_models.pkl')

for d in [DATA_DIR, CACHE_DIR, MODEL_DIR]:
    os.makedirs(d, exist_ok=True)

# ── Config ────────────────────────────────────────────────────────────────────
MLB_API        = 'https://statsapi.mlb.com/api/v1'
CURRENT_YEAR   = date.today().year
TRAIN_SEASONS  = [2022, 2023, 2024]
TEST_SEASON    = 2025
TOP_N          = 25
MIN_PA         = 50
ROLL_SHORT     = 7
ROLL_LONG      = 30
SLEEP_S        = 0.05

TODAY = date.today().strftime('%Y-%m-%d')

BATTER_ROLL_FEATURES = [
    'roll7_BA',   'roll7_OBP',  'roll7_SLG',  'roll7_OPS',
    'roll7_B_h',  'roll7_B_bb', 'roll7_B_so', 'roll7_B_hr',
    'roll30_BA',  'roll30_OBP', 'roll30_SLG', 'roll30_OPS',
    'roll30_B_h', 'roll30_B_bb','roll30_B_so','roll30_B_hr',
]
PITCHER_FEATURES = ['P_era','P_whip','P_so','P_bb','P_h','P_hr','P_bf','P_ip']
CONTEXT_FEATURES = ['is_home', 'batting_order']
ALL_FEATURES     = BATTER_ROLL_FEATURES + PITCHER_FEATURES + CONTEXT_FEATURES

DEFAULT_SP = {'P_era':4.50,'P_whip':1.30,'P_so':0,'P_bb':0,
              'P_h':0,'P_hr':0,'P_bf':1,'P_ip':0.0}


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _to_float(val):
    try:
        return float(str(val).replace('-.--','nan').replace('--','nan'))
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

    for side in ['away', 'home']:
        opp_side = 'home' if side == 'away' else 'away'
        is_home  = 1 if side == 'home' else 0

        team_obj = teams_data.get(side, {})
        opp_obj  = teams_data.get(opp_side, {})

        team_name = team_obj.get('team', {}).get('name', 'Unknown')
        opp_name  = opp_obj.get('team', {}).get('name', 'Unknown')

        # ── Opposing starter stats ────────────────────────────────────────────
        opp_pitchers = opp_obj.get('pitchers', [])
        opp_players  = opp_obj.get('players', {})
        starter_stats = {}
        if opp_pitchers:
            sp_key  = f'ID{opp_pitchers[0]}'
            sp_stat = opp_players.get(sp_key, {}).get('stats', {}).get('pitching', {})
            ip_str  = str(sp_stat.get('inningsPitched', '0.0'))
            try:
                parts  = ip_str.split('.')
                ip_val = float(parts[0]) + float(parts[1] if len(parts) > 1 else 0) / 3
            except:
                ip_val = 0.0
            starter_stats = {
                'P_ip'  : ip_val,
                'P_h'   : _to_int(sp_stat.get('hits', 0)),
                'P_er'  : _to_int(sp_stat.get('earnedRuns', 0)),
                'P_bb'  : _to_int(sp_stat.get('baseOnBalls', 0)),
                'P_so'  : _to_int(sp_stat.get('strikeOuts', 0)),
                'P_hr'  : _to_int(sp_stat.get('homeRuns', 0)),
                'P_era' : _to_float(sp_stat.get('era', np.nan)),
                'P_whip': _to_float(sp_stat.get('whip', np.nan)),
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
                'game_pk'      : game_pk,
                'season'       : season,
                'player_id'    : pid,
                'player_name'  : players.get(key, {}).get('person', {}).get('fullName', ''),
                'team'         : team_name,
                'opponent'     : opp_name,
                'is_home'      : is_home,
                'batting_order': order_pos.get(pid, 9),
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
    Caches result as a pickle for near-instant future loads.
    """
    cache_pkl = os.path.join(CACHE_DIR, f'records_{season}.pkl')
    if os.path.exists(cache_pkl):
        df = pd.read_pickle(cache_pkl)
        print(f'  {season}: loaded {len(df):,} records from cache')
        return df

    print(f'  {season}: fetching box scores...')
    pks = get_season_game_pks(season)
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
#  FEATURE ENGINEERING
# ═══════════════════════════════════════════════════════════════════════════════

def build_rolling_features(df):
    """
    Compute lagged rolling averages for each batter across their game history.
    Shift(1) ensures no data leakage (current game is excluded from its own features).
    """
    df = df.sort_values(['player_id', 'game_pk']).copy()
    grp = df.groupby('player_id')

    for col in ['B_h','B_ab','B_bb','B_so','B_hr','B_pa','B_tb']:
        df[f'roll7_{col}']  = grp[col].transform(
            lambda s: s.shift(1).rolling(ROLL_SHORT, min_periods=2).mean())
        df[f'roll30_{col}'] = grp[col].transform(
            lambda s: s.shift(1).rolling(ROLL_LONG, min_periods=5).mean())

    df['roll7_BA']   = df['roll7_B_h']  / df['roll7_B_ab'].replace(0, np.nan)
    df['roll7_OBP']  = (df['roll7_B_h'] + df['roll7_B_bb']) / df['roll7_B_pa'].replace(0, np.nan)
    df['roll7_SLG']  = df['roll7_B_tb'] / df['roll7_B_ab'].replace(0, np.nan)
    df['roll7_OPS']  = df['roll7_OBP']  + df['roll7_SLG']

    df['roll30_BA']  = df['roll30_B_h']  / df['roll30_B_ab'].replace(0, np.nan)
    df['roll30_OBP'] = (df['roll30_B_h'] + df['roll30_B_bb']) / df['roll30_B_pa'].replace(0, np.nan)
    df['roll30_SLG'] = df['roll30_B_tb'] / df['roll30_B_ab'].replace(0, np.nan)
    df['roll30_OPS'] = df['roll30_OBP']  + df['roll30_SLG']

    return df


def random_under_sample(X, y, random_state=42):
    """Downsample majority class to match minority class size (no imbalanced-learn)."""
    rng = np.random.default_rng(random_state)
    classes, counts = np.unique(y, return_counts=True)
    min_count = counts.min()
    keep = []
    for cls in classes:
        idx = np.where(y == cls)[0]
        keep.append(rng.choice(idx, size=min_count, replace=False))
    idx_all = np.concatenate(keep)
    rng.shuffle(idx_all)
    return X[idx_all], y[idx_all]


# ═══════════════════════════════════════════════════════════════════════════════
#  MODEL TRAINING AND CACHING
# ═══════════════════════════════════════════════════════════════════════════════

def train_models(model_df):
    """
    Train MLP, LR, and RF on TRAIN_SEASONS data.
    Evaluates on TEST_SEASON hold-out.
    Returns fitted models + preprocessing objects.
    """
    train_mask = model_df['season'].isin(TRAIN_SEASONS)
    test_mask  = model_df['season'] == TEST_SEASON

    X_train_raw = model_df.loc[train_mask, ALL_FEATURES].values.astype(float)
    y_train     = model_df.loc[train_mask, 'hit'].values
    X_test_raw  = model_df.loc[test_mask,  ALL_FEATURES].values.astype(float)
    y_test      = model_df.loc[test_mask,  'hit'].values

    print(f'  Train: {len(X_train_raw):,} samples  Test: {len(X_test_raw):,} samples')

    # Impute → scale → undersample
    imputer        = SimpleImputer(strategy='median')
    X_train_imp    = imputer.fit_transform(X_train_raw)
    X_test_imp     = imputer.transform(X_test_raw)

    scaler         = MinMaxScaler()
    X_train_scaled = scaler.fit_transform(X_train_imp)
    X_test_scaled  = scaler.transform(X_test_imp)

    X_bal, y_bal   = random_under_sample(X_train_scaled, y_train)
    print(f'  After RUS: {len(X_bal):,} balanced training samples')

    print('  Training MLP...')
    mlp = MLPClassifier(
        hidden_layer_sizes=(128, 64, 32), activation='relu', solver='adam',
        alpha=0.001, learning_rate='adaptive', max_iter=300,
        random_state=42, early_stopping=True, validation_fraction=0.1,
    )
    mlp.fit(X_bal, y_bal)

    print('  Training Logistic Regression...')
    lr = LogisticRegression(C=1.0, max_iter=1000, solver='lbfgs', random_state=42)
    lr.fit(X_bal, y_bal)

    print('  Training Random Forest...')
    rf = RandomForestClassifier(
        n_estimators=200, max_depth=10, min_samples_leaf=20,
        random_state=42, n_jobs=-1,
    )
    rf.fit(X_bal, y_bal)

    # Quick test-set accuracy
    for name, model in [('MLP', mlp), ('LR', lr), ('RF', rf)]:
        acc = (model.predict(X_test_scaled) == y_test).mean()
        print(f'  {name} test accuracy: {acc:.4f}')

    return mlp, lr, rf, imputer, scaler


def load_or_train_models(model_df):
    """
    Load cached models if they exist and match the current season.
    Otherwise train from scratch and cache.
    """
    if os.path.exists(MODELS_PKL):
        with open(MODELS_PKL, 'rb') as f:
            cache = pickle.load(f)
        if cache.get('trained_year') == CURRENT_YEAR:
            print('  Loaded cached ML models.')
            return (cache['mlp'], cache['lr'], cache['rf'],
                    cache['imputer'], cache['scaler'])
        else:
            print(f'  New season detected ({CURRENT_YEAR}) — retraining...')

    print('  Training models (first run — this takes a few minutes)...')
    mlp, lr, rf, imputer, scaler = train_models(model_df)

    with open(MODELS_PKL, 'wb') as f:
        pickle.dump({
            'trained_year': CURRENT_YEAR,
            'mlp':      mlp,
            'lr':       lr,
            'rf':       rf,
            'imputer':  imputer,
            'scaler':   scaler,
        }, f)
    print('  ✓ Models trained and cached.')
    return mlp, lr, rf, imputer, scaler


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
                'game_pk'     : g['gamePk'],
                'game_date'   : g.get('gameDate', ''),
                'away_team'   : g['teams']['away']['team']['name'],
                'home_team'   : g['teams']['home']['team']['name'],
                'away_team_id': g['teams']['away']['team']['id'],
                'home_team_id': g['teams']['home']['team']['id'],
                'away_team_abbr': g['teams']['away']['team'].get('abbreviation','?'),
                'home_team_abbr': g['teams']['home']['team'].get('abbreviation','?'),
                'away_sp': None,
                'home_sp': None,
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
        url = f'{MLB_API}/teams/{team_id}/roster?rosterType=active&season={CURRENT_YEAR}'
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
    """
    Season-to-date stats for a player.
    Hitting stats cached daily (refresh each morning).
    Pitching stats cached per season (stable enough).
    """
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


def get_pitcher_features(pitcher_id):
    """Build pitcher feature dict from season-to-date stats."""
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

    return {
        'P_era' : era  if era  == era  else 4.50,
        'P_whip': whip if whip == whip else 1.30,
        'P_so': so, 'P_bb': bb, 'P_h': h,
        'P_hr': hr, 'P_bf': bf, 'P_ip': ip_val,
    }


def build_batter_features(player_id, model_df):
    """
    Build rolling feature dict for a batter from historical model_df.
    Falls back to API season stats if fewer than 5 historical games exist.
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
                'BA':  h / ab,  'OBP': (h + bb) / pa,
                'SLG': tb / ab, 'OPS': (h + bb) / pa + tb / ab,
                'h': h/ng, 'bb': bb/ng, 'so': so/ng, 'hr': hr/ng,
            }
        r7  = _roll(player_games, ROLL_SHORT)
        r30 = _roll(player_games, ROLL_LONG)
        return {
            'roll7_BA'  : r7['BA'],   'roll7_OBP' : r7['OBP'],
            'roll7_SLG' : r7['SLG'],  'roll7_OPS' : r7['OPS'],
            'roll7_B_h' : r7['h'],    'roll7_B_bb': r7['bb'],
            'roll7_B_so': r7['so'],   'roll7_B_hr': r7['hr'],
            'roll30_BA' : r30['BA'],  'roll30_OBP': r30['OBP'],
            'roll30_SLG': r30['SLG'], 'roll30_OPS': r30['OPS'],
            'roll30_B_h': r30['h'],   'roll30_B_bb':r30['bb'],
            'roll30_B_so':r30['so'],  'roll30_B_hr':r30['hr'],
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
    ba  = h / ab;       obp = (h + bb) / pa
    slg = tb / ab;      ops = obp + slg
    return {
        'roll7_BA' : ba,   'roll7_OBP' : obp,  'roll7_SLG' : slg,  'roll7_OPS' : ops,
        'roll7_B_h': h/gp, 'roll7_B_bb': bb/gp,'roll7_B_so': so/gp,'roll7_B_hr': hr/gp,
        'roll30_BA': ba,   'roll30_OBP': obp,   'roll30_SLG': slg,  'roll30_OPS': ops,
        'roll30_B_h':h/gp,'roll30_B_bb':bb/gp, 'roll30_B_so':so/gp,'roll30_B_hr':hr/gp,
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
            params={'sportId':1,'date':yesterday_str},
            timeout=20,
        ).json()
    except Exception as e:
        print(f'    WARN: could not fetch box scores: {e}')
        return

    game_pks = [
        g['gamePk']
        for d in sched_meta.get('dates', [])
        for g in d.get('games', [])
    ]

    hit_lookup = {}
    for pk in game_pks:
        try:
            box = requests.get(f'{MLB_API}/game/{pk}/boxscore', timeout=20).json()
            for side in ['home', 'away']:
                for _pid, pdata in (box.get('teams', {})
                                       .get(side, {})
                                       .get('players', {}).items()):
                    name = pdata.get('person', {}).get('fullName', '')
                    hits = int(pdata.get('stats', {}).get('batting', {}).get('hits', 0))
                    if name:
                        hit_lookup[name] = max(hit_lookup.get(name, 0), hits)
            time.sleep(SLEEP_S)
        except Exception as e:
            print(f'    WARN box score pk={pk}: {e}')
            continue

    for pred in record.get('predictions', []):
        hits = hit_lookup.get(pred.get('player', ''), 0)
        pred['actual_hits'] = hits
        pred['correct']     = hits > 0

    record['graded'] = True

    played = [p for p in record['predictions'] if p.get('actual_hits') is not None]
    hit    = [p for p in played if p['correct']]
    buckets = {'75%+': [], '65-74%': [], '55-64%': [], '<55%': []}
    for p in played:
        prob = p.get('p_mlp', 0)
        b = '75%+' if prob >= 0.75 else '65-74%' if prob >= 0.65 else '55-64%' if prob >= 0.55 else '<55%'
        buckets[b].append(p['correct'])
    record['summary'] = {
        'total':        len(played),
        'hit_count':    len(hit),
        'hit_rate_pct': round(len(hit) / max(len(played), 1) * 100, 1),
        'hit_players':  [p['player'] for p in hit],
        'by_bucket':    {
            k: {'predicted': len(v), 'hits': sum(v),
                'rate_pct': round(sum(v) / max(len(v), 1) * 100, 1)}
            for k, v in buckets.items() if v
        },
    }
    print(f'    ✓ {len(hit)}/{len(played)} got a hit')


def compute_alltime_stats(history, today_str):
    buckets = {'75%+': [0,0], '65-74%': [0,0], '55-64%': [0,0], '<55%': [0,0]}
    total = hit_total = 0
    for rec in history['records']:
        if rec['date'] == today_str or not rec.get('graded'):
            continue
        for p in rec.get('predictions', []):
            if p.get('actual_hits') is None:
                continue
            h = 1 if p['correct'] else 0
            total += 1; hit_total += h
            prob = p.get('p_mlp', 0)
            b = '75%+' if prob >= 0.75 else '65-74%' if prob >= 0.65 else '55-64%' if prob >= 0.55 else '<55%'
            buckets[b][0] += 1; buckets[b][1] += h
    return {
        'total': total, 'hit_count': hit_total,
        'hit_rate_pct': round(hit_total / max(total, 1) * 100, 1),
        'by_bucket': {
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

    print(f'\n══ ML Hit Model — {today_str} ══')

    # ── 1. Load history and grade yesterday ───────────────────────────────────
    history = load_history()
    grade_yesterday(history, yesterday_str)

    # ── 2. Load or fetch box score data ───────────────────────────────────────
    print('\nLoading historical box scores...')
    all_dfs = []
    for season in TRAIN_SEASONS + [TEST_SEASON]:
        all_dfs.append(collect_season(season))

    raw_df   = pd.concat(all_dfs, ignore_index=True)
    model_df = build_rolling_features(raw_df)
    model_df = model_df.dropna(subset=BATTER_ROLL_FEATURES).copy()
    for col in PITCHER_FEATURES:
        if col in model_df.columns:
            model_df[col] = model_df[col].fillna(model_df[col].median())
    print(f'  Model dataset: {len(model_df):,} batter-game records')

    # ── 3. Load or train models ───────────────────────────────────────────────
    print('\nLoading models...')
    mlp, lr, rf, imputer, scaler = load_or_train_models(model_df)

    # ── 4. Today's schedule ───────────────────────────────────────────────────
    print(f'\nFetching schedule for {today_str}...')
    games = get_todays_games()
    if not games:
        print('No games today. Exiting.')
        return
    print(f'  ✓ {len(games)} game(s) found')

    # ── 5. Build feature vectors for today's batters ──────────────────────────
    print('\nBuilding today\'s predictions...')
    today_records = []
    skipped_no_qual = 0

    for game in games:
        away_abbr = game['away_team_abbr']
        home_abbr = game['home_team_abbr']
        matchup   = f'{away_abbr} @ {home_abbr}'
        game_time = get_game_time_et(game.get('game_date', ''))

        # Pitcher features (SP for each side)
        away_sp_feat = get_pitcher_features(game['away_sp']['id']) if game.get('away_sp') else DEFAULT_SP.copy()
        away_sp_name = game['away_sp']['name'] if game.get('away_sp') else 'TBD'
        home_sp_feat = get_pitcher_features(game['home_sp']['id']) if game.get('home_sp') else DEFAULT_SP.copy()
        home_sp_name = game['home_sp']['name'] if game.get('home_sp') else 'TBD'

        print(f'  {matchup} — SP vs {home_abbr}: {away_sp_name} | SP vs {away_abbr}: {home_sp_name}')

        # Score each side
        # Home batters face AWAY SP; Away batters face HOME SP
        sides = [
            {
                'team_id':      game['home_team_id'],
                'team_abbr':    home_abbr,
                'opp_abbr':     away_abbr,
                'opp_sp_feat':  away_sp_feat,
                'opp_sp_name':  away_sp_name,
                'is_home':      1,
            },
            {
                'team_id':      game['away_team_id'],
                'team_abbr':    away_abbr,
                'opp_abbr':     home_abbr,
                'opp_sp_feat':  home_sp_feat,
                'opp_sp_name':  home_sp_name,
                'is_home':      0,
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

                rec = {
                    'player_id'  : pid,
                    'player_name': name,
                    'position'   : pos,
                    'team'       : side['team_abbr'],
                    'opponent'   : side['opp_abbr'],
                    'opp_sp'     : side['opp_sp_name'],
                    'is_home'    : side['is_home'],
                    'batting_order': 5,   # pre-game default (middle of order)
                    'game'       : matchup,
                    'game_time'  : game_time,
                }
                rec.update(roll)
                rec.update(side['opp_sp_feat'])
                today_records.append(rec)

    print(f'  Qualified batters: {len(today_records)}  |  Skipped (<{MIN_PA} PA): {skipped_no_qual}')

    if not today_records:
        print('No qualified batters found. Exiting.')
        return

    today_df = pd.DataFrame(today_records)

    # Ensure all features present and numeric
    for col in ALL_FEATURES:
        if col not in today_df.columns:
            today_df[col] = np.nan
        today_df[col] = pd.to_numeric(today_df[col], errors='coerce')

    # Apply same imputer → scaler fitted on training data
    X_raw = today_df[ALL_FEATURES].values.astype(float)
    X_imp = imputer.transform(X_raw)
    X     = scaler.transform(X_imp)

    # ── 6. Predict ────────────────────────────────────────────────────────────
    mlp_proba = mlp.predict_proba(X)[:, 1]
    lr_proba  = lr.predict_proba(X)[:, 1]
    rf_proba  = rf.predict_proba(X)[:, 1]
    ens_proba = (mlp_proba + lr_proba + rf_proba) / 3

    today_df['p_mlp'] = np.round(mlp_proba, 4)
    today_df['p_lr']  = np.round(lr_proba,  4)
    today_df['p_rf']  = np.round(rf_proba,  4)
    today_df['p_ens'] = np.round(ens_proba,  4)

    today_df = today_df.sort_values('p_mlp', ascending=False).reset_index(drop=True)

    # ── 7. Build top-25 output records ────────────────────────────────────────
    top_n = []
    for i, (_, row) in enumerate(today_df.head(TOP_N).iterrows()):
        top_n.append({
            'rank'        : i + 1,
            'player'      : row['player_name'],
            'position'    : row['position'],
            'team'        : row['team'],
            'game'        : row['game'],
            'game_time'   : row['game_time'],
            'opposing_team': row['opponent'],
            'opp_sp'      : row['opp_sp'],
            # Probabilities
            'p_mlp'       : float(row['p_mlp']),
            'p_lr'        : float(row['p_lr']),
            'p_rf'        : float(row['p_rf']),
            'p_ens'       : float(row['p_ens']),
            # Key rolling features
            'roll7_ba'    : round(float(row['roll7_BA']),  3) if not np.isnan(row['roll7_BA'])  else None,
            'roll30_ops'  : round(float(row['roll30_OPS']),3) if not np.isnan(row['roll30_OPS']) else None,
            'roll7_ops'   : round(float(row['roll7_OPS']), 3) if not np.isnan(row['roll7_OPS'])  else None,
            'roll30_ba'   : round(float(row['roll30_BA']), 3) if not np.isnan(row['roll30_BA'])  else None,
            # SP stats
            'sp_era'      : round(float(row['P_era']),  2) if not np.isnan(row['P_era'])  else None,
            'sp_whip'     : round(float(row['P_whip']), 2) if not np.isnan(row['P_whip']) else None,
            'is_home'     : int(row['is_home']),
            # Grading
            'actual_hits' : None,
            'correct'     : None,
        })

    print(f'\n✓ Top {len(top_n)} predictions generated')

    # ── 8. Persist today's record in history ──────────────────────────────────
    today_record_preds = [
        {'rank': p['rank'], 'player': p['player'], 'team': p['team'],
         'p_mlp': p['p_mlp'], 'p_ens': p['p_ens'],
         'actual_hits': None, 'correct': None}
        for p in top_n
    ]
    existing = next((r for r in history['records'] if r['date'] == today_str), None)
    if existing:
        existing['predictions'] = today_record_preds
        existing['graded']      = False
    else:
        history['records'].append({
            'date': today_str, 'graded': False,
            'predictions': today_record_preds,
        })
    history['records'].sort(key=lambda r: r['date'], reverse=True)
    save_history(history)

    # ── 9. Stats summaries ────────────────────────────────────────────────────
    yday_record  = next((r for r in history['records'] if r['date'] == yesterday_str), None)
    yday_summary = yday_record.get('summary', {}) if yday_record else {}
    alltime      = compute_alltime_stats(history, today_str)

    # ── 10. Write output JSON ─────────────────────────────────────────────────
    output = {
        'updated'    : datetime.now(timezone.utc).isoformat(),
        'date'       : today_str,
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
