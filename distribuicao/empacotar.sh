#!/usr/bin/env bash
# Gera o pacote de distribuição para os peritos (Windows): os scripts, o LEIA-ME, o relato
# de teste e as imagens Docker, que vão junto (.tar.gz) ou são publicadas no Docker Hub.
#
# Uso (na raiz do projeto):  distribuicao/empacotar.sh [leve|completa|todas] [--publicar]
#   leve|completa|todas  variantes a gerar (padrão: todas)
#   --publicar           envia a imagem ao Docker Hub ($REPOSITORIO) em vez de incluí-la no
#                        pacote; o instalar.bat a baixa com docker pull. Só para a leve, pois
#                        a completa traz o modelo do pyannote, de acesso restrito.
#                        Requer docker login com um token de leitura e escrita.
#
# Pacotes: dist/audio2text-<versão>/ (com as imagens) ou dist/audio2text-<versão>-online/.
# A variante completa baixa o modelo de locutores do Hugging Face durante o build e
# precisa de um token com os termos do modelo aceitos (hf auth login).
set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
cd "$RAIZ"

REPOSITORIO="silviotassini/audio2text"
VERSAO="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' audio_transcription_tool/version.py)"
TOKEN="${HF_TOKEN_FILE:-$HOME/.cache/huggingface/token}"
USO="Uso: $0 [leve|completa|todas] [--publicar]"

VARIANTES="leve completa"
PUBLICAR=0
for ARG in "$@"; do
    case "$ARG" in
        leve) VARIANTES="leve" ;;
        completa) VARIANTES="completa" ;;
        todas) VARIANTES="leve completa" ;;
        --publicar) PUBLICAR=1 ;;
        *) echo "$USO" >&2; exit 1 ;;
    esac
done
if [ "$PUBLICAR" = 1 ] && [ "$VARIANTES" != "leve" ]; then
    echo "--publicar só pode ser usado com a variante leve: $0 leve --publicar" >&2; exit 1
fi
DESTINO="dist/audio2text-$VERSAO"
[ "$PUBLICAR" = 1 ] && DESTINO="$DESTINO-online"

for ARQUIVO in transcrever.bat instalar.bat audio2text.bat audio2text.sh; do
    grep -q "$VERSAO" "distribuicao/$ARQUIVO" || {
        echo "A versão em distribuicao/$ARQUIVO não é $VERSAO" >&2; exit 1; }
done
grep -q "$REPOSITORIO" distribuicao/instalar.bat || {
    echo "O repositório em distribuicao/instalar.bat não é $REPOSITORIO" >&2; exit 1; }
if [[ " $VARIANTES " == *" completa "* ]]; then
    [ -s "$TOKEN" ] || { echo "Token do Hugging Face não encontrado em $TOKEN (rode: hf auth login, ou gere só a leve: $0 leve)" >&2; exit 1; }
fi

for VARIANTE in $VARIANTES; do
    echo "== Build audio2text:$VERSAO-$VARIANTE"
    if [ "$VARIANTE" = "completa" ]; then
        docker build --build-arg VARIANTE=completa --secret id=hf_token,src="$TOKEN" \
            -t "audio2text:$VERSAO-completa" .
    else
        docker build --build-arg VARIANTE=leve -t "audio2text:$VERSAO-leve" .
    fi
done

rm -rf "$DESTINO"
mkdir -p "$DESTINO"

for VARIANTE in $VARIANTES; do
    if [ "$PUBLICAR" = 1 ]; then
        echo "== Publicando $REPOSITORIO:$VERSAO-$VARIANTE"
        docker tag "audio2text:$VERSAO-$VARIANTE" "$REPOSITORIO:$VERSAO-$VARIANTE"
        docker push "$REPOSITORIO:$VERSAO-$VARIANTE"
    else
        echo "== Exportando audio2text-$VERSAO-$VARIANTE.tar.gz"
        docker save "audio2text:$VERSAO-$VARIANTE" | gzip -1 > "$DESTINO/audio2text-$VERSAO-$VARIANTE.tar.gz"
    fi
done

# Arquivos de texto e scripts com quebra de linha do Windows (CRLF).
for ARQUIVO in instalar.bat transcrever.bat audio2text.bat config.txt LEIA-ME.txt RELATO_DE_TESTE.txt; do
    sed 's/\r\{0,1\}$/\r/' "distribuicao/$ARQUIVO" > "$DESTINO/$ARQUIVO"
done
# Lançador do Linux: quebra de linha do Linux (LF) e permissão de execução.
sed 's/\r$//' distribuicao/audio2text.sh > "$DESTINO/audio2text.sh"
chmod +x "$DESTINO/audio2text.sh"
# Pacote só com a leve: LEIA-ME sem as referências à versão completa.
if [ "$VARIANTES" = "leve" ]; then
    sed 's/\r\{0,1\}$/\r/' distribuicao/LEIA-ME-leve.txt > "$DESTINO/LEIA-ME.txt"
fi

(cd "$DESTINO" && sha256sum -- * | grep -v SHA256SUMS > SHA256SUMS.txt)

echo
echo "Pacote pronto em $DESTINO:"
ls -lh "$DESTINO"
