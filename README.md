# FIRE

![Hero.png]

Be accountable on your anki studies! Install the anki plugin, and share your heatmap with anyone. Fully open-source.

## Quick Setup

1. Copy the `heatmap_reporter/` folder to your Anki add-ons directory
2. Sync in Anki - that's it!

Your username will be your Anki profile name and registration happens automatically. View your heatmap by going Tools -> 🔥 -> View my heatmap
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
2. In Anki: Tools → Add-ons → Heatmap Reporter → Config
3. Set `base_url` to your server URL (e.g., `https://your-domain.com`)
4. Sync in Anki

### 3. View Your Heatmap

Visit `http://ANKIFIRE_BASE_URL/u/your-profile-name` to see your review heatmap.



