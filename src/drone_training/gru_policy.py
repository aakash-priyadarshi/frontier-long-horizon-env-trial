"""Small multi-head GRU behaviour-cloning baseline."""

from __future__ import annotations

try:
    import torch
    from torch import Tensor, nn
except ImportError as exc:  # pragma: no cover - exercised by dependency guard
    raise ImportError("Talon learned policies require the optional 'talon' dependency") from exc

from .features import ACTION_PADDING_INDEX, ACTIONS, FEATURE_DIM, MISSING_EVIDENCE_CODES


class GRUPolicy(nn.Module):
    def __init__(
        self,
        *,
        feature_dim: int = FEATURE_DIM,
        hidden_dim: int = 128,
        layers: int = 2,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.config = {
            "feature_dim": feature_dim,
            "hidden_dim": hidden_dim,
            "layers": layers,
            "dropout": dropout,
        }
        self.state_projection = nn.Linear(feature_dim, hidden_dim)
        self.action_embedding = nn.Embedding(len(ACTIONS) + 1, hidden_dim, padding_idx=ACTION_PADDING_INDEX)
        self.gru = nn.GRU(
            hidden_dim * 2,
            hidden_dim,
            num_layers=layers,
            batch_first=True,
            dropout=dropout if layers > 1 else 0.0,
        )
        self.action_head = nn.Linear(hidden_dim, len(ACTIONS))
        self.threat_head = nn.Linear(hidden_dim, 1)
        self.uncertainty_head = nn.Linear(hidden_dim, 1)
        self.missing_evidence_head = nn.Linear(hidden_dim, len(MISSING_EVIDENCE_CODES))

    def forward(self, states: Tensor, previous_actions: Tensor, mask: Tensor) -> dict[str, Tensor]:
        embedded = torch.cat(
            (self.state_projection(states), self.action_embedding(previous_actions)), dim=-1
        )
        output, _ = self.gru(embedded)
        final_index = mask.sum(dim=1).long().clamp(min=1) - 1
        final = output[torch.arange(output.shape[0], device=output.device), final_index]
        return {
            "action_logits": self.action_head(final),
            "threat_probability": torch.sigmoid(self.threat_head(final)).squeeze(-1),
            "uncertainty": torch.sigmoid(self.uncertainty_head(final)).squeeze(-1),
            "missing_evidence": self.missing_evidence_head(final),
        }
