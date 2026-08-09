# Synthetic Barge-in / Interruption Benchmark

## Question

Can a small, isolated and explainable classifier distinguish interruption attempts from non-interruption overlaps in a fully programmatic dataset, and can the ordering state recover safely under TP, FP, FN, and TN outcomes?

## Hypothesis

Simple acoustic/temporal features should separate some foreground interruption-like events from noise, while speech-like negatives will remain difficult without ASR/text semantics. The production text state machine should remain safe even when the prototype classifier is wrong.

## Dataset

- 1,600 fully synthetic programmatic overlap signals: 800 `INTERRUPTION`, 800 `NON_INTERRUPTION`.
- Exact group split: 1,120 train / 240 validation / 240 locked test (70% / 15% / 15%).
- Every class × locale × event-category cell is split by `template_group_id`; waveform variants of one semantic template never cross splits.
- Four locales are exactly balanced overall and within each split. All 20 positive/negative categories are balanced within each split.
- Onset covers 20/40/60/80%; configured SNR covers -10/-5/0/+5/+10 dB, with -120 dB representing the documented silence category.
- Signals are reconstructed from manifest parameters and checked by PCM SHA-256. They contain no recorded person, customer audio, intelligible TTS, or online ASR.
- Final dataset SHA-256: `0945846779a91ce413283ff05ec3c4c20bf0bbaf7e42778e339cb96590c9c97c`.

## Baseline

Model A is a fixed acoustic rule using energy, ZCR, centroid, flatness, duration, crest factor, and periodicity. It is transparent and has near-zero inference cost.

## Current system / prototype models

- Model B: L2-regularized logistic regression trained by deterministic full-batch gradient descent.
- Model C: 120 bounded gradient-boosted decision stumps with 85% row subsampling; seeds 42/43/44.
- Model selection used mean validation F1 only; ties prefer lower complexity. The locked test was opened after `model_selection.json` named `gradient_boosting_stumps`.
- Only 13 acoustic/temporal features derived from `mixed signal − known AI playback reference` enter a model. Label, semantic text, locale, category, template ID, onset, SNR, and waveform seed are excluded.

## Method

The final classifier prediction is a majority vote across the three predeclared seeds. Test precision, recall, F1, FPR, and FNR intervals use 10,000 example-level bootstrap resamples with seed 42. Inference is offline and is not wired into production.

A first pilot split was rejected before opening its test set because category balance was not preserved. Its dataset, features, validation predictions, models, and metadata remain under `experiments/results/barge_in/pilot_unbalanced_split`; no pilot sample was deleted. The corrected group-balanced dataset produced all results below.

## Model comparison

| Model | Validation mean F1 | Locked-test ensemble Precision | Recall | F1 | FPR |
|---|---:|---:|---:|---:|---:|
| rule_baseline | 0.805 | 0.745 | 0.900 | 0.815 | 0.308 |
| logistic_regression | 0.803 | 0.669 | 0.908 | 0.770 | 0.450 |
| gradient_boosting_stumps | 0.845 | 0.726 | 0.992 | 0.838 | 0.375 |


## Selected-model locked-test results

N = 240 (120 positive / 120 negative).

| Metric | Point estimate | Bootstrap 95% CI |
|---|---:|---:|
| Precision | 0.726 | 0.726 [0.655, 0.793] |
| Recall | 0.992 | 0.992 [0.973, 1.000] |
| F1 | 0.838 | 0.838 [0.789, 0.882] |
| Accuracy | 0.808 | not preregistered for CI |
| Specificity | 0.625 | not preregistered for CI |
| False interruption rate / FPR | 0.375 | 0.375 [0.289, 0.465] |
| Missed interruption rate / FNR | 0.008 | 0.008 [0.000, 0.027] |

Confusion matrix `[[TN, FP], [FN, TP]]`: `[[75, 45], [1, 119]]`. Test F1 by seed was 0.838, 0.838, 0.838; range = 0.000.

## Recovery experiment

The recovery definition was frozen before running (`2c42abeb5ca2b24d6184f555ce73455432dc6c554f51461050729400fdd67f5a`). It required no unintended mutation, the correct final draft, no confirmation bypass, no duplicate order, the correct safety state, and an advisory-only classifier.

| Condition | N | Recovery successes | Rate |
|---|---:|---:|---:|
| FN | 25 | 25 | 100.00% |
| FP | 25 | 25 | 100.00% |
| TN | 25 | 25 | 100.00% |
| TP | 25 | 25 | 100.00% |


Overall recovery success: **100/100 (100.00%)** in synthetic dialogue-state tests. A classifier prediction never confirmed or submitted an order.

## Confidence intervals

Classifier intervals resample locked-test examples. Recovery is reported as a finite deterministic test suite rather than dressed up as user-population inference; no production-success confidence claim is made.

## Error analysis

There were 45 false positives and 1 false negatives. Detailed examples and language/SNR/onset/cough/background-speech/acknowledgement breakdowns are in `experiments/reports/barge_in_error_analysis.md` and `experiments/results/barge_in/error_group_metrics.csv`.

The false-interruption rate of 37.50% is the principal product concern: frequent unnecessary interruptions would degrade playback and require clarification. This exceeded the preregistered 15% CV threshold.

## Limitations

- This is a synthetic programmatic overlapping-**signal** benchmark, not intelligible overlapping speech and not real users.
- The AI playback reference is perfectly aligned, unlike imperfect real echo cancellation.
- There is no real ASR, semantic speech recognition, streaming transport, endpointing, phone audio, or production barge-in integration.
- Generator-specific separability and balanced classes can overstate field performance.
- Recovery tests exercise the existing text state machine after a simulated classifier outcome; they do not demonstrate that live playback was actually stopped.

## Reproducibility

Run `generate_dataset.py`, `features.py`, `train.py`, `evaluate.py`, `recovery_eval.py`, and this analyzer. Raw manifests, feature CSV, validation/test predictions, all seed models, bootstrap JSON, error tables, recovery CSV, SHA-256 hashes, and PNGs are retained.

## CV eligibility

- Interruption classifier: **NOT_FOR_CV**. Although F1 is 0.838, FPR is 37.50% and fails the preregistered ceiling. It is not written into the CV.
- Recovery suite: **PRELIMINARY_CV_WITH_QUALIFIER** only as “100% success across 100 synthetic dialogue-state recovery cases”; it is not evidence of production barge-in and is not promoted in the CV because the upstream detector failed eligibility.
- Overall real-world barge-in: **NOT_FOR_CV / NOT_IMPLEMENTED**.
