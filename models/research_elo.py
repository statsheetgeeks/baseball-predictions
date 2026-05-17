"""
models/research_elo.py
──────────────────────────────────────────────────────────────────────────────
MLB Elo Rating Engine — Chalk Line Labs Research
──────────────────────────────────────────────────────────────────────────────
Methodology (matches FiveThirtyEight's published MLB approach):
  - Standard Elo with K = 4  (MLB uses a low K — results are noisy)
  - Home field advantage = 24 Elo points added to home team's rating
  - Season carry-over: 1/3 regression toward the mean (1500) each new year
  - All teams start at 1500 on first appearance

Workflow (runs daily at 9 AM CT via GitHub Actions):
  1. Fetch all completed regular-season games for SEASONS via MLB Stats API
     Historical seasons are cached permanently; current season is
     re-fetched each day so new results are included.
  2. Build Elo ratings chronologically across all seasons
  3. Compute current standings (latest post-game ratings + W-L record)
  4. Compile the last 30 completed games with pre-game Elos + model accuracy
  5. Write public/data/research-elo.json  (read by Next.js page)
──────────────────────────────────────────────────────────────────────────────
"""

import json
import os
import time
import requests
from datetime import date, datetime, timezone

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(BASE_DIR, '..', 'public', 'data')
CACHE_DIR = os.path.join(BASE_DIR, '..', 'mlb_cache_v2')   # shared with other models
MAIN_JSON = os.path.join(DATA_DIR, 'research-elo.json')

os.makedirs(DATA_DIR,  exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

MLB_API      = 'https://statsapi.mlb.com/api/v1'
TODAY        = date.today().isoformat()      # e.g. '2025-05-16'
CURRENT_YEAR = date.today().year
SEASONS      = list(range(2021, CURRENT_YEAR + 1))
SLEEP_S      = 0.15
RECENT_N     = 30   # recent completed games to surface on the page

# ── Elo parameters ────────────────────────────────────────────────────────────
K           = 4
HOME_ADV    = 24
REVERSION   = 1 / 3
INIT_RATING = 1500

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
    'New York Yankees':       'NYY',  'Oakland Athletics':        'OAK',
    'Philadelphia Phillies':  'PHI',  'Pittsburgh Pirates':       'PIT',
    'San Diego Padres':       'SD',   'Seattle Mariners':         'SEA',
    'San Francisco Giants':   'SF',   'St. Louis Cardinals':      'STL',
    'Tampa Bay Rays':         'TB',   'Texas Rangers':            'TEX',
    'Toronto Blue Jays':      'TOR',  'Washington Nationals':     'WSH',
    # Aliases
    'Athletics':              'OAK',  'Sacramento Athletics':     'OAK',
    'Guardians':              'CLE',
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
            return json.load(f)

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
    return games


# ── Elo engine ────────────────────────────────────────────────────────────────
def elo_win_prob(rating_a, rating_b):
    """Expected win probability for team A vs team B (standard formula)."""
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def build_elo(all_games):
    """
    Process every game chronologically.

    Returns
    -------
    ratings        : dict  {team_name: current_elo_float}
    rows           : list  of per-game dicts (used for recent_games output)
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
    print(f'  Seasons: {SEASONS[0]}–{SEASONS[-1]}'
          f'  |  K={K}  |  home_adv={HOME_ADV}'
          f'  |  reversion={REVERSION:.2f}')
    print(f'{"=" * 60}\n')

    # ── 1. Fetch all seasons ──────────────────────────────────────────────
    print('Fetching game data...')
    all_games = []
    for season in SEASONS:
        games = fetch_season_games(season)
        all_games.extend(games)

    print(f'\n  Total: {len(all_games):,} completed games '
          f'({SEASONS[0]}–{SEASONS[-1]})\n')

    # ── 2. Build Elo ratings ──────────────────────────────────────────────
    print('Computing Elo ratings...')
    ratings, rows, season_records = build_elo(all_games)
    print(f'  Done. {len(ratings)} teams rated.\n')

    # ── 3. Standings ──────────────────────────────────────────────────────
    standings = build_standings(ratings, season_records)

    # ── 4. Recent games (last RECENT_N, most-recent first) ────────────────
    recent = list(reversed(rows[-RECENT_N:]))

    # ── 5. Season accuracy ────────────────────────────────────────────────
    current_rows = [r for r in rows if r['date'].startswith(str(CURRENT_YEAR))]
    n_games   = len(current_rows)
    n_correct = sum(1 for r in current_rows if r['model_correct'])
    accuracy  = round(n_correct / n_games, 4) if n_games else None

    # ── 6. Write JSON ─────────────────────────────────────────────────────
    out = {
        'updated': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'params': {
            'k':        K,
            'home_adv': HOME_ADV,
            'reversion': round(REVERSION, 4),
            'seasons':  SEASONS,
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
