"""
models/research_team_metrics.py
──────────────────────────────────────────────────────────────────────────────
Team Metrics Model — Chalk Line Labs Research
──────────────────────────────────────────────────────────────────────────────
Three models compared side-by-side:

  1. PROPRIETARY FORMULA MODEL
     Predicts RS/G from hitting rate stats, RA/G from pitching rate stats,
     then applies Pythagorean expectation on the predicted values.
       Pred_R_G  = -3.162 + 7.336*OBP + 8.422*SLG + 0.087*TB/G + 0.208*BB/G
       Pred_RA_G = -2.678 + 10.569*WHIP - 0.548*H/9 + 0.275*HR/9 - 0.705*BB/9

  2. PYTHAGOREAN EXPECTATION MODEL
     Applies Pythagorean expectation directly on actual RS/RA.

  3. ELO RATINGS MODEL
     Reads implied_wp from the already-written research-elo.json and projects
     W-L through each team's games played. No re-computation needed — we just
     consume the Elo model's output as a third benchmark.

Key design: MLB Stats API joins are keyed on teamId (integer), not team name
string, to avoid name-mismatch bugs across endpoints. Elo data is joined by
team name since that's what research-elo.json provides; the Elo model already
uses the same MLB Stats API name strings as the standings endpoint.

Accuracy metrics (all three models vs actual win%):
  - Pearson correlation coefficient
  - MAE  (mean absolute error)
  - RMSE (root mean squared error)

Workflow:
  Runs daily via GitHub Actions AFTER research_elo.py so that
  research-elo.json is already up to date when we read it.
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
ELO_JSON  = os.path.join(DATA_DIR, 'research-elo.json')

os.makedirs(DATA_DIR, exist_ok=True)

# ── Settings ──────────────────────────────────────────────────────────────────
SEASON          = datetime.now().year
PYTHAG_EXPONENT = 1.83
MLB_API         = 'https://statsapi.mlb.com/api/v1'


# ── API helpers ───────────────────────────────────────────────────────────────
def get_json(url, params=None):
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


# ── Math helpers ──────────────────────────────────────────────────────────────
def pythag_win_pct(rs, ra, exp=PYTHAG_EXPONENT):
    if rs <= 0 and ra <= 0:
        return 0.5
    rs_e = rs ** exp
    ra_e = ra ** exp
    return rs_e / (rs_e + ra_e)


def calc_pred_r_g(obp, slg, tb_g, bb_g):
    pred = -3.162 + (7.336 * obp) + (8.422 * slg) + (0.087 * tb_g) + (0.208 * bb_g)
    return max(pred, 0.1)


def calc_pred_ra_g(whip, h9, hr9, bb9):
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


# ── Elo data loader ───────────────────────────────────────────────────────────
def load_elo_implied_wp():
    """Read research-elo.json and return {team_name: implied_wp}.
    research_elo.py must have already run before this script."""
    if not os.path.exists(ELO_JSON):
        print(f'  WARNING: {ELO_JSON} not found — Elo column will be empty.')
        return {}
    with open(ELO_JSON) as f:
        data = json.load(f)
    result = {}
    for entry in data.get('standings', []):
        result[entry['team']] = entry['implied_wp']
    print(f'  Elo data: {len(result)} teams loaded from research-elo.json')
    return result


# ── MLB Stats API fetchers — all keyed by teamId ──────────────────────────────
def fetch_standings():
    """Returns {teamId: {name, wins, losses}}."""
    data = get_json(f'{MLB_API}/standings', {
        'leagueId': '103,104',
        'season':   SEASON,
        'hydrate':  'team',
    })
    records = {}
    for division in data['records']:
        for entry in division['teamRecords']:
            tid  = entry['team']['id']
            name = entry['team']['name']
            records[tid] = {
                'name':   name,
                'wins':   entry['leagueRecord']['wins'],
                'losses': entry['leagueRecord']['losses'],
            }
    print(f'  Standings: {len(records)} teams')
    return records


def fetch_hitting():
    """Returns {teamId: hitting stats dict}."""
    data = get_json(f'{MLB_API}/teams/stats', {
        'stats':    'season',
        'group':    'hitting',
        'sportIds': 1,
        'season':   SEASON,
    })
    hitting = {}
    for split in data['stats'][0]['splits']:
        tid   = split['team']['id']
        s     = split['stat']
        games = int(s.get('gamesPlayed', 0))
        if games == 0:
            continue
        total_bases = int(s.get('totalBases', 0))
        walks       = int(s.get('baseOnBalls', 0))
        hitting[tid] = {
            'games': games,
            'obp':   float(s.get('obp', 0)),
            'slg':   float(s.get('slg', 0)),
            'tb_g':  total_bases / games,
            'bb_g':  walks / games,
            'runs':  int(s.get('runs', 0)),
        }
    print(f'  Hitting:   {len(hitting)} teams')
    return hitting


def fetch_pitching():
    """Returns {teamId: pitching stats dict}."""
    data = get_json(f'{MLB_API}/teams/stats', {
        'stats':    'season',
        'group':    'pitching',
        'sportIds': 1,
        'season':   SEASON,
    })
    pitching = {}
    for split in data['stats'][0]['splits']:
        tid  = split['team']['id']
        s    = split['stat']
        ip   = float(s.get('inningsPitched', 0))
        if ip == 0:
            continue
        hits  = int(s.get('hits', 0))
        hr    = int(s.get('homeRuns', 0))
        walks = int(s.get('baseOnBalls', 0))
        pitching[tid] = {
            'whip':         float(s.get('whip', 0)),
            'h9':           (hits  * 9) / ip,
            'hr9':          (hr    * 9) / ip,
            'bb9':          (walks * 9) / ip,
            'runs_allowed': int(s.get('runs', 0)),
        }
    print(f'  Pitching:  {len(pitching)} teams')
    return pitching


# ── Model builder ─────────────────────────────────────────────────────────────
def build_team_rows(standings, hitting, pitching, elo_wp_by_name):
    rows    = []
    skipped = []

    for tid, rec in standings.items():
        if tid not in hitting:
            skipped.append(f'{rec["name"]} (no hitting data)')
            continue
        if tid not in pitching:
            skipped.append(f'{rec["name"]} (no pitching data)')
            continue

        name   = rec['name']
        hit    = hitting[tid]
        pit    = pitching[tid]
        rs_act = hit['runs']
        ra_act = pit['runs_allowed']

        wins   = rec['wins']
        losses = rec['losses']
        games  = wins + losses
        if games == 0:
            continue

        actual_wp = wins / games

        # ── Formula model ────────────────────────────────────────────────
        pred_r_g  = calc_pred_r_g(hit['obp'], hit['slg'], hit['tb_g'], hit['bb_g'])
        pred_ra_g = calc_pred_ra_g(pit['whip'], pit['h9'], pit['hr9'], pit['bb9'])
        pred_rs   = pred_r_g  * games
        pred_ra   = pred_ra_g * games

        formula_wp     = pythag_win_pct(pred_rs, pred_ra)
        formula_wins   = round(formula_wp * games)
        formula_losses = games - formula_wins
        formula_diff   = formula_wins - wins

        # ── Pythagorean model ─────────────────────────────────────────────
        pythag_wp     = pythag_win_pct(rs_act, ra_act)
        pythag_wins   = round(pythag_wp * games)
        pythag_losses = games - pythag_wins
        pythag_diff   = pythag_wins - wins

        # ── Elo model — join by name ──────────────────────────────────────
        elo_implied = elo_wp_by_name.get(name)
        if elo_implied is not None:
            elo_wp     = elo_implied
            elo_wins   = round(elo_wp * games)
            elo_losses = games - elo_wins
            elo_diff   = elo_wins - wins
        else:
            # Elo data missing for this team (shouldn't happen in normal runs)
            elo_wp     = None
            elo_wins   = None
            elo_losses = None
            elo_diff   = None
            print(f'  WARNING: no Elo data for "{name}"')

        rows.append({
            'team':          name,
            'games':         games,

            # Actual
            'actual_wins':   wins,
            'actual_losses': losses,
            'actual_wp':     round(actual_wp, 3),

            # Formula
            'formula_wins':   formula_wins,
            'formula_losses': formula_losses,
            'formula_diff':   formula_diff,
            'formula_wp':     round(formula_wp, 3),

            # Pythagorean
            'pythag_wins':   pythag_wins,
            'pythag_losses': pythag_losses,
            'pythag_diff':   pythag_diff,
            'pythag_wp':     round(pythag_wp, 3),

            # Elo
            'elo_wins':      elo_wins,
            'elo_losses':    elo_losses,
            'elo_diff':      elo_diff,
            'elo_wp':        round(elo_wp, 3) if elo_wp is not None else None,
        })

    if skipped:
        print(f'  Skipped: {skipped}')

    rows.sort(key=lambda r: r['formula_wp'], reverse=True)
    return rows


# ── Accuracy metrics ──────────────────────────────────────────────────────────
def build_accuracy(rows):
    # Only include teams that have Elo data for a fair three-way comparison
    valid   = [r for r in rows if r['elo_wp'] is not None]
    actual  = [r['actual_wp']  for r in valid]
    formula = [r['formula_wp'] for r in valid]
    pythag  = [r['pythag_wp']  for r in valid]
    elo     = [r['elo_wp']     for r in valid]

    return {
        'correlation': {
            'formula': round(pearson_r(formula, actual), 4),
            'pythag':  round(pearson_r(pythag,  actual), 4),
            'elo':     round(pearson_r(elo,      actual), 4),
        },
        'mae': {
            'formula': round(mae(formula, actual), 4),
            'pythag':  round(mae(pythag,  actual), 4),
            'elo':     round(mae(elo,      actual), 4),
        },
        'rmse': {
            'formula': round(rmse(formula, actual), 4),
            'pythag':  round(rmse(pythag,  actual), 4),
            'elo':     round(rmse(elo,      actual), 4),
        },
    }


# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    print(f'\n{"=" * 60}')
    print(f'  Team Metrics Model — {SEASON}')
    print(f'  Pythagorean exponent: {PYTHAG_EXPONENT}')
    print(f'{"=" * 60}\n')

    print('Loading Elo implied win percentages...')
    elo_wp = load_elo_implied_wp()

    print('Fetching standings...')
    standings = fetch_standings()

    print('Fetching hitting stats...')
    hitting = fetch_hitting()

    print('Fetching pitching stats...')
    pitching = fetch_pitching()

    print('Building team rows...')
    rows = build_team_rows(standings, hitting, pitching, elo_wp)
    print(f'  {len(rows)} teams in output')

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
    print(f'  Elo      r={accuracy["correlation"]["elo"]:.4f}  '
          f'MAE={accuracy["mae"]["elo"]:.4f}  '
          f'RMSE={accuracy["rmse"]["elo"]:.4f}')

    print(f'\n  {"TEAM":<26} {"GP":>4} {"W":>4} {"L":>4} '
          f'{"FWP":>6} {"FΔ":>4} {"PWP":>6} {"PΔ":>4} {"EWP":>6} {"EΔ":>4}')
    print(f'  {"─" * 78}')
    for r in rows[:10]:
        ew = f'{r["elo_wp"]:.3f}' if r["elo_wp"] is not None else '  N/A'
        ed = f'{r["elo_diff"]:>+4}' if r["elo_diff"] is not None else '  N/A'
        print(f'  {r["team"]:<26} {r["games"]:>4} {r["actual_wins"]:>4} '
              f'{r["actual_losses"]:>4} {r["formula_wp"]:>6.3f} '
              f'{r["formula_diff"]:>+4} {r["pythag_wp"]:>6.3f} '
              f'{r["pythag_diff"]:>+4} {ew:>6} {ed}')


if __name__ == '__main__':
    run()
