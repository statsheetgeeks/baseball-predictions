# BaseballIQ — MLB Prediction Website

A Next.js website that displays daily MLB predictions from your Python models, hosted on GitHub and deployed via Vercel.

---

## How It Works

```
Your Python models  →  public/data/*.json  →  Next.js website  →  Vercel
        ↑                                              
GitHub Actions runs models daily at 10 AM ET
```

1. **GitHub Actions** runs your Python model scripts every morning
2. Each script writes predictions to a JSON file in `public/data/`
3. GitHub Actions commits the updated JSON files
4. **Vercel** detects the new commit and redeploys the site automatically
5. Visitors see fresh predictions every day

---

## Project Structure

```
baseball-predictions/
│
├── pages/                        ← Website pages (Next.js)
│   ├── index.js                  ← Home page
│   ├── games/
│   │   ├── index.js              ← Games hub
│   │   ├── log5.js
│   │   ├── research.js
│   │   ├── xgboost.js
│   │   ├── random-forest.js
│   │   └── composite.js
│   ├── hitters/
│   │   ├── index.js
│   │   ├── log5-hit.js
│   │   ├── ml-hit.js
│   │   └── hr-model.js
│   └── pitchers/
│       ├── index.js
│       └── strikeout.js
│
├── components/
│   ├── Layout.js                 ← Sidebar + header
│   ├── PredictionTable.js        ← Reusable table + helper cells
│   └── usePredictions.js         ← Hook that loads JSON data
│
├── public/data/                  ← JSON prediction files (written by Python)
│   ├── games-log5.json
│   ├── games-research.json
│   ├── games-xgboost.json
│   ├── games-random-forest.json
│   ├── games-composite.json
│   ├── hitters-log5-hit.json
│   ├── hitters-ml-hit.json
│   ├── hitters-hr-model.json
│   └── pitchers-strikeout.json
│
├── models/                       ← Your Python model scripts go here
│   └── games_log5.py             ← Template — replace with your real code
│
├── styles/globals.css
├── requirements.txt              ← Python dependencies
├── .github/workflows/
│   └── run-models.yml            ← Daily automation
└── vercel.json
```

---

## Setup Guide

### Step 1 — Create a GitHub repository

1. Go to [github.com](https://github.com) → **New repository**
2. Name it `baseball-predictions` (or anything you like)
3. Set it to **Public** or **Private** (both work with Vercel)
4. Do **not** initialize with a README (you already have one)

### Step 2 — Push this code to GitHub

Open a terminal in this folder and run:

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/baseball-predictions.git
git push -u origin main
```

### Step 3 — Connect to Vercel

1. Go to [vercel.com](https://vercel.com) → **Add New Project**
2. Click **Import Git Repository** → select your GitHub repo
3. Framework will auto-detect as **Next.js**
4. Click **Deploy** — that's it!

Every time GitHub Actions commits new JSON, Vercel will automatically redeploy.

### Step 4 — Add your Python models

1. Copy your existing Python model files into the `models/` folder
2. Each model file needs to write its output to `public/data/<name>.json`
3. Use `models/games_log5.py` as a template for the required output format
4. Update `requirements.txt` with any packages your models need

**Required JSON output format:**
```json
{
  "updated": "2025-04-20T10:00:00Z",
  "predictions": [
    { "field1": "value", "field2": 0.623, ... },
    ...
  ]
}
```

### Step 5 — Configure GitHub Actions

The workflow in `.github/workflows/run-models.yml` runs automatically at 10 AM ET daily.

To run it manually: Go to your GitHub repo → **Actions** tab → **Run Prediction Models Daily** → **Run workflow**

---

## Adding a New Model Page

1. Create `public/data/your-model-name.json` with sample data
2. Create `pages/your-section/your-model.js` — copy an existing page as a template
3. Change the `usePredictions('your-model-name')` call to match your JSON file name
4. Define your `COLUMNS` array to match the fields in your JSON
5. Add the page to the `NAV` array in `components/Layout.js`
6. Add a Python script in `models/` and add a step to the GitHub Actions workflow

---

## Customizing Columns

Each model page defines a `COLUMNS` array. Each column has:

```js
{
  key: 'field_name',        // must match a key in your JSON predictions
  label: 'Display Label',   // shown in the table header
  render: (value, row) => { // optional — custom cell renderer
    return <span>{value.toFixed(2)}</span>
  }
}
```

Built-in renderers available from `PredictionTable.js`:
- `<ProbCell value={v} />` — shows percentage + mini bar
- `<FavoriteCell value={v} />` — shows FAV/DOG tag

---

## Local Development

```bash
npm install
npm run dev
# → open http://localhost:3000
```
