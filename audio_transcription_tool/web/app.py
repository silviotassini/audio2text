"""Servidor da página web do audio2text.

Roda dentro do container. A pasta do caso é montada em /dados (somente leitura) e a pasta
de transcrições em /saida. O lançador publica a porta só em 127.0.0.1 e passa um token
aleatório: a página só abre pelo link que o lançador abre no navegador.
"""

from __future__ import annotations

import csv
import importlib.util
import logging
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import ctranslate2
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..transcriber_engine import TranscriberEngine, TranscricaoCancelada
from ..utils import (
    AUDIO_EXTENSIONS,
    DEFAULT_DIARIZATION_MODEL,
    DEVICE_OPTIONS,
    LANGUAGE_OPTIONS,
    MODEL_DESCRIPTIONS,
    SUPPORTED_MODELS,
)
from ..version import __version__

PASTA_AUDIOS = Path(os.environ.get("AT_PASTA_AUDIOS", "/dados"))
PASTA_SAIDA = Path(os.environ.get("AT_PASTA_SAIDA", "/saida"))
# Caminhos no computador do perito, só para exibição.
HOST_AUDIOS = os.environ.get("AT_HOST_AUDIOS", str(PASTA_AUDIOS))
HOST_SAIDA = os.environ.get("AT_HOST_SAIDA", str(PASTA_SAIDA))
GPU_NOME = os.environ.get("AT_GPU_NOME", "").strip()
DISPOSITIVO_PADRAO = os.environ.get("AT_DISPOSITIVO", "auto")
TOKEN = os.environ.get("AT_TOKEN") or secrets.token_urlsafe(24)
COOKIE = "audio2text_sessao"
HOSTS_PERMITIDOS = {"127.0.0.1", "localhost"}
LIMITE_LEITURA = 5 * 1024 * 1024

ESTATICOS = Path(__file__).parent / "static"

# Segundos de processamento por segundo de áudio, aproximados (para a estimativa inicial;
# durante a transcrição a estimativa usa a velocidade medida).
VELOCIDADE = {
    "cpu": {"base": 0.08, "small": 0.2, "medium": 0.6, "large-v3": 1.2, "turbo": 0.5},
    "cuda": {"base": 0.02, "small": 0.04, "medium": 0.08, "large-v3": 0.15, "turbo": 0.06},
}
VELOCIDADE_LOCUTORES = {"cpu": 0.15, "cuda": 0.03}

logger = logging.getLogger("audio2text.web")

# Telemetria do FastAPI (OpenTelemetry) desligada: nenhum dado do exame sai da máquina.
app = FastAPI(
    title="audio2text",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    telemetry={
        "auto_configure": False,
        "tracing": False,
        "metrics": False,
        "logs": False,
        "operation_spans": False,
    },
)


def locutores_disponivel() -> bool:
    try:
        return importlib.util.find_spec("pyannote.audio") is not None
    except ModuleNotFoundError:
        return False


# --- Segurança --------------------------------------------------------------

@app.middleware("http")
async def protecao(request: Request, call_next):
    # Só aceita o endereço local (evita que outro site use o navegador do perito para
    # acessar a ferramenta por "DNS rebinding").
    host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
    if host not in HOSTS_PERMITIDOS:
        return PlainTextResponse("Acesso permitido só pelo próprio computador.", status_code=403)

    if request.url.path == "/saude":
        return await call_next(request)

    token_url = request.query_params.get("token")
    if token_url is not None:
        if not secrets.compare_digest(token_url, TOKEN):
            return HTMLResponse(PAGINA_SEM_ACESSO, status_code=401)
        # Troca o token da URL por um cookie e limpa o endereço.
        resposta = RedirectResponse("/", status_code=303)
        resposta.set_cookie(COOKIE, TOKEN, httponly=True, samesite="strict")
        return resposta

    if not secrets.compare_digest(request.cookies.get(COOKIE, ""), TOKEN):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Sessão inválida. Abra pelo lançador."}, status_code=401)
        return HTMLResponse(PAGINA_SEM_ACESSO, status_code=401)

    resposta = await call_next(request)
    resposta.headers["Cache-Control"] = "no-store"
    resposta.headers["X-Content-Type-Options"] = "nosniff"
    resposta.headers["X-Frame-Options"] = "DENY"
    return resposta


