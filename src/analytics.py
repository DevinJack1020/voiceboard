from __future__ import annotations

import pandas as pd

from src.classifiers.base import BUSINESS_CATEGORIES


CATEGORY_ORDER = {category: index for index, category in enumerate(BUSINESS_CATEGORIES)}


def calculate_priority(records: list[dict]) -> list[dict]:
    """Aggregate formal categories with frequency × average impact."""
    if not records:
        return []
    frame = pd.DataFrame(records)
    if "category" not in frame or "impact_level" not in frame:
        return []
    formal = frame[frame["category"].isin(BUSINESS_CATEGORIES)].copy()
    if formal.empty:
        return []
    formal["impact_level"] = pd.to_numeric(formal["impact_level"], errors="coerce")
    formal = formal.dropna(subset=["impact_level"])
    grouped = (
        formal.groupby("category", observed=True)["impact_level"]
        .agg(frequency="size", average_impact="mean")
        .reset_index()
    )
    grouped["priority_score_raw"] = grouped["frequency"] * grouped["average_impact"]
    grouped["category_order"] = grouped["category"].map(CATEGORY_ORDER)
    grouped = grouped.sort_values(
        ["priority_score_raw", "average_impact", "frequency", "category_order"],
        ascending=[False, False, False, True],
        kind="stable",
    )
    result: list[dict] = []
    for row in grouped.to_dict(orient="records"):
        result.append(
            {
                "category": row["category"],
                "frequency": int(row["frequency"]),
                "average_impact": round(float(row["average_impact"]), 1),
                "priority_score": round(float(row["priority_score_raw"]), 1),
            }
        )
    return result


def top_pain_points(records: list[dict], limit: int = 5) -> list[dict]:
    priorities = calculate_priority(records)[: max(0, limit)]
    return [{"rank": index, **row} for index, row in enumerate(priorities, start=1)]
