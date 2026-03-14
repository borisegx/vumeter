# VU Meter para Windows

Un medidor de volumen (VU Meter) flotante para Windows que captura **todo el audio del sistema** y lo visualiza en tiempo real con estilo LED. Incluye analizador de espectro por frecuencias y estereoscopio Lissajous.

## Caracteristicas

- **Captura WASAPI Loopback** - Intercepta el audio de salida del sistema sin necesidad de microfono, usando `pyaudiowpatch` con WASAPI nativo.
- **Seleccion de dispositivo** - Escoge que tarjeta de sonido o salida de audio interceptar (speakers, auriculares, interfaces de audio).
- **Estilo LED profesional** - Animaciones a 60 FPS con interpolacion suave, fisica resistiva balistica y efecto glow.
- **Marcador Absolute Peak** - El pico maximo historico se ilumina en color cian brillante, siempre visible.
- **Analizador de espectro** - Visualizacion de frecuencias por canal (L/R) con barras horizontales LED por banda. Se puede activar/desactivar.
- **Bandas configurables** - Elige entre 3 bandas (Low/Mid/High), 6 bandas o 12 bandas con distribucion por tercios de octava.
- **Estereoscopio Lissajous** - Display X-Y que muestra la correlacion estereo con colores por intensidad (azul=bajo, verde=medio, rojo=alto). Se puede activar/desactivar.
- **Tamaños dinamicos** - Alterna entre tamaño Grande o Pequeño.
- **Ventana flotante** - Siempre visible, arrastrable a cualquier posicion, con memoria de posicion.
- **Opacidad ajustable** - Rueda del mouse para cambiar la transparencia de la ventana (30%-100%).
- **Esquemas de colores** - Classic, Green, Blue, Purple, Rainbow y skins JSON personalizados.
- **Auto-inicio con Windows** - Opcion para iniciar automaticamente con el sistema operativo.
- **Configuracion persistente** - Todas las opciones se guardan y restauran automaticamente.

## Requisitos

- **Windows 10/11**
- **Python 3.10+**

## Instalacion

### 1. Clonar el repositorio

```bash
git clone https://github.com/borisegx/vumeter.git
cd vumeter
```

### 2. Crear entorno virtual (recomendado)

```bash
python -m venv venv
venv\Scripts\activate
```

### 3. Instalar dependencias

```bash
pip install -r requirements.txt
```

Las dependencias principales son:

| Paquete | Uso |
|---------|-----|
| `PyQt6` | Interfaz grafica y manejo de hilos |
| `numpy` | Calculos numericos, RMS y FFT |
| `PyAudioWPatch` | Captura de audio WASAPI Loopback nativa |

## Uso

### Inicio silencioso sin consola (recomendado)

Doble clic en:
```
Start VUMeter.bat
```

O de forma manual:
```bash
pythonw start_vumeter.pyw
```

### Inicio desde terminal (debug)

```bash
python app.py
```

### Modo simulacion (sin hardware de audio)

```bash
python app.py --simulation
```

## Controles

| Accion | Resultado |
|--------|-----------|
| **Arrastrar** | Mueve la ventana flotante |
| **Doble clic** | Cierra el VU Meter |
| **Clic derecho** | Menu de opciones (color, reset peaks, cerrar) |
| **Rueda del mouse** | Ajusta la opacidad de la ventana |
| **Icono en bandeja** | Clic derecho para menu del sistema |

## Panel de configuracion

El panel de configuracion permite ajustar todas las opciones antes de iniciar el VU Meter:

| Opcion | Descripcion |
|--------|-------------|
| **Dispositivo de audio** | Selecciona la salida de audio a capturar |
| **Esquema de colores** | Cambia el tema visual de los LEDs |
| **Numero de LEDs** | 12, 20 o 30 LEDs por canal (tamaño adaptativo) |
| **Tamaño** | Grande o Pequeño |
| **Mostrar espectro** | Activa/desactiva el analizador de frecuencias |
| **Bandas de espectro** | 3, 6 o 12 bandas (solo si el espectro esta activo) |
| **Mostrar estereoscopio** | Activa/desactiva el display Lissajous X-Y |
| **Opacidad** | Transparencia de la ventana (30%-100%) |
| **Siempre visible** | Mantiene la ventana por encima de otras |
| **Iniciar con Windows** | Registra la app en el inicio automatico del sistema |

## Analizador de espectro

El analizador de espectro descompone la senal de audio en bandas de frecuencia usando FFT (Fast Fourier Transform) con ventana Hann y normalizacion Parseval. Cada canal (L/R) tiene sus propias barras de frecuencia.

### Modos disponibles

| Modo | Bandas | Descripcion |
|------|--------|-------------|
| **3 bandas** | Low / Mid / High | Vista simplificada: graves, medios, agudos |
| **6 bandas** | 20, 100, 350, 1k, 5k, 10k Hz | Vista estandar por rangos clasicos |
| **12 bandas** | 20, 60, 150, 300, 500, 1k, 2k, 4k, 6k, 8k, 12k, 16k Hz | Vista detallada por tercios de octava |

## Estereoscopio Lissajous

El estereoscopio muestra un diagrama X-Y (Lissajous) donde:
- **Eje X** = canal izquierdo
- **Eje Y** = canal derecho
- **Diagonal ascendente** = senal mono (L=R)
- **Elipse/spread** = senal estereo
- **Diagonal descendente** = senal en anti-fase

Los puntos se colorean segun la intensidad de la senal:
- **Azul** = amplitud baja
- **Verde** = amplitud media
- **Amarillo/Rojo** = amplitud alta

## Esquemas de colores

| Esquema | Descripcion |
|---------|-------------|
| **Classic** | Verde, Amarillo, Rojo (estudio profesional) |
| **Green** | Degradado de verdes |
| **Blue** | Degradado de azules |
| **Purple** | Degradado de purpuras |
| **Rainbow** | Arcoiris completo |

Tambien soporta **skins JSON personalizados** colocados en el directorio `skins/`.

## Estructura del proyecto

```
vumeter/
├── app.py                 # Ventana de configuracion (motor principal)
├── audio_capture.py       # Captura de audio WASAPI + analisis FFT
├── vu_meter_widget.py     # Widget visual LED, espectro, estereoscopio y animaciones
├── start_vumeter.pyw      # Punto de entrada sin consola
├── start.bat              # Inicio con consola (debug)
├── Start VUMeter.bat      # Inicio silencioso
├── install.bat            # Script de instalacion automatica
├── requirements.txt       # Dependencias Python
└── skins/                 # Skins JSON personalizados
    ├── fire.json
    ├── neon.json
    ├── ocean.json
    └── mint.json
```

## Opciones de linea de comandos

```
python app.py [-h] [--simulation] [--hidden]

Opciones:
  --simulation          Usar modo simulacion (sin captura de audio real)
  --hidden              Iniciar minimizado en la bandeja
```

## Solucion de problemas

### "No se captura audio"

1. Asegurate de haber seleccionado el dispositivo correcto en el menu principal.
2. Verifica que `PyAudioWPatch` se haya instalado correctamente.
3. El motor usa WASAPI Loopback nativo. Si no encuentra un dispositivo loopback, activara automaticamente el modo simulacion.

### "La ventana no aparece"

- Revisa la bandeja del sistema (junto al reloj).
- Ejecuta sin `--hidden`.

## Licencia

MIT License - Libre para usar y modificar.

## Creditos

- **PyQt6** - Framework de interfaz grafica
- **PyAudioWPatch** - Captura de audio WASAPI Loopback nativa
- **NumPy** - Calculos numericos, RMS y FFT
