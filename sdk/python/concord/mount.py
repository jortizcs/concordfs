"""
Concord Mount Manager

Provides a filesystem abstraction layer for agent coordination.
Creates and manages agent mount points with proper directory structure.

Note: This is a simplified mount manager. For production deployments,
consider using the FUSE-based ConcordFS (fusemount.py) which provides
true virtual filesystem semantics.
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Optional


class AgentMount:
    """
    An agent mount point with standard directory structure.
    
    Structure:
        <mount_point>/
            inbox/          - Intent files (JSON)
            outbox/         - Event log (events.jsonl)
            fs/             - Artifact storage
            locks/          - Lease files
            caps/           - Capability manifests
            policy/         - Policy files
            stats/          - Runtime statistics
    """
    
    def __init__(self, mount_point: str, agent_name: str):
        """
        Initialize an agent mount.
        
        Args:
            mount_point: Directory path for the mount
            agent_name: Name of the agent (for logging/identification)
        """
        self.mount_point = Path(mount_point)
        self.agent_name = agent_name
        
        # Standard subdirectories
        self.subdirs = ['inbox', 'outbox', 'fs', 'locks', 'caps', 'policy', 'stats']
        
        # Create mount structure
        self._initialize()
    
    def _initialize(self):
        """Create mount point and standard directories"""
        # Create base mount point
        self.mount_point.mkdir(parents=True, exist_ok=True)
        
        # Create standard subdirectories
        for subdir in self.subdirs:
            (self.mount_point / subdir).mkdir(exist_ok=True)
        
        # Create default files
        self._create_defaults()
    
    def _create_defaults(self):
        """Create default configuration files"""
        # Default capability manifest
        caps_file = self.mount_point / "caps" / "manifest.json"
        if not caps_file.exists():
            default_caps = {
                "agent": self.agent_name,
                "capabilities": [],
                "version": "0.2.0"
            }
            caps_file.write_text(json.dumps(default_caps, indent=2))
        
        # Default stats file
        stats_file = self.mount_point / "stats" / "runtime.json"
        if not stats_file.exists():
            default_stats = {
                "agent": self.agent_name,
                "started_at": None,
                "intents_processed": 0,
                "events_emitted": 0
            }
            stats_file.write_text(json.dumps(default_stats, indent=2))
    
    @property
    def inbox(self) -> Path:
        """Path to inbox directory"""
        return self.mount_point / "inbox"
    
    @property
    def outbox(self) -> Path:
        """Path to outbox directory"""
        return self.mount_point / "outbox"
    
    @property
    def fs(self) -> Path:
        """Path to filesystem storage"""
        return self.mount_point / "fs"
    
    @property
    def locks(self) -> Path:
        """Path to locks directory"""
        return self.mount_point / "locks"
    
    @property
    def caps(self) -> Path:
        """Path to capabilities directory"""
        return self.mount_point / "caps"
    
    @property
    def policy(self) -> Path:
        """Path to policy directory"""
        return self.mount_point / "policy"
    
    @property
    def stats(self) -> Path:
        """Path to stats directory"""
        return self.mount_point / "stats"
    
    def verify(self) -> bool:
        """Verify mount structure is intact"""
        for subdir in self.subdirs:
            if not (self.mount_point / subdir).exists():
                return False
        return True
    
    def cleanup(self):
        """Remove mount point (for testing/cleanup)"""
        import shutil
        if self.mount_point.exists():
            shutil.rmtree(self.mount_point)


class MountManager:
    """
    Manages multiple agent mounts.
    
    Provides centralized management of agent mount points,
    ensuring consistent structure and easy cleanup.
    """
    
    def __init__(self, base_path: str = "/tmp/concord"):
        """
        Initialize mount manager.
        
        Args:
            base_path: Base directory for all agent mounts
        """
        self.base_path = Path(base_path)
        self.mounts: Dict[str, AgentMount] = {}
    
    def create_mount(self, agent_name: str, mount_point: Optional[str] = None) -> AgentMount:
        """
        Create an agent mount.
        
        Args:
            agent_name: Name of the agent
            mount_point: Optional custom mount point (default: <base_path>/<agent_name>)
        
        Returns:
            AgentMount instance
        """
        if mount_point is None:
            mount_point = str(self.base_path / agent_name)
        
        mount = AgentMount(mount_point, agent_name)
        self.mounts[agent_name] = mount
        
        return mount
    
    def get_mount(self, agent_name: str) -> Optional[AgentMount]:
        """Get an existing mount by agent name"""
        return self.mounts.get(agent_name)
    
    def list_mounts(self) -> List[str]:
        """List all managed agent names"""
        return list(self.mounts.keys())
    
    def remove_mount(self, agent_name: str):
        """Remove an agent mount"""
        if agent_name in self.mounts:
            mount = self.mounts[agent_name]
            mount.cleanup()
            del self.mounts[agent_name]
    
    def cleanup_all(self):
        """Remove all managed mounts"""
        for agent_name in list(self.mounts.keys()):
            self.remove_mount(agent_name)


# Global mount manager instance
_mount_manager = None

def get_mount_manager(base_path: str = "/tmp/concord") -> MountManager:
    """Get or create global mount manager"""
    global _mount_manager
    if _mount_manager is None:
        _mount_manager = MountManager(base_path)
    return _mount_manager


# Convenience functions
def mount_agent(agent_name: str, mount_point: Optional[str] = None, base_path: str = "/tmp/concord") -> AgentMount:
    """
    Mount an agent at the specified location.
    
    Args:
        agent_name: Name of the agent
        mount_point: Optional custom mount point
        base_path: Base path for mounts if mount_point not specified
    
    Returns:
        AgentMount instance
    """
    manager = get_mount_manager(base_path)
    return manager.create_mount(agent_name, mount_point)


def unmount_agent(agent_name: str, base_path: str = "/tmp/concord"):
    """
    Unmount an agent.
    
    Args:
        agent_name: Name of the agent to unmount
        base_path: Base path where mounts are located
    """
    manager = get_mount_manager(base_path)
    manager.remove_mount(agent_name)


def list_agents(base_path: str = "/tmp/concord") -> List[str]:
    """
    List all mounted agents.
    
    Args:
        base_path: Base path where mounts are located
    
    Returns:
        List of agent names
    """
    manager = get_mount_manager(base_path)
    return manager.list_mounts()


if __name__ == '__main__':
    """Simple test"""
    import tempfile
    
    with tempfile.TemporaryDirectory(prefix='concord-test-') as tmpdir:
        # Create a mount
        mount = mount_agent('test-agent', base_path=tmpdir)
        
        print(f"Created mount at: {mount.mount_point}")
        print(f"Subdirectories:")
        for subdir in mount.subdirs:
            print(f"  ✓ {subdir}/")
        
        # Verify
        assert mount.verify(), "Mount verification failed"
        print("\n✅ Mount structure verified")
        
        # Cleanup
        unmount_agent('test-agent', base_path=tmpdir)
        print("✅ Mount cleaned up")

