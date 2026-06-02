"""
models/research_team_metrics.py
──────────────────────────────────────────────────────────────────────────────
Team Metrics Model — Chalk Line Labs Research
──────────────────────────────────────────────────────────────────────────────
Combines two models into a single daily output:

  1. PROPRIETARY FORMULA MODEL
     Predicts runs scored per game from hitting rate stats:
       Pred_R_G  = -3.162 + 7.336*OBP + 8.422*SLG + 0.087*TB/G + 0.208*BB/G
     Predicts runs allowed per game from pitching rate stats:
       Pred_RA_G = -2.678 + 10.569*WHIP - 0.548*H/9 + 0.275*HR/9 - 0.705*BB/9
     Then applies Pythagorean expectation on the *predicted* RS/RA.

  2. PYTHAGOREAN EXPECTATION MODEL
     Applies Pythagorean expectation directly on *actual* runs scored/allowed.

  Both models:
    - Project W-L records through games played (not 162)
    - Report win percentage
    - Report differential vs actual record (positive = "lucky", negative = "unlucky")

  Accuracy metrics (formula vs pythagorean vs actual win%):
    - Pearson correlation coefficient
    - MAE  (mean absolute error)
    - RMSE (root mean squared error)

Workflow:
  Runs daily via GitHub Actions after research_elo.py.
  Writes public/data/research-team-metrics.json.
──────────────────────────────────────────────────────────────────────────────
"""

import json
import os
import math
import requests
from datetime import datetime, timezone

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(BASE_DIR, '..', 'public', 'data')
MAIN_JSON = os.path.join(DATA_DIR, 'research-team-metrics.json')

os.makedirs(DATA_DIR, exist_ok=True)

# ── Settings ──────────────────────────────────────────────────────────────────
SEASON           = datetime.now().year
PYTHAG_EXPONENT  = 1.83
MLB_API          = 'https://statsapi.mlb.com/api/v1'

MLB_TEAMS = [
    'Arizona Diamondbacks', 'Atlanta Braves', 'Baltimore Orioles',
    'Boston Red Sox', 'Chicago Cubs', 'Chicago White Sox',
    'Cincinnati Reds', 'Cleveland Guardians', 'Colorado Rockies',
    'Detroit Tigers', 'Houston Astros', 'Kansas City Royals',
    'Los Angeles Angels', 'Los Angeles Dodgers', 'Miami Marlins',
    'Milwaukee Brewers', 'Minnesota Twins', 'New York Mets',
    'New York Yankees', 'Athletics', 'Philadelphia Phillies',
    'Pittsburgh Pirates', 'San Diego Padres', 'San Francisco Giants',
    'Seattle Mariners', 'St. Louis Cardinals', 'Tampa Bay Rays',
    'Texas Rangers', 'Toronto Blue Jays', 'Washington Nationals',
]

# ── API helpers ───────────────────────────────────────────────────────────────
def get_json(url, params=None):
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


# ── Math helpers ──────────────────────────────────────────────────────────────
def pythag_win_pct(rs, ra, exp=PYTHAG_EXPONENT):
    """Pythagorean win percentage given runs scored and runs allowed."""
    if rs <= 0 and ra <= 0:
        return 0.5
    rs_e = rs ** exp
    ra_e = ra ** exp
    return rs_e / (rs_e + ra_e)


def calc_pred_r_g(obp, slg, tb_g, bb_g):
    """Proprietary formula: predicted runs scored per game."""
    pred = -3.162 + (7.336 * obp) + (8.422 * slg) + (0.087 * tb_g) + (0.208 * bb_g)
    return max(pred, 0.1)


def calc_pred_ra_g(whip, h9, hr9, bb9):
    """Proprietary formula: predicted runs allowed per game."""
    pred = -2.678 + (10.569 * whip) - (0.548 * h9) + (0.275 * hr9) - (0.705 * bb9)
    return max(pred, 0.1)


# ── Accuracy metrics ──────────────────────────────────────────────────────────
def pearson_r(xs, ys):
    n  = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx  = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy  = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def mae(predicted, actual):
    return sum(abs(p - a) for p, a in zip(predicted, actual)) / len(actual)


