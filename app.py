"""
VU Meter Application - Aplicación principal
Captura audio del sistema y lo visualiza en un VU Meter flotante
"""

import sys
import os
import json
import argparse
import winreg
from pathlib import Path

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QComboBox,
                             QCheckBox, QSystemTrayIcon, QMenu,
                             QFrame, QSpinBox, QSlider)
from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import QIcon, QFont, QPixmap, QPainter, QColor, QBrush, QAction

# Importar módulos locales
from audio_capture import AudioCapture, DEVICE_REFRESH_INTERVAL
from vu_meter_widget import VUMeterWidget, get_available_skins

# Archivo de configuración persistente
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vumeter_config.json')

# Configuración por defecto
DEFAULT_CONFIG = {
    'color_scheme': 0,
    'num_leds': 20,
    'size_mode': 0,
    'spectrum_bands': 1,  # Índice: 0=3 bandas, 1=6 bandas, 2=12 bandas
    'always_on_top': True,
    'device': 'Default System Audio',
    'show_spectrum': True,
    'show_stereoscope': False,
    'window_x': None,
    'window_y': None,
    'opacity': 1.0,
    'auto_start': False,
}


def load_config():
    """Carga configuración desde archivo JSON."""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            saved = json.load(f)
        # Merge con defaults para cubrir claves nuevas
        config = DEFAULT_CONFIG.copy()
        config.update(saved)
        return config
    except Exception:
        return DEFAULT_CONFIG.copy()


def save_config(config):
    """Guarda configuración a archivo JSON."""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
    except Exception:
        pass


AUTOSTART_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_APP_NAME = "VUMeter"


def get_autostart_command():
    """Genera el comando para auto-inicio usando pythonw.exe con el .pyw."""
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'start_vumeter.pyw')
    venv_pythonw = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'venv', 'Scripts', 'pythonw.exe')
    if os.path.exists(venv_pythonw):
        return f'"{venv_pythonw}" "{script_path}" --hidden'
    return f'pythonw.exe "{script_path}" --hidden'


