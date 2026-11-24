"""Imported statistical routines from Aging Genomics Lab, under the MIT license."""
from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

if TYPE_CHECKING:
    from typing import Any as Dataset


def benjamini_hochberg(pvalues: np.ndarray | list[float]) -> np.ndarray:
    """Benjamini-Hochberg false-discovery-rate adjusted p-values."""
    p = np.asarray(pvalues, dtype=float)
    if p.ndim != 1 or not np.all(np.isfinite(p)) or np.any((p < 0) | (p > 1)):
        raise ValueError("p-values must be a finite vector in [0, 1].")
    if len(p) == 0:
        return np.array([], dtype=float)
    ordering = np.argsort(p)
    ranked = p[ordering]
    adjusted = np.minimum.accumulate((ranked * len(p) / np.arange(1, len(p) + 1))[::-1])[::-1]
    result = np.empty_like(adjusted)
    result[ordering] = np.minimum(adjusted, 1.0)
    return result


def age_association(ds: Dataset, *, group: str | None = None) -> pd.DataFrame:
    """Exploratory per-gene Spearman associations with chronological age.

    P-values do not adjust for sex, batch, ancestry, cell composition or other
    covariates. Group-vs-age confounding is especially important in aging cohorts.
    """
    if group is not None and group not in ds.groups:
        raise ValueError(f"Unknown group: {group}")
    samples = ds.metadata.index if group is None else ds.metadata.index[ds.metadata.group == group]
    ages = ds.metadata.loc[samples, "age"].to_numpy(dtype=float)
    if len(np.unique(ages)) < 3:
        raise ValueError("At least three distinct ages are needed for association analysis.")
    rows = []
    for gene, vals in ds.expression[samples].iterrows():
        x = vals.to_numpy(dtype=float)
        if np.std(x) <= 1e-12:
            rho, p = 0.0, 1.0
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                rho, p = spearmanr(ages, x)
            if not np.isfinite(p):
                rho, p = 0.0, 1.0
        rows.append((gene, float(rho), float(p)))
    frame = pd.DataFrame(rows, columns=["gene_id", "spearman_rho", "p_value"])
    frame["fdr"] = benjamini_hochberg(frame["p_value"].to_numpy())
    return frame.sort_values(["fdr", "p_value", "gene_id"], kind="stable").reset_index(drop=True)