PAGINA_SEM_ACESSO = """<!doctype html><meta charset="utf-8"><title>audio2text</title>
<body style="font-family:sans-serif;max-width:40em;margin:4em auto;line-height:1.5">
<h1>audio2text</h1><p>Esta página só pode ser aberta pelo lançador
(<b>audio2text.bat</b> no Windows ou <b>audio2text.sh</b> no Linux).</p>
<p>Feche esta aba e execute o lançador novamente.</p></body>"""


def dentro_de(base: Path, relativo: str) -> Path:
    """Resolve um caminho relativo garantindo que ele fique dentro da pasta base."""
    caminho = (base / relativo).resolve()
    if caminho != base.resolve() and base.resolve() not in caminho.parents:
        raise HTTPException(400, "Caminho inválido.")
    return caminho


# --- Arquivos ---------------------------------------------------------------

_cache_duracao: Dict[tuple, Optional[float]] = {}


def duracao_audio(caminho: Path) -> Optional[float]:
    info = caminho.stat()
    chave = (str(caminho), info.st_size, info.st_mtime)
    if chave not in _cache_duracao:
        try:
            import av

            with av.open(str(caminho)) as c:
                _cache_duracao[chave] = c.duration / 1_000_000 if c.duration else None
        except Exception:  # noqa: BLE001
            _cache_duracao[chave] = None
    return _cache_duracao[chave]


def listar_audios() -> List[Path]:
    if not PASTA_AUDIOS.is_dir():
        return []
    return sorted(
        (
            p
            for p in PASTA_AUDIOS.rglob("*")
            if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS and not p.name.startswith(".")
        ),
        key=lambda p: str(p.relative_to(PASTA_AUDIOS)).lower(),
    )


def transcricoes_de(relativo: Path) -> List[str]:
    """Transcrições já existentes de um áudio: nome.ext.txt, nome.ext_2.txt..."""
    pasta = PASTA_SAIDA / relativo.parent
    if not pasta.is_dir():
        return []
    padrao = re.compile(re.escape(relativo.name) + r"(_\d+)?\.txt$")
    return sorted(
        str((pasta / n).relative_to(PASTA_SAIDA)) for n in os.listdir(pasta) if padrao.fullmatch(n)
    )


def resumo_cabecalho(caminho: Path) -> Dict[str, str]:
    """Lê do cabeçalho de uma transcrição o modelo, a data e a origem."""
    dados: Dict[str, str] = {}
    try:
        with caminho.open(encoding="utf-8", errors="replace") as fp:
            for _ in range(20):
                linha = fp.readline()
                if not linha.startswith("#"):
                    break
                for chave, rotulo in (
                    ("modelo", "# Modelo:"),
                    ("gerado_em", "# Gerado em:"),
                    ("origem", "# Arquivo de origem:"),
                    ("ferramenta", "# Ferramenta:"),
                ):
                    if linha.startswith(rotulo):
                        dados[chave] = linha[len(rotulo):].strip()
        if "gerado_em" in dados:
            try:
                data = datetime.strptime(dados["gerado_em"][:19], "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M")
                dados["gerado_em"] = data + dados["gerado_em"][19:]
            except ValueError:
                pass
    except OSError:
        pass
    return dados


# --- Trabalho de transcrição ------------------------------------------------

@dataclass
class Trabalho:
    estado: str = "ocioso"  # ocioso, carregando, transcrevendo, concluido, cancelado, erro
    mensagem: str = ""
    arquivos: List[str] = field(default_factory=list)
    duracoes: List[float] = field(default_factory=list)
    indice: int = 0
    progresso_arquivo: float = 0.0
    inicio: float = 0.0
    fim: float = 0.0
    segundos_processados: float = 0.0
    tempo_processamento: float = 0.0
    resultados: List[Dict[str, Any]] = field(default_factory=list)
    relatorio: Optional[str] = None
    opcoes: Dict[str, Any] = field(default_factory=dict)
    cancelar: bool = False


