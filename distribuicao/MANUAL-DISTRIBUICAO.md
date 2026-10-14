# Manual de distribuição do audio2text

Como gerar, publicar e enviar as imagens Docker do audio2text aos peritos.
Este arquivo é só para quem mantém a ferramenta: não entra nos pacotes nem na imagem.

## 1. Visão geral

**Variantes da imagem** (definidas no `Dockerfile`, argumento `VARIANTE`):

| Variante | Conteúdo | Tamanho | Distribuição |
|---|---|---|---|
| `leve` | só CPU, sem identificação de locutores | ~185 MB compactada | Docker Hub (público) ou `.tar.gz` |
| `completa` | GPU NVIDIA + locutores (modelo pyannote embutido) | vários GB | só `.tar.gz` (ver seção 4) |

**Pacotes gerados** pelo `distribuicao/empacotar.sh` em `dist/`:

| Comando | Pacote | Conteúdo |
|---|---|---|
| `empacotar.sh leve --publicar` | `dist/audio2text-<versão>-online/` | só scripts; a imagem é baixada do Docker Hub |
| `empacotar.sh leve` | `dist/audio2text-<versão>/` | scripts + `audio2text-<versão>-leve.tar.gz` |
| `empacotar.sh completa` | `dist/audio2text-<versão>/` | scripts + `audio2text-<versão>-completa.tar.gz` |
| `empacotar.sh` (ou `todas`) | `dist/audio2text-<versão>/` | scripts + as duas imagens |

Cada execução apaga e recria a pasta de destino.

**Como o perito instala:** o `instalar.bat` carrega os `.tar.gz` que estiverem na pasta.
Se não houver nenhum, baixa `silviotassini/audio2text:<versão>-leve` do Docker Hub.
O `transcrever.bat` usa a completa, se estiver instalada; senão, a leve.

Os scripts dos peritos são só `.bat`, sem PowerShell: em máquinas institucionais a
política de grupo costuma bloquear scripts `.ps1` (o `-ExecutionPolicy Bypass` não vence
uma política definida por GPO), e essa política não se aplica a `.bat`. Não reintroduza
PowerShell nos scripts de distribuição.

## 2. Pré-requisitos (uma vez só)

- **Docker Desktop** em execução ("Engine running").
- **Git Bash**: o `empacotar.sh` é um script bash. Use o Git Bash, não o `bash` do
  PowerShell (que é o do WSL). Pelo PowerShell:
  `& "C:\Program Files\Git\bin\bash.exe" distribuicao/empacotar.sh leve`
- **Login no Docker Hub** (só para `--publicar`), feito numa janela do PowerShell fora do
  Claude Code ou pelo botão *Sign in* do Docker Desktop:
  ```powershell
  docker login -u silviotassini
  ```
  Use como senha um *Personal Access Token* com permissão **Read & Write**
  (hub.docker.com → Account settings → Personal access tokens). Um token só de leitura dá
  o erro `access token has insufficient scopes`.
- **Token do Hugging Face** (só para a completa): ver seção 4.

## 3. Publicar uma nova versão (leve)

Sempre que o código mudar, gere uma **versão nova**. Não republique a mesma tag com outro
conteúdo: a versão vai no cabeçalho de cada transcrição, e um laudo precisa indicar
exatamente qual ferramenta o gerou.

### 3.1 Atualizar o número da versão

Troque a versão (ex.: `0.2.0` → `0.3.0`) em todos estes arquivos:

| Arquivo | Onde |
|---|---|
| `audio_transcription_tool/version.py` | `__version__` (é a referência do `empacotar.sh`) |
| `Dockerfile` | `LABEL org.opencontainers.image.version` e os exemplos nos comentários |
| `distribuicao/transcrever.bat` | `set "VERSAO=` |
| `distribuicao/instalar.bat` | `set VERSAO=` |
| `distribuicao/audio2text.bat` | `set "VERSAO=` |
| `distribuicao/audio2text.sh` | `VERSAO=` |
| `distribuicao/LEIA-ME.txt` | título e nomes dos `.tar.gz` |
| `distribuicao/LEIA-ME-leve.txt` | título e nome do `.tar.gz` |
| `distribuicao/RELATO_DE_TESTE.txt` | título |
| `README.md` | exemplos de comandos |

