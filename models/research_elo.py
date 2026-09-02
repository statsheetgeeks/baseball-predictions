"""
models/research_elo.py
──────────────────────────────────────────────────────────────────────────────
MLB Elo Rating Engine — Chalk Line Labs Research
──────────────────────────────────────────────────────────────────────────────
Methodology (matches FiveThirtyEight's published MLB approach, base layer only):
  - Standard win/loss Elo (no margin-of-victory or starting-pitcher layers —
    those live in the separate game-matchups model).
  - K-factor, home-field advantage, and season reversion are NOT fixed
    constants. Each run, they're auto-tuned via a small walk-forward
    validation search (scipy.optimize.differential_evolution): the loaded
    seasons are split into a burn-in window, a validation window, and a
    held-out test window; the params that minimize log-loss on the
    validation window are the ones used to build the final standings. This
    mirrors Stage 1 of the standalone `mlb_elo_v2.py` auto-tuned model.
  - Season carry-over: tuned fraction of regression toward the mean (1500)
    each new year.
  - All teams start at 1500 on first appearance.
  - Team identity is canonicalized across franchise renames (Cleveland
    Indians → Guardians in 2022, Oakland/Sacramento → Athletics in 2025) so
    a single franchise never gets split into multiple rows.

Workflow (runs daily at 9 AM CT via GitHub Actions):
  1. Fetch all completed regular-season games for SEASONS via MLB Stats API
     Historical seasons are cached permanently; current season is
     re-fetched each day so new results are included.
  2. Canonicalize renamed franchises to a single current team identity.
  3. Auto-tune K / home-field advantage / season reversion via walk-forward
     validation (differential_evolution minimizing validation log-loss).
  4. Build final Elo ratings chronologically across all seasons with the
     tuned params.
  5. Compute current standings (latest post-game ratings + W-L record).
  6. Compile the last 30 completed games with pre-game Elos + model accuracy.
  7. Write public/data/research-elo.json  (read by Next.js page)
──────────────────────────────────────────────────────────────────────────────
"""

import json
import math
import os
import time
import requests
from datetime import date, datetime, timezone

from scipy.optimize import differential_evolution

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(BASE_DIR, '..', 'public', 'data')
CACHE_DIR = os.path.join(BASE_DIR, '..', 'mlb_cache_v2')   # shared with other models
MAIN_JSON = os.path.join(DATA_DIR, 'research-elo.json')

