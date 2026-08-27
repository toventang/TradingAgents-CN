"""
ChromaDB unified configuration module
Supports automatic adaptation for Windows 10/11 and other operating systems
"""
import os
import platform
import chromadb
from chromadb.config import Settings


def is_windows_11() -> bool:
    """
    Detect if running on Windows 11
    
    Returns:
        bool: True if Windows 11, False otherwise
    """
    if platform.system() != "Windows":
        return False
    
    # Windows 11 version number is typically 10.0.22000 or higher
    version = platform.version()
    try:
        # Extract version number, format is usually "10.0.26100"
        version_parts = version.split('.')
        if len(version_parts) >= 3:
            build_number = int(version_parts[2])
            # Windows 11 build number starts from 22000
            return build_number >= 22000
    except (ValueError, IndexError):
        pass
    
    return False


def get_win10_chromadb_client():
    """
    Get Windows 10 compatible ChromaDB client
    
    Returns:
        chromadb.Client: ChromaDB client instance
    """
    # Disable Rust bindings to avoid DLL loading issues on Windows
    os.environ['CHROMADB_IMPL'] = 'duckdb'
    
    settings = Settings(
        allow_reset=True,
        anonymized_telemetry=False,
        is_persistent=False,
        # Use ephemeral (in-memory) client to avoid file system issues
        chroma_api_impl="rest"
    )
    
    try:
        client = chromadb.Client(settings)
        return client
    except Exception as e:
        # Fallback to minimal configuration
        try:
            basic_settings = Settings(
                allow_reset=True,
                is_persistent=False,
                anonymized_telemetry=False
            )
            return chromadb.Client(basic_settings)
        except Exception:
            # Last resort: use ephemeral client
            return chromadb.EphemeralClient()


def get_win11_chromadb_client():
    """
    Get Windows 11 optimized ChromaDB client
    
    Returns:
        chromadb.Client: ChromaDB client instance
    """
    # Disable Rust bindings to avoid DLL loading issues
    os.environ['CHROMADB_IMPL'] = 'duckdb'
    
    settings = Settings(
        allow_reset=True,
        anonymized_telemetry=False,
        is_persistent=False
    )
    
    try:
        client = chromadb.Client(settings)
        return client
    except Exception as e:
        # Fallback to minimal configuration
        try:
            minimal_settings = Settings(
                allow_reset=True,
                anonymized_telemetry=False,
                is_persistent=False
            )
            return chromadb.Client(minimal_settings)
        except Exception:
            # Last resort: use ephemeral client
            return chromadb.EphemeralClient()


def get_optimal_chromadb_client():
    """
    Automatically select optimal ChromaDB configuration based on OS
    
    Returns:
        chromadb.Client: ChromaDB client instance
    """
    system = platform.system()
    
    if system == "Windows":
        # Use more accurate Windows 11 detection
        if is_windows_11():
            # Windows 11 or newer
            return get_win11_chromadb_client()
        else:
            # Windows 10 or older, use compatible configuration
            return get_win10_chromadb_client()
    else:
        # Non-Windows system, use standard configuration
        settings = Settings(
            allow_reset=True,
            anonymized_telemetry=False,
            is_persistent=False
        )
        try:
            return chromadb.Client(settings)
        except Exception:
            # Fallback to ephemeral client
            return chromadb.EphemeralClient()


# Export configuration
__all__ = [
    'get_optimal_chromadb_client',
    'get_win10_chromadb_client',
    'get_win11_chromadb_client',
    'is_windows_11'
]


