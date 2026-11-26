#!/usr/bin/env python
"""ETF 聚类分析 — 数据驱动的分组。

读入 01_extract_features.py 输出的 etf_features.csv，
PCA 降维 + K-means 聚类，输出分组标签和可视化。
"""

import sys
import os
import json
import numpy as np
import pandas as pd

_project_root = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score


DATA_PATH = os.path.join(os.path.dirname(__file__), "etf_features.csv")
OUT_DIR = os.path.dirname(__file__)


def main():
    df = pd.read_csv(DATA_PATH, encoding="utf-8-sig")
    print(f"加载 {len(df)} 只 ETF\n")

    # ── 选择聚类特征 ──
    feature_cols = [
        "median_atr_pct",
        "volatility_20d",
        "max_drawdown",
        "return_skew",
        "volume_cv",
        "strong_trend_pct",
        "median_adx",
    ]
    raw = df[feature_cols].copy()
    raw.columns = [c.replace("_", " ") for c in feature_cols]  # 展示用

    # ── 标准化 ──
    scaler = StandardScaler()
    X = scaler.fit_transform(df[feature_cols].fillna(0).values)

    # ── PCA 降维 ──
    pca = PCA()
    X_pca = pca.fit_transform(X)
    explained = pca.explained_variance_ratio_
    cumsum = np.cumsum(explained)
    print("=== PCA 解释方差 ===")
    for i, (ev, cs) in enumerate(zip(explained, cumsum)):
        print(f"  PC{i+1}: {ev:.2%} (累计 {cs:.2%})")

    # 选择保留 80%+ 方差的主成分数
    n_keep = next(i + 1 for i, cs in enumerate(cumsum) if cs >= 0.80)
    print(f"  保留前 {n_keep} 个主成分 ({cumsum[n_keep-1]:.1%})\n")

    # ── K-means 聚类，尝试 k=2~5 ──
    print("=== K-means 聚类评估 ===")
    results = []
    for k in range(2, 6):
        km = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = km.fit_predict(X_pca[:, :n_keep])
        sil = silhouette_score(X_pca[:, :n_keep], labels)
        inertia = km.inertia_
        results.append({"k": k, "silhouette": sil, "inertia": inertia})
        sizes = pd.Series(labels).value_counts().sort_index()
        print(f"  k={k}: silhouette={sil:.4f}, inertia={inertia:.1f}, sizes={dict(sizes)}")

    # 选最优 k
    best_k = max(results, key=lambda r: r["silhouette"])["k"]
    print(f"\n  最优 k = {best_k} (最高 silhouette 分数)\n")

    # ── 最终聚类 ──
    km_final = KMeans(n_clusters=best_k, random_state=42, n_init=10)
    labels = km_final.fit_predict(X_pca[:, :n_keep])
    df["cluster"] = labels

    # ── 每个聚类输出特征均值 ──
    print("=== 聚类特征均值 ===")
    group_stats = df.groupby("cluster")[feature_cols].mean().round(4)
    group_stats["count"] = df.groupby("cluster").size()
    for cluster_id in sorted(df["cluster"].unique()):
        members = df[df["cluster"] == cluster_id]
        print(f"\n  Cluster {cluster_id} ({len(members)} 只):")
        for _, etf in members.iterrows():
            print(f"    {etf['code']} {etf['name']} "
                  f"(现有分组: {etf['existing_vol_group']}, "
                  f"市场: {etf['regime_group']})")
        print(f"    特征均值:")
        for col in feature_cols:
            print(f"      {col:20s}: {group_stats.loc[cluster_id, col]:.4f}")

    # ── 与现有分组的对比 ──
    print("\n=== 与现有 volatility_group 对比 ===")
    cross = pd.crosstab(df["existing_vol_group"], df["cluster"])
    print(cross)

    # ── 保存结果 ──
    df.to_csv(os.path.join(OUT_DIR, "etf_clusters.csv"), index=False, encoding="utf-8-sig")
    print(f"\n聚类结果已保存: etf_clusters.csv")

    # ── 输出聚类摘要 JSON（供后续脚本使用） ──
    cluster_map = {}
    for _, row in df.iterrows():
        cluster_map[row["code"]] = int(row["cluster"])
    with open(os.path.join(OUT_DIR, "cluster_labels.json"), "w") as f:
        json.dump(cluster_map, f, indent=2)
    print(f"聚类标签已保存: cluster_labels.json")

    # ── PCA 载荷分析（各特征的贡献） ──
    print("\n=== PCA 载荷（各特征对 PC1/PC2 的贡献） ===")
    loadings = pd.DataFrame(
        pca.components_[:2].T,
        index=feature_cols,
        columns=[f"PC1 ({explained[0]:.1%})", f"PC2 ({explained[1]:.1%})"],
    )
    print(loadings.round(3))

    # ── 额外分析：ATR 天然分界点 ──
    print("\n=== ATR% 分布（按中位数排序） ===")
    atr_sorted = df[["code", "name", "median_atr_pct", "existing_vol_group", "cluster"]].sort_values(
        "median_atr_pct"
    )
    for _, row in atr_sorted.iterrows():
        print(f"  {row['median_atr_pct']:.4f}  {row['code']} {row['name'][:12]:12s}  "
              f"现={row['existing_vol_group'][:8]:8s}  聚类={row['cluster']}")


if __name__ == "__main__":
    main()
