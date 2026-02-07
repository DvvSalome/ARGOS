# Detector de Microsueños - Instrucciones

## Instalación rápida

### 1. Instalar dependencias esenciales
```bash
pip3 install opencv-python==4.8.1.78 mediapipe==0.10.9 numpy==1.24.3
```

### 2. (Opcional) Instalar alarma sonora
```bash
pip3 install pygame
```

## Ejecución

### Detector simple (sin alarma)
```bash
python3 src/detector_simple.py
```

### Detector con alarma
```bash
python3 src/detector_con_alarma.py
```

## Alarma personalizada (opcional)

Para usar tu propia alarma, coloca un archivo `alarm.wav` en la carpeta `assets/`:

```bash
# Ejemplo: descargar un sonido de alarma
# curl -o assets/alarm.wav https://url-de-tu-alarma.wav
```

Si no existe `alarm.wav`, el sistema usa el beep del sistema (sonido "\a").

## Ajustar parámetros

Edita las constantes al inicio del archivo `.py`:

```python
EAR_THRESHOLD = 0.21          # Umbral para detectar ojos cerrados
MICROSLEEP_SECONDS = 2.0      # Tiempo mínimo para activar alarma
```

## Teclas

- **q**: Salir del detector
