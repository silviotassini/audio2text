from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from colorama import Fore, Style, init

from .utils import (
    DEVICE_OPTIONS,
    LANGUAGE_OPTIONS,
    MODEL_DESCRIPTIONS,
    SUPPORTED_MODELS,
    parse_file_selection,
    parse_num_speakers,
)

init(autoreset=True)


@dataclass
class MenuSelection:
    selected_files: List[Path]
    model_name: str
    language: str
    timestamps: bool = False
    device: str = "auto"
    diarize: bool = False
    num_speakers: Optional[int] = None


class TranscriptionMenu:
    def __init__(
        self,
        files: List[Path],
        default_model: str,
        default_language: str,
        default_timestamps: bool = False,
        default_device: str = "auto",
        default_diarize: bool = False,
        default_num_speakers: Optional[int] = None,
    ):
        self.files = files
        self.selected_indexes = list(range(1, len(files) + 1))
        self.model_name = default_model
        self.language = default_language
        self.timestamps = default_timestamps
        self.device = default_device
        self.diarize = default_diarize
        self.num_speakers = default_num_speakers

    def display_files(self) -> None:
        print(f"\n{Fore.CYAN}Arquivos de áudio encontrados:{Style.RESET_ALL}")
        for idx, file_path in enumerate(self.files, start=1):
            selected_marker = f"{Fore.GREEN}✓{Style.RESET_ALL}" if idx in self.selected_indexes else " "
            print(f"  [{selected_marker}] {idx:02d}. {file_path.name}")

    def choose_all_files(self) -> None:
        self.selected_indexes = list(range(1, len(self.files) + 1))
        print(f"{Fore.GREEN}Todos os arquivos foram selecionados.{Style.RESET_ALL}")

    def choose_specific_files(self) -> None:
        user_input = input("Informe números/intervalos (ex: 1,3-5): ").strip()
        indexes = parse_file_selection(user_input, len(self.files))
        self.selected_indexes = indexes
        print(f"{Fore.GREEN}Seleção atualizada com {len(indexes)} arquivo(s).{Style.RESET_ALL}")

    def choose_model(self) -> None:
        print(f"\n{Fore.CYAN}Modelos disponíveis:{Style.RESET_ALL}")
        for idx, model in enumerate(SUPPORTED_MODELS, start=1):
            marker = "(atual)" if model == self.model_name else ""
            print(f"  {idx}. {model:<9} {MODEL_DESCRIPTIONS[model]} {marker}")

        selected = input("Escolha o número do modelo: ").strip()
        if not selected.isdigit() or int(selected) < 1 or int(selected) > len(SUPPORTED_MODELS):
            raise ValueError("Modelo inválido.")

        self.model_name = SUPPORTED_MODELS[int(selected) - 1]
        print(f"{Fore.GREEN}Modelo selecionado: {self.model_name}{Style.RESET_ALL}")

    def choose_language(self) -> None:
        print(f"\n{Fore.CYAN}Idiomas disponíveis:{Style.RESET_ALL}")
        lang_items = list(LANGUAGE_OPTIONS.items())
        for idx, (code, label) in enumerate(lang_items, start=1):
            marker = "(atual)" if code == self.language else ""
            print(f"  {idx}. {label} [{code}] {marker}")

        selected = input("Escolha o número do idioma: ").strip()
        if not selected.isdigit() or int(selected) < 1 or int(selected) > len(lang_items):
            raise ValueError("Idioma inválido.")

        self.language = lang_items[int(selected) - 1][0]
        print(f"{Fore.GREEN}Idioma selecionado: {self.language}{Style.RESET_ALL}")

    def toggle_timestamps(self) -> None:
        self.timestamps = not self.timestamps
        status = "ativada" if self.timestamps else "desativada"
        print(f"{Fore.GREEN}Marcação de tempo {status}.{Style.RESET_ALL}")

    def toggle_diarize(self) -> None:
        self.diarize = not self.diarize
        if not self.diarize:
            self.num_speakers = None
            print(f"{Fore.GREEN}Identificação de locutores desativada.{Style.RESET_ALL}")
            return
        answer = input("Número de locutores, se conhecido (Enter = detectar automaticamente): ").strip()
        self.num_speakers = parse_num_speakers(answer)
        if answer and self.num_speakers is None:
            raise ValueError("Número de locutores inválido; identificação mantida em modo automático.")
        print(f"{Fore.GREEN}Identificação de locutores ativada ({self.speakers_label()}).{Style.RESET_ALL}")

    def speakers_label(self) -> str:
        return f"{self.num_speakers} locutor(es)" if self.num_speakers else "número automático"

    def choose_device(self) -> None:
        print(f"\n{Fore.CYAN}Dispositivos:{Style.RESET_ALL}")
        device_items = list(DEVICE_OPTIONS.items())
        for idx, (code, label) in enumerate(device_items, start=1):
            marker = "(atual)" if code == self.device else ""
            print(f"  {idx}. {label} [{code}] {marker}")

        selected = input("Escolha o número do dispositivo: ").strip()
        if not selected.isdigit() or int(selected) < 1 or int(selected) > len(device_items):
            raise ValueError("Dispositivo inválido.")

        self.device = device_items[int(selected) - 1][0]
        print(f"{Fore.GREEN}Dispositivo selecionado: {self.device}{Style.RESET_ALL}")

    def build_selection(self) -> MenuSelection:
        selected_files = [self.files[i - 1] for i in self.selected_indexes]
        return MenuSelection(
            selected_files=selected_files,
            model_name=self.model_name,
            language=self.language,
            timestamps=self.timestamps,
            device=self.device,
            diarize=self.diarize,
            num_speakers=self.num_speakers,
        )

    def run(self) -> MenuSelection:
        while True:
            self.display_files()
            print(f"\n{Fore.YELLOW}Configuração atual:{Style.RESET_ALL}")
            print(f"  Modelo: {self.model_name}")
            print(f"  Idioma: {self.language}")
            print(f"  Marcação de tempo: {'sim' if self.timestamps else 'não'}")
            diarize_info = f"sim ({self.speakers_label()})" if self.diarize else "não"
            print(f"  Identificar locutores: {diarize_info}")
            print(f"  Dispositivo: {self.device}")
            print(f"  Selecionados: {len(self.selected_indexes)} arquivo(s)")

            print(f"\n{Fore.MAGENTA}Menu:{Style.RESET_ALL}")
            print("  1. Selecionar todos os arquivos")
            print("  2. Selecionar arquivos específicos")
            print("  3. Escolher modelo de transcrição")
            print("  4. Configurar idioma")
            print("  5. Ligar/desligar marcação de tempo")
            print("  6. Ligar/desligar identificação de locutores")
            print("  7. Escolher dispositivo (CPU/GPU)")
            print(f"  {Fore.GREEN}I. Iniciar transcrição{Style.RESET_ALL}")
            print("  0. Sair")

            option = input("Escolha uma opção: ").strip().upper()

            try:
                if option == "1":
                    self.choose_all_files()
                elif option == "2":
                    self.choose_specific_files()
                elif option == "3":
                    self.choose_model()
                elif option == "4":
                    self.choose_language()
                elif option == "5":
                    self.toggle_timestamps()
                elif option == "6":
                    self.toggle_diarize()
                elif option == "7":
                    self.choose_device()
                elif option == "I":
                    if not self.selected_indexes:
                        raise ValueError("Nenhum arquivo selecionado para transcrever.")
                    return self.build_selection()
                elif option == "0":
                    raise KeyboardInterrupt
                else:
                    print(f"{Fore.RED}Opção inválida. Tente novamente.{Style.RESET_ALL}")
            except ValueError as exc:
                print(f"{Fore.RED}Erro: {exc}{Style.RESET_ALL}")
