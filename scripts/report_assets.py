"""Audit saved measurements and generate publication figures/tables; no model calls."""

import hashlib
import json
import math
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap

from tender.benchmarks import score_output

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "report"
F = OUT / "figures"
F.mkdir(exist_ok=True)
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "savefig.bbox": "tight",
        "pdf.fonttype": 42,
    }
)
colors = ["#24618c", "#bd7036"]
experiments = {}
audit = []
for path in sorted((ROOT / "eval/results").glob("*/summary.json")):
    summary = json.loads(path.read_text())
    rows = json.loads((path.parent / "runs.json").read_text())
    assert len(rows) == summary["runs"], path
    passes = sum(r["scores"].get("reference_correctness") == 1 for r in rows)
    assert passes == summary["pass_count"]
    assert math.isclose(passes / len(rows), summary["reference_pass_rate"])
    for key, value in summary["metrics"].items():
        vals = [r["scores"][key] for r in rows if r["scores"].get(key) is not None]
        assert math.isclose(statistics.mean(vals), value, abs_tol=1e-10), (path, key)
    for row in rows:
        scored = {
            x["key"]: x["score"]
            for x in score_output(row["inputs"], row["output"], row["reference"])["results"]
        }
        assert scored == row["scores"], (path, row["case_id"], scored, row["scores"])
    times = sorted(r["output"].get("latency_ms", 0) for r in rows if r["output"])
    assert statistics.median(times) == summary["latency_p50_ms"]
    experiments[path.parent.name] = (summary, rows)
    audit.append(
        {
            "experiment": path.parent.name,
            "runs": len(rows),
            "passes": passes,
            "scores_recomputed": True,
            "summary_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "runs_sha256": hashlib.sha256((path.parent / "runs.json").read_bytes()).hexdigest(),
        }
    )
q, qr = experiments["v3-qwen-agents"]
g, gr = experiments["v3-gemma-agents"]
for field in ["source_tree_sha256", "dataset_sha256", "package_sha256", "prompt_version"]:
    assert q[field] == g[field], field
assert (
    hashlib.sha256((ROOT / "eval/datasets/model-comparison-v3.json").read_bytes()).hexdigest()
    == q["dataset_sha256"]
)
for item in json.loads((ROOT / "reference_documents/download_manifest.json").read_text()):
    data = (ROOT / item["path"]).read_bytes()
    assert len(data) == item["bytes"]
    assert hashlib.sha256(data).hexdigest() == item["sha256"]
# The stored p95 is a discrete order statistic in the benchmark, not interpolation.
for summary, rows in experiments.values():
    times = sorted(r["output"].get("latency_ms", 0) for r in rows if r["output"])
    assert summary["latency_p95_ms"] == times[min(len(times) - 1, int(len(times) * 0.95))]
(OUT / "evaluation_audit.json").write_text(
    json.dumps(
        {
            "method": "Recomputed each saved score using score_output; checked counts, macro means, medians, p95 order statistics, paired hashes and source manifests. No experiments rerun.",
            "experiments": audit,
            "matched_v3_hashes": True,
            "source_files_verified": 3,
        },
        indent=2,
    )
    + "\n"
)


def save(fig, name):
    fig.savefig(F / (name + ".pdf"))
    fig.savefig(F / (name + ".png"), dpi=180)
    plt.close(fig)


keys = [
    "reference_correctness",
    "field_precision",
    "field_recall",
    "quote_grounding",
    "citation_grounding",
    "defect_recall_proxy",
    "false_positive_free",
]
labels = [
    "Strict case\npass",
    "Field\nprecision",
    "Field\nrecall",
    "Quote\ngrounding",
    "Citation\ngrounding",
    "Defect recall\nproxy",
    "No extra\ngrounded ID",
]
x = np.arange(len(keys))
fig, ax = plt.subplots(figsize=(10, 3.5))
for i, (s, label) in enumerate([(q, "Qwen 2.5 3B"), (g, "Gemma 3 4.3B")]):
    vals = [s["metrics"][k] * 100 for k in keys]
    bars = ax.bar(x + (i - 0.5) * 0.36, vals, 0.36, label=label, color=colors[i])
    ax.bar_label(bars, fmt="%.1f", fontsize=8, padding=2)
ax.set_xticks(x, labels)
ax.set_ylim(0, 115)
ax.set_ylabel("Score (%)")
ax.legend(ncol=2, loc="upper center")
ax.grid(axis="y", alpha=0.18)
ax.set_axisbelow(True)
save(fig, "agent_metrics")

