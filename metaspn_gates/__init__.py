"""Config-driven gate and state-machine evaluator for MetaSPN pipelines."""

from .models import (
    GateConfig,
    StateMachineConfig,
    GateDecision,
    TransitionApplied,
    TransitionAttempted,
    HardRequirement,
    SoftThreshold,
)
from .config import (
    ConfigError,
    load_state_machine_config,
    parse_state_machine_config,
    schemas_backend_available,
    schemas_contract_available,
)
from .evaluator import Evaluator, evaluate_gates
from .schemas import schemas_available
from .applier import apply_decisions
from .learning import (
    AttemptOutcomeEvaluation,
    CalibrationProposal,
    classify_failure_reason,
    evaluate_attempt_outcomes,
    generate_calibration_proposals,
)

__all__ = [
    "GateConfig",
    "StateMachineConfig",
    "GateDecision",
    "TransitionApplied",
    "TransitionAttempted",
    "HardRequirement",
    "SoftThreshold",
    "Evaluator",
    "evaluate_gates",
    "apply_decisions",
    "parse_state_machine_config",
    "load_state_machine_config",
    "schemas_backend_available",
    "schemas_contract_available",
    "schemas_available",
    "ConfigError",
    "AttemptOutcomeEvaluation",
    "CalibrationProposal",
    "classify_failure_reason",
    "evaluate_attempt_outcomes",
    "generate_calibration_proposals",
]
