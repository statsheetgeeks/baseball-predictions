"""
models/hitters_hr_model.py
──────────────────────────────────────────────────────────────────────────────
Chalk Line Labs — HR Hitter Prediction Model

Scores every batter in today's MLB lineups on HR probability using a
four-factor deterministic model:

  Composite = 0.42 × Batter  +  0.35 × Pitcher Vulnerability
            + 0.15 × Park    +  0.08 × Context (temp/environment)

WEIGHT RATIONALE:
  Batter (42 %)   — ISO, HR/AB, and OPS are the strongest known individual
                    predictors. Park/context are game-level constants that
                    apply identically to every batter in a given game, so
                    player quality must dominate.
  Pitcher (35 %)  — Opponent quality is the second-biggest driver. This
                    component blends starting pitcher (65 %) and team bullpen
                    (35 %) to account for late-game matchups.
  Park (15 %)     — Park HR factors are real and hand-specific, but capped
                    so Coors Field doesn't systematically override batter skill.
  Context (8 %)   — Temperature effects on ball flight are real but small in
                    absolute magnitude relative to the factors above.

PITCHER COMPONENT — DETAIL:
  Combined pitcher score = 0.65 × SP_score + 0.35 × Bullpen_score

  SP_score     : individual SP's HR/9, HR/BF, ERA (see score_pitcher_vuln)
  Bullpen_score: opposing team's aggregate pitching HR/9, HR/BF, ERA
                 (same normalization formula as SP).
                 Team aggregate is a reasonable proxy because relievers
                 now account for 40–50 % of batters faced.

  TBD STARTER RULE (critical fix over previous version):
    When no SP is listed, the prior model returned a hardcoded 50.
    Corrected behaviour: if SP is TBD, pitcher score = 100 % team
    pitching stats.  Team performance always contains more information
    than a generic league-average placeholder.

PITCHER ASSIGNMENT (verified against MLB API structure):
  In a game listed as "AWAY @ HOME":
    • HOME batters face the AWAY team's probable starter
    • AWAY batters face the HOME team's probable starter
  A batter is NEVER scored against their own team's pitcher.
  Both SP stats and team pitching stats come from the OPPOSING team.

OUTPUTS (auto-committed daily by GitHub Actions):
  public/data/hitters-hr-model.json   — today's top-25 predictions + stats
  public/data/hitters-hr-history.json — cumulative daily history + grades
──────────────────────────────────────────────────────────────────────────────
"""

import os
import json
import time
import math
from datetime import date, timedelta, timezone, datetime

import requests

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(BASE_DIR, '..', 'public', 'data')
MAIN_JSON = os.path.join(DATA_DIR, 'hitters-hr-model.json')
HIST_JSON = os.path.join(DATA_DIR, 'hitters-hr-history.json')

os.makedirs(DATA_DIR, exist_ok=True)

MLB_API  = 'https://statsapi.mlb.com/api/v1'
TOP_N    = 25
SLEEP_S  = 0.15
SEASON   = date.today().year
PREV_SEA = SEASON - 1

# ── Composite weights ─────────────────────────────────────────────────────────
# These are the only top-level weights. Sub-component weights within each
# factor are documented inside their respective scoring functions below.
WEIGHTS = {
    'batter':  0.42,
    'pitcher': 0.35,   # internally: 65 % SP + 35 % team bullpen
    'park':    0.15,
    'context': 0.08,
}

# Pitcher sub-blend weights
SP_WEIGHT      = 0.65
BULLPEN_WEIGHT = 0.35

