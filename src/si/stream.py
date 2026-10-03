"""Streaming synthesis: VoxCPM2's generation loop, decoding as it goes.

mlx-audio's `Model.generate` makes all the patches (0.16 s of audio each)
and then decodes them in one piece. `stream` runs the same loop (reusing the
model's parts) but decodes and yields the new audio every few patches.

The AudioVAE decoder is causal (causal convolutions, transposed
convolutions trimmed on the right, no noise), so a sample depends only on
the latents up to it, and on 5 patches back at most (its receptive field is
~19 latent frames, 4 per patch). So the new patches are decoded with CONTEXT
patches before them, and only their audio is kept. Measured against a
one-shot decode of the same patches: 4 patches of context differ by at most
2e-5 (below 16-bit resolution), 5 or more by 0, 3 by 4e-4; the seams have
no clicks. Only the last 8 samples a decode makes need the next patch, so
they are dropped (except at the very end).
"""

import os

import mlx.core as mx
import numpy as np
from mlx import nn

CONTEXT = 4  # patches of left context per decode
# Patches per piece (the last size repeats). Smaller pieces arrive sooner,
# but each decode costs ~12 ms per patch, context included. A player that
# starts at 0.4 s buffered starts on the first piece and (modelled with the
# measured costs) doesn't run dry at RTF <= 0.8, the second piece being
# smaller to come before the first has played.
SIZES = (4, 3, 4)
_encoded = {}  # (model, path, mtime, padding) -> the .wav's VAE latents


def encode(model, path, padding_mode):
    """A reference .wav's VAE encoding, cached: it costs ~0.4 s, and each
    sentence needs it (twice with a transcript)."""
    key = (id(model), path, os.path.getmtime(path), padding_mode)
    if key not in _encoded:
        if len(_encoded) >= 16:
            _encoded.clear()
        _encoded[key] = model._encode_wav(path, padding_mode=padding_mode)
    return _encoded[key]


def patch_cap(text):
    """A cap on the audio patches for text, so the model can't babble on.
    A patch is 0.16 s of audio (7680 samples at 48 kHz). Measured speech
    runs 13-27 chars/s (0.25-0.5 patches per char, slowest with numbers,
    which are read out as words); a single word takes ~8 patches. The cap
    (1 patch per char, 2 per digit, +25) is 2-4x normal speech."""
    return 25 + len(text) + 2 * sum(c.isdigit() for c in text)


def prefix(model, text, ref_audio=None, prompt_text=None, prompt_audio=None):
    """The model's input sequence, as in Model.generate: [ref audio] text
    [prompt audio] (the audio: .wav paths). Returns tokens, feats, text
    mask and audio mask."""
    P, D = model.patch_size, model.audio_vae.latent_dim
    prompt = prompt_audio is not None and prompt_text is not None
    ids = model._tokenize(prompt_text + text if prompt else text)
    n = len(ids) + 1
    parts = [(mx.array(ids + [model.audio_start_token], dtype=mx.int32),
              mx.zeros((n, P, D)), mx.ones(n), mx.zeros(n))]
    if ref_audio is not None:
        parts.insert(0, model._make_ref_prefix(
            encode(model, ref_audio, "right")))
    if prompt:
        feat = encode(model, prompt_audio, "left")
        m = feat.shape[0]
        parts.append((mx.zeros(m, dtype=mx.int32), feat, mx.zeros(m),
                      mx.ones(m)))
    return [mx.concatenate(x, axis=0)[None] for x in zip(*parts)]


def decode(model, seq, start, end, last=False):
    """The audio of patches start..end of seq, decoded with left context.
    The decoder makes 8 samples more than 1920 per latent frame; they need
    the next patch, so only the last piece keeps them."""
    lo = max(0, start - CONTEXT)
    z = mx.concatenate(seq[lo:end], axis=1).reshape(1, -1, model.feat_dim)
    audio = model.audio_vae.decode(z).flatten()
    n = model.patch_size * model.audio_vae.decode_chunk_size
    return np.array(audio[(start - lo) * n:None if last else (end - lo) * n],
                    dtype=np.float32)


def stream(model, text, min_tokens=2, ref_audio=None, prompt_text=None,
           prompt_audio=None, instruct=None, inference_timesteps=10,
           cfg_value=2.0):
    """Yield the audio of text (float32 numpy at model.sample_rate) in
    pieces of SIZES[0], SIZES[1], ... patches (the last size repeats), at
    most patch_cap(text) patches (the cap is for the text, before the
    instruct)."""
    max_tokens = patch_cap(text)
    if instruct:
        text = f"({instruct}){text}"
    tokens, feats, tmask, amask = prefix(model, text, ref_audio, prompt_text,
                                         prompt_audio)
    scale = (model.args.lm_config.scale_emb if model.args.lm_config.use_mup
             else 1.0)
    feat_embed = model.enc_to_lm_proj(model.feat_encoder(feats))
    embed = (tmask[..., None] * model.base_lm.embed_tokens(tokens) * scale
             + amask[..., None] * feat_embed)
    out, lm_cache = model.base_lm(embed)
    out = (model.fsq_layer(out) * amask[..., None]
           + out * tmask[..., None])
    lm_hidden = out[:, -1, :]
    res, res_cache = model.residual_lm(model.fusion_concat_proj(
        mx.concatenate([out, amask[..., None] * feat_embed], axis=-1)))
    res_hidden = res[:, -1, :]
    cond = feats[:, -1]
    # After prompt audio, its last patches are the decoder's left context
    # (Model.generate decodes 3 of them and trims their audio off).
    seq = []
    if amask[0, -1].item() == 1:
        seq = [feats[:, i][:, None] for i in range(
            max(0, feats.shape[1] - CONTEXT), feats.shape[1])]
    done, k = len(seq), 0
    for i in range(max_tokens):
        h = mx.concatenate([model.lm_to_dit_proj(lm_hidden),
                            model.res_to_dit_proj(res_hidden)], axis=-1)
        pred = model.feat_decoder.sample(
            mu=h, n_timesteps=inference_timesteps, patch_size=model.patch_size,
            cond=cond.transpose(0, 2, 1), cfg_value=cfg_value
        ).transpose(0, 2, 1)
        seq.append(pred[:, None])
        stop = mx.argmax(model.stop_head(nn.silu(model.stop_proj(
            lm_hidden))), axis=-1).item() == 1
        if stop and i > min_tokens:
            break
        if len(seq) - done >= SIZES[min(k, len(SIZES) - 1)]:
            yield decode(model, seq, done, len(seq))
            done, k = len(seq), k + 1
        curr = model.enc_to_lm_proj(model.feat_encoder(pred[:, None]))
        out, lm_cache = model.base_lm(inputs_embeds=curr, cache=lm_cache)
        lm_hidden = model.fsq_layer(out[:, -1, :])
        res, res_cache = model.residual_lm(
            inputs_embeds=model.fusion_concat_proj(
                mx.concatenate([lm_hidden[:, None, :], curr], axis=-1)),
            cache=res_cache)
        res_hidden = res[:, -1, :]
        cond = pred
    yield decode(model, seq, done, len(seq), last=True)