def is_autostart_enabled():
    """Verifica si el auto-inicio está habilitado en el registro."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REG_KEY, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, AUTOSTART_APP_NAME)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return False


def set_autostart(enabled):
    """Agrega o remueve la entrada de auto-inicio del registro."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REG_KEY, 0, winreg.KEY_SET_VALUE)
        if enabled:
            winreg.SetValueEx(key, AUTOSTART_APP_NAME, 0, winreg.REG_SZ, get_autostart_command())
        else:
            try:
                winreg.DeleteValue(key, AUTOSTART_APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception as e:
        print(f"[ERROR] No se pudo modificar auto-inicio: {e}")


def create_vu_icon():
    """Genera un icono VU Meter programáticamente (sin archivo externo)."""
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Fondo circular oscuro
    painter.setBrush(QBrush(QColor(30, 30, 40)))
    painter.setPen(QColor(80, 80, 100))
    painter.drawRoundedRect(2, 2, size - 4, size - 4, 12, 12)

    # Barras LED simuladas (izq)
    colors = [QColor(0, 200, 0), QColor(0, 200, 0), QColor(255, 200, 0), QColor(255, 50, 50)]
    bar_heights = [30, 22, 14, 8]
    for i, (c, h) in enumerate(zip(colors, bar_heights)):
        painter.setBrush(QBrush(c))
        painter.setPen(Qt.PenStyle.NoPen)
        y = size - 10 - h
        painter.drawRoundedRect(14, y, 8, h, 2, 2)

    # Barras LED simuladas (der)
    bar_heights_r = [26, 20, 10, 5]
    for i, (c, h) in enumerate(zip(colors, bar_heights_r)):
        painter.setBrush(QBrush(c))
        painter.drawRoundedRect(42, size - 10 - h, 8, h, 2, 2)

    painter.end()
    return QIcon(pixmap)


class MainWindow(QMainWindow):
    """
    Ventana principal de la aplicación VU Meter.
    Proporciona configuración y control del VU Meter.
    """

    def __init__(self, simulation_mode: bool = False):
        """
        Inicializa la ventana principal.

        Args:
            simulation_mode: Forzar modo simulación (sin captura real)
        """
        super().__init__()

        self.simulation_mode = simulation_mode

        # Cargar configuración persistente
        self.config = load_config()

        # Configurar ventana
        self.setWindowTitle("VU Meter - Configuracion")
        self.setMinimumSize(350, 580)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowMaximizeButtonHint)

        # Variables
        self.vu_meter = None
        self.audio_capture = None
        self.is_running = False

        # Configurar UI
        self._setup_ui()
        self._setup_tray_icon()

        # Aplicar configuración guardada
        self._apply_saved_config()

        # Timer para refrescar dispositivos de audio
        self.device_refresh_timer = QTimer()
        self.device_refresh_timer.timeout.connect(self._refresh_devices)
        self.device_refresh_timer.start(DEVICE_REFRESH_INTERVAL)

    def _setup_ui(self):
        """Configura la interfaz de usuario."""
        # Widget central
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Layout principal
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # Título
        title = QLabel("VU METER")
        title.setStyleSheet("""
            QLabel {
                font-size: 20px;
                font-weight: bold;
                color: #333;
            }
        """)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title)

        # Separador
        line1 = QFrame()
        line1.setFrameShape(QFrame.Shape.HLine)
        line1.setStyleSheet("background-color: #ddd;")
        main_layout.addWidget(line1)

        # Sección de configuración
        config_label = QLabel("Configuración")
        config_label.setStyleSheet("font-weight: bold; color: #555;")
        main_layout.addWidget(config_label)

        # Audio Device Selector
        device_layout = QHBoxLayout()
        device_label = QLabel("Dispositivo de audio:")
        self.device_combo = QComboBox()
        # Obtener lista de dispositivos
        try:
            devices = AudioCapture.get_audio_devices()
            self.device_combo.addItems(devices)
        except Exception:
            self.device_combo.addItem("Default System Audio")

        device_layout.addWidget(device_label)
        device_layout.addWidget(self.device_combo)
        main_layout.addLayout(device_layout)

        # Color scheme (builtin + skins JSON)
        color_layout = QHBoxLayout()
        color_label = QLabel("Esquema de colores:")
        self.color_combo = QComboBox()
        self._populate_color_combo()
        color_layout.addWidget(color_label)
        color_layout.addWidget(self.color_combo)
        main_layout.addLayout(color_layout)

        # Número de LEDs
        led_layout = QHBoxLayout()
        led_label = QLabel("Número de LEDs:")
        self.led_spin = QSpinBox()
        self.led_spin.setRange(10, 30)
        self.led_spin.setValue(20)
        led_layout.addWidget(led_label)
        led_layout.addWidget(self.led_spin)
        main_layout.addLayout(led_layout)

        # Tamaño
        size_layout = QHBoxLayout()
        size_label = QLabel("Tamaño:")
        self.size_combo = QComboBox()
        self.size_combo.addItems(['Grande', 'Pequeño'])
        size_layout.addWidget(size_label)
        size_layout.addWidget(self.size_combo)
        main_layout.addLayout(size_layout)

        # Mostrar espectro
        self.show_spectrum_check = QCheckBox("Mostrar espectro")
        self.show_spectrum_check.setChecked(True)
        self.show_spectrum_check.stateChanged.connect(self._on_spectrum_toggle)
        main_layout.addWidget(self.show_spectrum_check)

        # Bandas de espectro (dentro de un widget para show/hide)
        self.bands_widget = QWidget()
        bands_inner_layout = QHBoxLayout(self.bands_widget)
        bands_inner_layout.setContentsMargins(20, 0, 0, 0)
        bands_label = QLabel("Bandas de espectro:")
        self.bands_combo = QComboBox()
        self.bands_combo.addItems(['3 bandas (Low/Mid/High)', '6 bandas', '12 bandas'])
        self.bands_combo.setCurrentIndex(1)
        bands_inner_layout.addWidget(bands_label)
        bands_inner_layout.addWidget(self.bands_combo)
        main_layout.addWidget(self.bands_widget)

        # Mostrar estereoscopio
        self.show_stereoscope_check = QCheckBox("Mostrar estereoscopio (Lissajous)")
        self.show_stereoscope_check.setChecked(False)
        main_layout.addWidget(self.show_stereoscope_check)

        # Opacidad
        opacity_layout = QHBoxLayout()
        opacity_label = QLabel("Opacidad:")
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(30, 100)
        self.opacity_slider.setValue(100)
        self.opacity_value_label = QLabel("100%")
        self.opacity_value_label.setFixedWidth(35)
        self.opacity_slider.valueChanged.connect(
            lambda v: self.opacity_value_label.setText(f"{v}%")
        )
        opacity_layout.addWidget(opacity_label)
        opacity_layout.addWidget(self.opacity_slider)
        opacity_layout.addWidget(self.opacity_value_label)
        main_layout.addLayout(opacity_layout)

        # Checkboxes
        self.always_on_top_check = QCheckBox("Siempre visible")
        self.always_on_top_check.setChecked(True)
        main_layout.addWidget(self.always_on_top_check)

        # Auto-inicio con Windows
        self.auto_start_check = QCheckBox("Iniciar con Windows")
        self.auto_start_check.setChecked(False)
        self.auto_start_check.stateChanged.connect(self._on_autostart_toggle)
        main_layout.addWidget(self.auto_start_check)

        # Separador
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setStyleSheet("background-color: #ddd;")
        main_layout.addWidget(line2)

        # Indicador de estado con icono de captura
        status_container = QHBoxLayout()

        self.capture_indicator = QLabel()
        self.capture_indicator.setFixedSize(12, 12)
        self.capture_indicator.setStyleSheet("""
            QLabel {
                background-color: #aaa;
                border-radius: 6px;
                border: 1px solid #888;
            }
        """)
        status_container.addWidget(self.capture_indicator)

        self.status_label = QLabel("Detenido")
        self.status_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                padding: 10px;
                background-color: #f5f5f5;
                border-radius: 5px;
            }
        """)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_container.addWidget(self.status_label)

        main_layout.addLayout(status_container)

        # Botones
        btn_layout = QHBoxLayout()

        self.start_btn = QPushButton("Iniciar")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 10px 20px;
                border-radius: 5px;
                border: none;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.start_btn.clicked.connect(self._toggle_vu_meter)
        btn_layout.addWidget(self.start_btn)

        main_layout.addLayout(btn_layout)

        # Información
        info = QLabel(
            "Doble clic en el VU Meter para cerrarlo\n"
            "Clic derecho para cambiar colores\n"
            "Rueda del mouse para cambiar opacidad\n"
            "Arrastra para mover"
        )
        info.setStyleSheet("color: #888; font-size: 10px;")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(info)

    def _setup_tray_icon(self):
        """Configura el icono de la bandeja del sistema."""
        self.tray_icon = QSystemTrayIcon(self)

        # Icono VU Meter personalizado
        self.app_icon = create_vu_icon()
        self.tray_icon.setIcon(self.app_icon)
        self.setWindowIcon(self.app_icon)

        # Menú del tray
        tray_menu = QMenu()

        show_action = QAction("Mostrar", self)
        show_action.triggered.connect(self.show)
        tray_menu.addAction(show_action)

        start_action = QAction("Iniciar/Detener", self)
        start_action.triggered.connect(self._toggle_vu_meter)
        tray_menu.addAction(start_action)

        tray_menu.addSeparator()

        quit_action = QAction("Salir", self)
        quit_action.triggered.connect(self._quit_app)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

        # Doble clic muestra la ventana
        self.tray_icon.activated.connect(
            lambda reason: self.show() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None
        )

    def _populate_color_combo(self):
        """Rellena el combo de esquemas de color con builtin + skins JSON."""
        builtin_labels = {
            'classic': 'Classic (Verde/Rojo)',
            'green': 'Green',
            'blue': 'Blue',
            'purple': 'Purple',
            'rainbow': 'Rainbow',
        }
        self.color_combo.clear()
        for skin_name in get_available_skins():
            label = builtin_labels.get(skin_name, skin_name.capitalize())
            self.color_combo.addItem(label, skin_name)

    def _apply_saved_config(self):
        """Aplica la configuración guardada a los controles de la UI."""
        cfg = self.config
        # Color scheme
        idx = cfg.get('color_scheme', 0)
        if 0 <= idx < self.color_combo.count():
            self.color_combo.setCurrentIndex(idx)
        # LEDs
        self.led_spin.setValue(cfg.get('num_leds', 20))
        # Size
        size_idx = cfg.get('size_mode', 0)
        if 0 <= size_idx < self.size_combo.count():
            self.size_combo.setCurrentIndex(size_idx)
        # Show spectrum
        show_spec = cfg.get('show_spectrum', True)
        self.show_spectrum_check.setChecked(show_spec)
        self.bands_widget.setVisible(show_spec)
        # Spectrum bands
        bands_idx = cfg.get('spectrum_bands', 1)
        if 0 <= bands_idx < self.bands_combo.count():
            self.bands_combo.setCurrentIndex(bands_idx)
        # Show stereoscope
        self.show_stereoscope_check.setChecked(cfg.get('show_stereoscope', False))
        # Opacity
        opacity_pct = int(cfg.get('opacity', 1.0) * 100)
        self.opacity_slider.setValue(opacity_pct)
        # Checkboxes
        self.always_on_top_check.setChecked(cfg.get('always_on_top', True))
        # Auto-start (verificar estado real del registro)
        self.auto_start_check.setChecked(is_autostart_enabled())
        # Dispositivo
        saved_device = cfg.get('device', 'Default System Audio')
        idx = self.device_combo.findText(saved_device)
        if idx >= 0:
            self.device_combo.setCurrentIndex(idx)

    def _save_current_config(self):
        """Guarda la configuración actual de los controles."""
        config = {
            'color_scheme': self.color_combo.currentIndex(),
            'num_leds': self.led_spin.value(),
            'size_mode': self.size_combo.currentIndex(),
            'spectrum_bands': self.bands_combo.currentIndex(),
            'always_on_top': self.always_on_top_check.isChecked(),
            'device': self.device_combo.currentText(),
            'show_spectrum': self.show_spectrum_check.isChecked(),
            'show_stereoscope': self.show_stereoscope_check.isChecked(),
            'window_x': self.config.get('window_x'),
            'window_y': self.config.get('window_y'),
            'opacity': self.opacity_slider.value() / 100.0,
            'auto_start': self.auto_start_check.isChecked(),
        }
        save_config(config)
        self.config = config

    def _refresh_devices(self):
        """Refresca la lista de dispositivos de audio disponibles."""
        current = self.device_combo.currentText()
        try:
            devices = AudioCapture.get_audio_devices()
        except Exception:
            return

        # Solo actualizar si cambió la lista
        current_items = [self.device_combo.itemText(i) for i in range(self.device_combo.count())]
        if current_items == devices:
            return

        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self.device_combo.addItems(devices)
        # Restaurar selección previa si sigue disponible
        idx = self.device_combo.findText(current)
        if idx >= 0:
            self.device_combo.setCurrentIndex(idx)
        self.device_combo.blockSignals(False)

    def _toggle_vu_meter(self):
        """Inicia o detiene el VU Meter."""
        if self.is_running:
            self._stop_vu_meter()
        else:
            self._start_vu_meter()

    def _start_vu_meter(self):
        """Inicia el VU Meter y conecta el hilo de captura."""
        try:
            # Guardar configuración al iniciar
            self._save_current_config()

            # Obtener configuración
            color_scheme = self.color_combo.currentData() or 'classic'
            num_leds = self.led_spin.value()
            selected_device = self.device_combo.currentText()
            size_mode = 'small' if self.size_combo.currentText() == 'Pequeño' else 'large'

            # Número de bandas de espectro
            bands_map = {0: 3, 1: 6, 2: 12}
            num_bands = bands_map.get(self.bands_combo.currentIndex(), 6)

            # Opciones de visualización
            show_spectrum = self.show_spectrum_check.isChecked()
            show_stereoscope = self.show_stereoscope_check.isChecked()
            opacity = self.opacity_slider.value() / 100.0

            # Crear VU Meter
            self.vu_meter = VUMeterWidget(
                num_leds=num_leds,
                color_scheme=color_scheme,
                size_mode=size_mode,
                num_bands=num_bands,
                show_spectrum=show_spectrum,
                show_stereoscope=show_stereoscope,
                opacity=opacity
            )

            # Siempre visible
            if self.always_on_top_check.isChecked():
                self.vu_meter.setWindowFlags(
                    self.vu_meter.windowFlags() | Qt.WindowType.WindowStaysOnTopHint
                )

            self.vu_meter.show()

            # Restaurar posición guardada
            saved_x = self.config.get('window_x')
            saved_y = self.config.get('window_y')
            if saved_x is not None and saved_y is not None:
                screen = QApplication.primaryScreen()
                if screen:
                    geom = screen.availableGeometry()
                    if geom.contains(int(saved_x), int(saved_y)):
                        self.vu_meter.move(int(saved_x), int(saved_y))

            # Conectar señales de posición y opacidad
            self.vu_meter.position_changed.connect(self._on_vu_meter_moved)
            self.vu_meter.opacity_changed.connect(self._on_opacity_changed)

            # Crear capturador de audio nativo de PyQt
            self.audio_capture = AudioCapture(
                simulation_mode=False,
                device_name=selected_device,
                num_bands=num_bands
            )

            # Conexión thread-safe mediante señales
            self.audio_capture.levels_updated.connect(self._on_audio_level)
            if show_spectrum:
                self.audio_capture.spectrum_updated.connect(self._on_spectrum_data)
            if show_stereoscope:
                self.audio_capture.raw_samples_updated.connect(self._on_raw_samples)

            # Iniciar captura (QThread.start())
            self.audio_capture.start()

            # Actualizar UI
            self.is_running = True
            self.start_btn.setText("Detener")
            self.start_btn.setStyleSheet("""
                QPushButton {
                    background-color: #f44336;
                    color: white;
                    font-weight: bold;
                    padding: 10px 20px;
                    border-radius: 5px;
                    border: none;
                }
                QPushButton:hover {
                    background-color: #d32f2f;
                }
            """)
            self.status_label.setText("Capturando audio...")
            self.status_label.setStyleSheet("""
                QLabel {
                    font-size: 14px;
                    padding: 10px;
                    background-color: #e8f5e9;
                    border-radius: 5px;
                    color: #2e7d32;
                }
            """)
            # Indicador verde pulsante
            self.capture_indicator.setStyleSheet("""
                QLabel {
                    background-color: #4CAF50;
                    border-radius: 6px;
                    border: 1px solid #388E3C;
                }
            """)

        except Exception as e:
            self.status_label.setText(f"[ Error ] {str(e)}")
            print(f"Error iniciando VU Meter: {e}")

    def _stop_vu_meter(self):
        """Detiene el VU Meter asegurando el cierre de hilos."""
        if self.audio_capture:
            self.audio_capture.stop()
            self.audio_capture = None

        if self.vu_meter:
            # Guardar posición antes de cerrar
            pos = self.vu_meter.pos()
            self.config['window_x'] = pos.x()
            self.config['window_y'] = pos.y()
            self._save_current_config()
            self.vu_meter.close()
            self.vu_meter = None

        # Actualizar UI
        self.is_running = False
        self.start_btn.setText("Iniciar")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 10px 20px;
                border-radius: 5px;
                border: none;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.status_label.setText("Detenido")
        self.status_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                padding: 10px;
                background-color: #f5f5f5;
                border-radius: 5px;
            }
        """)
        # Indicador gris (inactivo)
        self.capture_indicator.setStyleSheet("""
            QLabel {
                background-color: #aaa;
                border-radius: 6px;
                border: 1px solid #888;
            }
        """)

    def _on_audio_level(self, left: float, right: float,
                        left_peak: float, right_peak: float):
        """
        Callback llamado cuando hay nuevos niveles de audio.

        Args:
            left: Nivel izquierdo
            right: Nivel derecho
            left_peak: Peak izquierdo
            right_peak: Peak derecho
        """
        # Actualizar VU Meter
        if self.vu_meter:
            self.vu_meter.set_levels(left, right, left_peak, right_peak)

    def _on_spectrum_data(self, left_bands: list, right_bands: list):
        """Callback para datos de espectro de frecuencias."""
        if self.vu_meter:
            self.vu_meter.set_spectrum(left_bands, right_bands)

    def _on_raw_samples(self, data):
        """Pasa muestras raw al estereoscopio."""
        if self.vu_meter:
            self.vu_meter.set_raw_samples(data)

    def _on_vu_meter_moved(self, x, y):
        """Guarda posición del VU Meter al moverlo."""
        self.config['window_x'] = x
        self.config['window_y'] = y

    def _on_opacity_changed(self, opacity):
        """Sincroniza opacidad con el slider de configuración."""
        self.config['opacity'] = opacity
        self.opacity_slider.blockSignals(True)
        self.opacity_slider.setValue(int(opacity * 100))
        self.opacity_slider.blockSignals(False)
        self.opacity_value_label.setText(f"{int(opacity * 100)}%")

    def _on_spectrum_toggle(self, state):
        """Muestra/oculta el combo de bandas según el toggle de espectro."""
        self.bands_widget.setVisible(state == Qt.CheckState.Checked.value)

    def _on_autostart_toggle(self, state):
        """Activa/desactiva el inicio automático con Windows."""
        enabled = (state == Qt.CheckState.Checked.value)
        set_autostart(enabled)

    def closeEvent(self, event):
        """Maneja el cierre de la ventana."""
        # Minimizar a la bandeja en lugar de cerrar
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "VU Meter",
            "La aplicación sigue ejecutándose en la bandeja del sistema",
            QSystemTrayIcon.MessageIcon.Information,
            2000
        )

    def _quit_app(self):
        """Cierra completamente la aplicación."""
        self._save_current_config()
        self._stop_vu_meter()
        self.device_refresh_timer.stop()
        self.tray_icon.hide()
        QApplication.quit()


def main():
    """Punto de entrada principal."""
    # Parser de argumentos
    parser = argparse.ArgumentParser(
        description='VU Meter - Visualizador de audio del sistema'
    )
    parser.add_argument(
        '--simulation',
        action='store_true',
        help='Usar modo simulación (sin captura de audio real)'
    )
    parser.add_argument(
        '--hidden',
        action='store_true',
        help='Iniciar minimizado en la bandeja'
    )

    args = parser.parse_args()

    # Crear aplicación
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # Estilo de la aplicación
    app.setStyle('Fusion')

    # Crear ventana principal
    window = MainWindow(
        simulation_mode=args.simulation
    )

    # Mostrar ventana
    if not args.hidden:
        window.show()

    # Ejecutar
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
