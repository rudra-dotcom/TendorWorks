# TendorWorks probes

Scripts import the repo's own code and write only to a scratch directory you give them. Run them from the repo root after `uv sync --frozen`. In PowerShell, pass the scratch path explicitly (do not use the Bash-style `$SCRATCH` placeholder).

$SCRATCH = "D:\College\Semester  (7)\BTP\TendorWorks\empty"


    $scratch = "$PWD\empty"
    uv run python eval/retrieval_probe.py $scratch
    uv run python eval/intake_probe.py    $scratch
    uv run python eval/engine_probe.py    $scratch
    uv run python eval/silent_probe.py    $scratch
    uv run python eval/verify_probe.py    $scratch examples/evaluation-cases.json
    uv run python eval/probe_eval.py unseeded $scratch examples/evaluation-cases.json
    uv run python eval/probe_eval.py seeded   $scratch examples/evaluation-cases.json

| Script | What it measures |
|---|---|
| retrieval_probe.py | score semantics, tokenizer recall A/B, trust/authority in ranking, hybrid gating (fake embedder), chunk-cut rate, a confidence prototype |
| intake_probe.py | field-level accuracy of the offline brief extraction on 24 sentences |
| engine_probe.py | geometry invariants over 243 configs, area fidelity, evidence-coverage blind spot, work-type scope guard |
| silent_probe.py | whether `2,400 sq m` corrupts an estimate without any finding |
| verify_probe.py | seeded bundled evaluation, workflow-level effect of intake failures, arithmetic on the real documents |
| probe_eval.py | the bundled evaluation cases with and without demo-pack seeding |

Caveats: the retrieval corpus, the intake sentences and their gold labels were written for these probes, so the numbers show mechanisms, not real-world accuracy. All prices in the repo's demo packs are synthetic. `real-test-cases.json` lists which facts came from a read-only fetch and still need checking against a downloaded PDF.
