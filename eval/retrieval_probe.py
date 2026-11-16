"""Retrieval probe: score semantics, tokenizer recall, trust handling, hybrid gating, chunk cuts, confidence prototype.

All corpora here are SYNTHETIC text written for this probe (no prices matter). They test mechanisms,
not real-world retrieval quality on real schedules.
"""

import math
import re
import sys
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path

from tender import knowledge
from tender.config import Settings
from tender.db import Repository
from tender.knowledge import KnowledgeGateway
from tender.schemas import SourceDocument
from tender.storage import ObjectStore

SCRATCH = Path(sys.argv[1])
SCRATCH.mkdir(parents=True, exist_ok=True)
TENANT = "t"
REPO_TOKENS = knowledge.tokens


def fixed_tokens(value: str) -> list[str]:
    # keeps item codes such as 9.147.A3.1 and 1.5, but strips trailing '.' / '-'
    return re.findall(r"\w+(?:[.-]\w+)*", value.casefold())


def make_gateway(tag: str) -> KnowledgeGateway:
    root = Path(tempfile.mkdtemp(prefix=f"{tag}-", dir=SCRATCH))
    s = Settings(
        _env_file=None, data_dir=root / "var", database_dir=root / "db", database_url=f"sqlite:///{root}/s.db"
    )
    return KnowledgeGateway(Repository(s), ObjectStore(s), s)


def doc(id_, text, trust="approved", authority="cpwd", effective_from=date(2020, 1, 1)):
    return SourceDocument(
        id=id_,
        title=id_,
        version="1",
        kind="schedule",
        authority=authority,
        effective_from=effective_from,
        text=text,
        trust=trust,
        discipline="all",
    )


def auroc(pos, neg):
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


