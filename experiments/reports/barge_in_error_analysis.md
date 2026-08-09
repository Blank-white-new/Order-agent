# Synthetic Barge-in Error Analysis

Selected model: `gradient_boosting_stumps` (three-seed majority vote). Locked test N=240.

> All inputs are programmatic harmonic/noise overlaps. They contain no recorded voice and no intelligible TTS. These errors do not estimate real-user barge-in performance.

## Most common false positives

background_synthetic_speech: 12, unrelated_speech: 12, low_volume_background_speech: 12, music_tone_mixture: 9

## Most common false negatives

restart_request: 1

### False-positive examples

| Example | Locale | Category | SNR dB | Onset | Probability | Synthetic semantic template |
|---|---|---|---:|---:|---:|---|
| BGX-0857 | zh-CN | background_synthetic_speech | 10 | 20% | 0.6869 | non-instructional speech-like tone pattern [safety-notice] |
| BGX-0858 | zh-CN | background_synthetic_speech | -5 | 40% | 0.6869 | non-instructional speech-like tone pattern [safety-notice] |
| BGX-0859 | zh-CN | background_synthetic_speech | -10 | 40% | 0.6869 | non-instructional speech-like tone pattern [confirmation-readback] |
| BGX-0860 | zh-CN | background_synthetic_speech | 0 | 60% | 0.6869 | non-instructional speech-like tone pattern [confirmation-readback] |
| BGX-0880 | zh-CN | unrelated_speech | 0 | 20% | 0.6869 | unrelated speech-like tone pattern [confirmation-readback] |
| BGX-0960 | zh-CN | music_tone_mixture | 0 | 20% | 0.6869 | harmonic tone mixture [confirmation-readback] |
| BGX-0999 | zh-CN | low_volume_background_speech | -10 | 80% | 0.6869 | low-volume speech-like tone pattern [confirmation-readback] |
| BGX-1000 | zh-CN | low_volume_background_speech | -5 | 20% | 0.6869 | low-volume speech-like tone pattern [confirmation-readback] |
| BGX-1059 | yue-Hant-HK | background_synthetic_speech | -10 | 60% | 0.6869 | non-instructional speech-like tone pattern [confirmation-readback] |
| BGX-1060 | yue-Hant-HK | background_synthetic_speech | 0 | 80% | 0.6869 | non-instructional speech-like tone pattern [confirmation-readback] |
| BGX-1077 | yue-Hant-HK | unrelated_speech | 10 | 80% | 0.6869 | unrelated speech-like tone pattern [safety-notice] |
| BGX-1078 | yue-Hant-HK | unrelated_speech | -5 | 20% | 0.6869 | unrelated speech-like tone pattern [safety-notice] |
| BGX-1079 | yue-Hant-HK | unrelated_speech | -10 | 20% | 0.6869 | unrelated speech-like tone pattern [confirmation-readback] |
| BGX-1080 | yue-Hant-HK | unrelated_speech | 0 | 40% | 0.6869 | unrelated speech-like tone pattern [confirmation-readback] |
| BGX-1158 | yue-Hant-HK | music_tone_mixture | -5 | 20% | 0.6869 | harmonic tone mixture [safety-notice] |
| BGX-1159 | yue-Hant-HK | music_tone_mixture | -10 | 20% | 0.6869 | harmonic tone mixture [confirmation-readback] |
| BGX-1160 | yue-Hant-HK | music_tone_mixture | 0 | 40% | 0.6869 | harmonic tone mixture [confirmation-readback] |
| BGX-1197 | yue-Hant-HK | low_volume_background_speech | -5 | 80% | 0.6869 | low-volume speech-like tone pattern [safety-notice] |
| BGX-1200 | yue-Hant-HK | low_volume_background_speech | -5 | 40% | 0.6869 | low-volume speech-like tone pattern [confirmation-readback] |
| BGX-1257 | en-HK | background_synthetic_speech | 10 | 60% | 0.6869 | non-instructional speech-like tone pattern [safety-notice] |
| BGX-1258 | en-HK | background_synthetic_speech | -5 | 80% | 0.6869 | non-instructional speech-like tone pattern [safety-notice] |
| BGX-1259 | en-HK | background_synthetic_speech | -10 | 80% | 0.6869 | non-instructional speech-like tone pattern [confirmation-readback] |
| BGX-1260 | en-HK | background_synthetic_speech | 0 | 20% | 0.6869 | non-instructional speech-like tone pattern [confirmation-readback] |
| BGX-1279 | en-HK | unrelated_speech | -10 | 40% | 0.6869 | unrelated speech-like tone pattern [confirmation-readback] |
| BGX-1280 | en-HK | unrelated_speech | 0 | 60% | 0.6869 | unrelated speech-like tone pattern [confirmation-readback] |
| BGX-1359 | en-HK | music_tone_mixture | -10 | 40% | 0.6869 | harmonic tone mixture [confirmation-readback] |
| BGX-1360 | en-HK | music_tone_mixture | 0 | 60% | 0.6869 | harmonic tone mixture [confirmation-readback] |
| BGX-1400 | en-HK | low_volume_background_speech | -5 | 60% | 0.6869 | low-volume speech-like tone pattern [confirmation-readback] |
| BGX-1459 | mixed | background_synthetic_speech | -10 | 20% | 0.6869 | non-instructional speech-like tone pattern [confirmation-readback] |
| BGX-1460 | mixed | background_synthetic_speech | 0 | 40% | 0.6869 | non-instructional speech-like tone pattern [confirmation-readback] |

### False-negative examples

| Example | Locale | Category | SNR dB | Onset | Probability | Synthetic semantic template |
|---|---|---|---:|---:|---:|---|
| BGX-0599 | en-HK | restart_request | 10 | 40% | 0.4891 | change the phone number [confirmation-readback] |

## Stratified performance

The machine-readable table `experiments/results/barge_in/error_group_metrics.csv` reports language, configured SNR, onset, and every event category. It explicitly includes cough-like noise, background synthetic speech, acknowledgements, silence, breathing-like noise, cutlery transients, and music-like mixtures.

## Interpretation

Speech-like negative overlays are the hard cases because the prototype deliberately has no ASR/text semantics. Performance is therefore bounded by acoustic separability in this generator. The dataset is not evidence of real speech recognition, real barge-in, or caller behavior.
