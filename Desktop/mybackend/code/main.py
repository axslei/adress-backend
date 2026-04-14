from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from joblib import Memory
import httpx

app = FastAPI(title="2GIS Address Search API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── joblib cache (stores results on disk so repeated queries are instant) ──
memory = Memory(location=".joblib_cache", verbose=0)

TWOGIS_API_KEY = "30202935-f892-4b86-b3f6-948471f69e31"   # ← paste your key directly here
TWOGIS_GEOCODE_URL = "https://catalog.api.2gis.com/3.0/items/geocode"
TWOGIS_SUGGEST_URL = "https://suggest.api.2gis.com/1.0"


# ── cached helper functions (called synchronously, results stored on disk) ──
@memory.cache
def _cached_suggest(q: str, limit: int) -> list:
    """Cached autocomplete — same query returns instantly on repeat calls."""
    import httpx as _httpx  # imported inside so joblib can pickle cleanly
    params = {
        "q": q,
        "key": TWOGIS_API_KEY,
        "locale": "ru_KZ",
        "region_id": "56",
        "limit": limit,
    }
    with _httpx.Client(timeout=8.0) as client:
        resp = client.get(TWOGIS_SUGGEST_URL, params=params)
        resp.raise_for_status()
    data = resp.json()
    results = []
    for item in data.get("result", {}).get("items", []):
        results.append({
            "name": item.get("name", ""),
            "full_address": item.get("full_name", item.get("name", "")),
            "lat": item.get("point", {}).get("lat"),
            "lon": item.get("point", {}).get("lon"),
        })
    return results


@memory.cache
def _cached_search(q: str, city: str, limit: int) -> list:
    """Cached full geocode search."""
    import httpx as _httpx
    params = {
        "q": f"{city} {q}",
        "key": TWOGIS_API_KEY,
        "fields": "items.point,items.full_name,items.address_name",
        "page_size": limit,
        "type": "building,street,adm_div",
    }
    with _httpx.Client(timeout=10.0) as client:
        resp = client.get(TWOGIS_GEOCODE_URL, params=params)
        resp.raise_for_status()
    data = resp.json()
    items = data.get("result", {}).get("items", [])
    results = []
    for item in items:
        point = item.get("point")
        if not point:
            continue
        results.append({
            "name": item.get("address_name") or item.get("full_name", ""),
            "full_address": item.get("full_name", ""),
            "lat": point.get("lat"),
            "lon": point.get("lon"),
        })
    return results


# ── endpoints ──────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "message": "2GIS Address API is running"}


@app.get("/suggest")
async def suggest_address(
    q: str = Query(..., min_length=1),
    limit: int = Query(5, ge=1, le=10),
):
    try:
        suggestions = _cached_suggest(q.strip(), limit)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"2GIS error: {e.response.status_code}")
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Could not reach 2GIS")
    return {"query": q, "suggestions": suggestions}


@app.get("/search")
async def search_address(
    q: str = Query(..., min_length=2),
    city: str = Query("Atyrau"),
    limit: int = Query(5, ge=1, le=10),
):
    try:
        results = _cached_search(q.strip(), city.strip(), limit)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"2GIS error: {e.response.status_code}")
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Could not reach 2GIS")
    return {"query": q, "results": results}
