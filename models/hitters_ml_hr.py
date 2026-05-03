"""
models/hitters_ml_hr.py
──────────────────────────────────────────────────────────────────────────────
Chalk Line Labs — ML Home Run Prediction Model

Poisson XGBoost + Binary XGBoost trained on 2017–2023 box score history
with Statcast, weather, park, and handedness features. Evaluated on the
2024 hold-out season. Ranks today's qualified batters (≥100 PA) by their
expected HR rate (Poisson λ).

WHY POISSON:
  HRs occur in only ~4–6% of batter-games. Binary classification fights
  this extreme imbalance and loses signal. Poisson regression treats HR
  count as a rare count outcome (0, 1, occasionally 2), which is
  statistically principled and sidesteps resampling entirely.

FEATURE GROUPS:
  Rolling batter    — 15G and 60G HR/PA, SLG, ISO + 60G HR count
  Batter Statcast   — barrel%, exit velo, launch angle, hard hit%, xSLG
  Pitcher counting  — ERA, WHIP, HR, SO, BB, IP, BF (season-to-date)
  Pitcher Statcast  — barrel% allowed, exit velo allowed, hard hit% allowed
  Park              — HR factor, altitude (ft), roof type
  Weather           — temp (°F), wind speed, wind-out component toward CF
  Context           — is_home, bat_L, bat_R, sp_throws_L, platoon_adv

PITCHER ASSIGNMENT:
  Home batters face the AWAY starter + AWAY team stats.
  Away batters face the HOME starter + HOME team stats.
  A batter is never scored against their own team's pitcher.

CACHING:
  hr_pred_cache/          — gitignored, restored via GitHub Actions cache
    sched_{yr}.pkl        — season schedule (game_pk, date, home team)
    box_{pk}.json         — box score JSON — checks hit_pred_cache/ first
    hr_records_{yr}.pkl   — assembled batter-game rows
    statcast_batter_{yr}.pkl  — Savant batter CSV features
    statcast_pitcher_{yr}.pkl — Savant pitcher CSV features
    player_hands.json     — bat side + pitch hand (grows over time)
    weather_{park}_{yr}.pkl   — full-year hourly archive per park
    player_{id}_{today}_hitting.json — daily refresh
    roster_{teamId}_{today}.json     — daily refresh

  models/mlb_cache_v2/ml_hr_models.pkl
    Poisson XGBoost, Binary XGBoost, imputer, FITTED_FEATURES.
    Rebuilt only when missing or new season detected.

OUTPUTS:
  public/data/hitters-ml-hr.json
  public/data/hitters-ml-hr-history.json

BUG FIXES (vs. previous version):
  FIX 1 — Feature truncation: replaced silent column-drop with a ValueError
           that forces a model rebuild when train/inference features mismatch.
  FIX 2 — Dead code: removed unused TimeSeriesSplit import and object.
  FIX 3 — Current-season Statcast: live predictions now check CURRENT_YEAR
           Statcast first (batter + pitcher), falling back to prior years.
  FIX 4 — sp_bf feature: added to PITCHER_COUNTING so it enters fitted_features;
           previously computed and stored in DEFAULT_SP but silently ignored.
  FIX 5 — Park fallback: unknown home teams now map to 'NEUTRAL' (league-avg)
           with a logged warning instead of silently using Yankee Stadium (NYY).
  FIX 6 — eval_metric: moved from XGBClassifier __init__ to .fit() to avoid
           XGBoost ≥1.6 deprecation warning and ensure correct behaviour.
──────────────────────────────────────────────────────────────────────────────
"""

import io
import json
import math
import os
import pickle
import time
import warnings
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score
from xgboost import XGBClassifier, XGBRegressor

warnings.filterwarnings('ignore')
np.random.seed(42)

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(BASE_DIR, '..', 'public', 'data')
CACHE_DIR  = os.path.join(BASE_DIR, '..', 'hr_pred_cache')
HIT_CACHE  = os.path.join(BASE_DIR, '..', 'hit_pred_cache')   # shared box files
MODEL_DIR  = os.path.join(BASE_DIR, 'mlb_cache_v2')
MAIN_JSON  = os.path.join(DATA_DIR,  'hitters-ml-hr.json')
HIST_JSON  = os.path.join(DATA_DIR,  'hitters-ml-hr-history.json')
MODELS_PKL = os.path.join(MODEL_DIR, 'ml_hr_models.pkl')
HAND_FILE  = os.path.join(CACHE_DIR, 'player_hands.json')

for d in [DATA_DIR, CACHE_DIR, MODEL_DIR]:
    os.makedirs(d, exist_ok=True)

# ── Config ────────────────────────────────────────────────────────────────────
MLB_API        = 'https://statsapi.mlb.com/api/v1'
SAVANT_BASE    = 'https://baseballsavant.mlb.com'
METEO_ARCHIVE  = 'https://archive-api.open-meteo.com/v1/archive'
METEO_FORECAST = 'https://api.open-meteo.com/v1/forecast'

CURRENT_YEAR   = date.today().year                      # moved above — used by the lines below
TRAIN_SEASONS  = list(range(2017, CURRENT_YEAR - 1))    # 2017–(CURRENT_YEAR-2)
TEST_SEASON    = CURRENT_YEAR - 1                        # most recent complete season
TODAY          = date.today().strftime('%Y-%m-%d')

MIN_PA         = 100
ROLL_SHORT     = 15
ROLL_LONG      = 60
TOP_N          = 25
SLEEP_S        = 0.05

