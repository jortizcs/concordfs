#!/usr/bin/env python3
"""
Test script for Concord Mount Manager

Tests the mount abstraction layer that provides proper
directory structure for agent coordination.
"""

import sys
import json
import time
from pathlib import Path
import tempfile

# Add SDK to path
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

import concord


def test_mount_manager():
    """Test mount manager functionality"""
    
    print(f"\n=== Testing Concord Mount Manager v{concord.__version__} ===\n")
    
    # Use temporary directory
    with tempfile.TemporaryDirectory(prefix='concord-test-') as tmpdir:
        print(f"Test directory: {tmpdir}\n")
        
        # Test 1: Create a mount
        print("[1] Creating agent mount...")
        mount = concord.mount_agent('test-agent', base_path=tmpdir)
        print(f"    Mount point: {mount.mount_point}")
        assert mount.mount_point.exists(), "Mount point not created"
        print("    ✓ Mount created")
        
        # Test 2: Check standard directories
        print("\n[2] Verifying standard directories...")
        for subdir in mount.subdirs:
            dir_path = mount.mount_point / subdir
            assert dir_path.exists(), f"Missing directory: {subdir}"
            assert dir_path.is_dir(), f"Not a directory: {subdir}"
            print(f"    ✓ {subdir}/")
        
        # Test 3: Check default files
        print("\n[3] Checking default configuration files...")
        caps_file = mount.caps / "manifest.json"
        assert caps_file.exists(), "Capability manifest not created"
        caps = json.loads(caps_file.read_text())
        assert caps['agent'] == 'test-agent', "Incorrect agent name in manifest"
        print(f"    ✓ caps/manifest.json (agent: {caps['agent']})")
        
        stats_file = mount.stats / "runtime.json"
        assert stats_file.exists(), "Stats file not created"
        print(f"    ✓ stats/runtime.json")
        
        # Test 4: Write intent
        print("\n[4] Writing intent to inbox...")
        intent_id = "test-intent-001"
        intent_data = {
            "id": intent_id,
            "op": "test_operation",
            "args": {"key": "value"},
            "t0": time.time()
        }
        
        # Atomic write with temp + rename
        tmp_file = mount.inbox / f".tmp-{intent_id}.json"
        final_file = mount.inbox / f"{intent_id}.json"
        
        tmp_file.write_text(json.dumps(intent_data, indent=2))
        tmp_file.rename(final_file)
        
        assert final_file.exists(), "Intent file not created"
        print(f"    ✓ Intent written: {intent_id}.json")
        
        # Test 5: Read intent back
        print("\n[5] Reading intent from inbox...")
        read_data = json.loads(final_file.read_text())
        assert read_data == intent_data, "Intent data mismatch"
        print(f"    ✓ Intent read successfully")
        print(f"      op: {read_data['op']}")
        
        # Test 6: Append to event log
        print("\n[6] Appending to event log...")
        events_file = mount.outbox / "events.jsonl"
        
        for i in range(3):
            event = {
                "id": f"event-{i}",
                "event": "test_event",
                "timestamp": time.time(),
                "data": f"test-data-{i}"
            }
            with open(events_file, "a") as f:
                f.write(json.dumps(event) + "\n")
        
        # Verify events
        lines = events_file.read_text().strip().split('\n')
        assert len(lines) == 3, f"Expected 3 events, got {len(lines)}"
        print(f"    ✓ {len(lines)} events appended")
        
        # Test 7: Create tombstone
        print("\n[7] Creating tombstone...")
        done_file = mount.inbox / f"{intent_id}.json.done"
        done_file.write_text(json.dumps({"processed_at": time.time()}))
        assert done_file.exists(), "Tombstone not created"
        print(f"    ✓ Tombstone created: {done_file.name}")
        
        # Test 8: Policy file
        print("\n[8] Writing policy file...")
        policy_file = mount.policy / "no_network"
        policy_file.write_text("true")
        assert policy_file.exists(), "Policy file not created"
        print(f"    ✓ Policy file created: {policy_file.name}")
        
        # Test 9: Mount verification
        print("\n[9] Verifying mount integrity...")
        assert mount.verify(), "Mount verification failed"
        print(f"    ✓ Mount structure intact")
        
        # Test 10: Multiple mounts
        print("\n[10] Creating multiple mounts...")
        manager = concord.get_mount_manager(base_path=tmpdir)
        
        mount2 = manager.create_mount('agent-2')
        mount3 = manager.create_mount('agent-3')
        
        agents = manager.list_mounts()
        assert len(agents) == 3, f"Expected 3 agents, got {len(agents)}"
        assert 'test-agent' in agents, "test-agent not in list"
        assert 'agent-2' in agents, "agent-2 not in list"
        assert 'agent-3' in agents, "agent-3 not in list"
        
        print(f"    ✓ {len(agents)} agents mounted: {agents}")
        
        # Test 11: Mount cleanup
        print("\n[11] Cleaning up mounts...")
        manager.cleanup_all()
        remaining = manager.list_mounts()
        assert len(remaining) == 0, f"Expected 0 agents, got {len(remaining)}"
        print(f"    ✓ All mounts cleaned up")
        
        print("\n✅ All mount manager tests passed!")
        return True


