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

TWOGIS_SUGGEST_URL = "https://catalog.api.2gis.com/3.0/suggests"
TWOGIS_GEOCODE_URL = "https://catalog.api.2gis.com/3.0/items/geocode"

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
        # FIX 1: Removed region_id — it was filtering out results because
        # 208 is not Atyrau's correct 2GIS region ID. Without it, the API
        # uses the query text itself to find the right region.
        "fields": "items.point",
        "limit": limit,
    }

    logger.info(f"Calling 2GIS suggest: {q}")

    with httpx.Client(timeout=10.0) as client:
        resp = client.get(TWOGIS_SUGGEST_URL, params=params)
        logger.info(f"2GIS response status: {resp.status_code}")
        logger.info(f"2GIS response body: {resp.text[:500]}")
        resp.raise_for_status()

    data = resp.json()
    results = []

    # FIX 2: Broadened accepted types. 2GIS also returns "crossroad",
    # "attraction", and others that are valid delivery addresses.
    # Only skip internal/meta types.
    SKIP_TYPES = {"user_query", "region", "country"}

    for item in data.get("result", {}).get("items", []):
        item_type = item.get("type", "")
        if item_type in SKIP_TYPES:
            continue

        name = item.get("name") or ""
        full_name = item.get("full_name") or ""
        address_name = item.get("address_name") or ""

        # Build a clean display address
        if full_name:
            display = full_name
        elif address_name:
            display = f"{name}, {address_name}"
        else:
            display = name

        # Skip results with no usable name
        if not display.strip():
            continue

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


@app.get("/debug")
async def debug():
    """Test endpoint — returns raw 2GIS response to diagnose empty suggestions."""
    try:
        results = {}
        for test_q in ["Атырау", "Atyrau", "Aktau", "улица"]:
            params = {
                "q": test_q,
                "key": TWOGIS_API_KEY,
                "locale": "ru_KZ",
                "fields": "items.point",
                "limit": 5,
            }
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(TWOGIS_SUGGEST_URL, params=params)
            data = resp.json()
            items = data.get("result", {}).get("items", [])

            results[test_q] = {
                "status": resp.status_code,
                "total_count": len(items),
                "items_detail": [
                    {
                        "type": item.get("type"),
                        "name": item.get("name"),
                        "full_name": item.get("full_name"),
                        "has_point": item.get("point") is not None,
                    }
                    for item in items
                ],
                "raw_first_item": items[0] if items else None,
            }
        return {"status": "ok", "tests": results}
    except Exception as e:
        return {"error": str(e)}