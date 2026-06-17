#!/usr/bin/env python3
"""
Test ConcordFS functionality through backend directory

Since FUSE mounting on macOS can have permission issues,
this test validates the filesystem operations work correctly
by testing the backend directly.
"""
import sys
import json
import time
import tempfile
from pathlib import Path

# Add SDK to path
sys.path.insert(0, str(Path(__file__).parent / "concord/sdk/python"))

from concord.fusemount import ConcordFS

def test_concordfs_operations():
    """Test ConcordFS operations via backend"""
    
    print("=" * 60)
    print("ConcordFS Backend Operations Test")
    print("=" * 60)
    
    with tempfile.TemporaryDirectory(prefix='concord-test-') as tmpdir:
        backend = Path(tmpdir)
        
        print(f"\nBackend: {backend}\n")
        
        # Test 1: Initialize filesystem
        print("[1] Initializing ConcordFS...")
        fs = ConcordFS(str(backend))
        
        # Verify standard directories
        print("[2] Checking standard directories...")
        for subdir in ['inbox', 'outbox', 'fs', 'locks', 'caps', 'policy']:
            dir_path = backend / subdir
            if not dir_path.exists():
                print(f"    ✗ Missing: {subdir}/")
                return False
            print(f"    ✓ {subdir}/")
        
        # Test 2: Test getattr on directories
        print("\n[3] Testing getattr on directories...")
        for subdir in ['/', '/inbox', '/outbox']:
            try:
                attrs = fs.getattr(subdir)
                print(f"    ✓ getattr('{subdir}') -> mode={oct(attrs['st_mode'])}")
            except Exception as e:
                print(f"    ✗ getattr('{subdir}') failed: {e}")
                return False
        
        # Test 3: Test readdir
        print("\n[4] Testing readdir...")
        try:
            entries = fs.readdir('/', None)
            print(f"    Root entries: {entries}")
            if 'inbox' not in entries or 'outbox' not in entries:
                print("    ✗ Missing expected directories")
                return False
            print("    ✓ readdir working")
        except Exception as e:
            print(f"    ✗ readdir failed: {e}")
            return False
        
        # Test 4: Create a file
        print("\n[5] Testing file creation...")
        try:
            # Create a test file in inbox
            fh = fs.create('/inbox/test.json', 0o644)
            print(f"    ✓ create() returned fh={fh}")
            
            # Write to it
            test_data = json.dumps({"test": "data"}).encode('utf-8')
            bytes_written = fs.write('/inbox/test.json', test_data, 0, fh)
            print(f"    ✓ write() wrote {bytes_written} bytes")
            
            # Flush and close
            fs.flush('/inbox/test.json', fh)
            fs.release('/inbox/test.json', fh)
            print(f"    ✓ flush() and release()")
            
            # Verify file exists in backend
            test_file = backend / 'inbox' / 'test.json'
            if not test_file.exists():
                print(f"    ✗ File not found in backend")
                return False
            print(f"    ✓ File exists in backend: {test_file.name}")
            
        except Exception as e:
            print(f"    ✗ File operations failed: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        # Test 5: Read the file back
        print("\n[6] Testing file reading...")
        try:
            # Open for reading
            fh = fs.open('/inbox/test.json', os.O_RDONLY)
            print(f"    ✓ open() returned fh={fh}")
            
            # Get file size
            attrs = fs.getattr('/inbox/test.json')
            file_size = attrs['st_size']
            print(f"    ✓ File size: {file_size} bytes")
            
            # Read
            data = fs.read('/inbox/test.json', file_size, 0, fh)
            print(f"    ✓ read() returned {len(data)} bytes")
            
            # Verify content
            content = json.loads(data.decode('utf-8'))
            if content != {"test": "data"}:
                print(f"    ✗ Content mismatch: {content}")
                return False
            print(f"    ✓ Content verified: {content}")
            
            # Close
            fs.release('/inbox/test.json', fh)
            print(f"    ✓ release()")
            
        except Exception as e:
            print(f"    ✗ Read operations failed: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        # Test 6: Rename operation
        print("\n[7] Testing rename...")
        try:
            fs.rename('/inbox/test.json', '/inbox/test_renamed.json')
            
            # Verify old file gone
            if (backend / 'inbox' / 'test.json').exists():
                print(f"    ✗ Old file still exists")
                return False
            
            # Verify new file exists
            if not (backend / 'inbox' / 'test_renamed.json').exists():
                print(f"    ✗ New file not found")
                return False
            
            print(f"    ✓ Rename successful")
            
        except Exception as e:
            print(f"    ✗ Rename failed: {e}")
            return False
        
        # Test 7: Unlink (delete)
        print("\n[8] Testing unlink...")
        try:
            fs.unlink('/inbox/test_renamed.json')
            
            if (backend / 'inbox' / 'test_renamed.json').exists():
                print(f"    ✗ File still exists after unlink")
                return False
            
            print(f"    ✓ Unlink successful")
            
        except Exception as e:
            print(f"    ✗ Unlink failed: {e}")
            return False
        
        # Test 8: Append to event log
        print("\n[9] Testing append operations...")
        try:
            events_file = '/outbox/events.jsonl'
            
            for i in range(3):
                event = {"id": f"event-{i}", "timestamp": time.time()}
                event_data = (json.dumps(event) + "\n").encode('utf-8')
                
                # Open for append (or create if doesn't exist)
                try:
                    fh = fs.open(events_file, os.O_WRONLY | os.O_APPEND)
                except:
                    fh = fs.create(events_file, 0o644)
                
                # Get current size
                try:
                    attrs = fs.getattr(events_file)
                    offset = attrs['st_size']
                except:
                    offset = 0
                
                # Write at end
                fs.write(events_file, event_data, offset, fh)
                fs.flush(events_file, fh)
                fs.release(events_file, fh)
            
            # Verify
            backend_events = backend / 'outbox' / 'events.jsonl'
            lines = backend_events.read_text().strip().split('\n')
            if len(lines) != 3:
                print(f"    ✗ Expected 3 events, got {len(lines)}")
                return False
            
            print(f"    ✓ Appended 3 events successfully")
            
        except Exception as e:
            print(f"    ✗ Append operations failed: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        print("\n" + "=" * 60)
        print("✅ All ConcordFS operations working correctly!")
        print("=" * 60)
        return True

if __name__ == '__main__':
    import os  # Import os for O_RDONLY, etc.
    success = test_concordfs_operations()
    sys.exit(0 if success else 1)