os.makedirs(DATA_DIR,  exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

MLB_API      = 'https://statsapi.mlb.com/api/v1'
TODAY        = date.today().isoformat()
CURRENT_YEAR = date.today().year
SEASONS      = list(range(2021, CURRENT_YEAR + 1))
SLEEP_S      = 0.15
RECENT_N     = 30   # recent completed games to surface on the page

# ── Elo parameters ────────────────────────────────────────────────────────────
# Defaults — used only as a fallback if there isn't enough season history yet
# to run the walk-forward tuning search (e.g. a brand-new deployment).
DEFAULT_K           = 4.0
DEFAULT_HOME_ADV    = 24.0
DEFAULT_REVERSION   = 1 / 3
INIT_RATING         = 1500

# Search bounds for the auto-tuner (mirrors Stage 1 of mlb_elo_v2.py).
TUNE_BOUNDS = [(1, 40), (0, 80), (0, 1)]   # K, HOME_ADV, REVERSION

# ── Franchise renames → canonical current identity ────────────────────────────
# Collapses historical name variants returned by the MLB Stats API so each
# franchise is tracked as a single team across seasons, instead of quietly
# splitting into extra "teams" (which was inflating the standings count
# past 30).
CANONICAL_TEAM = {
    'Cleveland Indians':     'Cleveland Guardians',   # renamed 2022
    'Oakland Athletics':     'Athletics',             # relocated 2025
    'Sacramento Athletics':  'Athletics',             # transitional naming
}

def canonicalize_team(name):
    return CANONICAL_TEAM.get(name, name)


# ── Team name → display abbreviation ─────────────────────────────────────────
NAME2ABBR = {
    'Arizona Diamondbacks':   'ARI',  'Atlanta Braves':          'ATL',
    'Baltimore Orioles':      'BAL',  'Boston Red Sox':           'BOS',
    'Chicago Cubs':           'CHC',  'Chicago White Sox':        'CWS',
    'Cincinnati Reds':        'CIN',  'Cleveland Guardians':      'CLE',
    'Colorado Rockies':       'COL',  'Detroit Tigers':           'DET',
    'Houston Astros':         'HOU',  'Kansas City Royals':       'KC',
    'Los Angeles Angels':     'LAA',  'Los Angeles Dodgers':      'LAD',
    'Miami Marlins':          'MIA',  'Milwaukee Brewers':        'MIL',
    'Minnesota Twins':        'MIN',  'New York Mets':            'NYM',
    'New York Yankees':       'NYY',  'Athletics':                'ATH',
    'Philadelphia Phillies':  'PHI',  'Pittsburgh Pirates':       'PIT',
    'San Diego Padres':       'SD',   'Seattle Mariners':         'SEA',
    'San Francisco Giants':   'SF',   'St. Louis Cardinals':      'STL',
    'Tampa Bay Rays':         'TB',   'Texas Rangers':            'TEX',
    'Toronto Blue Jays':      'TOR',  'Washington Nationals':     'WSH',
    # Legacy aliases — kept as a safety net in case an un-canonicalized name
    # slips through somewhere, but canonicalize_team() should catch these
    # before resolve_abbr() is ever called.
    'Oakland Athletics':      'ATH',  'Sacramento Athletics':     'ATH',
    'Cleveland Indians':      'CLE',  'Guardians':                'CLE',
}

def resolve_abbr(name):
    if name in NAME2ABBR:
        return NAME2ABBR[name]
    for full, abbr in NAME2ABBR.items():
        if full.split()[-1].lower() in name.lower():
            return abbr
    return name[:3].upper()


# ── API helper ────────────────────────────────────────────────────────────────
def _get(url, timeout=20):
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


# ── Season schedule with scores ───────────────────────────────────────────────
def fetch_season_games(season):
    """
    Fetch all completed regular-season games for a season, with final scores.

    Uses the schedule endpoint with linescore + team hydration — one API
    call per season rather than one per game, which keeps runtime fast.

    Historical seasons: cached permanently (results never change).
    Current season: cached by date so new games are picked up daily.
    """
    if season == CURRENT_YEAR:
        cache = os.path.join(CACHE_DIR, f'elo_schedule_{season}_{TODAY}.json')
    else:
        cache = os.path.join(CACHE_DIR, f'elo_schedule_{season}.json')

    if os.path.exists(cache):
        with open(cache) as f:
            games = json.load(f)
    else:
        print(f'  Fetching {season} schedule with scores...')
        url = (f'{MLB_API}/schedule?sportId=1&season={season}'
               f'&gameType=R&hydrate=linescore,team')

        games = []
        data  = _get(url)

        for day in data.get('dates', []):
            game_date = day.get('date', '')
            for g in day.get('games', []):
                state = g.get('status', {}).get('abstractGameState', '')
                coded = g.get('status', {}).get('codedGameState', '')
                if state != 'Final' and coded != 'F':
                    continue

                ls         = g.get('linescore', {}).get('teams', {})
                home_score = ls.get('home', {}).get('runs')
                away_score = ls.get('away', {}).get('runs')

                if home_score is None or away_score is None:
                    continue

                home_name = g['teams']['home']['team']['name']
                away_name = g['teams']['away']['team']['name']

                games.append({
                    'date':       game_date,
                    'game_pk':    g['gamePk'],
                    'home_team':  home_name,
                    'away_team':  away_name,
                    'home_score': int(home_score),
                    'away_score': int(away_score),
                })

        games.sort(key=lambda x: (x['date'], x['game_pk']))

        if games:   # don't cache an empty response (API may have errored)
            with open(cache, 'w') as f:
                json.dump(games, f)

        print(f'    {season}: {len(games)} completed games')
        time.sleep(SLEEP_S)

    # Canonicalize franchise renames on every load (fresh fetch OR cache hit)
    # so old caches written before this fix still come out correct, with no
    # need to bust/re-fetch them.
    for g in games:
        g['home_team'] = canonicalize_team(g['home_team'])
        g['away_team'] = canonicalize_team(g['away_team'])

    return games


# ── Elo engine ────────────────────────────────────────────────────────────────
def elo_win_prob(rating_a, rating_b):
    """Expected win probability for team A vs team B (standard formula)."""
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def build_elo(all_games, K, HOME_ADV, REVERSION):
    """
    Process every game chronologically with the given hyperparameters.

    Returns
    -------
    ratings        : dict  {team_name: current_elo_float}
    rows           : list  of per-game dicts (used for recent_games output
                     and for log-loss scoring during tuning)
    season_records : dict  {team_name: {'wins': N, 'losses': N}}
                     — tracks W-L for the current season only
    """
    ratings        = {}
    cur_season     = None
    rows           = []
    all_teams      = (set(g['home_team'] for g in all_games)
                      | set(g['away_team'] for g in all_games))
    season_records = {t: {'wins': 0, 'losses': 0} for t in all_teams}

    for game in all_games:
        home   = game['home_team']
        away   = game['away_team']
        season = int(game['date'][:4])

        # ── Season boundary: regress all known teams toward 1500 ─────────
        if season != cur_season:
            cur_season = season
            for team in all_teams:
                if team in ratings:
                    ratings[team] = (ratings[team] * (1 - REVERSION)
                                     + INIT_RATING  * REVERSION)
                else:
                    ratings[team] = float(INIT_RATING)
            # Reset W-L counter when we enter the current season
            if season == CURRENT_YEAR:
                season_records = {t: {'wins': 0, 'losses': 0} for t in all_teams}

        ratings.setdefault(home, float(INIT_RATING))
        ratings.setdefault(away, float(INIT_RATING))

        home_pre = ratings[home]
        away_pre = ratings[away]

        # Home advantage applied only to win-probability calculation
        home_prob = elo_win_prob(home_pre + HOME_ADV, away_pre)
        home_win  = int(game['home_score'] > game['away_score'])

        # K-factor update: winner gains, loser loses
        if home_win:
            delta     = K * (1 - home_prob)
            home_post = home_pre + delta
            away_post = away_pre - delta
        else:
            away_prob = 1 - home_prob
            delta     = K * (1 - away_prob)
            away_post = away_pre + delta
            home_post = home_pre - delta

        ratings[home] = home_post
        ratings[away] = away_post

        # Track W-L for current season
        if season == CURRENT_YEAR:
            if home_win:
                season_records[home]['wins']   += 1
                season_records[away]['losses'] += 1
            else:
                season_records[away]['wins']   += 1
                season_records[home]['losses'] += 1

        # Model is "correct" if the higher-Elo side (with home advantage) won
        model_pick_home = home_prob >= 0.5
        model_correct   = bool(
            (model_pick_home and home_win) or
            (not model_pick_home and not home_win)
        )

        rows.append({
            'date':          game['date'],
            'season':        season,
            'game_pk':       game['game_pk'],
            'home_team':     home,
            'away_team':     away,
            'home_abbr':     resolve_abbr(home),
            'away_abbr':     resolve_abbr(away),
            'home_elo_pre':  round(home_pre, 1),
            'away_elo_pre':  round(away_pre, 1),
            'home_prob':     round(home_prob, 4),
            'away_prob':     round(1 - home_prob, 4),
            'home_score':    game['home_score'],
            'away_score':    game['away_score'],
            'home_win':      home_win,
            'model_correct': model_correct,
        })

    return ratings, rows, season_records


# ── Walk-forward hyperparameter tuning (Stage 1 of mlb_elo_v2.py) ─────────────
def auto_season_split(seasons_sorted):
    """
    Carve the loaded seasons into burn-in / validation / held-out test.
    Roughly 30% burn-in / 50% validation / 20% test by season count.
    """
    n = len(seasons_sorted)
    if n < 3:
        return 0, 0, seasons_sorted, []
    test_n = max(1, round(n * 0.2))
    burn_in_n = max(1, round(n * 0.3))
    while burn_in_n + test_n >= n:
        if burn_in_n > 1:
            burn_in_n -= 1
        elif test_n > 1:
            test_n -= 1
        else:
            break
    val_seasons  = seasons_sorted[burn_in_n : n - test_n]
    test_seasons = seasons_sorted[n - test_n :]
    return burn_in_n, test_n, val_seasons, test_seasons


def log_loss(rows, seasons_mask):
    if not seasons_mask:
        return 10.0
    seasons_mask = set(seasons_mask)
    filtered = [r for r in rows if r['season'] in seasons_mask]
    if not filtered:
        return 10.0
    eps   = 1e-6
    total = 0.0
    for r in filtered:
        p = min(max(r['home_prob'], eps), 1 - eps)
        y = r['home_win']
        total += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return total / len(filtered)


def tune_base_params(all_games):
    """
    Auto-tune K, home-field advantage, and season reversion via
    differential_evolution, minimizing log-loss on a validation window of
    seasons (walk-forward style, matching Stage 1 of mlb_elo_v2.py).

    Falls back to the fixed defaults if there isn't enough season history
    yet to form a meaningful validation window.
    """
    seasons_sorted = sorted(set(int(g['date'][:4]) for g in all_games))
    _, _, val_seasons, test_seasons = auto_season_split(seasons_sorted)

    if not val_seasons:
        print('Not enough season history to auto-tune — using defaults '
              f'(K={DEFAULT_K:g}, home_adv={DEFAULT_HOME_ADV:g}, '
              f'revert={DEFAULT_REVERSION:.3g}).')
        return DEFAULT_K, DEFAULT_HOME_ADV, DEFAULT_REVERSION, val_seasons, test_seasons

    def _objective(x):
        K_, HA_, REV_ = x
        _, rows, _ = build_elo(all_games, K=K_, HOME_ADV=HA_, REVERSION=REV_)
        return log_loss(rows, val_seasons)

    res = differential_evolution(
        _objective, bounds=TUNE_BOUNDS,
        maxiter=8, popsize=8, tol=1e-4, seed=42, polish=True, workers=1,
    )
    tuned_K, tuned_HOME_ADV, tuned_REVERSION = (float(v) for v in res.x)
    print(f'Auto-tuned params: K={tuned_K:.2f}, home_adv={tuned_HOME_ADV:.2f}, '
          f'season_revert={tuned_REVERSION:.3f} -> val log-loss {res.fun:.4f}')

    return tuned_K, tuned_HOME_ADV, tuned_REVERSION, val_seasons, test_seasons


# ── Standings builder ─────────────────────────────────────────────────────────
def build_standings(ratings, season_records):
    """
    Produce a sorted list of team standings from current Elo ratings.

    implied_wp — probability of beating a perfectly league-average (1500)
    opponent on a neutral field; useful as a standalone power metric.
    """
    entries = []
    for team_name, rating in ratings.items():
        abbr       = resolve_abbr(team_name)
        delta      = rating - INIT_RATING
        implied_wp = round(elo_win_prob(rating, INIT_RATING), 4)
        rec        = season_records.get(team_name, {'wins': 0, 'losses': 0})
        entries.append({
            'team':       team_name,
            'abbr':       abbr,
            'rating':     round(rating, 1),
            'delta':      round(delta, 1),
            'implied_wp': implied_wp,
            'wins':       rec['wins'],
            'losses':     rec['losses'],
        })

    entries.sort(key=lambda x: x['rating'], reverse=True)
    for i, e in enumerate(entries, 1):
        e['rank'] = i
    return entries


# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    print(f'\n{"=" * 60}')
    print(f'  MLB Elo Research Model — {TODAY}')
    print(f'  Seasons: {SEASONS[0]}–{SEASONS[-1]}')
    print(f'{"=" * 60}\n')

    # ── 1. Fetch all seasons ──────────────────────────────────────────────
    print('Fetching game data...')
    all_games = []
    for season in SEASONS:
        games = fetch_season_games(season)
        all_games.extend(games)

    print(f'\n  Total: {len(all_games):,} completed games '
          f'({SEASONS[0]}–{SEASONS[-1]})\n')

    n_teams = len(set(g['home_team'] for g in all_games)
                  | set(g['away_team'] for g in all_games))
    print(f'  {n_teams} distinct teams after canonicalization\n')

    # ── 2. Auto-tune K / home-field advantage / season reversion ──────────
    print('Auto-tuning base Elo params (walk-forward validation)...')
    K, HOME_ADV, REVERSION, val_seasons, test_seasons = tune_base_params(all_games)
    print()

    # ── 3. Build final Elo ratings with tuned params ───────────────────────
    print('Computing final Elo ratings...')
    ratings, rows, season_records = build_elo(all_games, K=K, HOME_ADV=HOME_ADV, REVERSION=REVERSION)
    print(f'  Done. {len(ratings)} teams rated.\n')

    if test_seasons:
        test_ll = log_loss(rows, test_seasons)
        print(f'  Held-out test log-loss ({test_seasons}): {test_ll:.4f}\n')

    # ── 4. Standings ────────────────────────────────────────────────────────
    standings = build_standings(ratings, season_records)

    # ── 5. Recent games (last RECENT_N, most-recent first) ────────────────
    recent = list(reversed(rows[-RECENT_N:]))

    # ── 6. Season accuracy ─────────────────────────────────────────────────
    current_rows = [r for r in rows if r['date'].startswith(str(CURRENT_YEAR))]
    n_games   = len(current_rows)
    n_correct = sum(1 for r in current_rows if r['model_correct'])
    accuracy  = round(n_correct / n_games, 4) if n_games else None

    # ── 7. Write JSON ───────────────────────────────────────────────────────
    out = {
        'updated': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'params': {
            'k':        round(K, 2),
            'home_adv': round(HOME_ADV, 2),
            'reversion': round(REVERSION, 4),
            'seasons':  SEASONS,
            'tuning':   {
                'method':        'differential_evolution (walk-forward validation)',
                'val_seasons':   val_seasons,
                'test_seasons':  test_seasons,
            },
        },
        'accuracy': {
            'season':  CURRENT_YEAR,
            'games':   n_games,
            'correct': n_correct,
            'pct':     accuracy,
        },
        'standings':    standings,
        'recent_games': recent,
    }

    with open(MAIN_JSON, 'w') as f:
        json.dump(out, f, indent=2)

    print(f'✓ Written → {MAIN_JSON}')
    print(f'  {len(standings)} teams  |  {len(recent)} recent games')
    if accuracy is not None:
        print(f'  {CURRENT_YEAR} accuracy: {accuracy * 100:.1f}%'
              f'  ({n_correct}/{n_games})')

    # Print top-10 standings to console for quick verification
    print(f'\n  {"RK":<4} {"TEAM":<26} {"ELO":>7}  {"Δ":>6}  {"IMP WP":>7}  W-L')
    print(f'  {"─" * 60}')
    for e in standings[:10]:
        rec = f'{e["wins"]}-{e["losses"]}'
        print(f'  {e["rank"]:<4} {e["team"]:<26} {e["rating"]:>7.1f}'
              f'  {e["delta"]:>+6.1f}  {e["implied_wp"]*100:>6.1f}%  {rec}')


if __name__ == '__main__':
    run()