def test_mount_with_agent():
    """Test mount with actual agent"""
    
    print(f"\n=== Testing Mount with Agent ===\n")
    
    with tempfile.TemporaryDirectory(prefix='concord-agent-test-') as tmpdir:
        # Create mount
        mount = concord.mount_agent('demo-agent', base_path=tmpdir)
        print(f"[1] Created mount: {mount.mount_point}")
        
        # Create agent using the mount
        # Note: Agent expects base_path + name, so we pass the parent directory
        print(f"\n[2] Creating agent...")
        agent = concord.Agent(
            name='demo-agent',
            base_path=tmpdir
        )
        print(f"    ✓ Agent created")
        print(f"    Inbox: {agent.inbox}")
        print(f"    Outbox: {agent.outbox}")
        
        # Verify agent can see mount directories
        print(f"\n[3] Verifying agent can access mount...")
        assert agent.inbox.exists(), "Agent cannot see inbox"
        assert agent.outbox.exists(), "Agent cannot see outbox"
        print(f"    ✓ Agent can access mount directories")
        
        # Write intent for agent
        print(f"\n[4] Writing intent for agent...")
        intent_file = mount.inbox / "test-intent.json"
        intent_data = {
            "id": "test-intent",
            "op": "echo",
            "args": {"message": "Hello from mount!"},
            "t0": time.time()
        }
        intent_file.write_text(json.dumps(intent_data, indent=2))
        print(f"    ✓ Intent written")
        
        # Agent should be able to read it
        print(f"\n[5] Agent reading intent...")
        intent_obj = concord.Intent.from_file(intent_file)
        assert intent_obj.id == "test-intent", "Intent ID mismatch"
        assert intent_obj.op == "echo", "Intent operation mismatch"
        print(f"    ✓ Agent read intent: {intent_obj.op}")
        
        # Cleanup
        concord.unmount_agent('demo-agent', base_path=tmpdir)
        print(f"\n[6] Cleaned up mount")
        
        print("\n✅ Agent + Mount integration tests passed!")
        return True


def main():
    """Run mount tests"""
    print("=" * 60)
    print("Concord Mount Manager Test")
    print("=" * 60)
    
    try:
        # Test basic mount manager
        success1 = test_mount_manager()
        
        # Test mount with agent
        success2 = test_mount_with_agent()
        
        success = success1 and success2
        
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        success = False
    
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        success = False
    
    print("\n" + "=" * 60)
    if success:
        print("RESULT: ✅ All mount tests passed!")
        if concord.FUSE_AVAILABLE:
            print("\nNote: FUSE layer is available but not tested here.")
            print("      FUSE provides true virtual filesystem semantics.")
            print("      Run test_fusemount.py for FUSE-specific tests.")
        else:
            print("\nNote: FUSE layer not available (requires fusepy).")
            print("      Using simplified mount manager instead.")
    else:
        print("RESULT: ✗ Mount tests failed")
    print("=" * 60)
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())

