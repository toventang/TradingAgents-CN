import pytest
import pandas as pd
import numpy as np
from pydantic import ValidationError
from app.models.factor import CompositeFactorSpec, AllowedTransform, MissingValuePolicy
from app.services.factors.composites import CompositeFactorService

def test_composite_factor_computation_and_contributions():
    service = CompositeFactorService()
    spec = CompositeFactorSpec(
        name="test_val_mom",
        description="Value + Momentum",
        base_factors=["ret_1d", "sma_5"],
        weights={"ret_1d": 0.6, "sma_5": 0.4},
        transforms=[AllowedTransform.ZSCORE]
    )

    df_matrix = pd.DataFrame({
        "ret_1d": [0.01, 0.02, -0.01, 0.03, 0.00],
        "sma_5": [10.0, 10.2, 10.1, 10.5, 10.3]
    })

    comp_s, contribs = service.compute_composite(spec, df_matrix)
    assert len(comp_s) == 5
    assert "ret_1d" in contribs
    assert "sma_5" in contribs

def test_unwhitelisted_transform_rejection():
    # Attempting unwhitelisted transform string fails Pydantic validation
    with pytest.raises(ValidationError):
        CompositeFactorSpec(
            name="malicious",
            base_factors=["ret_1d"],
            transforms=['__import__("os").system("ls")']
        )

def test_unknown_base_factor_rejection():
    service = CompositeFactorService()
    spec = CompositeFactorSpec(
        name="invalid_base",
        base_factors=["non_existent_factor_xyz"]
    )
    with pytest.raises(ValueError, match="Unknown base factor_id"):
        service.validate_spec(spec)