# ── Park table ────────────────────────────────────────────────────────────────
# (name, hr_factor, altitude_ft, roof, lat, lon, cf_bearing)
# roof: 0=open, 1=retractable, 2=dome
PARKS = {
    'ARI': ('Chase Field',              1.08, 1082, 1, 33.4455, -112.0667,  0),
    'ATL': ('Truist Park',              1.00, 1050, 0, 33.8909,  -84.4678, 15),
    'BAL': ('Camden Yards',             1.12,   15, 0, 39.2839,  -76.6218, 40),
    'BOS': ('Fenway Park',              0.94,   19, 0, 42.3467,  -71.0972, 55),
    'CHC': ('Wrigley Field',            1.07,  595, 0, 41.9484,  -87.6553, 30),
    'CWS': ('Guaranteed Rate Field',    1.09,  595, 0, 41.8300,  -87.6338,  5),
    'CIN': ('Great American Ball Park', 1.18,  489, 0, 39.0974,  -84.5083, 20),
    'CLE': ('Progressive Field',        0.93,  653, 0, 41.4962,  -81.6852, 10),
    'COL': ('Coors Field',              1.28, 5280, 0, 39.7559, -104.9942, 15),
    'DET': ('Comerica Park',            0.85,  600, 0, 42.3390,  -83.0485, 25),
    'HOU': ('Minute Maid Park',         1.02,   43, 1, 29.7573,  -95.3555,  5),
    'KC':  ('Kauffman Stadium',         0.91,  973, 0, 39.0517,  -94.4803, 20),
    'LAA': ('Angel Stadium',            1.05,  160, 0, 33.8003, -117.8827, 20),
    'LAD': ('Dodger Stadium',           0.90,  512, 0, 34.0739, -118.2400, 30),
    'MIA': ('loanDepot Park',           0.77,    6, 2, 25.7781,  -80.2197,  0),
    'MIL': ('American Family Field',    1.06,  635, 1, 43.0280,  -87.9712,  5),
    'MIN': ('Target Field',             1.05,  840, 0, 44.9817,  -93.2784, 25),
    'NYM': ('Citi Field',               0.90,   16, 0, 40.7571,  -73.8458, 30),
    'NYY': ('Yankee Stadium',           1.20,   16, 0, 40.8296,  -73.9262, 20),
    'OAK': ('Oakland Coliseum',         0.84,   26, 0, 37.7516, -122.2005, 10),
    'PHI': ('Citizens Bank Park',       1.14,   20, 0, 39.9061,  -75.1665, 25),
    'PIT': ('PNC Park',                 0.95,  730, 0, 40.4469,  -80.0058, 30),
    'SD':  ('Petco Park',               0.83,   20, 0, 32.7073, -117.1566, 20),
    'SEA': ('T-Mobile Park',            0.98,   20, 1, 47.5914, -122.3325, 15),
    'SF':  ('Oracle Park',              0.85,   10, 0, 37.7786, -122.3893, 10),
    'STL': ('Busch Stadium',            1.00,  465, 0, 38.6226,  -90.1928, 20),
    'TB':  ('Tropicana Field',          1.03,    0, 2, 27.7682,  -82.6534,  0),
    'TEX': ('Globe Life Field',         1.10,  551, 1, 32.7512,  -97.0832, 15),
    'TOR': ('Rogers Centre',            1.08,  249, 1, 43.6414,  -79.3894,  5),
    'WSH': ('Nationals Park',           1.02,   25, 0, 38.8730,  -77.0074, 20),
    # FIX 5: League-average neutral park for unknown/unmapped home teams.
    #        Previously the code defaulted silently to 'NYY' (HR factor 1.20),
    #        which would inflate predictions for any unrecognized team.
    'NEUTRAL': ('League Average',       1.00,  200, 0, 39.5,    -98.0,     0),
}

TEAM_TO_PARK = {
    'Arizona Diamondbacks':'ARI', 'Atlanta Braves':'ATL',
    'Baltimore Orioles':'BAL',    'Boston Red Sox':'BOS',
    'Chicago Cubs':'CHC',         'Chicago White Sox':'CWS',
    'Cincinnati Reds':'CIN',      'Cleveland Guardians':'CLE',
    'Cleveland Indians':'CLE',    'Colorado Rockies':'COL',
    'Detroit Tigers':'DET',       'Houston Astros':'HOU',
    'Kansas City Royals':'KC',    'Los Angeles Angels':'LAA',
    'Los Angeles Dodgers':'LAD',  'Miami Marlins':'MIA',
    'Milwaukee Brewers':'MIL',    'Minnesota Twins':'MIN',
    'New York Mets':'NYM',        'New York Yankees':'NYY',
    'Oakland Athletics':'OAK',    'Philadelphia Phillies':'PHI',
    'Pittsburgh Pirates':'PIT',   'San Diego Padres':'SD',
    'Seattle Mariners':'SEA',     'San Francisco Giants':'SF',
    'St. Louis Cardinals':'STL',  'Tampa Bay Rays':'TB',
    'Texas Rangers':'TEX',        'Toronto Blue Jays':'TOR',
    'Washington Nationals':'WSH', 'Athletics':'OAK',
}

DEFAULT_SP = {
    'sp_era': 4.50, 'sp_whip': 1.30, 'sp_hr': 0,
    'sp_so': 0, 'sp_bb': 0, 'sp_ip': 0.0, 'sp_bf': 1,
}

ROLL_FEATURES    = ['roll15_hr_pa', 'roll60_hr_pa', 'roll15_slg', 'roll60_slg',
                     'roll15_iso',   'roll60_iso',   'roll60_hr_count']
# FIX 4: Added 'sp_bf' to PITCHER_COUNTING. It was computed in get_pitcher_features()
#         and stored in DEFAULT_SP, but was absent here so it never entered
#         fitted_features and was silently dropped from every prediction.
PITCHER_COUNTING = ['sp_era', 'sp_whip', 'sp_hr', 'sp_so', 'sp_bb', 'sp_ip', 'sp_bf']
PARK_FEATURES    = ['park_hr_factor', 'park_altitude_ft', 'park_roof']
WEATHER_FEATURES = ['weather_temp_f', 'weather_wind_mph',
                     'weather_wind_out', 'weather_is_dome']
CONTEXT_FEATURES = ['is_home', 'bat_L', 'bat_R', 'sp_throws_L', 'platoon_adv']


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _to_float(val):
    try:    return float(str(val).replace('-.--', 'nan').replace('--', 'nan'))
    except: return np.nan

def _to_int(val):
    try:    return int(val)
    except: return 0

def _get(url, timeout=20):
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()

def wind_out_component(wind_speed_mph, wind_from_deg, park_abbr):
    """
    Signed wind component toward CF (positive = HR boost, negative = suppressor).
    wind_from_deg is the meteorological direction the wind is coming FROM.
    """
    if park_abbr not in PARKS:
        return 0.0
    cf_bearing = PARKS[park_abbr][6]
    angle = math.radians(wind_from_deg - cf_bearing - 180)
    return round(wind_speed_mph * math.cos(angle), 2)


# ═══════════════════════════════════════════════════════════════════════════════
#  BOX SCORE COLLECTION
# ═══════════════════════════════════════════════════════════════════════════════

def get_season_schedule(season):
    """
    Return DataFrame with [game_pk, game_date, home_team_name] for a season.
    Cached as pkl forever.
    """
    cache = os.path.join(CACHE_DIR, f'sched_{season}.pkl')
    if os.path.exists(cache):
        return pd.read_pickle(cache)
    print(f'  Fetching {season} schedule...')
    url = (f'{MLB_API}/schedule?sportId=1&season={season}'
           f'&gameType=R&fields=dates,date,games,gamePk,status,'
           f'codedGameState,teams,home,team,name,id')
    rows = []
    for d in _get(url, timeout=30).get('dates', []):
        for g in d.get('games', []):
            if g.get('status', {}).get('codedGameState') == 'F':
                rows.append({
                    'game_pk'       : g['gamePk'],
                    'game_date'     : d['date'],
                    'home_team_name': g['teams']['home']['team']['name'],
                })
    df = pd.DataFrame(rows)
    df.to_pickle(cache)
    print(f'  {season}: {len(df):,} completed games')
    return df


