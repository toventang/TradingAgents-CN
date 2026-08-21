import pytest
from app.services.strategies.validator import StrategyDSLValidator, DSLValidationError


def test_validator_valid_spec():
    validator = StrategyDSLValidator()
    spec = {
        "weights": {"ret_1d": 0.5, "ret_5d": -0.5},
        "conditions": {
            "op": "AND",
            "children": [
                {"op": ">", "factor_id": "ret_1d", "value": 0.01},
                {"op": "between", "factor_id": "ret_5d", "value": [-0.05, 0.05]}
            ]
        },
        "rules": {"top_k": 5}
    }
    factors = validator.validate_strategy_spec(spec)
    assert factors == {"ret_1d", "ret_5d"}


def test_validator_unregistered_factor():
    validator = StrategyDSLValidator()
    spec = {
        "weights": {"unknown_factor_123": 1.0}
    }
    with pytest.raises(DSLValidationError) as exc:
        validator.validate_strategy_spec(spec)
    assert "not registered" in str(exc.value)


def test_validator_depth_limit():
    validator = StrategyDSLValidator(max_depth=2)
    # Depth = 3: AND -> OR -> node
    spec = {
        "conditions": {
            "op": "AND",
            "children": [
                {
                    "op": "OR",
                    "children": [
                        {"op": ">", "factor_id": "ret_1d", "value": 0.01}
                    ]
                }
            ]
        }
    }
    with pytest.raises(DSLValidationError) as exc:
        validator.validate_strategy_spec(spec)
    assert "depth" in str(exc.value)


def test_validator_impossible_between():
    validator = StrategyDSLValidator()
    spec = {
        "conditions": {
            "op": "between", "factor_id": "ret_5d", "value": [0.05, -0.05]
        }
    }
    with pytest.raises(DSLValidationError) as exc:
        validator.validate_strategy_spec(spec)
    assert "Impossible condition" in str(exc.value)