def rmse(predicted, actual):
    return math.sqrt(sum((p - a) ** 2 for p, a in zip(predicted, actual)) / len(actual))


# ── Data fetching ─────────────────────────────────────────────────────────────
def fetch_standings():
    """Fetch actual W-L records keyed by team name."""
    data = get_json(f'{MLB_API}/standings', {'leagueId': '103,104', 'season': SEASON})
    records = {}
    for division in data['records']:
        for team in division['teamRecords']:
            name = team['team']['name']
            records[name] = {
                'wins':   team['leagueRecord']['wins'],
                'losses': team['leagueRecord']['losses'],
            }
    return records


def fetch_hitting():
    """Fetch team hitting stats; returns dict keyed by team name."""
    data = get_json(f'{MLB_API}/teams/stats', {
        'stats': 'season', 'group': 'hitting', 'sportIds': 1, 'season': SEASON,
    })
    hitting = {}
    for split in data['stats'][0]['splits']:
        name = split['team']['name']
        if name not in MLB_TEAMS:
            continue
        s = split['stat']
        games = int(s.get('gamesPlayed', 0))
        if games == 0:
            continue
        total_bases = int(s.get('totalBases', 0))
        walks       = int(s.get('baseOnBalls', 0))
        hitting[name] = {
            'games': games,
            'obp':   float(s.get('obp', 0)),
            'slg':   float(s.get('slg', 0)),
            'tb_g':  total_bases / games,
            'bb_g':  walks / games,
        }
    return hitting


def fetch_pitching():
    """Fetch team pitching stats; returns dict keyed by team name.
    Also includes actual runs allowed for the Pythagorean model."""
    data = get_json(f'{MLB_API}/teams/stats', {
        'stats': 'season', 'group': 'pitching', 'sportIds': 1, 'season': SEASON,
    })
    pitching = {}
    for split in data['stats'][0]['splits']:
        name = split['team']['name']
        if name not in MLB_TEAMS:
            continue
        s  = split['stat']
        ip = float(s.get('inningsPitched', 0))
        if ip == 0:
            continue
        hits  = int(s.get('hits', 0))
        hr    = int(s.get('homeRuns', 0))
        walks = int(s.get('baseOnBalls', 0))
        pitching[name] = {
            'whip': float(s.get('whip', 0)),
            'h9':   (hits  * 9) / ip,
            'hr9':  (hr    * 9) / ip,
            'bb9':  (walks * 9) / ip,
            'runs_allowed': int(s.get('runs', 0)),   # actual RA for Pythagorean
        }
    return pitching


def fetch_hitting_runs():
    """Fetch actual runs scored per team for the Pythagorean model."""
    data = get_json(f'{MLB_API}/teams/stats', {
        'stats': 'season', 'group': 'hitting', 'sportIds': 1, 'season': SEASON,
    })
    runs = {}
    for split in data['stats'][0]['splits']:
        name = split['team']['name']
        runs[name] = int(split['stat'].get('runs', 0))
    return runs


