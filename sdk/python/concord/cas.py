"""
Content-Addressable Storage (CAS) Bus for Concord

Provides /mnt/bus/sha256/<hash> storage for efficient artifact passing.
Agents exchange hash references instead of copying large blobs.
"""

import hashlib
import json
from pathlib import Path
from typing import Union, Optional

from .fsops import atomic_write_bytes, atomic_write_json


class CASBus:
    """Content-addressable storage for agent artifacts"""
    
    def __init__(self, base_path: str = "/tmp/bus"):
        self.base = Path(base_path)
        self.sha256_dir = self.base / "sha256"
        self.sha256_dir.mkdir(parents=True, exist_ok=True)
    
    def put(self, content: Union[bytes, str], content_type: str = "application/octet-stream") -> str:
        """
        Store content and return its hash.
        
        Args:
            content: Content to store (bytes or string)
            content_type: MIME type of content
        
        Returns:
            SHA256 hash of content
        """
        # Convert to bytes if string
        if isinstance(content, str):
            content_bytes = content.encode('utf-8')
        else:
            content_bytes = content
        
        # Compute hash
        hash_value = hashlib.sha256(content_bytes).hexdigest()
        
        # Store content
        content_path = self.sha256_dir / hash_value
        if not content_path.exists():
            atomic_write_bytes(content_path, content_bytes)
        
        # Store metadata
        meta_path = self.sha256_dir / f"{hash_value}.meta"
        meta = {
            "hash": hash_value,
            "size": len(content_bytes),
            "content_type": content_type,
        }
        atomic_write_json(meta_path, meta, indent=2)
        
        return hash_value
    
    def get(self, hash_value: str) -> Optional[bytes]:
        """
        Retrieve content by hash.
        
        Args:
            hash_value: SHA256 hash
        
        Returns:
            Content bytes, or None if not found
        """
        content_path = self.sha256_dir / hash_value
        
        if not content_path.exists():
            return None
        
        return content_path.read_bytes()
    
    def get_text(self, hash_value: str, encoding: str = 'utf-8') -> Optional[str]:
        """
        Retrieve text content by hash.
        
        Args:
            hash_value: SHA256 hash
            encoding: Text encoding (default: utf-8)
        
        Returns:
            Content string, or None if not found
        """
        content = self.get(hash_value)
        if content is None:
            return None
        
        return content.decode(encoding)
    
    def get_meta(self, hash_value: str) -> Optional[dict]:
        """
        Retrieve metadata for a hash.
        
        Args:
            hash_value: SHA256 hash
        
        Returns:
            Metadata dict, or None if not found
        """
        meta_path = self.sha256_dir / f"{hash_value}.meta"
        
        if not meta_path.exists():
            return None
        
        return json.loads(meta_path.read_text())
    
    def ref(self, hash_value: str) -> str:
        """
        Generate a CAS reference URI for a hash.
        
        Args:
            hash_value: SHA256 hash
        
        Returns:
            URI like "cas://sha256/<hash>"
        """
        return f"cas://sha256/{hash_value}"
    
    def parse_ref(self, ref: str) -> Optional[str]:
        """
        Parse a CAS reference URI to extract hash.
        
        Args:
            ref: URI like "cas://sha256/<hash>"
        
        Returns:
            Hash value, or None if invalid format
        """
        if not ref.startswith("cas://sha256/"):
            return None
        
        return ref[len("cas://sha256/"):]
    
    def exists(self, hash_value: str) -> bool:
        """Check if content exists for a hash"""
        content_path = self.sha256_dir / hash_value
        return content_path.exists()


# Global CAS bus instance
_cas_bus = None

def get_cas_bus(base_path: str = "/tmp/bus") -> CASBus:
    """Get or create global CAS bus instance"""
    global _cas_bus
    if _cas_bus is None:
        _cas_bus = CASBus(base_path)
    return _cas_bus

