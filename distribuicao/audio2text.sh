#!/usr/bin/env bash
# audio2text - abre a página de transcrição no navegador (Linux).
#
# Uso: ./audio2text.sh                  usa a pasta do caso definida no config.txt
#      ./audio2text.sh /pasta/do/caso   usa essa pasta só nesta execução
set -uo pipefail

VERSAO="0.3.0"
VOLUME="audio2text-modelos"
CONTAINER="audio2text-web"
IMAGEM_COMPLETA="audio2text:$VERSAO-completa"
IMAGEM_LEVE="audio2text:$VERSAO-leve"
DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG="$DIR/config.txt"

pausar() { if [ -t 0 ]; then read -rp "Pressione Enter para fechar..." _; fi; }
falha() { echo; echo "ERRO: $*" >&2; echo; pausar; exit 1; }
abrir() { xdg-open "$1" >/dev/null 2>&1 || true; }

# Lê CHAVE=valor do config.txt (ignora comentários, marcador BOM e \r do Windows).
ler_config() {
    sed '1s/^\xEF\xBB\xBF//' "$CONFIG" | tr -d '\r' | grep -E "^$1=" | tail -n 1 | cut -d= -f2- | sed 's/^"//; s/"$//'
}

# --- Configuração -----------------------------------------------------------
if [ ! -f "$CONFIG" ]; then
    falha "Arquivo de configuração não encontrado: $CONFIG
Copie o config.txt do pacote para esta pasta e informe a PASTA_AUDIOS."
fi

