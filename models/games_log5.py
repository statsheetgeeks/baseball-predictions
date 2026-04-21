"""
models/games_log5.py  —  TEMPLATE
─────────────────────────────────────────────────────────────────────────────
Replace the contents of this file with your actual Log5 model code.

The ONLY requirement: this script must write a JSON file to:
    public/data/games-log5.json

That file must follow this exact shape:
{
    "updated": "<ISO 8601 timestamp>",
    "predictions": [ <list of dicts> ]
}

Each dict in "predictions" should have the keys that match the columns
defined in pages/games/log5.js.  Add or remove fields freely — just keep
the same keys in both places.
─────────────────────────────────────────────────────────────────────────────
"""

import json
import os
from datetime import datetime, timezone

# ── Paste your MLB API + model code here ─────────────────────────────────────
# import statsapi                      # pip install MLB-StatsAPI
# from your_model import log5          # your existing Log5 function

def run():
    # 1. Fetch today's schedule via MLB API
    # schedule = statsapi.schedule(date=datetime.today().strftime('%m/%d/%Y'))

    # 2. Pull team win percentages
    # ...

    # 3. Run Log5 formula for each game
    # ...

    # 4. Build the predictions list — REPLACE with your real output
    predictions = [
        # {
        #     "game_time":    "7:10 PM ET",
        #     "home_team":    "Los Angeles Dodgers",
        #     "away_team":    "San Francisco Giants",
        #     "home_win_pct": 0.648,
        #     "away_win_pct": 0.519,
        #     "home_prob":    0.621,
        #     "away_prob":    0.379,
        # },
    ]

    # 5. Write JSON output
    output = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "predictions": predictions,
    }

    out_path = os.path.join(os.path.dirname(__file__), '..', 'public', 'data', 'games-log5.json')
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"✓ Wrote {len(predictions)} predictions to games-log5.json")

if __name__ == '__main__':
    run()
