@echo off
rem Instala as imagens do audio2text no Docker: carrega os arquivos .tar.gz desta pasta
rem ou, se nao houver nenhum, baixa a versao leve do Docker Hub.
chcp 65001 >nul
cd /d "%~dp0"
set VERSAO=0.3.0
set REPOSITORIO=silviotassini/audio2text
docker info >nul 2>&1
if errorlevel 1 (
    echo O Docker nao esta em execucao. Abra o Docker Desktop, aguarde ficar pronto e tente de novo.
    pause
    exit /b 1
)
set ENCONTROU=0
for %%f in (audio2text-*.tar.gz) do (
    set ENCONTROU=1
    echo Carregando %%f ^(pode levar alguns minutos^)...
    docker load -i "%%f"
)
if "%ENCONTROU%"=="1" goto volume

echo Baixando o audio2text %VERSAO% da internet (cerca de 185 MB, pode levar alguns minutos)...
docker pull %REPOSITORIO%:%VERSAO%-leve
if errorlevel 1 (
    echo.
    echo Nao foi possivel baixar a imagem. Verifique a conexao com a internet ou peca o
    echo pacote com o arquivo audio2text-%VERSAO%-leve.tar.gz ao responsavel pelo teste.
    pause
    exit /b 1
)
rem O transcrever.bat procura a imagem pelo nome local.
docker tag %REPOSITORIO%:%VERSAO%-leve audio2text:%VERSAO%-leve

:volume
docker volume create audio2text-modelos >nul
echo.
echo Pronto. Para usar, informe a pasta do caso no config.txt e de dois cliques em audio2text.bat.
pause
