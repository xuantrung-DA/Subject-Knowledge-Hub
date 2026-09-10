# Data and attribution

The PDFs and runbooks under `fixtures/project/` and `fixtures/portfolio/` are original synthetic testing material. The portfolio corpus is marked CC0-1.0 in its manifest. The answers are artificial study/runbook facts and do not describe real operational procedures.

QASPER originates from the Allen Institute for AI: [official dataset card](https://huggingface.co/datasets/allenai/qasper), licensed CC-BY-4.0. See the paper *A Dataset of Information-Seeking Questions and Answers Anchored in Research Papers* (Dasigi et al., 2021) linked by that card. The adapter selects a fixed subset and maps paragraph evidence; it does not claim full official benchmark performance.

`fixtures/qasper-selection.json` records the dataset source, source hash, selected IDs, selection rules and attribution. Published QASPER evaluation artifacts contain derived paragraph excerpts/evidence; the full downloaded dataset is excluded from Git under `artifacts/qasper/`.

Benchmark artifacts contain synthetic test questions, provider outputs and measured results. They must retain their stated scope and limitations when reused. Dataset licenses do not grant a separate blanket license to the application source or its dependencies; dependency licenses remain with their respective authors.
