import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from tqdm import tqdm

AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".flac", ".ogg",
    # Comuns em perícia: WhatsApp (.opus), celulares (.aac, .amr, .3gp), Windows (.wma)
    # e vídeos, dos quais só o áudio é usado.
    ".opus", ".aac", ".amr", ".3gp", ".wma", ".mp4", ".mkv", ".mov", ".avi",
}
# Nomes com versão explícita: "large" sozinho aponta para versões diferentes
# conforme a biblioteca, o que impede reproduzir o resultado.
MODEL_DESCRIPTIONS = {
    "base": "rápido, menor precisão (bom para triagem)",
    "small": "equilíbrio entre velocidade e precisão",
    "medium": "boa precisão, mais lento",
    "large-v3": "maior precisão, o mais lento (recomendado para laudo)",
    "turbo": "large-v3 otimizado: precisão próxima, bem mais rápido",
}
SUPPORTED_MODELS = list(MODEL_DESCRIPTIONS)
MODEL_ALIASES = {"large": "large-v3", "large-v3-turbo": "turbo"}

DEVICE_OPTIONS = {
    "auto": "Automático (GPU se disponível)",
    "cpu": "CPU",
    "cuda": "GPU NVIDIA (CUDA)",
}

DEFAULT_DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"

LANGUAGE_OPTIONS = {
    "auto": "Auto-detectar",
    "pt": "Português",
    "en": "Inglês",
    "es": "Espanhol",
    "fr": "Francês",
    "de": "Alemão",
    "it": "Italiano",
}


def load_config(config_path: Path) -> Dict[str, Any]:
    default_config: Dict[str, Any] = {
        "default_model": "base",
        "default_language": "auto",
        "output_dir": None,
        "log_enabled": False,
        "log_file": "transcriber.log",
        "verbose": False,
        "timestamps": False,
        "device": "auto",
        "diarize": False,
        "num_speakers": None,
        "diarization_model": DEFAULT_DIARIZATION_MODEL,
    }

    config = default_config.copy()
    if config_path.exists():
        try:
            with config_path.open("r", encoding="utf-8") as fp:
                loaded = json.load(fp)
            if isinstance(loaded, dict):
                config.update(loaded)
        except (OSError, json.JSONDecodeError):
            # Mantém defaults caso o config seja inválido
            pass

    env_map = {
        "AT_DEFAULT_MODEL": "default_model",
        "AT_DEFAULT_LANGUAGE": "default_language",
        "AT_OUTPUT_DIR": "output_dir",
        "AT_LOG_ENABLED": "log_enabled",
        "AT_LOG_FILE": "log_file",
        "AT_VERBOSE": "verbose",
        "AT_TIMESTAMPS": "timestamps",
        "AT_DEVICE": "device",
        "AT_DIARIZE": "diarize",
        "AT_NUM_SPEAKERS": "num_speakers",
        "AT_DIARIZATION_MODEL": "diarization_model",
    }

    for env_var, key in env_map.items():
        value = os.getenv(env_var)
        if value is None:
            continue
        if key in {"log_enabled", "verbose", "timestamps", "diarize"}:
            config[key] = value.strip().lower() in {"1", "true", "yes", "on"}
        else:
            config[key] = value

    config["default_model"] = MODEL_ALIASES.get(config["default_model"], config["default_model"])
    if config["default_model"] not in SUPPORTED_MODELS:
        config["default_model"] = "base"

    if config["default_language"] not in LANGUAGE_OPTIONS:
        config["default_language"] = "auto"

    if config["device"] not in DEVICE_OPTIONS:
        config["device"] = "auto"

    config["num_speakers"] = parse_num_speakers(config.get("num_speakers"))

    return config


def parse_num_speakers(value: Any) -> Optional[int]:
    """Converte o número de locutores; vazio, nulo ou inválido = detectar automaticamente."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


class TqdmLoggingHandler(logging.Handler):
    """Escreve no terminal sem quebrar a barra de progresso do tqdm."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            tqdm.write(self.format(record), file=sys.stderr)
        except Exception:  # noqa: BLE001
            self.handleError(record)


def setup_logger(enabled: bool, log_file: str, verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger("audio_transcriber")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.handlers.clear()

    # No terminal, só avisos e erros (o resumo final já mostra o resultado);
    # com verbose, todo o detalhamento.
    console_handler = TqdmLoggingHandler()
    console_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)
    console_handler.setFormatter(logging.Formatter("%(levelname)s | %(message)s"))
    logger.addHandler(console_handler)

    if enabled:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
        file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        logger.addHandler(file_handler)

    return logger


def find_audio_files(folder: Path) -> List[Path]:
    return sorted(
        [
            p
            for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
        ],
        key=lambda p: p.name.lower(),
    )


def validate_folder(folder_path: str) -> Path:
    folder = Path(folder_path).expanduser().resolve()
    if not folder.exists():
        raise FileNotFoundError(f"A pasta não existe: {folder}")
    if not folder.is_dir():
        raise NotADirectoryError(f"O caminho não é uma pasta: {folder}")
    return folder


def parse_file_selection(selection_text: str, max_index: int) -> List[int]:
    if not selection_text.strip():
        raise ValueError("Seleção vazia. Informe números ou intervalos, ex: 1,3-5")

    indexes = set()
    parts = [part.strip() for part in selection_text.split(",") if part.strip()]

    token_pattern = re.compile(r"^(\d+)(?:-(\d+))?$")

    for token in parts:
        match = token_pattern.match(token)
        if not match:
            raise ValueError(f"Token inválido: '{token}'. Use formato 1,2-4")

        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start

        if start < 1 or end < 1 or start > max_index or end > max_index:
            raise ValueError(f"Índice fora do intervalo permitido (1-{max_index}): '{token}'")

        if start > end:
            raise ValueError(f"Intervalo inválido (início maior que fim): '{token}'")

        for idx in range(start, end + 1):
            indexes.add(idx)

    return sorted(indexes)


def format_duration(seconds: float) -> str:
    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_timestamp(seconds: float) -> str:
    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def resolve_output_dir(output_dir: Optional[str], folder: Path) -> Path:
    """Define a pasta de saída, que nunca pode ser a pasta dos áudios nem estar dentro dela.

    Sem configuração, usa ./transcricoes_<nome da pasta> no diretório atual.
    """
    if output_dir:
        out = Path(output_dir).expanduser().resolve()
    else:
        out = (Path.cwd() / f"transcricoes_{folder.name}").resolve()

    if out == folder or folder in out.parents:
        raise ValueError(
            f"A pasta de saída ({out}) não pode ser a pasta dos áudios nem ficar dentro dela, "
            "para não alterar o material examinado. Informe outra pasta com --output."
        )

    out.mkdir(parents=True, exist_ok=True)
    return out
