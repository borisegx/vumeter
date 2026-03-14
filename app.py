"""
VU Meter Application - Aplicación principal
Captura audio del sistema y lo visualiza en un VU Meter flotante
Exporta datos para Rainmeter
"""

import sys
import os
import json
import argparse
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
from rainmeter_export import RainmeterExporter, RainmeterSkinGenerator

# Archivo de configuración persistente
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vumeter_config.json')

# Configuración por defecto
DEFAULT_CONFIG = {
    'color_scheme': 0,
    'num_leds': 20,
    'size_mode': 0,
    'spectrum_bands': 1,  # Índice: 0=3 bandas, 1=6 bandas, 2=12 bandas
    'always_on_top': True,
    'rainmeter_export': True,
    'device': 'Default System Audio',
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

    def __init__(self, enable_rainmeter: bool = True,
                 rainmeter_path: str = None,
                 simulation_mode: bool = False):
        """
        Inicializa la ventana principal.

        Args:
            enable_rainmeter: Habilitar exportación para Rainmeter
            rainmeter_path: Ruta personalizada para archivos de Rainmeter
            simulation_mode: Forzar modo simulación (sin captura real)
        """
        super().__init__()

        self.enable_rainmeter = enable_rainmeter
        self.rainmeter_path = rainmeter_path
        self.simulation_mode = simulation_mode

        # Cargar configuración persistente
        self.config = load_config()

        # Configurar ventana
        self.setWindowTitle("VU Meter - Configuracion")
        self.setMinimumSize(350, 450)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowMaximizeButtonHint)

        # Variables
        self.vu_meter = None
        self.audio_capture = None
        self.rainmeter_exporter = None
        self.is_running = False

        # Configurar UI
        self._setup_ui()
        self._setup_tray_icon()

        # Aplicar configuración guardada
        self._apply_saved_config()

        # Inicializar componentes
        self._init_components()

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

        # Bandas de espectro
        bands_layout = QHBoxLayout()
        bands_label = QLabel("Bandas de espectro:")
        self.bands_combo = QComboBox()
        self.bands_combo.addItems(['3 bandas (Low/Mid/High)', '6 bandas', '12 bandas'])
        self.bands_combo.setCurrentIndex(1)
        bands_layout.addWidget(bands_label)
        bands_layout.addWidget(self.bands_combo)
        main_layout.addLayout(bands_layout)

        # Checkboxes
        self.rainmeter_check = QCheckBox("Exportar para Rainmeter")
        self.rainmeter_check.setChecked(self.enable_rainmeter)
        main_layout.addWidget(self.rainmeter_check)

        self.always_on_top_check = QCheckBox("Siempre visible")
        self.always_on_top_check.setChecked(True)
        main_layout.addWidget(self.always_on_top_check)

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

        self.settings_btn = QPushButton("Configurar Rainmeter")
        self.settings_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                font-weight: bold;
                padding: 10px 20px;
                border-radius: 5px;
                border: none;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        self.settings_btn.clicked.connect(self._show_rainmeter_settings)
        btn_layout.addWidget(self.settings_btn)

        main_layout.addLayout(btn_layout)

        # Información
        info = QLabel(
            "Doble clic en el VU Meter para cerrarlo\n"
            "Clic derecho para cambiar colores\n"
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
        # Spectrum bands
        bands_idx = cfg.get('spectrum_bands', 1)
        if 0 <= bands_idx < self.bands_combo.count():
            self.bands_combo.setCurrentIndex(bands_idx)
        # Checkboxes
        self.always_on_top_check.setChecked(cfg.get('always_on_top', True))
        self.rainmeter_check.setChecked(cfg.get('rainmeter_export', True))
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
            'rainmeter_export': self.rainmeter_check.isChecked(),
            'device': self.device_combo.currentText(),
        }
        save_config(config)

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

    def _init_components(self):
        """Inicializa los componentes de audio y exportación."""
        if self.enable_rainmeter:
            export_path = self.rainmeter_path or os.path.dirname(os.path.abspath(__file__))
            self.rainmeter_exporter = RainmeterExporter(export_path)

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

            # Crear VU Meter
            self.vu_meter = VUMeterWidget(
                num_leds=num_leds,
                color_scheme=color_scheme,
                size_mode=size_mode,
                num_bands=num_bands
            )

            # Siempre visible
            if self.always_on_top_check.isChecked():
                self.vu_meter.setWindowFlags(
                    self.vu_meter.windowFlags() | Qt.WindowType.WindowStaysOnTopHint
                )

            self.vu_meter.show()

            # Crear capturador de audio nativo de PyQt
            self.audio_capture = AudioCapture(
                simulation_mode=False,
                device_name=selected_device,
                num_bands=num_bands
            )

            # Conexión thread-safe mediante señales
            self.audio_capture.levels_updated.connect(self._on_audio_level)
            self.audio_capture.spectrum_updated.connect(self._on_spectrum_data)

            # Iniciar captura (QThread.start())
            self.audio_capture.start()

            # Iniciar exportación Rainmeter
            if self.rainmeter_check.isChecked() and self.rainmeter_exporter:
                self.rainmeter_exporter.start_continuous_export()

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
            # Llama al método stop() que ahora gestiona el wait() del QThread
            self.audio_capture.stop()
            self.audio_capture = None

        if self.vu_meter:
            self.vu_meter.close()
            self.vu_meter = None

        if self.rainmeter_exporter:
            self.rainmeter_exporter.stop_continuous_export()

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

        # Actualizar exportador Rainmeter
        if self.rainmeter_exporter and self.rainmeter_check.isChecked():
            self.rainmeter_exporter.update_levels(left, right, left_peak, right_peak)

    def _on_spectrum_data(self, left_bands: list, right_bands: list):
        """Callback para datos de espectro de frecuencias."""
        if self.vu_meter:
            self.vu_meter.set_spectrum(left_bands, right_bands)

    def _show_rainmeter_settings(self):
        """Muestra el diálogo de configuración de Rainmeter."""
        from PyQt6.QtWidgets import QDialog, QTextEdit, QDialogButtonBox

        dialog = QDialog(self)
        dialog.setWindowTitle("Configurar Rainmeter")
        dialog.setMinimumSize(500, 400)

        layout = QVBoxLayout(dialog)

        # Instrucciones
        instructions = QLabel(
            "Instrucciones para usar con Rainmeter:\n\n"
            "1. Haz clic en 'Generar Skin' para crear los archivos del skin\n"
            "2. Copia la carpeta generada a: Documents/Rainmeter/Skins/\n"
            "3. En Rainmeter, haz clic derecho -> Refresh all\n"
            "4. Carga el skin 'PythonVUMeter'\n"
            "5. Inicia el VU Meter desde esta aplicación"
        )
        instructions.setStyleSheet("padding: 10px; background-color: #f5f5f5; border-radius: 5px;")
        layout.addWidget(instructions)

        # Botón generar
        def generate_skin():
            skin_path = RainmeterSkinGenerator.generate_led_skin(
                os.path.dirname(os.path.abspath(__file__))
            )
            result_label.setText(f"Skin generado en:\n{skin_path}")

        gen_btn = QPushButton("Generar Skin Rainmeter")
        gen_btn.clicked.connect(generate_skin)
        layout.addWidget(gen_btn)

        # Resultado
        result_label = QLabel()
        result_label.setStyleSheet("padding: 10px; background-color: #e8f5e9; border-radius: 5px;")
        layout.addWidget(result_label)

        # Botones del diálogo
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        dialog.exec()

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
        '--no-rainmeter',
        action='store_true',
        help='Deshabilitar exportación para Rainmeter'
    )
    parser.add_argument(
        '--rainmeter-path',
        type=str,
        help='Ruta para guardar archivos de Rainmeter'
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
        enable_rainmeter=not args.no_rainmeter,
        rainmeter_path=args.rainmeter_path,
        simulation_mode=args.simulation
    )

    # Mostrar ventana
    if not args.hidden:
        window.show()

    # Ejecutar
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
