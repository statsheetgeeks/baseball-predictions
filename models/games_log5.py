"""
models/games_log5.py
──────────────────────────────────────────────────────────────────────────────
Log5 Game Model — Chalk Line Labs
──────────────────────────────────────────────────────────────────────────────
Workflow (runs daily at 9 AM CT (14:00 UTC) via GitHub Actions):
  1. Load historical predictions from public/data/games-log5-history.json
  2. Fetch yesterday's final scores from MLB StatsAPI
  3. Grade yesterday's picks → update history file
  4. Fetch today's schedule + current standings
  5. Apply Log5 formula to generate today's predictions
  6. Compute all-time + yesterday accuracy stats (by confidence band)
  7. Write public/data/games-log5.json  (read by the Next.js page)
  8. Write public/data/games-log5-history.json (persistent record)
──────────────────────────────────────────────────────────────────────────────
"""

import json
import os
import statsapi
from datetime import date, timedelta, timezone, datetime

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(BASE_DIR, '..', 'public', 'data')
MAIN_JSON  = os.path.join(DATA_DIR, 'games-log5.json')
HIST_JSON  = os.path.join(DATA_DIR, 'games-log5-history.json')

CONFIDENCE_BANDS = [
    ('50-59%', 0.50, 0.60),
    ('60-69%', 0.60, 0.70),
    ('70-79%', 0.70, 0.80),
    ('80%+',   0.80, 1.01),
]

# ── Log5 formula ──────────────────────────────────────────────────────────────
def log5(pct_a, pct_b):
    """P(A beats B) given each team's season win percentage."""
    denom = pct_a + pct_b - 2 * pct_a * pct_b
    return (pct_a - pct_a * pct_b) / denom if denom else 0.5

# ── Helpers ───────────────────────────────────────────────────────────────────
def get_standings_lookup():
    """Return {team_name: win_pct} using current MLB standings."""
    standings = statsapi.standings_data()
    lookup = {}
    for div_data in standings.values():
        for team in div_data['teams']:
            w, l = team['w'], team['l']
            lookup[team['name']] = w / (w + l) if (w + l) > 0 else 0.500
    return lookup

def get_game_time(game):
    """Return a friendly game time string (e.g. '7:10 PM ET')."""
    raw = game.get('game_datetime', '')
    if not raw:
        return 'TBD'
    try:
        # game_datetime is UTC; convert to ET (UTC-4 during EDT)
        dt_utc = datetime.strptime(raw[:19], '%Y-%m-%dT%H:%M:%S')
        dt_et  = dt_utc - timedelta(hours=4)
        suffix = 'AM' if dt_et.hour < 12 else 'PM'
        hour   = dt_et.hour % 12 or 12
        return f"{hour}:{dt_et.minute:02d} {suffix} ET"
    except Exception:
        return 'TBD'

def band_for(confidence):
    """Return the label of the confidence band this pick falls into."""
    for label, lo, hi in CONFIDENCE_BANDS:
        if lo <= confidence < hi:
            return label
    return '80%+'

def compute_stats(games_list):
    """
    Given a list of graded game dicts, return:
      { total: {wins, losses, total}, by_confidence: [...] }
    """
    total_w = total_l = 0
    bands = {label: [0, 0] for label, _, _ in CONFIDENCE_BANDS}

    for g in games_list:
        if g.get('correct') is None:
            continue  # postponed / unresolved
        w = 1 if g['correct'] else 0
        l = 0 if g['correct'] else 1
        total_w += w
        total_l += l
        b = band_for(g['confidence'])
        bands[b][0] += w
        bands[b][1] += l

    by_conf = []
    for label, _, _ in CONFIDENCE_BANDS:
        bw, bl = bands[label]
        bt = bw + bl
        by_conf.append({
            'band':   label,
            'wins':   bw,
            'losses': bl,
            'total':  bt,
        })

    return {
        'total': {
            'wins':   total_w,
            'losses': total_l,
            'total':  total_w + total_l,
        },
        'by_confidence': by_conf,
    }

# ── History I/O ───────────────────────────────────────────────────────────────
def load_history():
    if os.path.exists(HIST_JSON):
        with open(HIST_JSON) as f:
            return json.load(f)
    return {'records': []}

def save_history(history):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HIST_JSON, 'w') as f:
        json.dump(history, f, indent=2)

