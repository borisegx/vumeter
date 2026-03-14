@echo off
chcp 65001 > nul
echo ========================================
echo   VU METER - Instalación
echo ========================================
echo.

REM Verificar Python
echo Verificando Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python no está instalado o no está en PATH
    echo    Descarga Python desde: https://python.org
    pause
    exit /b 1
)

echo ✅ Python encontrado
echo.

REM Crear entorno virtual
echo Creando entorno virtual...
python -m venv venv
if errorlevel 1 (
    echo ⚠️ No se pudo crear venv, instalando globalmente...
) else (
    echo ✅ Entorno virtual creado
    call venv\Scripts\activate.bat
)

echo.
echo Instalando dependencias...
echo.

REM Instalar dependencias básicas
pip install PyQt5 numpy

REM Intentar instalar PyAudio
echo Instalando PyAudio...
pip install pyaudio >nul 2>&1
if errorlevel 1 (
    echo.
    echo ⚠️ La instalación de PyAudio falló.
    echo.
    echo Intentando con pipwin...
    pip install pipwin >nul 2>&1
    pipwin install pyaudio >nul 2>&1
    if errorlevel 1 (
        echo.
        echo ============================================
        echo ❌ No se pudo instalar PyAudio automáticamente
        echo ============================================
        echo.
        echo Por favor, instala PyAudio manualmente:
        echo.
        echo 1. Visita: https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio
        echo 2. Descarga el wheel para tu versión de Python
        echo 3. Instala con: pip install PyAudio-xxx.whl
        echo.
        echo Mientras tanto, puedes usar el modo simulación:
        echo    python app.py --simulation
        echo ============================================
    ) else (
        echo ✅ PyAudio instalado con pipwin
    )
) else (
    echo ✅ PyAudio instalado
)

echo.
echo ========================================
echo   ✅ Instalación completada
echo ========================================
echo.
echo Para iniciar el VU Meter:
echo   - Ejecuta: start.bat
echo   - O: python app.py
echo.
echo Para modo demo (sin audio real):
echo   - python app.py --simulation
echo.
pause