if [ $# -ge 1 ]; then
    AUDIOS_ARG="$1"
    SAIDA_ARG="${2:-}"
else
    AUDIOS_ARG="$(ler_config PASTA_AUDIOS)"
    SAIDA_ARG="$(ler_config PASTA_TRANSCRICOES)"
fi
PORTA="$(ler_config PORTA)"
PORTA="${PORTA:-8765}"
[[ "$PORTA" =~ ^[0-9]+$ ]] || falha "PORTA inválida no config.txt: $PORTA"

if [ -z "$AUDIOS_ARG" ]; then
    abrir "$CONFIG"
    falha "Informe a pasta do caso em PASTA_AUDIOS no config.txt ($CONFIG) e execute de novo."
fi

# --- Pastas -----------------------------------------------------------------
AUDIOS="$(realpath -m -- "$AUDIOS_ARG")"
[ "$AUDIOS" = "/" ] && falha "Escolha a pasta do caso, não a raiz do disco."
[ -d "$AUDIOS" ] || falha "A pasta de áudios não existe: $AUDIOS"

if [ -n "$SAIDA_ARG" ]; then
    SAIDA="$(realpath -m -- "$SAIDA_ARG")"
else
    SAIDA="${AUDIOS}_transcricoes"
fi
[ "$SAIDA" = "/" ] && falha "Escolha uma pasta de transcrições, não a raiz do disco."
# A pasta de transcrições nunca pode ser a pasta dos áudios nem ficar dentro dela.
case "$SAIDA/" in
    "$AUDIOS"/*) falha "A pasta de transcrições ($SAIDA) não pode ser a pasta dos áudios nem ficar dentro dela." ;;
esac
mkdir -p -- "$SAIDA" 2>/dev/null && [ -w "$SAIDA" ] \
    || falha "Não foi possível criar ou gravar na pasta de transcrições: $SAIDA"

# --- Docker -----------------------------------------------------------------
command -v docker >/dev/null || falha "Docker não encontrado. Instale o Docker (veja o LEIA-ME)."
if ! ERRO_DOCKER="$(docker info 2>&1 >/dev/null)"; then
    if grep -qi "permission denied" <<<"$ERRO_DOCKER"; then
        falha "Seu usuário não tem permissão para usar o Docker. Rode:
    sudo usermod -aG docker \$USER
e depois saia e entre de novo na sessão."
    fi
    falha "O Docker não está em execução. Inicie-o (ex.: sudo systemctl start docker) e tente de novo."
fi

# Já existe uma página aberta? Reaproveita, em vez de abrir uma segunda.
if [ -n "$(docker ps -q --filter "name=^/${CONTAINER}$")" ]; then
    AMBIENTE="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$CONTAINER")"
    TOKEN_EXIST="$(grep '^AT_TOKEN=' <<<"$AMBIENTE" | cut -d= -f2-)"
    AUDIOS_EXIST="$(grep '^AT_HOST_AUDIOS=' <<<"$AMBIENTE" | cut -d= -f2-)"
    PORTA_EXIST="$(grep '^AT_PORTA_HOST=' <<<"$AMBIENTE" | cut -d= -f2-)"
    URL="http://127.0.0.1:${PORTA_EXIST}/?token=${TOKEN_EXIST}"
    abrir "$URL"
    if [ "$AUDIOS_EXIST" != "$AUDIOS" ]; then
        echo "Já existe uma sessão aberta com outra pasta: $AUDIOS_EXIST"
        echo "Ela foi aberta no navegador. Para trocar de pasta, clique em Encerrar na página"
        echo "e execute o audio2text.sh de novo."
    else
        echo "O audio2text já estava aberto; a página foi aberta no navegador."
    fi
    echo "Endereço: $URL"
    pausar
    exit 0
fi

if docker image inspect "$IMAGEM_COMPLETA" >/dev/null 2>&1; then
    IMAGEM="$IMAGEM_COMPLETA"
elif docker image inspect "$IMAGEM_LEVE" >/dev/null 2>&1; then
    IMAGEM="$IMAGEM_LEVE"
else
    falha "Nenhuma imagem do audio2text $VERSAO instalada. Carregue-a com: docker load -i audio2text-$VERSAO-leve.tar.gz"
fi

# --- GPU --------------------------------------------------------------------
GPU=()
GPU_NOME=""
DISPOSITIVO="cpu"
if [ "$IMAGEM" = "$IMAGEM_COMPLETA" ] && command -v nvidia-smi >/dev/null; then
    echo "Verificando a GPU NVIDIA..."
    if docker run --rm --gpus all --entrypoint python "$IMAGEM" -c \
        "import sys, ctranslate2; sys.exit(0 if ctranslate2.get_cuda_device_count() > 0 else 1)" >/dev/null 2>&1; then
        GPU=(--gpus all)
        DISPOSITIVO="auto"
        GPU_NOME="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n 1)"
    else
        echo "Aviso: há GPU NVIDIA, mas o Docker não conseguiu usá-la (falta o NVIDIA Container Toolkit?)."
        echo "A transcrição usará a CPU."
    fi
fi

# --- Execução ---------------------------------------------------------------
TOKEN="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
# Fuso horário do computador, para as datas das transcrições (o container usa UTC).
FUSO="$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || echo UTC)"
echo
echo "audio2text $VERSAO - imagem: $IMAGEM - GPU: $([ ${#GPU[@]} -gt 0 ] && echo sim || echo não)"
echo "Pasta do caso (somente leitura): $AUDIOS"
echo "Transcrições:                    $SAIDA"

docker run -d --rm --name "$CONTAINER" \
    -p "127.0.0.1:${PORTA}:8000" \
    --user "$(id -u):$(id -g)" -e HOME=/tmp \
    "${GPU[@]}" \
    -v "$AUDIOS:/dados:ro" \
    -v "$SAIDA:/saida" \
    -v "$VOLUME:/modelos" \
    -e "AT_TOKEN=$TOKEN" \
    -e "AT_HOST_AUDIOS=$AUDIOS" \
    -e "AT_HOST_SAIDA=$SAIDA" \
    -e "AT_GPU_NOME=$GPU_NOME" \
    -e "AT_DISPOSITIVO=$DISPOSITIVO" \
    -e "AT_PORTA_HOST=$PORTA" \
    -e "TZ=$FUSO" \
    --entrypoint python "$IMAGEM" -m audio_transcription_tool.web >/dev/null \
    || falha "Não foi possível iniciar o audio2text. A porta $PORTA pode estar em uso: troque PORTA no config.txt."

echo -n "Iniciando"
for _ in $(seq 1 60); do
    if curl -sf -o /dev/null "http://127.0.0.1:${PORTA}/saude" 2>/dev/null \
        || wget -q -O /dev/null "http://127.0.0.1:${PORTA}/saude" 2>/dev/null; then
        PRONTO=1
        break
    fi
    echo -n "."
    sleep 1
done
echo
[ "${PRONTO:-0}" = 1 ] || falha "A página não respondeu. Veja o motivo com: docker logs $CONTAINER"

URL="http://127.0.0.1:${PORTA}/?token=${TOKEN}"
abrir "$URL"
echo
echo "A página foi aberta no navegador. Se não abriu, acesse:"
echo "  $URL"
echo "Para encerrar o audio2text, use o botão Encerrar na página."
pausar
