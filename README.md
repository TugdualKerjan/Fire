# FIRE

![Hero.png]

Be accountable on your anki studies! Install the anki plugin, and share your heatmap with anyone. Fully open-source.

## Register

```bash
curl -X POST http://fire.tugdual.fr/api/register \
  -H "Content-Type: application/json" \
  -d '{"username": "YOUR DESIRED USERNAME"}'
```

1. Copy the `heatmap_reporter/` folder to your Anki add-ons directory
2. In Anki: Tools → Add-ons → Heatmap Reporter → Config add your token.

## Self hosting

### 1. Run the Server

```bash
cd server
uv sync
export ANKIFIRE_BASE_URL=https://your-domain.com
uv run uvicorn server:app --host 0.0.0.0 --port 8000
```

### 2. Install the Anki Add-on

1. Copy the `heatmap_reporter/` folder to your Anki add-ons directory
2. In Anki: Tools → Add-ons → Heatmap Reporter.
3. Configure your server URL (default: `ANKIFIRE_BASE_URL`)

### 3. Register and Get Token

```bash
curl -X POST http://ANKIFIRE_BASE_URL/api/register \
  -H "Content-Type: application/json" \
  -d '{"username": "your-username"}'
```

Copy the returned token to your Anki add-on config.

### 4. View Your Heatmap

Visit `http://ANKIFIRE_BASE_URL/u/your-username` to see your review heatmap.



