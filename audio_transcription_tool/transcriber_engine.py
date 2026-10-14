from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import ctranslate2
import faster_whisper
import numpy as np
from faster_whisper import WhisperModel, decode_audio
from tqdm import tqdm

from .utils import DEFAULT_DIARIZATION_MODEL, format_timestamp
from .version import __version__

SAMPLE_RATE = 16000

# Parâmetros de decodificação que reduzem "alucinações" do Whisper
# (frases inventadas em trechos de silêncio, ruído ou música).
DECODE_OPTIONS: Dict[str, Any] = {
    # Detecção de voz (VAD): remove trechos sem fala antes da transcrição.
    "vad_filter": True,
    # Não usa o texto anterior como contexto: evita que um erro se propague
    # e que frases sejam repetidas em loop.
    "condition_on_previous_text": False,
    # Necessário para hallucination_silence_threshold e para atribuir locutores por palavra.
    "word_timestamps": True,
    # Descarta trechos cercados por silêncio maior que N segundos que pareçam alucinação.
    "hallucination_silence_threshold": 2.0,
    "no_speech_threshold": 0.6,
    "log_prob_threshold": -1.0,
    "compression_ratio_threshold": 2.4,
    "beam_size": 5,
}

# Limiares para marcar um segmento como de baixa confiança no texto final.
LOW_CONFIDENCE_LOGPROB = -1.0
LOW_CONFIDENCE_NO_SPEECH = 0.6
LOW_CONFIDENCE_COMPRESSION = 2.4
LOW_CONFIDENCE_OPEN = "[?? "
LOW_CONFIDENCE_CLOSE = " ??]"

UNKNOWN_SPEAKER_LABEL = "LOCUTOR ?"


class TranscricaoCancelada(Exception):
    """Lançada pelo callback de progresso para interromper a transcrição em andamento."""


# Recebe (segundos já transcritos, duração total do áudio). Pode lançar TranscricaoCancelada.
ProgressCallback = Callable[[float, float], None]


def agora_com_fuso() -> str:
    """Data e hora locais com o deslocamento de UTC explícito, ex.: 2026-10-10 08:13:08 (UTC-03:00)."""
    agora = datetime.now().astimezone()
    deslocamento = agora.strftime("%z")
    return f"{agora.strftime('%Y-%m-%d %H:%M:%S')} (UTC{deslocamento[:3]}:{deslocamento[3:]})"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for bloco in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(bloco)
    return digest.hexdigest()


@dataclass
class TranscriptionResult:
    input_file: Path
    output_file: Optional[Path]
    success: bool
    language: Optional[str] = None
    elapsed_seconds: float = 0.0
    error_message: Optional[str] = None
    low_confidence_segments: int = 0
    total_segments: int = 0
    speakers: int = 0
    duration: float = 0.0
    audio_sha256: Optional[str] = None
    output_sha256: Optional[str] = None


def is_low_confidence(segment: Dict[str, Any]) -> bool:
    return (
        segment.get("avg_logprob", 0.0) < LOW_CONFIDENCE_LOGPROB
        or segment.get("no_speech_prob", 0.0) > LOW_CONFIDENCE_NO_SPEECH
        or segment.get("compression_ratio", 0.0) > LOW_CONFIDENCE_COMPRESSION
    )


def write_new_file(base_path: Path, content: str) -> Path:
    """Grava em um arquivo novo, nunca sobrescrevendo: se existir, usa _2, _3..."""
    candidate = base_path
    counter = 2
    while True:
        try:
            with candidate.open("x", encoding="utf-8") as fp:
                fp.write(content)
            return candidate
        except FileExistsError:
            candidate = base_path.with_name(f"{base_path.stem}_{counter}{base_path.suffix}")
            counter += 1