# ── Park data (keyed by MLB home-team ID) ────────────────────────────────────
# hr_L / hr_R : park HR index for LHB / RHB (1.00 = league average).
# lat / lon   : stadium coordinates for Open-Meteo weather lookup.
# roof        : True = retractable or permanent roof (wind/temp irrelevant).
# orientation : compass bearing from home plate to center field (degrees).
PARKS = {
    108: {'name': 'Angel Stadium',            'hr_L': 0.94, 'hr_R': 0.98,
          'lat': 33.800, 'lon': -117.883, 'roof': False, 'orientation': 340},
    109: {'name': 'Chase Field',              'hr_L': 1.00, 'hr_R': 1.03,
          'lat': 33.445, 'lon': -112.067, 'roof': True,  'orientation': 0},
    110: {'name': 'Camden Yards',             'hr_L': 1.07, 'hr_R': 1.03,
          'lat': 39.284, 'lon': -76.622,  'roof': False, 'orientation': 83},
    111: {'name': 'Fenway Park',              'hr_L': 0.93, 'hr_R': 1.04,
          'lat': 42.347, 'lon': -71.097,  'roof': False, 'orientation': 93},
    112: {'name': 'Wrigley Field',            'hr_L': 1.05, 'hr_R': 1.01,
          'lat': 41.948, 'lon': -87.656,  'roof': False, 'orientation': 93},
    113: {'name': 'Great American Ball Park', 'hr_L': 1.16, 'hr_R': 1.14,
          'lat': 39.098, 'lon': -84.507,  'roof': False, 'orientation': 352},
    114: {'name': 'Progressive Field',        'hr_L': 0.96, 'hr_R': 0.98,
          'lat': 41.496, 'lon': -81.685,  'roof': False, 'orientation': 340},
    115: {'name': 'Coors Field',              'hr_L': 1.34, 'hr_R': 1.38,
          'lat': 39.756, 'lon': -104.994, 'roof': False, 'orientation': 335},
    116: {'name': 'Comerica Park',            'hr_L': 0.91, 'hr_R': 0.94,
          'lat': 42.339, 'lon': -83.048,  'roof': False, 'orientation': 27},
    117: {'name': 'Minute Maid Park',         'hr_L': 0.97, 'hr_R': 1.00,
          'lat': 29.757, 'lon': -95.356,  'roof': True,  'orientation': 0},
    118: {'name': 'Kauffman Stadium',         'hr_L': 0.93, 'hr_R': 0.91,
          'lat': 39.051, 'lon': -94.480,  'roof': False, 'orientation': 5},
    119: {'name': 'Dodger Stadium',           'hr_L': 0.99, 'hr_R': 1.03,
          'lat': 34.074, 'lon': -118.240, 'roof': False, 'orientation': 25},
    120: {'name': 'Nationals Park',           'hr_L': 1.01, 'hr_R': 0.97,
          'lat': 38.873, 'lon': -77.007,  'roof': False, 'orientation': 355},
    121: {'name': 'Citi Field',              'hr_L': 0.96, 'hr_R': 0.92,
          'lat': 40.757, 'lon': -73.846,  'roof': False, 'orientation': 358},
    133: {'name': 'Oakland Coliseum',         'hr_L': 0.93, 'hr_R': 0.91,
          'lat': 37.752, 'lon': -122.201, 'roof': False, 'orientation': 200},
    134: {'name': 'PNC Park',                 'hr_L': 0.96, 'hr_R': 0.94,
          'lat': 40.447, 'lon': -80.006,  'roof': False, 'orientation': 100},
    135: {'name': 'Petco Park',              'hr_L': 0.89, 'hr_R': 0.85,
          'lat': 32.707, 'lon': -117.157, 'roof': False, 'orientation': 300},
    136: {'name': 'T-Mobile Park',           'hr_L': 0.93, 'hr_R': 0.89,
          'lat': 47.591, 'lon': -122.333, 'roof': True,  'orientation': 0},
    137: {'name': 'Oracle Park',             'hr_L': 0.85, 'hr_R': 0.80,
          'lat': 37.778, 'lon': -122.389, 'roof': False, 'orientation': 55},
    138: {'name': 'Busch Stadium',           'hr_L': 0.98, 'hr_R': 0.96,
          'lat': 38.623, 'lon': -90.193,  'roof': False, 'orientation': 68},
    139: {'name': 'Tropicana Field',         'hr_L': 1.00, 'hr_R': 0.97,
          'lat': 27.768, 'lon': -82.653,  'roof': True,  'orientation': 0},
    140: {'name': 'Globe Life Field',        'hr_L': 0.96, 'hr_R': 0.99,
          'lat': 32.748, 'lon': -97.084,  'roof': True,  'orientation': 0},
    141: {'name': 'Rogers Centre',           'hr_L': 1.01, 'hr_R': 1.03,
          'lat': 43.641, 'lon': -79.389,  'roof': True,  'orientation': 0},
    142: {'name': 'Target Field',            'hr_L': 0.94, 'hr_R': 0.96,
          'lat': 44.982, 'lon': -93.278,  'roof': False, 'orientation': 320},
    143: {'name': 'Citizens Bank Park',      'hr_L': 1.14, 'hr_R': 1.10,
          'lat': 39.906, 'lon': -75.166,  'roof': False, 'orientation': 62},
    144: {'name': 'Truist Park',             'hr_L': 1.05, 'hr_R': 1.09,
          'lat': 33.891, 'lon': -84.468,  'roof': False, 'orientation': 15},
    145: {'name': 'Guaranteed Rate Field',   'hr_L': 1.02, 'hr_R': 1.04,
          'lat': 41.830, 'lon': -87.634,  'roof': False, 'orientation': 5},
    146: {'name': 'LoanDepot Park',          'hr_L': 0.90, 'hr_R': 0.86,
          'lat': 25.778, 'lon': -80.220,  'roof': True,  'orientation': 0},
    147: {'name': 'Yankee Stadium',          'hr_L': 1.10, 'hr_R': 1.01,
          'lat': 40.829, 'lon': -73.926,  'roof': False, 'orientation': 42},
    158: {'name': 'American Family Field',   'hr_L': 1.08, 'hr_R': 1.04,
          'lat': 43.028, 'lon': -87.971,  'roof': True,  'orientation': 0},
}
PARKS[160] = {**PARKS[133], 'name': 'Sutter Health Park'}  # Sacramento Athletics


# ═══════════════════════════════════════════════════════════════════════════════
#  SCORING ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

def _norm(val, lo, hi):
    """Linearly map val ∈ [lo, hi] → [0, 100], clamped at both ends."""
    if val is None:
        return None
    return max(0.0, min(100.0, (val - lo) / (hi - lo) * 100.0))


