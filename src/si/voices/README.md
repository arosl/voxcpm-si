# Bundled voices

Each voice is a reference recording (`NAME.wav`) plus the words spoken in it
(`NAME.txt`). The model has no named voices; the names are just file names.

Each recording was made once with `si --instruct DESC -o NAME.wav
TEXT` (mlx-community/VoxCPM2-8bit, 8 steps), then picked from several
candidates. The description is not used again: the same
description gives a different speaker every run, so the recording is what
keeps the voice stable. Running these again will give similar, not identical,
voices.

| Voice | Default for | Description (`--instruct`) |
|---|---|---|
| `no-ulf` | Norwegian | An older Norwegian man in his sixties with a calm, gentle, slightly low voice, speaking clear Eastern Norwegian at a slow pace |
| `en-tim` | English, and text whose language is unclear | An older British man in his sixties with a calm, gentle, slightly low voice, speaking clear Received Pronunciation English at a slow, unhurried pace |
| `es-juan` | Spanish | An older Mexican man in his sixties, a calm, gentle newsreader with a slightly low voice, speaking clear, neutral Mexican Spanish like a Mexican television news anchor, at a slow, unhurried pace |

The spoken text of each is in its `.txt` file.
