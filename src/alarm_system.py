"""
Sistema de Alarmas Escalonado para Detector de Microsueños
==========================================================

3 niveles de alarma con criterios bien definidos:

NIVEL 1 — PRECAUCIÓN (Primer llamado)
    Señales tempranas de somnolencia. Alerta suave para que el conductor
    se percate de que está empezando a dar señales de cansancio.
    Criterios:
      • PERCLOS entre 20% y 40%
      • Microsueño breve: ojos cerrados 1.5 – 2.5 s
      • 2+ bostezos acumulados en los últimos 5 minutos
      • Cabeceo breve: 1 – 2 s

NIVEL 2 — ALERTA (Segundo llamado)
    Somnolencia moderada confirmada. Alarma más intensa y frecuente
    indicando que el conductor debe tomar acción inmediata (abrir ventanas,
    tomar agua, hacer una parada pronto).
    Criterios:
      • PERCLOS entre 40% y 70%
      • Microsueño moderado: ojos cerrados 2.5 – 4 s
      • Cabeceo sostenido > 2 s
      • 3+ eventos de Nivel 1 en los últimos 3 minutos
      • Combinación: PERCLOS > 25% + bostezo reciente

NIVEL 3 — DETENER VEHÍCULO (Solicitud de detención)
    Peligro inminente. El conductor muestra signos graves de incapacidad.
    Alarma máxima, continua e imposible de ignorar, con mensaje claro
    de que debe detenerse de inmediato.
    Criterios:
      • PERCLOS > 70%
      • Microsueño prolongado: ojos cerrados > 4 s
      • 2+ eventos de Nivel 2 en los últimos 5 minutos
      • Combinación simultánea: PERCLOS > 40% + cabeceo + bostezo reciente
"""

import time
from collections import deque
from datetime import datetime


# ─── Niveles de Alarma ────────────────────────────────────────────────────────
NIVEL_NORMAL = 0
NIVEL_1_PRECAUCION = 1
NIVEL_2_ALERTA = 2
NIVEL_3_DETENER = 3

NIVEL_NOMBRES = {
    NIVEL_NORMAL: "NORMAL",
    NIVEL_1_PRECAUCION: "PRECAUCIÓN",
    NIVEL_2_ALERTA: "ALERTA",
    NIVEL_3_DETENER: "¡DETENGA EL VEHÍCULO!",
}

NIVEL_COLORES_BGR = {
    NIVEL_NORMAL: (0, 255, 0),       # Verde
    NIVEL_1_PRECAUCION: (0, 255, 255),  # Amarillo
    NIVEL_2_ALERTA: (0, 130, 255),    # Naranja
    NIVEL_3_DETENER: (0, 0, 255),     # Rojo
}

NIVEL_MENSAJES = {
    NIVEL_1_PRECAUCION: [
        "Señales de somnolencia detectadas",
        "Manténgase alerta",
        "Considere tomar un descanso pronto",
    ],
    NIVEL_2_ALERTA: [
        "¡ALERTA! Somnolencia confirmada",
        "Tome acción: abra ventanas, tome agua",
        "Planifique una parada de descanso YA",
    ],
    NIVEL_3_DETENER: [
        "¡¡¡PELIGRO INMINENTE!!!",
        "DETENGA EL VEHÍCULO DE FORMA SEGURA",
        "SU VIDA ESTÁ EN RIESGO",
    ],
}

# ─── Umbrales por nivel ──────────────────────────────────────────────────────

# PERCLOS (porcentaje de cierre ocular)
PERCLOS_NIVEL_1 = 0.20   # 20%
PERCLOS_NIVEL_2 = 0.40   # 40%
PERCLOS_NIVEL_3 = 0.70   # 70%

# Microsueño (ojos cerrados sostenidos, en segundos)
MICROSLEEP_NIVEL_1 = 1.5  # 1.5 s
MICROSLEEP_NIVEL_2 = 2.5  # 2.5 s
MICROSLEEP_NIVEL_3 = 4.0  # 4.0 s

