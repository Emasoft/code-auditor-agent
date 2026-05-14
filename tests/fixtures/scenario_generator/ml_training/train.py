"""ML training fixture — exercises PyTorch low-level and sklearn-style loops.

The discoverer should pick up:
- ``train(...)``: PyTorch-style loop using optimizer.step + loss.backward.
- ``fit_sklearn(...)``: sklearn-style estimator.fit pipeline.
- ``main(cfg)``: Hydra-decorated entrypoint.

Each is one MAIN_FUNCTION entry point.
"""

from __future__ import annotations

from typing import Any

import hydra
import torch
import torch.nn as nn
from sklearn.linear_model import LogisticRegression
from torch.utils.data import DataLoader


class TinyNet(nn.Module):
    """A two-layer network — used as the model under test."""

    def __init__(self) -> None:
        super().__init__()
        self.fc1 = nn.Linear(10, 8)
        self.fc2 = nn.Linear(8, 2)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc2(torch.relu(self.fc1(x)))


def train(model: nn.Module, loader: DataLoader, epochs: int = 3) -> nn.Module:
    """Run a low-level PyTorch training loop — backward + step per batch."""
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = nn.CrossEntropyLoss()
    model.train()
    for _ in range(epochs):
        for batch in loader:
            x, y = batch
            optimizer.zero_grad()
            logits = model(x)
            loss = loss_fn(logits, y)
            loss.backward()
            optimizer.step()
    return model


def fit_sklearn(features: list[list[float]], labels: list[int]) -> LogisticRegression:
    """Train a sklearn classifier via the standard ``estimator.fit`` API."""
    clf = LogisticRegression(max_iter=200)
    clf.fit(features, labels)
    return clf


@hydra.main(config_path="conf", config_name="train", version_base=None)
def main(cfg: Any) -> None:
    """Hydra-driven training entry point — config drives the experiment."""
    model = TinyNet()
    loader: DataLoader = cfg.data.loader
    train(model, loader, epochs=cfg.train.epochs)
