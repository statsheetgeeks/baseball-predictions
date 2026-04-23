"""
models/games_composite.py
──────────────────────────────────────────────────────────────────────────────
Composite Game Model — Chalk Line Labs

Reads the daily output of all four game models and combines them into a
majority-vote composite prediction for each game.

Must run LAST in the GitHub Actions workflow, after all four base models
have written their JSON files.

Composite winner logic:
  - Each model votes for a team (its pick)
  - 3+ votes → majority winner
  - 2-2 tie → team with higher average composite confidence wins
  - Each model contributes a "support" value for the composite winner:
      picked composite winner → use model's confidence directly
      picked other team       → use 1 − model's confidence (implied prob)
  - Composite confidence = average of all four support values

Top 3 picks:
  The three games with the highest composite_confidence for today.
  Displayed as featured cards at the top of the composite page.
  Predictions are sorted by composite_confidence descending so the
  page always shows the top 3 first.

Model standings:
  Reads all four model history files, ranks by all-time win percentage.
  Included in the output JSON for use in the results section.
──────────────────────────────────────────────────────────────────────────────
"""

import json
import os
from datetime import date, timedelta, timezone, datetime

import requests

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(BASE_DIR, '..', 'public', 'data')
MAIN_JSON = os.path.join(DATA_DIR, 'games-composite.json')
HIST_JSON = os.path.join(DATA_DIR, 'games-composite-history.json')

MLB_API = 'https://statsapi.mlb.com/api/v1'

MODEL_FILES = {
    'log5':          os.path.join(DATA_DIR, 'games-log5.json'),
    'research':      os.path.join(DATA_DIR, 'games-research.json'),
    'xgboost':       os.path.join(DATA_DIR, 'games-xgboost.json'),
    'random_forest': os.path.join(DATA_DIR, 'games-random-forest.json'),
}

HISTORY_FILES = {
    'Log5':          os.path.join(DATA_DIR, 'games-log5-history.json'),
    'Research':      os.path.join(DATA_DIR, 'games-research-history.json'),
    'XGBoost':       os.path.join(DATA_DIR, 'games-xgboost-history.json'),
    'Random Forest': os.path.join(DATA_DIR, 'games-random-forest-history.json'),
}

MODEL_LABELS = {
    'log5':          'Log5',
    'research':      'Research',
    'xgboost':       'XGBoost',
    'random_forest': 'Random Forest',
}

CONFIDENCE_BANDS = [
    ('50-59%', 0.50, 0.60),
    ('60-69%', 0.60, 0.70),
    ('70-79%', 0.70, 0.80),
    ('80%+',   0.80, 1.01),
]

def band_for(confidence):
    for label, lo, hi in CONFIDENCE_BANDS:
        if lo <= confidence < hi:
            return label
    return '80%+'

def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)

def load_model_predictions():
    model_data = {}
    for model_key, path in MODEL_FILES.items():
        data = load_json(path)
        if not data or not data.get('predictions'):
            print(f'  WARN: No predictions found for {MODEL_LABELS[model_key]}')
            continue
        lookup = {}
        for p in data['predictions']:
            key = (p['away_team'], p['home_team'])
            lookup[key] = p
        model_data[model_key] = lookup
        print(f'  Loaded {len(lookup)} predictions from {MODEL_LABELS[model_key]}')
    return model_data

def compute_composite(away_team, home_team, model_data):
    models_result = {}
    votes    = {away_team: 0, home_team: 0}
    conf_for = {away_team: [], home_team: []}

    for model_key in MODEL_FILES:
        if model_key not in model_data:
            continue
        pred = model_data[model_key].get((away_team, home_team))
        if not pred:
            continue

        pick       = pred['pick']
        confidence = pred['confidence']
        models_result[model_key] = {'pick': pick, 'confidence': confidence}

        if pick == away_team:
            votes[away_team] += 1
            conf_for[away_team].append(confidence)
            conf_for[home_team].append(1.0 - confidence)
        else:
            votes[home_team] += 1
            conf_for[home_team].append(confidence)
            conf_for[away_team].append(1.0 - confidence)

    if not models_result:
        return None

    if votes[away_team] > votes[home_team]:
        composite_pick = away_team
    elif votes[home_team] > votes[away_team]:
        composite_pick = home_team
    else:
        away_avg = sum(conf_for[away_team]) / len(conf_for[away_team]) if conf_for[away_team] else 0.5
        home_avg = sum(conf_for[home_team]) / len(conf_for[home_team]) if conf_for[home_team] else 0.5
        composite_pick = away_team if away_avg >= home_avg else home_team

    supports = conf_for[composite_pick]
    composite_confidence = sum(supports) / len(supports) if supports else 0.5

    return {
        'models':               models_result,
        'composite_pick':       composite_pick,
        'composite_confidence': round(composite_confidence, 4),
        'vote_count':           votes[composite_pick],
        'total_votes':          sum(votes.values()),
    }

def compute_model_standings(today):
    standings = []
    for label, hist_path in HISTORY_FILES.items():
        hist = load_json(hist_path)
        if not hist:
            standings.append({'model': label, 'wins': 0, 'losses': 0, 'total': 0, 'pct': 0.0})
            continue
        wins = losses = 0
        for record in hist.get('records', []):
            if record['date'] == today:
                continue
            for g in record.get('games', []):
                if g.get('correct') is None:
                    continue
                if g['correct']:
                    wins += 1
                else:
                    losses += 1
        total = wins + losses
        pct   = wins / total if total > 0 else 0.0
        standings.append({'model': label, 'wins': wins, 'losses': losses,
                          'total': total, 'pct': round(pct, 4)})
    standings.sort(key=lambda x: (x['pct'], x['total']), reverse=True)
    return standings

