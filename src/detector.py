"""
Detector de Microsueños Avanzado
Detecta somnolencia mediante:
  - EAR (Eye Aspect Ratio) con calibración dinámica y suavizado EMA
  - PERCLOS (porcentaje de cierre ocular en ventana deslizante)
  - Head Pose Estimation (detección de cabeceo)
  - MAR (Mouth Aspect Ratio) para detección de bostezos
  - Sistema de alarmas escalonado de 3 niveles
  - Logging de eventos para análisis posterior
"""

import cv2
import mediapipe as mp
import numpy as np
import time
import math
import os
import csv
from collections import deque
from datetime import datetime

from alarm_system import (
    AlarmSystem, NIVEL_NORMAL, NIVEL_1_PRECAUCION,
    NIVEL_2_ALERTA, NIVEL_3_DETENER, NIVEL_NOMBRES, NIVEL_COLORES_BGR,
)

# ─── Configuración por defecto ────────────────────────────────────────────────
DEFAULT_EAR_THRESHOLD = 0.2       # Umbral EAR inicial (se recalibra)
CALIBRATION_SECONDS = 10          # Segundos de calibración al inicio
EAR_CALIBRATION_FACTOR = 0.75     # Umbral = EAR_medio * este factor
EMA_ALPHA = 0.3                   # Factor de suavizado exponencial del EAR
PERCLOS_WINDOW_SECONDS = 60       # Ventana deslizante para PERCLOS
MAR_THRESHOLD = 0.6               # MAR > 0.6 = boca muy abierta (bostezo)
YAWN_CONSECUTIVE_FRAMES = 15      # Frames consecutivos para confirmar bostezo
HEAD_PITCH_THRESHOLD = 25.0       # Grados de inclinación de cabeza (cabeceo)

# ─── Rutas ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.join(SCRIPT_DIR, "..")
ALARM_PATH = os.path.join(PROJECT_DIR, "assets", "alarm.wav")
LOG_DIR = os.path.join(PROJECT_DIR, "logs")

# ─── Índices de landmarks de MediaPipe Face Mesh ─────────────────────────────
# Ojos
LEFT_EYE = [33, 160, 158, 133, 153, 144]
RIGHT_EYE = [362, 385, 387, 263, 373, 380]

# Boca (para MAR)
UPPER_LIP = 13
LOWER_LIP = 14
LEFT_MOUTH = 78
RIGHT_MOUTH = 308

# Puntos para Head Pose (nariz, mentón, ojos, comisuras)
POSE_LANDMARKS = [1, 152, 33, 263, 78, 308]

# Modelo 3D genérico de referencia para solvePnP
MODEL_POINTS_3D = np.array([
    (0.0, 0.0, 0.0),             # Punta de nariz
    (0.0, -330.0, -65.0),        # Mentón
    (-225.0, 170.0, -135.0),     # Ojo izquierdo
    (225.0, 170.0, -135.0),      # Ojo derecho
    (-150.0, -150.0, -125.0),    # Comisura izquierda boca
    (150.0, -150.0, -125.0),     # Comisura derecha boca
], dtype=np.float64)


# ─── Funciones auxiliares ─────────────────────────────────────────────────────

def landmark_dist(landmarks, p1, p2):
    """Distancia euclidiana 2D entre dos landmarks."""
    return math.hypot(
        landmarks[p1].x - landmarks[p2].x,
        landmarks[p1].y - landmarks[p2].y,
    )


def eye_aspect_ratio(landmarks, eye_indices):
    """Calcula EAR para un ojo: (v1 + v2) / (2 * h)."""
    vertical1 = landmark_dist(landmarks, eye_indices[1], eye_indices[5])
    vertical2 = landmark_dist(landmarks, eye_indices[2], eye_indices[4])
    horizontal = landmark_dist(landmarks, eye_indices[0], eye_indices[3])
    if horizontal == 0:
        return 1.0
    return (vertical1 + vertical2) / (2.0 * horizontal)