# ── Model builder ─────────────────────────────────────────────────────────────
def build_team_rows(standings, hitting, pitching, runs_scored):
    rows = []

    for name in MLB_TEAMS:
        if name not in standings or name not in hitting or name not in pitching:
            continue

        rec    = standings[name]
        hit    = hitting[name]
        pit    = pitching[name]
        rs_act = runs_scored.get(name, 0)
        ra_act = pit['runs_allowed']

        wins   = rec['wins']
        losses = rec['losses']
        games  = wins + losses
        if games == 0:
            continue

        actual_wp = wins / games

        # ── Formula model ────────────────────────────────────────────────────
        pred_r_g  = calc_pred_r_g(hit['obp'], hit['slg'], hit['tb_g'], hit['bb_g'])
        pred_ra_g = calc_pred_ra_g(pit['whip'], pit['h9'], pit['hr9'], pit['bb9'])

        pred_rs = pred_r_g  * games
        pred_ra = pred_ra_g * games

        formula_wp   = pythag_win_pct(pred_rs, pred_ra)
        formula_wins = round(formula_wp * games)
        formula_losses = games - formula_wins
        formula_diff   = formula_wins - wins          # positive = model > actual ("unlucky")

        # ── Pythagorean model (actual RS/RA) ─────────────────────────────────
        pythag_wp     = pythag_win_pct(rs_act, ra_act)
        pythag_wins   = round(pythag_wp * games)
        pythag_losses = games - pythag_wins
        pythag_diff   = pythag_wins - wins            # same sign convention

        rows.append({
            'team':           name,
            'games':          games,

            # Actual
            'actual_wins':    wins,
            'actual_losses':  losses,
            'actual_wp':      round(actual_wp, 3),

            # Formula
            'formula_wins':   formula_wins,
            'formula_losses': formula_losses,
            'formula_diff':   formula_diff,
            'formula_wp':     round(formula_wp, 3),

            # Pythagorean
            'pythag_wins':    pythag_wins,
            'pythag_losses':  pythag_losses,
            'pythag_diff':    pythag_diff,
            'pythag_wp':      round(pythag_wp, 3),
        })

    # Sort by formula win% descending (best team first)
    rows.sort(key=lambda r: r['formula_wp'], reverse=True)
    return rows


# ── Accuracy metrics builder ──────────────────────────────────────────────────
def build_accuracy(rows):
    actual  = [r['actual_wp']  for r in rows]
    formula = [r['formula_wp'] for r in rows]
    pythag  = [r['pythag_wp']  for r in rows]

    return {
        'correlation': {
            'formula': round(pearson_r(formula, actual), 4),
            'pythag':  round(pearson_r(pythag,  actual), 4),
        },
        'mae': {
            'formula': round(mae(formula, actual), 4),
            'pythag':  round(mae(pythag,  actual), 4),
        },
        'rmse': {
            'formula': round(rmse(formula, actual), 4),
            'pythag':  round(rmse(pythag,  actual), 4),
        },
    }


# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    print(f'\n{"=" * 60}')
    print(f'  Team Metrics Model — {SEASON}')
    print(f'  Pythagorean exponent: {PYTHAG_EXPONENT}')
    print(f'{"=" * 60}\n')

    print('Fetching standings...')
    standings = fetch_standings()

    print('Fetching hitting stats...')
    hitting = fetch_hitting()

    print('Fetching pitching stats...')
    pitching = fetch_pitching()

    print('Fetching actual runs scored...')
    runs_scored = fetch_hitting_runs()

    print('Building team rows...')
    rows = build_team_rows(standings, hitting, pitching, runs_scored)

    print('Computing accuracy metrics...')
    accuracy = build_accuracy(rows)

    output = {
        'updated':  datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'season':   SEASON,
        'exponent': PYTHAG_EXPONENT,
        'teams':    rows,
        'accuracy': accuracy,
    }

    with open(MAIN_JSON, 'w') as f:
        json.dump(output, f, indent=2)

    print(f'\n✓ Written → {MAIN_JSON}')
    print(f'  {len(rows)} teams')
    print(f'  Formula  r={accuracy["correlation"]["formula"]:.4f}  '
          f'MAE={accuracy["mae"]["formula"]:.4f}  '
          f'RMSE={accuracy["rmse"]["formula"]:.4f}')
    print(f'  Pythag   r={accuracy["correlation"]["pythag"]:.4f}  '
          f'MAE={accuracy["mae"]["pythag"]:.4f}  '
          f'RMSE={accuracy["rmse"]["pythag"]:.4f}')

    # Quick table preview
    print(f'\n  {"TEAM":<26} {"GP":>4} {"W":>4} {"L":>4} '
          f'{"FWP":>6} {"FΔ":>5} {"PWP":>6} {"PΔ":>5}')
    print(f'  {"─" * 70}')
    for r in rows[:10]:
        print(f'  {r["team"]:<26} {r["games"]:>4} {r["actual_wins"]:>4} '
              f'{r["actual_losses"]:>4} {r["formula_wp"]:>6.3f} '
              f'{r["formula_diff"]:>+5} {r["pythag_wp"]:>6.3f} '
              f'{r["pythag_diff"]:>+5}')


if __name__ == '__main__':
    run()