def build_today_predictions(model_data):
    log5_data = load_json(MODEL_FILES['log5'])
    if not log5_data or not log5_data.get('predictions'):
        print('  WARN: Log5 predictions missing — cannot build composite')
        return []

    today_preds = []
    for p in log5_data['predictions']:
        away = p['away_team']
        home = p['home_team']
        result = compute_composite(away, home, model_data)
        if not result:
            continue
        today_preds.append({
            'game_time':            p.get('game_time', 'TBD'),
            'away_team':            away,
            'home_team':            home,
            'log5':                 result['models'].get('log5'),
            'research':             result['models'].get('research'),
            'xgboost':              result['models'].get('xgboost'),
            'random_forest':        result['models'].get('random_forest'),
            'composite_pick':       result['composite_pick'],
            'composite_confidence': result['composite_confidence'],
            'vote_count':           result['vote_count'],
            'total_votes':          result['total_votes'],
            'actual_winner':        None,
            'correct':              None,
        })

    # Sort by composite confidence descending — top 3 are always first
    today_preds.sort(key=lambda x: x['composite_confidence'], reverse=True)
    return today_preds

def load_history():
    if os.path.exists(HIST_JSON):
        with open(HIST_JSON) as f:
            return json.load(f)
    return {'records': []}

def save_history(history):
    with open(HIST_JSON, 'w') as f:
        json.dump(history, f, indent=2)

def grade_yesterday(history):
    yesterday = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')
    record = next((r for r in history['records'] if r['date'] == yesterday), None)
    if not record:
        return
    if all(g.get('correct') is not None for g in record['games']):
        return

    url = f'{MLB_API}/schedule?sportId=1&date={yesterday}'
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        results = []
        for entry in r.json().get('dates', []):
            results.extend(entry.get('games', []))
    except Exception as e:
        print(f'  WARN grading: {e}')
        return

    winner_lookup = {}
    for game in results:
        status = game.get('status', {}).get('detailedState', '')
        if status not in ('Final', 'Game Over', 'Completed Early'):
            continue
        away_score = game['teams']['away'].get('score')
        home_score = game['teams']['home'].get('score')
        if away_score is None or home_score is None:
            continue
        away_name = game['teams']['away']['team']['name']
        home_name = game['teams']['home']['team']['name']
        winner    = away_name if away_score > home_score else home_name
        winner_lookup[(away_name, home_name)] = winner

    for g in record['games']:
        actual = winner_lookup.get((g['away_team'], g['home_team']))
        if actual is not None:
            g['actual_winner'] = actual
            g['correct']       = (actual == g['composite_pick'])

def compute_stats(games_list):
    total_w = total_l = 0
    bands   = {label: [0, 0] for label, _, _ in CONFIDENCE_BANDS}
    for g in games_list:
        if g.get('correct') is None:
            continue
        w = 1 if g['correct'] else 0
        l = 0 if g['correct'] else 1
        total_w += w
        total_l += l
        b = band_for(g['composite_confidence'])
        bands[b][0] += w
        bands[b][1] += l
    by_conf = []
    for label, _, _ in CONFIDENCE_BANDS:
        bw, bl = bands[label]
        by_conf.append({'band': label, 'wins': bw, 'losses': bl, 'total': bw + bl})
    return {
        'total': {'wins': total_w, 'losses': total_l, 'total': total_w + total_l},
        'by_confidence': by_conf,
    }

def run():
    today     = date.today().strftime('%Y-%m-%d')
    yesterday = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')

    os.makedirs(DATA_DIR, exist_ok=True)

    print('Loading model predictions...')
    model_data = load_model_predictions()

    print('Building composite predictions...')
    today_preds = build_today_predictions(model_data)
    print(f'  -> {len(today_preds)} composite predictions (sorted by confidence)')
    if today_preds:
        top3 = today_preds[:3]
        print('  Top 3 picks:')
        for p in top3:
            print(f'    {p["composite_pick"]} ({p["composite_confidence"]:.1%}) — {p["away_team"]} @ {p["home_team"]}')

    print('Computing model standings...')
    model_standings = compute_model_standings(today)
    for s in model_standings:
        pct = f"{s['pct']:.1%}" if s['total'] > 0 else 'N/A'
        print(f'  {s["model"]:15s}: {s["wins"]}-{s["losses"]} ({pct})')

    print("Grading yesterday's composite picks...")
    history = load_history()
    grade_yesterday(history)

    existing = next((r for r in history['records'] if r['date'] == today), None)
    if existing:
        existing['games'] = today_preds
    else:
        history['records'].append({'date': today, 'games': today_preds})

    history['records'].sort(key=lambda r: r['date'], reverse=True)
    save_history(history)

    all_graded = [
        g for r in history['records']
        for g in r['games']
        if r['date'] != today and g.get('correct') is not None
    ]
    alltime_stats = compute_stats(all_graded)

    yday_record = next((r for r in history['records'] if r['date'] == yesterday), None)
    yday_stats  = compute_stats(yday_record['games'] if yday_record else [])

    output = {
        'updated':         datetime.now(timezone.utc).isoformat(),
        'date':            today,
        'predictions':     today_preds,
        'model_standings': model_standings,
        'yesterday':       {'date': yesterday, **yday_stats},
        'alltime':         alltime_stats,
    }
    with open(MAIN_JSON, 'w') as f:
        json.dump(output, f, indent=2)

    print(f'Wrote {len(today_preds)} composite predictions -> games-composite.json')
    print(f'  Composite all-time: {alltime_stats["total"]["wins"]}-{alltime_stats["total"]["losses"]}')

if __name__ == '__main__':
    run()
