# Audio Transcription Tool (Whisper)

Ferramenta de transcrição de áudio via terminal, com menu interativo, barra de progresso e estrutura modular para integração em outros scripts. Usa o Whisper por meio do [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (mesmos modelos, cerca de 4× mais rápido e com menos memória).

## Funcionalidades

- Busca automática de arquivos de áudio (`.mp3`, `.wav`, `.m4a`, `.flac`, `.ogg`)
- Menu interativo para:
  - selecionar todos os arquivos ou por número/intervalo (ex.: `1,3-5`)
  - escolher modelo Whisper (`base`, `small`, `medium`, `large-v3`, `turbo`)
  - configurar idioma (`auto` ou idioma fixo)
  - ligar/desligar marcação de tempo e identificação de locutores
  - escolher dispositivo (automático, CPU ou GPU)
- Barra de progresso com `tqdm`; no terminal aparecem só avisos e erros (detalhes com `verbose`)
- Tratamento de erros para pasta inválida e arquivos com falha/corrompidos
- Geração de `.txt` por arquivo de áudio (`audio.mp3` → `audio.mp3.txt`), com cabeçalho de aviso de transcrição automática, modelo, versão, dispositivo e duração
- Marcação de tempo por trecho opcional (`--timestamps`, opção 5 do menu ou `"timestamps": true`); padrão: desligada
- Identificação de locutores opcional (`--diarize`, opção 6 do menu ou `"diarize": true`); padrão: desligada
- Proteção do material examinado:
  - a pasta de saída nunca pode ser a pasta dos áudios (nem uma subpasta dela)
  - transcrições existentes nunca são sobrescritas: uma nova execução gera `audio.mp3_2.txt`, `_3`...
- Redução de alucinações do Whisper (detecção de voz, entre outros) e marcação de trechos de baixa confiança como `[?? ... ??]`
- Resumo final com tempo total e status
- Log opcional em arquivo (gravado na pasta de saída)

## Estrutura

```text
audio2text/
├── audio_transcription_tool/      código da ferramenta
│   ├── transcriber_engine.py      motor de transcrição (faster-whisper)
│   ├── diarization.py             identificação de locutores (pyannote, opcional)
│   ├── ui_menu.py                 menu do modo terminal
│   ├── utils.py                   configuração, modelos, formatos aceitos
│   ├── version.py                 número da versão
│   └── web/                       página web (servidor FastAPI + HTML/CSS/JS)
├── distribuicao/                  o que vai para os peritos + empacotar.sh e manual
├── dist/                          pacotes gerados pelo empacotar.sh (não versionar)
├── transcriber.py                 modo terminal
├── config.json                    configuração do modo terminal
├── requirements.txt               dependências (versões fixas)
├── requirements-gpu.txt           + CUDA 12 / cuDNN 9
├── requirements-diarizacao.txt    + identificação de locutores
├── Dockerfile                     imagens leve e completa
└── .dockerignore
```

## Instalação local

### 1) Pré-requisitos

- Python 3.11+ (no Ubuntu/Pop!_OS: `sudo apt install -y python3-venv python3-pip`)
- Opcional, para GPU: placa NVIDIA com driver instalado (ver [GPU NVIDIA](#gpu-nvidia-opcional))

### 2) Instalar dependências

Dentro da pasta do projeto, crie um ambiente virtual e instale:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Em cada terminal novo, ative o ambiente antes de usar: `source .venv/bin/activate`.

As versões estão fixadas para que a mesma entrada gere o mesmo resultado. Não atualize pacotes
isoladamente: versões mais novas podem mudar a transcrição ou quebrar a ferramenta.

Para usar a identificação de locutores (inclui PyTorch, download grande):

```bash
pip install -r requirements-diarizacao.txt
```

### 3) Executar

```bash
python transcriber.py /caminho/para/pasta_de_audios --output /caminho/para/transcricoes
```

Sem `--output`, as transcrições vão para `./transcricoes_<nome da pasta>` no diretório atual.

Opções:

| Opção | Efeito |
|---|---|
| `-o`, `--output PASTA` | Pasta de saída (não pode ser a pasta dos áudios) |
| `--timestamps` | Inclui `[HH:MM:SS - HH:MM:SS]` em cada trecho |
| `--diarize` | Identifica os locutores (`LOCUTOR 1`, `LOCUTOR 2`...) |
| `--num-speakers N` | Número de locutores, se conhecido (melhora a separação) |
| `--device auto\|cpu\|cuda` | Dispositivo de processamento (padrão: `auto`) |
| `--config ARQUIVO` | Arquivo de configuração (padrão: `config.json`) |

No menu, a transcrição começa com a opção **I** (Iniciar).

### Modelos

| Modelo | Uso indicado |
|---|---|
| `base` | rápido, menor precisão (bom para triagem) |
| `small` | equilíbrio entre velocidade e precisão |
| `medium` | boa precisão, mais lento |
| `large-v3` | maior precisão, o mais lento (recomendado para laudo) |
| `turbo` | large-v3 otimizado: precisão próxima, bem mais rápido |

O nome antigo `large` é convertido para `large-v3`, para que o modelo usado fique explícito e
reproduzível. Na primeira vez, o modelo é baixado da internet (Hugging Face) e fica guardado em
`~/.cache/huggingface`; depois a ferramenta funciona sem internet.

### GPU

Com `auto`, a GPU NVIDIA é usada quando disponível. Sem GPU, ou se ela falhar ao carregar, a
ferramenta avisa e continua na CPU, que é bem mais lenta (sobretudo com `large-v3`).
A instalação está em [GPU NVIDIA](#gpu-nvidia-opcional).

### Trechos de baixa confiança

Trechos marcados com `[?? ... ??]` tiveram baixa confiança do modelo (texto pouco provável,
provável ausência de fala ou repetição). São os pontos mais sujeitos a erro ou a texto
inventado e devem ser conferidos com atenção na gravação. Áudios sem fala geram
`[Nenhuma fala detectada]`.

### Identificação de locutores

Usa o [pyannote.audio](https://github.com/pyannote/pyannote-audio) com o modelo
`pyannote/speaker-diarization-community-1`. Cada palavra é atribuída ao locutor que está
falando naquele instante, e o texto sai com uma linha por fala:

```text
[00:00:08 - 00:00:09] LOCUTOR 1: Oh, hello. I didn't know you were there.
[00:00:09 - 00:00:10] LOCUTOR 2: Neither did I. Okay.
```

- Os rótulos não identificam pessoas: indicam apenas vozes diferentes no mesmo arquivo
  (o `LOCUTOR 1` de um arquivo não é necessariamente o `LOCUTOR 1` de outro).
- `LOCUTOR ?` indica trecho em que nenhum locutor foi atribuído.
- A atribuição é automática e deve ser conferida.

**Primeiro uso:** o modelo exige aceite dos termos e um token gratuito do Hugging Face:

1. Crie uma conta em huggingface.co e aceite os termos em
   `https://huggingface.co/pyannote/speaker-diarization-community-1`.
2. Gere um token de leitura e rode `hf auth login` (ou defina `HF_TOKEN`).

Depois do primeiro download, o modelo fica em cache e o token não é mais necessário.
A telemetria do pyannote é desligada pela ferramenta: nenhum dado do exame é enviado.

## GPU NVIDIA (opcional)

Com GPU, a transcrição fica muitas vezes mais rápida (ex.: GTX 1050 Ti, modelo `base`: 30 s de
áudio em menos de 1 s, contra cerca de 3 s na CPU). Os passos abaixo são para Ubuntu/Pop!_OS.

### 1) Descobrir a geração da placa

```bash
lspci | grep -i nvidia
```

| Placa | Geração | Driver | Formato usado |
|---|---|---|---|
| GTX 10xx, Quadro Pxxxx | Pascal | **somente o proprietário** `nvidia-driver-580` | `int8` |
| GTX 16xx, RTX 20xx ou mais nova | Turing+ | `nvidia-driver-580` ou mais novo (`-open` também serve) | `float16` |

Atenção para placas **Pascal (GTX 10xx)**:

- os drivers `-open` não funcionam nelas (o módulo não carrega e `nvidia-smi` falha);
- a série 580 é a última com suporte a Pascal: não instale `nvidia-driver-590` ou mais novo,
  nem o pacote `system76-driver-nvidia`, que pode trazer um driver mais novo.

### 2) Instalar o driver

```bash
sudo apt update
sudo apt install nvidia-driver-580   # confirme a remoção dos pacotes -open, se houver
dkms status                          # deve mostrar: nvidia/580..., <kernel>, x86_64: installed
```

A mensagem `Couldn't find EFI system partition` é inofensiva em computadores que iniciam em modo
BIOS legado com GRUB.

Em notebooks Pop!_OS com gráfico híbrido, coloque a NVIDIA em modo de cálculo (a tela fica com a
placa integrada e toda a memória da GPU fica livre para o Whisper):

```bash
sudo system76-power graphics compute
```

Reinicie e confira com `nvidia-smi`, que deve listar a placa e a versão do driver. O campo
`CUDA Version` mostrado é só a versão máxima que o driver suporta, não algo instalado.

### 3) Instalar CUDA 12 e cuDNN 9 no ambiente da ferramenta

As bibliotecas vão para dentro do `.venv` (cerca de 1 GB); não é preciso instalar o CUDA Toolkit.

```bash
source .venv/bin/activate
pip install -r requirements-gpu.txt
```

Faça o ambiente encontrar essas bibliotecas sempre que for ativado (só uma vez):

```bash
cat >> .venv/bin/activate <<'FIM'

# Bibliotecas CUDA 12 / cuDNN 9 (pip) usadas pelo faster-whisper na GPU
_NV="$(echo "$VIRTUAL_ENV"/lib/python3*/site-packages/nvidia)"
export LD_LIBRARY_PATH="$_NV/cublas/lib:$_NV/cudnn/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
unset _NV
FIM
deactivate; source .venv/bin/activate
```

### 4) Testar

```bash
python -c "import ctranslate2; print(ctranslate2.get_cuda_device_count(), ctranslate2.get_supported_compute_types('cuda'))"
```

Deve mostrar `1` e uma lista com `int8` (Pascal) ou `float16` (Turing+). Depois, rode a
ferramenta com `--device cuda`: a tela deve mostrar `Dispositivo: cuda (...)`. Se aparecer
`Falha ao usar a GPU (...)`, a transcrição continua na CPU e a mensagem indica o motivo.

Com 4 GB de memória de vídeo, prefira `turbo` ou modelos menores; `large-v3` pode não caber.

### Identificação de locutores na GPU

O PyTorch instalado por `requirements-diarizacao.txt` é compilado para CUDA 13, que **não
suporta placas Pascal (GTX 10xx)**. Nelas, a ferramenta detecta o problema, avisa e faz a
identificação de locutores na CPU (a transcrição continua na GPU). Para usar a GPU também
nessa etapa, instale a mesma versão do PyTorch compilada para CUDA 12.6 (cerca de 2–3 GB):

```bash
pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cu126
```

Placas Turing ou mais novas não precisam desse passo.

### Se algo der errado

- Tela preta após reiniciar: tecle `Ctrl+Alt+F3`, entre com seu usuário e volte para a placa
  integrada com `sudo system76-power graphics integrated`, depois reinicie.
- Voltar ao driver anterior: reinstale o pacote que havia antes (ex.: `nvidia-driver-580-open`).

## Configuração

Você pode usar `config.json` e/ou variáveis de ambiente. Opções de linha de comando têm prioridade.

### `config.json`

```json
{
  "default_model": "base",
  "default_language": "auto",
  "output_dir": null,
  "log_enabled": false,
  "log_file": "transcriber.log",
  "verbose": false,
  "timestamps": false,
  "device": "auto",
  "diarize": false,
  "num_speakers": null,
  "diarization_model": "pyannote/speaker-diarization-community-1"
}
```

Um `log_file` relativo é gravado na pasta de saída.

### Variáveis de ambiente

- `AT_DEFAULT_MODEL` (`base|small|medium|large-v3|turbo`)
- `AT_DEFAULT_LANGUAGE` (`auto`, `pt`, `en`, etc.)
- `AT_OUTPUT_DIR`
- `AT_LOG_ENABLED` (`true/false`)
- `AT_LOG_FILE`
- `AT_VERBOSE` (`true/false`)
- `AT_TIMESTAMPS` (`true/false`)
- `AT_DEVICE` (`auto|cpu|cuda`)
- `AT_DIARIZE` (`true/false`)
- `AT_NUM_SPEAKERS`
- `AT_DIARIZATION_MODEL`

Exemplo:

```bash
export AT_DEFAULT_MODEL=small
export AT_LOG_ENABLED=true
python transcriber.py ./audios -o ./transcricoes
```

## Uso como módulo

```python
from pathlib import Path
from audio_transcription_tool import TranscriberEngine

engine = TranscriberEngine(model_name="large-v3", device="auto", diarize=False)
result = engine.transcribe_file(
    audio_path=Path("./audios/exemplo.mp3"),
    output_dir=Path("./transcricoes"),
    language="auto",
    timestamps=True,
)
print(result)
```

## Docker

Há duas variantes da imagem:

| Imagem | Conteúdo |
|---|---|
| `audio2text:0.3.0-leve` | só CPU, sem identificação de locutores (~800 MB) |
| `audio2text:0.3.0-completa` | GPU NVIDIA (CUDA 12 / cuDNN 9) e identificação de locutores, com o modelo do pyannote embutido (revisão fixa); também funciona sem GPU |

A imagem roda com um usuário sem privilégios (`perito`, UID 1000). Os modelos do Whisper são
baixados no primeiro uso para `/modelos`; monte um volume nesse caminho para guardá-los.

### Build

```bash
docker build --build-arg VARIANTE=leve -t audio2text:0.3.0-leve .

# a completa baixa o modelo de locutores durante o build: requer token do Hugging Face com os
# termos do modelo aceitos (o token não fica gravado na imagem)
docker build --build-arg VARIANTE=completa \
  --secret id=hf_token,src=$HOME/.cache/huggingface/token \
  -t audio2text:0.3.0-completa .
```

### Execução (Linux)

```bash
docker run --rm -it \
  -v /caminho/local/audios:/dados:ro \
  -v /caminho/local/transcricoes:/saida \
  -v audio2text-modelos:/modelos \
  audio2text:0.3.0-completa /dados --output /saida
```

Para usar a GPU, acrescente `--gpus all` (requer o NVIDIA Container Toolkit no Linux).

> A verificação de que a saída não fica dentro da pasta dos áudios é feita dentro do container,
> onde as pastas aparecem como `/dados` e `/saida`. Não monte em `/saida` uma subpasta da pasta
> dos áudios; os scripts de distribuição para Windows já verificam isso com os caminhos reais.

### Página web (a partir da 0.3.0)

O modo principal de uso é pela página web: o perito informa a pasta do caso no
`config.txt` e executa `audio2text.bat` (Windows) ou `audio2text.sh` (Linux). O lançador:

1. valida as pastas (a de transcrições nunca dentro da pasta do caso; pastas de rede são
   recusadas no Windows, pois o Docker Desktop não as enxerga);
2. reaproveita uma sessão já aberta (container `audio2text-web`) em vez de abrir outra;
3. detecta a GPU e sobe o container com a pasta do caso **somente leitura** em `/dados`, a
   de transcrições em `/saida`, a porta publicada **só em `127.0.0.1`** e um token aleatório;
4. abre o navegador em `http://127.0.0.1:<PORTA>/?token=...`.

O servidor (`python -m audio_transcription_tool.web`, FastAPI) troca o token por um cookie,
recusa outros endereços (`Host`) e não acessa nada fora de `/dados` e `/saida`. A telemetria
do FastAPI fica desligada. A página informa o fuso horário do navegador, para que as datas
das transcrições saiam no horário local; o cabeçalho sempre indica o fuso, ex.: `(UTC-03:00)`.
Cada lote gera um `relatorio_<data>.csv` com o SHA-256 dos áudios e das transcrições.

### Distribuição para os peritos (Windows)

A pasta `distribuicao/` contém o que vai para os peritos: `instalar.bat` e `transcrever.bat`
(só `.bat`, sem PowerShell, que costuma ser bloqueado por política de grupo), que validam as
pastas, detectam a GPU e montam os áudios como somente leitura,
além do `LEIA-ME.txt` e do `RELATO_DE_TESTE.txt`. Para gerar o pacote completo, com as duas
imagens exportadas e o `SHA256SUMS.txt`:

```bash
distribuicao/empacotar.sh     # gera dist/audio2text-<versão>/
```

Ao lançar uma nova versão, atualize `audio_transcription_tool/version.py`, as tags no
`Dockerfile`, a variável `VERSAO` do `transcrever.bat` e do `instalar.bat` e os `LEIA-ME`.
