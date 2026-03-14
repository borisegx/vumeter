"""
VU Meter Widget - Widget visual estilo LED para PyQt6
Muestra los niveles de audio con LEDs y efectos visuales
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QFrame, QGraphicsDropShadowEffect)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPointF, QRectF, QRect
from PyQt6.QtGui import (QPainter, QColor, QBrush, QPen, QLinearGradient,
                         QRadialGradient, QPainterPath, QFont)
import json
import math
import os
import numpy as np

# Constantes de visualización
SMOOTHING_FACTOR = 0.3           # Factor de interpolación lineal (lerp)
MAX_PEAK_DECAY = 0.006           # Velocidad de caída del peak absoluto por frame (~2.8s full decay)
RENDER_FPS = 60                  # Frames por segundo del timer de renderizado
RENDER_INTERVAL_MS = 16          # ~60 FPS (1000/60)
SPECTRUM_LEDS = 8                # LEDs por barra de espectro (large)
SPECTRUM_LEDS_SMALL = 5          # LEDs por barra de espectro (small)

def spectrum_color(index: int, total: int) -> QColor:
    """Genera color HSV para banda de espectro (rojo→púrpura, cálido→frío)."""
    if total <= 1:
        return QColor.fromHsv(0, 255, 220)
    hue = int(index / (total - 1) * 270)  # 0° rojo → 270° púrpura
    return QColor.fromHsv(hue, 255, 220)

# Dimensiones por modo de tamaño (fallback)
SIZE_CONFIG = {
    'large': {'led_size': 12, 'led_spacing': 3, 'border_radius': 4, 'window': (220, 420)},
    'small': {'led_size': 6,  'led_spacing': 2, 'border_radius': 2, 'window': (120, 240)},
}

# Tamaño adaptativo de LEDs según cantidad (los LEDs se reducen con más cantidad)
LED_SIZE_CONFIG = {
    'large': {
        12: {'led_size': 14, 'led_spacing': 4, 'border_radius': 5},
        20: {'led_size': 12, 'led_spacing': 3, 'border_radius': 4},
        30: {'led_size': 8,  'led_spacing': 2, 'border_radius': 3},
    },
    'small': {
        12: {'led_size': 8, 'led_spacing': 2, 'border_radius': 3},
        20: {'led_size': 6, 'led_spacing': 2, 'border_radius': 2},
        30: {'led_size': 4, 'led_spacing': 1, 'border_radius': 2},
    },
}

# Opciones fijas de cantidad de LEDs
LED_COUNTS = [12, 20, 30]


def get_led_config(size_mode: str, num_leds: int) -> dict:
    """Retorna configuración de tamaño para LEDs según modo y cantidad."""
    mode_cfg = LED_SIZE_CONFIG.get(size_mode, LED_SIZE_CONFIG['large'])
    return mode_cfg.get(num_leds, mode_cfg[20])


class ScaleWidget(QWidget):
    """Escala dBFS pintada con QPainter, alineada con las barras LED."""

    # Marcas dB y su posición normalizada (0.0=silencio, 1.0=escala completa)
    DB_MARKS = [
        (0,   1.000),
        (-6,  0.900),
        (-12, 0.800),
        (-18, 0.700),
        (-24, 0.600),
        (-36, 0.400),
        (-48, 0.200),
    ]

    def __init__(self, num_leds: int, size_mode: str):
        super().__init__()
        cfg = get_led_config(size_mode, num_leds)
        self._bar_height = (cfg['led_size'] + cfg['led_spacing']) * num_leds + 10
        self._size_mode = size_mode
        self._font_size = 7 if size_mode == 'small' else 9
        self.setFixedWidth(35 if size_mode == 'large' else 22)
        self.setFixedHeight(self._bar_height)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        font = QFont('Consolas', self._font_size)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(112, 112, 128))

        h = self.height()
        pad = 5  # mismo padding que LEDBar
        usable = h - 2 * pad
        fm = painter.fontMetrics()
        text_h = fm.height()

        for db, norm in self.DB_MARKS:
            # norm=1.0 → arriba (y=pad), norm=0.0 → abajo (y=h-pad)
            y = pad + int(usable * (1.0 - norm))
            text = str(db)
            rect = QRect(0, y - text_h // 2, self.width(), text_h)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

        painter.end()


# Directorio de skins
SKINS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'skins')


def load_skins():
    """Carga todos los skins JSON del directorio skins/."""
    skins = {}
    if not os.path.isdir(SKINS_DIR):
        return skins
    for filename in os.listdir(SKINS_DIR):
        if filename.endswith('.json'):
            filepath = os.path.join(SKINS_DIR, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    skin_data = json.load(f)
                name = skin_data.get('name', filename.replace('.json', ''))
                skins[name.lower()] = skin_data
            except Exception:
                pass
    return skins


def get_available_skins():
    """Retorna lista de nombres de skins disponibles (builtin + JSON)."""
    builtin = ['classic', 'green', 'blue', 'purple', 'rainbow']
    custom = list(load_skins().keys())
    return builtin + [s for s in custom if s not in builtin]


class LEDBar(QWidget):
    """
    Barra de LEDs individual para mostrar un canal de audio.
    Incluye indicador de peak con hold.
    """

    def __init__(self, num_leds: int = 20, orientation: str = 'vertical',
                 color_scheme: str = 'classic', size_mode: str = 'large', parent=None):
        super().__init__(parent)

        self.num_leds = num_leds
        self.orientation = orientation
        self.color_scheme = color_scheme

        # Niveles (0.0 - 1.0)
        self.level = 0.0
        self.target_level = 0.0
        self.peak_level = 0.0
        self.max_peak_level = 0.0

        self.size_mode = size_mode
        cfg = get_led_config(size_mode, num_leds)
        self.led_size = cfg['led_size']
        self.led_spacing = cfg['led_spacing']
        self.border_radius = cfg['border_radius']

        # Esquemas de color builtin
        self._builtin_schemes = {
            'classic': self._classic_colors,
            'green': self._green_colors,
            'blue': self._blue_colors,
            'purple': self._purple_colors,
            'rainbow': self._rainbow_colors
        }

        # Cargar skins JSON externos
        self._custom_skins = load_skins()

        # Tamaño fijo para que el layout no comprima los LEDs
        if orientation == 'vertical':
            self.setMinimumWidth(self.led_size + 10)
            self.setFixedHeight((self.led_size + self.led_spacing) * num_leds + 10)
        else:
            self.setMinimumHeight(self.led_size + 10)
            self.setFixedWidth((self.led_size + self.led_spacing) * num_leds + 10)

    def _classic_colors(self, index: int, total: int) -> QColor:
        """Esquema clásico profesional: verde -> amarillo -> rojo
        Umbrales calibrados en dBFS (rango -60 a 0):
          Verde:    < -18 dBFS (ratio < 0.70) — nivel normal
          Amarillo: -18 a -6 dBFS (0.70-0.90) — nivel alto
          Rojo:     > -6 dBFS (ratio >= 0.90) — peligro de clipping
        """
        ratio = index / total
        if ratio < 0.70:
            return QColor(0, 200, 0)    # Verde — nivel seguro
        elif ratio < 0.90:
            return QColor(255, 200, 0)  # Amarillo — precaución
        else:
            return QColor(255, 50, 50)  # Rojo — peligro

    def _green_colors(self, index: int, total: int) -> QColor:
        """Esquema verde con degradado"""
        ratio = index / total
        intensity = int(100 + 155 * ratio)
        return QColor(0, intensity, 50)

    def _blue_colors(self, index: int, total: int) -> QColor:
        """Esquema azul con degradado"""
        ratio = index / total
        intensity = int(100 + 155 * ratio)
        return QColor(50, intensity, 255)

    def _purple_colors(self, index: int, total: int) -> QColor:
        """Esquema púrpura con degradado"""
        ratio = index / total
        intensity = int(100 + 155 * ratio)
        return QColor(150, 50, intensity)

    def _rainbow_colors(self, index: int, total: int) -> QColor:
        """Esquema arcoíris"""
        hue = int((index / total) * 270)  # 0-270 grados (rojo a púrpura)
        return QColor.fromHsv(hue, 255, 255)

    def _custom_skin_colors(self, index: int, total: int) -> QColor:
        """Obtiene color desde un skin JSON personalizado."""
        skin = self._custom_skins.get(self.color_scheme, {})
        led_colors = skin.get('led_colors', [])
        ratio = (index / total) * 100

        for entry in led_colors:
            r = entry.get('range', [0, 100])
            if r[0] <= ratio < r[1]:
                c = entry.get('color', [0, 200, 0])
                return QColor(c[0], c[1], c[2])

        # Fallback: último color definido o verde
        if led_colors:
            c = led_colors[-1].get('color', [0, 200, 0])
            return QColor(c[0], c[1], c[2])
        return QColor(0, 200, 0)

    def get_led_color(self, index: int, is_on: bool) -> QColor:
        """Obtiene el color de un LED específico."""
        # Intentar esquema builtin primero, luego skin JSON
        color_func = self._builtin_schemes.get(self.color_scheme)
        if color_func:
            base_color = color_func(index, self.num_leds)
        elif self.color_scheme in self._custom_skins:
            base_color = self._custom_skin_colors(index, self.num_leds)
        else:
            base_color = self._classic_colors(index, self.num_leds)

        if is_on:
            return base_color
        else:
            return QColor(base_color.red() // 5,
                         base_color.green() // 5,
                         base_color.blue() // 5)

    def set_level(self, level: float, peak: float = None):
        """
        Establece el nivel actual y el peak.

        Args:
            level: Nivel actual (0.0 - 1.0)
            peak: Nivel de peak (opcional)
        """
        self.target_level = max(0.0, min(1.0, level))
        if peak is not None:
            self.peak_level = max(0.0, min(1.0, peak))
            if self.peak_level > self.max_peak_level:
                self.max_peak_level = self.peak_level

    def apply_interpolation(self):
        """Suaviza el movimiento al interpolar el nivel actual hacia el objetivo."""
        self.level += (self.target_level - self.level) * SMOOTHING_FACTOR

        self.max_peak_level -= MAX_PEAK_DECAY
        self.max_peak_level = max(0.0, self.max_peak_level)

        self.update()

    def paintEvent(self, event):
        """Dibuja la barra de LEDs."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Fondo oscuro
        painter.fillRect(self.rect(), QColor(20, 20, 25))

        # Calcular posición de los LEDs
        if self.orientation == 'vertical':
            self._paint_vertical(painter)
        else:
            self._paint_horizontal(painter)

    def _paint_vertical(self, painter):
        """Dibuja LEDs en orientación vertical."""
        led_height = self.led_size
        led_width = self.led_size

        # Centrar horizontalmente
        start_x = (self.width() - led_width) // 2
        start_y = self.height() - 5  # Empezar desde abajo

        # Calcular el índice exacto del absolute peak y del peak balístico
        max_peak_idx = int(self.max_peak_level * self.num_leds)
        if max_peak_idx >= self.num_leds: max_peak_idx = self.num_leds - 1
        if self.max_peak_level <= 0: max_peak_idx = -1

        peak_idx = int(self.peak_level * self.num_leds)
        if peak_idx >= self.num_leds: peak_idx = self.num_leds - 1
        if self.peak_level <= 0: peak_idx = -1

        for i in range(self.num_leds):
            # Índice directo: i=0 (abajo, verde) → i=N-1 (arriba, rojo)
            led_index = i

            # Posición del LED
            y = start_y - (i + 1) * (led_height + self.led_spacing)
            x = start_x

            # Determinar si el LED está encendido
            threshold = led_index / self.num_leds
            is_on = self.level > threshold

            # Obtener color
            color = self.get_led_color(led_index, is_on)

            # Dibujar el "LED" en cian si es el absolute peak exacto
            is_max_peak_led = (led_index == max_peak_idx)
            if is_max_peak_led:
                # Peak absoluto siempre visible en cian (incluso sobre LEDs encendidos)
                color = QColor(0, 255, 255)
                self._draw_led(painter, x, y, led_width, led_height, color, True)
            else:
                # Dibujar LED normal con efecto de brillo
                self._draw_led(painter, x, y, led_width, led_height, color, is_on)

            # Dibujar indicador del peak balístico (triángulo exterior)
            if led_index == peak_idx:
                self._draw_peak_indicator(painter, x, y, led_width, led_height)

    def _paint_horizontal(self, painter):
        """Dibuja LEDs en orientación horizontal."""
        led_height = self.led_size
        led_width = self.led_size

        # Centrar verticalmente
        start_y = (self.height() - led_height) // 2
        start_x = 5

        # Calcular índices exactos para horizontal
        max_peak_idx = int(self.max_peak_level * self.num_leds)
        if max_peak_idx >= self.num_leds: max_peak_idx = self.num_leds - 1
        if self.max_peak_level <= 0: max_peak_idx = -1

        peak_idx = int(self.peak_level * self.num_leds)
        if peak_idx >= self.num_leds: peak_idx = self.num_leds - 1
        if self.peak_level <= 0: peak_idx = -1

        for i in range(self.num_leds):
            # Posición del LED
            x = start_x + i * (led_width + self.led_spacing)
            y = start_y

            # Determinar si el LED está encendido
            threshold = i / self.num_leds
            is_on = self.level > threshold

            # Obtener color
            color = self.get_led_color(i, is_on)

            # Dibujar el "LED" en cian si es el absolute peak exacto
            is_max_peak_led = (i == max_peak_idx)
            if is_max_peak_led:
                # Peak absoluto siempre visible en cian
                color = QColor(0, 255, 255)
                self._draw_led(painter, x, y, led_width, led_height, color, True)
            else:
                # Dibujar LED normal
                self._draw_led(painter, x, y, led_width, led_height, color, is_on)

            # Dibujar indicador del peak balístico (triángulo exterior)
            if i == peak_idx:
                self._draw_peak_indicator(painter, x, y, led_width, led_height)

    def _draw_led(self, painter, x, y, width, height, color, is_on):
        """Dibuja un LED individual con efectos."""
        # Rectángulo del LED
        rect = QRectF(x, y, width, height)

        # Borde del LED
        painter.setPen(QPen(QColor(60, 60, 70), 1))

        if is_on:
            # LED encendido con gradiente
            gradient = QLinearGradient(x, y, x + width, y + height)
            gradient.setColorAt(0, color.lighter(150))
            gradient.setColorAt(0.5, color)
            gradient.setColorAt(1, color.darker(120))

            painter.setBrush(QBrush(gradient))
            painter.drawRoundedRect(rect, self.border_radius, self.border_radius)

            # Efecto de brillo interior mejorado
            glow_gradient = QRadialGradient(x + width/2, y + height/2, width/0.8)
            glow_gradient.setColorAt(0, QColor(255, 255, 255, 140))
            glow_gradient.setColorAt(0.5, QColor(255, 255, 255, 40))
            glow_gradient.setColorAt(1, QColor(255, 255, 255, 0))
            painter.setBrush(QBrush(glow_gradient))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, self.border_radius, self.border_radius)

            # Glow externo moderno (Aura)
            aura_rect = rect.adjusted(-4, -4, 4, 4)
            aura_color = QColor(color)
            aura_color.setAlpha(60)
            painter.setBrush(QBrush(aura_color))
            painter.drawRoundedRect(aura_rect, self.border_radius + 2, self.border_radius + 2)
        else:
            # LED apagado
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(rect, self.border_radius, self.border_radius)

            # Efecto de reflejo sutil
            reflect = QLinearGradient(x, y, x, y + height/2)
            reflect.setColorAt(0, QColor(255, 255, 255, 20))
            reflect.setColorAt(1, QColor(255, 255, 255, 0))
            painter.setBrush(QBrush(reflect))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(x, y, width, height/2),
                                   self.border_radius, self.border_radius)

    def _draw_peak_indicator(self, painter, x, y, width, height):
        """Dibuja el indicador de peak."""
        # Triángulo pequeño
        painter.setBrush(QBrush(QColor(255, 255, 255, 200)))
        painter.setPen(Qt.PenStyle.NoPen)

        if self.orientation == 'vertical':
            # Triángulo a la izquierda
            triangle = QPainterPath()
            triangle.moveTo(x - 8, y + height/2)
            triangle.lineTo(x - 3, y + 2)
            triangle.lineTo(x - 3, y + height - 2)
            triangle.closeSubpath()
            painter.drawPath(triangle)
        else:
            # Triángulo arriba
            triangle = QPainterPath()
            triangle.moveTo(x + width/2, y - 6)
            triangle.lineTo(x + 2, y - 1)
            triangle.lineTo(x + width - 2, y - 1)
            triangle.closeSubpath()
            painter.drawPath(triangle)


