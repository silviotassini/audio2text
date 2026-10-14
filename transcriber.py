#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from colorama import Fore, Style, init

from audio_transcription_tool.transcriber_engine import TranscriberEngine
from audio_transcription_tool.ui_menu import TranscriptionMenu
from audio_transcription_tool.version import __version__
from audio_transcription_tool.utils import (
    DEVICE_OPTIONS,
    find_audio_files,
    format_duration,
    load_config,
    parse_num_speakers,
    resolve_output_dir,
    setup_logger,
    validate_folder,
)

init(autoreset=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ferramenta interativa de transcrição de áudio com Whisper (faster-whisper)"
    )
    parser.add_argument("--version", action="version", version=f"audio2text {__version__}")
    parser.add_argument(
        "folder",
        help="Pasta contendo arquivos de áudio (.mp3, .wav, .m4a, .flac, .ogg)",
    )
    parser.add_argument(
        "--config",
        default="config.json",
        help="Caminho para arquivo de configuração JSON (padrão: config.json)",
    )
    parser.add_argument(
        "-o",
        "--output",
        help=(
            "Pasta onde as transcrições serão gravadas. Não pode ser a pasta dos áudios "
            "(padrão: ./transcricoes_<nome da pasta>)"
        ),
    )
    parser.add_argument(
        "--timestamps",
        action="store_true",
        default=None,
        help="Inclui a marcação de tempo [HH:MM:SS - HH:MM:SS] em cada trecho (padrão: não)",
    )
    parser.add_argument(
        "--device",
        choices=list(DEVICE_OPTIONS),
        help="Dispositivo de processamento: auto (GPU se disponível), cpu ou cuda (padrão: auto)",
    )
    parser.add_argument(
        "--diarize",
        action="store_true",
        default=None,
        help="Identifica os locutores (LOCUTOR 1, 2...). Requer requirements-diarizacao.txt (padrão: não)",
    )
    parser.add_argument(
        "--num-speakers",
        type=int,
        help="Número de locutores, se conhecido (padrão: detectar automaticamente)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    if args.output:
        config["output_dir"] = args.output
    if args.timestamps is not None:
        config["timestamps"] = args.timestamps
    if args.device:
        config["device"] = args.device
    if args.diarize is not None:
        config["diarize"] = args.diarize
    if args.num_speakers is not None:
        config["num_speakers"] = parse_num_speakers(args.num_speakers)

    try:
        audio_folder = validate_folder(args.folder)
        output_dir = resolve_output_dir(config.get("output_dir"), audio_folder)
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        print(f"{Fore.RED}Erro: {exc}{Style.RESET_ALL}")
        return 1

    # Log relativo vai para a pasta de saída, nunca para a pasta dos áudios.
    log_file = Path(str(config.get("log_file", "transcriber.log"))).expanduser()
    if not log_file.is_absolute():
        log_file = output_dir / log_file

    logger = setup_logger(
        enabled=bool(config.get("log_enabled", False)),
        log_file=str(log_file),
        verbose=bool(config.get("verbose", False)),
    )

    audio_files = find_audio_files(audio_folder)
    if not audio_files:
        print(f"{Fore.YELLOW}Nenhum arquivo de áudio suportado foi encontrado na pasta.{Style.RESET_ALL}")
        return 0

    menu = TranscriptionMenu(
        files=audio_files,
        default_model=str(config.get("default_model", "base")),
        default_language=str(config.get("default_language", "auto")),
        default_timestamps=bool(config.get("timestamps", False)),
        default_device=str(config.get("device", "auto")),
        default_diarize=bool(config.get("diarize", False)),
        default_num_speakers=config.get("num_speakers"),
    )

    try:
        selection = menu.run()
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Processo cancelado pelo usuário.{Style.RESET_ALL}")
        return 0

    engine = TranscriberEngine(
        model_name=selection.model_name,
        logger=logger,
        device=selection.device,
        diarize=selection.diarize,
        num_speakers=selection.num_speakers,
        diarization_model=str(config.get("diarization_model")),
    )

    # Carrega os modelos antes do lote: um erro (sem internet no primeiro download,
    # dependência ausente...) aparece uma vez, e não como falha em cada arquivo.
    print(f"\n{Fore.CYAN}Carregando modelo(s)...{Style.RESET_ALL}")
    try:
        engine.load_model()
    except Exception as exc:  # noqa: BLE001
        print(f"{Fore.RED}Erro ao carregar o modelo: {exc}{Style.RESET_ALL}")
        return 1

    print(f"{Fore.CYAN}Iniciando transcrição...{Style.RESET_ALL}")
    print(f"Modelo: {engine.model_name} | Dispositivo: {engine.device} ({engine.compute_type})")
    print(f"Saída: {output_dir}")
    started_at = time.perf_counter()

    results = engine.transcribe_batch(
        files=selection.selected_files,
        output_dir=output_dir,
        language=selection.language,
        timestamps=selection.timestamps,
        show_progress=True,
    )

    elapsed = time.perf_counter() - started_at
    success = [result for result in results if result.success]
    failures = [result for result in results if not result.success]

    print(f"\n{Fore.CYAN}Resumo final{Style.RESET_ALL}")
    print(f"Tempo total: {format_duration(elapsed)}")
    print(f"Arquivos processados: {len(results)}")
    print(f"Sucesso: {len(success)}")
    print(f"Falhas: {len(failures)}")

    if success:
        print(f"\n{Fore.GREEN}Arquivos transcritos:{Style.RESET_ALL}")
        for item in success:
            print(f"  - {item.input_file.name} -> {item.output_file}")
            if item.low_confidence_segments:
                print(
                    f"    {Fore.YELLOW}{item.low_confidence_segments} de {item.total_segments} "
                    f"trecho(s) com baixa confiança marcados com [?? ... ??]{Style.RESET_ALL}"
                )
            if engine.diarize:
                print(f"    {item.speakers} locutor(es) identificado(s)")

    if failures:
        print(f"\n{Fore.RED}Arquivos com erro:{Style.RESET_ALL}")
        for item in failures:
            print(f"  - {item.input_file.name}: {item.error_message}")

    return 0 if not failures else 2


if __name__ == "__main__":
    sys.exit(main())
