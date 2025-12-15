# sdg_api.py
"""
Helper library for the official UN SDG Global Database API.

API docs:
- Swagger: https://unstats.un.org/SDGAPI/swagger/
- V1 SDG endpoints (Indicator/List, Indicator/Data, GeoArea/List, etc.)
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://unstats.un.org/SDGAPI/v1/sdg"


class SDGAPIError(Exception):
    """Raised when the UNSD SDG API returns an error."""


def _get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Internal helper for GET requests."""
    url = f"{BASE_URL}{path}"
    resp = requests.get(url, params=params, timeout=60)
    if resp.status_code != 200:
        raise SDGAPIError(
            f"GET {url} failed ({resp.status_code}): {resp.text[:300]}"
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise SDGAPIError(f"Invalid JSON from {url}: {resp.text[:300]}") from exc


# ---------- Metadata ----------

@lru_cache()
def list_indicators() -> List[Dict[str, Any]]:
    """
    Return list of all SDG indicators with metadata.

    Wraps /Indicator/List.
    """
    data = _get("/Indicator/List")
    # Swagger example shows the response is a JSON array of indicator records. :contentReference[oaicite:8]{index=8}
    if isinstance(data, list):
        return data
    # Sometimes APIs wrap lists; handle both.
    return data.get("data", [])


@lru_cache()
def list_geo_areas() -> List[Dict[str, Any]]:
    """
    Return flat list of all geographic areas (M49 codes).

    Wraps /GeoArea/List.
    """
    data = _get("/GeoArea/List")
    if isinstance(data, list):
        return data
    return data.get("data", [])


def get_geo_by_name(name: str) -> Optional[Tuple[int, str]]:
    """
    Fuzzy match a human country/area name to a (M49 code, official name)
    using /GeoArea/List metadata.
    """
    import difflib

    name_norm = name.strip().lower()
    geo_areas = list_geo_areas()
    names = [g.get("geoAreaName", "") for g in geo_areas]
    lower_names = [n.lower() for n in names]

    matches = difflib.get_close_matches(name_norm, lower_names, n=1, cutoff=0.6)
    if not matches:
        return None

    best = matches[0]
    idx = lower_names.index(best)
    record = geo_areas[idx]
    try:
        code = int(record["geoAreaCode"])
    except Exception:
        return None
    return code, record.get("geoAreaName", name)


# ---------- Data retrieval ----------

def fetch_indicator_data(
    indicator_codes: List[str],
    area_codes: List[int],
    time_period_start: Optional[int] = None,
    time_period_end: Optional[int] = None,
    time_period: Optional[List[int]] = None,
    page_size: int = 10_000,
) -> Dict[str, Any]:
    """
    Fetch observations from /Indicator/Data.

    Parameters are mapped to the official UNSD SDG API query params:
    - indicator: list of indicator codes (e.g. ["3.1.1"])
    - areaCode: list of M49 codes
    - timePeriodStart/timePeriodEnd: optional bounding years
    - timePeriod: optional explicit list of years to request

    Note: for most indicator/country combos, a single page is enough.
    """
    params: Dict[str, Any] = {
        "indicator": indicator_codes,
        "areaCode": area_codes,
        "page": 1,
        "pageSize": page_size,
    }

    if time_period_start is not None:
        params["timePeriodStart"] = time_period_start
    if time_period_end is not None:
        params["timePeriodEnd"] = time_period_end
    if time_period:
        params["timePeriod"] = time_period

    payload = _get("/Indicator/Data", params)
    return payload


def indicator_data_to_dataframe(payload: Dict[str, Any]):
    """
    Convert /Indicator/Data payload to a tidy pandas DataFrame.

    Expected payload keys (per UNSD SDG API docs):
    - 'data': list of observations, each with fields like:
      'indicator', 'geoAreaCode', 'geoAreaName', 'timePeriod' or
      'timePeriodStart', 'value', plus various attribute/dimension fields. 
    """
    import pandas as pd

    data = payload.get("data", [])
    if not data:
        return pd.DataFrame()

    records = []
    for row in data:
        # indicator may be list or scalar; handle both
        indicator = row.get("indicator")
        if isinstance(indicator, list):
            indicator_code = indicator[0]
        else:
            indicator_code = indicator

        # year may be 'timePeriod' or 'timePeriodStart'
        year = row.get("timePeriod")
        if year is None:
            year = row.get("timePeriodStart")

        value_raw = row.get("value")
        try:
            value = float(value_raw) if value_raw is not None else None
        except Exception:
            value = None

        records.append(
            {
                "indicator": indicator_code,
                "series": row.get("series"),
                "seriesDescription": row.get("seriesDescription"),
                "geoAreaCode": row.get("geoAreaCode"),
                "geoAreaName": row.get("geoAreaName"),
                "year": int(year) if year is not None else None,
                "value": value,
                "valueType": row.get("valueType"),
                "source": row.get("source"),
                "time_detail": row.get("time_detail"),
                "timeCoverage": row.get("timeCoverage"),
            }
        )

    df = pd.DataFrame.from_records(records)
    # Drop rows with no value or year
    df = df.dropna(subset=["year", "value"])
    df["year"] = df["year"].astype(int)
    df = df.sort_values(["indicator", "geoAreaName", "year"])
    return df