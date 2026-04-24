"""Data Quality framework.

Quality checks run at three points:
    1. Ingestion (Pydantic): structural validation — types, required fields
    2. Transformation (declarative rules): business rules
    3. Post-load (Great Expectations): statistical properties, drift detection
"""
from src.data_quality.validators.rule_engine import DQResult, DQRule, run_rules

__all__ = ["DQResult", "DQRule", "run_rules"]