# ----------------------------------------------------------------------------- corpus
ITEMS = {  # trade -> [(description, unit, query)]
    "masonry": [
        (
            "Brick work with common burnt clay bricks in cement mortar 1:6 in superstructure above plinth level.",
            "cum",
            "brick masonry cement mortar 1:6 superstructure",
        ),
        (
            "Half brick masonry in cement mortar 1:4 for partition walls.",
            "sqm",
            "half brick partition wall mortar 1:4",
        ),
        (
            "Fly ash lime bricks masonry in cement mortar 1:6 including scaffolding.",
            "cum",
            "fly ash bricks masonry scaffolding",
        ),
        (
            "Random rubble stone masonry in cement mortar 1:6 for foundations.",
            "cum",
            "rubble stone masonry foundations",
        ),
        (
            "AAC block masonry 200 mm thick in thin bed adhesive.",
            "cum",
            "AAC block masonry thin bed adhesive",
        ),
    ],
    "concrete": [
        (
            "Reinforced cement concrete M25 grade in columns, beams and slabs excluding steel and shuttering.",
            "cum",
            "RCC M25 columns beams slabs",
        ),
        (
            "Plain cement concrete 1:4:8 using graded stone aggregate 40 mm nominal size in foundations.",
            "cum",
            "plain cement concrete 1:4:8 foundation",
        ),
        (
            "Thermo mechanically treated reinforcement bars Fe 500D including cutting bending and binding.",
            "kg",
            "TMT reinforcement Fe 500D bending binding",
        ),
        (
            "Centering and shuttering including strutting for slabs, soffit of beams and columns.",
            "sqm",
            "shuttering centering soffit beams",
        ),
        (
            "Providing ready mixed concrete M30 pumped to floor level.",
            "cum",
            "ready mixed concrete M30 pumped",
        ),
    ],
    "finishes": [
        (
            "12 mm cement plaster in cement mortar 1:6 on brick walls with neeru finish.",
            "sqm",
            "cement plaster 12 mm 1:6 walls",
        ),
        (
            "Vitrified floor tiles 600x600 mm laid in cement mortar 1:4 with joints filled with tile grout.",
            "sqm",
            "vitrified floor tiles 600x600 grout",
        ),
        ("Kota stone flooring 25 mm thick laid over cement mortar bed.", "sqm", "kota stone flooring 25 mm"),
        (
            "Acrylic emulsion paint two coats over putty on interior walls.",
            "sqm",
            "acrylic emulsion paint interior walls putty",
        ),
        ("Ceramic glazed wall tiles in toilets up to dado height.", "sqm", "ceramic wall tiles toilet dado"),
    ],
    "roof_openings": [
        (
            "Applying cementitious waterproofing treatment on roof slab with brick bat coba.",
            "sqm",
            "roof waterproofing brick bat coba",
        ),
        (
            "Providing thermal insulation of extruded polystyrene boards on terrace.",
            "sqm",
            "terrace thermal insulation polystyrene",
        ),
        (
            "Aluminium sliding windows with 5 mm clear glass and anodised sections.",
            "sqm",
            "aluminium sliding windows anodised glass",
        ),
        (
            "Flush door shutters 35 mm thick with commercial ply face veneer.",
            "sqm",
            "flush door shutter 35 mm ply veneer",
        ),
        (
            "Steel rolling shutter with box guide channels and top cover.",
            "sqm",
            "rolling shutter guide channels",
        ),
    ],
    "electrical": [
        (
            "Wiring for light point with 1.5 sq mm FRLS copper conductor in concealed PVC conduit.",
            "point",
            "light point wiring FRLS copper conduit",
        ),
        (
            "Earthing with GI pipe electrode 40 mm diameter 3 m long including accessories.",
            "each",
            "earthing GI pipe electrode",
        ),
        ("LED batten luminaire 20 W fixed on ceiling.", "each", "LED batten 20 W luminaire"),
        (
            "Miniature circuit breaker 32 A double pole in distribution board.",
            "each",
            "MCB 32 A double pole distribution board",
        ),
    ],
    "plumbing_fire": [
        (
            "CPVC pipe 25 mm diameter concealed in walls including fittings.",
            "rm",
            "CPVC pipe 25 mm concealed",
        ),
        (
            "Water closet European type white vitreous china with flushing cistern.",
            "each",
            "European water closet flushing cistern",
        ),
        ("Overhead water tank HDPE 1000 litre capacity on roof.", "each", "HDPE water tank 1000 litre"),
        (
            "ABC type portable fire extinguisher 6 kg capacity with wall bracket.",
            "each",
            "fire extinguisher ABC 6 kg",
        ),
        ("Smoke detector addressable type installed on false ceiling.", "each", "addressable smoke detector"),
        (
            "Hydrant valve landing type with coupling and hose pipe 15 m.",
            "each",
            "landing valve hydrant hose",
        ),
    ],
    "external_earth": [
        (
            "Interlocking concrete paver block 60 mm thick for pathways.",
            "sqm",
            "interlocking paver block pathways",
        ),
        ("Chain link fencing 1.8 m high with MS angle posts.", "rm", "chain link fencing MS angle posts"),
        (
            "Excavation in ordinary soil for foundation up to 1.5 m depth.",
            "cum",
            "excavation ordinary soil foundation depth",
        ),
        (
            "Filling in plinth with sand under floors compacted in layers.",
            "cum",
            "plinth filling sand compacted",
        ),
    ],
}
NEGATIVE = [  # absent topics; some share generic tokens; the last 8 are deliberate hard negatives
    "elastomeric bridge bearing replacement per each",
    "railway track ballast cleaning per cum",
    "tower crane monthly hire charges",
    "sewage treatment plant 50 KLD supply and installation",
    "swimming pool filtration plant installation",
    "helipad perimeter lighting system",
    "marine piling jetty construction",
    "shotcrete tunnel lining rate per cum",
    "diaphragm wall underground metro station",
    "supply of diesel generator set 250 kVA",
    "elevator lift 8 passenger installation",
    "geo textile fabric road embankment",
    "bituminous concrete wearing course road surfacing",
    "bore well drilling 150 mm diameter",
    "optical fibre cable laying trench",
    "HVAC chiller 100 TR installation",
    "stainless steel kitchen exhaust hood",
    "railway platform shelter fabrication",
    "retaining wall gabion boxes riverbank",
    "CCTV camera installation 4 MP",
    "road marking thermoplastic paint",
    "false ceiling gypsum board 12.5 mm",
    "providing acoustic panels auditorium walls",
    # hard negatives (partial overlap with real items)
    "wind turbine foundation concrete M40",
    "providing and fixing solar street light pole",
    "providing and laying cement concrete road pavement M30",
    "reinforcement steel bars fabrication for bridge girders",
    "brick masonry for chimney stack in refractory mortar",
    "sand filling for road shoulders",
    "plaster of paris decorative cornice",
    "kota stone cladding for external facade",
]


