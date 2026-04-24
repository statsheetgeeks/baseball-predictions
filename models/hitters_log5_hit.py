"""
models/hitters_log5_hit.py
──────────────────────────────────────────────────────────────────────────────
Chalk Line Labs — Log5 Hit Probability Model

Scores every qualified batter in today's MLB lineups on the probability of
getting at least one hit, using the Bill James Log5 formula applied to
Statcast expected batting average (xBA / xBAA).

Formula:
    log5(B, P, L) = (B·P/L) / (B·P/L + (1−B)·(1−P)/(1−L))

    B = batter xBA          (from MLB expectedStatistics)
    P = pitcher xBAA        (SP or team bullpen)
    L = league average xBA  (computed live each day — NOT a static value)

Hit probability:
    First 2 expected ABs use vs-SP log5.
    Remaining expected ABs use vs-bullpen log5.
    P(≥1 hit) = 1 − (1−vs_sp)^sp_abs × (1−vs_bp)^bp_abs

Pitcher assignment (verified):
    Home batters face the AWAY starter + AWAY bullpen.
    Away batters face the HOME starter + HOME bullpen.
    A batter is never scored against their own team.

SP fallback:
    When no starter is announced (TBD), batter is scored against the
    opposing team's overall pitching xBAA (all pitchers, BF-weighted).

League average:
    Computed each run as an AB-weighted mean of all qualified batters'
    xBA. Falls back to 0.248 only if fewer than 20 batters have data.

Qualification filter:
    Batter must have appeared in ≥ 50% of their team's games this season.
    (Down from 75% in the original — 75% was too strict early in the season.)

Starter vs reliever:
    A pitcher with fewer than 3 games started is classified as a reliever
    for the bullpen xBAA calculation.

OUTPUTS:
    public/data/hitters-log5-hit.json   — today's top-25 + stats
    public/data/hitters-log5-history.json — cumulative history + grades
──────────────────────────────────────────────────────────────────────────────
"""

import os
import json
import time
from datetime import date, timedelta, timezone, datetime

import requests

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(BASE_DIR, '..', 'public', 'data')
MAIN_JSON = os.path.join(DATA_DIR, 'hitters-log5-hit.json')
HIST_JSON = os.path.join(DATA_DIR, 'hitters-log5-history.json')

os.makedirs(DATA_DIR, exist_ok=True)

MLB_API             = 'https://statsapi.mlb.com/api/v1'
SEASON              = date.today().year
PREV_SEA            = SEASON - 1
TOP_N               = 25
QUALIFY_THRESHOLD   = 0.50   # batter must have played ≥ 50% of team games
STARTER_THRESHOLD   = 3      # fewer than this many GS → classified as reliever
SLEEP_S             = 0.15   # polite pause between API calls
FALLBACK_LEAGUE_AVG = 0.248  # used only if live avg cannot be computed


# ═══════════════════════════════════════════════════════════════════════════════
#  MLB API HELPERS
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
        dt_et  = dt_utc - timedelta(hours=4)   # EDT
        hour   = dt_et.hour % 12 or 12
        ampm   = 'AM' if dt_et.hour < 12 else 'PM'
        return f'{hour}:{dt_et.minute:02d} {ampm} ET'
    except Exception:
        return 'TBD'


# ═══════════════════════════════════════════════════════════════════════════════
#  DATA FETCHERS
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_schedule(today_str):
    """
    Fetch today's regular-season games with probable pitchers.
    Returns a list of game dicts with team IDs, SP IDs, game times.
    """
    print(f'  Fetching schedule for {today_str}...')
    data  = mlb_get('/schedule', {
        'sportId': 1,
        'date':    today_str,
        'hydrate': 'probablePitcher,team',
    })
    games = []
    for d in data.get('dates', []):
        for g in d.get('games', []):
            if g.get('gameType') != 'R':
                continue
            home = g['teams']['home']
            away = g['teams']['away']
            home_sp = home.get('probablePitcher', {})
            away_sp = away.get('probablePitcher', {})
            games.append({
                'game_pk':        g['gamePk'],
                'game_date':      g.get('gameDate', ''),
                'home_team_id':   home['team']['id'],
                'home_team_name': home['team']['name'],
                'home_team_abbr': home['team'].get('abbreviation', '?'),
                'away_team_id':   away['team']['id'],
                'away_team_name': away['team']['name'],
                'away_team_abbr': away['team'].get('abbreviation', '?'),
                'home_sp_id':     home_sp.get('id'),
                'home_sp_name':   home_sp.get('fullName', 'TBD'),
                'away_sp_id':     away_sp.get('id'),
                'away_sp_name':   away_sp.get('fullName', 'TBD'),
            })
    print(f'  ✓ {len(games)} regular-season game(s) found')
    return games


