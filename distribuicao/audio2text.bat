@echo off
rem audio2text - abre a pagina de transcricao no navegador (Windows).
rem
rem Uso: dois cliques (usa a pasta do caso definida no config.txt), ou arraste a pasta do
rem caso sobre este arquivo para usa-la so nesta execucao.
rem
rem Escrito so em .bat, sem PowerShell: maquinas institucionais costumam bloquear scripts
rem .ps1 por politica de grupo. Caminhos nunca aparecem dentro de blocos ( ), para que
rem nomes como "Program Files (x86)" nao quebrem o script.
setlocal DisableDelayedExpansion
chcp 65001 >nul

set "VERSAO=0.3.0"
set "VOLUME=audio2text-modelos"
set "CONTAINER=audio2text-web"
set "IMAGEM_COMPLETA=audio2text:%VERSAO%-completa"
set "IMAGEM_LEVE=audio2text:%VERSAO%-leve"
set "CONFIG=%~dp0config.txt"
rem Arquivo temporario para ler a saida de comandos (docker, nvidia-smi) sem "for /f".
set "TMPF=%TEMP%\audio2text_%RANDOM%%RANDOM%.txt"

rem --- Configuracao ---------------------------------------------------------
if exist "%CONFIG%" goto ler_config
set "MSG=Arquivo de configuracao nao encontrado: %CONFIG%. Copie o config.txt do pacote para esta pasta e informe a PASTA_AUDIOS."
goto falha

:ler_config
set "CFG_AUDIOS="
set "CFG_SAIDA="
set "PORTA="
rem eol=# ignora os comentarios. O config.txt do pacote comeca com um comentario: se o
rem editor gravar o marcador BOM no inicio do arquivo, ele fica nessa linha, sem efeito.
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%CONFIG%") do (
    if /i "%%A"=="PASTA_AUDIOS" set "CFG_AUDIOS=%%B"
    if /i "%%A"=="PASTA_TRANSCRICOES" set "CFG_SAIDA=%%B"
    if /i "%%A"=="PORTA" set "PORTA=%%B"
)
if defined CFG_AUDIOS set "CFG_AUDIOS=%CFG_AUDIOS:"=%"
if defined CFG_SAIDA set "CFG_SAIDA=%CFG_SAIDA:"=%"
if not defined PORTA set "PORTA=8765"
set /a "PORTA_NUM=PORTA" 2>nul
if not "%PORTA_NUM%"=="%PORTA%" goto porta_invalida

set "AUDIOS_ARG=%CFG_AUDIOS%"
set "SAIDA_ARG=%CFG_SAIDA%"
if "%~1"=="" goto verificar_pasta
rem Pasta arrastada sobre o lancador: usa so nesta execucao, com as transcricoes ao lado.
set "AUDIOS_ARG=%~1"
set "SAIDA_ARG=%~2"

:verificar_pasta
if defined AUDIOS_ARG goto pastas
start "" notepad "%CONFIG%"
set "MSG=Informe a pasta do caso em PASTA_AUDIOS no config.txt (aberto no Bloco de Notas), salve e execute o audio2text.bat de novo."
goto falha

:porta_invalida
set "MSG=PORTA invalida no config.txt: %PORTA%"
goto falha

rem --- Pastas ---------------------------------------------------------------
:pastas
for %%I in ("%AUDIOS_ARG%") do set "AUDIOS=%%~fI"
if "%AUDIOS:~0,2%"=="\\" goto pasta_rede
if "%AUDIOS:~1%"==":\" goto pasta_raiz
if "%AUDIOS:~-1%"=="\" set "AUDIOS=%AUDIOS:~0,-1%"
rem Unidade de rede mapeada (ex.: Z:): o Docker Desktop nao a enxerga.
net use %AUDIOS:~0,2% >nul 2>&1
if not errorlevel 1 goto pasta_rede
if not exist "%AUDIOS%\*" goto pasta_inexistente

if defined SAIDA_ARG goto saida_informada
set "SAIDA=%AUDIOS%_transcricoes"
goto saida_definida
:saida_informada
for %%I in ("%SAIDA_ARG%") do set "SAIDA=%%~fI"
:saida_definida
if "%SAIDA:~1%"==":\" goto pasta_raiz
if "%SAIDA:~-1%"=="\" set "SAIDA=%SAIDA:~0,-1%"

