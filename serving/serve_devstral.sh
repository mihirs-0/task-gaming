#!/bin/bash
# Devstral-Small-2507 (AWQ 4-bit) — model 2 (PREREG A6c).
# Mistral family (deliberately not Qwen), 128k native context, agentic-coding
# tuned. Dense 24B: 4-bit weights ~13GB leave ample KV headroom on 2x24GB.
# Non-reasoning, so no reasoning parser and no reasoning_effort.
# The community AWQ repo ships no HF chat template (vLLM 400s on tool calls),
# but does ship tekken.json, so vLLM's mistral tokenizer mode supplies the
# template. config-format stays HF so the AWQ quantization_config is honoured.
export HF_HOME=$HOME/tg/hf
export HF_HUB_OFFLINE=1
export VLLM_CACHE_ROOT=$HOME/tg/vllm_cache
export CUDA_HOME=$HOME/tg/vllmenv/lib/python3.12/site-packages/nvidia/cu13
export PATH=$HOME/tg/vllmenv/bin:$CUDA_HOME/bin:$PATH
export VLLM_USE_FLASHINFER_SAMPLER=0
export VLLM_ATTENTION_BACKEND=TRITON_ATTN
export VLLM_LOGGING_LEVEL=INFO

MAXLEN=${MAXLEN:-131072}
UTIL=${UTIL:-0.92}

exec $HOME/tg/vllmenv/bin/vllm serve cpatonn/Devstral-Small-2507-AWQ-4bit \
  --served-model-name devstral-small \
  --host 0.0.0.0 --port 8000 \
  --tensor-parallel-size 2 \
  --max-model-len "$MAXLEN" \
  --kv-cache-dtype bfloat16 \
  --gpu-memory-utilization "$UTIL" \
  --enable-auto-tool-choice \
  --tool-call-parser mistral \
  --tokenizer-mode mistral \
  --max-num-seqs 8
