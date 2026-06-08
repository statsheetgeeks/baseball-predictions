"""
models/research_hot_hitters.py
──────────────────────────────────────────────────────────────────────────────
Hot Hitters Leaderboard — Chalk Line Labs

Pulls the last 60 days of MLB boxscores + Statcast xwOBA, then ranks the
top 100 "hottest" active hitters by a recency-weighted Hotness Score.

Modifications vs. original notebook:
  1. Exponential decay (λ = 0.85) — recent games weighted more heavily.
     Weight for a game N days ago = 0.85^N
  2. Minimum qualifier: ≥ 10 ABs in last 5 calendar days AND ≥ 2 distinct
     games played (AB > 0) in the same window.

Writes: public/data/research-hot-hitters.json
──────────────────────────────────────────────────────────────────────────────
"""

import json
import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

try:
    from pybaseball import statcast
except ImportError:
    raise SystemExit("pybaseball is required: pip install pybaseball")

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(BASE_DIR, '..', 'public', 'data')
os.makedirs(DATA_DIR, exist_ok=True)

OUT_JSON  = os.path.join(DATA_DIR, 'research-hot-hitters.json')

# ── Config ────────────────────────────────────────────────────────────────────
DECAY        = 0.85   # exponential decay rate (λ) — 7 days ago ≈ 32% weight
LOOKBACK     = 60     # days of history to pull
MIN_AB_5     = 10     # minimum AB in last 5 calendar days
MIN_GAMES_5  = 2      # minimum distinct games played (AB > 0) in last 5 days
TOP_N        = 100    # leaderboard size


# ══════════════════════════════════════════════════════════════════════════════
#  MLB Stats API helpers
# ══════════════════════════════════════════════════════════════════════════════

def get_schedule(start_date: str, end_date: str) -> pd.DataFrame:
    url = (
        f"https://statsapi.mlb.com/api/v1/schedule"
        f"?sportId=1&startDate={start_date}&endDate={end_date}"
    )
    resp = requests.get(url, timeout=30).json()
    games = []
    for date_obj in resp.get("dates", []):
        for game in date_obj.get("games", []):
            # Only regular season completed games
            if game.get("status", {}).get("codedGameState") == "F":
                games.append({
                    "gamePk": game["gamePk"],
                    "date":   date_obj["date"],
                })
    return pd.DataFrame(games)


def get_game_hitters(game_pk: int) -> pd.DataFrame:
    url  = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
    resp = requests.get(url, timeout=30).json()
    hitters = []
    for side in ("home", "away"):
        players = resp.get("teams", {}).get(side, {}).get("players", {})
        for player in players.values():
            batting = player.get("stats", {}).get("batting")
            if not batting:
                continue
            hitters.append({
                "player_id":   player["person"]["id"],
                "player_name": player["person"]["fullName"],
                "AB":  batting.get("atBats", 0),
                "H":   batting.get("hits", 0),
                "HR":  batting.get("homeRuns", 0),
                "BB":  batting.get("baseOnBalls", 0),
                "2B":  batting.get("doubles", 0),
                "3B":  batting.get("triples", 0),
            })
    return pd.DataFrame(hitters)


# ══════════════════════════════════════════════════════════════════════════════
#  Streak helpers
# ══════════════════════════════════════════════════════════════════════════════

def current_hit_streak(group: pd.DataFrame) -> int:
    streak = 0
    for hits in reversed(group.sort_values("date")["H"].tolist()):
        if hits > 0:
            streak += 1
        else:
            break
    return streak


def current_hr_streak(group: pd.DataFrame) -> int:
    streak = 0
    for hr in reversed(group.sort_values("date")["HR"].tolist()):
        if hr > 0:
            streak += 1
        else:
            break
    return streak


# ══════════════════════════════════════════════════════════════════════════════
#  Main pipeline
# ══════════════════════════════════════════════════════════════════════════════

