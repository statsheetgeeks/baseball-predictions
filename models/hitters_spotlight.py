"""
models/hitters_spotlight.py
──────────────────────────────────────────────────────────────────────────────
Chalk Line Labs — Hitters Spotlight Aggregator

Identifies "Spotlight Hitters": players who appear in the top 25 of two or
more of the four daily hitter model predictions.

IMPORTANT: This script makes ZERO MLB API calls.
  - Today's spotlight is derived by reading the four main prediction JSONs
    that the four hitter model scripts have already written this morning.
  - Yesterday's grading is derived by reading the four history JSONs that
    the individual model scripts have already graded this morning.
    No box-score fetch needed here.

Field name reference (confirmed against individual model scripts):
  Log5 Hit history   : actual_hits (int), correct (bool)
  ML Hit history     : actual_hits (int), correct (bool)
  HR Model history   : actual_hr   (int), correct (bool)
  ML HR history      : actual_hr   (int), correct (bool)

Run order: must run AFTER all four hitter models in run-models.yml.

OUTPUTS:
  public/data/hitters-spotlight-history.json
──────────────────────────────────────────────────────────────────────────────
"""

import json
import os
from collections import defaultdict
from datetime import date, timedelta

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(BASE_DIR, '..', 'public', 'data')
SPOT_HIST = os.path.join(DATA_DIR, 'hitters-spotlight-history.json')

# Four prediction JSONs (today's top-25 lists)
PRED_FILES = {
    'Log5 Hit': os.path.join(DATA_DIR, 'hitters-log5-hit.json'),
    'ML Hit':   os.path.join(DATA_DIR, 'hitters-ml-hit.json'),
    'HR Model': os.path.join(DATA_DIR, 'hitters-hr-model.json'),
    'ML HR':    os.path.join(DATA_DIR, 'hitters-ml-hr.json'),
}

# Four history JSONs (yesterday's graded records)
HIST_FILES = {
    'Log5 Hit': os.path.join(DATA_DIR, 'hitters-log5-history.json'),
    'ML Hit':   os.path.join(DATA_DIR, 'hitters-ml-hit-history.json'),
    'HR Model': os.path.join(DATA_DIR, 'hitters-hr-history.json'),
    'ML HR':    os.path.join(DATA_DIR, 'hitters-ml-hr-history.json'),
}

# Which field means "got a hit" and "got a HR" in each history file
HIT_FIELD = {
    'Log5 Hit': 'actual_hits',
    'ML Hit':   'actual_hits',
    'HR Model': 'actual_hr',
    'ML HR':    'actual_hr',
}
# Models that track hits (not HRs as their primary event)
HIT_MODELS = {'Log5 Hit', 'ML Hit'}
HR_MODELS  = {'HR Model', 'ML HR'}

MIN_APPEARANCES = 2   # must appear in this many lists to be a spotlight hitter


def _load_json(path):
    """Load a JSON file safely, return None if missing or malformed."""
    if not os.path.exists(path):
        print(f'  WARN: {path} not found — skipping')
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        print(f'  WARN: could not load {path}: {e}')
        return None


def load_spotlight_history():
    data = _load_json(SPOT_HIST)
    if data and 'records' in data:
        return data
    return {'records': []}


def save_spotlight_history(hist):
    with open(SPOT_HIST, 'w') as f:
        json.dump(hist, f, indent=2)


# ─── Today's spotlight computation ────────────────────────────────────────────

