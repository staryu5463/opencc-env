"""
治理与避坑模块
"""

from opencc_env.remediation.cache_cleaner import CacheCleaner
from opencc_env.remediation.startup_fixer import StartupFixer
from opencc_env.remediation.guides import ExpertGuideManager, EXPERT_GUIDES

__all__ = [
    "CacheCleaner",
    "StartupFixer",
    "ExpertGuideManager",
    "EXPERT_GUIDES"
]

