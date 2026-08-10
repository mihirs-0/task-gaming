#!/bin/bash
# Qwen3-Coder-30B-A3B-Instruct, AWQ 4-bit — model 1 (PREREG A5).
#
# Weight quantization is chosen for KV headroom, not speed. Measured on this
# box: FP8 weights leave only 134,944 KV tokens (1.03x concurrency at 131k),
# no better than the gpt-oss-20b context this swap exists to escape. FP8 KV
# cache is unavailable — vLLM: "FP8 KV cache is not supported by the Triton
# attention backend on RTX 3090 (compute capability 8.6); native FP8 requires
# SM89+". 4-bit weights are the only way to buy real context on 2x24GB.
export HF_HOME=$HOME/tg/hf
export HF_HUB_OFFLINE=1
export VLLM_CACHE_ROOT=$HOME/tg/vllm_cache
export CUDA_HOME=$HOME/tg/vllmenv/lib/python3.12/site-packages/nvidia/cu13
export PATH=$HOME/tg/vllmenv/bin:$CUDA_HOME/bin:$PATH
export VLLM_USE_FLASHINFER_SAMPLER=0
export VLLM_ATTENTION_BACKEND=TRITON_ATTN
export VLLM_LOGGING_LEVEL=INFO

MAXLEN=${MAXLEN:-262144}
UTIL=${UTIL:-0.92}

exec $HOME/tg/vllmenv/bin/vllm serve cpatonn/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit \
  --served-model-name qwen3-coder-30b \
  --host 0.0.0.0 --port 8000 \
  --tensor-parallel-size 2 \
  --max-model-len "$MAXLEN" \
  --kv-cache-dtype bfloat16 \
  --gpu-memory-utilization "$UTIL" \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --max-num-seqs 8
