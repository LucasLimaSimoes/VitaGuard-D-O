\
@echo off
setlocal
cd /d "%~dp0"

echo =============================================
echo VitaGuard D^&O v1.0.0 - inicializacao local
echo =============================================
echo.

if exist ".venv\Scripts\python.exe" goto :deps

echo [1/4] Criando ambiente virtual .venv...
where py >nul 2>&1
if not errorlevel 1 (
    py -3 -m venv .venv
) else (
    where python >nul 2>&1
    if errorlevel 1 goto :no_python
    python -m venv .venv
)
if errorlevel 1 goto :error

:deps
echo [2/4] Verificando dependencias do VitaGuard...
".venv\Scripts\python.exe" -c "import streamlit, pydantic, yaml, pymupdf; from google import genai" >nul 2>&1
if not errorlevel 1 goto :validate

echo Dependencias ausentes. Instalando requirements.txt...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :error

:validate
echo [3/4] Validando release v1.0.0...
".venv\Scripts\python.exe" scripts\validate_v100.py
if errorlevel 1 goto :error

:run
echo [4/4] Abrindo VitaGuard em http://localhost:8501
echo Feche esta janela ou pressione Ctrl+C para encerrar o servidor.
echo.
".venv\Scripts\python.exe" -m streamlit run streamlit_app.py
exit /b %errorlevel%

:no_python
echo.
echo [ERRO] Python nao foi encontrado no PATH.
echo Instale Python 3.11+ e marque a opcao "Add Python to PATH", depois execute novamente.
pause
exit /b 1

:error
echo.
echo [ERRO] A inicializacao do VitaGuard falhou. Veja a mensagem acima.
pause
exit /b 1
