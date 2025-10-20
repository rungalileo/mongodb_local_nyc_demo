"""
Toggle manager for failure injection and configuration

Provides configurable toggles for testing different failure scenarios.
"""

import os
from typing import Dict, Any


class ToggleManager:
    """Toggle manager for failure injection scenarios"""
    
    def __init__(self):
        self.policy_force_old_version = os.getenv("POLICY_FORCE_OLD_VERSION", "false").lower() == "true"
        self.refund_api_error_rate = float(os.getenv("REFUND_API_ERROR_RATE", "0.0"))
        
    
    def get_toggle(self, name: str, default: Any = None) -> Any:
        """Get a toggle value by name"""
        return getattr(self, name, default)
    
    def set_toggle(self, name: str, value: Any):
        """Set a toggle value"""
        setattr(self, name, value)
    
    def get_all_toggles(self) -> Dict[str, Any]:
        """Get all toggle values as a dictionary"""
        return {
            "policy_force_old_version": self.policy_force_old_version,
            "refund_api_error_rate": self.refund_api_error_rate
        }


# Global instance
_toggle_manager = None


def get_toggle_manager() -> ToggleManager:
    """Get the global toggle manager instance"""
    global _toggle_manager
    if _toggle_manager is None:
        _toggle_manager = ToggleManager()
    return _toggle_manager


def get_toggle(name: str, default: Any = None) -> Any:
    """Convenience function to get a toggle value"""
    return get_toggle_manager().get_toggle(name, default)