Para achar o que faltou (no Git Bash, na raiz do projeto):
```bash
grep -rn "0\.2\.0" --exclude-dir={.venv,dist,tmp} .
```
O `empacotar.sh` para com erro se a versão do `transcrever.bat`, do `instalar.bat`, do
`audio2text.bat` ou do `audio2text.sh` não
bater com o `version.py`. Os demais arquivos ele não confere.

Se a mudança afetar o uso (opção nova no menu, comportamento diferente), atualize também
os LEIA-ME.

### 3.2 Gerar, testar e publicar

```bash
cd /d/workspace/audio/audio2text

# 1. Pacote sem internet (gera a imagem e o .tar.gz) e teste local
distribuicao/empacotar.sh leve
```

Teste antes de publicar (seção 5). Estando tudo certo:

```bash
# 2. Publica no Docker Hub e gera o pacote online
distribuicao/empacotar.sh leve --publicar
```

O `--publicar` reaproveita o cache do Docker, então é rápido. Ele envia
`silviotassini/audio2text:<versão>-leve` e cria `dist/audio2text-<versão>-online/`.
Rode o pacote sem internet de novo depois, se quiser garantir que os dois saíram da
mesma imagem (`empacotar.sh leve`, cache também).

### 3.3 Conferir a publicação

```bash
docker buildx imagetools inspect silviotassini/audio2text:<versão>-leve
```
Para simular um perito, apague as imagens locais e rode o `instalar.bat` do pacote online:
```powershell
docker rmi audio2text:<versão>-leve silviotassini/audio2text:<versão>-leve
```
(Depois disso, o próximo build recompila a última camada e a tag publicada pode ganhar um
digest novo ao republicar; o código é o mesmo.)

### 3.4 Enviar

- Compacte `dist/audio2text-<versão>-online/` num `.zip` (poucos KB) e envie.
- Guarde `dist/audio2text-<versão>/` (com o `.tar.gz`) para quem estiver numa rede que
  bloqueia o Docker Hub.
- Avise os peritos para **rodar o `instalar.bat` da versão nova**: os scripts antigos
  continuam apontando para a imagem antiga.

As versões antigas continuam no Docker Hub; não apague tags já distribuídas enquanto houver
laudos ou testes em andamento com elas.

## 4. Imagem completa (GPU + identificação de locutores)

### 4.1 Token do Hugging Face (uma vez só)

O modelo `pyannote/speaker-diarization-community-1` tem acesso restrito: o build precisa de
um token de uma conta que aceitou os termos.

1. Crie uma conta em https://huggingface.co (grátis).
2. Abra https://huggingface.co/pyannote/speaker-diarization-community-1 e aceite os termos.
3. Crie um token de leitura (*Read*) em https://huggingface.co/settings/tokens.
4. Faça o login (grava o token em `~/.cache/huggingface/token`), numa janela do PowerShell:
   ```powershell
   D:\workspace\audio\audio2text\.venv\Scripts\hf.exe auth login
   ```

O token só é usado durante o build e não fica gravado na imagem. O modelo, sim, fica dentro
da imagem, na revisão fixada no `Dockerfile` (`PYANNOTE_REVISAO`).

### 4.2 Gerar

No Git Bash, passando o caminho do token no formato do Windows (o `$HOME` do Git Bash,
`/c/Users/...`, não é entendido pelo `docker.exe`):

```bash
cd /d/workspace/audio/audio2text
HF_TOKEN_FILE="$(cygpath -m ~/.cache/huggingface/token)" distribuicao/empacotar.sh completa
```

Use `todas` no lugar de `completa` para um pacote com as duas variantes.

- O primeiro build demora (PyTorch com CUDA, vários GB) e precisa de bastante espaço em disco.
- O pacote sai em `dist/audio2text-<versão>/` com o `LEIA-ME.txt` completo (o que cita
  GPU e locutores).
- O PyTorch é o build `+cu126` de propósito: o padrão (CUDA 13) não funciona em GPUs Pascal
  (GTX 10xx). O Dockerfile falha se o pip trocar essa versão.

### 4.3 Testar

Com GPU NVIDIA na máquina, além do checklist da seção 5:

- Rode o `transcrever.bat` do pacote: a tela deve mostrar `imagem: audio2text:<versão>-completa | GPU: sim`.
- Ative a opção 6 (locutores) e confira se aparecem `LOCUTOR 1`, `LOCUTOR 2`...
- Teste também sem GPU: `transcrever.bat "C:\pasta\audios" -SemGpu`.
- Para forçar uma variante quando as duas estão instaladas:
  `transcrever.bat "C:\pasta\audios" -Variante leve` (ou `-Variante completa`).

