# Detector de Microsueños Avanzado

Sistema de detección de somnolencia en conductores mediante análisis multisensor en tiempo real con cámara web.

## Funcionalidades

| Módulo | Descripción |
|---|---|
| **EAR** (Eye Aspect Ratio) | Detecta ojos cerrados sostenidos ≥2s = microsueño |
| **Calibración dinámica** | Los primeros 10s mide tu EAR natural y ajusta el umbral automáticamente |
| **Suavizado EMA** | Filtra ruido frame-a-frame con media exponencial |
| **PERCLOS** | Porcentaje de cierre ocular en ventana de 60s (estándar de seguridad vial) |
| **MAR** (Mouth Aspect Ratio) | Detecta bostezos frecuentes como indicador temprano de fatiga |
| **Head Pose** | Detecta cabeceo (cabeza cayendo) mediante estimación de pose 3D |
| **Alarma sonora** | Reproduce alarma `.wav` o beep del sistema al detectar somnolencia |
| **Logging CSV** | Registra todos los eventos en `logs/` para análisis posterior |

## Tecnologías

- Python 3.8+
- OpenCV (captura de video, renderizado, solvePnP)
- MediaPipe Face Mesh (468 landmarks faciales)
- NumPy (cálculos de calibración y pose)
- Pygame (reproducción de alarma)

## Instalación

```bash
pip install -r requirements.txt
```

## Ejecución

```bash
python src/detector.py
```

### Al iniciar:
1. **Calibración (10 segundos)**: Mira a la cámara con los ojos abiertos normalmente. El sistema medirá tu EAR base y ajustará el umbral automáticamente.
2. **Detección activa**: Después de la calibración, el sistema monitorea en tiempo real.
3. **Presiona `q`** para salir.

## HUD en pantalla

El detector muestra en tiempo real:
- **EAR**: valor actual y umbral calibrado
- **PERCLOS**: porcentaje de cierre ocular (verde < 40%, naranja 40-80%, rojo > 80%)
- **MAR**: apertura de boca (rojo si detecta bostezo)
- **Pitch/Yaw**: inclinación de la cabeza
- **Bostezos**: contador acumulado
- **FPS**: frames por segundo reales
- **Banner rojo**: aparece cuando se dispara una alerta

## Parámetros ajustables

Todos los parámetros se definen al inicio de `src/detector.py`:

| Parámetro | Default | Descripción |
|---|---|---|
| `CALIBRATION_SECONDS` | 10 | Duración de la calibración inicial |
| `EAR_CALIBRATION_FACTOR` | 0.75 | Umbral = EAR_medio × factor |
| `EMA_ALPHA` | 0.3 | Factor de suavizado exponencial |
| `MICROSLEEP_SECONDS` | 2.0 | Tiempo mínimo de ojos cerrados para microsueño |
| `PERCLOS_WINDOW_SECONDS` | 60 | Ventana deslizante para PERCLOS |
| `PERCLOS_ALERT_THRESHOLD` | 0.40 | PERCLOS > 40% = alerta |
| `PERCLOS_SEVERE_THRESHOLD` | 0.80 | PERCLOS > 80% = alerta severa |
| `MAR_THRESHOLD` | 0.6 | MAR > 0.6 = bostezo |
| `YAWN_CONSECUTIVE_FRAMES` | 15 | Frames consecutivos para confirmar bostezo |
| `HEAD_PITCH_THRESHOLD` | 25.0 | Grados de pitch para detectar cabeceo |
| `ALARM_COOLDOWN_SECONDS` | 5 | Tiempo mínimo entre alarmas |

## Alarma personalizada

Coloca un archivo `alarm.wav` en `assets/` para usar un sonido personalizado. Si no existe, el sistema usa un beep del terminal.

## Logs

Cada sesión genera un archivo CSV en `logs/` con columnas:
- `timestamp`, `event_type`, `ear`, `mar`, `perclos`, `pitch`, `yaw`, `duration_s`, `detail`

Tipos de evento: `calibration`, `microsleep_end`, `yawn`, `head_nod`, `alarm`

## Estructura del proyecto

```
proyecto/
├── PROJECT_CONTEXT.md   # Contexto para IA / decisiones técnicas
├── README.md
├── requirements.txt
├── src/
│   └── detector.py      # Código principal
├── assets/
│   └── alarm.wav        # Sonido de alarma (opcional)
└── logs/
    └── session_*.csv    # Logs de sesiones (generados automáticamente)
```