def build_corpus(gw):
    gold = {}
    for trade, rows in ITEMS.items():
        lines = [
            f"Item {i + 1}.{n + 1} | {d} | {u} | {1000 + 37 * n}"
            for n, (d, u, _) in enumerate(rows)
            for i in [list(ITEMS).index(trade)]
        ]
        gw.index_document(doc(trade, "\n".join(lines)), TENANT)
        for _, _, q in rows:
            gold[q] = trade
    return gold


def top_ids(res):
    return [r["title"] for r in res["results"]]


out = {}

# ---------------------------------------------------------------- E1 score semantics + ranking quality
gw = make_gateway("e1")
gold = build_corpus(gw)
pos_q, neg_q = list(gold), NEGATIVE
rows = []
for label, queries in (("answerable", pos_q), ("unanswerable", neg_q)):
    for q in queries:
        res = gw.search(q, TENANT, limit=5)
        rows.append(
            (
                label,
                q,
                res["results"][0]["score"] if res["results"] else 0.0,
                len(res["results"]),
                top_ids(res),
            )
        )
ans = [r for r in rows if r[0] == "answerable"]
una = [r for r in rows if r[0] == "unanswerable"]
r1 = sum(r[4][:1] == [gold[r[1]]] for r in ans) / len(ans)
r5 = sum(gold[r[1]] in r[4] for r in ans) / len(ans)
print("E1  corpus: %d docs / %d answerable queries / %d unanswerable" % (len(ITEMS), len(ans), len(una)))
print("E1  doc-level recall@1=%.2f recall@5=%.2f (repo tokenizer)" % (r1, r5))
print("E1  distinct top-1 'score' values, answerable:", sorted({round(r[2], 6) for r in ans}))
print("E1  distinct top-1 'score' values, unanswerable:", sorted({round(r[2], 6) for r in una}))
print("E1  unanswerable queries that still return >=1 result: %d/%d" % (sum(r[3] > 0 for r in una), len(una)))
print(
    "E1  AUROC(repo top-1 score, answerable vs unanswerable) = %.3f"
    % auroc([r[2] for r in ans], [r[2] for r in una])
)
print("E1  1/61 =", round(1 / 61, 6), "(top-1 RRF value in keyword mode)")

# ---------------------------------------------------------------- E2 tokenizer recall A/B
words_final = [
    "plinth",
    "lintel",
    "parapet",
    "coping",
    "sunshade",
    "skirting",
    "dado",
    "chajja",
    "weathering",
    "cornice",
    "gutter",
    "downpipe",
    "manhole",
    "septic",
    "soakpit",
    "kerbstone",
    "bollard",
    "culvert",
    "headwall",
    "wingwall",
]
words_mid = [
    "tiebeam",
    "stirrup",
    "sill",
    "fascia",
    "rafter",
    "purlin",
    "gusset",
    "anchor",
    "grouting",
    "bracing",
    "ferrule",
    "flashing",
    "mullion",
    "transom",
    "jamb",
    "newel",
    "baluster",
    "riser",
    "tread",
    "nosing",
]


def ab_recall(tok):
    knowledge.tokens = tok
    g = make_gateway("e2")
    for i, (a, b) in enumerate(zip(words_final, words_mid)):
        g.index_document(
            doc(
                f"d{i}",
                f"The contractor shall complete the {b} work before the {a}. Payment follows measurement.",
            ),
            TENANT,
        )
    hit_final = sum(f"d{i}" in top_ids(g.search(a, TENANT, limit=5)) for i, a in enumerate(words_final))
    hit_mid = sum(f"d{i}" in top_ids(g.search(b, TENANT, limit=5)) for i, b in enumerate(words_mid))
    knowledge.tokens = REPO_TOKENS
    return hit_final, hit_mid


rf, rm = ab_recall(REPO_TOKENS)
ff, fm = ab_recall(fixed_tokens)
print("E2  repo tokenizer : sentence-final term found %d/20, mid-sentence term found %d/20" % (rf, rm))
print("E2  fixed tokenizer: sentence-final term found %d/20, mid-sentence term found %d/20" % (ff, fm))
print("E2  tokens('Brick masonry. Rate 6200.') ->", REPO_TOKENS("Brick masonry. Rate 6200."))
print("E2  tokens('M-25 and m³ and 9.147.A3.1') ->", REPO_TOKENS("M-25 and m³ and 9.147.A3.1"))