trabalho = Trabalho()
trava = threading.Lock()
_motor: Optional[TranscriberEngine] = None
_motor_chave: Optional[tuple] = None


def obter_motor(modelo: str, dispositivo: str, locutores: bool, num_locutores: Optional[int]) -> TranscriberEngine:
    global _motor, _motor_chave
    chave = (modelo, dispositivo, locutores)
    if _motor is None or _motor_chave != chave:
        _motor = TranscriberEngine(
            model_name=modelo,
            logger=logger,
            device=dispositivo,
            diarize=locutores,
            diarization_model=os.environ.get("AT_DIARIZATION_MODEL", DEFAULT_DIARIZATION_MODEL),
        )
        _motor_chave = chave
    _motor.num_speakers = num_locutores
    return _motor


def executar(opcoes: Dict[str, Any]) -> None:
    t = trabalho
    try:
        motor = obter_motor(opcoes["modelo"], opcoes["dispositivo"], opcoes["locutores"], opcoes["num_locutores"])
        motor.load_model()
    except Exception as exc:  # noqa: BLE001
        t.estado, t.mensagem, t.fim = "erro", f"Não foi possível carregar o modelo: {exc}", time.time()
        return

    t.opcoes["dispositivo_usado"] = f"{motor.device} ({motor.compute_type})"
    t.estado = "transcrevendo"
    for indice, relativo in enumerate(t.arquivos):
        if t.cancelar:
            break
        t.indice, t.progresso_arquivo = indice, 0.0
        origem = PASTA_AUDIOS / relativo
        destino = PASTA_SAIDA / Path(relativo).parent
        inicio_arquivo = time.perf_counter()

        def progresso(feito: float, total: float) -> None:
            if t.cancelar:
                raise TranscricaoCancelada()
            t.progresso_arquivo = min(feito / total, 1.0) if total else 0.0

        try:
            destino.mkdir(parents=True, exist_ok=True)
            r = motor.transcribe_file(
                origem, destino, language=opcoes["idioma"], timestamps=opcoes["marcacao_tempo"],
                progress_callback=progresso,
            )
        except TranscricaoCancelada:
            break
        except Exception as exc:  # noqa: BLE001
            r = None
            erro = str(exc)

        t.tempo_processamento += time.perf_counter() - inicio_arquivo
        t.segundos_processados += t.duracoes[indice] or 0.0
        t.resultados.append(
            {
                "arquivo": relativo,
                "sucesso": bool(r and r.success),
                "transcricao": str(r.output_file.relative_to(PASTA_SAIDA)) if r and r.output_file else None,
                "erro": (r.error_message if r else erro) if not (r and r.success) else None,
                "idioma": r.language if r else None,
                "duracao": r.duration if r else None,
                "tempo": round(r.elapsed_seconds, 1) if r else None,
                "baixa_confianca": r.low_confidence_segments if r else 0,
                "trechos": r.total_segments if r else 0,
                "locutores": r.speakers if r else 0,
                "sha256_audio": r.audio_sha256 if r else None,
                "sha256_transcricao": r.output_sha256 if r else None,
            }
        )

    t.relatorio = gravar_relatorio(t)
    t.fim = time.time()
    t.estado = "cancelado" if t.cancelar else "concluido"


def gravar_relatorio(t: Trabalho) -> Optional[str]:
    if not t.resultados:
        return None
    nome = f"relatorio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    caminho = PASTA_SAIDA / nome
    # ";" e UTF-8 com BOM: abre corretamente no Excel em português.
    with caminho.open("x", encoding="utf-8-sig", newline="") as fp:
        w = csv.writer(fp, delimiter=";")
        w.writerow([
            "arquivo", "status", "transcricao", "sha256_audio", "sha256_transcricao", "duracao_s",
            "idioma", "modelo", "dispositivo", "ferramenta", "tempo_processamento_s",
            "trechos_baixa_confianca", "locutores", "erro",
        ])
        for r in t.resultados:
            w.writerow([
                r["arquivo"], "ok" if r["sucesso"] else "erro", r["transcricao"] or "",
                r["sha256_audio"] or "", r["sha256_transcricao"] or "",
                f"{r['duracao']:.1f}".replace(".", ",") if r["duracao"] else "",
                r["idioma"] or "", t.opcoes.get("modelo", ""), t.opcoes.get("dispositivo_usado", ""),
                f"audio2text {__version__}",
                f"{r['tempo']:.1f}".replace(".", ",") if r["tempo"] is not None else "",
                r["baixa_confianca"], r["locutores"], r["erro"] or "",
            ])
    return nome


