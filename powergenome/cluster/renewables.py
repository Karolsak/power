"""
Flexible methods to cluster/aggregate renewable projects
"""
import logging
from pathlib import Path
from typing import Any, List, Union

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.cluster import AgglomerativeClustering

from powergenome.resource_clusters import MERGE

logger = logging.getLogger(__name__)


def load_site_profiles(path: Path, site_ids: List[str]) -> pd.DataFrame:
    suffix = path.suffix
    if suffix == ".parquet":
        df = pq.read_table(path, columns=site_ids).to_pandas()
    elif suffix == ".csv":
        df = pd.read_csv(path, usecols=site_ids)
    return df


def value_bin(
    s: pd.Series,
    bins: Union[int, List[float]] = None,
    q: Union[int, List[float]] = None,
) -> pd.DataFrame:
    if s.empty:
        return []
    if q:
        labels = pd.qcut(s, q=q, duplicates="drop", labels=False)
    elif bins:
        labels = pd.cut(s, bins=bins, duplicates="drop")
    else:
        logger.warning(
            "One of your renewables_clusters uses the 'bin' option but doesn't include "
            "either the 'bins' or 'q' argument. One of these is required to bin sites "
            "by a numeric feature. No binning will be performed on this group of sites."
        )
        labels = np.ones_like(s)

    return labels


def agg_cluster_profile(s: pd.Series, n_clusters: int) -> pd.DataFrame:
    if s.empty:
        return []
    if len(s) == 1:
        return [1]
    if n_clusters <= 0:
        logger.warning(
            f"You have entered a n_clusters parameter that is less than or equal to 0 "
            "in the settings parameter renewables_clusters. n_clusters must be >= 1. "
            "Manually setting n_clusters to 1 in this case."
        )
        n_clusters = 1
    if n_clusters > len(s):
        logger.warning(
            f"You have entered a n_clusters parameter that is greater than the number of "
            "renewable sites for one grouping in the settings parameter renewables_clusters."
            "Manually setting n_clusters to the number of renewable sites in this case."
        )
        n_clusters = len(s)

    clust = AgglomerativeClustering(n_clusters=n_clusters).fit(
        np.array([x for x in s.values])
    )
    labels = clust.labels_
    return labels


def agg_cluster_other(s: pd.Series, n_clusters: int) -> pd.DataFrame:
    if s.empty:
        return []
    if len(s) == 1:
        return [1]
    if n_clusters <= 0:
        logger.warning(
            f"You have entered a n_clusters parameter that is less than or equal to 0 "
            "in the settings parameter renewables_clusters. n_clusters must be >= 1. "
            "Manually setting n_clusters to 1 in this case."
        )
        n_clusters = 1
    if n_clusters > len(s):
        logger.warning(
            f"You have entered a n_clusters parameter that is greater than the number of "
            "renewable sites for one grouping in the settings parameter renewables_clusters."
            "Manually setting n_clusters to the number of renewable sites in this case."
        )
        n_clusters = len(s)
    clust = AgglomerativeClustering(n_clusters=n_clusters).fit(s.values.reshape(-1, 1))
    labels = clust.labels_
    return labels


def agglomerative_cluster_binned(
    data: pd.DataFrame, by: Union[str, List[str]], feature: str, n_clusters: int
) -> pd.DataFrame:
    if data.empty:
        data["cluster"] = []
        return data

    if feature == "profile":
        func = agg_cluster_profile
    else:
        func = agg_cluster_other

    grouped = data.groupby(by)
    df_list = []
    first_label = 0
    for _, _df in grouped:
        if len(_df) == 1:
            labels = 1
            labels += first_label
            _df["cluster"] = labels
        else:
            labels = func(_df[feature], min(n_clusters, len(_df)))
            labels += first_label
            first_label = max(labels) + 1
            _df["cluster"] = labels
        df_list.append(_df)
    df = pd.concat(df_list)

    return df


def agglomerative_cluster_no_bin(
    data: pd.DataFrame, feature: str, n_clusters: int
) -> pd.DataFrame:
    if data.empty:
        data["cluster"] = []
        return data
    _data = data.copy()
    if feature == "profile":
        func = agg_cluster_profile
    else:
        func = agg_cluster_other

    if len(_data) == 1:
        labels = 1
        _data["cluster"] = labels
    else:
        labels = func(_data[feature], min(n_clusters, len(_data)))
        _data["cluster"] = labels

    return _data


def agglomerative_cluster(binned: bool, data: pd.DataFrame, **kwargs) -> pd.DataFrame:
    kwargs.pop("method")
    if binned:
        return agglomerative_cluster_binned(data, **kwargs)
    else:
        return agglomerative_cluster_no_bin(data, **kwargs)


def value_filter(
    data: pd.DataFrame, feature: str, max_value: float = None, min_value: float = None
) -> pd.DataFrame:
    df = data.copy()
    if max_value:
        df = df.loc[df[feature] <= max_value, :]
    if min_value:
        df = df.loc[df[feature] >= min_value, :]

    return df


