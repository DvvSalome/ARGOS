"""
Detector de Microsueños - Con alarma sonora
Detecta ojos cerrados sostenidos (≥2 s) mediante EAR
"""

import cv2
import mediapipe as mp
import time
import math
import os

# ─── Configuración ────────────────────────────────────────────────────────────
EAR_THRESHOLD = 0.21
MICROSLEEP_SECONDS = 2.0

# ─── Rutas ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ALARM_PATH = os.path.join(SCRIPT_DIR, "..", "assets", "alarm.wav")

# ─── Índices de landmarks (MediaPipe Face Mesh) ──────────────────────────────
LEFT_EYE = [33, 160, 158, 133, 153, 144]
RIGHT_EYE = [362, 385, 387, 263, 373, 380]


def eye_aspect_ratio(landmarks, eye_indices):
    """Calcula EAR para un ojo: (v1 + v2) / (2 * h)"""
    def dist(p1, p2):
        return math.hypot(
            landmarks[p1].x - landmarks[p2].x,
            landmarks[p1].y - landmarks[p2].y,
        )

    vertical1 = dist(eye_indices[1], eye_indices[5])
    vertical2 = dist(eye_indices[2], eye_indices[4])
    horizontal = dist(eye_indices[0], eye_indices[3])

    if horizontal == 0:
        return 1.0
    return (vertical1 + vertical2) / (2.0 * horizontal)


def init_alarm():
    """Inicializa Pygame para reproducir alarmas"""
    try:
        import pygame
        pygame.mixer.init()
        return pygame
    except Exception as e:
        print(f"⚠️  Pygame no disponible: {e}")
        print("   Se usará beep del sistema como alternativa")
        return None


def play_alarm(pygame_ref):
    """Reproduce la alarma sonora"""
    if pygame_ref and os.path.exists(ALARM_PATH):
        try:
            pygame_ref.mixer.music.load(ALARM_PATH)
            pygame_ref.mixer.music.play()
            return
        except Exception as e:
            print(f"⚠️  Error reproduciendo {ALARM_PATH}: {e}")
    
    # Fallback: beep del sistema
    print("\a", end="", flush=True)


def run_detector():
    """Función principal del detector"""
    mp_face_mesh = mp.solutions.face_mesh
    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("❌ No se pudo abrir la cámara")
        return

    # Inicializar alarma
    pygame_ref = init_alarm()

    closed_start = None
    alert_cooldown_until = 0.0

    with mp_face_mesh.FaceMesh(
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    ) as face_mesh:

        print("=" * 60)
        print("  DETECTOR DE MICROSUEÑOS - CON ALARMA")
        print("=" * 60)
        print(f"  Umbral EAR: {EAR_THRESHOLD}")
        print(f"  Tiempo mínimo ojos cerrados: {MICROSLEEP_SECONDS}s")
        if pygame_ref and os.path.exists(ALARM_PATH):
            print(f"  Alarma: {ALARM_PATH}")
        elif pygame_ref:
            print(f"  Alarma: Beep del sistema (no se encontró alarm.wav)")
        else:
            print(f"  Alarma: Beep del sistema (pygame no disponible)")
        print(f"  Presiona 'q' para salir")
        print("=" * 60)

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            now = time.time()
            frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = face_mesh.process(rgb)

            if results.multi_face_landmarks:
                lm = results.multi_face_landmarks[0].landmark

                # ═══ Calcular EAR ════════════════════════════════════════
                ear_left = eye_aspect_ratio(lm, LEFT_EYE)
                ear_right = eye_aspect_ratio(lm, RIGHT_EYE)
                ear = (ear_left + ear_right) / 2.0

                # ═══ Detectar ojos cerrados ══════════════════════════════
                eyes_closed = ear < EAR_THRESHOLD

                if eyes_closed:
                    if closed_start is None:
                        closed_start = now
                    elapsed = now - closed_start

                    # ═══ MICROSUEÑO DETECTADO ════════════════════════════
                    if elapsed >= MICROSLEEP_SECONDS:
                        if now > alert_cooldown_until:
                            print(f"🚨 ¡MICROSUEÑO DETECTADO! ({elapsed:.1f}s)")
                            play_alarm(pygame_ref)
                            alert_cooldown_until = now + 5  # Cooldown 5s

                        # Mostrar alerta en pantalla
                        overlay = frame.copy()
                        cv2.rectangle(overlay, (0, h - 80), (w, h), (0, 0, 200), -1)
                        cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)
                        cv2.putText(
                            frame, f"MICROSUEÑO: {elapsed:.1f}s",
                            (10, h - 30), cv2.FONT_HERSHEY_SIMPLEX,
                            1.0, (255, 255, 255), 3
                        )

                    # Contador de tiempo con ojos cerrados
                    cv2.putText(
                        frame, f"Ojos cerrados: {elapsed:.1f}s",
                        (10, 60), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (0, 0, 255), 2
                    )
                else:
                    closed_start = None

                # ═══ HUD (métricas) ═══════════════════════════════════════
                ear_color = (0, 255, 0) if not eyes_closed else (0, 0, 255)
                cv2.putText(
                    frame, f"EAR: {ear:.3f}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, ear_color, 2
                )

                # Línea de umbral
                cv2.putText(
                    frame, f"Umbral: {EAR_THRESHOLD}",
                    (w - 180, 30), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (200, 200, 200), 1
                )

            else:
                # Sin cara detectada
                closed_start = None
                cv2.putText(
                    frame, "Cara no detectada",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (0, 165, 255), 2
                )

            # Mostrar frame
            cv2.imshow("Detector de Microsueños", frame)

            # Salir con 'q'
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    cap.release()
    cv2.destroyAllWindows()
    print("\n✅ Sesión finalizada")


if __name__ == "__main__":
    run_detector()