def score_batter(stats):
    """
    Batter HR-propensity score (0-100).  Higher = more likely to HR today.

    Sub-component weights (must sum to 100):
      hr_per_ab  40 % — most direct HR rate predictor
      iso        30 % — isolated power = SLG minus AVG
      ops        20 % — overall offensive quality / plate discipline
      slg        10 % — slugging percentage (secondary texture)

    Normalization anchors (league average yields ≈ 45):
      hr_per_ab : 0.000 → 0  |  0.030 (avg) → 46  |  0.065 (elite) → 100
      iso       : 0.050 → 0  |  0.150 (avg) → 40  |  0.300 (elite) → 100
      ops       : 0.600 → 0  |  0.750 (avg) → 38  |  1.000 (elite) → 100
      slg       : 0.300 → 0  |  0.450 (avg) → 50  |  0.600 (elite) → 100

    Returns 38 (slightly below average) when no stats are available for a player.
    """
    comps, wts = [], []

    hr_ab = stats.get('hr_per_ab')
    if hr_ab is not None:
        comps.append(_norm(hr_ab, 0.0, 0.065)); wts.append(40)

    iso = stats.get('iso')
    if iso is not None:
        comps.append(_norm(iso, 0.050, 0.300)); wts.append(30)

    ops = stats.get('ops')
    if ops is not None:
        comps.append(_norm(ops, 0.600, 1.000)); wts.append(20)

    slg = stats.get('slg')
    if slg is not None:
        comps.append(_norm(slg, 0.300, 0.600)); wts.append(10)

    if not comps:
        return 38
    return round(sum(c * w for c, w in zip(comps, wts)) / sum(wts))


def score_pitcher_vuln(stats):
    """
    Single-pitcher or team-aggregate HR-vulnerability score (0-100).
    Higher = more HRs allowed = better matchup for a batter.

    This function is called for BOTH individual SP stats AND team aggregate
    stats (bullpen proxy) — the same normalization applies to both.

    Sub-component weights:
      hr9        45 % — HR per 9 innings (most intuitive HR rate)
      hr_per_bf  35 % — HR per batter faced (granular rate, less IP-sensitive)
      era        20 % — overall ERA (reliable fallback when rate stats are thin)

    Normalization anchors:
      hr9      : 0.50 → 0  |  1.15 (avg) → 43  |  2.00 (bad) → 100
      hr_per_bf: 0.010 → 0  |  0.030 (avg) → 44  |  0.055 (bad) → 100
      era      : 2.00 → 0  |  4.00 (avg) → 50  |  6.00 (bad) → 100

    Returns 50 (league-average vulnerability) when stats are empty.
    In practice this only occurs for the bullpen component when team
    pitching data is unavailable — never for a TBD starter (see
    score_pitcher_combined for that case).
    """
    comps, wts = [], []

    hr9 = stats.get('hr9')
    if hr9 is not None:
        comps.append(_norm(hr9, 0.50, 2.00)); wts.append(45)

    hr_bf = stats.get('hr_per_bf')
    if hr_bf is not None:
        comps.append(_norm(hr_bf, 0.010, 0.055)); wts.append(35)

    era = stats.get('era')
    if era is not None:
        comps.append(_norm(era, 2.00, 6.00)); wts.append(20)

    if not comps:
        return 50
    return round(sum(c * w for c, w in zip(comps, wts)) / sum(wts))


def score_pitcher_combined(sp_stats, team_pitching_stats):
    """
    Combined pitcher vulnerability score (0-100).

    Blending rule:
      65 % (SP_WEIGHT)      — individual starting pitcher
      35 % (BULLPEN_WEIGHT) — opposing team aggregate pitching (bullpen proxy)

    TBD STARTER RULE:
      When sp_stats is empty (starter not yet announced), the previous
      version of this model returned a hardcoded neutral 50.  This was
      inaccurate because a team's actual pitching performance always
      provides more signal than a generic average.

      Corrected behaviour:
        SP is TBD  → pitcher score = 100 % team pitching stats
        SP is known → pitcher score = 65 % SP + 35 % team pitching

    Both sp_stats and team_pitching_stats must always be from the
    OPPOSING team — the caller is responsible for this guarantee.
    """
    bp_score = score_pitcher_vuln(team_pitching_stats)

    if not sp_stats:
        # No announced starter — use team pitching entirely
        return bp_score

    sp_score = score_pitcher_vuln(sp_stats)
    return round(SP_WEIGHT * sp_score + BULLPEN_WEIGHT * bp_score)


def score_park(park, hand, wind_adj_val):
    """
    Park + wind HR-favorability score (0-100).

    Sub-component weights:
      hr_factor  70 % — hand-specific park HR index (stable, data-rich)
      wind_adj   30 % — wind multiplier (variable; neutral 50 for roofed parks)

    Normalization:
      hr_factor: 0.80 → 0  |  1.00 (neutral) → 33  |  1.40 (Coors R) → 100
      wind_adj : 0.85 → 0  |  1.00 (calm)    → 43  |  1.20 (out)     → 100
    """
    factor    = park.get('hr_L', 1.0) if hand == 'L' else park.get('hr_R', 1.0)
    park_comp = _norm(factor, 0.80, 1.40)

    wind_comp = 50.0   # neutral for roofed parks or missing weather data
    if wind_adj_val is not None and not park.get('roof'):
        wind_comp = _norm(wind_adj_val, 0.85, 1.20)

    return round(0.70 * park_comp + 0.30 * wind_comp)


def score_context(park, temp_f):
    """
    Environmental context score (0-100) based on game-time temperature.

    Ball travel increases roughly 1 ft per 10 °F above 60 °F (Alan Nathan).
    Roofed parks receive a fixed 62 (mild climate-control edge).

    Outdoor thresholds:
      < 40 °F  → 18   (severe suppression)
      40–49    → 32
      50–59    → 47
      60–67    → 57   (slightly below neutral)
      68–77    → 68   (favorable)
      78–87    → 75   (very favorable)
      ≥ 88     → 70   (very hot — minor drag at extremes)
    """
    if park.get('roof'):
        return 62
    if temp_f is None:
        return 55   # unknown outdoor conditions
    if temp_f < 40:  return 18
    if temp_f < 50:  return 32
    if temp_f < 60:  return 47
    if temp_f < 68:  return 57
    if temp_f < 78:  return 68
    if temp_f < 88:  return 75
    return 70


