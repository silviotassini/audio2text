@echo off
rem audio2text - transcreve os audios de uma pasta (via Docker).
rem
rem Uso: arraste a pasta com os audios sobre este arquivo, ou:
rem   transcrever.bat "C:\pasta\audios" ["C:\pasta\saida"] [-SemGpu] [-Variante leve|completa]
rem
rem Escrito so em .bat, sem PowerShell: maquinas institucionais costumam bloquear scripts
rem .ps1 por politica de grupo, e essa politica nao se aplica a arquivos .bat.
setlocal DisableDelayedExpansion
chcp 65001 >nul

set "VERSAO=0.3.0"
set "VOLUME=audio2text-modelos"
set "IMAGEM_COMPLETA=audio2text:%VERSAO%-completa"
set "IMAGEM_LEVE=audio2text:%VERSAO%-leve"

rem --- Parametros -----------------------------------------------------------
set "AUDIOS_ARG="
set "SAIDA_ARG="
set "SEM_GPU=0"
set "VARIANTE=auto"

:parametros
if "%~1"=="" goto fim_parametros
if /i "%~1"=="-SemGpu" (
    set "SEM_GPU=1"
    shift
    goto parametros
)
if /i "%~1"=="-Variante" (
    set "VARIANTE=%~2"
    shift
    shift
    goto parametros
)
if not defined AUDIOS_ARG (
    set "AUDIOS_ARG=%~1"
    shift
    goto parametros
)
if not defined SAIDA_ARG (
    set "SAIDA_ARG=%~1"
    shift
    goto parametros
)
set "MSG=Parametro desconhecido: %~1"
goto falha

:fim_parametros
if not defined AUDIOS_ARG (
    echo Arraste a pasta com os audios sobre este arquivo, ou use:
    echo   transcrever.bat "C:\pasta\audios" ["C:\pasta\saida"]
    echo.
    pause
    exit /b 1
)

rem --- Docker ---------------------------------------------------------------
where docker >nul 2>&1
if errorlevel 1 (
    set "MSG=Docker nao encontrado. Instale o Docker Desktop (veja o LEIA-ME)."
    goto falha
)
docker info >nul 2>&1
if errorlevel 1 (
    set "MSG=O Docker nao esta em execucao. Abra o Docker Desktop, aguarde ficar pronto e tente de novo."
    goto falha
)

set "IMAGEM="
if /i "%VARIANTE%"=="completa" set "IMAGEM=%IMAGEM_COMPLETA%"
if /i "%VARIANTE%"=="leve" set "IMAGEM=%IMAGEM_LEVE%"
if /i "%VARIANTE%"=="auto" (
    docker image inspect %IMAGEM_COMPLETA% >nul 2>&1
    if errorlevel 1 (set "IMAGEM=%IMAGEM_LEVE%") else (set "IMAGEM=%IMAGEM_COMPLETA%")
)
if not defined IMAGEM (
    set "MSG=-Variante deve ser leve ou completa."
    goto falha
)
docker image inspect %IMAGEM% >nul 2>&1
if errorlevel 1 (
    set "MSG=A imagem %IMAGEM% nao esta instalada. Execute instalar.bat primeiro."
    goto falha
)

rem --- Pastas ---------------------------------------------------------------
for %%I in ("%AUDIOS_ARG%") do set "AUDIOS=%%~fI"
if "%AUDIOS:~1%"==":\" (
    set "MSG=Escolha a pasta com os audios, nao a raiz de um disco."
    goto falha
)
if "%AUDIOS:~-1%"=="\" set "AUDIOS=%AUDIOS:~0,-1%"
if not exist "%AUDIOS%\*" (
    set "MSG=A pasta de audios nao existe: %AUDIOS%"
    goto falha
)

if defined SAIDA_ARG (
    for %%I in ("%SAIDA_ARG%") do set "SAIDA=%%~fI"
) else (
    set "SAIDA=%AUDIOS%_transcricoes"
)
if "%SAIDA:~1%"==":\" (
    set "MSG=Escolha uma pasta de saida, nao a raiz de um disco."
    goto falha
)
if "%SAIDA:~-1%"=="\" set "SAIDA=%SAIDA:~0,-1%"

rem A pasta de saida nunca pode ser a pasta dos audios nem ficar dentro dela, para nao
rem alterar o material examinado. A verificacao e feita aqui, com os caminhos do Windows:
rem dentro do container as duas pastas aparecem separadas (/dados e /saida).
rem Sobe pelas pastas-pai do caminho de saida, comparando cada uma com a pasta dos audios
rem (sem diferenciar maiusculas), ate chegar a raiz do disco.
set "ATUAL=%SAIDA%"
set "NIVEIS=0"
:sobe_pasta
if /i "%ATUAL%"=="%AUDIOS%" (
    set "MSG=A pasta de saida (%SAIDA%) nao pode ser a pasta dos audios nem ficar dentro dela."
    goto falha
)
for %%I in ("%ATUAL%\..") do set "PAI=%%~fI"
if "%PAI:~-1%"=="\" set "PAI=%PAI:~0,-1%"
if /i "%PAI%"=="%ATUAL%" goto fim_sobe_pasta
set "ATUAL=%PAI%"
set /a NIVEIS+=1
if %NIVEIS% lss 200 goto sobe_pasta
:fim_sobe_pasta

rem Daqui em diante, os caminhos so sao lidos com !VAR!: assim nomes com & ! % ( )
rem nao sao interpretados como comandos.
setlocal EnableDelayedExpansion

if not exist "!SAIDA!\*" mkdir "!SAIDA!" >nul 2>&1
if not exist "!SAIDA!\*" (
    set "MSG=Nao foi possivel criar a pasta de saida !SAIDA!. Informe outra pasta como segundo parametro."
    goto falha
)

rem --- GPU ------------------------------------------------------------------
set "GPU="
if "!IMAGEM!"=="!IMAGEM_COMPLETA!" if "!SEM_GPU!"=="0" (
    where nvidia-smi >nul 2>&1
    if not errorlevel 1 (
        echo Verificando a GPU NVIDIA...
        docker run --rm --gpus all --entrypoint python !IMAGEM! -c "import sys, ctranslate2; sys.exit(0 if ctranslate2.get_cuda_device_count() > 0 else 1)" >nul 2>&1
        if errorlevel 1 (
            echo Aviso: ha GPU NVIDIA, mas o Docker nao conseguiu usa-la. A transcricao usara a CPU.
        ) else (
            set "GPU=--gpus all"
        )
    )
)
if defined GPU (
    set "DISPOSITIVO=auto"
    set "TEM_GPU=sim"
) else (
    set "DISPOSITIVO=cpu"
    set "TEM_GPU=nao"
)

rem --- Execucao -------------------------------------------------------------
echo.
echo audio2text !VERSAO! - imagem: !IMAGEM! - GPU: !TEM_GPU!
echo Audios (somente leitura): !AUDIOS!
echo Transcricoes:             !SAIDA!

docker run --rm -it !GPU! -v "!AUDIOS!:/dados:ro" -v "!SAIDA!:/saida" -v "!VOLUME!:/modelos" !IMAGEM! /dados --output /saida --device !DISPOSITIVO!
set "RC=!errorlevel!"
echo.
pause
exit /b !RC!

:falha
setlocal EnableDelayedExpansion
echo.
echo ERRO: !MSG!
echo.
pause
exit /b 1