def min_capacity_mw(
    data: pd.DataFrame,
    min_cap: int = None,
    cap_col: str = "mw",
) -> pd.DataFrame:
    if "lcoe" not in data.columns:
        logger.warning(
            "You have selected a minimum capacity for one of the renewables_clusters "
            "groups. This feature is only available if the column 'lcoe' is included in "
            "your data file on renewable sites. No 'lcoe' column has been found, so all "
            "sites will be included in the final clusters."
        )
        return data
    if min_cap is None:
        return data

    _df = data.sort_values("lcoe")
    mask = np.ones(len(_df), dtype=bool)
    temp = (_df.loc[mask, cap_col].cumsum() < min_cap).values
    temp[temp.argmin()] = True
    mask[mask] = temp

    return _df.loc[mask, :]


def calc_cluster_values(
    df: pd.DataFrame,
    sums: List[str] = MERGE["sums"],
    means: List[str] = MERGE["means"],
    weight: str = MERGE["weight"],
) -> pd.DataFrame:
    sums = [s for s in sums if s in df.columns]
    means = [m for m in means if m in df.columns]
    assert weight in df.columns
    df = df.reset_index(drop=True)
    df["weight"] = df[weight] / df[weight].sum()

    data = {}
    for s in sums:
        data[s] = df[s].sum()
    for m in means:
        data[m] = np.average(df[m], weights=df[weight])

    _df = pd.DataFrame(data, index=[0])
    profile = df.loc[0, "profile"] * df.loc[0, "weight"]
    for row in df.loc[1:, :].itertuples():
        profile += row.profile * row.weight

    profile /= df["weight"].sum()

    _df["profile"] = [profile]
    _df["cluster"] = df["cluster"].values[0]

    return _df


CLUSTER_FUNCS = {"agglomerative": agglomerative_cluster}


def assign_site_cluster(
    renew_data: pd.DataFrame,
    profile_path: Path,
    regions: List[str],
    site_map: pd.DataFrame = None,
    min_capacity: int = None,
    filter: List[dict] = None,
    bin: List[dict] = None,
    group: List[str] = None,
    cluster: List[dict] = None,
    utc_offset: int = 0,
    **kwargs: Any,
) -> pd.DataFrame:
    data = renew_data.loc[renew_data["region"].isin(regions), :]

    for filt in filter or []:
        data = value_filter(
            data=data,
            feature=filt["feature"].lower(),
            max_value=filt.get("max"),
            min_value=filt.get("min"),
        )
    if data.empty:
        data["cluster"] = []
        return data
    if min_capacity:
        data = min_capacity_mw(data, min_cap=min_capacity)
    if site_map is not None:
        site_ids = [str(site_map.loc[i]) for i in data["cpa_id"]]
    else:
        site_ids = [str(i) for i in data["cpa_id"]]
    if profile_path is not None:
        cpa_profiles = load_site_profiles(profile_path, site_ids=list(set(site_ids)))
        profiles = [np.roll(cpa_profiles[site].values, utc_offset) for site in site_ids]
        data["profile"] = profiles

    bin_features = []
    for b in bin or []:
        feature = b.get("feature")
        if not feature:
            raise KeyError(
                "One of your renewables_clusters uses the 'bin' option but doesn't include "
                "the 'feature' argument. You must specify a numeric feature (column) to "
                "split the renewable sites into bins."
            )
        if feature not in data.columns:
            raise KeyError(
                "One of your renewables_clusters uses the 'bin' option and includes the "
                f"feature argument '{feature}', which is not in the renewable site data. The "
                "feature must be one of the columns in your renewable site data file."
            )
        if not data[feature].dtype.kind in "iufc":
            raise TypeError(
                f"You specified the feature '{feature}' to bin one of your renewables_clusters. "
                f"'{feature}' is not a numeric column. Binning requires a numeric column."
            )
        feature = feature.lower()
        bin_features.append(f"{feature}_bin")
        data[f"{feature}_bin"] = value_bin(data[feature], b.get("bins"), b.get("q"))

    group_by = bin_features + ([g.lower() for g in group or []])
    prev_feature_cluster_col = None
    for clust in cluster or []:
        if "mw_per_cluster" in clust and clust.get("n_clusters") is None:
            clust["n_clusters"] = int(data["mw"].sum() / clust["mw_per_cluster"]) + 1

        if "cluster" in data.columns and prev_feature_cluster_col:
            data = data.rename(columns={"cluster": prev_feature_cluster_col})
        if group_by:
            clust["by"] = group_by
            data = CLUSTER_FUNCS[clust["method"]](True, data, **clust)
        else:
            data = CLUSTER_FUNCS[clust["method"]](False, data, **clust)

        group_by.append(f"{clust['feature']}_clust")
        prev_feature_cluster_col = f"{clust['feature']}_clust"

    if "cluster" not in data.columns:
        if group_by:
            i = 1
            df_list = []
            for _, _df in data.groupby(group_by):
                _df["cluster"] = i
                df_list.append(_df)
                i += 1
            data = pd.concat(df_list)
        else:
            data["cluster"] = range(1, len(data) + 1)

    return data