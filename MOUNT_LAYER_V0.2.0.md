# Concord v0.2.0: Mount Abstraction Layer

**Date**: October 21, 2025  
**Version**: 0.2.0 (upgraded from 0.1.0)  
**Status**: ✅ Implemented and Tested

---

## Summary

Concord v0.2.0 adds a **mount abstraction layer** that provides proper directory structure and semantic guarantees for agent coordination. This layer creates standardized mount points with all necessary directories (`inbox/`, `outbox/`, `fs/`, `locks/`, `caps/`, `policy/`, `stats/`), making agent setup trivial.

---

## What Was Added

### 1. Mount Manager (`mount.py`)

A simplified mount management system that:
- Creates agent mount points with standard directory structure
- Manages multiple agents with centralized cleanup
- Provides convenience functions for mount/unmount operations
- Works on all platforms without special dependencies

**Key Classes:**
- `AgentMount`: Represents a single agent mount point
- `MountManager`: Manages multiple agent mounts
- Helper functions: `mount_agent()`, `unmount_agent()`, `list_agents()`

### 2. Optional FUSE Layer (`fusemount.py`)

A true FUSE filesystem implementation that:
- Provides virtual filesystem semantics
- Implements all POSIX file operations (read, write, rename, etc.)
- Backed by real directories for persistence
- Requires `fusepy` + macFUSE/FUSE (optional dependency)

**Key Class:**
- `ConcordFS`: FUSE filesystem operations
- Functions: `mount_agent()` (FUSE version), `unmount_agent()`

---

## Directory Structure

Each agent mount provides:

```
<agent-name>/
├── inbox/              # Intent files (JSON)
├── outbox/             # Event log (events.jsonl)
├── fs/                 # Artifact storage
├── locks/              # Lease files
├── caps/               # Capability manifests
│   └── manifest.json   # Default capability manifest
├── policy/             # Policy files (no_network, max_tokens, etc.)
└── stats/              # Runtime statistics
    └── runtime.json    # Default stats file
```

---

## Usage Examples

### Basic Mount Manager

```python
import concord

# Create a mount for an agent
mount = concord.mount_agent('my-agent')

# Access mount directories
print(mount.inbox)       # /tmp/concord/my-agent/inbox
print(mount.outbox)      # /tmp/concord/my-agent/outbox
print(mount.policy)      # /tmp/concord/my-agent/policy

# Verify mount structure
assert mount.verify()

# Clean up
concord.unmount_agent('my-agent')
```

### Multiple Agents

```python
import concord

# Get mount manager
manager = concord.get_mount_manager(base_path='/tmp/my-agents')

# Create multiple mounts
agent1 = manager.create_mount('agent-1')
agent2 = manager.create_mount('agent-2')
agent3 = manager.create_mount('agent-3')

# List all agents
agents = manager.list_mounts()
print(f"Mounted agents: {agents}")

# Clean up all at once
manager.cleanup_all()
```

### Integration with Agent

```python
import concord

# Create mount
mount = concord.mount_agent('demo-agent', base_path='/tmp/concord')

# Create agent (it will use the mount directories)
agent = concord.Agent(name='demo-agent', base_path='/tmp/concord')

# Agent automatically uses:
# - /tmp/concord/demo-agent/inbox/
# - /tmp/concord/demo-agent/outbox/
# - /tmp/concord/demo-agent/outbox/events.jsonl
```

### Optional FUSE Layer

```python
import concord

if concord.FUSE_AVAILABLE:
    # Use true FUSE filesystem
    from concord import ConcordFS
    # ... FUSE-specific operations
else:
    # Fall back to simplified mount manager
    mount = concord.mount_agent('my-agent')
```

---

## Testing

### Run Mount Tests

```bash
cd sdk/examples
python3 test_mount.py
```

**Tests include:**
- ✅ Mount creation with standard directories
- ✅ Default configuration files (caps, policy, stats)
- ✅ Intent write with atomic rename
- ✅ Event log append
- ✅ Tombstone creation
- ✅ Policy file creation
- ✅ Mount verification
- ✅ Multiple agent management
- ✅ Integration with Agent class

### Run FUSE Tests (Optional)

```bash
cd sdk/examples
python3 test_fusemount.py
```

**Note**: Requires `fusepy` and macFUSE/FUSE installed on the system.

---

## Benefits

### 1. **Standardized Structure**
Every agent mount has the same directory layout, making tooling and automation straightforward.

### 2. **Semantic Guarantees**
- Default capability manifests
- Default policy files
- Default stats tracking
- Proper directory permissions

### 3. **Easy Cleanup**
Centralized mount management makes it easy to clean up test environments and temporary agents.

