# Deploying North Path

The app is a plain Flask app. It runs anywhere that runs Python; these are the
steps for Render's free tier, which is where the other project lives.

## 1. Push to GitHub

```bash
cd uni-cost
git init
git add .
git commit -m "North Path — degree-first university selector"
git branch -M main
git remote add origin https://github.com/<you>/north-path.git
git push -u origin main
```

`.gitignore` already keeps `.env`, `__pycache__` and the generated
`CALIBRATION.md` out. **Never commit your API key** — it goes in Render's
environment settings, not in the repo.

## 2. Create the service on Render

New → Web Service → connect the repo, then:

| Setting | Value |
| --- | --- |
| Runtime | Python 3 |
| Build command | `pip install -r requirements.txt` |
| Start command | `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --timeout 90` |
| Instance type | Free |

`render.yaml` in the repo sets the same thing, so Render can also pick it up
automatically ("Blueprint" deploy).

## 3. Add the Gemini key

In the service's **Environment** tab:

| Key | Value |
| --- | --- |
| `GEMINI_API_KEY` | your key from aistudio.google.com |
| `GEMINI_MODEL` | optional — leave it unset unless you want a specific model |
| `GEMINI_TIMEOUT` | `12` (optional; seconds) |
| `GEMINI_MAX_TOKENS` | `1200` (optional) |
| `GEMINI_RETRY_PAUSE` | `0.8` (optional; seconds between retries) |

**The app works without the key.** With no key set, the "describe your situation"
box and the summary simply don't appear, and everything else behaves the same.
That's deliberate: if the free tier runs out or the key is revoked, the tool
still works rather than breaking.

## 4. The assistant's call budget

Two Gemini calls go out per page load that uses the assistant. A public link
with a free-tier key behind it needs a ceiling, so there is one:

| Key | Default | Meaning |
| --- | --- | --- |
| `ASSISTANT_LIMIT_PER_VISITOR` | `12` | assistant calls per IP per hour |
| `ASSISTANT_LIMIT_PER_HOUR` | `180` | assistant calls in total per hour |

Past either limit the sentence box and the summary go quiet and the page says
so; **the ranking is never limited**, because it reads local JSON and costs
nothing. The counter lives in memory, which is why the start command pins
`--workers 1` — a second worker would keep its own counter and double the
budget. It also resets on deploy, which is fine for what it protects.

## 5. Free-tier behaviour

Render's free web services sleep after about 15 minutes of inactivity, so the
first visit after a quiet period takes ~30 seconds to wake. Fine for a portfolio
link; mention it if you demo live.

## When the assistant says it's unavailable

```bash
python check_gemini.py
```

It reports, in order: whether the key is set, whether Google answers, whether the
model name is one this key can call, and whether a real request works. The
common causes:

| Message | Cause |
| --- | --- |
| `API key not valid` | Wrong or revoked key. Make a new one at aistudio.google.com. |
| `HTTP 403` | The Generative Language API isn't enabled for that key's project, or the key is restricted by referrer/IP. |
| `HTTP 429` / `HTTP 503` | Throttled or overloaded. The app already retries and tries another model; if it still fails the page says the assistant is busy and ranks normally. |
| `is NOT in the list above` | A `GEMINI_MODEL` you pinned has been retired. Clear it — with nothing pinned the app picks a working model itself. |
| `used its whole output budget on reasoning` | A thinking model with too small a cap. Raise `GEMINI_MAX_TOKENS`. |
| `could not connect` | Network, VPN or firewall. |

## Running locally

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=...        # optional; Windows: setx GEMINI_API_KEY "..."
python app.py                    # http://localhost:5000
```

Copy `.env.example` to `.env` if you prefer keeping it in a file — but that file
is gitignored and Flask does not read it automatically; export the variable, or
add `python-dotenv` if you want that.

## What the assistant may and may not do

Worth knowing before you demo it, because someone will ask:

- It **parses** a sentence into form fields. Every field it returns is validated
  against the same rules as the form — an out-of-range average or an unknown
  degree is discarded rather than used.
- It **summarises** results that are already computed, and is handed the exact
  figures. A summary containing any number that isn't in those figures is thrown
  away, including a rounded version of a real one.
- It never supplies tuition, rent, costs, cutoffs or rankings. Those come from
  `data/` with a source attached to each figure.

If the API is down, slow or rate-limited, both features fail quietly and the
page renders as normal.

## Model names move

Google retired `gemini-2.0-flash` and then `gemini-2.5-flash` during the few
weeks this was built, each time answering with a 404 that named the
replacement. So the model name is not pinned in the code: the app asks the key
which models it can call, prefers a current flash model, and when a 404 says a
name is retired it reads the suggested replacement out of Google's own error
and retries with it. Set `GEMINI_MODEL` only if you want a specific one — and
if you do, you own keeping it current.