class SpectrumBar(QWidget):
    """Barra horizontal LED compacta para una banda de frecuencia."""

    def __init__(self, color: QColor = None, num_leds: int = SPECTRUM_LEDS,
                 size_mode: str = 'large', parent=None):
        super().__init__(parent)
        self.num_leds = num_leds
        self.level = 0.0
        self.target_level = 0.0

        self.color = color or QColor(0, 200, 0)

        if size_mode == 'small':
            self.led_size = 4
            self.led_spacing = 1
        else:
            self.led_size = 7
            self.led_spacing = 2

        self.border_radius = 2
        bar_width = num_leds * (self.led_size + self.led_spacing)
        self.setFixedSize(bar_width, self.led_size + 4)

    def set_level(self, level: float):
        self.target_level = max(0.0, min(1.0, level))

    def apply_interpolation(self):
        self.level += (self.target_level - self.level) * SMOOTHING_FACTOR
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = (self.height() - self.led_size) // 2

        for i in range(self.num_leds):
            x = i * (self.led_size + self.led_spacing)
            threshold = i / self.num_leds
            is_on = self.level > threshold

            rect = QRectF(x, y, self.led_size, self.led_size)
            painter.setPen(QPen(QColor(50, 50, 60), 1))

            if is_on:
                gradient = QLinearGradient(x, y, x + self.led_size, y + self.led_size)
                gradient.setColorAt(0, self.color.lighter(140))
                gradient.setColorAt(0.5, self.color)
                gradient.setColorAt(1, self.color.darker(120))
                painter.setBrush(QBrush(gradient))
                painter.drawRoundedRect(rect, self.border_radius, self.border_radius)

                # Glow sutil
                glow = QColor(self.color)
                glow.setAlpha(45)
                painter.setBrush(QBrush(glow))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(rect.adjusted(-2, -2, 2, 2),
                                       self.border_radius + 1, self.border_radius + 1)
            else:
                dim = QColor(self.color.red() // 6, self.color.green() // 6, self.color.blue() // 6)
                painter.setBrush(QBrush(dim))
                painter.drawRoundedRect(rect, self.border_radius, self.border_radius)


class StereoScopeWidget(QWidget):
    """
    Display Lissajous (X-Y) para visualizar correlación estéreo.
    Eje X = canal izquierdo, Eje Y = canal derecho.
    """

    BUFFER_SIZE = 4096
    FADE_BUCKETS = 8

    def __init__(self, size_mode='large', parent=None):
        super().__init__(parent)
        self.size_mode = size_mode

        if size_mode == 'small':
            self._display_size = 80
        else:
            self._display_size = 140

        self.setFixedSize(self._display_size + 20, self._display_size + 20)

        self._buffer_left = np.zeros(self.BUFFER_SIZE, dtype=np.float32)
        self._buffer_right = np.zeros(self.BUFFER_SIZE, dtype=np.float32)
        self._buffer_pos = 0
        self._sample_count = 0

    def add_samples(self, data):
        """Agrega muestras estéreo raw al buffer circular."""
        if data.shape[1] < 2:
            return
        left = data[:, 0]
        right = data[:, 1]
        n = len(left)

        if n >= self.BUFFER_SIZE:
            self._buffer_left[:] = left[-self.BUFFER_SIZE:]
            self._buffer_right[:] = right[-self.BUFFER_SIZE:]
            self._buffer_pos = 0
        else:
            end = self._buffer_pos + n
            if end <= self.BUFFER_SIZE:
                self._buffer_left[self._buffer_pos:end] = left
                self._buffer_right[self._buffer_pos:end] = right
                self._buffer_pos = end % self.BUFFER_SIZE
            else:
                first_part = self.BUFFER_SIZE - self._buffer_pos
                self._buffer_left[self._buffer_pos:] = left[:first_part]
                self._buffer_right[self._buffer_pos:] = right[:first_part]
                remainder = n - first_part
                self._buffer_left[:remainder] = left[first_part:]
                self._buffer_right[:remainder] = right[first_part:]
                self._buffer_pos = remainder
        self._sample_count += n

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        margin = 10
        display_rect = QRectF(margin, margin, self._display_size, self._display_size)
        painter.fillRect(self.rect(), QColor(20, 20, 25))
        painter.fillRect(display_rect, QColor(10, 10, 15))

        # Guías de referencia
        cx = margin + self._display_size / 2
        cy = margin + self._display_size / 2
        painter.setPen(QPen(QColor(40, 40, 50), 1))
        painter.drawLine(int(cx), margin, int(cx), margin + self._display_size)
        painter.drawLine(margin, int(cy), margin + self._display_size, int(cy))

        # Diagonal mono (L=R)
        painter.setPen(QPen(QColor(30, 35, 30), 1, Qt.PenStyle.DotLine))
        painter.drawLine(margin, margin + self._display_size,
                         margin + self._display_size, margin)
        # Diagonal anti-fase
        painter.setPen(QPen(QColor(35, 30, 30), 1, Qt.PenStyle.DotLine))
        painter.drawLine(margin, margin,
                         margin + self._display_size, margin + self._display_size)

        total_valid = min(self._sample_count, self.BUFFER_SIZE)
        if total_valid < 2:
            painter.end()
            return

        # Leer buffer en orden (más antiguo primero)
        if self._sample_count >= self.BUFFER_SIZE:
            indices = np.arange(self._buffer_pos, self._buffer_pos + self.BUFFER_SIZE) % self.BUFFER_SIZE
        else:
            indices = np.arange(0, total_valid)

        left_samples = self._buffer_left[indices]
        right_samples = self._buffer_right[indices]

        # Downsample para rendimiento
        max_points = 800
        if len(left_samples) > max_points:
            step = len(left_samples) // max_points
            left_samples = left_samples[::step]
            right_samples = right_samples[::step]
            total_valid = len(left_samples)

        # Mapear a coordenadas de display
        half = self._display_size / 2
        xs = margin + half + left_samples * half * 0.9
        ys = margin + half - right_samples * half * 0.9

        # Calcular amplitud para colores por intensidad
        amplitudes = np.sqrt(left_samples**2 + right_samples**2)
        max_amp = max(float(np.max(amplitudes)), 0.001)
        norm_amp = amplitudes / max_amp

        # Brackets de color por amplitud (low, high, hue HSV)
        amp_brackets = [
            (0.0, 0.2, 200),    # Azul (señal baja)
            (0.2, 0.4, 160),    # Cian
            (0.4, 0.6, 120),    # Verde
            (0.6, 0.8, 60),     # Amarillo
            (0.8, 1.01, 0),     # Rojo (señal alta)
        ]

        bucket_size = max(1, total_valid // self.FADE_BUCKETS)
        dot_size = 2 if self.size_mode == 'small' else 3

        for bucket in range(self.FADE_BUCKETS):
            start = bucket * bucket_size
            end = min(start + bucket_size, total_valid)
            if start >= total_valid:
                break

            alpha = int(40 + (bucket / max(1, self.FADE_BUCKETS - 1)) * 200)

            for low, high, hue in amp_brackets:
                mask = (norm_amp[start:end] >= low) & (norm_amp[start:end] < high)
                if not np.any(mask):
                    continue

                color = QColor.fromHsv(hue, 255, 255, alpha)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(color))

                indices_in_bucket = np.where(mask)[0] + start
                for j in indices_in_bucket:
                    painter.drawEllipse(QPointF(float(xs[j]), float(ys[j])),
                                        dot_size / 2, dot_size / 2)

        painter.end()


class VUMeterWidget(QWidget):
    """
    Widget completo de VU Meter con dos canales (L/R).
    Incluye etiquetas de canal, escala dB y analizador de espectro.
    """

    # Señal emitida cuando cambian los niveles
    levels_changed = pyqtSignal(float, float, float, float)  # L, R, L_peak, R_peak
    position_changed = pyqtSignal(int, int)
    opacity_changed = pyqtSignal(float)

    def __init__(self, num_leds: int = 20, color_scheme: str = 'classic',
                 show_scale: bool = True, size_mode: str = 'large',
                 num_bands: int = 6, show_spectrum: bool = True,
                 show_stereoscope: bool = False, opacity: float = 1.0,
                 parent=None):
        """
        Inicializa el widget VU Meter.

        Args:
            num_leds: Número de LEDs por canal
            color_scheme: Esquema de colores
            show_scale: Mostrar escala en dB
            num_bands: Número de bandas de espectro (3, 6 o 12)
        """
        super().__init__(parent)

        self.num_leds = num_leds
        self.color_scheme = color_scheme
        self.show_scale = show_scale
        self.size_mode = size_mode
        self.num_bands = num_bands
        self.show_spectrum = show_spectrum
        self.show_stereoscope = show_stereoscope
        self._opacity = max(0.3, min(1.0, opacity))

        # Configurar ventana flotante
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        # Niveles actuales
        self.left_level = 0.0
        self.right_level = 0.0
        self.left_peak = 0.0
        self.right_peak = 0.0

        # Configurar UI
        self._setup_ui()

        # Aplicar opacidad
        self.setWindowOpacity(self._opacity)

        # Efecto de sombra para la ventana flotante (Neon / Elevación)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 180))
        shadow.setOffset(0, 5)
        self.findChild(QFrame, "container").setGraphicsEffect(shadow)

        # Timer para decaimiento suave y animaciones fluidas
        self.decay_timer = QTimer()
        self.decay_timer.timeout.connect(self._apply_decay)
        self.decay_timer.start(RENDER_INTERVAL_MS)

        # Permitir arrastrar la ventana
        self.drag_position = None

    def _setup_ui(self):
        """Configura la interfaz del widget."""
        # Layout principal
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(5)

        # Contenedor principal con fondo
        container = QFrame()
        container.setObjectName("container")
        container.setStyleSheet("""
            QFrame#container {
                background-color: rgba(25, 25, 30, 220);
                border-radius: 12px;
                border: 1px solid rgba(80, 80, 100, 150);
            }
        """)

        container_layout = QVBoxLayout(container)
        if self.size_mode == 'small':
            container_layout.setContentsMargins(8, 10, 8, 10)
            container_layout.setSpacing(6)
        else:
            container_layout.setContentsMargins(15, 20, 15, 20)
            container_layout.setSpacing(12)

        # Título
        title_font_size = "9px" if self.size_mode == 'small' else "13px"
        title = QLabel("VU METER")
        title.setStyleSheet(f"""
            QLabel {{
                color: #A0A0B0;
                font-size: {title_font_size};
                font-weight: 800;
                font-family: 'Segoe UI', Arial, sans-serif;
                letter-spacing: 3px;
            }}
        """)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.addWidget(title)

        # Layout para los canales
        channels_layout = QHBoxLayout()
        channels_layout.setSpacing(10 if self.size_mode == 'small' else 20)

        # Canal izquierdo
        left_channel = self._create_channel_widget("L", "left")
        self.left_bar = left_channel.findChild(LEDBar, "left_bar")
        channels_layout.addWidget(left_channel)

        # Escala central (opcional)
        if self.show_scale:
            scale_widget = self._create_scale_widget()
            channels_layout.addWidget(scale_widget)

        # Canal derecho
        right_channel = self._create_channel_widget("R", "right")
        self.right_bar = right_channel.findChild(LEDBar, "right_bar")
        channels_layout.addWidget(right_channel)

        container_layout.addLayout(channels_layout)

        # Etiqueta de dB
        db_font_size = "8px" if self.size_mode == 'small' else "11px"
        self.db_label = QLabel("-\u221e dB")
        self.db_label.setStyleSheet(f"""
            QLabel {{
                color: #9090A0;
                font-size: {db_font_size};
                font-weight: bold;
                font-family: 'Consolas', monospace;
            }}
        """)
        self.db_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container_layout.addWidget(self.db_label)

        # --- SECCIÓN DE ESPECTRO (condicional) ---
        self.left_spectrum_bars = []
        self.right_spectrum_bars = []

        if self.show_spectrum:
            separator = QFrame()
            separator.setFrameShape(QFrame.Shape.HLine)
            separator.setStyleSheet("background-color: rgba(80, 80, 100, 100);")
            separator.setFixedHeight(1)
            container_layout.addWidget(separator)

            spec_title_size = "7px" if self.size_mode == 'small' else "10px"
            spec_title = QLabel("SPECTRUM")
            spec_title.setStyleSheet(f"""
                QLabel {{
                    color: #808090;
                    font-size: {spec_title_size};
                    font-weight: 700;
                    font-family: 'Segoe UI', Arial, sans-serif;
                    letter-spacing: 2px;
                }}
            """)
            spec_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            container_layout.addWidget(spec_title)

            from audio_capture import SPECTRUM_PRESETS
            preset = SPECTRUM_PRESETS.get(self.num_bands, SPECTRUM_PRESETS[6])
            band_labels = preset['labels']

            num_spec_leds = SPECTRUM_LEDS_SMALL if self.size_mode == 'small' else SPECTRUM_LEDS
            hz_font_size = "6px" if self.size_mode == 'small' else "8px"
            hz_label_width = 24 if self.size_mode == 'small' else 30

            for i, hz_text in enumerate(band_labels):
                row = QHBoxLayout()
                row.setSpacing(2)
                row.setContentsMargins(0, 0, 0, 0)

                color = spectrum_color(i, len(band_labels))
                left_bar = SpectrumBar(color=color, num_leds=num_spec_leds, size_mode=self.size_mode)
                self.left_spectrum_bars.append(left_bar)
                row.addWidget(left_bar)

                hz_lbl = QLabel(hz_text)
                hz_lbl.setStyleSheet(f"""
                    QLabel {{
                        color: #606070;
                        font-size: {hz_font_size};
                        font-weight: bold;
                        font-family: 'Consolas', monospace;
                    }}
                """)
                hz_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                hz_lbl.setFixedWidth(hz_label_width)
                row.addWidget(hz_lbl)

                right_bar = SpectrumBar(color=color, num_leds=num_spec_leds, size_mode=self.size_mode)
                self.right_spectrum_bars.append(right_bar)
                row.addWidget(right_bar)

                container_layout.addLayout(row)

        # --- SECCIÓN DE ESTEREOSCOPIO (condicional) ---
        self.stereoscope = None

        if self.show_stereoscope:
            stereo_sep = QFrame()
            stereo_sep.setFrameShape(QFrame.Shape.HLine)
            stereo_sep.setStyleSheet("background-color: rgba(80, 80, 100, 100);")
            stereo_sep.setFixedHeight(1)
            container_layout.addWidget(stereo_sep)

            stereo_title_size = "7px" if self.size_mode == 'small' else "10px"
            stereo_title = QLabel("STEREO SCOPE")
            stereo_title.setStyleSheet(f"""
                QLabel {{
                    color: #808090;
                    font-size: {stereo_title_size};
                    font-weight: 700;
                    font-family: 'Segoe UI', Arial, sans-serif;
                    letter-spacing: 2px;
                }}
            """)
            stereo_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            container_layout.addWidget(stereo_title)

            self.stereoscope = StereoScopeWidget(size_mode=self.size_mode)
            container_layout.addWidget(self.stereoscope, alignment=Qt.AlignmentFlag.AlignCenter)

        main_layout.addWidget(container)

        # Ancho fijo, alto automático según contenido real
        width = 120 if self.size_mode == 'small' else 220
        self.setFixedWidth(width)
        self.adjustSize()

    def _create_channel_widget(self, label: str, name: str) -> QWidget:
        """Crea un widget de canal con etiqueta y barra LED."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        # Etiqueta del canal
        label_font_size = "10px" if self.size_mode == 'small' else "14px"
        channel_label = QLabel(label)
        channel_label.setStyleSheet(f"""
            QLabel {{
                color: #C0C0D0;
                font-size: {label_font_size};
                font-weight: 900;
                font-family: 'Segoe UI', Arial, sans-serif;
            }}
        """)
        channel_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(channel_label)

        # Barra de LEDs
        led_bar = LEDBar(
            num_leds=self.num_leds,
            orientation='vertical',
            color_scheme=self.color_scheme,
            size_mode=self.size_mode
        )
        led_bar.setObjectName(f"{name}_bar")
        layout.addWidget(led_bar, 1)

        # Valor numérico
        value_label = QLabel("0.00")
        value_label.setStyleSheet("""
            QLabel {
                color: #888;
                font-size: 10px;
                font-family: monospace;
            }
        """)
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value_label.setObjectName(f"{name}_value")
        layout.addWidget(value_label)

        return widget

    def _create_scale_widget(self) -> QWidget:
        """Crea el widget de escala dBFS alineado con las barras LED."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)  # mismo spacing que _create_channel_widget

        # Espaciador superior (misma fuente que label de canal para igualar altura)
        label_font_size = "10px" if self.size_mode == 'small' else "14px"
        top_spacer = QLabel("")
        top_spacer.setStyleSheet(f"font-size: {label_font_size};")
        top_spacer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(top_spacer)

        # Escala pintada con QPainter (misma altura que LEDBar)
        scale = ScaleWidget(self.num_leds, self.size_mode)
        layout.addWidget(scale, 1)

        # Espaciador inferior (misma fuente que value label para igualar altura)
        bottom_spacer = QLabel("")
        bottom_spacer.setStyleSheet("font-size: 10px; font-family: monospace;")
        bottom_spacer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(bottom_spacer)

        return widget

    def set_levels(self, left: float, right: float,
                   left_peak: float = None, right_peak: float = None):
        """
        Establece los niveles de audio.

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

        # Actualizar barras
        self.left_bar.set_level(self.left_level, self.left_peak)
        self.right_bar.set_level(self.right_level, self.right_peak)

        # Actualizar etiquetas de valor
        left_value = self.findChild(QLabel, "left_value")
        right_value = self.findChild(QLabel, "right_value")
        if left_value:
            left_value.setText(f"{self.left_level:.2f}")
        if right_value:
            right_value.setText(f"{self.right_level:.2f}")

        # Emitir señal
        self.levels_changed.emit(self.left_level, self.right_level,
                                self.left_peak, self.right_peak)

    def set_spectrum(self, left_bands: list, right_bands: list):
        """Establece los niveles de las bandas de frecuencia."""
        for i, level in enumerate(left_bands):
            if i < len(self.left_spectrum_bars):
                self.left_spectrum_bars[i].set_level(level)
        for i, level in enumerate(right_bands):
            if i < len(self.right_spectrum_bars):
                self.right_spectrum_bars[i].set_level(level)

    def set_raw_samples(self, data):
        """Alimenta muestras raw al estereoscopio."""
        if self.stereoscope is not None:
            self.stereoscope.add_samples(data)

    def _apply_decay(self):
        """Aplica decaimiento suave a los niveles e interpola visualmente."""
        if hasattr(self, 'left_bar'):
            self.left_bar.apply_interpolation()
        if hasattr(self, 'right_bar'):
            self.right_bar.apply_interpolation()

        # Mostrar dBFS del nivel suavizado (coincide visualmente con las barras LED)
        if hasattr(self, 'left_bar') and hasattr(self, 'right_bar'):
            smoothed = max(self.left_bar.level, self.right_bar.level)
            if smoothed > 0.001:
                from audio_capture import DB_FLOOR, DB_RANGE
                db = smoothed * DB_RANGE + DB_FLOOR
                self.db_label.setText(f"{db:.1f} dBFS")
            else:
                self.db_label.setText("-\u221e dBFS")

        for bar in getattr(self, 'left_spectrum_bars', []):
            bar.apply_interpolation()
        for bar in getattr(self, 'right_spectrum_bars', []):
            bar.apply_interpolation()
        if self.stereoscope is not None:
            self.stereoscope.update()

    def mousePressEvent(self, event):
        """Permite arrastrar la ventana."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        """Mueve la ventana al arrastrar."""
        if event.buttons() & Qt.MouseButton.LeftButton and self.drag_position:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def moveEvent(self, event):
        """Emite posición cuando la ventana se mueve."""
        super().moveEvent(event)
        pos = self.pos()
        self.position_changed.emit(pos.x(), pos.y())

    def wheelEvent(self, event):
        """Cambia opacidad con la rueda del mouse."""
        delta = event.angleDelta().y()
        step = 0.05
        if delta > 0:
            self._opacity = min(1.0, self._opacity + step)
        else:
            self._opacity = max(0.3, self._opacity - step)
        self.setWindowOpacity(self._opacity)
        self.opacity_changed.emit(self._opacity)
        event.accept()

    def mouseDoubleClickEvent(self, event):
        """Cierra la ventana con doble clic."""
        self.close()

    def contextMenuEvent(self, event):
        """Muestra menú contextual."""
        from PyQt6.QtWidgets import QMenu

        menu = QMenu(self)

        # Opciones de color (builtin + custom skins)
        color_menu = menu.addMenu("Color Scheme")
        for scheme in get_available_skins():
            action = color_menu.addAction(scheme.capitalize())
            action.triggered.connect(lambda checked, s=scheme: self._change_color(s))

        menu.addSeparator()

        reset_peaks_action = menu.addAction("Reset Peaks")
        reset_peaks_action.triggered.connect(self._reset_peaks)

        menu.addSeparator()

        close_action = menu.addAction("Close")
        close_action.triggered.connect(self.close)

        menu.exec(event.globalPos())

    def _reset_peaks(self):
        """Reinicia los indicadores de peak absoluto."""
        self.left_bar.max_peak_level = 0.0
        self.right_bar.max_peak_level = 0.0

    def _change_color(self, scheme: str):
        """Cambia el esquema de colores."""
        self.color_scheme = scheme
        self.left_bar.color_scheme = scheme
        self.right_bar.color_scheme = scheme
        self.left_bar.update()
        self.right_bar.update()


# Prueba del widget
if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)

    # Crear y mostrar el widget
    meter = VUMeterWidget(num_leds=20, color_scheme='classic')
    meter.show()

    # Simular niveles
    import math
    t = 0

    def update():
        global t
        t += 0.1
        level = 0.5 + 0.3 * math.sin(t)
        meter.set_levels(level, level * 0.8, level * 1.1, level * 0.9)

    timer = QTimer()
    timer.timeout.connect(update)
    timer.start(50)

    sys.exit(app.exec())
