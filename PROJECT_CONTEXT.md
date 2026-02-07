# Contexto del Proyecto: Detector de Microsueños por Parpadeos

## Objetivo del proyecto
Sistema que detecta **microsueños** (breves episodios de sueño de 1–3 segundos) en conductores mediante análisis de parpadeos en tiempo real con cámara web. Debe ser funcional, ligero y adecuado para una hackathon (prototipo en poco tiempo).

---

## Alcance simplificado (enfoque actual)
- **Solo detección de parpadeos/microsueños** (sin móvil, sin pose de cabeza)
- **Microsueño** = ojos cerrados de forma sostenida (≥2 segundos)
- **Alerta** = sonido cuando se detecte un microsueño
- Objetivo: que funcione bien en una laptop común

---

## Definiciones técnicas

### EAR (Eye Aspect Ratio)
- Fórmula que relaciona ancho y altura del ojo usando puntos faciales
- EAR alto ≈ ojo abierto, EAR bajo ≈ ojo cerrado
- Umbral típico: ~0.2 (ajustable según calibración)

### Microsueño vs parpadeo normal
- Parpadeo normal: 0.1–0.4 segundos
- Microsueño: ojos cerrados >2 segundos
- Lógica: tiempo sostenido con EAR < umbral → activar alarma

---

## Requisitos técnicos
- Lenguaje: Python (rápido de prototipar)
- Visión: OpenCV + MediaPipe (ligero, bueno en laptop)
- Entrada: cámara web en tiempo real
- Salida: alarma sonora (.wav) al detectar microsueño
- Restricción: uso moderado de CPU/GPU para no saturar el equipo

---

## Restricciones de una hackathon
- Pocas horas para desarrollar
- Demo en vivo ante jurado
- Poca o ninguna calibración previa
- Iluminación variable
- Hardware limitado

---

## Tecnologías candidatas

| Componente | Opción 1 (recomendada) | Opción 2 | Razón |
|------------|------------------------|----------|-------|
| Landmarks faciales | MediaPipe Face Mesh | Dlib | MediaPipe más ligero y rápido |
| Captura de video | OpenCV (cv2.VideoCapture) | — | Estándar, simple |
| Alarma | Pygame / playsound | winsound (Windows) | Pygame multiplataforma |
| EAR / lógica | Cálculo manual desde landmarks | — | Control total y mínimo overhead |

---

## Arquitectura sugerida

```
1. Captura frame (OpenCV)
2. Detección facial + landmarks (MediaPipe)
3. Cálculo EAR para ambos ojos (promedio)
4. Lógica de tiempo:
   - Si EAR < umbral → acumular tiempo
   - Si EAR ≥ umbral → resetear contador
   - Si tiempo acumulado > 2 s → MICROSUEÑO → reproducir alarma
5. Loop en tiempo real (≈15–30 fps)
```

---

## Parámetros ajustables
- `EAR_THRESHOLD`: ~0.2 (ajustar según usuario/iluminación)
- FPS objetivo: 15–20 (suficiente para la demo)

---

## Sistema de Alarmas Escalonado (3 niveles)

### Nivel 1 — PRECAUCIÓN (Primer llamado)
Señales tempranas de somnolencia. Alerta suave, visual amarilla.

| Criterio | Umbral |
|----------|--------|
| PERCLOS | 20% – 40% |
| Ojos cerrados sostenidos | 1.5 – 2.5 segundos |
| Bostezos acumulados | 2+ en últimos 5 minutos |
| Cabeceo | 1 – 2 segundos |

**Acción:** Sonido a volumen moderado (50%), banner amarillo con mensaje de precaución.

### Nivel 2 — ALERTA (Segundo llamado)
Somnolencia confirmada. Alarma intensa, visual naranja.

| Criterio | Umbral |
|----------|--------|
| PERCLOS | 40% – 70% |
| Ojos cerrados sostenidos | 2.5 – 4 segundos |
| Cabeceo sostenido | > 2 segundos |
| Acumulación de eventos N1 | 3+ en últimos 3 minutos |
| Combinación | PERCLOS > 25% + bostezo reciente |

**Acción:** Sonido a volumen alto (80%), banner naranja con instrucciones de acción.

### Nivel 3 — ¡DETENER VEHÍCULO! (Solicitud de detención)
Peligro inminente. Alarma máxima, visual roja parpadeante.

| Criterio | Umbral |
|----------|--------|
| PERCLOS | > 70% |
| Ojos cerrados sostenidos | > 4 segundos |
| Acumulación de eventos N2 | 2+ en últimos 5 minutos |
| Combinación simultánea | PERCLOS > 40% + cabeceo + bostezo reciente |

**Acción:** Sonido a volumen máximo con repetición, borde rojo parpadeante, banner rojo con mensaje "DETENGA EL VEHÍCULO".

### Lógica de escalamiento
- Los niveles se evalúan del más grave al menos grave (3 → 2 → 1)
- Si hay acumulación de eventos de un nivel inferior, se escala automáticamente
- El descenso de nivel es gradual (requiere ~3 segundos de normalidad)
- Cada nivel tiene su propio cooldown para evitar repetición excesiva

---

## Riesgos y mitigaciones
- Falsos positivos (bostezo largo): subir umbral de tiempo o añadir heurística de bostezo
- Poca luz: MediaPipe suele funcionar mejor que Dlib; considerar ajuste dinámico de contraste
- Sin cara visible: ignorar frames sin detección; no disparar alarma

---

## Entregables esperados
1. Script Python ejecutable
2. `requirements.txt` con versiones
3. Archivo de alarma `.wav` (opcional)
4. README con instrucciones de instalación y ejecución

---

## Preguntas para que la IA decida
- ¿MediaPipe Face Mesh completo o solo la subgrafo de ojos (más eficiente)?
- ¿EAR en ambos ojos o solo uno (si uno está tapado)?
- ¿Calibración inicial del EAR por usuario o valores fijos?
- ¿Qué biblioteca usar para reproducir la alarma según el SO?
