# Classifier explorer

Browse field/subfield predictions for papers and career-level authors
from the deployed model. Paper cards show model predictions beside LLM
labels when available. Author cards show OpenAlex AuthorIDs with at
least one paper in the 14.6M e5-frame, their career field/subfield
aggregates, representative papers, and LLM judge labels when available.

## Live

<https://calamosv.github.io/bitnet-classifier-explorer/>

## Run locally

```bash
cd tools/classifier_explorer
python3 -m http.server 8000
# open http://localhost:8000
```

## Deploy

```bash
./deploy.sh   # rsyncs this folder to the public site repo and pushes
```

## Files

- `index.html` / `style.css` / `app.js` — static web UI.
- `authors.html` / `authors.js` — author-level browser.
- `papers.json` — the sampled records (~11 MB, 7k papers).
- `authors.json` — sampled author records for the author browser.
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
After the paper job finishes:

```bash
scp sherlock:/scratch/users/alamos/oafc/data/explorer/papers.json papers.json
```

The author-level sample is built from
`/scratch/users/alamos/oafc/data/author_preds/author_eval_sample.parquet`
and optional LLM labels:

```bash
python3 build_author_explorer_sample.py \
  --sample /scratch/users/alamos/oafc/data/author_preds/author_eval_sample.parquet \
  --labels /scratch/users/alamos/oafc/data/author_preds/author_eval_labels.parquet
```
