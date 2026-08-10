#!/bin/bash
export HF_HOME=$HOME/tg/hf
export HF_HUB_OFFLINE=1
export VLLM_CACHE_ROOT=$HOME/tg/vllm_cache
# vLLM JIT-compiles MXFP4 Marlin kernels for Ampere. The host has only the
# driver, but the torch cu13 wheels ship a full nvcc toolchain; ninja lives in
# the venv bin, which is not on PATH when the launcher is exec'd directly.
export CUDA_HOME=$HOME/tg/vllmenv/lib/python3.12/site-packages/nvidia/cu13
export PATH=$HOME/tg/vllmenv/bin:$CUDA_HOME/bin:$PATH
# flashinfer ships cccl headers incompatible with the bundled nvcc 13.3 and
# fails its JIT build; it is an optional fast path, so use the native kernels.
export VLLM_USE_FLASHINFER_SAMPLER=0
export VLLM_ATTENTION_BACKEND=TRITON_ATTN
export VLLM_LOGGING_LEVEL=INFO
exec $HOME/tg/vllmenv/bin/vllm serve openai/gpt-oss-20b \
  --served-model-name gpt-oss-20b \
  --host 0.0.0.0 --port 8000 \
  --tensor-parallel-size 2 \
  --max-model-len 131072 \
  --gpu-memory-utilization 0.90 \
  --enable-auto-tool-choice \
  --tool-call-parser openai \
  --max-num-seqs 8
