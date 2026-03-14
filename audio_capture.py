"""
Audio Capture Module - WASAPI Loopback para capturar audio del sistema
Implementación segura mediante QThread y pyaudiowpatch (WASAPI nativo).
"""

import numpy as np
import math
import time
from PyQt6.QtCore import QThread, pyqtSignal

# Intentar importar pyaudiowpatch para captura WASAPI loopback nativa
try:
    import pyaudiowpatch as pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False
    print("Libreria pyaudiowpatch no instalada. Operando en modo simulacion.")

# Constantes de captura de audio
DEFAULT_SAMPLE_RATE = 44100
DEFAULT_CHUNK_SIZE = 1024
BALLISTIC_DECAY_RATE = 3.0       # Factor de decaimiento exponencial (seg^-1)
DB_FLOOR = -60.0                 # Piso en dB (silencio)
DB_CEILING = 6.0                 # Techo en dB (+6dB headroom para evitar saturación visual)
DB_RANGE = DB_CEILING - DB_FLOOR # Rango total en dB
SIMULATION_STEP = 0.05           # Incremento temporal en simulación
SIMULATION_SLEEP = 0.02          # Pausa entre frames de simulación (seg)
DEVICE_REFRESH_INTERVAL = 5000   # Intervalo de refresco de dispositivos (ms)

# Presets de bandas de frecuencia para el analizador de espectro
SPECTRUM_PRESETS = {
    3: {
        'bands': [(20, 250), (250, 4000), (4000, 22000)],
        'labels': ['Low', 'Mid', 'High'],
    },
    6: {
        'bands': [
            (20, 100), (100, 350), (350, 1000),
            (1000, 5000), (5000, 10000), (10000, 22000),
        ],
        'labels': ['20', '100', '350', '1k', '5k', '10k'],
    },
    12: {
        'bands': [
            (20, 60), (60, 150), (150, 300), (300, 500),
            (500, 1000), (1000, 2000), (2000, 4000), (4000, 6000),
            (6000, 8000), (8000, 12000), (12000, 16000), (16000, 22000),
        ],
        'labels': ['20', '60', '150', '300', '500', '1k', '2k', '4k', '6k', '8k', '12k', '16k'],
    },
}
# Constantes por defecto (compatibilidad)
SPECTRUM_BANDS = SPECTRUM_PRESETS[6]['bands']
SPECTRUM_BAND_LABELS = SPECTRUM_PRESETS[6]['labels']


