"""Hand-written coding drills: PyTorch, numerics, and LLM internals.

These are original practice problems, not scraped from LeetCode or Deep-ML.
Hidden checks stay on the server. The learner only sees the prompt and starter.
"""

from __future__ import annotations

from typing import Any

_TORCH_PREAMBLE = """
import torch

def _close(got, want, tol=1e-5, name="tensors"):
    if not torch.is_tensor(got):
        raise AssertionError(f"{name}: expected a torch.Tensor, got {type(got).__name__}")
    if tuple(got.shape) != tuple(want.shape):
        raise AssertionError(f"{name}: shape {tuple(got.shape)} != {tuple(want.shape)}")
    if not torch.allclose(got.float(), want.float(), atol=tol, rtol=tol):
        raise AssertionError(f"{name}: values differ")
"""


def _checks(*cases: str) -> str:
    body = "\n\n".join(cases)
    return _TORCH_PREAMBLE + "\n" + body + "\n"


PROBLEMS: list[dict[str, Any]] = [
    {
        "slug": "softmax",
        "title": "Numerically stable softmax",
        "difficulty": "easy",
        "tags": ["pytorch", "numerics"],
        "concept_hints": ["softmax"],
        "prompt": (
            "Implement `softmax(x, dim=-1)` without calling `torch.softmax` or "
            "`torch.nn.functional.softmax`. Subtract the max along `dim` before the "
            "exp so large logits do not overflow. The result must sum to 1 along `dim`."
        ),
        "starter": (
            "import torch\n\n"
            "def softmax(x: torch.Tensor, dim: int = -1) -> torch.Tensor:\n"
            "    raise NotImplementedError\n"
        ),
        "tests": _checks(
            "from solution import softmax",
            "CHECKS = [\n"
            "    ('matches torch.softmax', lambda: _close(\n"
            "        softmax(torch.tensor([1.0, 2.0, 3.0])),\n"
            "        torch.softmax(torch.tensor([1.0, 2.0, 3.0]), dim=-1))),\n"
            "    ('stable on huge logits', lambda: _close(\n"
            "        softmax(torch.tensor([1000.0, 1000.0, 1001.0])),\n"
            "        torch.softmax(torch.tensor([1000.0, 1000.0, 1001.0]), dim=-1))),\n"
            "    ('batched last dim', lambda: _close(\n"
            "        softmax(torch.arange(12, dtype=torch.float32).reshape(3, 4)),\n"
            "        torch.softmax(torch.arange(12, dtype=torch.float32).reshape(3, 4), dim=-1))),\n"
            "    ('sums to one', lambda: _close(\n"
            "        softmax(torch.randn(2, 5)).sum(dim=-1),\n"
            "        torch.ones(2))),\n"
            "]\n",
        ),
    },
    {
        "slug": "log-softmax",
        "title": "Log-softmax from logits",
        "difficulty": "easy",
        "tags": ["pytorch", "numerics"],
        "concept_hints": ["log softmax", "log-softmax", "logprob"],
        "prompt": (
            "Implement `log_softmax(x, dim=-1)` in log-space. Do not call "
            "`torch.log_softmax`. A correct version is `x - logsumexp(x)` after "
            "the same max-subtraction trick as softmax."
        ),
        "starter": (
            "import torch\n\n"
            "def log_softmax(x: torch.Tensor, dim: int = -1) -> torch.Tensor:\n"
            "    raise NotImplementedError\n"
        ),
        "tests": _checks(
            "from solution import log_softmax",
            "CHECKS = [\n"
            "    ('matches torch.log_softmax', lambda: _close(\n"
            "        log_softmax(torch.tensor([0.2, -1.0, 3.5])),\n"
            "        torch.log_softmax(torch.tensor([0.2, -1.0, 3.5]), dim=-1))),\n"
            "    ('stable on huge logits', lambda: _close(\n"
            "        log_softmax(torch.tensor([1000.0, 1001.0])),\n"
            "        torch.log_softmax(torch.tensor([1000.0, 1001.0]), dim=-1))),\n"
            "]\n",
        ),
    },
    {
        "slug": "cross-entropy",
        "title": "Cross-entropy from logits",
        "difficulty": "medium",
        "tags": ["pytorch", "loss"],
        "concept_hints": ["cross-entropy", "cross entropy", "nll"],
        "prompt": (
            "Implement `cross_entropy(logits, targets)` for a classification batch. "
            "`logits` is `(N, C)`, `targets` is `(N,)` of class indices. Return the "
            "mean NLL of `log_softmax(logits)` at the target index. Do not call "
            "`torch.nn.functional.cross_entropy`."
        ),
        "starter": (
            "import torch\n\n"
            "def cross_entropy(logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:\n"
            "    raise NotImplementedError\n"
        ),
        "tests": _checks(
            "from solution import cross_entropy",
            "logits = torch.tensor([[1.0, 2.0, 0.1], [0.0, 0.0, 5.0]])\n"
            "targets = torch.tensor([1, 2])\n"
            "CHECKS = [\n"
            "    ('matches F.cross_entropy', lambda: _close(\n"
            "        cross_entropy(logits, targets),\n"
            "        torch.nn.functional.cross_entropy(logits, targets))),\n"
            "    ('scalar output', lambda: None if cross_entropy(logits, targets).ndim == 0 "
            "else (_ for _ in ()).throw(AssertionError('expected a scalar'))),\n"
            "]\n",
        ),
    },
    {
        "slug": "linear-forward",
        "title": "Linear layer forward",
        "difficulty": "easy",
        "tags": ["pytorch", "layers"],
        "concept_hints": ["linear layer", "affine"],
        "prompt": (
            "Implement `linear(x, weight, bias)` as `x @ weight.T + bias`. "
            "`x` is `(..., in_features)`, `weight` is `(out_features, in_features)`, "
            "`bias` is `(out_features,)` or `None`."
        ),
        "starter": (
            "import torch\n\n"
            "def linear(x: torch.Tensor, weight: torch.Tensor, bias: torch.Tensor | None) -> torch.Tensor:\n"
            "    raise NotImplementedError\n"
        ),
        "tests": _checks(
            "from solution import linear",
            "x = torch.arange(6, dtype=torch.float32).reshape(2, 3)\n"
            "w = torch.arange(12, dtype=torch.float32).reshape(4, 3)\n"
            "b = torch.tensor([0.1, 0.2, 0.3, 0.4])\n"
            "CHECKS = [\n"
            "    ('with bias', lambda: _close(linear(x, w, b), torch.nn.functional.linear(x, w, b))),\n"
            "    ('no bias', lambda: _close(linear(x, w, None), torch.nn.functional.linear(x, w, None))),\n"
            "]\n",
        ),
    },
    {
        "slug": "mse-loss",
        "title": "Mean squared error",
        "difficulty": "easy",
        "tags": ["pytorch", "loss"],
        "concept_hints": ["mean squared", "mse"],
        "prompt": (
            "Implement `mse(pred, target)` as the mean of squared differences over "
            "every element. Do not call `torch.nn.functional.mse_loss`."
        ),
        "starter": (
            "import torch\n\n"
            "def mse(pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:\n"
            "    raise NotImplementedError\n"
        ),
        "tests": _checks(
            "from solution import mse",
            "pred = torch.tensor([[1.0, 2.0], [3.0, 4.0]])\n"
            "target = torch.tensor([[1.5, 2.0], [2.0, 5.0]])\n"
            "CHECKS = [\n"
            "    ('matches F.mse_loss', lambda: _close(mse(pred, target), torch.nn.functional.mse_loss(pred, target))),\n"
            "]\n",
        ),
    },
    {
        "slug": "sgd-step",
        "title": "SGD parameter step",
        "difficulty": "easy",
        "tags": ["pytorch", "optim"],
        "concept_hints": ["gradient descent", "sgd"],
        "prompt": (
            "Implement `sgd_step(param, grad, lr)` returning the updated parameter "
            "`param - lr * grad`. Do not mutate the inputs in place; return a new tensor."
        ),
        "starter": (
            "import torch\n\n"
            "def sgd_step(param: torch.Tensor, grad: torch.Tensor, lr: float) -> torch.Tensor:\n"
            "    raise NotImplementedError\n"
        ),
        "tests": _checks(
            "from solution import sgd_step",
            "p = torch.tensor([1.0, -2.0, 0.5])\n"
            "g = torch.tensor([0.1, -0.2, 0.0])\n"
            "CHECKS = [\n"
            "    ('steps against the gradient', lambda: _close(sgd_step(p, g, 0.5), p - 0.5 * g)),\n"
            "    ('leaves param unchanged', lambda: (_close(p, torch.tensor([1.0, -2.0, 0.5]), name='param'))),\n"
            "]\n",
        ),
    },
    {
        "slug": "layer-norm",
        "title": "LayerNorm over the last axis",
        "difficulty": "medium",
        "tags": ["pytorch", "layers", "llm"],
        "concept_hints": ["layer norm", "layernorm", "layer normalisation", "layer normalization"],
        "prompt": (
            "Implement `layer_norm(x, weight, bias, eps=1e-5)` over the last dimension. "
            "Normalise to mean 0 variance 1, then apply affine `weight` and `bias`, "
            "both shaped `(x.shape[-1],)`."
        ),
        "starter": (
            "import torch\n\n"
            "def layer_norm(x: torch.Tensor, weight: torch.Tensor, bias: torch.Tensor, eps: float = 1e-5) -> torch.Tensor:\n"
            "    raise NotImplementedError\n"
        ),
        "tests": _checks(
            "from solution import layer_norm",
            "x = torch.arange(12, dtype=torch.float32).reshape(2, 2, 3)\n"
            "w = torch.tensor([1.0, 0.5, 2.0])\n"
            "b = torch.tensor([0.0, 0.1, -0.2])\n"
            "ref = torch.nn.functional.layer_norm(x, (3,), w, b, 1e-5)\n"
            "CHECKS = [\n"
            "    ('matches F.layer_norm', lambda: _close(layer_norm(x, w, b), ref, tol=1e-4)),\n"
            "]\n",
        ),
    },
    {
        "slug": "rms-norm",
        "title": "RMSNorm",
        "difficulty": "medium",
        "tags": ["pytorch", "llm"],
        "concept_hints": ["rmsnorm", "rms norm"],
        "prompt": (
            "Implement `rms_norm(x, weight, eps=1e-6)` used in Llama-style models: "
            "`x * rsqrt(mean(x^2, last dim) + eps) * weight`. No bias, no mean subtraction."
        ),
        "starter": (
            "import torch\n\n"
            "def rms_norm(x: torch.Tensor, weight: torch.Tensor, eps: float = 1e-6) -> torch.Tensor:\n"
            "    raise NotImplementedError\n"
        ),
        "tests": _checks(
            "from solution import rms_norm",
            "x = torch.tensor([[1.0, -1.0, 2.0], [0.0, 3.0, -4.0]])\n"
            "w = torch.tensor([1.5, 1.0, 0.5])\n"
            "def _ref(x, w, eps=1e-6):\n"
            "    rms = torch.sqrt(x.pow(2).mean(dim=-1, keepdim=True) + eps)\n"
            "    return x / rms * w\n"
            "CHECKS = [\n"
            "    ('matches RMS formula', lambda: _close(rms_norm(x, w), _ref(x, w), tol=1e-5)),\n"
            "]\n",
        ),
    },
    {
        "slug": "scaled-dot-product-attention",
        "title": "Scaled dot-product attention",
        "difficulty": "hard",
        "tags": ["pytorch", "attention", "llm"],
        "concept_hints": ["attention", "scaled dot", "self-attention"],
        "prompt": (
            "Implement `attention(q, k, v)` for unbatched sequences: `q,k,v` are "
            "`(S, D)`. Scores are `q @ k.T / sqrt(D)`, then softmax, then `@ v`. "
            "No mask, no dropout, no batch or head dims."
        ),
        "starter": (
            "import torch\n\n"
            "def attention(q: torch.Tensor, k: torch.Tensor, v: torch.Tensor) -> torch.Tensor:\n"
            "    raise NotImplementedError\n"
        ),
        "tests": _checks(
            "from solution import attention",
            "torch.manual_seed(0)\n"
            "q = torch.randn(4, 8)\n"
            "k = torch.randn(4, 8)\n"
            "v = torch.randn(4, 8)\n"
            "scale = 8 ** 0.5\n"
            "ref = torch.softmax(q @ k.T / scale, dim=-1) @ v\n"
            "CHECKS = [\n"
            "    ('matches the textbook formula', lambda: _close(attention(q, k, v), ref, tol=1e-5)),\n"
            "    ('output shape', lambda: None if attention(q, k, v).shape == q.shape "
            "else (_ for _ in ()).throw(AssertionError('shape'))),\n"
            "]\n",
        ),
    },
    {
        "slug": "causal-mask",
        "title": "Causal attention mask",
        "difficulty": "medium",
        "tags": ["pytorch", "attention", "llm"],
        "concept_hints": ["causal", "autoregressive mask"],
        "prompt": (
            "Implement `causal_mask(scores)` where `scores` is `(S, S)`. Positions "
            "`j > i` (looking ahead) must become `-inf` so softmax puts zero mass "
            "on the future. Do not change the lower triangle including the diagonal."
        ),
        "starter": (
            "import torch\n\n"
            "def causal_mask(scores: torch.Tensor) -> torch.Tensor:\n"
            "    raise NotImplementedError\n"
        ),
        "tests": _checks(
            "from solution import causal_mask",
            "s = torch.arange(9, dtype=torch.float32).reshape(3, 3)\n"
            "out = None\n"
            "def _run():\n"
            "    global out\n"
            "    out = causal_mask(s.clone())\n"
            "    return out\n"
            "CHECKS = [\n"
            "    ('keeps the present and past', lambda: _close(_run()[1, :2], s[1, :2], name='lower')),\n"
            "    ('future is -inf', lambda: None if torch.isneginf(causal_mask(s.clone())[0, 1]) "
            "and torch.isneginf(causal_mask(s.clone())[0, 2]) and torch.isneginf(causal_mask(s.clone())[1, 2])\n"
            "    else (_ for _ in ()).throw(AssertionError('expected -inf above the diagonal'))),\n"
            "]\n",
        ),
    },
    {
        "slug": "repeat-kv-heads",
        "title": "Repeat KV heads for GQA",
        "difficulty": "medium",
        "tags": ["pytorch", "attention", "llm"],
        "concept_hints": ["grouped query", "gqa", "kv heads"],
        "prompt": (
            "Grouped-query attention stores fewer KV heads than query heads. "
            "Implement `repeat_kv(kv, n_rep)` where `kv` is `(B, n_kv, S, D)` and "
            "the result is `(B, n_kv * n_rep, S, D)` by repeating each KV head "
            "`n_rep` times. If `n_rep == 1`, return `kv` unchanged."
        ),
        "starter": (
            "import torch\n\n"
            "def repeat_kv(kv: torch.Tensor, n_rep: int) -> torch.Tensor:\n"
            "    raise NotImplementedError\n"
        ),
        "tests": _checks(
            "from solution import repeat_kv",
            "kv = torch.arange(24, dtype=torch.float32).reshape(1, 2, 3, 4)\n"
            "CHECKS = [\n"
            "    ('n_rep 1 is identity', lambda: _close(repeat_kv(kv, 1), kv)),\n"
            "    ('repeats the first head', lambda: _close(repeat_kv(kv, 2)[0, 0], kv[0, 0])),\n"
            "    ('copies the first head into the next slot', lambda: _close(repeat_kv(kv, 2)[0, 1], kv[0, 0])),\n"
            "    ('shape', lambda: None if repeat_kv(kv, 3).shape == (1, 6, 3, 4)\n"
            "    else (_ for _ in ()).throw(AssertionError(repeat_kv(kv, 3).shape))),\n"
            "]\n",
        ),
    },
    {
        "slug": "group-advantages",
        "title": "GRPO group advantages",
        "difficulty": "medium",
        "tags": ["pytorch", "rl", "llm"],
        "concept_hints": ["grpo", "advantage", "group relative"],
        "prompt": (
            "GRPO does not learn a value model. Implement `group_advantages(rewards, eps=1e-8)` "
            "for `rewards` of shape `(B, G)`: subtract the group mean and divide by the "
            "group standard deviation (unbiased=False, like `torch.std(..., correction=0)`). "
            "Each row is one prompt's group of rollouts. The result must have mean ~0 per row."
        ),
        "starter": (
            "import torch\n\n"
            "def group_advantages(rewards: torch.Tensor, eps: float = 1e-8) -> torch.Tensor:\n"
            "    raise NotImplementedError\n"
        ),
        "tests": _checks(
            "from solution import group_advantages",
            "r = torch.tensor([[1.0, 2.0, 3.0, 4.0], [10.0, 10.0, 10.0, 14.0]])\n"
            "mean = r.mean(dim=-1, keepdim=True)\n"
            "std = r.std(dim=-1, keepdim=True, correction=0)\n"
            "ref = (r - mean) / (std + 1e-8)\n"
            "CHECKS = [\n"
            "    ('matches group z-score', lambda: _close(group_advantages(r), ref, tol=1e-5)),\n"
            "    ('row mean near zero', lambda: _close(group_advantages(r).mean(dim=-1), torch.zeros(2), tol=1e-5)),\n"
            "]\n",
        ),
    },
    {
        "slug": "gelu",
        "title": "GELU activation",
        "difficulty": "easy",
        "tags": ["pytorch", "layers"],
        "concept_hints": ["gelu"],
        "prompt": (
            "Implement `gelu(x)` as the tanh approximation used by GPT-2 / BERT: "
            "`0.5 * x * (1 + tanh(sqrt(2/pi) * (x + 0.044715 * x^3)))`. "
            "Do not call `torch.nn.functional.gelu`."
        ),
        "starter": (
            "import torch\n\n"
            "def gelu(x: torch.Tensor) -> torch.Tensor:\n"
            "    raise NotImplementedError\n"
        ),
        "tests": _checks(
            "from solution import gelu",
            "x = torch.tensor([-2.0, -0.5, 0.0, 0.5, 2.0])\n"
            "ref = torch.nn.functional.gelu(x, approximate='tanh')\n"
            "CHECKS = [\n"
            "    ('matches tanh GELU', lambda: _close(gelu(x), ref, tol=1e-5)),\n"
            "]\n",
        ),
    },
    {
        "slug": "embedding-lookup",
        "title": "Embedding lookup",
        "difficulty": "easy",
        "tags": ["pytorch", "layers"],
        "concept_hints": ["embedding"],
        "prompt": (
            "Implement `embed(ids, weight)` as a gather: `ids` is `(N, S)` of integer "
            "indices, `weight` is `(V, D)`. Return `(N, S, D)`. Do not call `torch.nn.functional.embedding`."
        ),
        "starter": (
            "import torch\n\n"
            "def embed(ids: torch.Tensor, weight: torch.Tensor) -> torch.Tensor:\n"
            "    raise NotImplementedError\n"
        ),
        "tests": _checks(
            "from solution import embed",
            "weight = torch.arange(20, dtype=torch.float32).reshape(5, 4)\n"
            "ids = torch.tensor([[0, 4], [2, 1]])\n"
            "CHECKS = [\n"
            "    ('gathers rows', lambda: _close(embed(ids, weight), torch.nn.functional.embedding(ids, weight))),\n"
            "]\n",
        ),
    },
    {
        "slug": "cosine-similarity",
        "title": "Row-wise cosine similarity",
        "difficulty": "easy",
        "tags": ["pytorch", "metrics"],
        "concept_hints": ["cosine"],
        "prompt": (
            "Implement `cosine(a, b, eps=1e-8)` for `a` and `b` of shape `(N, D)`, "
            "returning `(N,)` cosine similarities. Normalise each row, then multiply "
            "and sum over `D`."
        ),
        "starter": (
            "import torch\n\n"
            "def cosine(a: torch.Tensor, b: torch.Tensor, eps: float = 1e-8) -> torch.Tensor:\n"
            "    raise NotImplementedError\n"
        ),
        "tests": _checks(
            "from solution import cosine",
            "a = torch.tensor([[1.0, 0.0], [1.0, 1.0], [0.0, 2.0]])\n"
            "b = torch.tensor([[1.0, 0.0], [1.0, 0.0], [0.0, -1.0]])\n"
            "ref = torch.nn.functional.cosine_similarity(a, b, dim=-1)\n"
            "CHECKS = [\n"
            "    ('matches F.cosine_similarity', lambda: _close(cosine(a, b), ref, tol=1e-5)),\n"
            "]\n",
        ),
    },
    {
        "slug": "kl-divergence",
        "title": "KL divergence of categoricals",
        "difficulty": "medium",
        "tags": ["pytorch", "loss", "rl"],
        "concept_hints": ["kl", "kl divergence", "kl term"],
        "prompt": (
            "Implement `kl_div(log_p, q)` for two categorical distributions over the "
            "last axis. `log_p` is log-probabilities `(..., C)`, `q` is probabilities "
            "that sum to 1. Return `sum(q * (log q - log_p))` reduced over the last "
            "axis, then mean over the batch. Use `q.clamp_min(1e-8)` before taking log."
        ),
        "starter": (
            "import torch\n\n"
            "def kl_div(log_p: torch.Tensor, q: torch.Tensor) -> torch.Tensor:\n"
            "    raise NotImplementedError\n"
        ),
        "tests": _checks(
            "from solution import kl_div",
            "q = torch.tensor([[0.1, 0.2, 0.7], [0.5, 0.5, 0.0]])\n"
            "p = torch.tensor([[0.2, 0.2, 0.6], [0.4, 0.4, 0.2]])\n"
            "log_p = torch.log(p)\n"
            "q_safe = q.clamp_min(1e-8)\n"
            "ref = (q * (q_safe.log() - log_p)).sum(dim=-1).mean()\n"
            "CHECKS = [\n"
            "    ('matches sum q log(q/p)', lambda: _close(kl_div(log_p, q), ref, tol=1e-5)),\n"
            "]\n",
        ),
    },
]