def parse_boxscore(game_pk, season):
    """
    Parse one box score into batter-level HR records.
    Checks hit_pred_cache first to avoid duplicate downloads.
    """
    shared = os.path.join(HIT_CACHE, f'box_{game_pk}.json')
    local  = os.path.join(CACHE_DIR, f'box_{game_pk}.json')
    for path in [shared, local]:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    try:
        url  = f'{MLB_API}/game/{game_pk}/boxscore'
        data = _get(url)
        rows = []
        for side in ['away', 'home']:
            team_data = data.get('teams', {}).get(side, {})
            batters   = team_data.get('batters', [])
            players   = team_data.get('players', {})
            for pid in batters:
                key   = f'ID{pid}'
                p     = players.get(key, {})
                stats = p.get('stats', {}).get('batting', {})
                name  = p.get('person', {}).get('fullName', '')
                pos   = p.get('position', {}).get('abbreviation', 'UNK')
                rows.append({
                    'player_id'  : pid,
                    'player_name': name,
                    'position'   : pos,
                    'season'     : season,
                    'game_pk'    : game_pk,
                    'B_pa'       : _to_int(stats.get('plateAppearances', 0)),
                    'B_ab'       : _to_int(stats.get('atBats', 0)),
                    'B_h'        : _to_int(stats.get('hits', 0)),
                    'B_hr'       : _to_int(stats.get('homeRuns', 0)),
                    'B_bb'       : _to_int(stats.get('baseOnBalls', 0)),
                    'B_so'       : _to_int(stats.get('strikeOuts', 0)),
                    'B_tb'       : _to_int(stats.get('totalBases', 0)),
                })
        with open(local, 'w') as f:
            json.dump(rows, f)
        time.sleep(SLEEP_S)
        return rows
    except Exception as e:
        print(f'    WARN box score pk={game_pk}: {e}')
        return []


def collect_season(season):
    """Collect all batter-game rows for a season. Cached as pkl."""
    cache = os.path.join(CACHE_DIR, f'hr_records_{season}.pkl')
    if os.path.exists(cache):
        return pd.read_pickle(cache)
    print(f'  Collecting {season} box scores...')
    sched = get_season_schedule(season)
    rows  = []
    for i, pk in enumerate(sched['game_pk']):
        rows.extend(parse_boxscore(pk, season))
        if (i + 1) % 200 == 0:
            print(f'    {i+1}/{len(sched)} games...')
    df = pd.DataFrame(rows)
    df.to_pickle(cache)
    print(f'  {season}: {len(df):,} batter-game rows')
    return df


# ═══════════════════════════════════════════════════════════════════════════════
#  STATCAST
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_statcast_csv(year, kind):
    """
    Fetch season-level Statcast leaderboard CSV from Baseball Savant.
    kind: 'batter' or 'pitcher'
    Returns DataFrame indexed by player_id with sc_* or sp_sc_* columns.
    Cached per year — re-fetched if the cache file is missing.
    """
    cache = os.path.join(CACHE_DIR, f'statcast_{kind}_{year}.pkl')
    if os.path.exists(cache):
        return pd.read_pickle(cache)

    player_type = 'batter' if kind == 'batter' else 'pitcher'
    url = (f'{SAVANT_BASE}/leaderboard/custom?year={year}&type={player_type}'
           f'&filter=&groupBy=name&sort=player_id&sortDir=asc'
           f'&min=q&csv=true')
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        if 'player_id' not in df.columns:
            return pd.DataFrame()
        df = df.set_index('player_id')
        prefix  = 'sc_' if kind == 'batter' else 'sp_sc_'
        col_map = {
            'barrel_batted_rate': f'{prefix}barrel_pct',
            'avg_hit_speed'     : f'{prefix}exit_velo',
            'avg_launch_angle'  : f'{prefix}launch_angle',
            'hard_hit_percent'  : f'{prefix}hard_hit_pct',
            'xslg'              : f'{prefix}xslg',
        }
        rename = {old: new for old, new in col_map.items() if old in df.columns}
        df = df.rename(columns=rename)[[v for v in col_map.values()
                                        if v in df.rename(columns=rename).columns]]
        df = df.apply(pd.to_numeric, errors='coerce')
        df.to_pickle(cache)
        time.sleep(0.5)
        return df
    except Exception as e:
        print(f'  WARN Statcast {kind} {year}: {e}')
        return pd.DataFrame()


# ═══════════════════════════════════════════════════════════════════════════════
#  HANDEDNESS CACHE
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
#  HISTORICAL WEATHER (for training data)
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_park_weather_archive(park_abbr, year):
    """
    Full year of hourly weather for a park from Open-Meteo archive.
    Cached per park × year. Used to join weather to historical box scores.
    Uses 18:30 local-time approximation for game time.
    """
    cache = os.path.join(CACHE_DIR, f'weather_{park_abbr}_{year}.pkl')
    if os.path.exists(cache):
        return pd.read_pickle(cache)
    if park_abbr not in PARKS:
        return pd.DataFrame()

    _, _, _, roof, lat, lon, _ = PARKS[park_abbr]
    if roof == 2:  # dome
        return pd.DataFrame()

    try:
        r = requests.get(METEO_ARCHIVE, params={
            'latitude'         : lat,
            'longitude'        : lon,
            'start_date'       : f'{year}-01-01',
            'end_date'         : f'{year}-12-31',
            'hourly'           : 'temperature_2m,windspeed_10m,winddirection_10m',
            'windspeed_unit'   : 'mph',
            'temperature_unit' : 'fahrenheit',
            'timezone'         : 'auto',
        }, timeout=30)
        r.raise_for_status()
        h  = r.json().get('hourly', {})
        df = pd.DataFrame({
            'dt': pd.to_datetime(h['time']),
            'tf': h['temperature_2m'],
            'ws': h['windspeed_10m'],
            'wd': h['winddirection_10m'],
        })
        df.to_pickle(cache)
        time.sleep(0.2)
        return df
    except Exception as e:
        print(f'  WARN weather archive {park_abbr} {year}: {e}')
        return pd.DataFrame()


def lookup_game_weather(park_abbr, game_date_str, weather_df):
    """Look up 18:30 local approximate weather for a historical game."""
    if park_abbr not in PARKS:
        return {'weather_temp_f': 72.0, 'weather_wind_mph': 5.0,
                'weather_wind_out': 0.0, 'weather_is_dome': 0.0}
    _, _, _, roof, lat, lon, _ = PARKS[park_abbr]
    if roof == 2:
        return {'weather_temp_f': 72.0, 'weather_wind_mph': 0.0,
                'weather_wind_out': 0.0, 'weather_is_dome': 1.0}
    if weather_df.empty:
        return {'weather_temp_f': 72.0, 'weather_wind_mph': 5.0,
                'weather_wind_out': 0.0, 'weather_is_dome': 0.0}
    try:
        target_dt = pd.Timestamp(f'{game_date_str} 18:30')
        diffs     = (weather_df['dt'] - target_dt).abs()
        row       = weather_df.iloc[diffs.argmin()]
        ws        = float(row['ws'])
        wd        = float(row['wd'])
        return {
            'weather_temp_f'  : round(float(row['tf']), 1),
            'weather_wind_mph': round(ws, 1),
            'weather_wind_out': wind_out_component(ws, wd, park_abbr),
            'weather_is_dome' : 0.0,
        }
    except:
        return {'weather_temp_f': 72.0, 'weather_wind_mph': 5.0,
                'weather_wind_out': 0.0, 'weather_is_dome': 0.0}