rem A pasta de transcricoes nunca pode ser a pasta dos audios nem ficar dentro dela.
rem Sobe pelas pastas-pai da saida comparando cada uma com a pasta dos audios.
set "ATUAL=%SAIDA%"
set "NIVEIS=0"
:sobe_pasta
if /i "%ATUAL%"=="%AUDIOS%" goto saida_dentro
for %%I in ("%ATUAL%\..") do set "PAI=%%~fI"
if "%PAI:~-1%"=="\" set "PAI=%PAI:~0,-1%"
if /i "%PAI%"=="%ATUAL%" goto fim_sobe_pasta
set "ATUAL=%PAI%"
set /a NIVEIS+=1
if %NIVEIS% lss 200 goto sobe_pasta
:fim_sobe_pasta

if not exist "%SAIDA%\*" mkdir "%SAIDA%" >nul 2>&1
if not exist "%SAIDA%\*" goto saida_falhou
goto docker

:pasta_rede
set "MSG=A pasta %AUDIOS% esta na rede. O Docker nao acessa pastas de rede: copie os audios para um disco deste computador e informe essa pasta."
goto falha
:pasta_raiz
set "MSG=Escolha uma pasta, nao a raiz de um disco."
goto falha
:pasta_inexistente
set "MSG=A pasta do caso nao existe ou o disco nao esta conectado: %AUDIOS%"
goto falha
:saida_dentro
set "MSG=A pasta de transcricoes (%SAIDA%) nao pode ser a pasta dos audios nem ficar dentro dela."
goto falha
:saida_falhou
set "MSG=Nao foi possivel criar a pasta de transcricoes %SAIDA%. Informe outra em PASTA_TRANSCRICOES no config.txt."
goto falha

rem --- Docker --------------------------------------------------------------
:docker
where docker >nul 2>&1
if errorlevel 1 goto sem_docker
docker info >nul 2>&1
if not errorlevel 1 goto docker_pronto
rem Docker Desktop fechado: abre e espera ficar pronto (ate cerca de 2 minutos).
if not exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" goto docker_parado
echo Abrindo o Docker Desktop, aguarde...
start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
set "ESPERA=0"
:espera_docker
ping -n 3 127.0.0.1 >nul
docker info >nul 2>&1
if not errorlevel 1 goto docker_pronto
set /a ESPERA+=1
if %ESPERA% lss 60 goto espera_docker
goto docker_parado

:sem_docker
set "MSG=Docker nao encontrado. Instale o Docker Desktop (veja o LEIA-ME)."
goto falha
:docker_parado
set "MSG=O Docker nao esta em execucao. Abra o Docker Desktop, aguarde ficar pronto e tente de novo."
goto falha

:docker_pronto
rem Ja existe uma pagina aberta? Reaproveita, em vez de abrir uma segunda.
set "EXISTENTE="
docker ps -q --filter "name=^/%CONTAINER%$" > "%TMPF%" 2>nul
set /p EXISTENTE=<"%TMPF%"
del "%TMPF%" >nul 2>&1
if not defined EXISTENTE goto escolher_imagem
set "TOKEN_EXIST="
set "AUDIOS_EXIST="
set "PORTA_EXIST="
docker inspect -f "{{range .Config.Env}}{{println .}}{{end}}" %CONTAINER% > "%TMPF%" 2>nul
for /f "usebackq tokens=1,* delims==" %%A in ("%TMPF%") do (
    if "%%A"=="AT_TOKEN" set "TOKEN_EXIST=%%B"
    if "%%A"=="AT_HOST_AUDIOS" set "AUDIOS_EXIST=%%B"
    if "%%A"=="AT_PORTA_HOST" set "PORTA_EXIST=%%B"
)
del "%TMPF%" >nul 2>&1
start "" "http://127.0.0.1:%PORTA_EXIST%/?token=%TOKEN_EXIST%"
if /i "%AUDIOS_EXIST%"=="%AUDIOS%" goto ja_aberto_mesma
setlocal EnableDelayedExpansion
echo Ja existe uma sessao aberta com outra pasta: !AUDIOS_EXIST!
echo Ela foi aberta no navegador. Para trocar de pasta, clique em Encerrar na pagina
echo e execute o audio2text.bat de novo.
echo.
pause
exit /b 0
:ja_aberto_mesma
echo O audio2text ja estava aberto; a pagina foi aberta no navegador.
echo.
pause
exit /b 0