### 4. **Platform Independence**
The simplified mount manager works on all platforms. FUSE is optional for specialized use cases.

### 5. **Observable by Default**
All mount state is filesystem-visible:
```bash
ls /tmp/concord/my-agent/inbox/     # See pending intents
tail -f /tmp/concord/my-agent/outbox/events.jsonl  # Watch events
cat /tmp/concord/my-agent/policy/no_network         # Check policy
```

---

## Technical Details

### Mount Manager Implementation

The simplified mount manager:
- Uses standard Python `pathlib` for filesystem operations
- Creates directories with `mkdir(parents=True, exist_ok=True)`
- Writes default JSON files for caps/policy/stats
- Provides property accessors for all subdirectories
- Manages cleanup via `shutil.rmtree()`

### FUSE Implementation

The FUSE layer:
- Extends `fuse.Operations` from `fusepy`
- Implements all required FUSE operations (getattr, readdir, open, read, write, etc.)
- Uses a backend directory for actual file storage
- Provides true virtual filesystem semantics
- Supports extended attributes for policy enforcement

### Compatibility

| Platform | Mount Manager | FUSE Layer |
|----------|---------------|------------|
| Linux | ✅ Yes | ✅ Yes (requires FUSE) |
| macOS | ✅ Yes | ✅ Yes (requires macFUSE) |
| Windows | ✅ Yes | ⚠️ Requires WinFSP |

---

## Dependencies

### Core Dependencies (Always)
- `pathlib` (stdlib)
- `json` (stdlib)
- `shutil` (stdlib)

### Optional Dependencies (FUSE Layer)
- `fusepy>=3.0.1`
- macFUSE (macOS) or FUSE (Linux)
- WinFSP (Windows)

Install FUSE dependencies:
```bash
pip install fusepy
```

---

## Version History

### v0.2.0 (October 21, 2025)
- ✅ Added `MountManager` and `AgentMount` classes
- ✅ Added optional FUSE layer (`ConcordFS`)
- ✅ Added `mount_agent()`, `unmount_agent()`, `list_agents()` functions
- ✅ Added default configuration files (caps, policy, stats)
- ✅ Added comprehensive mount tests
- ✅ Updated requirements.txt with fusepy
- ✅ Updated SDK exports

### v0.1.0 (October 20, 2025)
- Initial release with basic Agent, CAS, and Orchestrator

---

## Future Enhancements (v0.3.0)

Potential improvements for the mount layer:

1. **Mount Options**: Configurable directory sets, custom subdirectories
2. **Mount Permissions**: Fine-grained access control per agent
3. **Mount Quotas**: Storage limits per agent mount
4. **Mount Monitoring**: Real-time stats on mount usage
5. **Network Mounts**: 9P or SSHFS for remote agent coordination
6. **Hot Reload**: Dynamic mount updates without agent restart
7. **Snapshotting**: Capture mount state for debugging/replay

---

## Testing Results

```
============================================================
Concord Mount Manager Test
============================================================

=== Testing Concord Mount Manager v0.2.0 ===

[1] Creating agent mount...                    ✓
[2] Verifying standard directories...          ✓
[3] Checking default configuration files...    ✓
[4] Writing intent to inbox...                 ✓
[5] Reading intent from inbox...               ✓
[6] Appending to event log...                  ✓
[7] Creating tombstone...                      ✓
[8] Writing policy file...                     ✓
[9] Verifying mount integrity...               ✓
[10] Creating multiple mounts...               ✓
[11] Cleaning up mounts...                     ✓

✅ All mount manager tests passed!

=== Testing Mount with Agent ===

[1] Created mount                              ✓
[2] Creating agent                             ✓
[3] Verifying agent can access mount           ✓
[4] Writing intent for agent                   ✓
[5] Agent reading intent                       ✓
[6] Cleaned up mount                           ✓

✅ Agent + Mount integration tests passed!

RESULT: ✅ All mount tests passed!
============================================================
```

---

## Documentation

- **API Reference**: See docstrings in `sdk/python/concord/mount.py`
- **FUSE Reference**: See docstrings in `sdk/python/concord/fusemount.py`
- **Usage Examples**: See `sdk/examples/test_mount.py`
- **Integration**: See multi-agent examples in `sdk/examples/multiagent/`

---

## Conclusion

The mount abstraction layer in v0.2.0 provides a clean, standardized way to create and manage agent filesystems. It simplifies agent setup, ensures consistent structure, and makes coordination state observable by default---all core principles of Concord's filesystem-native approach.

**Status**: ✅ **Fully Implemented and Tested**  
**Ready for**: Production use in multi-agent systems

