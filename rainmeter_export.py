"""
Rainmeter Export Module - Exporta datos de audio para Rainmeter
Permite que Rainmeter lea los niveles de audio del sistema
"""

import json
import math
import os
import tempfile
import time
import threading
from datetime import datetime

# Constantes de exportación
EXPORT_UPDATE_INTERVAL = 0.033   # ~30 FPS
EXPORT_CHANGE_THRESHOLD = 0.015  # 1.5% - umbral mínimo para escribir a disco
DB_FLOOR = -60                   # Valor mínimo en dB (silencio)


class RainmeterExporter:
    """
    Exporta los niveles de audio a archivos que Rainmeter puede leer.
    Soporta múltiples formatos de salida.
    """

    def __init__(self, output_dir: str = None, update_interval: float = EXPORT_UPDATE_INTERVAL):
        """
        Inicializa el exportador.
        
        Args:
            output_dir: Directorio donde guardar los archivos
            update_interval: Intervalo de actualización en segundos (default: ~30 FPS)
        """
        self.output_dir = output_dir or os.path.dirname(os.path.abspath(__file__))
        self.update_interval = update_interval
        
        # Archivos de salida
        self.json_file = os.path.join(self.output_dir, "audio_levels.json")
        self.ini_file = os.path.join(self.output_dir, "audio_levels.inc")
        
        # Datos actuales
        self.left_level = 0.0
        self.right_level = 0.0
        self.left_peak = 0.0
        self.right_peak = 0.0
        
        # Estado
        self.is_running = False
        self._thread = None
        
        # Asegurar que el directorio existe
        os.makedirs(self.output_dir, exist_ok=True)
    
    def update_levels(self, left: float, right: float, 
                      left_peak: float = None, right_peak: float = None):
        """
        Actualiza los niveles de audio.
        
        Args:
            left: Nivel canal izquierdo (0.0 - 1.0)
            right: Nivel canal derecho (0.0 - 1.0)
            left_peak: Peak izquierdo (opcional)
            right_peak: Peak derecho (opcional)
        """
        self.left_level = left
        self.right_level = right
        if left_peak is not None:
            self.left_peak = left_peak
        if right_peak is not None:
            self.right_peak = right_peak
        
        # Exportar inmediatamente si no hay thread
        if not self.is_running:
            self._export()
    
    def start_continuous_export(self):
        """Inicia la exportación continua en un hilo separado."""
        if self.is_running:
            return
        
        self.is_running = True
        self._thread = threading.Thread(target=self._export_loop, daemon=True)
        self._thread.start()
        print(f"[EXPORT] Exportación Rainmeter iniciada en: {self.output_dir}")
    
    def stop_continuous_export(self):
        """Detiene la exportación continua."""
        self.is_running = False
        if self._thread:
            self._thread.join(timeout=1)
        print("[STOP] Exportación Rainmeter detenida")
    
    def _export_loop(self):
        """Loop de exportación continua con mitigación de desgaste SSD."""
        last_exported_left = -1.0
        last_exported_right = -1.0

        while self.is_running:
            diff_left = abs(self.left_level - last_exported_left)
            diff_right = abs(self.right_level - last_exported_right)

            if diff_left > EXPORT_CHANGE_THRESHOLD or diff_right > EXPORT_CHANGE_THRESHOLD:
                self._export()
                last_exported_left = self.left_level
                last_exported_right = self.right_level

            time.sleep(self.update_interval)
    
    @staticmethod
    def _to_db(level):
        """Convierte nivel lineal (0.0-1.0) a decibelios."""
        if level <= 0:
            return DB_FLOOR
        return max(DB_FLOOR, 20.0 * math.log10(level))

    def _atomic_write(self, filepath, content):
        """Escribe un archivo de forma atómica usando temp + rename."""
        dir_name = os.path.dirname(filepath)
        try:
            fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(content)
            os.replace(tmp_path, filepath)
        except Exception:
            # Si falla el rename, intentar limpiar el temporal
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def _export(self):
        """Exporta los datos a los archivos."""
        left_db = self._to_db(self.left_level)
        right_db = self._to_db(self.right_level)
        left_peak_db = self._to_db(self.left_peak)
        right_peak_db = self._to_db(self.right_peak)
        
        # Calcular porcentajes para barras (0-100)
        left_percent = int(self.left_level * 100)
        right_percent = int(self.right_level * 100)
        left_peak_percent = int(self.left_peak * 100)
        right_peak_percent = int(self.right_peak * 100)
        
        # Exportar JSON
        data = {
            "timestamp": datetime.now().isoformat(),
            "levels": {
                "left": round(self.left_level, 4),
                "right": round(self.right_level, 4),
                "left_peak": round(self.left_peak, 4),
                "right_peak": round(self.right_peak, 4)
            },
            "db": {
                "left": round(left_db, 1),
                "right": round(right_db, 1),
                "left_peak": round(left_peak_db, 1),
                "right_peak": round(right_peak_db, 1)
            },
            "percent": {
                "left": left_percent,
                "right": right_percent,
                "left_peak": left_peak_percent,
                "right_peak": right_peak_percent
            }
        }
        
        try:
            self._atomic_write(self.json_file, json.dumps(data, indent=2))
        except Exception:
            pass
        
        # Exportar archivo .inc para Rainmeter (formato variables)
        ini_content = f"""; Audio Levels for Rainmeter
; Generated by Python VU Meter
; Timestamp: {datetime.now().isoformat()}

[Variables]
AudioLeft={round(self.left_level, 4)}
AudioRight={round(self.right_level, 4)}
AudioLeftPeak={round(self.left_peak, 4)}
AudioRightPeak={round(self.right_peak, 4)}
AudioLeftPercent={left_percent}
AudioRightPercent={right_percent}
AudioLeftPeakPercent={left_peak_percent}
AudioRightPeakPercent={right_peak_percent}
AudioLeftDB={round(left_db, 1)}
AudioRightDB={round(right_db, 1)}
"""
        
        try:
            self._atomic_write(self.ini_file, ini_content)
        except Exception:
            pass
    
    def get_rainmeter_webparser_url(self):
        """
        Retorna la URL local para usar con WebParser en Rainmeter.
        Rainmeter puede leer el archivo JSON generado.
        """
        return f"file:///{self.json_file.replace(os.sep, '/')}"


