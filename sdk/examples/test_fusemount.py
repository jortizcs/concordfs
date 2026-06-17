#!/usr/bin/env python3
"""
Test script for ConcordFS FUSE mount layer

This script:
1. Installs fusepy if needed
2. Creates a FUSE mount for an agent
3. Runs basic filesystem operations through the mount
4. Verifies that operations work correctly
5. Unmounts and cleans up
"""

import sys
import json
import time
import subprocess
from pathlib import Path
import tempfile
import threading

# Add SDK to path
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

def install_fusepy():
    """Install fusepy if not available"""
    try:
        import fuse
        print("✓ fusepy already installed")
        return True
    except ImportError:
        print("Installing fusepy...")
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "fusepy"],
                check=True,
                capture_output=True
            )
            print("✓ fusepy installed successfully")
            return True
        except subprocess.CalledProcessError as e:
            print(f"✗ Failed to install fusepy: {e}")
            return False


def test_fuse_mount():
    """Test FUSE mount functionality"""
    
    # Check/install fusepy
    if not install_fusepy():
        print("\nERROR: Could not install fusepy. Skipping FUSE test.")
        return False
    
    # Import after installation
    import concord
    from concord.fusemount import mount_agent
    
    if not concord.FUSE_AVAILABLE:
        print("\nERROR: FUSE not available after installation")
        return False
    
    print(f"\n=== Testing ConcordFS v{concord.__version__} ===\n")
    
    # Create temporary directories
    with tempfile.TemporaryDirectory(prefix='concord-backend-') as backend_dir, \
         tempfile.TemporaryDirectory(prefix='concord-mount-') as mount_dir:
        
        backend = Path(backend_dir)
        mount = Path(mount_dir)
        
        print(f"Backend:     {backend}")
        print(f"Mount point: {mount}\n")
        
        # Store exception from mount thread
        mount_exception = []
        
        def mount_wrapper():
            try:
                mount_agent('test-agent', str(backend), str(mount), foreground=True)
            except Exception as e:
                mount_exception.append(e)
                import traceback
                print(f"\n✗ Mount error: {e}")
                traceback.print_exc()
        
        # Mount in background thread
        mount_thread = threading.Thread(
            target=mount_wrapper,
            daemon=True
        )
        
        print("[1] Mounting ConcordFS...")
        mount_thread.start()
        
        # Wait for mount to be ready
        print("    Waiting for mount to be ready...")
        time.sleep(3)
        
        # Check if mount failed
        if mount_exception:
            print(f"\n✗ Mount failed with error: {mount_exception[0]}")
            return False
        
        # Check if mount is actually mounted
        try:
            subprocess.run(['mount'], capture_output=True, text=True, check=True)
        except:
            pass
        
        try:
            # Test 1: Check standard directories exist
            print("[2] Checking standard directories...")
            
            # First check if mount point itself is accessible
            if not mount.exists():
                raise AssertionError(f"Mount point not accessible: {mount}")
            
            # List what's actually in the mount point
            try:
                contents = list(mount.iterdir())
                print(f"    Mount point contains: {[f.name for f in contents]}")
            except Exception as e:
                print(f"    Could not list mount point: {e}")
                # Check backend instead
                print(f"    Checking backend directory...")
                backend_contents = list(backend.iterdir())
                print(f"    Backend contains: {[f.name for f in backend_contents]}")
                raise AssertionError(f"Mount point not responding properly")
            
            for subdir in ['inbox', 'outbox', 'fs', 'locks', 'caps', 'policy']:
                dir_path = mount / subdir
                if not dir_path.exists():
                    raise AssertionError(f"Missing directory: {subdir}")
                if not dir_path.is_dir():
                    raise AssertionError(f"Not a directory: {subdir}")
                print(f"    ✓ {subdir}/")
            
            # Test 2: Write intent to inbox
            print("\n[3] Writing intent to inbox...")
            intent_id = "test-intent-001"
            intent_data = {
                "id": intent_id,
                "op": "test_operation",
                "args": {"key": "value"},
                "t0": time.time()
            }
            
            # Atomic write with temp + rename
            tmp_file = mount / "inbox" / f".tmp-{intent_id}.json"
            final_file = mount / "inbox" / f"{intent_id}.json"
            
            tmp_file.write_text(json.dumps(intent_data, indent=2))
            tmp_file.rename(final_file)
            
            assert final_file.exists(), "Intent file not created"
            print(f"    ✓ Intent written: {intent_id}.json")
            
            # Test 3: Read intent back
            print("\n[4] Reading intent from inbox...")
            read_data = json.loads(final_file.read_text())
            assert read_data == intent_data, "Intent data mismatch"
            print(f"    ✓ Intent read successfully")
            print(f"      op: {read_data['op']}")
            
            # Test 4: Append to event log
            print("\n[5] Appending to event log...")
            events_file = mount / "outbox" / "events.jsonl"
            
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
            
            # Test 5: Create tombstone
            print("\n[6] Creating tombstone...")
            done_file = mount / "inbox" / f"{intent_id}.json.done"
            done_file.write_text(json.dumps({"processed_at": time.time()}))
            assert done_file.exists(), "Tombstone not created"
            print(f"    ✓ Tombstone created: {done_file.name}")
            
            # Test 6: Policy file
            print("\n[7] Writing policy file...")
            policy_file = mount / "policy" / "no_network"
            policy_file.write_text("true")
            assert policy_file.exists(), "Policy file not created"
            print(f"    ✓ Policy file created: {policy_file.name}")
            
            # Test 7: List directory contents
            print("\n[8] Listing directory contents...")
            inbox_files = list((mount / "inbox").iterdir())
            print(f"    Inbox files: {len(inbox_files)}")
            for f in inbox_files:
                print(f"      - {f.name}")
            
            print("\n✅ All FUSE tests passed!")
            return True
            
        except AssertionError as e:
            print(f"\n✗ Test failed: {e}")
            return False
        
        except Exception as e:
            print(f"\n✗ Unexpected error: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        finally:
            # Unmount
            print("\n[9] Unmounting...")
            try:
                if sys.platform == 'darwin':
                    subprocess.run(['/sbin/umount', str(mount)], check=True, capture_output=True)
                else:
                    subprocess.run(['fusermount', '-u', str(mount)], check=True, capture_output=True)
                print("    ✓ Unmounted successfully")
            except subprocess.CalledProcessError:
                print("    ! Could not unmount (may require manual cleanup)")
            
            # Give mount thread time to exit
            time.sleep(1)


def main():
    """Run FUSE mount test"""
    print("=" * 60)
    print("Concord FUSE Mount Layer Test")
    print("=" * 60)
    
    success = test_fuse_mount()
    
    print("\n" + "=" * 60)
    if success:
        print("RESULT: ✅ FUSE mount layer working correctly")
    else:
        print("RESULT: ✗ FUSE mount layer test failed")
    print("=" * 60)
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())