def fetch_team_games_played():
    """
    Returns {str(team_id): games_played} from current standings.
    Used for the 50% qualification filter.
    """
    team_gp = {}
    for league_id in [103, 104]:
        try:
            data = mlb_get('/standings', {
                'leagueId':     league_id,
                'season':       SEASON,
                'standingsType': 'regularSeason',
            })
            for record in data.get('records', []):
                for tr in record.get('teamRecords', []):
                    tid = str(tr['team']['id'])
                    gp  = (tr.get('wins', 0) or 0) + (tr.get('losses', 0) or 0)
                    team_gp[tid] = gp
        except Exception as e:
            print(f'    WARN standings league {league_id}: {e}')
    return team_gp


def fetch_roster(team_id):
    """Active roster for a team. Returns list of {id, fullName, position_code}."""
    try:
        data    = mlb_get(f'/teams/{team_id}/roster', {'rosterType': 'active'})
        players = []
        for p in data.get('roster', []):
            players.append({
                'id':            p['person']['id'],
                'fullName':      p['person']['fullName'],
                'position_code': p.get('position', {}).get('code', ''),
            })
        return players
    except Exception as e:
        print(f'    WARN roster team {team_id}: {e}')
        return []


def fetch_player_season_hitting(pid):
    """
    Season hitting stats: gamesPlayed, atBats.
    Tries SEASON first; falls back to PREV_SEA if fewer than 5 games.
    """
    def _pull(season):
        try:
            data = mlb_get(f'/people/{pid}/stats', {
                'stats': 'season', 'group': 'hitting', 'season': season,
            })
            splits = (data.get('stats', [{}])[0]
                          .get('splits', [{}]) or [{}])
            if not splits:
                return None
            s  = splits[0].get('stat', {})
            gp = int(s.get('gamesPlayed') or 0)
            ab = int(s.get('atBats') or 0)
            if gp < 5:
                return None
            return {'games_played': gp, 'at_bats': ab}
        except Exception:
            return None
    return _pull(SEASON) or _pull(PREV_SEA) or {}


def fetch_player_xba(pid):
    """
    Statcast expected batting average (xBA) for a batter.
    Stored as 'avg' in the expectedStatistics stat type.
    Tries SEASON first; falls back to PREV_SEA.
    """
    def _pull(season):
        try:
            data = mlb_get(f'/people/{pid}/stats', {
                'stats': 'expectedStatistics',
                'group': 'hitting',
                'season': season,
            })
            splits = (data.get('stats', [{}])[0]
                          .get('splits', [{}]) or [{}])
            if not splits:
                return None
            val = splits[0].get('stat', {}).get('avg')
            if val is None:
                return None
            return float(val)
        except Exception:
            return None
    return _pull(SEASON) or _pull(PREV_SEA)


def fetch_player_xbaa(pid):
    """
    Statcast expected batting average against (xBAA) for a pitcher.
    Same endpoint but group=pitching.
    """
    def _pull(season):
        try:
            data = mlb_get(f'/people/{pid}/stats', {
                'stats': 'expectedStatistics',
                'group': 'pitching',
                'season': season,
            })
            splits = (data.get('stats', [{}])[0]
                          .get('splits', [{}]) or [{}])
            if not splits:
                return None
            val = splits[0].get('stat', {}).get('avg')
            if val is None:
                return None
            return float(val)
        except Exception:
            return None
    return _pull(SEASON) or _pull(PREV_SEA)


def fetch_pitcher_season_stats(pid):
    """
    Season pitching stats: gamesStarted, battersFaced.
    Used to classify starters vs relievers for bullpen calculation.
    """
    try:
        data = mlb_get(f'/people/{pid}/stats', {
            'stats': 'season', 'group': 'pitching', 'season': SEASON,
        })
        splits = (data.get('stats', [{}])[0]
                      .get('splits', [{}]) or [{}])
        if not splits:
            return {'games_started': 0, 'batters_faced': 0}
        s = splits[0].get('stat', {})
        return {
            'games_started': int(s.get('gamesStarted') or 0),
            'batters_faced': int(s.get('battersFaced') or 0),
        }
    except Exception:
        return {'games_started': 0, 'batters_faced': 0}