# ---------------------------------------------------------------- E3 trust / authority are not used in ranking
for first, second in (("candidate", "approved"), ("approved", "candidate")):
    g = make_gateway("e3")
    g.index_document(
        doc(
            "A-" + first, "Brick masonry specification for superstructure.", trust=first, authority="unknown"
        ),
        TENANT,
    )
    g.index_document(
        doc("B-" + second, "Brick masonry specification for superstructure.", trust=second, authority="cpwd"),
        TENANT,
    )
    res = g.search("brick masonry", TENANT, authority="cpwd")
    print(
        "E3  insert order [%s(unknown-auth), %s(cpwd)] -> ranked:" % (first, second),
        [(r["title"], r["trust"], r["authority"]) for r in res["results"]],
    )


# ---------------------------------------------------------------- E4 hybrid gating (code-path demonstration)
class FakeEmbedder:
    name = "fake://hashed-bow"

    def embed(self, texts):
        out_ = []
        for t in texts:
            v = [0.0] * 64
            for tok in REPO_TOKENS(t):
                v[hash(tok) % 64] += 1.0
            out_.append(v)
        return out_


g = make_gateway("e4")
g.embedder = FakeEmbedder()
build_corpus(g)
for q in ("zzzz qqqq xxxx", "elastomeric bridge bearing replacement"):
    res = g.search(q, TENANT, limit=5)
    print("E4  hybrid mode=%s query=%r -> %d results" % (res["mode"], q, len(res["results"])))
g2 = make_gateway("e4b")
build_corpus(g2)
print(
    "E4  keyword mode query='zzzz qqqq xxxx' ->",
    len(g2.search("zzzz qqqq xxxx", TENANT, limit=5)["results"]),
    "results",
)


# ---------------------------------------------------------------- E5 chunk cut rate by row length
def cut_rate(L, n=60000):
    spans = [(i, min(i + 2400, n)) for i in range(0, n, 2100)]
    bad = 0
    total = n - L
    for p in range(total):
        if not any(s <= p and p + L <= e for s, e in spans):
            bad += 1
    return bad / total


print("E5  fraction of positions where a row of L chars is split across chunks (no chunk holds it whole):")
print("E5  ", {L: round(cut_rate(L), 3) for L in (150, 300, 450, 600, 900, 1200)})


# ---------------------------------------------------------------- E6 confidence prototype
def confidence(query, results, corpus_counts, tok):
    """IDF-weighted share of query terms present in the top chunk; unseen terms get the maximum IDF."""
    if not results:
        return 0.0
    N = len(corpus_counts)
    qterms = set(tok(query))

    def idf(t):
        n = sum(t in c for c in corpus_counts)
        return math.log(1 + (N - n + 0.5) / (n + 0.5))

    top = set(tok(results[0]["content"]))
    denom = sum(idf(t) for t in qterms) or 1.0
    return sum(idf(t) for t in qterms if t in top) / denom


def eval_conf(tok, tag):
    knowledge.tokens = tok
    g = make_gateway(tag)
    build_corpus(g)
    chunk_counts = [
        Counter(tok(e["content"])) for q in ["x"] for e in g.search("item", TENANT, limit=50)["results"]
    ]
    # full corpus = every chunk, fetched without a query-dependent filter
    chunk_counts = [
        Counter(tok(t))
        for t in ("\n".join(f"Item | {d} | {u}" for d, u, _ in rows_) for rows_ in ITEMS.values())
    ]
    sc = {"A": [], "U": []}
    for key_, qs in (("A", pos_q), ("U", neg_q)):
        for q in qs:
            res = g.search(q, TENANT, limit=5)
            sc[key_].append(confidence(q, res["results"], chunk_counts, tok))
    knowledge.tokens = REPO_TOKENS
    return sc


for tok, name in ((REPO_TOKENS, "repo tokenizer"), (fixed_tokens, "fixed tokenizer")):
    sc = eval_conf(tok, "e6")
    print(
        "E6  [%s] AUROC(coverage confidence) = %.3f | mean conf answerable=%.2f unanswerable=%.2f"
        % (name, auroc(sc["A"], sc["U"]), sum(sc["A"]) / len(sc["A"]), sum(sc["U"]) / len(sc["U"]))
    )
    for lo, hi in ((0.0, 0.4), (0.4, 0.7), (0.7, 1.01)):
        a = sum(lo <= s < hi for s in sc["A"])
        u = sum(lo <= s < hi for s in sc["U"])
        if a + u:
            print(
                "E6      bin [%.1f,%.1f): answerable=%d unanswerable=%d  -> precision(answerable)=%.2f"
                % (lo, hi, a, u, a / (a + u))
            )
