# Local Voice Models

Model files are local development artifacts and must not be committed to Git.

Expected layout for local ASR:

```text
models/asr/vosk-cn/
  conf/
  am/
  graph/
  ivector/    # if included by the model
  README
```

Recommended Vosk Chinese model for development:

- `vosk-model-small-cn-0.22`
- Download page: `https://alphacephei.com/vosk/models`
- Extract the model root directory to `models/asr/vosk-cn`

An empty `models/asr/vosk-cn` directory is not enough. `modelLooksValid` only becomes true when the directory looks like an extracted Vosk model.

Expected layout for optional local TTS models:

```text
models/tts/
```

Only `.gitkeep` files are tracked to preserve the directory structure.
