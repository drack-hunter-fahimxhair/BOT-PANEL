# MAHIR TCP PANEL — Owner Edition (Updated)

## New Features Added

### 1. Module / Pip Manager (`/owner/modules`)
- Auto-detect `ModuleNotFoundError` from bot logs (e.g. `edge_tts`)
- One-click **Auto Fix Detected Modules**
- Custom pip install (any package: `edge-tts`, `PyJWT`, `google-play-scraper`, ...)
- Upgrade pip + setuptools + wheel
- `pip install -r requirements.txt`
- Quick buttons for common packages
- Status of common bot packages

### 2. Photo Manager (`/owner/photos`)
- All images now served from local `photo/` folder
- Upload PNG/JPG/WEBP/GIF
- Set any photo as **Logo** or **Cover**
- External `mahir-photo-url.vercel.app` links fully removed

### 3. Voice Greeting + Sound
- After login, browser speaks: "Welcome <name>. Mahir TCP Panel is ready."
- Soft click beep on buttons

## How to Run
```bash
pip install -r requirements.txt
python main.py
# Open http://YOUR_IP:8080
# Owner: /owner/login
```

## Folders
- `photo/` — put your logo/cover images here (or upload from owner panel)
- `mahir.py` — bot template (upload via owner panel)
- `users.db` — created automatically

## Owner Panel Links
- Dashboard: `/owner/dashboard`
- Modules: `/owner/modules`
- Photos: `/owner/photos`
- File Manager: `/owner/files`