def compute_todays_spotlight(today_str):
    """
    Read each model's top-25 predictions and find players in 2+ lists.
    Returns a sorted list of spotlight player dicts.
    """
    # name → {models: [list], team: str, ranks: {model: rank}}
    player_map = defaultdict(lambda: {'models': [], 'team': '', 'ranks': {}})

    for model_name, path in PRED_FILES.items():
        data = _load_json(path)
        if not data:
            continue
        # Check that this JSON is for today (may be stale if a model failed)
        if data.get('date') != today_str:
            print(f'  WARN: {model_name} JSON is for {data.get("date")}, '
                  f'not today ({today_str}) — still including')
        for pred in data.get('predictions', []):
            name = pred.get('player', '')
            if not name:
                continue
            player_map[name]['models'].append(model_name)
            player_map[name]['team']  = pred.get('team', '')
            player_map[name]['ranks'][model_name] = pred.get('rank', 99)

    # Filter to 2+ appearances
    spotlight = []
    for name, info in player_map.items():
        n = len(info['models'])
        if n >= MIN_APPEARANCES:
            spotlight.append({
                'player':      name,
                'team':        info['team'],
                'appearances': n,
                'models':      sorted(info['models']),
                'ranks':       info['ranks'],
                'actual_hit':  None,
                'actual_hr':   None,
            })

    # Sort: most appearances first, then alphabetically
    spotlight.sort(key=lambda x: (-x['appearances'], x['player']))
    return spotlight


# ─── Yesterday's grading ──────────────────────────────────────────────────────

def grade_yesterday_spotlight(history, yesterday_str):
    """
    Grade yesterday's spotlight players using results already stored
    in the four individual model history files. Zero API calls.
    """
    record = next((r for r in history['records'] if r['date'] == yesterday_str), None)
    if not record or record.get('graded'):
        return

    print(f'  Grading spotlight for {yesterday_str}...')

    # Build name → {actual_hits, actual_hr} from all four history files
    hit_lookup = {}   # name → bool (got ≥1 hit)
    hr_lookup  = {}   # name → bool (got ≥1 HR)

    for model_name, path in HIST_FILES.items():
        data = _load_json(path)
        if not data:
            continue
        yday_rec = next((r for r in data.get('records', [])
                         if r['date'] == yesterday_str), None)
        if not yday_rec or not yday_rec.get('graded'):
            print(f'    {model_name} history not yet graded for {yesterday_str}')
            continue

        field = HIT_FIELD[model_name]
        for pred in yday_rec.get('predictions', []):
            name = pred.get('player', '')
            if not name:
                continue
            val = pred.get(field)
            if val is None:
                continue
            if model_name in HIT_MODELS:
                # actual_hits: int — got a hit if > 0
                hit_lookup[name] = hit_lookup.get(name, False) or (val > 0)
            else:
                # actual_hr: int — got a HR if > 0
                hr_lookup[name] = hr_lookup.get(name, False) or (val > 0)
                # HR players also got a hit if they homered
                if val > 0:
                    hit_lookup[name] = True

    any_graded = bool(hit_lookup or hr_lookup)
    if not any_graded:
        print(f'    No graded history found for {yesterday_str} — deferring')
        return

    for player in record.get('players', []):
        name = player['player']
        # A spotlight player "got a hit" if any hit-tracking model recorded one,
        # OR if any HR model recorded a HR (a HR implies a hit)
        player['actual_hit'] = hit_lookup.get(name) or hr_lookup.get(name) or False
        player['actual_hr']  = hr_lookup.get(name, False)

    record['graded'] = True

    # Day summary
    played  = record['players']
    got_hit = [p for p in played if p.get('actual_hit')]
    got_hr  = [p for p in played if p.get('actual_hr')]

    by_apps = {}
    for p in played:
        n   = p.get('appearances', 2)
        key = f'{n} models'
        if key not in by_apps:
            by_apps[key] = {'total': 0, 'hits': 0, 'hrs': 0}
        by_apps[key]['total'] += 1
        if p.get('actual_hit'): by_apps[key]['hits'] += 1
        if p.get('actual_hr'):  by_apps[key]['hrs']  += 1

    record['summary'] = {
        'total':        len(played),
        'hit_count':    len(got_hit),
        'hr_count':     len(got_hr),
        'hit_rate_pct': round(len(got_hit) / max(len(played), 1) * 100, 1),
        'hr_rate_pct':  round(len(got_hr)  / max(len(played), 1) * 100, 1),
        'hit_players':  [p['player'] for p in got_hit],
        'hr_players':   [p['player'] for p in got_hr],
        'by_appearances': {
            k: {
                'total':        v['total'],
                'hits':         v['hits'],
                'hrs':          v['hrs'],
                'hit_rate_pct': round(v['hits'] / max(v['total'], 1) * 100, 1),
                'hr_rate_pct':  round(v['hrs']  / max(v['total'], 1) * 100, 1),
            }
            for k, v in by_apps.items()
        },
    }

    print(f'    ✓ {len(got_hit)}/{len(played)} got a hit, '
          f'{len(got_hr)}/{len(played)} hit a HR')


