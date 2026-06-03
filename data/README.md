# Data

This folder defines the data strategy for the wake-word model: one positive class, one negative speech pool, and several noise sources, all normalized into a fixed training shape.

## Idea

The augment pipeline is built around one idea: make the wake-word detector conservative on purpose.
It should fire on the target word, ignore ordinary speech, and stay stable under real background noise.
To do that, the pipeline normalizes every clip to 1 second, then creates a balanced synthetic dataset with controlled gain and SNR mixing.

The main mechanisms are:

- 1-second resampling at 16 kHz for every clip, so the model sees a fixed temporal window
- random gain, to simulate speaker loudness variance
- SNR-based mixing with different noise pools, to expose the model to multiple acoustic conditions
- split-aware sampling, so train, val, and test do not leak into each other
- held-out OOD noise, so the final test set contains noise the model did not train on

This keeps the dataset compact, reproducible, and closer to real deployment conditions.

## Proportions

The final dataset uses a fixed 25/50/25 class balance:

- `wakeup`: 25%
- `unknown`: 50%
- `noise`: 25%

That corresponds to 15,000 clips total:

- train: 9,600 clips
- val: 2,400 clips
- test: 3,000 clips

The ratio is not arbitrary. `unknown` is intentionally larger because ordinary speech is the most common negative input in a real device, and the model needs more negative examples to avoid false activations. `wakeup` and `noise` are kept at equal weight so the detector learns the positive trigger without overfitting to noise as a proxy for the keyword.

## Sources

- `raw/synthetic-wakeword-wake_up/`: positive wake-word clips from [TigreGotico/synthetic-wakeword-wake_up](https://huggingface.co/datasets/TigreGotico/synthetic-wakeword-wake_up)
- `raw/Google-Speech-Commands-V2/`: negative speech commands from [speech-commands-v2](https://www.kaggle.com/datasets/sylkaladin/speech-commands-v2)
- `raw/wham_noise/`: background noise pool from [WHAM! Noise Reduced Dataset](https://www.kaggle.com/datasets/alior101/wham-noise-reduced-dataset)
- `raw/ESC-50-master/`: background noise pool and OOD noise source from [karolpiczak/ESC-50](https://github.com/karolpiczak/ESC-50)
- `raw/my-noise/`: self-collected real-world noise, recorded directly from ESP32 and streamed back to the server in deployment-like conditions

## Prepare

Place the source folders under `raw/` with the names above.

For the public datasets, download from the upstream project pages and keep only the raw audio needed by the notebook.

For `my-noise/`, collect noise by streaming live audio from ESP32 to the server in realistic environments, then save the resulting WAV files under `raw/my-noise/`.

## Collection Notes

- `synthetic-wakeword-wake_up` provides the positive class and is only one part of the wake-word distribution, not the whole training set.
- `Google Speech Commands V2` is used as the main non-target speech source, then capped per word before splitting so one command does not dominate the negative pool.
- `WHAM!` and `ESC-50` are used as structured noise sources; `ESC-50` is also split by class so a subset of classes can be held out for OOD evaluation.
- `my-noise` represents deployment-like real noise captured from ESP32, which is important because synthetic or public noise alone usually misses the exact device and room characteristics.

## Notes

- `raw/` is input material, not the final deliverable.
- `temp/` and `dataset/` are generated artifacts and can be deleted safely.
- The notebook is the single place that encodes the augmentation logic and dataset balancing rules.