# Cabeceo (head nod sostenido, en segundos)
HEAD_NOD_NIVEL_1 = 1.0  # 1 s
HEAD_NOD_NIVEL_2 = 2.0  # 2 s

# Bostezos en ventana de tiempo
YAWN_COUNT_NIVEL_1 = 2   # 2 bostezos en ventana
YAWN_WINDOW_SECONDS = 300  # Ventana de 5 minutos

# Escalamiento por acumulación de eventos
LEVEL1_EVENTS_FOR_LEVEL2 = 3      # 3 eventos N1 → escalar a N2
LEVEL1_EVENTS_WINDOW = 180        # en 3 minutos
LEVEL2_EVENTS_FOR_LEVEL3 = 2      # 2 eventos N2 → escalar a N3
LEVEL2_EVENTS_WINDOW = 300        # en 5 minutos

# Combinación para Nivel 3: PERCLOS + cabeceo + bostezo reciente
COMBO_PERCLOS_THRESHOLD = 0.40
COMBO_YAWN_RECENCY = 60  # Bostezo en último minuto

# Cooldowns entre alarmas por nivel (en segundos)
COOLDOWN_POR_NIVEL = {
    NIVEL_1_PRECAUCION: 8,    # No repetir Nivel 1 antes de 8s
    NIVEL_2_ALERTA: 5,        # No repetir Nivel 2 antes de 5s
    NIVEL_3_DETENER: 3,       # Nivel 3 se repite cada 3s (urgente)
}


class AlarmEvent:
    """Representa un evento de alarma registrado."""
    def __init__(self, timestamp, level, reasons):
        self.timestamp = timestamp
        self.level = level
        self.reasons = reasons

    def __repr__(self):
        return f"AlarmEvent(t={self.timestamp:.1f}, L{self.level}, {self.reasons})"


