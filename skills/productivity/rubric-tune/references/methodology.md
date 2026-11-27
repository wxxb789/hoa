# Rubric hillclimbing methodology

## Separate the two loops

The inner loop changes rubric instructions or category boundaries against fixed,
human-labeled training data. Each candidate has one hypothesis, one comparison
to the current best, and one ledger record. The outer loop uses the rubrics to
choose what a human should label next. Feeding model guesses back into the inner
loop would reward agreement with its existing biases: an omitted category could
disappear from both the labels and the measured errors. Disagreement and novelty
scores decide **what to review**, never **what is true**.

A blind holdout checks generalization to labeled items the editor never saw.
Showing examples, IDs, or per-item errors to the editor turns those items into
training evidence. Even aggregate metrics become a feedback channel when used to
choose among repeated finalists. Compare a frozen finalist against the original
once. Use a fresh holdout before evaluating another finalist after a failed gate.
Stratification keeps repeated classes on both sides; a class with just one item
stays in training, so its generalization has not been tested.

## Choose the metric before editing

Use $F_\beta = (1+\beta^2)PR/(\beta^2P+R)$, where $P$ is precision and $R$ is
recall. The default $F_{0.5}$ emphasizes precision when false positives consume
review capacity. Choose $F_2$ when missing positives is more expensive. Neither
score replaces red-line anchors: evaluate their zero-error gate separately so
common cases cannot hide a critical regression.

For boolean labels, the positive score is `0.6 × normalized score + 0.4 ×
P(non-routine)`. Normalize the score by `max(1, number_of_levels - 1)` and use the
fixed threshold (default `0.5`, inclusive). `worst_case_gap` is the minimum
positive score minus the maximum negative score, or `null` without both classes.
For string labels, compare the top mechanism choice to the expected label;
precision and recall are micro-averaged (a wrong choice adds both a false
positive and a false negative). No scalar margin is defined for these labels.
A refusal is an abstention and never a correct result: count it as a false
negative on a binary positive or as a false positive on a binary negative, with
the pessimistic score for the margin. For a string label, it misses the
expected class without predicting another one. Any refusal blocks an anchor
pass. Transport and malformed-response errors abort rather than becoming labels.

The rubric may be standalone or selected from a `stages` object. A mechanism
choice head (`mech_question`), ordered score head (`score_question`), routine
labels, and a distinct escape-hatch `novel_label` are required. Optional
`anomaly_probe` predicates enable out-of-distribution sampling. Embedded
`anchors` are used only with `--check-anchors`; prefer a separate locked anchor
JSONL or JSON file supplied by `--anchors` so the edits cannot change the gate.

## Review overlaps before merging

`confusion_pairs` counts pairs of top non-routine, non-escape-hatch labels on
misclassified or near-tied training items. In blind output it contains only
rubric label names and counts. In `sample` it counts high-overlap predictions
across both rubrics, once per item per pair. The ranking weights the entropy of
the top-two split by the probability of the runner-up, so weak tails do not
compete with substantial near ties. High counts suggest two buckets worth
reviewing, not permission to merge. Check the training excerpts and ask a human
whether the labels support different downstream actions. If the label space
changes, predefine a shared mapping or obtain comparable human labels before
starting a new scoring run; do not silently relabel a locked split.

The `ood_pool` ranks the maximum across the two rubrics of
`P(anomaly_probe) × P(novel_label)`, when the probe exists. It finds anomalies
that landed in the escape hatch rather than proposing a new class automatically.
With chat completions, boolean and choice answers are hard (zero or one), so
agreement, disagreement, and the escape-hatch signal are still usable, but
soft overlap is not observable. The CLI orders and scores results deterministically
for a given set of answers; the remote model itself may vary. Record the backend
and model with the run and do not switch either mid-comparison.

Native `/v1/decisions` backends also vary in output resolution: some emit smooth
continuous probabilities while others quantize to `0.01` steps with polarized
tails. On quantized backends, `F_beta` over small training sets moves in discrete
steps; prioritize tightening `choice` category boundaries and explicit negative
exclusions over minor wording tweaks, and group adjacent spans or same-incident
memories before splitting so near-duplicate IDs cannot leak across train and
holdout.
