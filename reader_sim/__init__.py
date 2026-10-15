"""จำลองนักอ่าน My Novel 100 คน เพื่อประเมินหนังสือหลัง QC"""

from .model import run
from .personas import DIMENSIONS, GENRES, TROPES, build_panel

__all__ = ["run", "build_panel", "DIMENSIONS", "GENRES", "TROPES"]