def run():
    end_date   = datetime.today()
    start_date = end_date - timedelta(days=LOOKBACK)
    start_str  = start_date.strftime("%Y-%m-%d")
    end_str    = end_date.strftime("%Y-%m-%d")

    # ── 1. Pull daily boxscores ───────────────────────────────────────────────
    print("Fetching schedule...")
    schedule = get_schedule(start_str, end_str)
    print(f"  {len(schedule)} completed games found.")

    all_games = []
    for i, row in enumerate(schedule.itertuples(), 1):
        try:
            game_df = get_game_hitters(row.gamePk)
            game_df["date"] = pd.to_datetime(row.date).date()
            all_games.append(game_df)
        except Exception as exc:
            print(f"  [WARN] game {row.gamePk} failed: {exc}")
        if i % 50 == 0:
            print(f"  processed {i}/{len(schedule)} games…")

    if not all_games:
        raise SystemExit("No boxscore data retrieved — aborting.")

    master_df = pd.concat(all_games, ignore_index=True)
    master_df["player_id"] = master_df["player_id"].astype(int)

    # ── 2. Pull Statcast xwOBA ────────────────────────────────────────────────
    print("Pulling Statcast data...")
    sc = statcast(start_dt=start_str, end_dt=end_str)
    bip = sc[
        sc["launch_speed"].notna() &
        sc["estimated_woba_using_speedangle"].notna()
    ].copy()
    bip["batter"]    = bip["batter"].astype(int)
    bip["game_date"] = pd.to_datetime(bip["game_date"]).dt.date

    game_xwoba = (
        bip.groupby(["batter", "game_date"])["estimated_woba_using_speedangle"]
        .mean()
        .reset_index()
        .rename(columns={"batter": "player_id", "game_date": "date"})
    )

    # ── 3. Merge & derive base stats ─────────────────────────────────────────
    master_df = master_df.merge(game_xwoba, on=["player_id", "date"], how="left")
    master_df["estimated_woba_using_speedangle"] = (
        master_df["estimated_woba_using_speedangle"].fillna(0)
    )
    master_df["1B"] = master_df["H"] - master_df["2B"] - master_df["3B"] - master_df["HR"]
    master_df["TB"] = (
        master_df["1B"]
        + 2 * master_df["2B"]
        + 3 * master_df["3B"]
        + 4 * master_df["HR"]
    )

    # ── 4. Compute exponential decay weights ──────────────────────────────────
    anchor_date = end_date.date()
    master_df["days_ago"] = master_df["date"].apply(
        lambda d: (anchor_date - d).days
    )
    master_df["weight"] = DECAY ** master_df["days_ago"]

    # ── 5. Calendar cutoffs for window segmentation ───────────────────────────
    cutoff_5  = anchor_date - timedelta(days=5)
    cutoff_10 = anchor_date - timedelta(days=10)

    # ── 6. Build leaderboard ──────────────────────────────────────────────────
    print("Computing leaderboard...")
    leaderboard = []

    for player, group in master_df.groupby("player_name"):
        group    = group.sort_values("date")
        group_5  = group[group["date"] > cutoff_5]
        group_10 = group[group["date"] > cutoff_10]

        # ── Qualifier filters ────────────────────────────────────────────────
        ab5 = group_5["AB"].sum()
        games_played_5 = (group_5["AB"] > 0).sum()  # distinct game appearances

        if ab5 < MIN_AB_5 or games_played_5 < MIN_GAMES_5:
            continue

        # ── Decay-weighted OPS (5-day window) ────────────────────────────────
        w5    = group_5["weight"]
        ab5_w = (group_5["AB"] * w5).sum()
        h5_w  = (group_5["H"]  * w5).sum()
        bb5_w = (group_5["BB"] * w5).sum()
        tb5_w = (group_5["TB"] * w5).sum()

        obp5 = (h5_w + bb5_w) / (ab5_w + bb5_w) if (ab5_w + bb5_w) > 0 else 0
        slg5 = tb5_w / ab5_w if ab5_w > 0 else 0
        ops5 = obp5 + slg5

        # ── Decay-weighted OPS (10-day window) ───────────────────────────────
        w10    = group_10["weight"]
        ab10_w = (group_10["AB"] * w10).sum()
        h10_w  = (group_10["H"]  * w10).sum()
        bb10_w = (group_10["BB"] * w10).sum()
        tb10_w = (group_10["TB"] * w10).sum()

        obp10 = (h10_w + bb10_w) / (ab10_w + bb10_w) if (ab10_w + bb10_w) > 0 else 0
        slg10 = tb10_w / ab10_w if ab10_w > 0 else 0
        ops10 = obp10 + slg10

        # ── Decay-weighted xwOBA (5-day window) ──────────────────────────────
        xw5 = group_5[group_5["estimated_woba_using_speedangle"] > 0]
        if len(xw5) > 0:
            xwoba5 = (xw5["estimated_woba_using_speedangle"] * xw5["weight"]).sum() / xw5["weight"].sum()
        else:
            xwoba5 = 0.0

        # ── Decay-weighted xwOBA (10-day window) ─────────────────────────────
        xw10 = group_10[group_10["estimated_woba_using_speedangle"] > 0]
        if len(xw10) > 0:
            xwoba10 = (xw10["estimated_woba_using_speedangle"] * xw10["weight"]).sum() / xw10["weight"].sum()
        else:
            xwoba10 = 0.0

        # ── Streaks (unweighted — streaks are inherently recency-based) ───────
        hit_streak = current_hit_streak(group)
        hr_streak  = current_hr_streak(group)

        # ── Hotness Score ─────────────────────────────────────────────────────
        hotness_score = (
            0.4 * (xwoba5  * 2)
            + 0.3 * (xwoba10 * 2)
            + 0.2 * hit_streak
            + 0.1 * hr_streak
        )

        leaderboard.append({
            "player":       player,
            "hit_streak":   hit_streak,
            "hr_streak":    hr_streak,
            "ops_5":        round(ops5,    3),
            "ops_10":       round(ops10,   3),
            "xwoba_5":      round(xwoba5,  3),
            "xwoba_10":     round(xwoba10, 3),
            "ab_5":         int(ab5),
            "games_5":      int(games_played_5),
            "hotness_score": round(hotness_score, 3),
        })

    if not leaderboard:
        raise SystemExit("Leaderboard is empty — check data pull.")

    df = (
        pd.DataFrame(leaderboard)
        .sort_values("hotness_score", ascending=False)
        .head(TOP_N)
        .reset_index(drop=True)
    )
    df.insert(0, "rank", df.index + 1)

    # ── 7. Write JSON ─────────────────────────────────────────────────────────
    output = {
        "updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "decay":   DECAY,
        "players": df.to_dict(orient="records"),
    }

    with open(OUT_JSON, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n✓ Written {len(df)} players → {OUT_JSON}")


if __name__ == "__main__":
    run()
