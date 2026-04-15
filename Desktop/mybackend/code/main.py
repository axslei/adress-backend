from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import httpx
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="2GIS Address Search API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

TWOGIS_API_KEY = "30202935-f892-4b86-b3f6-948471f69e31"

# ✅ FIXED URLs
TWOGIS_SUGGEST_URL = "https://catalog.api.2gis.com/3.0/suggests"
TWOGIS_GEOCODE_URL = "https://catalog.api.2gis.com/3.0/items/geocode"


# ── joblib cache removed — was causing issues on Render (disk wipes on redeploy)
# ── Using simple in-memory dict cache instead (fast, reliable, zero dependencies)

_suggest_cache: dict = {}
_search_cache: dict = {}


def _cached_suggest(q: str, limit: int) -> list:
    cache_key = f"{q}|{limit}"
    if cache_key in _suggest_cache:
        logger.info(f"Cache hit for suggest: {q}")
        return _suggest_cache[cache_key]

    params = {
        "q": q,
        "key": TWOGIS_API_KEY,
        "locale": "ru_KZ",
        "region_id": "56",          # Atyrau region
        "fields": "items.point",
        "limit": limit,
    }

    logger.info(f"Calling 2GIS suggest: {q}")

    with httpx.Client(timeout=10.0) as client:
        resp = client.get(TWOGIS_SUGGEST_URL, params=params)
        logger.info(f"2GIS response status: {resp.status_code}")
        logger.info(f"2GIS response body: {resp.text[:500]}")  # log first 500 chars
        resp.raise_for_status()

    data = resp.json()
    results = []
    for item in data.get("result", {}).get("items", []):
        # skip user_query type — it has no address
        if item.get("type") == "user_query":
            continue

        name = item.get("name", "")
        full_name = item.get("full_name", "")
        address_name = item.get("address_name", "")

        # Build a clean display address
        if full_name:
            display = full_name
        elif address_name:
            display = f"{name}, {address_name}"
        else:
            display = name

        point = item.get("point")
        results.append({
            "name": name,
            "full_address": display,
            "lat": point.get("lat") if point else None,
            "lon": point.get("lon") if point else None,
        })

    _suggest_cache[cache_key] = results
    return results


def _cached_search(q: str, city: str, limit: int) -> list:
    cache_key = f"{q}|{city}|{limit}"
    if cache_key in _search_cache:
        return _search_cache[cache_key]

    params = {
        "q": f"{city} {q}",
        "key": TWOGIS_API_KEY,
        "fields": "items.point,items.full_name,items.address_name",
        "page_size": limit,
        "type": "building,street,adm_div",
    }

    logger.info(f"Calling 2GIS geocode: {q}")

    with httpx.Client(timeout=10.0) as client:
        resp = client.get(TWOGIS_GEOCODE_URL, params=params)
        logger.info(f"2GIS geocode status: {resp.status_code}")
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

    _search_cache[cache_key] = results
    return results


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
        logger.error(f"2GIS HTTP error: {e.response.status_code} — {e.response.text}")
        raise HTTPException(status_code=502, detail=f"2GIS error: {e.response.status_code} — {e.response.text}")
    except httpx.RequestError as e:
        logger.error(f"2GIS request error: {e}")
        raise HTTPException(status_code=503, detail="Could not reach 2GIS")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
        logger.error(f"2GIS HTTP error: {e.response.status_code} — {e.response.text}")
        raise HTTPException(status_code=502, detail=f"2GIS error: {e.response.status_code}")
    except httpx.RequestError as e:
        logger.error(f"2GIS request error: {e}")
        raise HTTPException(status_code=503, detail="Could not reach 2GIS")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"query": q, "results": results}


# ── Debug endpoint — hit this to verify API key and URL work ──
@app.get("/debug")
async def debug():
    try:
        params = {
            "q": "Атырау",
            "key": TWOGIS_API_KEY,
            "locale": "ru_KZ",
            "limit": 2,
        }
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(TWOGIS_SUGGEST_URL, params=params)
        return {
            "status_code": resp.status_code,
            "url_called": str(resp.url),
            "response": resp.json(),
        }
    except Exception as e:
        return {"error": str(e)}