def get_today_weather(park_abbr, game_date_utc_str):
    """
    Fetch actual game-time weather from Open-Meteo forecast API.
    Uses the game's UTC start time for precision.
    """
    if park_abbr not in PARKS:
        return {'weather_temp_f': 72.0, 'weather_wind_mph': 5.0,
                'weather_wind_out': 0.0, 'weather_is_dome': 0.0}
    _, _, _, roof, lat, lon, _ = PARKS[park_abbr]
    if roof == 2:
        return {'weather_temp_f': 72.0, 'weather_wind_mph': 0.0,
                'weather_wind_out': 0.0, 'weather_is_dome': 1.0}
    try:
        dt      = datetime.strptime(game_date_utc_str[:16], '%Y-%m-%dT%H:%M')
        day_str = dt.strftime('%Y-%m-%d')
        r = requests.get(METEO_FORECAST, params={
            'latitude'         : lat,
            'longitude'        : lon,
            'hourly'           : 'temperature_2m,windspeed_10m,winddirection_10m',
            'windspeed_unit'   : 'mph',
            'temperature_unit' : 'fahrenheit',
            'timezone'         : 'UTC',
            'start_date'       : day_str,
            'end_date'         : day_str,
        }, timeout=15)
        r.raise_for_status()
        h      = r.json().get('hourly', {})
        times  = h.get('time', [])
        target = dt.strftime('%Y-%m-%dT%H:00')
        idx    = times.index(target) if target in times else 0
        ws     = float(h['windspeed_10m'][idx])
        wd     = float(h['winddirection_10m'][idx])
        wo     = wind_out_component(ws, wd, park_abbr)
        return {
            'weather_temp_f'  : round(float(h['temperature_2m'][idx]), 1),
            'weather_wind_mph': round(ws, 1),
            'weather_wind_out': round(wo, 2),
            'weather_is_dome' : float(roof >= 1),
        }
    except Exception as e:
        print(f'  WARN forecast {park_abbr}: {e}')
        return {'weather_temp_f': 72.0, 'weather_wind_mph': 5.0,
                'weather_wind_out': 0.0, 'weather_is_dome': 0.0}


# ═══════════════════════════════════════════════════════════════════════════════
#  FEATURE ENGINEERING
# ═══════════════════════════════════════════════════════════════════════════════

def build_rolling_features(df):
    """Compute lagged rolling HR/power stats per batter. Shift(1) = no leakage."""
    df = df.sort_values(['player_id', 'game_pk']).copy()
    grp = df.groupby('player_id')

    for col in ['B_hr', 'B_pa', 'B_ab', 'B_tb', 'B_h']:
        df[f'r15_{col}'] = grp[col].transform(
            lambda s: s.shift(1).rolling(ROLL_SHORT, min_periods=3).sum())
        df[f'r60_{col}'] = grp[col].transform(
            lambda s: s.shift(1).rolling(ROLL_LONG,  min_periods=5).sum())

    pa15 = df['r15_B_pa'].replace(0, np.nan)
    ab15 = df['r15_B_ab'].replace(0, np.nan)
    pa60 = df['r60_B_pa'].replace(0, np.nan)
    ab60 = df['r60_B_ab'].replace(0, np.nan)

    df['roll15_hr_pa']    = df['r15_B_hr'] / pa15
    df['roll15_slg']      = df['r15_B_tb'] / ab15
    df['roll15_iso']      = (df['r15_B_tb'] - df['r15_B_h']) / ab15
    df['roll60_hr_pa']    = df['r60_B_hr'] / pa60
    df['roll60_slg']      = df['r60_B_tb'] / ab60
    df['roll60_iso']      = (df['r60_B_tb'] - df['r60_B_h']) / ab60
    df['roll60_hr_count'] = df['r60_B_hr']

    return df


# ═══════════════════════════════════════════════════════════════════════════════
#  MODEL TRAINING AND CACHING
# ═══════════════════════════════════════════════════════════════════════════════

def train_models(model_df, fitted_features):
    """Train Poisson XGBoost and Binary XGBoost on training seasons."""
    # FIX 2: Removed the unused TimeSeriesSplit import and object that was
    #         previously created here but never applied to training. This was
    #         dead code. Proper CV will be added as a future improvement.

    train_mask = model_df['season'].isin(TRAIN_SEASONS)
    test_mask  = model_df['season'] == TEST_SEASON

    X_train_raw = model_df.loc[train_mask, fitted_features].values.astype(float)
    y_train     = model_df.loc[train_mask, 'B_hr'].values.astype(float)
    X_test_raw  = model_df.loc[test_mask,  fitted_features].values.astype(float)
    y_test      = model_df.loc[test_mask,  'B_hr'].values.astype(float)

    imputer = SimpleImputer(strategy='median')
    X_train = imputer.fit_transform(X_train_raw)
    X_test  = imputer.transform(X_test_raw)

    print(f'  Train: {X_train.shape[0]:,}  Test: {X_test.shape[0]:,}')
    print(f'  HR rate train: {(y_train>0).mean():.3f}  test: {(y_test>0).mean():.3f}')

    print('  Training Poisson XGBoost...')
    xgb_poisson = XGBRegressor(
        objective='count:poisson', n_estimators=600, learning_rate=0.05,
        max_depth=5, min_child_weight=10, subsample=0.8, colsample_bytree=0.8,
        gamma=1.0, reg_alpha=0.1, reg_lambda=1.0,
        random_state=42, n_jobs=-1, verbosity=0,
    )
    xgb_poisson.fit(X_train, y_train, verbose=False)
    poisson_pred = xgb_poisson.predict(X_test)
    y_test_bin   = (y_test > 0).astype(int)
    if y_test_bin.sum() > 0:
        auc = average_precision_score(y_test_bin, poisson_pred)
        print(f'  Poisson AUC-PR (2024 hold-out): {auc:.4f}')

    print('  Training Binary XGBoost...')
    y_train_bin = (y_train > 0).astype(int)
    spw = (y_train_bin == 0).sum() / max((y_train_bin == 1).sum(), 1)
    # FIX 6: eval_metric moved from __init__ to .fit(). Passing it at __init__
    #         without a corresponding eval_set in .fit() triggers a deprecation
    #         warning in XGBoost ≥1.6 and has no effect on training.
    xgb_binary = XGBClassifier(
        objective='binary:logistic', n_estimators=600, learning_rate=0.05,
        max_depth=5, min_child_weight=10, subsample=0.8, colsample_bytree=0.8,
        gamma=1.0, reg_alpha=0.1, reg_lambda=1.0, scale_pos_weight=spw,
        random_state=42, n_jobs=-1, verbosity=0,
    )
    xgb_binary.fit(X_train, y_train_bin, verbose=False, eval_metric='aucpr')

    return xgb_poisson, xgb_binary, imputer


