"""
ConcordFS Python SDK for filesystem-native agent coordination.
"""

from .agent import Agent, Intent, Event
from .router import Router
from .cas import CASBus, get_cas_bus
from .orchestrator import PlanExecutor, Step
from .fsops import atomic_write_bytes, atomic_write_text, atomic_write_json
from .contract_probe import probe_storage_contract

# Mount manager (always available)
from .mount import (
    AgentMount, MountManager, get_mount_manager,
    mount_agent, unmount_agent, list_agents
)

# FUSE mount layer (optional, requires fusepy + macFUSE/FUSE)
try:
    from .fusemount import ConcordFS
    FUSE_AVAILABLE = True
except ImportError:
    FUSE_AVAILABLE = False
    ConcordFS = None

# LangGraph integration (optional, requires langgraph)
try:
    from .langgraph_saver import ConcordFSCheckpointSaver
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    ConcordFSCheckpointSaver = None

__version__ = "0.3.0"
__all__ = [
    # Core
    "Agent", "Intent", "Event", "Router",
    # Storage
    "CASBus", "get_cas_bus",
    # Orchestration
    "PlanExecutor", "Step",
    # Filesystem primitives
    "atomic_write_bytes", "atomic_write_text", "atomic_write_json",
    "probe_storage_contract",
    # Mount management
    "AgentMount", "MountManager", "get_mount_manager",
    "mount_agent", "unmount_agent", "list_agents",
    # FUSE (optional)
    "ConcordFS", "FUSE_AVAILABLE",
    # LangGraph (optional)
    "ConcordFSCheckpointSaver", "LANGGRAPH_AVAILABLE",
]