fig, ax = plt.subplots(figsize=(8.5, 3.4))
for i, rows in enumerate([qr, gr]):
    vals = [r["output"]["latency_ms"] / 1000 for r in rows]
    ax.scatter(
        np.arange(len(rows)),
        vals,
        color=colors[i],
        label=["Qwen 2.5 3B", "Gemma 3 4.3B"][i],
        s=28,
        marker=["o", "s"][i],
    )
ax.set_xticks(
    range(14),
    [
        r["case_id"]
        .replace("-defect", "")
        .replace("quantity_verifier", "quantity")
        .replace("rate_estimator", "rate")
        .replace("pricing_verifier", "pricing")
        .replace("evidence_audit", "evidence")
        .replace("intake-unseen-", "intake-")
        for r in qr
    ],
    rotation=45,
    ha="right",
    fontsize=8,
)
ax.set_ylabel("Target latency (s)")
ax.legend()
ax.grid(axis="y", alpha=0.2)
save(fig, "latency")

matrix = np.array(
    [[r["scores"]["reference_correctness"] for r in qr], [r["scores"]["reference_correctness"] for r in gr]]
)
fig, ax = plt.subplots(figsize=(10, 2.6))

ax.imshow(matrix, aspect="auto", cmap=ListedColormap(["#eeddd2", "#b3d1df"]), vmin=0, vmax=1)
for i in range(2):
    for j in range(14):
        ax.text(j, i, "Pass" if matrix[i, j] else "Fail", ha="center", va="center", fontsize=8)
ax.set_yticks([0, 1], ["Qwen", "Gemma"])
ax.set_xticks(
    range(14),
    [r["case_id"].replace("-defect", "").replace("_", " ") for r in qr],
    rotation=55,
    ha="right",
    fontsize=8,
)
save(fig, "case_matrix")

names = ["Office shell", "Internal electricity", "Internal water", "Downcomer", "Manual alarm"]
values = [9276000, 1159500, 371040, 138000, 84000]
assert sum(values) == 11028540
fig, ax = plt.subplots(figsize=(8, 3.1))
bars = ax.barh(names[::-1], np.array(values[::-1]) / 100000, color="#24618c")
ax.bar_label(
    bars, labels=[f"{v / 100000:.2f} ({v / sum(values):.1%})" for v in values[::-1]], padding=4, fontsize=9
)
ax.set_xlim(0, 117)
ax.set_xlabel("INR lakh; labels include share of defined scope")
ax.grid(axis="x", alpha=0.15)
ax.set_axisbelow(True)
save(fig, "cost_composition")


# Tables are generated from audited records rather than copied by hand.
def esc(s):
    return str(s).replace("_", r"\_").replace("%", r"\%").replace("&", r"\&")


def table(headers, rows, widths=None):
    spec = widths or ("l" + "r" * (len(headers) - 1))
    return (
        "\\begin{tabularx}{\\linewidth}{"
        + spec
        + "}\n\\toprule\n"
        + " & ".join(headers)
        + r" \\"
        + "\n\\midrule\n"
        + "\n".join(" & ".join(esc(c) for c in row) + r" \\" for row in rows)
        + "\n\\bottomrule\n\\end{tabularx}\n"
    )


metric_names = [
    "Strict case pass",
    "Field precision",
    "Field recall",
    "Exact-quote grounding",
    "Citation grounding",
    "Defect recall proxy",
    "No extra grounded evidence ID",
]
rows = []
for k, label in zip(keys, metric_names):
    n = sum(k in r["scores"] for r in qr)
    rows.append([label, str(n), f"{q['metrics'][k]:.4f}", f"{g['metrics'][k]:.4f}"])
(OUT / "metrics_table.tex").write_text(table(["Metric", "Cases", "Qwen", "Gemma"], rows, "Xrrr"))
(OUT / "cases_table.tex").write_text(
    table(
        ["Case", "Qwen", "Gemma"],
        [
            [
                r["case_id"],
                "Pass" if r["scores"]["reference_correctness"] else "Fail",
                "Pass" if gr[i]["scores"]["reference_correctness"] else "Fail",
            ]
            for i, r in enumerate(qr)
        ],
        "Xll",
    )
)
(OUT / "latency_table.tex").write_text(
    table(
        ["Model", "p50 (s)", "p95 (s)", "Execution"],
        [
            [s["model"], f"{s['latency_p50_ms'] / 1000:.2f}", f"{s['latency_p95_ms'] / 1000:.2f}", "14/14"]
            for s in [q, g]
        ],
        "Xrrr",
    )
)
print("Audited", len(audit), "saved experiments; figures and tables generated.")
