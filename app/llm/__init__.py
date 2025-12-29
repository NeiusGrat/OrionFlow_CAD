"""
LLM package - Centralized language model interface.

ONE client, ONE method: generate_feature_graph()
Provider-agnostic design for easy swapping.
"""
from .client import LLMClient

__all__ = ["LLMClient"]
