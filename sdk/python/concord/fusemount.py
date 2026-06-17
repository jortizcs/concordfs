"""
ConcordFS: FUSE-based agent mount layer

Provides a virtual filesystem interface for agent coordination.
Each mounted agent appears as a directory with inbox/, outbox/, fs/, locks/.

IMPORTANT - macOS Limitations:
    FUSE mounting on macOS requires macFUSE and has strict security restrictions.
    If FUSE mounting fails:
    1. Use the backend directory operations directly (ConcordFS class)
    2. Use the standard mount module (concord.mount) instead
    3. See FUSE_TEST_RESULTS.md for detailed workarounds
    
    All filesystem operations work correctly - the limitation is only in the
    mounting process on macOS due to platform security restrictions.
"""

import os
import sys
import json
import time
import errno
import stat
from pathlib import Path
from typing import Dict, Optional
from collections import defaultdict

try:
    from fuse import FUSE, FuseOSError, Operations, LoggingMixIn
except ImportError:
    print("ERROR: fusepy not installed. Install with: pip install fusepy", file=sys.stderr)
    sys.exit(1)


class ConcordFS(LoggingMixIn, Operations):
    """
    FUSE filesystem for agent coordination.
    
    Structure per agent mount:
        /inbox/          - Intents (JSON files)
        /outbox/         - Events (events.jsonl)
        /fs/             - Artifacts
        /locks/          - Lease files
        /caps/           - Capabilities
        /policy/         - Policy files
    """
    
    def __init__(self, backend_root: str):
        """
        Initialize ConcordFS with a backend directory.
        
        Args:
            backend_root: Real directory where files are stored
        """
        self.backend = Path(backend_root)
        self.backend.mkdir(parents=True, exist_ok=True)
        
        # Create standard directories
        for subdir in ['inbox', 'outbox', 'fs', 'locks', 'caps', 'policy']:
            (self.backend / subdir).mkdir(exist_ok=True)
        
        # File descriptors (for opened files)
        self.fd_counter = 0
        self.open_files: Dict[int, Dict] = {}
        
        print(f"[ConcordFS] Initialized with backend: {self.backend}")
    
    def _backend_path(self, path: str) -> Path:
        """Convert FUSE path to backend path"""
        # Remove leading slash
        rel_path = path.lstrip('/')
        return self.backend / rel_path if rel_path else self.backend
    
    # Filesystem metadata
    def getattr(self, path, fh=None):
        """Get file/directory attributes"""
        backend_path = self._backend_path(path)
        
        try:
            st = os.lstat(backend_path)
            return {
                'st_mode': st.st_mode,
                'st_nlink': st.st_nlink,
                'st_size': st.st_size,
                'st_ctime': st.st_ctime,
                'st_mtime': st.st_mtime,
                'st_atime': st.st_atime,
                'st_uid': st.st_uid,
                'st_gid': st.st_gid,
            }
        except FileNotFoundError:
            raise FuseOSError(errno.ENOENT)
    
    # Directory operations
    def readdir(self, path, fh):
        """List directory contents"""
        backend_path = self._backend_path(path)
        
        entries = ['.', '..']
        if backend_path.exists():
            entries.extend([e.name for e in backend_path.iterdir()])
        
        return entries
    
    def mkdir(self, path, mode):
        """Create directory"""
        backend_path = self._backend_path(path)
        backend_path.mkdir(mode=mode, exist_ok=False)
        return 0
    
    def rmdir(self, path):
        """Remove directory"""
        backend_path = self._backend_path(path)
        backend_path.rmdir()
        return 0
    
    # File operations
    def create(self, path, mode, fi=None):
        """Create and open file"""
        backend_path = self._backend_path(path)
        
        # Create file
        fd = os.open(backend_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        
        # Track in open files
        self.fd_counter += 1
        fh = self.fd_counter
        self.open_files[fh] = {'fd': fd, 'path': str(backend_path), 'flags': os.O_WRONLY}
        
        return fh
    
    def open(self, path, flags):
        """Open existing file"""
        backend_path = self._backend_path(path)
        
        fd = os.open(backend_path, flags)
        
        self.fd_counter += 1
        fh = self.fd_counter
        self.open_files[fh] = {'fd': fd, 'path': str(backend_path), 'flags': flags}
        
        return fh
    
    def read(self, path, size, offset, fh):
        """Read from file"""
        if fh in self.open_files:
            fd = self.open_files[fh]['fd']
            os.lseek(fd, offset, os.SEEK_SET)
            return os.read(fd, size)
        else:
            raise FuseOSError(errno.EBADF)
    
    def write(self, path, data, offset, fh):
        """Write to file"""
        if fh in self.open_files:
            fd = self.open_files[fh]['fd']
            os.lseek(fd, offset, os.SEEK_SET)
            return os.write(fd, data)
        else:
            raise FuseOSError(errno.EBADF)
    
    def release(self, path, fh):
        """Close file"""
        if fh in self.open_files:
            os.close(self.open_files[fh]['fd'])
            del self.open_files[fh]
        return 0
    
    def unlink(self, path):
        """Delete file"""
        backend_path = self._backend_path(path)
        os.unlink(backend_path)
        return 0
    
    def rename(self, old, new):
        """Rename/move file (atomic)"""
        old_path = self._backend_path(old)
        new_path = self._backend_path(new)
        os.rename(old_path, new_path)
        return 0
    
    # Extended attributes (for policy enforcement)
    def getxattr(self, path, name, position=0):
        """Get extended attribute"""
        backend_path = self._backend_path(path)
        try:
            # Use xattr module if available, otherwise skip
            if hasattr(os, 'getxattr'):
                return os.getxattr(backend_path, name)
            else:
                # macOS may not have os.getxattr in all Python versions
                raise OSError("xattr not supported")
        except (OSError, AttributeError):
            return b''
    
    def listxattr(self, path):
        """List extended attributes"""
        backend_path = self._backend_path(path)
        try:
            # Use xattr module if available, otherwise skip
            if hasattr(os, 'listxattr'):
                return os.listxattr(backend_path)
            else:
                # macOS may not have os.listxattr in all Python versions
                raise OSError("xattr not supported")
        except (OSError, AttributeError):
            return []
    
    # Filesystem stats
    def statfs(self, path):
        """Get filesystem statistics"""
        stv = os.statvfs(self.backend)
        return {
            'f_bsize': stv.f_bsize,
            'f_frsize': stv.f_frsize,
            'f_blocks': stv.f_blocks,
            'f_bfree': stv.f_bfree,
            'f_bavail': stv.f_bavail,
            'f_files': stv.f_files,
            'f_ffree': stv.f_ffree,
            'f_favail': stv.f_favail,
        }
    
    def flush(self, path, fh):
        """Flush file buffers"""
        if fh in self.open_files:
            os.fsync(self.open_files[fh]['fd'])
        return 0
    
    def fsync(self, path, datasync, fh):
        """Sync file to disk"""
        if fh in self.open_files:
            if datasync and hasattr(os, 'fdatasync'):
                os.fdatasync(self.open_files[fh]['fd'])
            else:
                os.fsync(self.open_files[fh]['fd'])
        return 0


def mount_agent(agent_name: str, backend_dir: str, mount_point: str, foreground: bool = False):
    """
    Mount an agent filesystem at mount_point.
    
    Args:
        agent_name: Name of the agent (for logging)
        backend_dir: Real directory where files are stored
        mount_point: Where to mount the FUSE filesystem
        foreground: Run in foreground (blocking)
    
    Returns:
        FUSE instance (if foreground=False, returns immediately and runs in background thread)
    """
    backend = Path(backend_dir)
    mount = Path(mount_point)
    
    # Ensure mount point exists
    mount.mkdir(parents=True, exist_ok=True)
    
    print(f"[ConcordFS] Mounting agent '{agent_name}'")
    print(f"  Backend:     {backend.absolute()}")
    print(f"  Mount point: {mount.absolute()}")
    
    # Create FUSE instance
    fs = ConcordFS(str(backend))
    
    # Mount options
    mount_options = {
        'foreground': foreground,
        'allow_other': False,  # Only mounting user can access
        'default_permissions': True,
    }
    
    # Start FUSE
    fuse = FUSE(fs, str(mount), **mount_options)
    
    return fuse


def unmount_agent(mount_point: str):
    """
    Unmount an agent filesystem.
    
    Args:
        mount_point: Path to unmount
    """
    import subprocess
    
    mount = Path(mount_point)
    
    if not mount.exists():
        print(f"[ConcordFS] Mount point does not exist: {mount}")
        return
    
    print(f"[ConcordFS] Unmounting: {mount}")
    
    # Platform-specific unmount
    if sys.platform == 'darwin':
        subprocess.run(['umount', str(mount)], check=True)
    else:
        subprocess.run(['fusermount', '-u', str(mount)], check=True)
    
    print(f"[ConcordFS] Unmounted successfully")


if __name__ == '__main__':
    """Simple test: mount a single agent"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Mount ConcordFS agent filesystem')
    parser.add_argument('backend', help='Backend directory (where real files are stored)')
    parser.add_argument('mountpoint', help='Mount point (where FUSE filesystem appears)')
    parser.add_argument('--name', default='demo', help='Agent name (for logging)')
    parser.add_argument('--foreground', '-f', action='store_true', help='Run in foreground')
    
    args = parser.parse_args()
    
    try:
        mount_agent(args.name, args.backend, args.mountpoint, foreground=args.foreground)
    except KeyboardInterrupt:
        print("\n[ConcordFS] Interrupted")
        unmount_agent(args.mountpoint)

