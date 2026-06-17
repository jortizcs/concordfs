"""
Model router for Concord (v0.1.0 stub)

Will implement:
- cascade.json parsing
- Controller/doer selection
- llama.cpp integration
- Token budgeting
"""


class Router:
    """Model router daemon (stub for v0.1.0)"""
    
    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        
    def select_model(self, op: str) -> str:
        """Select model based on operation (stub)"""
        return "stub-model"

