"""Compact causal Decision Transformer for vector-state Talon trajectories."""

from __future__ import annotations

try:
    import torch
    from torch import Tensor, nn
except ImportError as exc:  # pragma: no cover - exercised by dependency guard
    raise ImportError("Talon learned policies require the optional 'talon' dependency") from exc

from .features import ACTION_PADDING_INDEX, ACTIONS, FEATURE_DIM, MISSING_EVIDENCE_CODES


class DecisionTransformerPolicy(nn.Module):
    def __init__(
        self,
        *,
        feature_dim: int = FEATURE_DIM,
        hidden_dim: int = 256,
        layers: int = 6,
        heads: int = 8,
        context_length: int = 20,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        if hidden_dim % heads:
            raise ValueError("hidden_dim must be divisible by heads")
        self.config = {
            "feature_dim": feature_dim,
            "hidden_dim": hidden_dim,
            "layers": layers,
            "heads": heads,
            "context_length": context_length,
            "dropout": dropout,
        }
        self.state_embedding = nn.Linear(feature_dim, hidden_dim)
        self.action_embedding = nn.Embedding(len(ACTIONS) + 1, hidden_dim, padding_idx=ACTION_PADDING_INDEX)
        self.return_embedding = nn.Linear(1, hidden_dim)
        self.position_embedding = nn.Embedding(context_length, hidden_dim)
        layer = nn.TransformerEncoderLayer(
            d_model=hidden_dim,
            nhead=heads,
            dim_feedforward=hidden_dim * 4,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.transformer = nn.TransformerEncoder(layer, num_layers=layers, enable_nested_tensor=False)
        self.final_norm = nn.LayerNorm(hidden_dim)
        self.action_head = nn.Linear(hidden_dim, len(ACTIONS))
        self.threat_head = nn.Linear(hidden_dim, 1)
        self.uncertainty_head = nn.Linear(hidden_dim, 1)
        self.missing_evidence_head = nn.Linear(hidden_dim, len(MISSING_EVIDENCE_CODES))

    def forward(
        self,
        states: Tensor,
        previous_actions: Tensor,
        returns_to_go: Tensor,
        mask: Tensor,
    ) -> dict[str, Tensor]:
        batch, sequence, _ = states.shape
        if sequence > self.config["context_length"]:
            raise ValueError("sequence exceeds configured context length")
        positions = torch.arange(sequence, device=states.device).unsqueeze(0).expand(batch, sequence)
        tokens = (
            self.state_embedding(states)
            + self.action_embedding(previous_actions)
            + self.return_embedding(returns_to_go.unsqueeze(-1))
            + self.position_embedding(positions)
        )
        causal_mask = torch.triu(
            torch.ones(sequence, sequence, dtype=torch.bool, device=states.device), diagonal=1
        )
        encoded = self.transformer(
            tokens,
            mask=causal_mask,
            src_key_padding_mask=~mask.bool(),
        )
        final_index = mask.sum(dim=1).long().clamp(min=1) - 1
        final = self.final_norm(encoded[torch.arange(batch, device=states.device), final_index])
        return {
            "action_logits": self.action_head(final),
            "threat_probability": torch.sigmoid(self.threat_head(final)).squeeze(-1),
            "uncertainty": torch.sigmoid(self.uncertainty_head(final)).squeeze(-1),
            "missing_evidence": self.missing_evidence_head(final),
        }