# --- API --------------------------------------------------------------------

class PedidoFuso(BaseModel):
    fuso: str


def aplicar_fuso(fuso: str) -> bool:
    """Usa o fuso horário do navegador do perito (o container roda em UTC)."""
    if not re.fullmatch(r"[A-Za-z0-9_+\-]+(/[A-Za-z0-9_+\-]+)*", fuso or ""):
        return False
    if not (Path("/usr/share/zoneinfo") / fuso).is_file():
        return False
    os.environ["TZ"] = fuso
    time.tzset()
    return True


class PedidoTranscricao(BaseModel):
    arquivos: List[str]
    modelo: str = "base"
    idioma: str = "auto"
    marcacao_tempo: bool = False
    locutores: bool = False
    num_locutores: Optional[int] = None
    dispositivo: str = "auto"


def gpu_disponivel() -> bool:
    try:
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001
        return False


@app.get("/saude")
def saude():
    return {"ok": True}


@app.get("/")
def pagina():
    return FileResponse(ESTATICOS / "index.html")


@app.get("/api/estado")
def estado():
    gpu = gpu_disponivel()
    return {
        "versao": __version__,
        "pasta_audios": HOST_AUDIOS,
        "pasta_saida": HOST_SAIDA,
        "gpu": gpu,
        "gpu_nome": GPU_NOME if gpu else "",
        "dispositivo_padrao": DISPOSITIVO_PADRAO if gpu else "cpu",
        "locutores_disponivel": locutores_disponivel(),
        "modelos": [{"id": m, "descricao": MODEL_DESCRIPTIONS[m]} for m in SUPPORTED_MODELS],
        "idiomas": [{"id": k, "nome": v} for k, v in LANGUAGE_OPTIONS.items()],
        "dispositivos": [{"id": k, "nome": v} for k, v in DEVICE_OPTIONS.items()],
        "velocidade": VELOCIDADE,
        "velocidade_locutores": VELOCIDADE_LOCUTORES,
    }


@app.post("/api/fuso")
def definir_fuso(pedido: PedidoFuso):
    return {"ok": aplicar_fuso(pedido.fuso), "fuso": os.environ.get("TZ", "UTC")}


@app.get("/api/audios")
def audios():
    itens = []
    for p in listar_audios():
        relativo = p.relative_to(PASTA_AUDIOS)
        itens.append(
            {
                "arquivo": str(relativo),
                "tamanho": p.stat().st_size,
                "duracao": duracao_audio(p),
                "transcricoes": transcricoes_de(relativo),
            }
        )
    return {"pasta_existe": PASTA_AUDIOS.is_dir(), "audios": itens}


@app.get("/api/transcricoes")
def transcricoes():
    itens = []
    if PASTA_SAIDA.is_dir():
        # Transcrições primeiro, relatórios do lote no fim.
        for p in sorted(PASTA_SAIDA.rglob("*"), key=lambda p: (p.suffix.lower() == ".csv", str(p).lower())):
            if not p.is_file() or p.suffix.lower() not in {".txt", ".csv"}:
                continue
            info = p.stat()
            item = {
                "arquivo": str(p.relative_to(PASTA_SAIDA)),
                "tipo": "relatorio" if p.suffix.lower() == ".csv" else "transcricao",
                "tamanho": info.st_size,
                "modificado": datetime.fromtimestamp(info.st_mtime).strftime("%d/%m/%Y %H:%M"),
            }
            if item["tipo"] == "transcricao":
                item.update(resumo_cabecalho(p))
            itens.append(item)
    return {"arquivos": itens}