class RainmeterSkinGenerator:
    """
    Genera skins de Rainmeter para VU Meter.
    Crea archivos .ini listos para usar.
    """
    
    @staticmethod
    def generate_led_skin(output_dir: str, skin_name: str = "PythonVUMeter"):
        """
        Genera un skin de Rainmeter estilo LED.
        
        Args:
            output_dir: Directorio donde crear el skin
            skin_name: Nombre del skin
        """
        skin_dir = os.path.join(output_dir, skin_name)
        os.makedirs(skin_dir, exist_ok=True)
        
        # Archivo principal del skin
        ini_content = """[Rainmeter]
Update=16
Author=Python VU Meter
Name=Python VU Meter LED

[Metadata]
Name=Python VU Meter LED Style
Description=VU Meter que lee datos de la aplicación Python
License=MIT
Version=1.0

; ============================================
; VARIABLES
; ============================================
[Variables]
; Colores
ColorGreen=0,200,0,255
ColorYellow=255,200,0,255
ColorRed=255,50,50,255
ColorOff=30,30,30,255
ColorBackground=20,20,25,240

; Dimensiones
BarWidth=20
BarHeight=250
LedCount=20
LedSize=10
LedSpacing=2

; Archivo de datos generado por Python
DataFile=audio_levels.json

; ============================================
; MEDIDAS - Leer datos del JSON
; ============================================
[MeasureJSON]
Measure=WebParser
URL=file:///#@#Variables/#DataFile#
RegExp="left":\\s*([0-9.]+).*"right":\\s*([0-9.]+).*"left_peak":\\s*([0-9.]+).*"right_peak":\\s*([0-9.]+)
DecodeCharacterReference=1
LogSubstringErrors=0
UpdateRate=60

[MeasureLeft]
Measure=WebParser
URL=[MeasureJSON]
StringIndex=1

[MeasureRight]
Measure=WebParser
URL=[MeasureJSON]
StringIndex=2

[MeasureLeftPeak]
Measure=WebParser
URL=[MeasureJSON]
StringIndex=3

[MeasureRightPeak]
Measure=WebParser
URL=[MeasureJSON]
StringIndex=4

; Alternativa: Leer del archivo .inc
[MeasureLeftDirect]
Measure=Calc
Formula=AudioLeft
DynamicVariables=1

; ============================================
; METERS - Visualización LED
; ============================================
[MeterBackground]
Meter=Shape
Shape=Rectangle 0,0,180,310,10 | Fill Color #ColorBackground# | Stroke Color 60,60,70,100,1

; Título
[MeterTitle]
Meter=String
X=90
Y=15
StringAlign=Center
FontColor=100,100,120,255
FontSize=10
FontWeight=600
Text="VU METER"

; Canal Izquierdo - Etiqueta
[MeterLabelL]
Meter=String
X=35
Y=35
StringAlign=Center
FontColor=150,150,150,255
FontSize=12
FontWeight=700
Text="L"

; Canal Izquierdo - Barra
[MeterBarL]
Meter=Bar
X=20
Y=55
W=#BarWidth#
H=#BarHeight#
BarColor=#ColorGreen#
SolidColor=#ColorOff#
BarOrientation=Vertical
MeasureName=MeasureLeft
Value=1

; Peak izquierdo
[MeterPeakL]
Meter=Bar
X=20
Y=55
W=#BarWidth#
H=#BarHeight#
BarColor=#ColorYellow#
SolidColor=0,0,0,0
BarOrientation=Vertical
MeasureName=MeasureLeftPeak
Value=1

; Canal Derecho - Etiqueta
[MeterLabelR]
Meter=String
X=145
Y=35
StringAlign=Center
FontColor=150,150,150,255
FontSize=12
FontWeight=700
Text="R"

; Canal Derecho - Barra
[MeterBarR]
Meter=Bar
X=130
Y=55
W=#BarWidth#
H=#BarHeight#
BarColor=#ColorGreen#
SolidColor=#ColorOff#
BarOrientation=Vertical
MeasureName=MeasureRight
Value=1

; Peak derecho
[MeterPeakR]
Meter=Bar
X=130
Y=55
W=#BarWidth#
H=#BarHeight#
BarColor=#ColorYellow#
SolidColor=0,0,0,0
BarOrientation=Vertical
MeasureName=MeasureRightPeak
Value=1

; Valor dB
[MeterDB]
Meter=String
X=90
Y=300
StringAlign=Center
FontColor=100,100,100,255
FontSize=9
FontFace=Consolas
Text="Python VU"
"""
        
        # Escribir archivo ini
        ini_path = os.path.join(skin_dir, "PythonVUMeter.ini")
        with open(ini_path, 'w', encoding='utf-8') as f:
            f.write(ini_content)
        
        # Crear archivo de variables
        vars_content = """; Variables file for Python VU Meter
; This file is updated by the Python application

[Variables]
AudioLeft=0
AudioRight=0
AudioLeftPeak=0
AudioRightPeak=0
"""
        
        vars_path = os.path.join(skin_dir, "audio_levels.inc")
        with open(vars_path, 'w', encoding='utf-8') as f:
            f.write(vars_content)
        
        # Crear archivo JSON inicial
        json_path = os.path.join(skin_dir, "audio_levels.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump({
                "levels": {"left": 0, "right": 0, "left_peak": 0, "right_peak": 0}
            }, f)
        
        print(f"Skin de Rainmeter creado en: {skin_dir}")
        return skin_dir
    
    @staticmethod
    def generate_spectrum_skin(output_dir: str, skin_name: str = "PythonSpectrum"):
        """
        Genera un skin con estilo espectro/analyzer.
        """
        skin_dir = os.path.join(output_dir, skin_name)
        os.makedirs(skin_dir, exist_ok=True)
        
        ini_content = """[Rainmeter]
Update=16
Author=Python VU Meter
Name=Python Spectrum Analyzer

[Metadata]
Name=Python Spectrum Analyzer
Description=Visualizador tipo espectro
License=MIT
Version=1.0

[Variables]
BarCount=16
BarWidth=8
BarSpacing=2
BarHeight=100
ColorBar=0,180,255,255
ColorPeak=255,255,255,200
ColorBackground=15,15,20,240

; Leer datos del JSON
[MeasureJSON]
Measure=WebParser
URL=file:///#@#audio_levels.json
RegExp="left":\\s*([0-9.]+)
LogSubstringErrors=0

[MeasureLevel]
Measure=WebParser
URL=[MeasureJSON]
StringIndex=1

; Fondo
[MeterBackground]
Meter=Shape
Shape=Rectangle 0,0,200,150,8 | Fill Color #ColorBackground# | Stroke Color 40,40,50,100,1

; Barras simuladas basadas en el nivel general
"""
        
        # Generar barras
        for i in range(16):
            ini_content += f"""
[MeterBar{i}]
Meter=Bar
X={10 + i * 12}
Y=20
W=#BarWidth#
H=#BarHeight#
BarColor=0,{180 - i * 10},255,255
SolidColor=30,30,30,255
BarOrientation=Vertical
MeasureName=MeasureLevel
Value={0.3 + (i % 5) * 0.1}
"""
        
        ini_path = os.path.join(skin_dir, "PythonSpectrum.ini")
        with open(ini_path, 'w', encoding='utf-8') as f:
            f.write(ini_content)
        
        print(f"Skin Spectrum creado en: {skin_dir}")
        return skin_dir


if __name__ == "__main__":
    # Prueba del exportador
    exporter = RainmeterExporter()
    exporter.update_levels(0.7, 0.5, 0.75, 0.55)
    
    # Generar skins
    RainmeterSkinGenerator.generate_led_skin(".")
    RainmeterSkinGenerator.generate_spectrum_skin(".")
