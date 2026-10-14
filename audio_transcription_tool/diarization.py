"""Identificação de locutores (diarização) com pyannote.audio.

Opcional: só é importado quando o perito ativa a identificação, pois depende de
torch e pyannote (ver requirements-diarizacao.txt).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from .utils import DEFAULT_DIARIZATION_MODEL

SAMPLE_RATE = 16000
UNKNOWN_SPEAKER = "?"


@dataclass
class SpeakerTurn:
    start: float
    end: float
    speaker: str


class SpeakerDiarizer:
    def __init__(self, model_name: str = DEFAULT_DIARIZATION_MODEL, device: str = "cpu", logger=None):
        self.model_name = model_name
        self.device = device
        self.logger = logger
        self._pipeline = None
        self.library_version = "?"

    def load(self) -> None:
        if self._pipeline is not None:
            return

        # Desliga a telemetria do pyannote: nenhum dado do exame deve sair da máquina.
        os.environ["PYANNOTE_METRICS_ENABLED"] = "false"
        try:
            import pyannote.audio
            import torch
            from pyannote.audio import Pipeline
        except ImportError as exc:
            raise RuntimeError(
                "A identificação de locutores requer dependências extras. "
                "Instale com: pip install -r requirements-diarizacao.txt"
            ) from exc

        if self.logger:
            self.logger.info("Carregando modelo de identificação de locutores: %s", self.model_name)

        try:
            # O token do Hugging Face (só necessário no primeiro download) é lido de
            # HF_TOKEN ou do login feito com "hf auth login".
            pipeline = Pipeline.from_pretrained(self.model_name)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Não foi possível carregar o modelo '{self.model_name}': {exc}. "
                "No primeiro uso, aceite os termos do modelo em huggingface.co e "
                "defina HF_TOKEN (ou rode 'hf auth login')."
            ) from exc
        if pipeline is None:
            raise RuntimeError(
                f"Acesso negado ao modelo '{self.model_name}'. Aceite os termos do modelo "
                "em huggingface.co e defina HF_TOKEN (ou rode 'hf auth login')."
            )

        if self.device == "cuda":
            problem = self._cuda_problem(torch)
            if problem is None:
                pipeline.to(torch.device("cuda"))
            else:
                self.device = "cpu"
                if self.logger:
                    self.logger.warning(
                        "GPU indisponível para o PyTorch (%s): identificação de locutores usará a CPU.", problem
                    )

        self._pipeline = pipeline
        self.library_version = pyannote.audio.__version__

    @staticmethod
    def _cuda_problem(torch) -> Optional[str]:
        """Testa a GPU de fato: torch.cuda.is_available() pode ser verdadeiro mesmo quando
        o PyTorch não foi compilado para a placa (ex.: GTX 10xx com PyTorch para CUDA 13)."""
        if not torch.cuda.is_available():
            return "nenhuma GPU CUDA detectada"
        try:
            (torch.ones(1, device="cuda") * 2).item()
        except Exception as exc:  # noqa: BLE001
            return str(exc).splitlines()[0]
        return None

    def diarize(self, audio: np.ndarray, num_speakers: Optional[int] = None) -> List[SpeakerTurn]:
        """Recebe o áudio já decodificado (mono, 16 kHz, float32) e devolve os turnos de fala."""
        import torch

        self.load()
        waveform = torch.from_numpy(audio).unsqueeze(0)
        kwargs = {"num_speakers": num_speakers} if num_speakers else {}
        output = self._pipeline({"waveform": waveform, "sample_rate": SAMPLE_RATE}, **kwargs)

        # pyannote 4 devolve DiarizeOutput; a versão "exclusive" não tem falas
        # sobrepostas e é a indicada para alinhar com a transcrição.
        annotation = getattr(output, "exclusive_speaker_diarization", None)
        if annotation is None:
            annotation = getattr(output, "speaker_diarization", output)

        return [
            SpeakerTurn(start=turn.start, end=turn.end, speaker=str(label))
            for turn, _, label in annotation.itertracks(yield_label=True)
        ]


def speaker_at(start: float, end: float, turns: List[SpeakerTurn]) -> str:
    """Locutor com maior sobreposição no intervalo; '?' se nenhum turno cobrir o trecho."""
    if end <= start:
        end = start + 0.01
    best_speaker = UNKNOWN_SPEAKER
    best_overlap = 0.0
    for turn in turns:
        overlap = min(end, turn.end) - max(start, turn.start)
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = turn.speaker
    return best_speaker