@app.get("/api/arquivo")
def ler_arquivo(caminho: str):
    alvo = dentro_de(PASTA_SAIDA, caminho)
    if not alvo.is_file() or alvo.suffix.lower() not in {".txt", ".csv"}:
        raise HTTPException(404, "Arquivo não encontrado.")
    if alvo.stat().st_size > LIMITE_LEITURA:
        raise HTTPException(413, "Arquivo grande demais para exibir; abra-o pela pasta.")
    return PlainTextResponse(alvo.read_text(encoding="utf-8-sig", errors="replace"))


@app.post("/api/iniciar")
def iniciar(pedido: PedidoTranscricao):
    global trabalho
    if pedido.modelo not in SUPPORTED_MODELS:
        raise HTTPException(400, "Modelo inválido.")
    if pedido.idioma not in LANGUAGE_OPTIONS:
        raise HTTPException(400, "Idioma inválido.")
    if pedido.dispositivo not in DEVICE_OPTIONS:
        raise HTTPException(400, "Dispositivo inválido.")
    if pedido.locutores and not locutores_disponivel():
        raise HTTPException(400, "A identificação de locutores não está disponível nesta versão.")
    if not pedido.arquivos:
        raise HTTPException(400, "Nenhum arquivo selecionado.")
    validos = {str(p.relative_to(PASTA_AUDIOS)) for p in listar_audios()}
    if any(a not in validos for a in pedido.arquivos):
        raise HTTPException(400, "Arquivo fora da pasta do caso.")

    with trava:
        if trabalho.estado in {"carregando", "transcrevendo"}:
            raise HTTPException(409, "Já há uma transcrição em andamento.")
        opcoes = pedido.model_dump()
        opcoes["num_locutores"] = pedido.num_locutores if pedido.locutores and pedido.num_locutores else None
        trabalho = Trabalho(
            estado="carregando",
            arquivos=list(pedido.arquivos),
            duracoes=[duracao_audio(PASTA_AUDIOS / a) or 0.0 for a in pedido.arquivos],
            inicio=time.time(),
            opcoes=opcoes,
        )
    threading.Thread(target=executar, args=(opcoes,), daemon=True).start()
    return {"ok": True}


@app.get("/api/progresso")
def progresso():
    t = trabalho
    total_audio = sum(t.duracoes)
    feito_audio = t.segundos_processados
    if t.estado == "transcrevendo" and t.indice < len(t.duracoes):
        feito_audio += t.duracoes[t.indice] * t.progresso_arquivo
    restante = None
    if t.estado == "transcrevendo" and t.segundos_processados > 0:
        velocidade = t.tempo_processamento / t.segundos_processados
        restante = max(total_audio - feito_audio, 0) * velocidade
    fim = t.fim or time.time()
    return {
        "estado": t.estado,
        "mensagem": t.mensagem,
        "total": len(t.arquivos),
        "indice": t.indice,
        "arquivo_atual": t.arquivos[t.indice] if t.arquivos and t.indice < len(t.arquivos) else None,
        "progresso_arquivo": t.progresso_arquivo,
        "progresso_geral": (feito_audio / total_audio) if total_audio else 0.0,
        "decorrido": (fim - t.inicio) if t.inicio else 0,
        "restante": restante,
        "resultados": t.resultados,
        "relatorio": t.relatorio,
        "opcoes": t.opcoes,
    }


@app.post("/api/cancelar")
def cancelar():
    if trabalho.estado in {"carregando", "transcrevendo"}:
        trabalho.cancelar = True
    return {"ok": True}


@app.post("/api/encerrar")
def encerrar(forcar: bool = False):
    if trabalho.estado in {"carregando", "transcrevendo"} and not forcar:
        raise HTTPException(409, "Há uma transcrição em andamento.")
    trabalho.cancelar = True
    # Responde antes de encerrar o processo (o container é removido ao terminar).
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return {"ok": True}


app.mount("/static", StaticFiles(directory=ESTATICOS), name="static")