def resolve_device(requested: str, logger=None) -> str:
    try:
        has_gpu = ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001
        has_gpu = False

    if has_gpu and requested in {"auto", "cuda"}:
        return "cuda"
    if logger and requested == "cuda":
        logger.warning("GPU (CUDA) solicitada, mas não disponível: usando CPU (bem mais lento).")
    elif logger and requested == "auto":
        logger.warning("Nenhuma GPU CUDA detectada: usando CPU (bem mais lento).")
    return "cpu"


# Formatos numéricos em ordem de preferência (mais rápido primeiro). GPUs anteriores
# à geração Volta (ex.: GTX 10xx) não suportam float16 e usam int8 ou float32.
COMPUTE_TYPE_PREFERENCE = {
    "cuda": ["float16", "int8_float16", "int8", "float32"],
    "cpu": ["int8", "float32"],
}


def pick_compute_type(device: str) -> str:
    try:
        supported = ctranslate2.get_supported_compute_types(device)
    except Exception:  # noqa: BLE001
        return "float32"
    for compute_type in COMPUTE_TYPE_PREFERENCE[device]:
        if compute_type in supported:
            return compute_type
    return "float32"


class TranscriberEngine:
    """Engine principal de transcrição usando Whisper (via faster-whisper)."""

    def __init__(
        self,
        model_name: str = "base",
        logger=None,
        device: str = "auto",
        diarize: bool = False,
        num_speakers: Optional[int] = None,
        diarization_model: str = DEFAULT_DIARIZATION_MODEL,
    ):
        self.model_name = model_name
        self.logger = logger
        self.requested_device = device
        self.device: Optional[str] = None
        self.compute_type: Optional[str] = None
        self.diarize = diarize
        self.num_speakers = num_speakers
        self.diarization_model = diarization_model
        self._model = None
        self._diarizer = None

    def load_model(self) -> None:
        if self._model is None:
            self.device = resolve_device(self.requested_device, self.logger)
            try:
                self._model = self._create_model(self.device)
                if self.device == "cuda":
                    # Teste curto: falhas de biblioteca CUDA/cuDNN ou falta de memória da GPU
                    # aparecem só na primeira transcrição; melhor detectá-las agora.
                    segments, _ = self._model.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32))
                    list(segments)
            except Exception as exc:  # noqa: BLE001
                if self.device != "cuda":
                    raise
                if self.logger:
                    self.logger.warning("Falha ao usar a GPU (%s): usando CPU (bem mais lento).", exc)
                self._model = None
                self.device = "cpu"
                self._model = self._create_model(self.device)

        if self.diarize and self._diarizer is None:
            from .diarization import SpeakerDiarizer

            self._diarizer = SpeakerDiarizer(self.diarization_model, device=self.device, logger=self.logger)
            self._diarizer.load()

    def _create_model(self, device: str) -> WhisperModel:
        self.compute_type = pick_compute_type(device)
        if self.logger:
            self.logger.info("Carregando modelo Whisper: %s (%s/%s)", self.model_name, device, self.compute_type)
        return WhisperModel(self.model_name, device=device, compute_type=self.compute_type)

    def set_model(self, model_name: str) -> None:
        if self.model_name != model_name:
            self.model_name = model_name
            self._model = None

    def _split_by_speaker(self, segments: List[Dict[str, Any]], turns) -> List[Dict[str, Any]]:
        """Divide cada segmento por palavra, atribuindo cada palavra ao locutor do momento."""
        from .diarization import speaker_at

        pieces: List[Dict[str, Any]] = []
        for segment in segments:
            low = is_low_confidence(segment)
            words = segment["words"] or [(segment["start"], segment["end"], segment["text"])]
            segment_pieces: List[Dict[str, Any]] = []
            for start, end, word in words:
                speaker = speaker_at(start, end, turns)
                if segment_pieces and segment_pieces[-1]["speaker"] == speaker:
                    segment_pieces[-1]["text"] += word
                    segment_pieces[-1]["end"] = end
                else:
                    segment_pieces.append(
                        {"start": start, "end": end, "text": word, "speaker": speaker, "low": low}
                    )
            pieces.extend(segment_pieces)
        return pieces

    def build_transcript(
        self,
        audio_path: Path,
        pieces: List[Dict[str, Any]],
        language: str,
        detected_language: Optional[str],
        duration: float,
        timestamps: bool,
        speaker_count: int,
        audio_sha256: Optional[str] = None,
    ) -> str:
        if language and language != "auto":
            language_info = f"{language} (definido pelo perito)"
        else:
            language_info = f"{detected_language} (detectado automaticamente)"

        header = [
            "# TRANSCRIÇÃO AUTOMÁTICA - SUJEITA A CONFERÊNCIA PERICIAL",
            f"# Ferramenta: audio2text {__version__}",
            f"# Arquivo de origem: {audio_path.name}",
            f"# Duração do áudio: {format_timestamp(duration)}",
        ]
        if audio_sha256:
            header.append(f"# SHA-256 do áudio: {audio_sha256}")
        header += [
            f"# Modelo: Whisper {self.model_name} "
            f"(faster-whisper {faster_whisper.__version__}, {self.device}/{self.compute_type})",
            f"# Idioma: {language_info}",
            f"# Gerado em: {agora_com_fuso()}",
            "# Atenção: o reconhecimento automático pode omitir falas ou gerar texto",
            "# inexistente no áudio. Todo o conteúdo deve ser conferido com a gravação.",
            f"# Trechos entre {LOW_CONFIDENCE_OPEN.strip()} e {LOW_CONFIDENCE_CLOSE.strip()} "
            "têm baixa confiança e exigem atenção especial.",
        ]
        if self.diarize:
            header += [
                f"# Locutores: identificação automática ({self.diarization_model}, "
                f"pyannote.audio {self._diarizer.library_version}) - {speaker_count} locutor(es).",
                "# Os rótulos LOCUTOR 1, 2... não identificam pessoas e a atribuição de cada",
                f"# fala deve ser conferida. {UNKNOWN_SPEAKER_LABEL} = trecho sem locutor atribuído.",
            ]
        header += ["", ""]

        # Agrupa trechos consecutivos do mesmo locutor em uma linha.
        lines: List[Dict[str, Any]] = []
        for piece in pieces:
            text = piece["text"].strip()
            if not text:
                continue
            if piece["low"]:
                text = f"{LOW_CONFIDENCE_OPEN}{text}{LOW_CONFIDENCE_CLOSE}"
            if self.diarize and lines and lines[-1]["speaker"] == piece["speaker"]:
                lines[-1]["texts"].append(text)
                lines[-1]["end"] = piece["end"]
            else:
                lines.append(
                    {"start": piece["start"], "end": piece["end"], "speaker": piece["speaker"], "texts": [text]}
                )

        rendered = []
        for line in lines:
            text = " ".join(line["texts"])
            if self.diarize:
                text = f"{line['speaker']}: {text}"
            if timestamps:
                text = f"[{format_timestamp(line['start'])} - {format_timestamp(line['end'])}] {text}"
            rendered.append(text)

        body = "\n".join(rendered) if (timestamps or self.diarize) else " ".join(rendered)
        if not body:
            body = "[Nenhuma fala detectada]"
        return "\n".join(header) + body + "\n"

    def transcribe_file(
        self,
        audio_path: Path,
        output_dir: Path,
        language: str = "auto",
        timestamps: bool = False,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> TranscriptionResult:
        started_at = time.perf_counter()
        audio_sha256: Optional[str] = None

        try:
            self.load_model()
            kwargs = dict(DECODE_OPTIONS)
            if language and language != "auto":
                kwargs["language"] = language

            if self.logger:
                self.logger.info("Iniciando transcrição: %s", audio_path.name)

            audio_sha256 = sha256_file(audio_path)
            audio = decode_audio(str(audio_path), sampling_rate=SAMPLE_RATE)
            segments_iter, info = self._model.transcribe(audio, **kwargs)
            segments = []
            for s in segments_iter:
                segments.append(
                    {
                        "start": s.start,
                        "end": s.end,
                        "text": s.text,
                        "avg_logprob": s.avg_logprob,
                        "no_speech_prob": s.no_speech_prob,
                        "compression_ratio": s.compression_ratio,
                        "words": [(w.start, w.end, w.word) for w in (s.words or [])],
                    }
                )
                if progress_callback:
                    progress_callback(s.end, info.duration)
            detected_language = info.language

            speaker_count = 0
            if self.diarize:
                if self.logger:
                    self.logger.info("Identificando locutores: %s", audio_path.name)
                turns = self._diarizer.diarize(audio, num_speakers=self.num_speakers)
                pieces = self._split_by_speaker(segments, turns)
                # Rótulos na ordem em que cada locutor aparece na transcrição.
                labels: Dict[str, str] = {}
                for piece in pieces:
                    raw = piece["speaker"]
                    if raw == "?":
                        piece["speaker"] = UNKNOWN_SPEAKER_LABEL
                        continue
                    if raw not in labels and piece["text"].strip():
                        labels[raw] = f"LOCUTOR {len(labels) + 1}"
                    piece["speaker"] = labels.get(raw, UNKNOWN_SPEAKER_LABEL)
                speaker_count = len(labels)
            else:
                pieces = [
                    {
                        "start": s["start"],
                        "end": s["end"],
                        "text": s["text"],
                        "speaker": None,
                        "low": is_low_confidence(s),
                    }
                    for s in segments
                ]

            content = self.build_transcript(
                audio_path, pieces, language, detected_language, info.duration, timestamps, speaker_count,
                audio_sha256,
            )
            # Usa o nome completo (com extensão) para que "a.mp3" e "a.wav" não colidam.
            output_file = write_new_file(output_dir / f"{audio_path.name}.txt", content)

            low_confidence = sum(1 for s in segments if s["text"].strip() and is_low_confidence(s))
            elapsed = time.perf_counter() - started_at
            if self.logger:
                self.logger.info(
                    "Concluído: %s (idioma=%s, tempo=%.2fs, baixa confiança=%d/%d, locutores=%d)",
                    audio_path.name,
                    detected_language,
                    elapsed,
                    low_confidence,
                    len(segments),
                    speaker_count,
                )

            return TranscriptionResult(
                input_file=audio_path,
                output_file=output_file,
                success=True,
                language=detected_language,
                elapsed_seconds=elapsed,
                low_confidence_segments=low_confidence,
                total_segments=len(segments),
                speakers=speaker_count,
                duration=info.duration,
                audio_sha256=audio_sha256,
                output_sha256=sha256_file(output_file),
            )

        except TranscricaoCancelada:
            raise
        except Exception as exc:  # noqa: BLE001
            elapsed = time.perf_counter() - started_at
            if self.logger:
                self.logger.error("Falha ao transcrever '%s': %s", audio_path.name, exc)
            return TranscriptionResult(
                input_file=audio_path,
                output_file=None,
                success=False,
                elapsed_seconds=elapsed,
                error_message=str(exc),
                audio_sha256=audio_sha256,
            )

    def transcribe_batch(
        self,
        files: List[Path],
        output_dir: Path,
        language: str = "auto",
        timestamps: bool = False,
        show_progress: bool = True,
    ) -> List[TranscriptionResult]:
        results: List[TranscriptionResult] = []

        iterator = files
        if show_progress:
            iterator = tqdm(files, desc="Transcrevendo arquivos", unit="arquivo")

        for file_path in iterator:
            result = self.transcribe_file(
                audio_path=file_path,
                output_dir=output_dir,
                language=language,
                timestamps=timestamps,
            )
            results.append(result)

        return results