### 4.4 Enviar

A completa **não** vai para o Docker Hub público: o `--publicar` recusa essa variante,
porque a imagem traz o modelo do pyannote, cujo acesso o Hugging Face restringe a quem
aceitou os termos. Formas de enviar:

- **`.tar.gz` (recomendado):** compacte `dist/audio2text-<versão>/` e envie por rede interna,
  nuvem ou pendrive. O arquivo é grande; confira o `SHA256SUMS.txt` depois da cópia.
- **Repositório privado no Docker Hub:** possível, mas cada perito precisaria de conta e
  `docker login`, e o `instalar.bat`/`empacotar.sh` precisariam ser adaptados (hoje só fazem
  pull da leve).

Requisitos para o perito (já descritos no `LEIA-ME.txt`): driver NVIDIA atualizado
(série 580 para GTX 10xx) e cerca de 15 GB livres.

## 5. Checklist antes de enviar

- [ ] `instalar.bat` termina com "Pronto".
- [ ] `transcrever.bat` (arrastando uma pasta de teste) mostra a versão e a imagem certas.
- [ ] Transcrição com o modelo `base` gera os `.txt` em `<pasta>_transcricoes`.
- [ ] Os áudios originais não foram alterados.
- [ ] O cabeçalho do `.txt` mostra a versão nova.
- [ ] (completa) GPU usada e locutores identificados.
- [ ] O LEIA-ME do pacote corresponde à variante enviada.
- [ ] `sha256sum -c SHA256SUMS.txt` dentro da pasta do pacote dá tudo `OK`.

## 6. Problemas comuns

| Sintoma | Causa / solução |
|---|---|
| `cannot perform an interactive login from a non-TTY device` | `docker login` rodado pelo `!` do Claude Code. Rode numa janela do PowerShell ou use o *Sign in* do Docker Desktop. |
| `push access denied ... insufficient_scope` | Sem login no Docker Hub. |
| `access token has insufficient scopes` | Token sem escrita. Crie um *Read & Write*, `docker logout` e `docker login` de novo. |
| `Token do Hugging Face não encontrado` | Faltou `hf auth login` (seção 4.1) ou o `HF_TOKEN_FILE`. |
| Build da completa falha no download do modelo | Termos do modelo não aceitos na conta do token, ou token inválido. |
| `A versão em distribuicao/... não é X` | Faltou atualizar a versão nesse arquivo (seção 3.1). |
| `--publicar só pode ser usado com a variante leve` | Proposital (seção 4.4). |
| Perito: "Nenhuma imagem ... instalada" | Não rodou o `instalar.bat` da versão nova. |
| Perito: "O Windows protegeu o computador" (SmartScreen) | O `.zip` veio da internet/e-mail e o Windows marcou os arquivos. "Mais informações" > "Executar assim mesmo", ou desbloquear o `.zip` (Propriedades > Desbloquear) antes de extrair. Para eliminar de vez: distribuir por pasta de rede interna ou pedir à TI uma exceção. |
| Perito: "Não foi possível baixar a imagem" | Sem internet ou rede bloqueando o Docker Hub: envie o pacote com `.tar.gz`. |

## 7. Arquivos envolvidos

| Arquivo | Função |
|---|---|
| `Dockerfile` | define as duas variantes |
| `.dockerignore` | o que não entra na imagem (`distribuicao/`, `dist/`, `tmp/`, `.venv/`...) |
| `distribuicao/empacotar.sh` | build, publicação e montagem dos pacotes |
| `distribuicao/instalar.bat` | instalação no perito (`.tar.gz` ou Docker Hub) |
| `distribuicao/audio2text.bat` / `.sh` | lançadores da página web (Windows / Linux) |
| `distribuicao/config.txt` | modelo de configuração do perito (`PASTA_AUDIOS`...) |
| `distribuicao/transcrever.bat` | modo terminal, alternativo (só `.bat`, sem PowerShell) |
| `audio_transcription_tool/web/` | servidor e página web |
| `distribuicao/LEIA-ME.txt` | instruções do pacote com a completa |
| `distribuicao/LEIA-ME-leve.txt` | instruções do pacote só com a leve (vira `LEIA-ME.txt`) |
| `distribuicao/RELATO_DE_TESTE.txt` | formulário de retorno dos peritos |