# ─── All-time stats ───────────────────────────────────────────────────────────

def compute_alltime(history, today_str):
    total = hit_total = hr_total = 0
    by_apps = {}   # '2 models', '3 models', '4 models'

    for rec in history['records']:
        if rec['date'] == today_str or not rec.get('graded'):
            continue
        for p in rec.get('players', []):
            if p.get('actual_hit') is None:
                continue
            total    += 1
            hit_total += 1 if p['actual_hit'] else 0
            hr_total  += 1 if p['actual_hr']  else 0
            n   = p.get('appearances', 2)
            key = f'{n} models'
            if key not in by_apps:
                by_apps[key] = {'total': 0, 'hits': 0, 'hrs': 0}
            by_apps[key]['total'] += 1
            if p.get('actual_hit'): by_apps[key]['hits'] += 1
            if p.get('actual_hr'):  by_apps[key]['hrs']  += 1

    return {
        'total':        total,
        'hit_count':    hit_total,
        'hr_count':     hr_total,
        'hit_rate_pct': round(hit_total / max(total, 1) * 100, 1),
        'hr_rate_pct':  round(hr_total  / max(total, 1) * 100, 1),
        'by_appearances': {
            k: {
                'total':        v['total'],
                'hits':         v['hits'],
                'hrs':          v['hrs'],
                'hit_rate_pct': round(v['hits'] / max(v['total'], 1) * 100, 1),
                'hr_rate_pct':  round(v['hrs']  / max(v['total'], 1) * 100, 1),
            }
            for k, v in sorted(by_apps.items(), reverse=True)
        },
    }


# ─── Main ────────────────────────────────────────────────────────────────────

def run():
    today_str     = date.today().isoformat()
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()

    print(f'\n══ Hitters Spotlight — {today_str} ══')

    history = load_spotlight_history()

    # Grade yesterday (reads from already-graded model histories)
    grade_yesterday_spotlight(history, yesterday_str)

    # Compute today's spotlight
    print('\nComputing today\'s spotlight...')
    spotlight = compute_todays_spotlight(today_str)
    print(f'  ✓ {len(spotlight)} spotlight hitter(s) found '
          f'({sum(1 for p in spotlight if p["appearances"] >= 3)} in 3+ models)')

    # Persist today's record
    existing = next((r for r in history['records'] if r['date'] == today_str), None)
    if existing:
        existing['players'] = spotlight
        existing['graded']  = False
    else:
        history['records'].append({
            'date':    today_str,
            'graded':  False,
            'players': spotlight,
        })
    history['records'].sort(key=lambda r: r['date'], reverse=True)

    # Build output
    yday_record  = next((r for r in history['records'] if r['date'] == yesterday_str), None)
    yday_summary = yday_record.get('summary', {}) if yday_record else {}
    alltime      = compute_alltime(history, today_str)

    history['yesterday'] = {'date': yesterday_str, **yday_summary}
    history['alltime']   = alltime

    save_spotlight_history(history)
    print(f'✓ Spotlight history saved → {SPOT_HIST}')

    if spotlight:
        for p in spotlight[:5]:
            print(f'  {p["player"]} ({p["team"]}) — '
                  f'{p["appearances"]} models: {", ".join(p["models"])}')
        if len(spotlight) > 5:
            print(f'  ... and {len(spotlight) - 5} more')


if __name__ == '__main__':
    run()
