"""Hand-written formula drills: read the equation aloud, fill a piece, say why.

The learner sees LaTeX. The work is English — naming the mechanism, not
decorating symbols. Blanks and term-whys stay on the server until after a try.
"""

from __future__ import annotations

from typing import Any

FORMULAS: list[dict[str, Any]] = [
    {
        "slug": "softmax",
        "title": "Softmax",
        "latex": r"\mathrm{softmax}(z)_i = \frac{e^{z_i}}{\sum_j e^{z_j}}",
        "spoken": (
            "Softmax turns a vector of logits into a probability distribution: "
            "exponentiate each logit, then divide by the sum of those exponentials "
            "so the results are positive and add to one."
        ),
        "intuition": (
            "You need a distribution over classes, but logits are unconstrained reals. "
            "The exponential makes them positive; the sum in the denominator is the "
            "normalizer that turns them into probabilities. Larger logits dominate "
            "because exp grows so fast."
        ),
        "key_phrases": ["probability", "exponent", "sum", "logit"],
        "blanks": [
            {
                "id": "num",
                "prompt": "What sits in the numerator for class i?",
                "answer": "e^{z_i}",
                "aliases": ["exp(z_i)", "exponential of the logit"],
                "why": "The exponential maps any real logit to a positive number, and stretches the gap between winners and losers.",
            },
            {
                "id": "den",
                "prompt": "What sits in the denominator?",
                "answer": "sum of exp(z_j)",
                "aliases": ["sum e^{z_j}", "partition function", "sum of exponentials"],
                "why": "Dividing by the total mass forces the outputs to add to one, which is what makes them a distribution.",
            },
        ],
        "terms": [
            {"symbol": r"z_i", "name": "logit for class i", "why": "The raw, unconstrained score for that class before it is forced into a probability."},
            {"symbol": r"e^{z_i}", "name": "unnormalized mass", "why": "A strictly positive rewrite of the logit so comparison across classes is well-defined."},
        ],
        "tags": ["dl", "probability"],
        "concept_hints": ["softmax"],
    },
    {
        "slug": "cross-entropy",
        "title": "Cross-entropy from logits",
        "latex": r"\mathcal{L} = -\log \mathrm{softmax}(z)_{y} = -z_y + \log\sum_j e^{z_j}",
        "spoken": (
            "Cross-entropy of a one-hot label is the negative log of the softmax "
            "probability of the true class, which expands to minus the true logit "
            "plus the log-sum-exp of every logit."
        ),
        "intuition": (
            "You want the model to put almost all probability on the true class. "
            "Negative log probability punishes a small softmax mass there. Writing "
            "it as -z_y + logsumexp is the numerically stable form of the same idea."
        ),
        "key_phrases": ["negative log", "true class", "softmax", "log sum"],
        "blanks": [
            {
                "id": "nll",
                "prompt": "What happens to the log-probability of the true class?",
                "answer": "it is negated",
                "aliases": ["negative log", "minus log", "-log"],
                "why": "Loss should be large when the predicted probability of the truth is small.",
            },
            {
                "id": "lse",
                "prompt": "What replaces the partition function in the stable form?",
                "answer": "log-sum-exp of the logits",
                "aliases": ["logsumexp", "log of the sum of exponentials"],
                "why": "log of the softmax denominator, computed so huge logits do not overflow.",
            },
        ],
        "terms": [
            {"symbol": r"z_y", "name": "true-class logit", "why": "The score assigned to the labelled class. Raising it directly cuts the loss."},
            {"symbol": r"\log\sum_j e^{z_j}", "name": "log-sum-exp", "why": "A stable stand-in for log of the softmax normalizer, coupling every class together."},
        ],
        "tags": ["dl", "loss"],
        "concept_hints": ["cross-entropy", "cross entropy", "nll"],
    },
    {
        "slug": "attention",
        "title": "Scaled dot-product attention",
        "latex": r"\mathrm{Attention}(Q,K,V)=\mathrm{softmax}\left(\frac{QK^\top}{\sqrt{d}}\right)V",
        "spoken": (
            "Scaled dot-product attention takes the softmax of query-key products "
            "divided by square root of the head dimension, then uses those weights "
            "to mix the values."
        ),
        "intuition": (
            "Queries ask, keys advertise, values carry content. The dot product is "
            "a cheap similarity. Dividing by sqrt(d) stops the dots from growing "
            "with dimension, which would otherwise saturate softmax into one-hot "
            "attention and kill gradients."
        ),
        "key_phrases": ["softmax", "query", "key", "value", "sqrt"],
        "blanks": [
            {
                "id": "scale",
                "prompt": "Why divide by sqrt(d)?",
                "answer": "to keep the variance of the dots from growing with dimension",
                "aliases": ["scale", "prevent softmax saturation", "variance"],
                "why": "Without the scale, large d makes logits huge, softmax collapses to a one-hot, and gradients vanish.",
            },
            {
                "id": "mix",
                "prompt": "What do the softmax weights multiply?",
                "answer": "V",
                "aliases": ["values", "value matrix"],
                "why": "The weights are a distribution over positions; multiplying V is a weighted average of content.",
            },
        ],
        "terms": [
            {"symbol": r"QK^\top", "name": "similarity scores", "why": "Each query is compared to every key so the model can decide where to look."},
            {"symbol": r"\sqrt{d}", "name": "scale", "why": "A dimension-dependent rescaling so softmax stays in a trainable regime."},
        ],
        "tags": ["llm", "attention"],
        "concept_hints": ["attention", "scaled dot"],
    },
    {
        "slug": "grpo-advantage",
        "title": "GRPO group advantages",
        "latex": r"A_{i,k} = \frac{r_{i,k} - \mathrm{mean}_k(r_{i,\cdot})}{\mathrm{std}_k(r_{i,\cdot}) + \varepsilon}",
        "spoken": (
            "GRPO sets the advantage of each rollout to that rollout's reward minus "
            "the mean reward of its group, divided by the group's standard deviation. "
            "There is no learned value model."
        ),
        "intuition": (
            "A critic estimates how good a state is; GRPO refuses that extra network. "
            "The other samples for the same prompt are the baseline. Centering and "
            "scaling inside the group is what 'group relative' means."
        ),
        "key_phrases": ["group", "mean", "standard deviation", "reward", "no value"],
        "blanks": [
            {
                "id": "base",
                "prompt": "What is subtracted from each reward?",
                "answer": "the mean reward of the group",
                "aliases": ["group mean", "mean of the rollouts"],
                "why": "A within-prompt baseline. Better than average in this group is a positive advantage; worse is negative.",
            },
            {
                "id": "scale",
                "prompt": "What do you divide by?",
                "answer": "the group standard deviation",
                "aliases": ["std", "sigma"],
                "why": "So a prompt whose rewards are all 0.9 vs 1.0 is not drowned by a prompt whose rewards span 0 to 10.",
            },
        ],
        "terms": [
            {"symbol": r"r_{i,k}", "name": "reward of rollout k for prompt i", "why": "The only learning signal. Advantages are just a standardised view of these."},
            {"symbol": r"\varepsilon", "name": "stability constant", "why": "Stops a collapse when every rollout in the group got the same reward and std is zero."},
        ],
        "tags": ["rl", "llm"],
        "concept_hints": ["grpo", "advantage", "group relative"],
    },
    {
        "slug": "kl",
        "title": "KL divergence",
        "latex": r"D_{\mathrm{KL}}(q \| p) = \sum_x q(x)\log\frac{q(x)}{p(x)}",
        "spoken": (
            "KL from q to p is the expected log ratio of q over p, with the "
            "expectation taken under q — how many extra nats you spend coding "
            "samples from q using P as the code."
        ),
        "intuition": (
            "It is not a distance: it is asymmetric because the average is under q, "
            "not p. In RLHF and GRPO-style updates, a KL term to the reference "
            "policy is a leash so the new policy cannot wander into garbage."
        ),
        "key_phrases": ["expectation", "log ratio", "under q", "asymmetric"],
        "blanks": [
            {
                "id": "expect",
                "prompt": "Which distribution is the expectation under?",
                "answer": "q",
                "aliases": ["the first argument", "left"],
                "why": "You average the surprise of p on points that q actually produces.",
            },
            {
                "id": "ratio",
                "prompt": "What is inside the log?",
                "answer": "q(x)/p(x)",
                "aliases": ["q over p", "ratio of probabilities"],
                "why": "The pointwise extra cost of using p to describe an event that q thinks is likely.",
            },
        ],
        "terms": [
            {"symbol": r"q", "name": "the approximating / current distribution", "why": "The one you are moving. KL is measured from here."},
            {"symbol": r"p", "name": "the reference", "why": "The code you are charged against — often the frozen SFT policy."},
        ],
        "tags": ["probability", "rl"],
        "concept_hints": ["kl", "kl divergence", "kl term"],
    },
    {
        "slug": "layer-norm",
        "title": "LayerNorm",
        "latex": r"y = \frac{x - \mu}{\sqrt{\sigma^2 + \varepsilon}}\odot \gamma + \beta,\quad \mu=\mathrm{mean}(x),\;\sigma^2=\mathrm{var}(x)",
        "spoken": (
            "LayerNorm subtracts the mean of the last axis, divides by the standard "
            "deviation, then applies a learned per-feature scale and shift."
        ),
        "intuition": (
            "Deep stacks drift in scale. Re-centering and re-scaling each token's "
            "features keeps the next layer in a reasonable range without tying "
            "examples together the way BatchNorm does. Gamma and beta put back "
            "the degrees of freedom you just removed."
        ),
        "key_phrases": ["mean", "variance", "scale", "shift", "last"],
        "blanks": [
            {
                "id": "center",
                "prompt": "What is subtracted from x?",
                "answer": "the mean",
                "aliases": ["mu", "average"],
                "why": "Removes a per-token offset so the next linear layer is not fighting a moving bias.",
            },
            {
                "id": "affine",
                "prompt": "What do gamma and beta do after normalisation?",
                "answer": "learned scale and shift",
                "aliases": ["affine", "gain and bias"],
                "why": "Normalising to mean 0 variance 1 is a hard constraint; the affine map lets the network recover useful scale.",
            },
        ],
        "terms": [
            {"symbol": r"\gamma", "name": "learned gain", "why": "Lets some features stay sharp after the forced unit-variance step."},
            {"symbol": r"\varepsilon", "name": "stability constant", "why": "Protects the reciprocal square root when a token's features are nearly constant."},
        ],
        "tags": ["dl", "layers"],
        "concept_hints": ["layer norm", "layernorm"],
    },
    {
        "slug": "rms-norm",
        "title": "RMSNorm",
        "latex": r"y = \frac{x}{\mathrm{RMS}(x)}\odot \gamma,\quad \mathrm{RMS}(x)=\sqrt{\mathrm{mean}(x^2)+\varepsilon}",
        "spoken": (
            "RMSNorm scales x by the root-mean-square of its last axis and a "
            "learned gain. There is no mean subtraction and no bias."
        ),
        "intuition": (
            "Llama-style models dropped the mean-centering of LayerNorm. What "
            "mattered in practice was the scale. Fewer stats to compute, and the "
            "representation can keep a DC offset if it wants one."
        ),
        "key_phrases": ["root mean square", "no mean", "gain", "scale"],
        "blanks": [
            {
                "id": "rms",
                "prompt": "What is RMS(x)?",
                "answer": "sqrt of mean of x squared",
                "aliases": ["sqrt(mean(x^2))", "root mean square"],
                "why": "A scale estimate that does not spend a pass computing the mean.",
            },
            {
                "id": "missing",
                "prompt": "What LayerNorm pieces are missing?",
                "answer": "mean subtraction and beta",
                "aliases": ["no bias", "no centering"],
                "why": "The designers decided centering was not earning its keep.",
            },
        ],
        "terms": [
            {"symbol": r"\gamma", "name": "learned gain", "why": "The only affine parameter. No beta, so the origin is not reintroduced."},
        ],
        "tags": ["llm", "layers"],
        "concept_hints": ["rmsnorm", "rms norm"],
    },
    {
        "slug": "sgd",
        "title": "Gradient descent step",
        "latex": r"\theta \leftarrow \theta - \eta\nabla_\theta \mathcal{L}(\theta)",
        "spoken": (
            "A gradient descent step subtracts the learning rate times the "
            "gradient of the loss with respect to the parameters."
        ),
        "intuition": (
            "The gradient points to the steepest increase of the loss. Walking "
            "the opposite way, with a small step size eta, is the most local "
            "thing you can do to make the loss smaller."
        ),
        "key_phrases": ["subtract", "learning rate", "gradient", "loss"],
        "blanks": [
            {
                "id": "dir",
                "prompt": "Why is there a minus sign?",
                "answer": "to descend the loss",
                "aliases": ["opposite the gradient", "minimise", "decrease"],
                "why": "The gradient of L points uphill. Training wants downhill.",
            },
            {
                "id": "eta",
                "prompt": "What does eta control?",
                "answer": "step size",
                "aliases": ["learning rate", "how far to walk"],
                "why": "Too large and you jump over the valley; too small and you crawl.",
            },
        ],
        "terms": [
            {"symbol": r"\nabla_\theta \mathcal{L}", "name": "parameter gradient", "why": "The local linear map from a parameter nudge to a change in loss."},
        ],
        "tags": ["optim"],
        "concept_hints": ["gradient descent", "sgd"],
    },
    {
        "slug": "chain-rule",
        "title": "Backprop chain rule",
        "latex": r"\frac{\partial L}{\partial x} = \frac{\partial L}{\partial y}\frac{\partial y}{\partial x}",
        "spoken": (
            "The chain rule says the derivative of the loss with respect to x is "
            "the derivative of the loss with respect to y, times the local "
            "Jacobian of y with respect to x."
        ),
        "intuition": (
            "Each layer only needs to know how it changed its own output, and "
            "how much the loss cared about that output. Backprop is this product "
            "applied from the loss backward, which is why vanishing happens when "
            "many of those local factors are smaller than one."
        ),
        "key_phrases": ["product", "local", "upstream", "jacobian"],
        "blanks": [
            {
                "id": "up",
                "prompt": "What is the upstream factor?",
                "answer": "dL/dy",
                "aliases": ["partial L partial y", "incoming gradient"],
                "why": "How much the loss already cares about this layer's output.",
            },
            {
                "id": "loc",
                "prompt": "What is the local factor?",
                "answer": "dy/dx",
                "aliases": ["partial y partial x", "layer jacobian"],
                "why": "How this layer maps a change in its input to a change in its output.",
            },
        ],
        "terms": [
            {"symbol": r"y", "name": "this layer's output", "why": "The intermediate that both the rest of the net and this layer agree on."},
        ],
        "tags": ["dl", "math"],
        "concept_hints": ["chain rule", "backprop", "vanishing"],
    },
    {
        "slug": "bayes",
        "title": "Bayes' rule",
        "latex": r"p(\theta\mid x)=\frac{p(x\mid\theta)\,p(\theta)}{p(x)}",
        "spoken": (
            "Posterior equals likelihood times prior, divided by the evidence: "
            "how much you should believe theta after seeing x."
        ),
        "intuition": (
            "The likelihood is what the data would look like if theta were true. "
            "The prior is what you believed before the data. Their product is "
            "unnormalized belief; dividing by p(x) makes it a distribution over theta."
        ),
        "key_phrases": ["posterior", "likelihood", "prior", "evidence"],
        "blanks": [
            {
                "id": "like",
                "prompt": "What is p(x | theta)?",
                "answer": "the likelihood",
                "aliases": ["likelihood of the data"],
                "why": "It scores how well this parameter would have produced the observation.",
            },
            {
                "id": "ev",
                "prompt": "What is the denominator p(x) doing?",
                "answer": "normalising so the posterior sums to one",
                "aliases": ["evidence", "marginal likelihood"],
                "why": "Without it you have a score, not a probability over hypotheses.",
            },
        ],
        "terms": [
            {"symbol": r"p(\theta)", "name": "prior", "why": "Belief before this observation. In deep learning this is often implicit in the architecture and init."},
        ],
        "tags": ["probability", "stats"],
        "concept_hints": ["bayes", "posterior"],
    },
    {
        "slug": "mse",
        "title": "Mean squared error",
        "latex": r"\mathrm{MSE}=\frac{1}{n}\sum_{i=1}^n (y_i-\hat{y}_i)^2",
        "spoken": (
            "Mean squared error is the average of squared differences between "
            "each target and its prediction."
        ),
        "intuition": (
            "Squaring does two jobs: it makes every error positive, and it "
            "punishes large misses much more than small ones. The mean just "
            "makes the number comparable across batch sizes. Under a Gaussian "
            "noise model this is also maximum likelihood."
        ),
        "key_phrases": ["average", "squared", "difference", "target"],
        "blanks": [
            {
                "id": "sq",
                "prompt": "Why square the residual?",
                "answer": "to make errors positive and penalise large misses more",
                "aliases": ["always positive", "quadratic penalty"],
                "why": "A signed residual would cancel. A quadratic also matches Gaussian MLE.",
            },
        ],
        "terms": [
            {"symbol": r"y_i", "name": "target", "why": "The number the model is supposed to hit."},
            {"symbol": r"\hat{y}_i", "name": "prediction", "why": "What the model actually emitted for that example."},
        ],
        "tags": ["loss", "stats"],
        "concept_hints": ["mean squared", "mse"],
    },
    {
        "slug": "cosine",
        "title": "Cosine similarity",
        "latex": r"\cos(a,b)=\frac{a\cdot b}{\|a\|\,\|b\|}",
        "spoken": (
            "Cosine similarity is the dot product of two vectors after each has "
            "been divided by its Euclidean norm — the cosine of the angle between them."
        ),
        "intuition": (
            "You often care about direction, not magnitude: two reviews can be "
            "long or short and still be about the same thing. Normalising strips "
            "length so the score lives in [-1, 1] and is just an angle."
        ),
        "key_phrases": ["dot product", "norm", "angle", "direction"],
        "blanks": [
            {
                "id": "den",
                "prompt": "What is in the denominator?",
                "answer": "the product of the two Euclidean norms",
                "aliases": ["||a|| ||b||", "lengths"],
                "why": "Dividing out length leaves only orientation.",
            },
        ],
        "terms": [
            {"symbol": r"a\cdot b", "name": "dot product", "why": "Sums coordinatewise agreement. Large when vectors point the same way and are long."},
        ],
        "tags": ["metrics"],
        "concept_hints": ["cosine"],
    },
]