# ── Grade yesterday's picks ────────────────────────────────────────────────────
def grade_yesterday(history):
    """
    Look up yesterday's date in history. If we have ungraded predictions,
    fetch final scores from MLB API and mark each game correct/incorrect.
    Returns the graded list (or empty list if nothing to grade).
    """
    yesterday = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')
    record = next((r for r in history['records'] if r['date'] == yesterday), None)
    if not record:
        return []

    # Check if already graded
    if all(g.get('correct') is not None for g in record['games']):
        return record['games']

    # Fetch final scores for yesterday
    yday_str = (date.today() - timedelta(days=1)).strftime('%m/%d/%Y')
    try:
        results = statsapi.schedule(date=yday_str)
    except Exception as e:
        print(f"  ⚠ Could not fetch yesterday's results: {e}")
        return record['games']

    # Build result lookup: (away, home) → winning team name
    winner_lookup = {}
    for game in results:
        status = game.get('status', '')
        if status not in ('Final', 'Game Over', 'Completed Early'):
            continue
        away_score = game.get('away_score')
        home_score = game.get('home_score')
        if away_score is None or home_score is None:
            continue
        winner = game['away_name'] if away_score > home_score else game['home_name']
        key = (game['away_name'], game['home_name'])
        winner_lookup[key] = winner

    # Grade each pick
    for g in record['games']:
        key = (g['away_team'], g['home_team'])
        actual = winner_lookup.get(key)
        if actual is not None:
            g['actual_winner'] = actual
            g['correct']       = (actual == g['pick'])
        # else: postponed or not final — leave as None

    return record['games']

# ── Today's predictions ────────────────────────────────────────────────────────
def build_today_predictions(pct_lookup):
    today_str = date.today().strftime('%m/%d/%Y')
    try:
        games = statsapi.schedule(date=today_str)
    except Exception as e:
        print(f"  ⚠ Could not fetch today's schedule: {e}")
        return []

    predictions = []
    for game in games:
        away = game['away_name']
        home = game['home_name']
        away_pct = pct_lookup.get(away, 0.500)
        home_pct = pct_lookup.get(home, 0.500)

        away_prob = log5(away_pct, home_pct)
        home_prob = log5(home_pct, away_pct)

        if away_prob >= home_prob:
            pick       = away
            confidence = away_prob
        else:
            pick       = home
            confidence = home_prob

        predictions.append({
            'game_time':    get_game_time(game),
            'away_team':    away,
            'home_team':    home,
            'away_pct':     round(away_pct, 3),
            'home_pct':     round(home_pct, 3),
            'away_prob':    round(away_prob, 4),
            'home_prob':    round(home_prob, 4),
            'pick':         pick,
            'confidence':   round(confidence, 4),
            # These get filled in when graded tomorrow:
            'actual_winner': None,
            'correct':       None,
        })

    return predictions

# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    os.makedirs(DATA_DIR, exist_ok=True)
    today = date.today().strftime('%Y-%m-%d')
    yesterday = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')

    # 1. Load history
    print("Loading history...")
    history = load_history()

    # 2. Grade yesterday (mutates history in-place via dict reference)
    print(f"Grading {yesterday} picks...")
    grade_yesterday(history)

    # 3. Build today's predictions
    print("Fetching standings + today's schedule...")
    pct_lookup   = get_standings_lookup()
    today_preds  = build_today_predictions(pct_lookup)
    print(f"  → {len(today_preds)} games found for {today}")

    # 4. Upsert today's record in history
    existing_today = next((r for r in history['records'] if r['date'] == today), None)
    if existing_today:
        existing_today['games'] = today_preds
    else:
        history['records'].append({'date': today, 'games': today_preds})

    # Keep history sorted newest-first
    history['records'].sort(key=lambda r: r['date'], reverse=True)
    save_history(history)
    print("✓ History saved")

    # 5. Compute all-time stats (all graded games across all days)
    all_graded = [
        g
        for r in history['records']
        for g in r['games']
        if r['date'] != today and g.get('correct') is not None
    ]
    alltime_stats = compute_stats(all_graded)

    # 6. Build yesterday block (unresolved is still useful to show)
    yday_record = next((r for r in history['records'] if r['date'] == yesterday), None)
    yday_games  = yday_record['games'] if yday_record else []
    yday_stats  = compute_stats(yday_games)

    # 7. Write main JSON
    output = {
        'updated':     datetime.now(timezone.utc).isoformat(),
        'date':        today,
        'predictions': today_preds,
        'yesterday': {
            'date':  yesterday,
            **yday_stats,
        },
        'alltime': alltime_stats,
    }

    with open(MAIN_JSON, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"✓ Wrote {len(today_preds)} predictions → games-log5.json")
    print(f"  All-time: {alltime_stats['total']['wins']}-{alltime_stats['total']['losses']}")
    if yday_stats['total']['total'] > 0:
        pct = yday_stats['total']['wins'] / yday_stats['total']['total']
        print(f"  Yesterday: {yday_stats['total']['wins']}-{yday_stats['total']['losses']} ({pct:.1%})")

if __name__ == '__main__':
    run()