def mouth_aspect_ratio(landmarks):
    """Calcula MAR: distancia vertical / distancia horizontal de la boca."""
    vertical = landmark_dist(landmarks, UPPER_LIP, LOWER_LIP)
    horizontal = landmark_dist(landmarks, LEFT_MOUTH, RIGHT_MOUTH)
    if horizontal == 0:
        return 0.0
    return vertical / horizontal


def estimate_head_pose(landmarks, frame_shape):
    """
    Estima la rotación de la cabeza (pitch, yaw, roll) usando solvePnP.
    Retorna (pitch, yaw, roll) en grados, o None si falla.
    """
    h, w = frame_shape[:2]

    # Extraer puntos 2D de los landmarks seleccionados
    image_points = np.array([
        (landmarks[idx].x * w, landmarks[idx].y * h)
        for idx in POSE_LANDMARKS
    ], dtype=np.float64)

    # Matriz de cámara aproximada
    focal_length = w
    center = (w / 2, h / 2)
    camera_matrix = np.array([
        [focal_length, 0, center[0]],
        [0, focal_length, center[1]],
        [0, 0, 1],
    ], dtype=np.float64)
    dist_coeffs = np.zeros((4, 1))

    success, rotation_vec, translation_vec = cv2.solvePnP(
        MODEL_POINTS_3D, image_points, camera_matrix, dist_coeffs,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )

    if not success:
        return None

    # Convertir vector de rotación a matriz y extraer ángulos de Euler
    rotation_mat, _ = cv2.Rodrigues(rotation_vec)
    pose_mat = cv2.hconcat((rotation_mat, translation_vec))
    _, _, _, _, _, _, euler_angles = cv2.decomposeProjectionMatrix(
        cv2.hconcat((pose_mat, np.array([[0, 0, 0, 1]], dtype=np.float64).T))
    )

    # decomposeProjectionMatrix no siempre funciona limpio;
    # alternativa robusta con atan2
    sy = math.sqrt(rotation_mat[0, 0] ** 2 + rotation_mat[1, 0] ** 2)
    if sy > 1e-6:
        pitch = math.degrees(math.atan2(rotation_mat[2, 1], rotation_mat[2, 2]))
        yaw = math.degrees(math.atan2(-rotation_mat[2, 0], sy))
        roll = math.degrees(math.atan2(rotation_mat[1, 0], rotation_mat[0, 0]))
    else:
        pitch = math.degrees(math.atan2(-rotation_mat[1, 2], rotation_mat[1, 1]))
        yaw = math.degrees(math.atan2(-rotation_mat[2, 0], sy))
        roll = 0.0

    return pitch, yaw, roll