def fetch_team_pitching(team_id):
    """
    Compute BF-weighted xBAA for a team's entire staff (overall) and
    bullpen-only (relievers = games_started < STARTER_THRESHOLD).

    Returns {'overall': float|None, 'bullpen': float|None}
    """
    roster = fetch_roster(team_id)
    pitchers = [p for p in roster if p['position_code'] in ('1', 'P')]

    overall_num = 0.0;  overall_den = 0
    bullpen_num = 0.0;  bullpen_den = 0

    for pitcher in pitchers:
        pid = pitcher['id']

        season_stats = fetch_pitcher_season_stats(pid)
        time.sleep(SLEEP_S)
        bf = season_stats.get('batters_faced', 0)
        gs = season_stats.get('games_started', 0)
        if bf == 0:
            continue

        xbaa = fetch_player_xbaa(pid)
        time.sleep(SLEEP_S)
        if xbaa is None:
            continue

        overall_num += xbaa * bf
        overall_den += bf

        if gs < STARTER_THRESHOLD:
            bullpen_num += xbaa * bf
            bullpen_den += bf

    return {
        'overall': round(overall_num / overall_den, 4) if overall_den > 0 else None,
        'bullpen': round(bullpen_num / bullpen_den, 4) if bullpen_den > 0 else None,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  LOG5 FORMULA AND HIT PROBABILITY
# ═══════════════════════════════════════════════════════════════════════════════

def log5(b, p, l):
    """
    Bill James Log5 formula.
    Returns the expected batting average for batter B vs pitcher P
    given league baseline L.

    log5(B, P, L) = (B·P/L) / (B·P/L + (1−B)·(1−P)/(1−L))
    """
    if l <= 0 or l >= 1 or b <= 0 or p <= 0:
        return None
    numerator   = (b * p) / l
    denominator = numerator + ((1 - b) * (1 - p)) / (1 - l)
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def compute_hit_prob(vs_sp, vs_bp, ab_per_game):
    """
    P(at least 1 hit in today's expected at-bats).

    First min(2, ab_per_game) ABs use vs-SP log5 probability.
    Remaining ABs use vs-bullpen log5 probability.

    P(≥1 hit) = 1 − P(0 hits vs SP) × P(0 hits vs bullpen)
              = 1 − (1−vs_sp)^sp_abs × (1−vs_bp)^bp_abs
    """
    if ab_per_game <= 0 or vs_sp is None:
        return None
    sp_abs = min(2.0, ab_per_game)
    bp_abs = max(0.0, ab_per_game - 2.0)
    p_no_hit_sp = (1 - vs_sp) ** sp_abs
    p_no_hit_bp = (1 - vs_bp) ** bp_abs if (bp_abs > 0 and vs_bp is not None) else 1.0
    return round(1 - (p_no_hit_sp * p_no_hit_bp), 4)


# ═══════════════════════════════════════════════════════════════════════════════
#  LEAGUE AVERAGE COMPUTATION
# ═══════════════════════════════════════════════════════════════════════════════

def compute_league_avg(all_batters):
    """
    Compute the live league-average xBA as an AB-weighted mean of all
    collected batters' xBA values.  Falls back to FALLBACK_LEAGUE_AVG
    if fewer than 20 batters have usable data.

    This replaces the static 0.248 constant from the original model.
    """
    pairs = [
        (b['xba'], b['at_bats'])
        for b in all_batters
        if b.get('xba') is not None and b.get('at_bats', 0) >= 10
    ]
    if len(pairs) < 20:
        print(f'  WARN: only {len(pairs)} batters for league avg — using fallback {FALLBACK_LEAGUE_AVG}')
        return FALLBACK_LEAGUE_AVG
    total_ab  = sum(ab for _, ab in pairs)
    weighted  = sum(xba * ab for xba, ab in pairs)
    league_avg = round(weighted / total_ab, 4) if total_ab > 0 else FALLBACK_LEAGUE_AVG
    print(f'  Live league avg xBA: {league_avg} (from {len(pairs)} batters, {total_ab} AB)')
    return league_avg


# ═══════════════════════════════════════════════════════════════════════════════
#  HISTORY AND AUTO-GRADING
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
    Auto-grade yesterday's picks: check if each predicted batter got ≥1 hit
    using the MLB Stats API box score. Skips if already graded.
    """
    record = next((r for r in history['records'] if r['date'] == yesterday_str), None)
    if not record or record.get('graded'):
        return

    print(f'  Grading picks for {yesterday_str}...')
    # Fetch schedule first to get game PKs, then each box score directly.
    # Hydrating boxscore through the schedule endpoint is unreliable.
    try:
        sched_meta = mlb_get('/schedule', {'sportId': 1, 'date': yesterday_str})
    except Exception as e:
        print(f'    WARN: could not fetch box scores: {e}')
        return

    game_pks = [
        g['gamePk']
        for d in sched_meta.get('dates', [])
        for g in d.get('games', [])
    ]

    # Build {player_name: hits} from direct box score fetches
    hit_lookup = {}
    for pk in game_pks:
        try:
            box = mlb_get(f'/game/{pk}/boxscore')
            for side in ['home', 'away']:
                for _pid, pdata in (box.get('teams', {})
                                       .get(side, {})
                                       .get('players', {}).items()):
                    name = pdata.get('person', {}).get('fullName', '')
                    hits = int(pdata.get('stats', {})
                                    .get('batting', {})
                                    .get('hits', 0))
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

    # Bucket by hit_probability
    buckets = {'70%+': [], '60-69%': [], '50-59%': [], '<50%': []}
    for p in played:
        prob = p.get('hit_probability', 0)
        b    = '70%+' if prob >= 0.70 else '60-69%' if prob >= 0.60 else '50-59%' if prob >= 0.50 else '<50%'
        buckets[b].append(p['correct'])

    record['summary'] = {
        'total':        len(played),
        'hit_count':    len(hit),
        'hit_rate_pct': round(len(hit) / max(len(played), 1) * 100, 1),
        'hit_players':  [p['player'] for p in hit],
        'by_bucket':    {
            k: {
                'predicted': len(v),
                'hits':      sum(v),
                'rate_pct':  round(sum(v) / max(len(v), 1) * 100, 1),
            }
            for k, v in buckets.items() if v
        },
    }
    print(f'    ✓ {len(hit)}/{len(played)} got a hit')


def compute_alltime_stats(history, today_str):
    buckets  = {'70%+': [0, 0], '60-69%': [0, 0], '50-59%': [0, 0], '<50%': [0, 0]}
    total, hit_total = 0, 0
    for rec in history['records']:
        if rec['date'] == today_str or not rec.get('graded'):
            continue
        for p in rec.get('predictions', []):
            if p.get('actual_hits') is None:
                continue
            h        = 1 if p['correct'] else 0
            total   += 1
            hit_total += h
            prob = p.get('hit_probability', 0)
            b    = '70%+' if prob >= 0.70 else '60-69%' if prob >= 0.60 else '50-59%' if prob >= 0.50 else '<50%'
            buckets[b][0] += 1
            buckets[b][1] += h
    return {
        'total':        total,
        'hit_count':    hit_total,
        'hit_rate_pct': round(hit_total / max(total, 1) * 100, 1),
        'by_bucket':    {
            k: {
                'predicted': buckets[k][0],
                'hits':      buckets[k][1],
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

    print(f'\n══ Log5 Hit Model — {today_str} ══')
    print(f'   Qualify threshold : {int(QUALIFY_THRESHOLD * 100)}% of team games')
    print(f'   Starter threshold : {STARTER_THRESHOLD} GS')
    print(f'   Top N             : {TOP_N}')

    # ── 1. Load history and grade yesterday ───────────────────────────────────
    history = load_history()
    grade_yesterday(history, yesterday_str)

    # ── 2. Today's schedule ───────────────────────────────────────────────────
    games = fetch_schedule(today_str)
    if not games:
        print('No games today. Exiting.')
        return

    # ── 3. Team games played (for qualification filter) ───────────────────────
    print('\nFetching team games played...')
    team_gp = fetch_team_games_played()

    # ── 4. Collect all unique team and SP IDs ────────────────────────────────
    all_team_ids = set()
    all_sp_ids   = set()
    for g in games:
        all_team_ids.add(g['home_team_id'])
        all_team_ids.add(g['away_team_id'])
        if g['home_sp_id']:
            all_sp_ids.add(g['home_sp_id'])
        if g['away_sp_id']:
            all_sp_ids.add(g['away_sp_id'])

    # ── 5. Fetch SP xBAA (individual SPs) ────────────────────────────────────
    print(f'\nFetching xBAA for {len(all_sp_ids)} starting pitcher(s)...')
    sp_xbaa_map = {}   # pid → xbaa float
    for pid in all_sp_ids:
        sp_xbaa_map[pid] = fetch_player_xbaa(pid)
        time.sleep(SLEEP_S)

    # ── 6. Fetch team pitching (overall + bullpen xBAA) ───────────────────────
    print(f'\nFetching team pitching xBAA for {len(all_team_ids)} team(s)...')
    team_pitching = {}   # team_id → {'overall': float|None, 'bullpen': float|None}
    for team_id in all_team_ids:
        print(f'  Team {team_id}...')
        team_pitching[team_id] = fetch_team_pitching(team_id)
        tp = team_pitching[team_id]
        print(f'    overall xBAA: {tp["overall"]}  bullpen xBAA: {tp["bullpen"]}')

    # ── 7. Fetch batter data for all teams ────────────────────────────────────
    print(f'\nFetching batter data...')
    # all_batter_data: list of batter dicts with xba, games_played, at_bats, team_id
    all_batter_data = []   # all batters collected (used for league avg)
    # batter_map: {team_id: [batter_dict, ...]}
    batter_map = {}

    for team_id in all_team_ids:
        roster  = fetch_roster(team_id)
        batters = [p for p in roster if p['position_code'] not in ('1', 'P')]
        batter_map[team_id] = []

        for player in batters:
            pid  = player['id']
            name = player['fullName']

            season = fetch_player_season_hitting(pid)
            time.sleep(SLEEP_S)
            xba = fetch_player_xba(pid)
            time.sleep(SLEEP_S)

            if not season or xba is None:
                continue

            gp     = season.get('games_played', 0)
            ab     = season.get('at_bats', 0)
            ab_pg  = round(ab / gp, 3) if gp > 0 else 0.0

            batter_dict = {
                'pid':          pid,
                'name':         name,
                'team_id':      team_id,
                'xba':          xba,
                'games_played': gp,
                'at_bats':      ab,
                'ab_per_game':  ab_pg,
            }
            batter_map[team_id].append(batter_dict)
            all_batter_data.append(batter_dict)

    # ── 8. Compute live league average xBA ────────────────────────────────────
    league_avg = compute_league_avg(all_batter_data)

    # ── 9. Score each batter ──────────────────────────────────────────────────
    print(f'\nComputing Log5 matchups (league avg xBA: {league_avg})...')
    all_candidates = []

    for g in games:
        home_id   = g['home_team_id']
        away_id   = g['away_team_id']
        home_abbr = g['home_team_abbr']
        away_abbr = g['away_team_abbr']
        matchup   = f'{away_abbr} @ {home_abbr}'
        game_time = get_game_time_et(g['game_date'])

        # PITCHER ASSIGNMENT:
        #   Home batters face → AWAY SP + AWAY bullpen
        #   Away batters face → HOME SP + HOME bullpen
        home_sp_id   = g['home_sp_id']    # faces AWAY batters
        home_sp_name = g['home_sp_name']
        away_sp_id   = g['away_sp_id']    # faces HOME batters
        away_sp_name = g['away_sp_name']

        print(f'\n  ── {matchup} ({game_time}) ──')
        print(f'    SP vs {home_abbr} batters: {away_sp_name or "TBD"}')
        print(f'    SP vs {away_abbr} batters: {home_sp_name or "TBD"}')

        # For each side:
        # (batting_team_id, opp_sp_id, opp_sp_name, opp_team_id, team_abbr, side_label)
        sides = [
            {
                'batting_team_id':   home_id,
                'team_abbr':         home_abbr,
                'opp_sp_id':         away_sp_id,    # AWAY SP faces HOME batters
                'opp_sp_name':       away_sp_name,
                'opp_team_id':       away_id,        # AWAY bullpen faces HOME batters
                'opp_team_abbr':     away_abbr,
            },
            {
                'batting_team_id':   away_id,
                'team_abbr':         away_abbr,
                'opp_sp_id':         home_sp_id,    # HOME SP faces AWAY batters
                'opp_sp_name':       home_sp_name,
                'opp_team_id':       home_id,        # HOME bullpen faces AWAY batters
                'opp_team_abbr':     home_abbr,
            },
        ]

        for side in sides:
            batting_tid  = side['batting_team_id']
            opp_tid      = side['opp_team_id']
            opp_gp_key   = str(opp_tid)

            # Opposing SP xBAA (with fallback to team overall)
            opp_sp_id   = side['opp_sp_id']
            sp_xbaa_val = sp_xbaa_map.get(opp_sp_id) if opp_sp_id else None
            sp_source   = 'sp' if sp_xbaa_val is not None else 'team_overall'
            if sp_xbaa_val is None:
                sp_xbaa_val = team_pitching.get(opp_tid, {}).get('overall')
            opp_sp_display = side['opp_sp_name'] if opp_sp_id else 'TBD'

            # Opposing bullpen xBAA
            bp_xbaa_val = team_pitching.get(opp_tid, {}).get('bullpen')

            # Qualification: batter must have played ≥ 50% of their team's games
            batting_gp = team_gp.get(str(batting_tid), 0)

            batters = batter_map.get(batting_tid, [])
            for batter in batters:
                if batting_gp > 0:
                    min_gp = batting_gp * QUALIFY_THRESHOLD
                    if batter['games_played'] < min_gp:
                        continue

                bxba      = batter['xba']
                ab_pg     = batter['ab_per_game']
                sp_abs    = round(min(2.0, ab_pg), 3)
                bp_abs    = round(max(0.0, ab_pg - 2.0), 3)

                vs_sp = log5(bxba, sp_xbaa_val, league_avg) if sp_xbaa_val else None
                vs_bp = log5(bxba, bp_xbaa_val, league_avg) if bp_xbaa_val else None
                hit_prob = compute_hit_prob(vs_sp, vs_bp, ab_pg)

                if hit_prob is None:
                    continue

                all_candidates.append({
                    'player':           batter['name'],
                    'team':             side['team_abbr'],
                    'game':             matchup,
                    'game_time':        game_time,
                    'opposing_team':    side['opp_team_abbr'],
                    'opposing_sp_name': opp_sp_display,
                    'sp_xbaa_source':   sp_source,
                    'batter_xba':       bxba,
                    'sp_xbaa':          sp_xbaa_val,
                    'bullpen_xbaa':     bp_xbaa_val,
                    'vs_sp_log5':       vs_sp,
                    'vs_bullpen_log5':  vs_bp,
                    'hit_probability':  hit_prob,
                    'games_played':     batter['games_played'],
                    'team_games':       batting_gp,
                    'at_bats':          batter['at_bats'],
                    'ab_per_game':      ab_pg,
                    'sp_abs':           sp_abs,
                    'bp_abs':           bp_abs,
                    'league_avg_xba':   league_avg,
                    'actual_hits':      None,
                    'correct':          None,
                })

    # ── 10. Sort and take top N ───────────────────────────────────────────────
    all_candidates.sort(key=lambda x: x['hit_probability'], reverse=True)
    top_n = all_candidates[:TOP_N]
    for i, p in enumerate(top_n):
        p['rank'] = i + 1

    print(f'\n✓ {len(all_candidates)} qualified batters scored → top {len(top_n)} selected')

    # ── 11. Persist today's record in history ─────────────────────────────────
    today_record_preds = [
        {
            'rank':            p['rank'],
            'player':          p['player'],
            'team':            p['team'],
            'hit_probability': p['hit_probability'],
            'actual_hits':     None,
            'correct':         None,
        }
        for p in top_n
    ]
    existing = next((r for r in history['records'] if r['date'] == today_str), None)
    if existing:
        existing['predictions']   = today_record_preds
        existing['league_avg_xba'] = league_avg
        existing['graded']        = False
    else:
        history['records'].append({
            'date':            today_str,
            'graded':          False,
            'league_avg_xba': league_avg,
            'predictions':     today_record_preds,
        })
    history['records'].sort(key=lambda r: r['date'], reverse=True)
    save_history(history)

    # ── 12. Build summary stats ───────────────────────────────────────────────
    yday_record  = next((r for r in history['records'] if r['date'] == yesterday_str), None)
    yday_summary = yday_record.get('summary', {}) if yday_record else {}
    alltime      = compute_alltime_stats(history, today_str)

    # ── 13. Write main output JSON ────────────────────────────────────────────
    output = {
        'updated':         datetime.now(timezone.utc).isoformat(),
        'date':            today_str,
        'league_avg_xba':  league_avg,
        'predictions':     top_n,
        'yesterday':       {'date': yesterday_str, **yday_summary},
        'alltime':         alltime,
    }
    with open(MAIN_JSON, 'w') as f:
        json.dump(output, f, indent=2)

    print(f'✓ Wrote {len(top_n)} predictions → {MAIN_JSON}')
    if alltime['total'] > 0:
        print(f'  All-time: {alltime["hit_count"]}/{alltime["total"]} '
              f'got a hit ({alltime["hit_rate_pct"]} %)')


if __name__ == '__main__':
    run()
