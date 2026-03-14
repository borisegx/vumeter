@echo off
chcp 65001 > nul
echo ========================================
echo   VU METER - Iniciando aplicación
echo ========================================
echo.

REM Verificar si existe venv
if exist "venv\Scripts\activate.bat" (
    echo Activando entorno virtual...
    call venv\Scripts\activate.bat
)

REM Verificar dependencias
echo Verificando dependencias...
python -c "import PyQt5" 2>nul
if errorlevel 1 (
    echo Instalando dependencias...
    pip install -r requirements.txt
)

echo.
echo Iniciando VU Meter...
echo ================================
echo Controles:
echo   - Arrastra para mover
echo   - Doble clic para cerrar
echo   - Clic derecho para opciones
echo   - Cierra ventana = minimiza a bandeja
echo ================================
echo.

python app.py %*

pause
