"""Pacote principal da ferramenta de transcrição de áudio."""

from .transcriber_engine import TranscriberEngine, TranscriptionResult
from .version import __version__

__all__ = ["TranscriberEngine", "TranscriptionResult", "__version__"]
