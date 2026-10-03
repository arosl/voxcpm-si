# si

A mostly drop-in replacement for the Mac's `say` command, with the voice of
[VoxCPM2](https://github.com/OpenBMB/VoxCPM), OpenBMB's text-to-speech
model ([weights](https://huggingface.co/openbmb/VoxCPM2)), run locally on
Apple Silicon through [mlx-audio](https://github.com/Blaizzy/mlx-audio).
Like `say`, it speaks its arguments or stdin and takes `-v`, `-r` (words
per minute) and `-o`; unlike it, `-o` writes a `.wav`, and the voices are
its own. Speech is synthesized on your machine;
the network is only used to fetch the model from Hugging Face.

VoxCPM2 speaks 30 languages. This tool was built for Norwegian and English,
and also handles (Mexican) Spanish: it detects those three and spells out
their numbers. Each has a bundled default voice: `no-ulf` (an older
Norwegian man), `en-tim` (an older British man) and `es-juan` (a calm
Mexican newsreader). Other languages work too, but use the English voice
unless you pass `-v` (see [Voices](#voices)).

## Requirements

- A Mac with Apple Silicon.
- Python 3.12 or 3.13, and [uv](https://docs.astral.sh/uv/).
- Disk: about 3 GB for the model (`mlx-community/VoxCPM2-8bit`), which is
  downloaded into the Hugging Face cache (`~/.cache/huggingface/hub`) the
  first time the tool runs. Set `HF_HOME` to keep it elsewhere (the cache is
  then `$HF_HOME/hub`); the server reads it when it starts, so run
  `si --stop` after changing it.
- Network: only for that first download. After it, the tool works offline.
- Memory: about 3.3 GB resident while the model is loaded, with peaks
  around 5-7 GB while it speaks. The background server exits after 15
  minutes without requests, which frees it.

## Install

```sh
uv tool install git+https://github.com/arosl/voxcpm-si
```

or from a clone, to work on it:

```sh
git clone https://github.com/arosl/voxcpm-si
cd voxcpm-si
uv tool install --editable .
```

Either puts `si` on your PATH (the repository is `voxcpm-si`; the tool
is `si`). To update, run the first command again with `--reinstall`; in a
clone with `--editable`, changes take effect at once (the server's after
`si --stop`). The three bundled voices are installed with the code; the
model is not.

### First run: download the model

The model is downloaded on first use. Either just run it once and wait:

```console
$ si "Hello, this is a test."
… starting VoxCPM2
… downloading mlx-community/VoxCPM2-8bit (about 3 GB), only the first time; progress: tail -f ~/.cache/si/server.log
… still downloading (1 min)
… still downloading (2 min)
… downloaded; loading the model
```

or download it in the background and check on it:

```sh
si --warm     # returns at once
si --status   # "downloading: ...", then "loading: ...", then "running: ..."
```

The download is 3.2 GB (1.5-4 minutes in testing); `tail -f
~/.cache/si/server.log` shows its progress in bytes. An interrupted
download resumes on the next run. Once `--status` says `running`, calls
start speaking in under a second.

To abort the download, run `si --stop`. A call waiting for the
model then fails rather than start the download again:

```console
si: the server exited while downloading the model
```

The next call starts the server again, and the download resumes.

The model is pinned to the revision the bundled voices were made and tuned
with (`mlx-community/VoxCPM2-8bit` at commit `d527258`), so a new upload to
Hugging Face can't change how they sound. To use another revision, set
`SI_REVISION` (a commit, branch or tag; `main` is the latest). A
different `SI_MODEL` is not pinned: it gets that model's latest
revision unless you also set `SI_REVISION`. Once the pinned
revision is in the cache, it's loaded without any network access.

If the download fails, the call fails at once with a short message, and
the log has the details:

```console
$ si "Hello."
… starting VoxCPM2
si: couldn't download the model mlx-community/VoxCPM2-8bit (no network, or Hugging Face can't be reached); see ~/.cache/si/server.log
```

Other reasons are `HF_HUB_OFFLINE is set`, `no such model on Hugging Face`
and `no revision ...`. Offline, it fails within a second when the host
can't be resolved or refuses the connection, or after about 75 seconds when
the connection times out. Run it again once you're online.

In a Nix shell (or anywhere `PYTHONPATH` points at another Python's
packages), run uv as `env -u PYTHONPATH uv ...`. The tool itself already
drops `PYTHONPATH` when it runs.

## Usage

```sh
si "Hei, dette er en test."            # text as arguments
echo "Hello from standard input." | si  # or on stdin
si -o out.wav "Write this to a file."   # write a WAV instead of playing
si -r 220 "A bit faster."               # words per minute, same pitch
si --speed 0.9 "A bit slower."          # or a speed factor (0.25-4)
si -v no-ulf "Hei igjen."           # a bundled voice by name
si -v ~/voices/me.wav "Hello."          # or any .wav to clone
si --voices                             # list the voices (yours too)
```

The command returns when playback has finished. `-o` writes 16-bit mono
48 kHz WAV.

`-r` is approximate: speech is stretched by the ratio of the rate to the
voice's own pace (bundled voices: measured, about 160-185 words per minute;
yours: estimated from the clip and its transcript), within half to twice
that pace. `--speed` multiplies the result.

Design a new voice from a description, save it, and use it as a reference:

```sh
si --instruct "A calm middle-aged woman, warm and clear" \
    -o anna.wav "Hello, this is my new voice. I hope it sounds good to you."
si -v anna.wav "This uses the voice designed above."
```

With `--instruct` the text is spoken in one piece (each generation designs
a new speaker), and `-o` also writes the text to `anna.txt` next to the
WAV, as its transcript. Listen to the result and check that it says exactly
that text. Without `-o`, a designed voice is just played once.

The server:

```sh
si --warm              # load the model now, without speaking
si --warm --hold 1234  # ... and keep it loaded while PID 1234 runs
si --status            # "running: <model>", "loading: ...", "downloading: ..." or "not running"
si --stop              # stop the server
```

`--warm` returns at once and loads the model in the background (the first
time, it also downloads it). `--hold PID` implies `--warm`. Use `--status`
to see when it's ready; the server log is `~/.cache/si/server.log`.

## How it works

- **A warm background server.** VoxCPM2 is a 2B-parameter model and takes a
  while to load, so the first call starts a server in its own session that
  keeps the model in memory. It listens on a Unix socket in
  `~/.cache/si` (with its log in `server.log` there). Later calls
  connect to it and only synthesize. There is only ever one server per
  directory: it holds `server.lock` for its whole life, and a call that
  finds the lock held waits for that server rather than start another. It
  listens before the model has loaded, so calls queue meanwhile; calls
  made while it speaks queue too and are spoken one after the other.
  `--status`, `--warm` and `--stop` are answered at once, even while it
  loads or speaks. A bad request gets an error and doesn't affect the
  others. The server exits after
  `SI_IDLE` seconds (default 900) without requests and without a
  live `--hold` process; with `--hold`, the idle time starts when that
  process exits. A call that reaches the server just as it exits (idle,
  or `--stop`), so that it gets no answer and no server is left, starts
  a new one and asks again, once; but not if that server was still
  downloading or loading the model (see [First
  run](#first-run-download-the-model)). If the model fails to load, every
  waiting call gets the reason, and the server exits.
- **Streaming.** The text is split into sentence-sized chunks of roughly
  60-200 characters (short sentences are joined, long ones are cut at a
  comma or similar). The server synthesizes one chunk at a time and sends
  the audio every few 0.16 s patches as it is generated. The client starts
  playing once 0.4 s is buffered, so speech starts well before the first
  sentence is done and continues without gaps between sentences, as long as
  synthesis keeps up with playback.
- **The voice follows the language.** Without `-v`, the text's language is
  guessed from common words and letters (Norwegian, English or Spanish:
  æøå; ñ, ¿, ¡ and á í ó ú outside names) and the default voice for that
  language is used: `no-ulf` for Norwegian, `en-tim` for English,
  `es-juan` for Spanish. Text in any other language, or too short to
  tell, gets the English default (a fixed voice, so it doesn't change
  between calls).
- **Text cleanup.** A URL is read as its host (`https://github.com/foo/bar`
  becomes "github.com"), and markdown markup is dropped (headings and list
  items become sentences). In Norwegian, English and Spanish text, numbers
  are spelled out: dates, times, phone numbers, prices, percentages, ranges,
  ordinals, years, versions, and IDs (`#4521`, "order 48213"), which are
  read digit by digit. Text in other languages is left as it is.
- **Spanish numbers follow Mexican usage.** `$1,250.50` is pesos ("mil
  doscientos cincuenta pesos con cincuenta centavos"; also `MXN`, `USD`,
  `dólares`, `€`); `02/10/2026` and `2/10/2026` are day/month ("dos de
  octubre de dos mil veintiséis"; Norwegian and English leave slash dates
  alone), as are `2026-10-02` and "2 de octubre"; years are plain numbers;
  `14:30` is "catorce treinta" and `2:30 pm` "dos treinta de la tarde";
  `3.5` is "tres punto cinco"; `1er`, `2º`, `3ra` are ordinals; `55 1234
  5678` is read in pairs, "cincuenta y cinco, doce treinta y cuatro,
  cincuenta y seis setenta y ocho"; "un día", "una hora".

## Use from scripts

The tool is meant to be called once per paragraph from another program.

- **Exit codes.** 0 when playback is done (or the file is written). On
  Ctrl-C it stops the sound and kills itself with SIGINT, so a parent sees
  it die by signal (`returncode == -2` in Python's `subprocess`, 130 in a
  shell). On SIGTERM it stops the sound at once and dies by SIGTERM (-15,
  or 143 in a shell). Any failure (no such voice, bad rate, server error,
  timeout, no audio device) prints a short message to stderr and exits
  nonzero.
- **Stopping a reading.** To stop a reading running in the background,
  start it in its own process group and send SIGTERM to the group (in
  Python: `start_new_session=True`, then `os.killpg(proc.pid,
  signal.SIGTERM)`). The server is in a session of its own, so it survives;
  it drops the abandoned request and serves the next one.
- **Warming up.** Run `si --warm --hold $$` (or your program's PID)
  when your program starts (it returns at once), so the model is loaded by the
  time it first speaks and stays loaded while your program runs.
- **Timeouts.** It never waits forever:
  - `SI_TIMEOUT` (120 s): how long the client waits on the server
    for the next piece of audio.
  - Waiting for the server: while it loads the model, or while it speaks
    for earlier calls, up to 30 minutes (which covers the first model
    download; while the model downloads it says so on stderr, once a
    minute); it fails at once if the server dies or the download fails, and after
    `SI_TIMEOUT` if the server makes no progress.
  - `--status`, `--warm` and `--stop`: 10 s.
  - Playback: if playback hasn't finished 5 s after the audio should have
    ended (a stuck audio device), it exits with an error.

Empty input exits 0 without starting the server. A call prints nothing
on stderr unless it fails, or it starts the server or waits while the
server downloads the model (lines starting with `…`).

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `SI_VOICE` | (unset) | The default for `-v`, for text in any language. |
| `SI_VOICE_NO` | `no-ulf` | The voice for Norwegian text when no `-v` or `SI_VOICE` is given. |
| `SI_VOICE_EN` | `en-tim` | The voice for English text (and text in an unknown language), likewise. |
| `SI_VOICE_ES` | `es-juan` | The voice for Spanish text, likewise. |
| `SI_RATE` | (unset) | The default for `-r`, in words per minute. Unset, each voice speaks at its own pace. |
| `SI_SPEED` | `1.0` | The default for `--speed`. |
| `SI_TIMEOUT` | `120` | Seconds the client waits on the server for audio. |
| `SI_CACHE` | `~/.cache/si` | Where the socket, lock and log live. A different directory runs a separate server. The socket path must stay under 104 bytes. |
| `SI_DEBUG` | (unset) | If set, print the time to first audio and the number of buffer underruns after playback. |
| `SI_MODEL` | `mlx-community/VoxCPM2-8bit` | The model (a Hugging Face repo ID, or a local directory). Read when the server starts. |
| `SI_REVISION` | `d527258…` for the default model, else the latest | The model's revision: a commit, branch or tag (see [First run](#first-run-download-the-model)). Read when the server starts. |
| `HF_HOME` | `~/.cache/huggingface` | Where Hugging Face keeps the model (in `$HF_HOME/hub`). Its other variables, such as `HF_HUB_OFFLINE` and `HF_TOKEN`, work too. Read when the server starts. |
| `SI_STEPS` | `8` | Diffusion steps per 0.16 s of audio. Fewer is faster, more is the model's default of 10. Read when the server starts. |
| `SI_IDLE` | `900` | Seconds without requests before the server exits. Read when the server starts. |

The server inherits the environment of the call that started it, so to
change the ones read when it starts, run `si --stop` first. Voice values are
names or paths, as for `-v`.

## Voices

A voice is a short WAV of someone speaking, used as the reference to clone.
Without one, VoxCPM2 picks a random speaker on every call, so the tool
always uses a reference unless you design a voice with `--instruct`.

`si --voices` lists the voices you can use by name. There are three
ways to use another voice:

- **A listed voice:** `si -v no-ulf "..."` reads any text in
  that voice.
- **Any recording:** `si -v ~/clips/me.wav "..."`. A clean clip of
  a few to about ten seconds of one speaker works; the bundled ones are 7-8 s.
- **A new voice from a description:** `--instruct` invents one, but it's a
  different speaker every call, so save one you like and use the file:

      si --instruct "A calm older woman with a warm voice" \
          -o ~/.config/si/voices/anna.wav "Hello, I'm Anna. Nice to meet you."
      si -v anna "Now speaking in Anna's voice."

Your own voices live in `~/.config/si/voices/` (`$XDG_CONFIG_HOME`
is respected) as `NAME.wav` plus an optional `NAME.txt`; `-v NAME` finds
them, and a name there wins over a bundled one. To make one the default for
a language, set `SI_VOICE_EN=NAME` (or `_NO`, `_ES`); `SI_VOICE`
sets it for all text.

Optionally put a transcript next to it: `NAME.txt`, with exactly the words
spoken in the clip. With a transcript, the clip is also used as a prompt for
the model to continue, which keeps the speaker and the pronunciation more
consistent than the reference alone. The transcript is only used when the
text is in the transcript's language (or the language can't be told);
English text with a Norwegian transcript, say, uses the clip as a reference
only, since continuing a Norwegian prompt would give it an accent. Without a
transcript, the clip is always used as a reference only. `--instruct -o`
writes this transcript for you.

## Speed

Measured on an M4 Pro with the 8-bit model and the default voice, with
nothing else using the GPU; expect slower numbers on other machines or when
the GPU is busy.

- With the server warm, the first audio plays after about 0.7-0.8 s. The
  first request after the server starts takes about 1.5 s.
- Synthesis runs at about 0.86x real time with the default 8 steps
  (0.83-0.92 over several paragraphs), so playback normally doesn't run
  dry. At 10 steps it's about real time. When the GPU is shared with
  another heavy process, synthesis can fall behind; the player then pauses
  a few times per paragraph rather than stutter.
- At `--speed 1.3` (or an `-r` about 30% above the voice's pace) the audio
  plays faster than it is made, so expect a pause or two per paragraph.

## License

si is released under the [Apache-2.0](LICENSE) license.
[VoxCPM2](https://github.com/OpenBMB/VoxCPM) is released under the
Apache-2.0 license by OpenBMB. The bundled voices were generated with
VoxCPM2 from text descriptions; they are not recordings of real people.
