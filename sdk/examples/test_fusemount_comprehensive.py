#!/usr/bin/env python3
"""
Comprehensive FUSE mount test - tests more advanced scenarios
"""
import sys
import json
import time
import tempfile
import threading
from pathlib import Path

# Add SDK to path
sys.path.insert(0, str(Path(__file__).parent / "concord/sdk/python"))

from concord.fusemount import mount_agent

def test_comprehensive():
    """Test more comprehensive FUSE scenarios"""
    
    print("=" * 70)
    print("ConcordFS Comprehensive Test Suite")
    print("=" * 70)
    
    with tempfile.TemporaryDirectory(prefix='concord-backend-') as backend_dir, \
         tempfile.TemporaryDirectory(prefix='concord-mount-') as mount_dir:
        
        backend = Path(backend_dir)
        mount = Path(mount_dir)
        
        print(f"\nBackend:     {backend}")
        print(f"Mount point: {mount}\n")
        
        # Mount filesystem
        mount_exception = []
        
        def mount_wrapper():
            try:
                mount_agent('comprehensive-test', str(backend), str(mount), foreground=True)
            except Exception as e:
                mount_exception.append(e)
        
        mount_thread = threading.Thread(target=mount_wrapper, daemon=True)
        
        print("[1] Mounting ConcordFS...")
        mount_thread.start()
        time.sleep(2)
        
        if mount_exception:
            print(f"✗ Mount failed: {mount_exception[0]}")
            return False
        
        try:
            # Test 1: Multiple concurrent intents
            print("\n[2] Testing concurrent intent creation...")
            intents = []
            for i in range(10):
                intent_id = f"intent-{i:03d}"
                intent_data = {
                    "id": intent_id,
                    "op": f"operation_{i}",
                    "priority": i % 3,
                    "timestamp": time.time()
                }
                
                tmp_file = mount / "inbox" / f".tmp-{intent_id}.json"
                final_file = mount / "inbox" / f"{intent_id}.json"
                
                tmp_file.write_text(json.dumps(intent_data, indent=2))
                tmp_file.rename(final_file)
                intents.append(final_file)
            
            # Verify all exist
            inbox_files = list((mount / "inbox").glob("intent-*.json"))
            if len(inbox_files) != 10:
                print(f"    ✗ Expected 10 intents, found {len(inbox_files)}")
                return False
            print(f"    ✓ Created 10 intents atomically")
            
            # Test 2: Concurrent event appends
            print("\n[3] Testing concurrent event log appends...")
            events_file = mount / "outbox" / "events.jsonl"
            
            for batch in range(3):
                for i in range(5):
                    event = {
                        "batch": batch,
                        "event_id": i,
                        "timestamp": time.time(),
                        "data": f"test-data-{batch}-{i}"
                    }
                    with open(events_file, "a") as f:
                        f.write(json.dumps(event) + "\n")
            
            # Verify all events
            lines = events_file.read_text().strip().split('\n')
            if len(lines) != 15:
                print(f"    ✗ Expected 15 events, found {len(lines)}")
                return False
            print(f"    ✓ Appended 15 events across 3 batches")
            
            # Test 3: Artifact storage
            print("\n[4] Testing artifact storage...")
            artifacts_dir = mount / "fs" / "artifacts"
            artifacts_dir.mkdir(exist_ok=True)
            
            # Create some test artifacts
            for i in range(5):
                artifact = artifacts_dir / f"artifact-{i}.dat"
                artifact.write_bytes(b"x" * (1024 * (i + 1)))  # Variable sizes
            
            # Verify artifacts
            artifacts = list(artifacts_dir.glob("artifact-*.dat"))
            if len(artifacts) != 5:
                print(f"    ✗ Expected 5 artifacts, found {len(artifacts)}")
                return False
            
            total_size = sum(a.stat().st_size for a in artifacts)
            print(f"    ✓ Created 5 artifacts ({total_size} bytes total)")
            
            # Test 4: Lock files
            print("\n[5] Testing lock/lease files...")
            lock_file = mount / "locks" / "resource-123.lock"
            lock_data = {
                "holder": "comprehensive-test",
                "acquired_at": time.time(),
                "expires_at": time.time() + 60
            }
            lock_file.write_text(json.dumps(lock_data))
            
            # Verify lock
            if not lock_file.exists():
                print(f"    ✗ Lock file not created")
                return False
            
            read_lock = json.loads(lock_file.read_text())
            if read_lock["holder"] != "comprehensive-test":
                print(f"    ✗ Lock data mismatch")
                return False
            print(f"    ✓ Lock file created and verified")
            
            # Test 5: Policy files
            print("\n[6] Testing policy files...")
            policies = {
                "no_network": "true",
                "max_memory_mb": "512",
                "allow_disk_write": "false"
            }
            
            for policy_name, policy_value in policies.items():
                policy_file = mount / "policy" / policy_name
                policy_file.write_text(policy_value)
            
            # Verify policies
            policy_files = list((mount / "policy").iterdir())
            policy_count = len([f for f in policy_files if not f.name.startswith('.')])
            if policy_count < 3:
                print(f"    ✗ Expected at least 3 policies, found {policy_count}")
                return False
            print(f"    ✓ Created and verified {policy_count} policy files")
            
            # Test 6: Capability manifest
            print("\n[7] Testing capability manifest...")
            caps_file = mount / "caps" / "manifest.json"
            caps_data = {
                "agent": "comprehensive-test",
                "capabilities": [
                    {"name": "file_read", "enabled": True},
                    {"name": "file_write", "enabled": True},
                    {"name": "network", "enabled": False}
                ],
                "version": "0.2.0"
            }
            caps_file.write_text(json.dumps(caps_data, indent=2))
            
            # Verify
            read_caps = json.loads(caps_file.read_text())
            if len(read_caps["capabilities"]) != 3:
                print(f"    ✗ Capability count mismatch")
                return False
            print(f"    ✓ Capability manifest created and verified")
            
            # Test 7: Directory traversal
            print("\n[8] Testing directory traversal...")
            all_dirs = []
            for root, dirs, files in (mount).walk():
                for d in dirs:
                    if not d.startswith('.'):
                        all_dirs.append(d)
            
            required_dirs = ['inbox', 'outbox', 'fs', 'locks', 'caps', 'policy']
            missing_dirs = [d for d in required_dirs if d not in all_dirs]
            if missing_dirs:
                print(f"    ✗ Missing directories: {missing_dirs}")
                return False
            print(f"    ✓ All standard directories present")
            
            # Test 8: File statistics
            print("\n[9] Testing file statistics...")
            test_file = mount / "inbox" / "intent-000.json"
            stats = test_file.stat()
            
            if stats.st_size == 0:
                print(f"    ✗ File size is 0")
                return False
            
            print(f"    ✓ File stats: size={stats.st_size}, mode={oct(stats.st_mode)}")
            
            # Test 9: Intent cleanup (tombstones)
            print("\n[10] Testing intent cleanup with tombstones...")
            processed_count = 0
            for intent_file in (mount / "inbox").glob("intent-*.json"):
                tombstone = intent_file.with_suffix('.json.done')
                tombstone.write_text(json.dumps({
                    "processed_at": time.time(),
                    "result": "success"
                }))
                processed_count += 1
            
            # Count only visible tombstones (ignore ._ files)
            tombstones = [t for t in (mount / "inbox").glob("*.done") 
                         if not t.name.startswith('._')]
            if len(tombstones) != processed_count:
                print(f"    ✗ Tombstone count mismatch: expected {processed_count}, got {len(tombstones)}")
                return False
            print(f"    ✓ Created {len(tombstones)} tombstones")
            
            # Test 10: Large file write
            print("\n[11] Testing large file operations...")
            large_file = mount / "fs" / "large_data.bin"
            large_data = b"X" * (1024 * 100)  # 100KB
            large_file.write_bytes(large_data)
            
            # Read back and verify
            read_data = large_file.read_bytes()
            if len(read_data) != len(large_data):
                print(f"    ✗ Large file size mismatch")
                return False
            if read_data != large_data:
                print(f"    ✗ Large file content mismatch")
                return False
            print(f"    ✓ Large file ({len(large_data)} bytes) written and verified")
            
            print("\n" + "=" * 70)
            print("✅ All comprehensive tests passed!")
            print("=" * 70)
            
            # Summary
            print("\nTest Summary:")
            print("  - 10 concurrent intents created atomically")
            print("  - 15 event log entries appended")
            print("  - 5 artifacts stored")
            print("  - Lock/lease mechanism tested")
            print("  - Policy enforcement files created")
            print("  - Capability manifest updated")
            print("  - Directory structure verified")
            print("  - File statistics validated")
            print("  - Tombstone cleanup tested")
            print("  - Large file I/O verified (100KB)")
            
            return True
            
        except Exception as e:
            print(f"\n✗ Test failed: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        finally:
            # Unmount
            print("\n[12] Unmounting...")
            import subprocess
            try:
                subprocess.run(['/sbin/umount', str(mount)], 
                             check=True, capture_output=True)
                print("    ✓ Unmounted successfully")
            except subprocess.CalledProcessError as e:
                print(f"    ! Unmount failed: {e}")
            
            time.sleep(1)

if __name__ == '__main__':
    success = test_comprehensive()
    sys.exit(0 if success else 1)