:escolher_imagem
set "IMAGEM="
docker image inspect %IMAGEM_COMPLETA% >nul 2>&1
if not errorlevel 1 set "IMAGEM=%IMAGEM_COMPLETA%"
if defined IMAGEM goto gpu
docker image inspect %IMAGEM_LEVE% >nul 2>&1
if not errorlevel 1 set "IMAGEM=%IMAGEM_LEVE%"
if defined IMAGEM goto gpu
set "MSG=Nenhuma imagem do audio2text %VERSAO% instalada. Execute instalar.bat primeiro."
goto falha

rem --- GPU -----------------------------------------------------------------
:gpu
set "GPU="
set "GPU_NOME="
set "DISPOSITIVO=cpu"
if not "%IMAGEM%"=="%IMAGEM_COMPLETA%" goto executar
where nvidia-smi >nul 2>&1
if errorlevel 1 goto executar
echo Verificando a GPU NVIDIA...
docker run --rm --gpus all --entrypoint python %IMAGEM% -c "import sys, ctranslate2; sys.exit(0 if ctranslate2.get_cuda_device_count() > 0 else 1)" >nul 2>&1
if errorlevel 1 goto gpu_falhou
set "GPU=--gpus all"
set "DISPOSITIVO=auto"
nvidia-smi --query-gpu=name --format=csv,noheader > "%TMPF%" 2>nul
set /p GPU_NOME=<"%TMPF%"
del "%TMPF%" >nul 2>&1
goto executar
:gpu_falhou
echo Aviso: ha GPU NVIDIA, mas o Docker nao conseguiu usa-la. A transcricao usara a CPU.

rem --- Execucao ------------------------------------------------------------
:executar
rem Token aleatorio: so quem abre pelo link do lancador acessa a pagina.
set "TOKEN=%RANDOM%%RANDOM%%RANDOM%%RANDOM%%RANDOM%%RANDOM%%RANDOM%%RANDOM%"

rem Daqui em diante, os caminhos so sao lidos com !VAR!: nomes com & ! % ( ) nao sao
rem interpretados como comandos.
setlocal EnableDelayedExpansion
if defined GPU (set "TEM_GPU=sim") else (set "TEM_GPU=nao")
echo.
echo audio2text !VERSAO! - imagem: !IMAGEM! - GPU: !TEM_GPU!
echo Pasta do caso (somente leitura): !AUDIOS!
echo Transcricoes:                    !SAIDA!

docker run -d --rm --name !CONTAINER! -p 127.0.0.1:!PORTA!:8000 !GPU! -v "!AUDIOS!:/dados:ro" -v "!SAIDA!:/saida" -v "!VOLUME!:/modelos" -e "AT_TOKEN=!TOKEN!" -e "AT_HOST_AUDIOS=!AUDIOS!" -e "AT_HOST_SAIDA=!SAIDA!" -e "AT_GPU_NOME=!GPU_NOME!" -e "AT_DISPOSITIVO=!DISPOSITIVO!" -e "AT_PORTA_HOST=!PORTA!" --entrypoint python !IMAGEM! -m audio_transcription_tool.web >nul
if errorlevel 1 (
    set "MSG=Nao foi possivel iniciar o audio2text. A porta !PORTA! pode estar em uso: troque PORTA no config.txt."
    goto falha
)

set "PRONTO=0"
where curl >nul 2>&1
if errorlevel 1 (
    ping -n 9 127.0.0.1 >nul
    set "PRONTO=1"
    goto abrir
)
set "ESPERA=0"
:espera_pagina
curl -sf -o nul "http://127.0.0.1:!PORTA!/saude" >nul 2>&1
if not errorlevel 1 (
    set "PRONTO=1"
    goto abrir
)
set /a ESPERA+=1
if !ESPERA! lss 60 (
    ping -n 2 127.0.0.1 >nul
    goto espera_pagina
)
set "MSG=A pagina nao respondeu. Veja o motivo com: docker logs !CONTAINER!"
goto falha

:abrir
start "" "http://127.0.0.1:!PORTA!/?token=!TOKEN!"
echo.
echo A pagina foi aberta no navegador. Pode fechar esta janela.
echo Para encerrar o audio2text, use o botao Encerrar na pagina.
echo.
pause
exit /b 0

:falha
setlocal EnableDelayedExpansion
echo.
echo ERRO: !MSG!
echo.
pause
exit /b 1