class AlarmSystem:
    """
    Sistema de alarmas escalonado de 3 niveles.

    Evalúa el estado actual del conductor (métricas de somnolencia)
    y determina el nivel de alarma apropiado, gestionando escalamiento,
    cooldowns y registro de eventos.
    """

    def __init__(self, pygame_ref=None, alarm_paths=None, logger=None,
                 telegram_notifier=None):
        """
        Args:
            pygame_ref: Referencia a pygame (o None para beep del sistema)
            alarm_paths: dict con rutas a archivos de alarma por nivel, e.g.
                         {1: "alert_soft.wav", 2: "alert_medium.wav", 3: "alert_critical.wav"}
                         Si es None o falta un nivel, usa un archivo único o beep.
            logger: Instancia de EventLogger para registrar eventos
            telegram_notifier: Instancia de TelegramNotifier (o None)
        """
        self.pygame_ref = pygame_ref
        self.alarm_paths = alarm_paths or {}
        self.logger = logger
        self.telegram_notifier = telegram_notifier

        # Estado actual
        self.current_level = NIVEL_NORMAL
        self.level_start_time = None  # Cuándo empezó el nivel actual

        # Historial de eventos para escalamiento
        self.event_history = deque(maxlen=200)
        self.yawn_timestamps = deque(maxlen=50)

        # Cooldowns
        self.cooldown_until = {
            NIVEL_1_PRECAUCION: 0.0,
            NIVEL_2_ALERTA: 0.0,
            NIVEL_3_DETENER: 0.0,
        }

        # Para seguimiento de estado entre frames
        self._last_alarm_level = NIVEL_NORMAL
        self._consecutive_normal_frames = 0
        self.NORMAL_FRAMES_TO_RESET = 60  # ~3s a 20fps para bajar nivel

    def register_yawn(self, timestamp):
        """Registra un bostezo detectado."""
        self.yawn_timestamps.append(timestamp)

    def _count_recent_yawns(self, now):
        """Cuenta bostezos dentro de la ventana de tiempo."""
        cutoff = now - YAWN_WINDOW_SECONDS
        return sum(1 for t in self.yawn_timestamps if t > cutoff)

    def _count_recent_events(self, now, level, window_seconds):
        """Cuenta eventos de un nivel específico dentro de una ventana."""
        cutoff = now - window_seconds
        return sum(1 for e in self.event_history
                   if e.level == level and e.timestamp > cutoff)

    def _has_recent_yawn(self, now, recency_seconds=COMBO_YAWN_RECENCY):
        """Verifica si hubo un bostezo reciente."""
        if not self.yawn_timestamps:
            return False
        return (now - self.yawn_timestamps[-1]) < recency_seconds

    def evaluate(self, now, perclos, eyes_closed_duration, head_nod_duration,
                 is_eyes_closed, is_head_nodding, ear=0.0, mar=0.0,
                 pitch=0.0, yaw=0.0):
        """
        Evalúa todas las métricas y determina el nivel de alarma.

        Args:
            now: Timestamp actual (time.monotonic())
            perclos: Valor PERCLOS actual (0.0 - 1.0)
            eyes_closed_duration: Tiempo con ojos cerrados actuales (s)
            head_nod_duration: Tiempo con cabeza inclinada actual (s)
            is_eyes_closed: Bool, si los ojos están cerrados ahora
            is_head_nodding: Bool, si la cabeza está inclinada ahora
            ear: EAR actual (para logging)
            mar: MAR actual (para logging)
            pitch: Pitch actual (para logging)
            yaw: Yaw actual (para logging)

        Returns:
            dict con:
                level: int (0-3)
                name: str del nivel
                color: tuple BGR
                reasons: list[str] de razones
                messages: list[str] mensajes para el conductor
                should_sound: bool si debe sonar alarma
                is_new_alarm: bool si es una alarma nueva (no repetición)
        """
        reasons = []
        determined_level = NIVEL_NORMAL

        # ──────────────────────────────────────────────────────────────
        # EVALUAR CRITERIOS DE NIVEL 3 (más grave primero)
        # ──────────────────────────────────────────────────────────────

        # Microsueño prolongado > 4s
        if eyes_closed_duration >= MICROSLEEP_NIVEL_3:
            reasons.append(f"Microsueño crítico: {eyes_closed_duration:.1f}s")
            determined_level = max(determined_level, NIVEL_3_DETENER)

        # PERCLOS > 70%
        if perclos >= PERCLOS_NIVEL_3:
            reasons.append(f"PERCLOS crítico: {perclos*100:.0f}%")
            determined_level = max(determined_level, NIVEL_3_DETENER)

        # Acumulación: 2+ eventos Nivel 2 en 5 min
        n2_events = self._count_recent_events(
            now, NIVEL_2_ALERTA, LEVEL2_EVENTS_WINDOW)
        if n2_events >= LEVEL2_EVENTS_FOR_LEVEL3:
            reasons.append(f"{n2_events} alertas de Nivel 2 en {LEVEL2_EVENTS_WINDOW//60} min")
            determined_level = max(determined_level, NIVEL_3_DETENER)

        # Combinación peligrosa: PERCLOS alto + cabeceo + bostezo reciente
        if (perclos >= COMBO_PERCLOS_THRESHOLD
                and is_head_nodding and head_nod_duration >= HEAD_NOD_NIVEL_1
                and self._has_recent_yawn(now)):
            reasons.append("Combinación: PERCLOS + cabeceo + bostezo")
            determined_level = max(determined_level, NIVEL_3_DETENER)

        # ──────────────────────────────────────────────────────────────
        # EVALUAR CRITERIOS DE NIVEL 2 (solo si no ya es N3)
        # ──────────────────────────────────────────────────────────────

        if determined_level < NIVEL_3_DETENER:
            # Microsueño moderado 2.5-4s
            if eyes_closed_duration >= MICROSLEEP_NIVEL_2:
                reasons.append(f"Microsueño moderado: {eyes_closed_duration:.1f}s")
                determined_level = max(determined_level, NIVEL_2_ALERTA)

            # PERCLOS 40-70%
            if PERCLOS_NIVEL_2 <= perclos < PERCLOS_NIVEL_3:
                reasons.append(f"PERCLOS elevado: {perclos*100:.0f}%")
                determined_level = max(determined_level, NIVEL_2_ALERTA)

            # Cabeceo sostenido > 2s
            if is_head_nodding and head_nod_duration >= HEAD_NOD_NIVEL_2:
                reasons.append(f"Cabeceo sostenido: {head_nod_duration:.1f}s")
                determined_level = max(determined_level, NIVEL_2_ALERTA)

            # Acumulación: 3+ eventos Nivel 1 en 3 min
            n1_events = self._count_recent_events(
                now, NIVEL_1_PRECAUCION, LEVEL1_EVENTS_WINDOW)
            if n1_events >= LEVEL1_EVENTS_FOR_LEVEL2:
                reasons.append(f"{n1_events} avisos de precaución en {LEVEL1_EVENTS_WINDOW//60} min")
                determined_level = max(determined_level, NIVEL_2_ALERTA)

            # Combinación: PERCLOS > 25% + bostezo reciente
            if perclos > 0.25 and self._has_recent_yawn(now):
                reasons.append("PERCLOS moderado + bostezo reciente")
                determined_level = max(determined_level, NIVEL_2_ALERTA)

        # ──────────────────────────────────────────────────────────────
        # EVALUAR CRITERIOS DE NIVEL 1 (solo si no ya es N2+)
        # ──────────────────────────────────────────────────────────────

        if determined_level < NIVEL_2_ALERTA:
            # Microsueño breve 1.5-2.5s
            if eyes_closed_duration >= MICROSLEEP_NIVEL_1:
                reasons.append(f"Ojos cerrados: {eyes_closed_duration:.1f}s")
                determined_level = max(determined_level, NIVEL_1_PRECAUCION)

            # PERCLOS 20-40%
            if PERCLOS_NIVEL_1 <= perclos < PERCLOS_NIVEL_2:
                reasons.append(f"PERCLOS moderado: {perclos*100:.0f}%")
                determined_level = max(determined_level, NIVEL_1_PRECAUCION)

            # Cabeceo breve 1-2s
            if is_head_nodding and head_nod_duration >= HEAD_NOD_NIVEL_1:
                reasons.append(f"Cabeceo: {head_nod_duration:.1f}s")
                determined_level = max(determined_level, NIVEL_1_PRECAUCION)

            # 2+ bostezos en 5 minutos
            recent_yawns = self._count_recent_yawns(now)
            if recent_yawns >= YAWN_COUNT_NIVEL_1:
                reasons.append(f"{recent_yawns} bostezos en {YAWN_WINDOW_SECONDS//60} min")
                determined_level = max(determined_level, NIVEL_1_PRECAUCION)

        # ──────────────────────────────────────────────────────────────
        # GESTIÓN DE TRANSICIONES Y COOLDOWNS
        # ──────────────────────────────────────────────────────────────

        # Si volvemos a normal, contar frames consecutivos antes de bajar
        if determined_level == NIVEL_NORMAL:
            self._consecutive_normal_frames += 1
            # No bajar de inmediato si estábamos en alerta alta
            if (self.current_level >= NIVEL_2_ALERTA
                    and self._consecutive_normal_frames < self.NORMAL_FRAMES_TO_RESET * 2):
                determined_level = max(NIVEL_1_PRECAUCION, self.current_level - 1)
                reasons.append("Descendiendo nivel gradualmente")
            elif (self.current_level == NIVEL_1_PRECAUCION
                    and self._consecutive_normal_frames < self.NORMAL_FRAMES_TO_RESET):
                determined_level = NIVEL_1_PRECAUCION
                reasons.append("Precaución aún activa")
        else:
            self._consecutive_normal_frames = 0

        # Determinar si debe sonar la alarma
        should_sound = False
        is_new_alarm = False

        if determined_level > NIVEL_NORMAL:
            # Verificar cooldown
            if now > self.cooldown_until.get(determined_level, 0):
                should_sound = True
                self.cooldown_until[determined_level] = (
                    now + COOLDOWN_POR_NIVEL.get(determined_level, 5)
                )

            # ¿Es una alarma nueva o una escalación?
            if determined_level > self._last_alarm_level:
                is_new_alarm = True
                should_sound = True  # Siempre sonar en escalación

            # Registrar evento si es nueva alarma o escalación
            if is_new_alarm or (should_sound and determined_level >= NIVEL_2_ALERTA):
                event = AlarmEvent(now, determined_level, list(reasons))
                self.event_history.append(event)

                # Log
                if self.logger:
                    self.logger.log(
                        f"alarm_level_{determined_level}",
                        ear=ear, mar=mar, perclos=perclos,
                        pitch=pitch, yaw=yaw,
                        detail=f"L{determined_level}: {' | '.join(reasons)}"
                    )

        # Actualizar estado
        if determined_level != self.current_level:
            self.level_start_time = now
        self.current_level = determined_level
        self._last_alarm_level = determined_level if determined_level > NIVEL_NORMAL else self._last_alarm_level

        # ──────────────────────────────────────────────────────────────
        # CONSTRUIR RESPUESTA
        # ──────────────────────────────────────────────────────────────

        return {
            "level": determined_level,
            "name": NIVEL_NOMBRES[determined_level],
            "color": NIVEL_COLORES_BGR[determined_level],
            "reasons": reasons,
            "messages": NIVEL_MENSAJES.get(determined_level, []),
            "should_sound": should_sound,
            "is_new_alarm": is_new_alarm,
        }

    def play_alarm(self, level, alarm_base_path=None):
        """
        Reproduce la alarma correspondiente al nivel.
        Para Nivel 3, intenta reproducir en loop o más fuerte.
        """
        import os

        # Intentar archivos específicos por nivel
        alarm_file = self.alarm_paths.get(level)

        # Si no hay archivo específico, usar el base
        if not alarm_file and alarm_base_path:
            alarm_file = alarm_base_path

        if self.pygame_ref and alarm_file and os.path.exists(alarm_file):
            try:
                self.pygame_ref.mixer.music.load(alarm_file)

                if level == NIVEL_3_DETENER:
                    # Nivel 3: volumen máximo, loop hasta que mejore
                    self.pygame_ref.mixer.music.set_volume(1.0)
                    self.pygame_ref.mixer.music.play(loops=2)
                elif level == NIVEL_2_ALERTA:
                    # Nivel 2: volumen alto
                    self.pygame_ref.mixer.music.set_volume(0.8)
                    self.pygame_ref.mixer.music.play()
                else:
                    # Nivel 1: volumen moderado
                    self.pygame_ref.mixer.music.set_volume(0.5)
                    self.pygame_ref.mixer.music.play()
                return
            except Exception:
                pass

        # Fallback: beep del sistema (más beeps para más urgencia)
        beeps = {NIVEL_1_PRECAUCION: 1, NIVEL_2_ALERTA: 2, NIVEL_3_DETENER: 3}
        for _ in range(beeps.get(level, 1)):
            print("\a", end="", flush=True)

    def stop_alarm(self):
        """Detiene la alarma sonora si está reproduciéndose."""
        if self.pygame_ref:
            try:
                self.pygame_ref.mixer.music.stop()
            except Exception:
                pass

    def get_status_summary(self, now):
        """
        Retorna un resumen del estado actual para mostrar en consola.
        """
        n1 = self._count_recent_events(now, NIVEL_1_PRECAUCION, LEVEL1_EVENTS_WINDOW)
        n2 = self._count_recent_events(now, NIVEL_2_ALERTA, LEVEL2_EVENTS_WINDOW)
        yawns = self._count_recent_yawns(now)

        duration = ""
        if self.level_start_time and self.current_level > NIVEL_NORMAL:
            duration = f" (hace {now - self.level_start_time:.0f}s)"

        return (
            f"Nivel: {NIVEL_NOMBRES[self.current_level]}{duration} | "
            f"Eventos N1: {n1}/{LEVEL1_EVENTS_FOR_LEVEL2} | "
            f"Eventos N2: {n2}/{LEVEL2_EVENTS_FOR_LEVEL3} | "
            f"Bostezos: {yawns}"
        )
