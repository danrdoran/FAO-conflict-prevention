from __future__ import annotations

import logging
from io import StringIO
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

import pandas as pd
import requests

logger = logging.getLogger(__name__)


class FAOSDGClient:
    """
    Minimal client for the FAO SDG SDMX API using the DF_SDG_ALL_INDICATORS dataset.

    SDMX REST pattern (FAO/Statsuite):
      GET {base}/data/{AGENCY,DATAFLOW,VERSION}/all
        ?dimensionAtObservation=AllDimensions&format=csvfilewithlabels
        [&startPeriod=YYYY][&endPeriod=YYYY]
    """

    def __init__(
        self,
        base_url: str = "https://nsi-release-ro-statsuite.fao.org/rest",
        agency: str = "FAO",
        dataflow_id: str = "DF_SDG_ALL_INDICATORS",
        version: str = "1.0",
        timeout: int = 60,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.agency = agency
        self.dataflow_id = dataflow_id
        self.version = version
        self.timeout = timeout

        self._session = requests.Session()
        self._cache: Dict[Tuple[Optional[int], Optional[int]], pd.DataFrame] = {}

    @property
    def _flow_ref(self) -> str:
        return f"{self.agency},{self.dataflow_id},{self.version}"

    def _build_data_url(self) -> str:
        flow_encoded = quote(self._flow_ref)
        return f"{self.base_url}/data/{flow_encoded}/all"

    def _download_dataset(
        self,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None,
    ) -> pd.DataFrame:
        cache_key = (start_year, end_year)
        if cache_key in self._cache:
            return self._cache[cache_key]

        url = self._build_data_url()
        params = {
            "dimensionAtObservation": "AllDimensions",
            "format": "csvfilewithlabels",
        }
        if start_year is not None:
            params["startPeriod"] = str(start_year)
        if end_year is not None:
            params["endPeriod"] = str(end_year)

        logger.info("Requesting FAO SDG data: %s", url)
        resp = self._session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()

        df = pd.read_csv(StringIO(resp.text))
        self._cache[cache_key] = df
        return df

    def get_series_dataframe(
        self,
        series_code: str,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Return a tidy DataFrame for a single SDG series across all areas.

        Columns:
          series_code, series_name, area_code, area_name, year, value
        """
        raw = self._download_dataset(start_year, end_year)
        if raw.empty:
            return pd.DataFrame(
                columns=["series_code", "series_name", "area_code", "area_name", "year", "value"]
            )

        cols = list(raw.columns)

        def _find_col(code: str) -> str:
            for c in cols:
                if c.upper() == code:
                    return c
            raise KeyError(f"Column '{code}' not found. Columns: {cols}")

        series_col = _find_col("SERIES")
        ref_area_col = _find_col("REF_AREA")
        time_col = _find_col("TIME_PERIOD")
        value_col = _find_col("OBS_VALUE")
        freq_col = _find_col("FREQ")

        def _label_col(code_col: str) -> Optional[str]:
            try:
                idx = cols.index(code_col)
            except ValueError:
                return None
            return cols[idx + 1] if idx + 1 < len(cols) else None

        series_label_col = _label_col(series_col)
        area_label_col = _label_col(ref_area_col)

        df = raw.copy()

        # Annual only
        df = df[df[freq_col] == "A"]

        # Filter to series
        df = df[df[series_col] == series_code]
        if df.empty:
            return pd.DataFrame(
                columns=["series_code", "series_name", "area_code", "area_name", "year", "value"]
            )

        out = pd.DataFrame()
        out["series_code"] = df[series_col].astype(str)
        out["series_name"] = (
            df[series_label_col].astype(str) if series_label_col in df.columns else df[series_col].astype(str)
        )

        out["area_code"] = df[ref_area_col].astype(str)
        out["area_name"] = (
            df[area_label_col].astype(str) if area_label_col in df.columns else df[ref_area_col].astype(str)
        )

        out["year"] = pd.to_numeric(df[time_col], errors="coerce")
        out["value"] = pd.to_numeric(df[value_col], errors="coerce")
        out = out.dropna(subset=["year", "value"])
        out["year"] = out["year"].astype(int)

        return out[["series_code", "series_name", "area_code", "area_name", "year", "value"]]

    def list_areas(
        self,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None,
    ) -> List[str]:
        """
        Return a sorted list of unique area names (countries/regions).
        """
        raw = self._download_dataset(start_year, end_year)
        if raw.empty:
            return []

        cols = list(raw.columns)
        ref_area_col = next((c for c in cols if c.upper() == "REF_AREA"), None)
        if not ref_area_col:
            return []

        # label column follows code column in csvfilewithlabels
        idx = cols.index(ref_area_col)
        label_col = cols[idx + 1] if idx + 1 < len(cols) else None

        area_series = raw[label_col] if (label_col and label_col in raw.columns) else raw[ref_area_col]
        areas = sorted(set(str(x).strip() for x in area_series.dropna().unique()))
        return [a for a in areas if a]

    def get_timeseries(
        self,
        series_code: str,
        area_name: str,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None,
    ) -> Dict[int, float]:
        """
        Return {year: value} for one series_code and one area_name.
        """
        df = self.get_series_dataframe(series_code=series_code, start_year=start_year, end_year=end_year)
        if df.empty:
            return {}

        # case-insensitive exact match first, then fallback to contains
        area_lower = area_name.strip().lower()
        exact = df[df["area_name"].astype(str).str.lower() == area_lower]
        if exact.empty:
            contains = df[df["area_name"].astype(str).str.lower().str.contains(area_lower)]
            df_area = contains
        else:
            df_area = exact

        if df_area.empty:
            return {}

        out = {}
        for _, row in df_area.iterrows():
            y = int(row["year"])
            v = float(row["value"])
            out[y] = v
        return dict(sorted(out.items()))