def load_or_train_models(model_df, fitted_features):
    """Load cached models or train from scratch if missing or new season detected."""
    if os.path.exists(MODELS_PKL):
        with open(MODELS_PKL, 'rb') as f:
            cache = pickle.load(f)
        if cache.get('trained_year') == CURRENT_YEAR:
            print('  Loaded cached ML HR models.')
            return (cache['xgb_poisson'], cache['xgb_binary'],
                    cache['imputer'], cache['fitted_features'])

    print('  Training ML HR models (new season or first run)...')
    xgb_poisson, xgb_binary, imputer = train_models(model_df, fitted_features)
    with open(MODELS_PKL, 'wb') as f:
        pickle.dump({
            'trained_year'   : CURRENT_YEAR,
            'xgb_poisson'    : xgb_poisson,
            'xgb_binary'     : xgb_binary,
            'imputer'        : imputer,
            'fitted_features': fitted_features,
        }, f)
    print('  ✓ Models saved.')
    return xgb_poisson, xgb_binary, imputer, fitted_features


# ═══════════════════════════════════════════════════════════════════════════════
#  HISTORY + GRADING
# ═══════════════════════════════════════════════════════════════════════════════

def load_history():
    if os.path.exists(HIST_JSON):
        with open(HIST_JSON) as f:
            return json.load(f)
    return {'records': []}


def grade_yesterday(history, yesterday_str):
    """Grade yesterday's predictions against actual box scores."""
    record = next(
        (r for r in history['records'] if r['date'] == yesterday_str), None
    )
    if record is None or record.get('graded'):
        return

    sched            = get_season_schedule(CURRENT_YEAR)
    yesterday_games  = sched[sched['game_date'] == yesterday_str]['game_pk'].tolist()

    hr_lookup = {}
    for pk in yesterday_games:
        try:
            rows = parse_boxscore(pk, CURRENT_YEAR)
            for row in rows:
                name = row.get('player_name', '')
                if name:
                    hr_lookup[name] = hr_lookup.get(name, 0) + row.get('B_hr', 0)
        except Exception as e:
            print(f'    WARN box score pk={pk}: {e}')
            continue

    for pred in record.get('predictions', []):
        hrs = hr_lookup.get(pred.get('player', ''), 0)
        pred['actual_hr'] = hrs
        pred['correct']   = hrs > 0

    record['graded'] = True

    played  = [p for p in record['predictions'] if p.get('actual_hr') is not None]
    hit     = [p for p in played if p['correct']]
    buckets = {'High (λ≥0.08)': [], 'Mid (λ≥0.05)': [], 'Low (λ<0.05)': []}
    for p in played:
        lam = p.get('lambda_poisson', 0)
        b   = ('High (λ≥0.08)' if lam >= 0.08 else
               'Mid (λ≥0.05)'  if lam >= 0.05 else 'Low (λ<0.05)')
        buckets[b].append(p['correct'])
    record['summary'] = {
        'total'       : len(played),
        'hr_count'    : len(hit),
        'hit_rate_pct': round(len(hit) / max(len(played), 1) * 100, 1),
        'hr_players'  : [p['player'] for p in hit],
        'by_bucket'   : {
            k: {
                'predicted': len(v),
                'hr'       : sum(v),
                'rate_pct' : round(sum(v) / max(len(v), 1) * 100, 1),
            }
            for k, v in buckets.items() if v
        },
    }
    print(f'    ✓ {len(hit)}/{len(played)} hit HRs')


