# syntax=docker/dockerfile:1
#
# Duas variantes:
#   leve     : só CPU, sem identificação de locutores (imagem pequena)
#   completa : GPU NVIDIA (CUDA 12 / cuDNN 9) + identificação de locutores com o modelo
#              do pyannote embutido; também funciona sem GPU
#
#   docker build --build-arg VARIANTE=leve -t audio2text:0.3.0-leve .
#   docker build --build-arg VARIANTE=completa --secret id=hf_token,src=$HOME/.cache/huggingface/token \
#       -t audio2text:0.3.0-completa .
#
# O token do Hugging Face só é usado durante o build, para baixar o modelo do pyannote
# (licença CC-BY-4.0); ele não fica gravado na imagem.

FROM python:3.11-slim

ARG VARIANTE=leve
# Revisão fixa do modelo de locutores, para reprodutibilidade.
ARG PYANNOTE_MODELO=pyannote/speaker-diarization-community-1
ARG PYANNOTE_REVISAO=3533c8cf8e369892e6b79ff1bf80f7b0286a54ee

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYANNOTE_METRICS_ENABLED=false \
    HF_HOME=/modelos \
    LD_LIBRARY_PATH=/usr/local/lib/python3.11/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.11/site-packages/nvidia/cudnn/lib \
    AT_DIARIZATION_MODEL=/opt/modelos/speaker-diarization-community-1@3533c8c

RUN case "$VARIANTE" in leve|completa) ;; *) echo "VARIANTE deve ser leve ou completa" >&2; exit 1 ;; esac

RUN if [ "$VARIANTE" = "completa" ]; then \
        apt-get update && \
        apt-get install -y --no-install-recommends ffmpeg && \
        rm -rf /var/lib/apt/lists/*; \
    fi

WORKDIR /app

COPY requirements.txt requirements-gpu.txt requirements-diarizacao.txt ./
# Na completa, o PyTorch vem do build para CUDA 12.6: o build padrão (CUDA 13) não
# suporta GPUs Pascal (GTX 10xx). Tudo num único comando, com a versão +cu126 explícita,
# para o pip não trocar o PyTorch ao resolver as demais dependências.
RUN if [ "$VARIANTE" = "completa" ]; then \
        pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cu126 \
            "torch==2.14.1+cu126" -r requirements-gpu.txt -r requirements-diarizacao.txt && \
        python -c "import torch, sys; sys.exit(0 if torch.__version__.endswith('+cu126') else 'PyTorch errado: ' + torch.__version__)"; \
    else \
        pip install --no-cache-dir -r requirements.txt; \
    fi

RUN --mount=type=secret,id=hf_token,required=false \
    if [ "$VARIANTE" = "completa" ]; then \
        test -s /run/secrets/hf_token || { echo "A variante completa precisa do token do Hugging Face (--secret id=hf_token,...)" >&2; exit 1; }; \
        HF_TOKEN="$(cat /run/secrets/hf_token)" python -c "from huggingface_hub import snapshot_download; snapshot_download('$PYANNOTE_MODELO', revision='$PYANNOTE_REVISAO', local_dir='$AT_DIARIZATION_MODEL')" && \
        rm -rf "$AT_DIARIZATION_MODEL/.cache"; \
    fi

# Usuário sem privilégios; /modelos guarda os modelos do Whisper baixados no primeiro uso
# (monte um volume nele para não baixar a cada execução).
RUN useradd --create-home --uid 1000 perito && \
    mkdir -p /modelos && chown perito /modelos && chmod 777 /modelos

COPY --chown=perito . .

# Esconde avisos do Hugging Face irrelevantes para o perito.
ENV HF_HUB_VERBOSITY=error

USER perito

LABEL org.opencontainers.image.title="audio2text" \
      org.opencontainers.image.version="0.3.0" \
      org.opencontainers.image.description="Transcrição de áudio para uso pericial (Whisper)"

ENTRYPOINT ["python", "transcriber.py"]