class EventLogger:
    """Registra eventos de somnolencia en un archivo CSV."""

    def __init__(self, log_dir):
        os.makedirs(log_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.filepath = os.path.join(log_dir, f"session_{timestamp}.csv")
        self.file = open(self.filepath, "w", newline="", encoding="utf-8")
        self.writer = csv.writer(self.file)
        self.writer.writerow([
            "timestamp", "event_type", "ear", "mar", "perclos",
            "pitch", "yaw", "duration_s", "detail"
        ])
        self.file.flush()
        print(f"Log de sesión: {self.filepath}")

    def log(self, event_type, ear=0.0, mar=0.0, perclos=0.0,
            pitch=0.0, yaw=0.0, duration=0.0, detail=""):
        self.writer.writerow([
            datetime.now().isoformat(), event_type,
            f"{ear:.3f}", f"{mar:.3f}", f"{perclos:.3f}",
            f"{pitch:.1f}", f"{yaw:.1f}", f"{duration:.2f}", detail
        ])
        self.file.flush()

    def close(self):
        self.file.close()


def init_alarm():
    """Inicializa Pygame mixer para reproducir alarmas."""
    try:
        import pygame
        pygame.mixer.init()
        return pygame
    except Exception as e:
        print(f"Pygame no disponible: {e}. Se usará beep del sistema.")
        return None


def play_alarm(pygame_ref):
    """Reproduce la alarma sonora."""
    if pygame_ref and os.path.exists(ALARM_PATH):
        try:
            pygame_ref.mixer.music.load(ALARM_PATH)
            pygame_ref.mixer.music.play()
            return
        except Exception:
            pass
    # Fallback: beep del sistema
    print("\a", end="", flush=True)


# ─── Función principal ────────────────────────────────────────────────────────

def run_detector():
    mp_face_mesh = mp.solutions.face_mesh
    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("No se pudo abrir la cámara.")
        return

    # Inicializar subsistemas
    pygame_ref = init_alarm()
    logger = EventLogger(LOG_DIR)

    # Sistema de alarmas escalonado
    alarm_system = AlarmSystem(
        pygame_ref=pygame_ref,
        alarm_paths={},  # Se pueden agregar archivos .wav por nivel
        logger=logger,
    )

    # ─── Estado del detector ──────────────────────────────────────────────
    # Calibración
    calibrating = True
    calibration_ears = []
    ear_threshold = DEFAULT_EAR_THRESHOLD

    # EMA (suavizado exponencial)
    smoothed_ear = None

    # Microsueño directo (ojos cerrados sostenidos)
    closed_start = None

    # PERCLOS (ventana deslizante)
    # Se almacenan booleanos: True = ojo cerrado en ese frame
    # Estimamos ~20 FPS; ajustaremos dinámicamente
    fps_estimate = 20
    perclos_buffer = deque(maxlen=fps_estimate * PERCLOS_WINDOW_SECONDS)
    last_fps_time = time.monotonic()
    frame_count_for_fps = 0

    # Bostezos
    yawn_frame_counter = 0
    yawn_total_count = 0

    # Head pose
    head_nod_start = None
    head_nod_duration = 0.0

    # Tiempo de inicio
    start_time = time.monotonic()

    with mp_face_mesh.FaceMesh(
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    ) as face_mesh:

        print("=" * 60)
        print("  DETECTOR DE MICROSUEÑOS — SISTEMA DE ALARMAS")
        print("=" * 60)
        print("  Niveles de alarma:")
        print("    N1: PRECAUCIÓN    — Primeras señales de somnolencia")
        print("    N2: ALERTA        — Somnolencia confirmada, actúe")
        print("    N3: ¡DETENER!     — Peligro, detenga el vehículo")
        print("-" * 60)
        print(f"  Calibrando EAR durante {CALIBRATION_SECONDS}s...")
        print(f"  Mire a la cámara con los ojos abiertos normalmente.")
        print(f"  Presione 'q' para salir.")
        print("=" * 60)

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            now = time.monotonic()
            frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = face_mesh.process(rgb)

            # ── Calcular FPS real cada segundo ────────────────────────
            frame_count_for_fps += 1
            if now - last_fps_time >= 1.0:
                fps_estimate = max(frame_count_for_fps, 1)
                frame_count_for_fps = 0
                last_fps_time = now
                # Ajustar tamaño del buffer PERCLOS al FPS real
                new_maxlen = fps_estimate * PERCLOS_WINDOW_SECONDS
                if new_maxlen != perclos_buffer.maxlen:
                    old_data = list(perclos_buffer)
                    perclos_buffer = deque(old_data, maxlen=new_maxlen)

            # ── Barra superior de estado ──────────────────────────────
            status_bar_y = 25
            alert_reasons = []

            if results.multi_face_landmarks:
                lm = results.multi_face_landmarks[0].landmark

                # ════════════════════════════════════════════════════════
                # 1. EAR (Eye Aspect Ratio)
                # ════════════════════════════════════════════════════════
                ear_left = eye_aspect_ratio(lm, LEFT_EYE)
                ear_right = eye_aspect_ratio(lm, RIGHT_EYE)
                ear_raw = (ear_left + ear_right) / 2.0

                # Suavizado EMA
                if smoothed_ear is None:
                    smoothed_ear = ear_raw
                else:
                    smoothed_ear = EMA_ALPHA * ear_raw + (1 - EMA_ALPHA) * smoothed_ear
                ear = smoothed_ear

                # ════════════════════════════════════════════════════════
                # 2. Calibración dinámica
                # ════════════════════════════════════════════════════════
                elapsed_since_start = now - start_time
                if calibrating:
                    calibration_ears.append(ear_raw)
                    progress = min(elapsed_since_start / CALIBRATION_SECONDS, 1.0)
                    bar_width = int(200 * progress)
                    cv2.rectangle(frame, (10, 50), (210, 70), (100, 100, 100), -1)
                    cv2.rectangle(frame, (10, 50), (10 + bar_width, 70), (0, 255, 0), -1)
                    cv2.putText(frame, f"Calibrando... {progress*100:.0f}%",
                                (10, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

                    if elapsed_since_start >= CALIBRATION_SECONDS:
                        if len(calibration_ears) > 10:
                            mean_ear = np.mean(calibration_ears)
                            ear_threshold = mean_ear * EAR_CALIBRATION_FACTOR
                            print(f"\n  Calibración completa:")
                            print(f"  EAR promedio ojos abiertos: {mean_ear:.3f}")
                            print(f"  Umbral EAR calibrado: {ear_threshold:.3f}")
                            logger.log("calibration", ear=mean_ear,
                                       detail=f"threshold={ear_threshold:.3f}")
                        else:
                            print(f"\n  Pocos datos de calibración. Usando umbral por defecto: {DEFAULT_EAR_THRESHOLD}")
                            ear_threshold = DEFAULT_EAR_THRESHOLD
                        calibrating = False
                        print(f"  Detección activa.\n")

                # ════════════════════════════════════════════════════════
                # 3. PERCLOS (solo post-calibración)
                # ════════════════════════════════════════════════════════
                eyes_closed = ear < ear_threshold
                if not calibrating:
                    perclos_buffer.append(eyes_closed)

                perclos = 0.0
                if len(perclos_buffer) > fps_estimate * 5:  # Al menos 5s de datos
                    perclos = sum(perclos_buffer) / len(perclos_buffer)

                # ════════════════════════════════════════════════════════
                # 4. Microsueño (ojos cerrados sostenidos)
                # ════════════════════════════════════════════════════════
                eyes_closed_duration = 0.0
                if not calibrating:
                    if eyes_closed:
                        if closed_start is None:
                            closed_start = now
                        eyes_closed_duration = now - closed_start
                    else:
                        if closed_start is not None:
                            duration = now - closed_start
                            if duration >= 1.5:
                                logger.log("microsleep_end", ear=ear,
                                           perclos=perclos, duration=duration)
                        closed_start = None

                # ════════════════════════════════════════════════════════
                # 5. MAR (detección de bostezos)
                # ════════════════════════════════════════════════════════
                mar = mouth_aspect_ratio(lm)
                if mar > MAR_THRESHOLD:
                    yawn_frame_counter += 1
                    if yawn_frame_counter == YAWN_CONSECUTIVE_FRAMES:
                        yawn_total_count += 1
                        alarm_system.register_yawn(now)
                        logger.log("yawn", ear=ear, mar=mar, perclos=perclos,
                                   detail=f"total_yawns={yawn_total_count}")
                        print(f"  Bostezo detectado (total: {yawn_total_count})")
                else:
                    yawn_frame_counter = 0

                # ════════════════════════════════════════════════════════
                # 6. Head Pose (cabeceo)
                # ════════════════════════════════════════════════════════
                pose = estimate_head_pose(lm, frame.shape)
                pitch, yaw = 0.0, 0.0
                is_head_nodding = False
                if pose is not None:
                    pitch, yaw, roll = pose

                    if abs(pitch) > HEAD_PITCH_THRESHOLD:
                        is_head_nodding = True
                        if head_nod_start is None:
                            head_nod_start = now
                        head_nod_duration = now - head_nod_start
                    else:
                        if head_nod_start is not None:
                            duration = now - head_nod_start
                            if duration >= 1.0:
                                logger.log("head_nod", ear=ear, perclos=perclos,
                                           pitch=pitch, yaw=yaw, duration=duration)
                        head_nod_start = None
                        head_nod_duration = 0.0

                # ════════════════════════════════════════════════════════
                # 7. SISTEMA DE ALARMAS ESCALONADO (3 niveles)
                # ════════════════════════════════════════════════════════
                alarm_result = {"level": NIVEL_NORMAL, "name": "NORMAL",
                                "color": (0, 255, 0), "reasons": [],
                                "messages": [], "should_sound": False,
                                "is_new_alarm": False}

                if not calibrating:
                    alarm_result = alarm_system.evaluate(
                        now=now,
                        perclos=perclos,
                        eyes_closed_duration=eyes_closed_duration,
                        head_nod_duration=head_nod_duration,
                        is_eyes_closed=eyes_closed,
                        is_head_nodding=is_head_nodding,
                        ear=ear, mar=mar, pitch=pitch, yaw=yaw,
                    )

                    # Reproducir alarma si corresponde
                    if alarm_result["should_sound"]:
                        level = alarm_result["level"]
                        reason_str = " | ".join(alarm_result["reasons"])
                        level_name = alarm_result["name"]
                        print(f"  [{level_name}] {reason_str}")
                        alarm_system.play_alarm(level, alarm_base_path=ALARM_PATH)

                # ════════════════════════════════════════════════════════
                # HUD (Head-Up Display)
                # ════════════════════════════════════════════════════════
                alarm_level = alarm_result["level"]
                alarm_color = alarm_result["color"]

                # ── Indicador de nivel actual (esquina superior derecha) ──
                level_indicator_w = 180
                level_indicator_h = 35
                lx = w - level_indicator_w - 10
                ly = 5
                overlay = frame.copy()
                cv2.rectangle(overlay, (lx, ly),
                              (lx + level_indicator_w, ly + level_indicator_h),
                              alarm_color, -1)
                cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)
                cv2.putText(frame, f"N{alarm_level}: {alarm_result['name'][:15]}",
                            (lx + 5, ly + 24), cv2.FONT_HERSHEY_SIMPLEX,
                            0.55, (255, 255, 255), 2)

                # ── Métricas (lado izquierdo) ──
                # Color del EAR según estado
                ear_color = (0, 255, 0) if not eyes_closed else (0, 0, 255)
                cv2.putText(frame, f"EAR: {ear:.2f} (umbral: {ear_threshold:.2f})",
                            (10, status_bar_y), cv2.FONT_HERSHEY_SIMPLEX,
                            0.55, ear_color, 2)

                # PERCLOS con colores del sistema de alarma
                perclos_pct = perclos * 100
                if perclos >= 0.70:
                    pc_color = (0, 0, 255)      # Rojo
                elif perclos >= 0.40:
                    pc_color = (0, 130, 255)     # Naranja
                elif perclos >= 0.20:
                    pc_color = (0, 255, 255)     # Amarillo
                else:
                    pc_color = (0, 255, 0)       # Verde
                cv2.putText(frame, f"PERCLOS: {perclos_pct:.1f}%",
                            (10, status_bar_y + 25), cv2.FONT_HERSHEY_SIMPLEX,
                            0.55, pc_color, 2)

                # MAR
                mar_color = (0, 0, 255) if mar > MAR_THRESHOLD else (200, 200, 200)
                cv2.putText(frame, f"MAR: {mar:.2f}",
                            (10, status_bar_y + 50), cv2.FONT_HERSHEY_SIMPLEX,
                            0.55, mar_color, 2)

                # Head pose
                if pose is not None:
                    pose_color = (0, 0, 255) if abs(pitch) > HEAD_PITCH_THRESHOLD else (200, 200, 200)
                    cv2.putText(frame, f"Pitch: {pitch:.1f} Yaw: {yaw:.1f}",
                                (10, status_bar_y + 75), cv2.FONT_HERSHEY_SIMPLEX,
                                0.55, pose_color, 2)

                # Bostezos totales
                cv2.putText(frame, f"Bostezos: {yawn_total_count}",
                            (10, status_bar_y + 100), cv2.FONT_HERSHEY_SIMPLEX,
                            0.55, (200, 200, 200), 2)

                # Ojos cerrados duración
                if eyes_closed_duration > 0.5:
                    cv2.putText(frame, f"Ojos cerrados: {eyes_closed_duration:.1f}s",
                                (10, status_bar_y + 125), cv2.FONT_HERSHEY_SIMPLEX,
                                0.55, (0, 0, 255), 2)

                # FPS
                cv2.putText(frame, f"FPS: {fps_estimate}",
                            (w - 100, status_bar_y + 45), cv2.FONT_HERSHEY_SIMPLEX,
                            0.5, (200, 200, 200), 1)

                # ── Banner de ALERTA según nivel ──────────────────────
                if alarm_level >= NIVEL_1_PRECAUCION and not calibrating:
                    # Altura del banner según gravedad
                    if alarm_level == NIVEL_3_DETENER:
                        banner_h = 100
                    elif alarm_level == NIVEL_2_ALERTA:
                        banner_h = 75
                    else:
                        banner_h = 55

                    overlay = frame.copy()
                    cv2.rectangle(overlay, (0, h - banner_h), (w, h),
                                  alarm_color, -1)

                    # Opacidad más fuerte para niveles altos
                    alpha = 0.5 + (alarm_level * 0.1)
                    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)

                    # Mensajes del nivel
                    messages = alarm_result.get("messages", [])
                    if messages:
                        # Mensaje principal (grande)
                        cv2.putText(frame, messages[0],
                                    (10, h - banner_h + 28),
                                    cv2.FONT_HERSHEY_SIMPLEX,
                                    0.75 if alarm_level >= NIVEL_2_ALERTA else 0.6,
                                    (255, 255, 255), 2)
                        # Mensaje secundario (si cabe)
                        if len(messages) > 1 and banner_h >= 70:
                            cv2.putText(frame, messages[1],
                                        (10, h - banner_h + 55),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                                        (255, 255, 255), 1)
                        if len(messages) > 2 and banner_h >= 95:
                            cv2.putText(frame, messages[2],
                                        (10, h - banner_h + 80),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                                        (255, 255, 255), 1)

                    # Razones técnicas (pequeño, esquina)
                    reason_str = " | ".join(alarm_result["reasons"][:2])
                    cv2.putText(frame, reason_str,
                                (10, h - 5), cv2.FONT_HERSHEY_SIMPLEX,
                                0.35, (200, 200, 200), 1)

                    # NIVEL 3: Borde rojo parpadeante
                    if alarm_level == NIVEL_3_DETENER:
                        # Borde rojo grueso alrededor de toda la pantalla
                        border_thickness = 8
                        # Parpadeo cada ~0.5s
                        if int(now * 2) % 2 == 0:
                            cv2.rectangle(frame,
                                          (0, 0), (w - 1, h - 1),
                                          (0, 0, 255), border_thickness)
                            cv2.rectangle(frame,
                                          (border_thickness, border_thickness),
                                          (w - border_thickness - 1,
                                           h - border_thickness - 1),
                                          (0, 0, 200), border_thickness // 2)

            else:
                # Sin cara detectada
                closed_start = None
                head_nod_start = None
                head_nod_duration = 0.0
                cv2.putText(frame, "Cara no detectada", (10, status_bar_y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)

            cv2.imshow("Detector de Microsuenos Avanzado", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    # ── Limpieza ──────────────────────────────────────────────────────────
    logger.close()
    cap.release()
    cv2.destroyAllWindows()
    print("\nSesión finalizada. Log guardado en:", logger.filepath)


if __name__ == "__main__":
    run_detector()
