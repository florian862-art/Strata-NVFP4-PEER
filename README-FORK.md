# Fork notes: squeezing two RTX 5070 Ti (NVFP4 peer-prefill)

What this fork changes, why, and every number we measured. The code lives on
branch [`f-nvfp4-peer`](../../tree/f-nvfp4-peer) → upstream
[Niko1221/Strata#2995](https://github.com/Niko1221/Strata/pull/2995); the deep
design notes are in `src/prefill/README-nvfp4-peer.md` on that branch.

## Goal

Run Qwen3.8-Flash-Next (NVFP4-GPTQ, 24,576 experts) as fast as possible on
**two consumer PCIe GPUs without NVLink**.

## Hardware

| | |
|---|---|
| GPUs | 2x NVIDIA GeForce RTX 5070 Ti, 16,303 MiB each (PCIe 02:00.0 / 04:00.0) |
| CPU / RAM | Intel Core Ultra 7 270K Plus / 91 GB |
| OS / driver | Ubuntu, NVIDIA 595.99.02 — open kernel modules rebuilt with P2P support, MOK-signed (Secure Boot stays on), `iommu=pt` |
| GPU↔GPU link (BAR1 P2P) | measured **5.5 GB/s** |
| GPU↔RAM (pinned host route) | measured **14.3 GB/s** |

## The config change: layer split → peer expert cache

Stock default on two GPUs is `--layer-split auto` (GPU1 runs layers 24–47).
We switched to `--peer-device 1`: GPU1 instead holds the **expert cache**
(5,131 experts, 13.2 GiB resident) and the primary streams past it.

| | layer split (stock) | peer expert cache |
|---|---:|---:|
| **Decode** (generation) | 76 tok/s | **96–97 tok/s (+27 %)** |
| **Prefill** (cold prompt) | **~4,096 tok/s** (chunked, n=138) | 2,385 tok/s (−42 %) |

The trade: generation wins because the expert stream hits GPU1's local cache
instead of PCIe; prompt processing loses ground because it effectively runs on
GPU0's streamed experts.

## What `STRATA_PEER_NO_P2P=1` switches off: the prefill route only

The peer GPU is active in **both** phases — during generation it computes
expert rows from its resident cache, during prefill it computes its share
of every prompt chunk. But the two phases talk to GPU1 differently:

- **Generation** uses the *direct* tier (`STRATA_PEER_DIRECT`, on by
  default): GPU1's kernel writes its result rows zero-copy into a pinned
  host doorbell block. Small, latency-friendly transfers — and this path
  never uses CUDA peer access, so the knob below cannot slow it down.
- **Prefill** moves ~84 MB chunks per layer and can route them either over
  BAR1 P2P (**5.5 GB/s**, real and working thanks to the custom modules)
  or over the pinned-host route (**14.3 GB/s**). Here bandwidth rules:
  the microsecond P2P latency edge saves nothing on 84 MB transfers (dmon
  confirms: GPU1 rx pinned at the link limit, bandwidth-bound), so config
  C takes the host route.

`STRATA_PEER_NO_P2P=1` is surgical: `p2p()` is read in exactly two places,
both in `prefill.cpp` — it moves the *prefill* peer route to host memory
and leaves generation untouched.

Three peer-prefill routes were measured, all on the scale-fixed binary
(PR #2995 — without it every peer row is numerically wrong on NVFP4):

| Route | Forward leg | Return leg | Prefill tok/s |
|---|---|---|---:|
| B | fp32 over P2P | rows over P2P | 1,383 |
| sums-P2P (opt-in `STRATA_PF_PEER_SUMS_P2P=1`) | fp32 over P2P | fp16 sum over host | 2,264 |
| **C — deployed** | fp16 over host | fp16 sum over host | **2,683–2,718** |

**Config C** runs the peer route with P2P off (`STRATA_PEER_NO_P2P=1`): both
legs through mapped pinned host memory, one weighted fp16 sum per token back.
It recovers most of the prefill loss (−34 % vs. layer split instead of −42 %,
at +27 % decode) and is **numerically correct** — recall gate: 24,934-token
cold prompt, both needles found, 0 non-finite logits.

## Running config C

- Engine args: `--peer-device 1 --peer-reserve-mib 1400 --peer-prefill-rows 0`
  (no `--layer-split`)
- Engine env (anchored in the run-config JSON's `"env"` section, so every
  start path — autostart, switcher, manual — gets it):
  `STRATA_PF_PEER_NVFP4=1` + `STRATA_PEER_NO_P2P=1`
- Optional experiment: `STRATA_PF_PEER_SUMS_P2P=1` *without* `STRATA_PEER_NO_P2P`
  — worth a try on boxes where P2P beats PCIe (NVLink bridges, newer boards);
  on this box it loses. The route banner in the model log names the live route.

## Status

- Upstream PR: [Niko1221/Strata#2995](https://github.com/Niko1221/Strata/pull/2995)
  — NVFP4 scale wiring for the peer path (config C), OPEN / mergeable.
- sums-P2P stays env-gated and off by default; not deployed on this box.