class AudioCapture(QThread):
    """
    Captura audio del sistema usando WASAPI Loopback via pyaudiowpatch.
    Opera en un hilo separado para no bloquear la interfaz gráfica.
    """

    # Señal thread-safe para enviar datos a la ventana principal
    levels_updated = pyqtSignal(float, float, float, float)
    # Señal para datos de espectro de frecuencias (left_bands, right_bands)
    spectrum_updated = pyqtSignal(list, list)
    # Señal para muestras raw (estereoscopio Lissajous)
    raw_samples_updated = pyqtSignal(object)

    def __init__(self, sample_rate=DEFAULT_SAMPLE_RATE, chunk_size=DEFAULT_CHUNK_SIZE,
                 simulation_mode=False, device_name=None, num_bands=6):
        super().__init__()
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.simulation_mode = simulation_mode
        self.device_name = device_name
        self.is_running = False

        # Configuración de bandas de espectro
        preset = SPECTRUM_PRESETS.get(num_bands, SPECTRUM_PRESETS[6])
        self._spectrum_bands = preset['bands']

        # Niveles actuales
        self.left_peak = 0.0
        self.right_peak = 0.0
        self.last_time = time.time()

        self.decay_rate = BALLISTIC_DECAY_RATE

        # Ventana Hann pre-calculada para FFT (evita recalcularla cada frame)
        self._hann_window = np.hanning(self.chunk_size)

    def run(self):
        """Punto de entrada del hilo de captura."""
        self.is_running = True

        if self.simulation_mode or not PYAUDIO_AVAILABLE:
            self._simulate_audio()
            return

        p = None
        stream = None
        try:
            p = pyaudio.PyAudio()

            # Buscar dispositivo loopback correspondiente al dispositivo de salida
            device_index, device_info = self._find_loopback_device(p)

            if device_index is None:
                print("[ERROR] No se encontro dispositivo loopback WASAPI")
                print(">> Activando modo simulacion...")
                self._simulate_audio()
                return

            channels = min(2, device_info['maxInputChannels'])
            sample_rate = int(device_info['defaultSampleRate'])

            # Actualizar sample rate real para cálculos de FFT correctos
            self.sample_rate = sample_rate

            stream = p.open(
                format=pyaudio.paFloat32,
                channels=channels,
                rate=sample_rate,
                input=True,
                input_device_index=device_index,
                frames_per_buffer=self.chunk_size
            )

            print(f">> Captura loopback WASAPI iniciada: {device_info['name']}")
            print(f"   Canales: {channels}, Sample rate: {sample_rate} Hz")

            while self.is_running:
                data = stream.read(self.chunk_size, exception_on_overflow=False)
                audio_data = np.frombuffer(data, dtype=np.float32)

                if channels >= 2:
                    audio_data = audio_data.reshape(-1, channels)
                else:
                    audio_data = audio_data.reshape(-1, 1)

                self._process_audio(audio_data)

        except Exception as e:
            print(f"[ERROR] Fallo en la captura loopback: {e}")
            print(">> Activando modo simulacion para mantener la estabilidad...")
            self._simulate_audio()
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            if p is not None:
                try:
                    p.terminate()
                except Exception:
                    pass

    def _find_loopback_device(self, p):
        """
        Busca el dispositivo loopback WASAPI correspondiente al dispositivo
        de salida seleccionado por el usuario.

        Returns:
            tuple: (device_index, device_info) o (None, None)
        """
        try:
            wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError:
            print("[ERROR] WASAPI no disponible en este sistema")
            return None, None

        # Determinar el dispositivo de salida objetivo
        target_output_info = None

        if self.device_name and self.device_name != "Default System Audio":
            # Buscar el dispositivo específico seleccionado por el usuario
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if (info['hostApi'] == wasapi_info['index'] and
                    not info.get('isLoopbackDevice', False) and
                    info['maxOutputChannels'] > 0 and
                    info['name'] == self.device_name):
                    target_output_info = info
                    break

        # Si no se encontró o es "Default", usar el dispositivo por defecto del sistema
        if target_output_info is None:
            default_idx = wasapi_info['defaultOutputDevice']
            target_output_info = p.get_device_info_by_index(default_idx)

        target_name = target_output_info['name']
        print(f">> Buscando loopback para dispositivo: {target_name}")

        # Buscar el dispositivo loopback correspondiente
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if (info.get('isLoopbackDevice', False) and
                target_name in info['name']):
                return i, info

        print(f"[WARN] No se encontro loopback para '{target_name}'")
        return None, None

    @staticmethod
    def _rms_to_display(rms):
        """Convierte RMS crudo a nivel de display (0.0-1.0) usando escala dB."""
        if rms <= 0:
            return 0.0
        db = 20.0 * math.log10(rms)
        # Mapear rango de -60 dB a 0 dB → 0.0 a 1.0
        normalized = (db - DB_FLOOR) / DB_RANGE
        return max(0.0, min(1.0, normalized))

    def _compute_spectrum(self, channel_data):
        """Calcula el espectro de potencia agrupado en bandas de frecuencia."""
        windowed = channel_data * self._hann_window
        fft_mag = np.abs(np.fft.rfft(windowed))
        freq_resolution = self.sample_rate / len(channel_data)
        sqrt_n = np.sqrt(len(channel_data))

        bands = []
        for low_hz, high_hz in self._spectrum_bands:
            low_bin = max(1, int(low_hz / freq_resolution))
            high_bin = min(len(fft_mag) - 1, int(high_hz / freq_resolution))
            if high_bin > low_bin:
                # RMS de magnitudes en la banda, normalizado por √N (Parseval)
                band_mag = np.sqrt(np.mean(fft_mag[low_bin:high_bin + 1] ** 2)) / sqrt_n
            else:
                band_mag = fft_mag[low_bin] / sqrt_n if low_bin < len(fft_mag) else 0.0
            bands.append(self._rms_to_display(band_mag))
        return bands

    def _process_audio(self, data):
        """Calcula el valor RMS matemático de la señal y lo normaliza en escala dB."""
        # Evitar errores si el hardware entrega un solo canal
        if data.shape[1] >= 2:
            left_rms = np.sqrt(np.mean(data[:, 0]**2))
            right_rms = np.sqrt(np.mean(data[:, 1]**2))
        else:
            left_rms = right_rms = np.sqrt(np.mean(data[:, 0]**2))

        # Normalizar a escala de display (dB → 0.0-1.0)
        left = self._rms_to_display(left_rms)
        right = self._rms_to_display(right_rms)

        # Cálculo del tiempo delta para una física independiente del framerate
        current_time = time.time()
        dt = current_time - self.last_time
        self.last_time = current_time

        # Inercia balística mediante decaimiento exponencial
        decay_factor = np.exp(-self.decay_rate * dt)

        # Actualización de picos con resistencia a la caída
        self.left_peak = left if left > self.left_peak else self.left_peak * decay_factor
        self.right_peak = right if right > self.right_peak else self.right_peak * decay_factor

        # Emitir la señal de forma segura a la interfaz
        self.levels_updated.emit(left, right, self.left_peak, self.right_peak)

        # Análisis de espectro por bandas de frecuencia
        if data.shape[1] >= 2:
            left_bands = self._compute_spectrum(data[:, 0])
            right_bands = self._compute_spectrum(data[:, 1])
        else:
            left_bands = self._compute_spectrum(data[:, 0])
            right_bands = left_bands[:]
        self.spectrum_updated.emit(left_bands, right_bands)

        # Emitir muestras raw para estereoscopio
        self.raw_samples_updated.emit(data.copy())

    def stop(self):
        """Detiene la ejecución del hilo de forma limpia."""
        self.is_running = False
        self.wait()
        print("[STOP] Captura de audio detenida")

    def _simulate_audio(self):
        """Genera patrones matemáticos para demostración sin hardware."""
        print("[DEMO] Modo simulacion activado")
        t = 0
        while self.is_running:
            t += 0.05

            # Crear patrones de onda oscilatoria simulada
            base = 0.3 + 0.2 * np.sin(t * 0.5)
            left = min(1.0, max(0.0, base + 0.1 * np.sin(t * 7)))
            right = min(1.0, max(0.0, base - 0.1 * np.sin(t * 3)))

            current_time = time.time()
            dt = current_time - self.last_time
            self.last_time = current_time

            decay_factor = np.exp(-self.decay_rate * dt)
            self.left_peak = left if left > self.left_peak else self.left_peak * decay_factor
            self.right_peak = right if right > self.right_peak else self.right_peak * decay_factor

            self.levels_updated.emit(left, right, self.left_peak, self.right_peak)

            # Espectro simulado (bandas con patrones distintos)
            num = len(self._spectrum_bands)
            left_bands = [min(1.0, max(0.0, base + 0.15 * np.sin(t * (2 + i * 1.3)))) for i in range(num)]
            right_bands = [min(1.0, max(0.0, base + 0.15 * np.sin(t * (2.5 + i * 1.1)))) for i in range(num)]
            self.spectrum_updated.emit(left_bands, right_bands)

            # Muestras raw simuladas para estereoscopio
            num_samples = self.chunk_size
            t_arr = np.linspace(t - SIMULATION_STEP, t, num_samples)
            sim_left = 0.3 * np.sin(2 * np.pi * 440 * t_arr) + 0.1 * np.sin(2 * np.pi * 880 * t_arr)
            sim_right = 0.3 * np.sin(2 * np.pi * 440 * t_arr + 0.5) + 0.1 * np.sin(2 * np.pi * 660 * t_arr)
            sim_data = np.column_stack([sim_left, sim_right]).astype(np.float32)
            self.raw_samples_updated.emit(sim_data)

            time.sleep(0.02)

    @staticmethod
    def get_audio_devices() -> list:
        """
        Retorna una lista con los nombres de los dispositivos de salida de audio disponibles.
        Solo muestra dispositivos WASAPI de salida (speakers/auriculares).
        """
        if not PYAUDIO_AVAILABLE:
            return ["Default System Audio"]

        try:
            p = pyaudio.PyAudio()
            devices = ["Default System Audio"]

            try:
                wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            except OSError:
                p.terminate()
                return devices

            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                # Solo dispositivos WASAPI de salida, excluyendo loopback
                if (info['hostApi'] == wasapi_info['index'] and
                    info['maxOutputChannels'] > 0 and
                    not info.get('isLoopbackDevice', False)):
                    name = info['name']
                    if name not in devices:
                        devices.append(name)

            p.terminate()
            return devices
        except Exception as e:
            print(f"[ERROR] No se pudo obtener la lista de dispositivos: {e}")
            return ["Default System Audio"]
