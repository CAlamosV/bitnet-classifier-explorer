# Classifier explorer

Browse field/subfield predictions for a sample of $\sim 7{,}000$ papers
from the deployed model. About $2{,}300$ of the papers are also in the
LLM-labelled training set — for those we display the LLM's labels
alongside the model's predictions so you can spot agreement and
disagreement at a glance.

## Run

```bash
cd tools/classifier_explorer
python3 -m http.server 8000
# open http://localhost:8000
```

## Files

- `index.html` / `style.css` / `app.js` — static web UI.
- `papers.json` — the sampled records (~11 MB, 7k papers).
- `taxonomy.json` — code → human-readable name for the 30 fields and
  304 subfields.

## Sample composition

- **Training-set papers** ($n \approx 2{,}260$): a stratified sample
  (≤ 134 per SciNET field) of the LLM-labelled seed that overlaps the
  deployed $14.6$M e5 frame.
- **Corpus papers** ($n \approx 4{,}870$): a reservoir-sampled batch
  from the rest of the deployed corpus, stratified by predicted field
  and confidence bin so all four confidence regimes
  ($p_1 < 0.3$, $0.3$–$0.6$, $0.6$–$0.85$, $\ge 0.85$) are represented.

## Rebuild

The server-side build script and SLURM wrapper live on Sherlock at
`/scratch/users/alamos/oafc/code/build_explorer_sample.py` and
`/tmp/explorer.slurm`. Re-running takes ~1 minute on `hns,normal`.
After the job finishes:

```bash
scp sherlock:/scratch/users/alamos/oafc/data/explorer/papers.json papers.json
```
