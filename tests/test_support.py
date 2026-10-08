"""Bounded cleanup for transient Windows fixture handles only."""
import time
from pathlib import Path

def cleanup_temporary_directory(temporary_directory) -> None:
    target=Path(temporary_directory.name)
    for attempt in range(20):
        try:
            if attempt==0:
                temporary_directory.cleanup()
            elif target.exists():
                temporary_directory._rmtree(target, ignore_errors=False)
            return
        except OSError as exc:
            if getattr(exc, 'winerror', None) not in {5, 32} or attempt == 19:
                raise
            time.sleep(0.15)