def composite(b, p, pk, ctx):
    """
    Weighted composite HR score (0-100).
    Weights: Batter 42 % · Pitcher 35 % · Park 15 % · Context 8 %
    """
    return round(
        WEIGHTS['batter']  * b  +
        WEIGHTS['pitcher'] * p  +
        WEIGHTS['park']    * pk +
        WEIGHTS['context'] * ctx
    )


def confidence(score):
    if score >= 70: return 'high'
    if score >= 55: return 'medium'
    return 'low'


# ═══════════════════════════════════════════════════════════════════════════════
#  DATA FETCHING
# ═══════════════════════════════════════════════════════════════════════════════

def mlb_get(path, params=None):
    r = requests.get(MLB_API + path, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def get_game_time_et(game_date_str):
    """Convert UTC ISO game time to a readable ET string."""
    if not game_date_str:
        return 'TBD'
    try:
        dt_utc = datetime.strptime(game_date_str[:16], '%Y-%m-%dT%H:%M')
        dt_et  = dt_utc - timedelta(hours=4)   # EDT offset
        hour   = dt_et.hour % 12 or 12
        ampm   = 'AM' if dt_et.hour < 12 else 'PM'
        return f'{hour}:{dt_et.minute:02d} {ampm} ET'
    except Exception:
        return 'TBD'


def fetch_weather(lat, lon, game_date_str):
    """
    Fetch hourly temperature and wind at game-time from Open-Meteo.

    Uses timezone='UTC' so the hour index matches the UTC game time from
    the MLB API.  Earlier versions used timezone='auto' which returned
    local-time hours and caused an off-by-several-hours mismatch.
    """
    if not lat:
        return {}
    try:
        dt      = datetime.strptime(game_date_str[:16], '%Y-%m-%dT%H:%M')
        day_str = dt.strftime('%Y-%m-%d')
        r = requests.get(
            'https://api.open-meteo.com/v1/forecast',
            params={
                'latitude':         lat,
                'longitude':        lon,
                'hourly':           'temperature_2m,windspeed_10m,winddirection_10m',
                'windspeed_unit':   'mph',
                'temperature_unit': 'fahrenheit',
                'timezone':         'UTC',
                'start_date':       day_str,
                'end_date':         day_str,
            },
            timeout=12,
        )
        h      = r.json().get('hourly', {})
        times  = h.get('time', [])
        target = dt.strftime('%Y-%m-%dT%H:00')   # UTC hour of first pitch
        idx    = times.index(target) if target in times else 0
        return {
            'temp_f':       round(h['temperature_2m'][idx],   1),
            'wind_mph':     round(h['windspeed_10m'][idx],    1),
            'wind_dir_deg': h['winddirection_10m'][idx],
        }
    except Exception as e:
        print(f'    WARN weather fetch: {e}')
        return {}


def calc_wind_hr_adj(wind_mph, wind_dir, park_orient, roof):
    """
    HR adjustment multiplier from wind direction and speed (range ≈ 0.85–1.20).
    Cosine of angle between wind bearing and outfield bearing gives sign/magnitude.
    """
    if roof or wind_mph < 3:
        return 1.0
    cf_bearing = (park_orient + 180) % 360
    delta = abs(wind_dir - cf_bearing)
    if delta > 180:
        delta = 360 - delta
    return round(max(0.85, min(1.20,
        1.0 + math.cos(math.radians(delta)) * wind_mph * 0.007
    )), 3)


def fetch_batter_stats(pid):
    """
    Season hitting stats for a batter.
    Tries current SEASON; falls back to PREV_SEA if fewer than 20 AB.
    """
    def _pull(season):
        try:
            data = mlb_get(f'/people/{pid}/stats',
                           {'stats': 'season', 'group': 'hitting', 'season': season})
            s  = (data.get('stats', [{}])[0]
                      .get('splits', [{}]) or [{}])[0].get('stat', {})
            ab = int(s.get('atBats') or 0)
            if ab < 20:
                return None
            hr  = int(s.get('homeRuns') or 0)
            slg = float(s.get('slg') or 0)
            avg = float(s.get('avg') or 0)
            ops = float(s.get('ops') or 0)
            return {
                'hr':        hr,
                'ab':        ab,
                'avg':       round(avg, 3),
                'slg':       round(slg, 3),
                'ops':       round(ops, 3),
                'iso':       round(slg - avg, 3),
                'hr_per_ab': round(hr / ab, 4) if ab > 0 else 0,
            }
        except Exception:
            return None
    return _pull(SEASON) or _pull(PREV_SEA) or {}


def fetch_pitcher_stats(pid):
    """
    Season pitching stats for an individual pitcher (SP).
    Tries current SEASON; falls back to PREV_SEA if fewer than 10 BF.
    """
    def _pull(season):
        try:
            data = mlb_get(f'/people/{pid}/stats',
                           {'stats': 'season', 'group': 'pitching', 'season': season})
            s  = (data.get('stats', [{}])[0]
                      .get('splits', [{}]) or [{}])[0].get('stat', {})
            bf = int(s.get('battersFaced') or 0)
            if bf < 10:
                return None
            hrs = int(s.get('homeRuns') or 0)
            return {
                'era':       round(float(s.get('era') or 0), 2),
                'hr9':       round(float(s.get('homeRunsPer9') or 0), 2),
                'whip':      round(float(s.get('whip') or 0), 2),
                'bf':        bf,
                'hr_per_bf': round(hrs / bf, 4) if bf > 0 else 0,
            }
        except Exception:
            return None
    return _pull(SEASON) or _pull(PREV_SEA) or {}


def fetch_team_pitching_stats(team_id):
    """
    Team aggregate season pitching stats — used as the bullpen proxy.

    This provides the 35 % BULLPEN_WEIGHT component of every pitcher score,
    and serves as the FULL pitcher score when the SP is TBD.

    Team aggregate includes all pitchers (starters + relievers).  Using it
    as a bullpen proxy is a simplification: a future version could subtract
    SP contributions to isolate relief stats.  For now, team aggregate is
    stable, always available, and captures organizational pitching quality.

    Tries current SEASON; falls back to PREV_SEA if fewer than 50 BF.
    """
    def _pull(season):
        try:
            data = mlb_get(f'/teams/{team_id}/stats',
                           {'stats': 'season', 'group': 'pitching', 'season': season})
            splits = data.get('stats', [{}])[0].get('splits', [])
            s  = splits[0].get('stat', {}) if splits else {}
            bf = int(s.get('battersFaced') or 0)
            if bf < 50:
                return None
            hrs = int(s.get('homeRuns') or 0)
            return {
                'era':       round(float(s.get('era') or 0), 2),
                'hr9':       round(float(s.get('homeRunsPer9') or 0), 2),
                'hr_per_bf': round(hrs / bf, 4) if bf > 0 else 0,
            }
        except Exception:
            return None
    return _pull(SEASON) or _pull(PREV_SEA) or {}


def fetch_player_hand(pid):
    """Return bat side code ('L', 'R', or 'S') for a player."""
    try:
        data = mlb_get(f'/people/{pid}')
        return data.get('people', [{}])[0].get('batSide', {}).get('code', 'R')
    except Exception:
        return 'R'


# ═══════════════════════════════════════════════════════════════════════════════
#  TEXT GENERATION  (deterministic — no external LLM)
# ═══════════════════════════════════════════════════════════════════════════════

def build_recent_form(bstats):
    parts = []
    hr = bstats.get('hr')
    if hr is not None:
        parts.append(f'{hr} HR this season')
    if bstats.get('hr_per_ab'):
        parts.append(f'HR/AB {bstats["hr_per_ab"]:.3f}')
    if bstats.get('iso'):
        parts.append(f'ISO {bstats["iso"]:.3f}')
    if bstats.get('slg'):
        parts.append(f'SLG {bstats["slg"]:.3f}')
    return ', '.join(parts) if parts else '—'


def build_reasoning(player, bstats, b_score,
                    sp_name, sp_stats, sp_score, bullpen_score, p_score,
                    park_name, pk_score, ctx_score, weather):
    # Batter description
    bd = []
    if bstats.get('iso'):       bd.append(f'ISO {bstats["iso"]:.3f}')
    if bstats.get('hr_per_ab'): bd.append(f'HR/AB {bstats["hr_per_ab"]:.3f}')
    if bstats.get('ops'):       bd.append(f'OPS {bstats["ops"]:.3f}')
    batter_str = ', '.join(bd) if bd else 'limited data this season'

    # Pitcher description
    if sp_stats:
        pd_ = []
        if sp_stats.get('hr9'): pd_.append(f'HR/9 {sp_stats["hr9"]:.2f}')
        if sp_stats.get('era'): pd_.append(f'ERA {sp_stats["era"]:.2f}')
        sp_detail  = f'{sp_name} ({", ".join(pd_) or "limited data"}; SP vuln {sp_score})'
        pit_text   = (f'Faces {sp_detail}; bullpen vuln {bullpen_score}. '
                      f'Combined pitcher score {p_score} '
                      f'({int(SP_WEIGHT*100)}% SP + {int(BULLPEN_WEIGHT*100)}% bullpen).')
    else:
        pit_text = (f'SP not yet announced — pitcher score {p_score} derived entirely '
                    f'from opposing team pitching stats (bullpen vuln {bullpen_score}).')

    s1 = f'{player} posts {batter_str} (batter score {b_score}).'

    env = ''
    if weather and weather.get('temp_f') is not None:
        env = f' At {park_name}: {weather["temp_f"]:.0f}\u00b0F'
        if weather.get('wind_mph', 0) >= 5:
            env += f', wind {weather["wind_mph"]:.0f} mph'
        env += f' (park score {pk_score}, context {ctx_score}).'
    elif pk_score >= 60:
        env = f' {park_name} is a hitter-friendly park for this matchup.'

    return f'{s1} {pit_text}{env}'


# ═══════════════════════════════════════════════════════════════════════════════
#  HISTORY  (auto-grading yesterday's picks via box scores)
# ═══════════════════════════════════════════════════════════════════════════════

def load_history():
    if os.path.exists(HIST_JSON):
        try:
            with open(HIST_JSON) as f:
                return json.load(f)
        except Exception:
            pass
    return {'records': []}


def save_history(hist):
    with open(HIST_JSON, 'w') as f:
        json.dump(hist, f, indent=2)


def grade_yesterday(history, yesterday_str):
    """
    Auto-grade yesterday's picks using MLB Stats API box scores.
    Fetches each game's box score directly via /game/{pk}/boxscore —
    more reliable than hydrating the schedule endpoint, which doesn't
    consistently return batting stats in the expected structure.
    Skips if the record doesn't exist or has already been graded.
    """
    record = next((r for r in history['records'] if r['date'] == yesterday_str), None)
    if not record or record.get('graded'):
        return

    print(f'  Grading picks for {yesterday_str}...')

    # Step 1: get game PKs for yesterday
    try:
        sched = mlb_get('/schedule', {'sportId': 1, 'date': yesterday_str})
    except Exception as e:
        print(f'    WARN: could not fetch yesterday schedule: {e}')
        return

    game_pks = [
        g['gamePk']
        for d in sched.get('dates', [])
        for g in d.get('games', [])
    ]
    if not game_pks:
        print(f'    WARN: no games found for {yesterday_str}')
        return

    # Step 2: fetch each box score directly — avoids hydration inconsistency
    hr_lookup = {}
    for pk in game_pks:
        try:
            box = mlb_get(f'/game/{pk}/boxscore')
            for side in ['home', 'away']:
                players = (box.get('teams', {})
                              .get(side, {})
                              .get('players', {}))
                for _pid, pdata in players.items():
                    name = pdata.get('person', {}).get('fullName', '')
                    hrs  = int(pdata.get('stats', {})
                                    .get('batting', {})
                                    .get('homeRuns', 0))
                    if name:
                        hr_lookup[name] = max(hr_lookup.get(name, 0), hrs)
            time.sleep(SLEEP_S)
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
    buckets = {'70+': [], '60-69': [], '50-59': [], '<50': []}
    for p in played:
        sc = p.get('score', 0)
        b  = '70+' if sc >= 70 else '60-69' if sc >= 60 else '50-59' if sc >= 50 else '<50'
        buckets[b].append(p['correct'])
    record['summary'] = {
        'total':        len(played),
        'hr_count':     len(hit),
        'hit_rate_pct': round(len(hit) / max(len(played), 1) * 100, 1),
        'hr_players':   [p['player'] for p in hit],
        'by_bucket':    {
            k: {
                'predicted': len(v),
                'hr':        sum(v),
                'rate_pct':  round(sum(v) / max(len(v), 1) * 100, 1),
            }
            for k, v in buckets.items() if v
        },
    }
    print(f'    ✓ {len(hit)}/{len(played)} hit HRs')


def compute_alltime_stats(history, today_str):
    buckets  = {'70+': [0, 0], '60-69': [0, 0], '50-59': [0, 0], '<50': [0, 0]}
    total, hr_total = 0, 0
    for rec in history['records']:
        if rec['date'] == today_str or not rec.get('graded'):
            continue
        for p in rec.get('predictions', []):
            if p.get('actual_hr') is None:
                continue
            hit      = 1 if p['correct'] else 0
            total   += 1
            hr_total += hit
            sc = p.get('score', 0)
            b  = '70+' if sc >= 70 else '60-69' if sc >= 60 else '50-59' if sc >= 50 else '<50'
            buckets[b][0] += 1
            buckets[b][1] += hit
    return {
        'total':        total,
        'hr_count':     hr_total,
        'hit_rate_pct': round(hr_total / max(total, 1) * 100, 1),
        'by_bucket':    {
            k: {
                'predicted': buckets[k][0],
                'hr':        buckets[k][1],
                'rate_pct':  round(buckets[k][1] / max(buckets[k][0], 1) * 100, 1),
            }
            for k in buckets if buckets[k][0] > 0
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

def run():
    today_str     = date.today().isoformat()
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()

    print(f'\n══ HR Hitter Model — {today_str} ══')
    print(f'   Weights: Batter {int(WEIGHTS["batter"]*100)} % · '
          f'Pitcher {int(WEIGHTS["pitcher"]*100)} % '
          f'({int(SP_WEIGHT*100)} % SP + {int(BULLPEN_WEIGHT*100)} % bullpen) · '
          f'Park {int(WEIGHTS["park"]*100)} % · '
          f'Context {int(WEIGHTS["context"]*100)} %')

    # ── 1. Load history and grade yesterday ───────────────────────────────────
    history = load_history()
    grade_yesterday(history, yesterday_str)

    # ── 2. Fetch today's schedule ─────────────────────────────────────────────
    print('\nFetching schedule...')
    sched = mlb_get('/schedule', {
        'sportId': 1,
        'date':    today_str,
        'hydrate': 'probablePitcher,lineups,team,venue',
    })
    raw_games = [g for d in sched.get('dates', []) for g in d.get('games', [])]
    print(f'  ✓ {len(raw_games)} games found')

    # ── 3. Per-game data collection ───────────────────────────────────────────
    all_candidates = []

    # In-run caches — avoid redundant API calls within a single execution
    _batter_cache     = {}   # pid     → hitting stats dict
    _pitcher_cache    = {}   # pid     → pitching stats dict
    _team_pitch_cache = {}   # team_id → team aggregate pitching stats dict
    _hand_cache       = {}   # pid     → 'L' / 'R' / 'S'

    def get_batter(pid):
        if pid not in _batter_cache:
            _batter_cache[pid] = fetch_batter_stats(pid)
            time.sleep(SLEEP_S)
        return _batter_cache[pid]

    def get_sp(pid):
        if pid not in _pitcher_cache:
            _pitcher_cache[pid] = fetch_pitcher_stats(pid)
            time.sleep(SLEEP_S)
        return _pitcher_cache[pid]

    def get_team_pitching(team_id):
        if team_id not in _team_pitch_cache:
            _team_pitch_cache[team_id] = fetch_team_pitching_stats(team_id)
            time.sleep(SLEEP_S)
        return _team_pitch_cache[team_id]

    def get_hand(pid):
        if pid not in _hand_cache:
            _hand_cache[pid] = fetch_player_hand(pid)
            time.sleep(SLEEP_S)
        return _hand_cache[pid]

    for g in raw_games:
        home_info = g['teams']['home']
        away_info = g['teams']['away']
        home_id   = home_info['team']['id']
        away_id   = away_info['team']['id']
        home_abbr = home_info['team'].get('abbreviation', '?')
        away_abbr = away_info['team'].get('abbreviation', '?')
        matchup   = f'{away_abbr} @ {home_abbr}'
        game_dt   = g.get('gameDate', '')
        game_time = get_game_time_et(game_dt)

        park = PARKS.get(home_id, {
            'name':        g.get('venue', {}).get('name', '?'),
            'hr_L':        1.0,
            'hr_R':        1.0,
            'lat':         None,
            'lon':         None,
            'roof':        False,
            'orientation': 0,
        })
        park_name = park['name']

        print(f'\n  ── {matchup} ({game_time}) ──')

        # ── Weather at game time (outdoor parks only) ─────────────────────────
        weather = {}
        w_adj   = 1.0
        if not park.get('roof') and park.get('lat') and game_dt:
            weather = fetch_weather(park['lat'], park['lon'], game_dt)
            time.sleep(0.4)
            if weather:
                w_adj = calc_wind_hr_adj(
                    weather.get('wind_mph', 0),
                    weather.get('wind_dir_deg', 0),
                    park.get('orientation', 0),
                    park.get('roof', False),
                )
                weather['wind_hr_adj'] = w_adj
                print(f'    Weather: {weather.get("temp_f", "?")} °F, '
                      f'wind {weather.get("wind_mph", "?")} mph → HR adj {w_adj}')

        # ── PITCHER ASSIGNMENT ────────────────────────────────────────────────
        #
        # API structure for game "AWAY @ HOME":
        #   g['teams']['home']['probablePitcher'] = the HOME team's starter
        #     → this pitcher FACES the AWAY batters
        #   g['teams']['away']['probablePitcher'] = the AWAY team's starter
        #     → this pitcher FACES the HOME batters
        #
        # Variable naming convention used below:
        #   home_sp_*  = the home team's starter (relevant to AWAY batters)
        #   away_sp_*  = the away team's starter (relevant to HOME batters)
        #
        home_sp_raw  = home_info.get('probablePitcher', {})
        away_sp_raw  = away_info.get('probablePitcher', {})

        home_sp_id   = home_sp_raw.get('id')          # faces AWAY batters
        home_sp_name = home_sp_raw.get('fullName', 'TBD')
        away_sp_id   = away_sp_raw.get('id')          # faces HOME batters
        away_sp_name = away_sp_raw.get('fullName', 'TBD')

        home_sp_stats = get_sp(home_sp_id) if home_sp_id else {}
        away_sp_stats = get_sp(away_sp_id) if away_sp_id else {}

        # Team pitching — always from the OPPOSING team
        #   home_team_pitching → bullpen proxy against AWAY batters
        #   away_team_pitching → bullpen proxy against HOME batters
        home_team_pitching = get_team_pitching(home_id)
        away_team_pitching = get_team_pitching(away_id)

        print(f'    SP vs {home_abbr} batters: '
              f'{"TBD" if not away_sp_id else away_sp_name}  |  '
              f'SP vs {away_abbr} batters: '
              f'{"TBD" if not home_sp_id else home_sp_name}')
        if not away_sp_id:
            print(f'    ↳ {home_abbr} batter pitcher score will use '
                  f'{away_abbr} team pitching (TBD fallback)')
        if not home_sp_id:
            print(f'    ↳ {away_abbr} batter pitcher score will use '
                  f'{home_abbr} team pitching (TBD fallback)')

        # ── Lineups (fallback to active non-pitcher roster) ───────────────────
        lineups         = g.get('lineups', {})
        home_lineup_raw = lineups.get('homePlayers', [])
        away_lineup_raw = lineups.get('awayPlayers', [])

        def resolve_lineup(lineup_raw, team_id):
            if lineup_raw:
                return [{'id': p['id'], 'name': p.get('fullName', '')}
                        for p in lineup_raw]
            try:
                roster = mlb_get(f'/teams/{team_id}/roster',
                                 {'rosterType': 'active'}).get('roster', [])
                time.sleep(SLEEP_S)
                return [
                    {'id': p['person']['id'], 'name': p['person']['fullName']}
                    for p in roster
                    if p.get('position', {}).get('code') not in ('1', 'P')
                ][:13]
            except Exception:
                return []

        home_players = resolve_lineup(home_lineup_raw, home_id)
        away_players = resolve_lineup(away_lineup_raw, away_id)

        # ── Score each batter ─────────────────────────────────────────────────
        #
        # Each group tuple:
        #   (side, players, opp_sp_stats, opp_sp_name, opp_sp_id,
        #    opp_team_pitching, team_abbr)
        #
        # HOME batters → face AWAY starter + AWAY team pitching (bullpen)
        # AWAY batters → face HOME starter + HOME team pitching (bullpen)
        #
        batter_groups = [
            ('home', home_players,
             away_sp_stats,    away_sp_name, away_sp_id,
             away_team_pitching, home_abbr),
            ('away', away_players,
             home_sp_stats,    home_sp_name, home_sp_id,
             home_team_pitching, away_abbr),
        ]

        for (_side, players,
             opp_sp_stats, opp_sp_name, opp_sp_id,
             opp_team_pitching, team_abbr) in batter_groups:

            for player in players:
                pid  = player['id']
                name = player['name']
                if not pid or not name:
                    continue

                bstats = get_batter(pid)
                hand   = get_hand(pid)

                # ── Compute each sub-score ────────────────────────────────────
                b_score       = score_batter(bstats)
                sp_score      = score_pitcher_vuln(opp_sp_stats)    # raw SP
                bullpen_score = score_pitcher_vuln(opp_team_pitching)  # raw bullpen
                p_score       = score_pitcher_combined(opp_sp_stats, opp_team_pitching)
                pk_score      = score_park(park, hand,
                                           w_adj if not park.get('roof') else None)
                ctx           = score_context(park, weather.get('temp_f'))
                total         = composite(b_score, p_score, pk_score, ctx)

                sp_era_str = (
                    f'{opp_sp_stats["era"]:.2f}'
                    if opp_sp_stats and opp_sp_stats.get('era') is not None
                    else '—'
                )

                all_candidates.append({
                    # ── Identity ──────────────────────────────────────────────
                    'player':         name,
                    'team':           team_abbr,
                    'hand':           hand,
                    'game':           matchup,
                    'game_time':      game_time,
                    'park':           park_name,
                    # ── Composite and component scores ────────────────────────
                    'score':          total,
                    'confidence':     confidence(total),
                    'batter_score':   b_score,
                    'pitcher_score':  p_score,        # combined (65 % SP + 35 % bullpen)
                    'sp_score':       sp_score,        # raw SP vulnerability
                    'bullpen_score':  bullpen_score,   # raw team pitching vulnerability
                    'park_score':     pk_score,
                    'context_score':  ctx,
                    # ── Pitcher info ──────────────────────────────────────────
                    'sp_name':        opp_sp_name,
                    'sp_era':         sp_era_str,
                    'sp_listed':      bool(opp_sp_id),
                    # ── Batter stats (displayed in expanded row) ──────────────
                    'hr':             bstats.get('hr'),
                    'hr_per_ab':      bstats.get('hr_per_ab'),
                    'iso':            bstats.get('iso'),
                    'slg':            bstats.get('slg'),
                    'ops':            bstats.get('ops'),
                    # ── Weather / park details ────────────────────────────────
                    'temp_f':         weather.get('temp_f'),
                    'wind_mph':       weather.get('wind_mph'),
                    'wind_hr_adj':    w_adj if not park.get('roof') else None,
                    'hr_factor':      park.get('hr_L' if hand == 'L' else 'hr_R', 1.0),
                    # ── Generated text ────────────────────────────────────────
                    'recent_form':    build_recent_form(bstats),
                    'reasoning':      build_reasoning(
                        name, bstats, b_score,
                        opp_sp_name, opp_sp_stats, sp_score, bullpen_score, p_score,
                        park_name, pk_score, ctx, weather,
                    ),
                    # ── Grading (filled after games complete) ─────────────────
                    'actual_hr':      None,
                    'correct':        None,
                })

    # ── 4. Sort and take top N ────────────────────────────────────────────────
    all_candidates.sort(key=lambda x: x['score'], reverse=True)
    top_n = all_candidates[:TOP_N]
    for i, p in enumerate(top_n):
        p['rank'] = i + 1

    print(f'\n✓ {len(all_candidates)} batters scored → top {len(top_n)} selected')

    # ── 5. Persist today's record in history ──────────────────────────────────
    today_preds_for_history = [
        {
            'rank':       p['rank'],
            'player':     p['player'],
            'team':       p['team'],
            'score':      p['score'],
            'confidence': p['confidence'],
            'actual_hr':  None,
            'correct':    None,
        }
        for p in top_n
    ]
    existing = next((r for r in history['records'] if r['date'] == today_str), None)
    if existing:
        existing['predictions'] = today_preds_for_history
        existing['graded']      = False
    else:
        history['records'].append({
            'date':        today_str,
            'graded':      False,
            'predictions': today_preds_for_history,
        })
    history['records'].sort(key=lambda r: r['date'], reverse=True)
    save_history(history)

    # ── 6. Build stats summaries ──────────────────────────────────────────────
    yday_record  = next((r for r in history['records'] if r['date'] == yesterday_str), None)
    yday_summary = yday_record.get('summary', {}) if yday_record else {}
    alltime      = compute_alltime_stats(history, today_str)

    # ── 7. Write main output JSON ─────────────────────────────────────────────
    output = {
        'updated':     datetime.now(timezone.utc).isoformat(),
        'date':        today_str,
        'predictions': top_n,
        'yesterday':   {'date': yesterday_str, **yday_summary},
        'alltime':     alltime,
    }
    with open(MAIN_JSON, 'w') as f:
        json.dump(output, f, indent=2)

    print(f'✓ Wrote {len(top_n)} predictions → {MAIN_JSON}')
    if alltime['total'] > 0:
        print(f'  All-time: {alltime["hr_count"]}/{alltime["total"]} '
              f'hit HRs ({alltime["hit_rate_pct"]} %)')


if __name__ == '__main__':
    run()