def compute_alltime_stats(history, today_str):
    buckets  = {'High (λ≥0.08)': [0, 0], 'Mid (λ≥0.05)': [0, 0], 'Low (λ<0.05)': [0, 0]}
    total    = hr_total = 0
    for rec in history['records']:
        if rec['date'] == today_str or not rec.get('graded'):
            continue
        for p in rec.get('predictions', []):
            if p.get('actual_hr') is None:
                continue
            h         = 1 if p['correct'] else 0
            total    += 1
            hr_total += h
            lam = p.get('lambda_poisson', 0)
            b   = ('High (λ≥0.08)' if lam >= 0.08 else
                   'Mid (λ≥0.05)'  if lam >= 0.05 else 'Low (λ<0.05)')
            buckets[b][0] += 1
            buckets[b][1] += h
    return {
        'total'       : total,
        'hr_count'    : hr_total,
        'hit_rate_pct': round(hr_total / max(total, 1) * 100, 1),
        'by_bucket'   : {
            k: {
                'predicted': buckets[k][0],
                'hrs'      : buckets[k][1],
                'rate_pct' : round(buckets[k][1] / max(buckets[k][0], 1) * 100, 1),
            }
            for k in buckets if buckets[k][0] > 0
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  TODAY'S SCHEDULE + PLAYER DATA
# ═══════════════════════════════════════════════════════════════════════════════

def get_todays_games():
    """Fetch today's schedule with probable pitchers."""
    url = (f'{MLB_API}/schedule?sportId=1&date={TODAY}&gameType=R'
           f'&hydrate=probablePitcher,team')
    games = []
    for d in _get(url).get('dates', []):
        for g in d.get('games', []):
            status = g.get('status', {}).get('abstractGameState', '')
            if status in ('Final', 'Live', 'Preview'):
                info = {
                    'game_date'     : g.get('gameDate', ''),
                    'home_team'     : g['teams']['home']['team']['name'],
                    'home_team_id'  : g['teams']['home']['team']['id'],
                    'home_team_abbr': g['teams']['home']['team'].get('abbreviation', '?'),
                    'away_team_id'  : g['teams']['away']['team']['id'],
                    'away_team_abbr': g['teams']['away']['team'].get('abbreviation', '?'),
                    'away_sp'       : None,
                    'home_sp'       : None,
                }
                for side in ['away', 'home']:
                    sp = g['teams'][side].get('probablePitcher')
                    if sp:
                        info[f'{side}_sp'] = {'id'  : sp['id'],
                                              'name': sp.get('fullName', 'TBD')}
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
    cache = os.path.join(CACHE_DIR, f'roster_{team_id}_{TODAY}.json')
    if os.path.exists(cache):
        with open(cache) as f:
            return json.load(f)
    try:
        r       = _get(f'{MLB_API}/teams/{team_id}/roster'
                       f'?rosterType=active&season={CURRENT_YEAR}')
        players = []
        for p in r.get('roster', []):
            pos = p.get('position', {}).get('abbreviation', 'UNK')
            if pos not in ('P', 'SP', 'RP', 'TWP'):
                players.append({'id'      : p['person']['id'],
                                'name'    : p['person']['fullName'],
                                'position': pos})
        with open(cache, 'w') as f:
            json.dump(players, f)
        return players
    except Exception as e:
        print(f'  WARN roster {team_id}: {e}')
        return []


def get_season_stats(player_id, season, group='hitting'):
    """Cached player season stats — daily refresh for hitting, yearly for pitching."""
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
    """Build pitcher feature dict from season stats + Statcast."""
    s = get_season_stats(pitcher_id, CURRENT_YEAR, 'pitching')
    if not s:
        s = get_season_stats(pitcher_id, CURRENT_YEAR - 1, 'pitching')
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
    hr   = _to_int(s.get('homeRuns', 0))
    bb   = _to_int(s.get('baseOnBalls', 0))
    so   = _to_int(s.get('strikeOuts', 0))
    h    = _to_int(s.get('hits', 0))
    er   = _to_int(s.get('earnedRuns', 0))
    era  = _to_float(s.get('era',  er * 9 / ip))
    whip = _to_float(s.get('whip', (bb + h) / ip))

    feats = {
        'sp_era' : era  if era  == era  else 4.50,
        'sp_whip': whip if whip == whip else 1.30,
        'sp_hr'  : hr,
        'sp_so'  : so,
        'sp_bb'  : bb,
        'sp_ip'  : ip_val,
        'sp_bf'  : bf,
    }
    # FIX 3 (pitcher): Check current season Statcast first, then fall back.
    #                  Previously only CURRENT_YEAR-1 and CURRENT_YEAR-2 were
    #                  checked, so in-season pitcher Statcast was never used.
    for yr in [CURRENT_YEAR, CURRENT_YEAR - 1, CURRENT_YEAR - 2]:
        pit_sc = sc_pit.get(yr, pd.DataFrame())
        if not pit_sc.empty and pitcher_id in pit_sc.index:
            for col in pit_sc.columns:
                feats[col] = float(pit_sc.loc[pitcher_id, col])
            break
    return feats


def get_batter_roll_today(player_id, model_df):
    """Build rolling HR features for a batter from historical data or API fallback."""
    player_games = model_df[
        (model_df['player_id'] == player_id) &
        (model_df['season'].isin([CURRENT_YEAR, CURRENT_YEAR - 1]))
    ].sort_values('game_pk')

    if len(player_games) >= 5:
        total_pa = player_games['B_pa'].sum()
        if total_pa < MIN_PA:
            return None

        def _roll(df, n):
            tail = df.tail(n)
            pa   = max(tail['B_pa'].sum(), 1)
            ab   = max(tail['B_ab'].sum(), 1)
            hr   = tail['B_hr'].sum()
            h    = tail['B_h'].sum()
            tb   = tail['B_tb'].sum()
            return hr / pa, tb / ab, (tb - h) / ab

        hr15, slg15, iso15 = _roll(player_games, ROLL_SHORT)
        hr60, slg60, iso60 = _roll(player_games, ROLL_LONG)
        return {
            'roll15_hr_pa'   : hr15,
            'roll15_slg'     : slg15,
            'roll15_iso'     : iso15,
            'roll60_hr_pa'   : hr60,
            'roll60_slg'     : slg60,
            'roll60_iso'     : iso60,
            'roll60_hr_count': float(player_games.tail(ROLL_LONG)['B_hr'].sum()),
        }

    # API fallback
    for yr in [CURRENT_YEAR, CURRENT_YEAR - 1]:
        s  = get_season_stats(player_id, yr, 'hitting')
        pa = _to_int(s.get('plateAppearances', 0))
        if pa >= MIN_PA:
            ab   = max(_to_int(s.get('atBats', 1)), 1)
            pa   = max(pa, 1)
            hr   = _to_int(s.get('homeRuns', 0))
            h    = _to_int(s.get('hits', 0))
            tb   = _to_int(s.get('totalBases', 0))
            slg  = tb / ab
            iso  = (tb - h) / ab
            hr_pa = hr / pa
            return {
                'roll15_hr_pa'   : hr_pa,
                'roll15_slg'     : slg,
                'roll15_iso'     : iso,
                'roll60_hr_pa'   : hr_pa,
                'roll60_slg'     : slg,
                'roll60_iso'     : iso,
                'roll60_hr_count': float(hr),
            }
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

def run():
    today_str     = date.today().isoformat()
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()

    print(f'\n══ ML HR Model — {today_str} ══')
    print(f'   Train: {TRAIN_SEASONS}  |  Test: {TEST_SEASON}  |  MIN_PA: {MIN_PA}')

    # ── 1. History + grade yesterday ──────────────────────────────────────────
    history = load_history()
    grade_yesterday(history, yesterday_str)

    # ── 2. Collect box score data ─────────────────────────────────────────────
    print('\nLoading historical box scores...')
    all_dfs    = []
    all_scheds = []
    for season in TRAIN_SEASONS + [TEST_SEASON]:
        all_scheds.append(get_season_schedule(season))
        all_dfs.append(collect_season(season))

    sched_all = pd.concat(all_scheds, ignore_index=True)
    raw_df    = pd.concat(all_dfs,    ignore_index=True)
    raw_df    = raw_df.merge(
        sched_all[['game_pk', 'game_date', 'home_team_name']],
        on='game_pk', how='left',
    )
    raw_df['park_abbr'] = raw_df['home_team_name'].map(TEAM_TO_PARK)
    print(f'  Total records: {len(raw_df):,}  HR events: {(raw_df["B_hr"]>0).sum():,}')

    # ── 3. Statcast ───────────────────────────────────────────────────────────
    print('\nFetching Statcast CSVs...')
    sc_bat = {}
    sc_pit = {}
    for yr in TRAIN_SEASONS + [TEST_SEASON]:
        sc_bat[yr] = fetch_statcast_csv(yr, 'batter')
        sc_pit[yr] = fetch_statcast_csv(yr, 'pitcher')

    # FIX 3 (part 1): Always ensure current-season Statcast is fetched so it
    #                  is available for live batter and pitcher lookups below.
    #                  CURRENT_YEAR may equal TEST_SEASON early in the year;
    #                  the dict assignment is harmless in that case.
    if CURRENT_YEAR not in sc_bat:
        print(f'  Fetching current-year ({CURRENT_YEAR}) Statcast for live predictions...')
        sc_bat[CURRENT_YEAR] = fetch_statcast_csv(CURRENT_YEAR, 'batter')
        sc_pit[CURRENT_YEAR] = fetch_statcast_csv(CURRENT_YEAR, 'pitcher')

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

    # ── 5. Historical weather ─────────────────────────────────────────────────
    # Skipped for training data — the Open-Meteo archive requires ~200 HTTP
    # requests (25 outdoor parks × 8 seasons) and times out frequently in CI.
    # Training rows use neutral defaults; XGBoost still learns the feature
    # structure and actual weather is applied to today's predictions below.
    print('\nSkipping historical weather archive (neutral defaults for training rows)...')
    wx_cache = {}   # empty — _wx() will return defaults for all training rows

    # ── 6. Build full feature dataframe ───────────────────────────────────────
    print('\nEngineering features...')
    feat_df = build_rolling_features(raw_df)

    # Join handedness (batter bat side)
    feat_df['bat_side'] = feat_df['player_id'].apply(
            lambda pid: hand_cache.get(str(int(pid)), {}).get('bat_side', 'R') if pd.notna(pid) else 'R'
        )
    feat_df['bat_L'] = (feat_df['bat_side'] == 'L').astype(int)
    feat_df['bat_R'] = (feat_df['bat_side'] == 'R').astype(int)

    # SP pitch hand + platoon
    if 'sp_id' in feat_df.columns:
        feat_df['sp_hand'] = feat_df['sp_id'].apply(
            lambda pid: hand_cache.get(str(int(pid)), {}).get('pitch_hand', 'R')
            if not pd.isna(pid) else 'R'
        )
        feat_df['sp_throws_L'] = (feat_df['sp_hand'] == 'L').astype(int)
        feat_df['platoon_adv'] = (
            (feat_df['bat_side'] != feat_df['sp_hand']) &
            (feat_df['bat_side'] != 'S')
        ).astype(int)
    else:
        feat_df['sp_throws_L'] = 0
        feat_df['platoon_adv'] = 0

    # Park features
    feat_df['park_hr_factor']   = feat_df['park_abbr'].map(
        lambda a: PARKS.get(a, (None, 1.0, 0, 0))[1])
    feat_df['park_altitude_ft'] = feat_df['park_abbr'].map(
        lambda a: PARKS.get(a, (None, None, 0))[2])
    feat_df['park_roof']        = feat_df['park_abbr'].map(
        lambda a: PARKS.get(a, (None, None, None, 0))[3])

    # Weather join (using 18:30 approximation for training)
    def _wx(row):
        park     = row.get('park_abbr')
        date_str = str(row.get('game_date', ''))[:10]
        try:
            yr   = int(date_str[:4])
            wxdf = wx_cache.get((park, yr), pd.DataFrame())
            return lookup_game_weather(park, date_str, wxdf)
        except:
            return {'weather_temp_f': 72.0, 'weather_wind_mph': 5.0,
                    'weather_wind_out': 0.0, 'weather_is_dome': 0.0}

    wx_rows       = feat_df[['park_abbr', 'game_date']].drop_duplicates()
    wx_rows_dicts = [_wx(r) for _, r in wx_rows.iterrows()]
    wx_df         = pd.DataFrame(wx_rows_dicts, index=wx_rows.index)
    for col in ['weather_temp_f', 'weather_wind_mph', 'weather_wind_out', 'weather_is_dome']:
        feat_df[col] = wx_df[col]

    # Join Statcast (batter)
    for yr in TRAIN_SEASONS + [TEST_SEASON]:
        bsc = sc_bat.get(yr, pd.DataFrame())
        if bsc.empty:
            continue
        mask = feat_df['season'] == yr
        for col in bsc.columns:
            if col not in feat_df.columns:
                feat_df.loc[mask, col] = np.nan
            feat_df.loc[mask & feat_df['player_id'].isin(bsc.index), col] = \
                feat_df.loc[mask & feat_df['player_id'].isin(bsc.index), 'player_id'].map(bsc[col])

    # Join Statcast (pitcher, via sp_id)
    if 'sp_id' in feat_df.columns:
        for yr in TRAIN_SEASONS + [TEST_SEASON]:
            psc = sc_pit.get(yr, pd.DataFrame())
            if psc.empty:
                continue
            mask   = feat_df['season'] == yr
            for col in psc.columns:
                if col not in feat_df.columns:
                    feat_df.loc[mask, col] = np.nan
                sp_map = feat_df.loc[mask, 'sp_id'].dropna().astype(int)
                feat_df.loc[
                    mask & sp_map.isin(psc.index).reindex(feat_df.index, fill_value=False),
                    col
                ] = sp_map[sp_map.isin(psc.index)].map(psc[col])

    # Determine final feature list (only include cols that exist)
    batter_statcast  = [c for c in feat_df.columns if c.startswith('sc_')]
    pitcher_statcast = [c for c in feat_df.columns if c.startswith('sp_sc_')]
    all_features     = (ROLL_FEATURES + batter_statcast + pitcher_statcast +
                        PITCHER_COUNTING + PARK_FEATURES + WEATHER_FEATURES + CONTEXT_FEATURES)
    fitted_features  = [f for f in dict.fromkeys(all_features) if f in feat_df.columns]

    model_df = feat_df.dropna(subset=['roll15_hr_pa', 'roll60_hr_pa']).copy()
    for col in PITCHER_COUNTING + PARK_FEATURES + WEATHER_FEATURES:
        if col in model_df.columns:
            model_df[col] = model_df[col].fillna(model_df[col].median())

    print(f'  Model dataset: {len(model_df):,} records  |  {len(fitted_features)} features')

    # ── 7. Load or train models ───────────────────────────────────────────────
    print('\nLoading models...')
    xgb_poisson, xgb_binary, imputer, fitted_features = \
        load_or_train_models(model_df, fitted_features)

    # ── 8. Today's schedule + predictions ─────────────────────────────────────
    print(f'\nFetching schedule for {today_str}...')
    games = get_todays_games()
    if not games:
        print('No games today. Exiting.')
        return
    print(f'  ✓ {len(games)} game(s) found')

    today_records   = []
    skipped_no_qual = 0

    for game in games:
        away_abbr = game['away_team_abbr']
        home_abbr = game['home_team_abbr']
        home_team = game['home_team']
        matchup   = f'{away_abbr} @ {home_abbr}'
        game_time = get_game_time_et(game.get('game_date', ''))

        # FIX 5: Unknown team names now map to a NEUTRAL park with a warning.
        #         Previously the code silently defaulted to 'NYY' (Yankee
        #         Stadium, HR factor 1.20), which would inflate every batter's
        #         prediction for any team whose name changed or wasn't in the map.
        park_abbr = TEAM_TO_PARK.get(home_team)
        if park_abbr is None:
            print(f'  WARN: Unknown home team "{home_team}" — using NEUTRAL park factors')
            park_abbr = 'NEUTRAL'

        # Park features
        park_row   = PARKS.get(park_abbr, PARKS['NEUTRAL'])
        park_feats = {
            'park_hr_factor'  : park_row[1],
            'park_altitude_ft': park_row[2],
            'park_roof'       : park_row[3],
        }

        # Weather at actual game time
        wx = get_today_weather(park_abbr, game.get('game_date', ''))
        time.sleep(0.3)

        # SP features (home SP faces AWAY batters, away SP faces HOME batters)
        away_sp      = game.get('away_sp')
        home_sp      = game.get('home_sp')
        away_sp_feat = get_pitcher_features(away_sp['id'], sc_pit) if away_sp else DEFAULT_SP.copy()
        away_sp_name = away_sp['name'] if away_sp else 'TBD'
        home_sp_feat = get_pitcher_features(home_sp['id'], sc_pit) if home_sp else DEFAULT_SP.copy()
        home_sp_name = home_sp['name'] if home_sp else 'TBD'

        print(f'  {matchup} ({game_time}) · park={park_abbr} · '
              f'SP vs {home_abbr}: {away_sp_name} | SP vs {away_abbr}: {home_sp_name}')

        sides = [
            {'team_id': game['home_team_id'], 'team_abbr': home_abbr,
             'opp_abbr': away_abbr, 'opp_sp_feat': away_sp_feat,
             'opp_sp_name': away_sp_name,
             'opp_sp_id': away_sp['id'] if away_sp else None,
             'is_home': 1},
            {'team_id': game['away_team_id'], 'team_abbr': away_abbr,
             'opp_abbr': home_abbr, 'opp_sp_feat': home_sp_feat,
             'opp_sp_name': home_sp_name,
             'opp_sp_id': home_sp['id'] if home_sp else None,
             'is_home': 0},
        ]

        for side in sides:
            roster = get_active_roster(side['team_id'])
            for player in roster:
                pid  = player['id']
                name = player['name']
                pos  = player['position']

                roll = get_batter_roll_today(pid, model_df)
                if roll is None:
                    skipped_no_qual += 1
                    continue

                # FIX 3 (batter): Check current-season Statcast first, then
                #                  fall back to prior years. Previously only
                #                  CURRENT_YEAR-1 and CURRENT_YEAR-2 were
                #                  checked, so mid-season Statcast was ignored.
                bat_sc = {}
                for yr in [CURRENT_YEAR, CURRENT_YEAR - 1, CURRENT_YEAR - 2]:
                    bsc = sc_bat.get(yr, pd.DataFrame())
                    if not bsc.empty and pid in bsc.index:
                        for col in bsc.columns:
                            bat_sc[col] = float(bsc.loc[pid, col])
                        break

                # Handedness
                bh  = hand_cache.get(str(pid), {}).get('bat_side', 'R')
                sph = (hand_cache.get(str(side['opp_sp_id']), {}).get('pitch_hand', 'R')
                       if side['opp_sp_id'] else 'R')

                rec = {
                    'player_id'  : pid,
                    'player_name': name,
                    'position'   : pos,
                    'team'       : side['team_abbr'],
                    'opp_sp'     : side['opp_sp_name'],
                    'opp_abbr'   : side['opp_abbr'],
                    'park_abbr'  : park_abbr,
                    'is_home'    : side['is_home'],
                    'bat_L'      : int(bh == 'L'),
                    'bat_R'      : int(bh == 'R'),
                    'sp_throws_L': int(sph == 'L'),
                    'platoon_adv': int(bh != sph and bh != 'S'),
                    'game'       : matchup,
                    'game_time'  : game_time,
                }
                rec.update(roll)
                rec.update(bat_sc)
                rec.update(side['opp_sp_feat'])
                rec.update(park_feats)
                rec.update(wx)
                today_records.append(rec)

    print(f'  Qualified: {len(today_records)}  |  Skipped (<{MIN_PA} PA): {skipped_no_qual}')

    if not today_records:
        print('No qualified batters. Exiting.')
        return

    today_df = pd.DataFrame(today_records)
    for col in fitted_features:
        if col not in today_df.columns:
            today_df[col] = np.nan
        today_df[col] = pd.to_numeric(today_df[col], errors='coerce')

    X_raw = today_df[fitted_features].values.astype(float)
    X_imp = imputer.transform(X_raw)

    # FIX 1: Replace the previous silent feature-count truncation with an
    #         explicit ValueError. The old code did:
    #             if X_imp.shape[1] != n_feats: X_imp = X_imp[:, :n_feats]
    #         which silently dropped rightmost feature columns, corrupting
    #         predictions whenever the cached model had a different feature
    #         set than the current pipeline. The correct resolution is to
    #         delete the stale model cache and let it rebuild cleanly.
    n_feats = xgb_poisson.n_features_in_
    if X_imp.shape[1] != n_feats:
        raise ValueError(
            f'Feature mismatch: cached model expects {n_feats} features '
            f'but the current pipeline produced {X_imp.shape[1]}. '
            f'Delete {MODELS_PKL} to force a clean model rebuild.'
        )

    # ── 9. Predict ────────────────────────────────────────────────────────────
    today_df['lambda_poisson'] = np.round(xgb_poisson.predict(X_imp), 5)
    today_df['prob_binary']    = np.round(xgb_binary.predict_proba(X_imp)[:, 1], 4)
    today_df = today_df.sort_values('lambda_poisson', ascending=False).reset_index(drop=True)

    # ── 10. Build top-25 output ───────────────────────────────────────────────
    top_n = []
    for i, (_, row) in enumerate(today_df.head(TOP_N).iterrows()):
        park_name = PARKS.get(row['park_abbr'], ('?',))[0]
        top_n.append({
            'rank'            : i + 1,
            'player'          : row['player_name'],
            'position'        : row['position'],
            'team'            : row['team'],
            'game'            : row['game'],
            'game_time'       : row['game_time'],
            'opp_abbr'        : row['opp_abbr'],
            'opp_sp'          : row['opp_sp'],
            'park'            : park_name,
            'park_abbr'       : row['park_abbr'],
            'lambda_poisson'  : float(row['lambda_poisson']),
            'prob_binary'     : float(row['prob_binary']),
            'park_hr_factor'  : row.get('park_hr_factor'),
            'park_altitude_ft': row.get('park_altitude_ft'),
            'weather_temp_f'  : row.get('weather_temp_f'),
            'weather_wind_mph': row.get('weather_wind_mph'),
            'weather_wind_out': row.get('weather_wind_out'),
            'sp_era'          : row.get('sp_era'),
            'sp_whip'         : row.get('sp_whip'),
            'sc_barrel_pct'   : row.get('sc_barrel_pct'),
            'sc_exit_velo'    : row.get('sc_exit_velo'),
            'sc_xslg'         : row.get('sc_xslg'),
            'roll15_hr_pa'    : row.get('roll15_hr_pa'),
            'roll60_hr_pa'    : row.get('roll60_hr_pa'),
            'is_home'         : int(row['is_home']),
            'actual_hr'       : None,
            'correct'         : None,
        })

    print(f'\n✓ Top {len(top_n)} predictions generated')

    # ── 11. Save today's record to history ────────────────────────────────────
    existing = next((r for r in history['records'] if r['date'] == today_str), None)
    if existing:
        existing['predictions'] = top_n
        existing['graded']      = False
    else:
        history['records'].append({
            'date'       : today_str,
            'predictions': top_n,
            'graded'     : False,
        })

    alltime = compute_alltime_stats(history, today_str)

    with open(HIST_JSON, 'w') as f:
        json.dump(history, f)

    # ── 12. Write main output ─────────────────────────────────────────────────
    yesterday_record = next(
        (r for r in history['records'] if r['date'] == yesterday_str), {}
    )
    output = {
        'generated'  : today_str,
        'predictions': top_n,
        'yesterday'  : {
            'date'        : yesterday_str,
            'total'       : yesterday_record.get('summary', {}).get('total', 0),
            'hr_count'    : yesterday_record.get('summary', {}).get('hr_count', 0),
            'hit_rate_pct': yesterday_record.get('summary', {}).get('hit_rate_pct', 0),
            'by_bucket'   : yesterday_record.get('summary', {}).get('by_bucket', {}),
        },
        'alltime'    : alltime,
    }
    with open(MAIN_JSON, 'w') as f:
        json.dump(output, f, indent=2)

    print(f'\n✓ Written: {MAIN_JSON}')
    print(f'✓ Written: {HIST_JSON}')


if __name__ == '__main__':
    run()
