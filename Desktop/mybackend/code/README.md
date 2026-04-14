# 2GIS Address Search API — Deployment Guide

## Folder structure
```
2gis-address-api/
├── main.py                    ← FastAPI app (joblib-cached)
├── requirements.txt
├── render.yaml                ← Render auto-deploy config
├── .gitignore
└── address_search_sheet.dart  ← Drop-in Flutter widget
```

---

## How joblib is used here

`joblib.Memory` caches the result of `_cached_suggest()` and `_cached_search()`
to a local `.joblib_cache/` folder on disk. This means:
- The **first call** for a given query hits 2GIS normally
- Every **repeat call** with the same query is returned from disk instantly — no network round-trip
- The cache survives server restarts (until Render redeploys and wipes the disk)

---

## STEP 1 — Add your API key

Open `main.py` and replace line 14:
```python
TWOGIS_API_KEY = "your_2gis_api_key_here"   # ← paste your real key here
```

---

## STEP 2 — Test locally

```bash
cd 2gis-address-api
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Open http://localhost:8000/suggest?q=Атырау  
You should see JSON with address suggestions.

---

## STEP 3 — Push to GitHub

```bash
git init
git add .
git commit -m "initial 2gis api"
# Create a new repo on github.com, then:
git remote add origin https://github.com/YOUR_USERNAME/2gis-address-api.git
git branch -M main
git push -u origin main
```

---

## STEP 4 — Deploy on Render

1. Go to https://render.com → **New** → **Web Service**
2. Connect your GitHub repo (`2gis-address-api`)
3. Render will detect `render.yaml` automatically — no extra config needed
4. Click **Create Web Service**
5. Wait ~2 min. You'll get a URL like:
   `https://2gis-address-api.onrender.com`

Test it: `https://2gis-address-api.onrender.com/suggest?q=Атырау`

---

## STEP 5 — Connect to Flutter

### pubspec.yaml — add the http package:
```yaml
dependencies:
  http: ^1.2.0
```
Run `flutter pub get`.

### Copy address_search_sheet.dart
Copy `address_search_sheet.dart` into your Flutter project at:
`lib/view/shop/address_search_sheet.dart`

### Change the base URL constant (line ~30):
```dart
const String kAddressApiBase = 'https://2gis-address-api.onrender.com';
```

### In shop_screen.dart — add import:
```dart
import 'address_search_sheet.dart';
```

### Replace _openSetLocation() in shop_screen.dart with:
```dart
void _openSetLocation() {
  showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.white,
    shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
    builder: (ctx) => _AddressSearchSheet(
      initialAddress: SharedAddress().address ?? '',
      onConfirm: (address) {
        SharedAddress().setAddress(address);
      },
    ),
  );
}
```

Do the same for `_editAddress()` in `cart_screen.dart`.

---

## API Endpoints

| Endpoint | Params | Use |
|---|---|---|
| `GET /suggest` | `q`, `limit` | Autocomplete while typing (fast, joblib-cached) |
| `GET /search`  | `q`, `city`, `limit` | Full geocode search (joblib-cached) |
| `GET /`        | — | Health check |

---

## Notes
- Render free tier **spins down after 15 min of inactivity** — first request after idle takes ~30 s. Upgrade to a paid plan ($7/mo) to keep it always-on.
- The `.joblib_cache/` folder is already in `.gitignore` so it won't be committed.

