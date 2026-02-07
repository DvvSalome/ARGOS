"""
Sistema de Notificaciones por Telegram para Detector de Microsueños
===================================================================

Envía alertas al celular del conductor (o de un acompañante/central de
monitoreo) a través de un bot de Telegram cuando se detectan niveles de
somnolencia peligrosos.

Características:
  - Mensajes formateados con emojis según nivel de alerta
  - Rate limiting por nivel para no saturar Telegram
  - Envío asíncrono en hilo separado para no bloquear el detector
  - Reporte de resumen al finalizar la sesión
"""

import threading
import time
import os
from datetime import datetime

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    print("[Telegram] Módulo 'requests' no disponible. "
          "Instálalo con: pip install requests")


# ─── Configuración por defecto ────────────────────────────────────────────────

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/{method}"

# Cooldowns entre notificaciones por nivel (en segundos)
# Evita spam en Telegram; más urgente = más frecuente
TELEGRAM_COOLDOWN = {
    1: 60,    # Nivel 1 (Precaución): máximo 1 msg por minuto
    2: 30,    # Nivel 2 (Alerta): máximo 1 msg cada 30s
    3: 15,    # Nivel 3 (Detener): máximo 1 msg cada 15s
}

# Emojis y formato por nivel
NIVEL_EMOJI = {
    1: "⚠️",
    2: "🚨",
    3: "🛑",
}

NIVEL_TITULO = {
    1: "PRECAUCIÓN - Señales de somnolencia",
    2: "ALERTA - Somnolencia confirmada",
    3: "PELIGRO - ¡DETENGA EL VEHÍCULO!",
}


class TelegramNotifier:
    """
    Envía notificaciones de alerta por Telegram de forma no bloqueante.

    Uso:
        notifier = TelegramNotifier(token="...", chat_id="...")
        notifier.send_alert(level=2, reasons=["PERCLOS elevado: 45%"],
                            ear=0.18, perclos=0.45)
        ...
        notifier.send_session_summary(total_alerts={1: 5, 2: 2, 3: 0},
                                       yawns=3, duration_min=45.2)
    """

    def __init__(self, token, chat_id, enabled=True):
        """
        Args:
            token: Token del bot de Telegram
            chat_id: ID del chat donde enviar las notificaciones
            enabled: Si es False, no envía mensajes (útil para desactivar)
        """
        self.token = token
        self.chat_id = chat_id
        self.enabled = enabled and REQUESTS_AVAILABLE
        self._cooldown_until = {1: 0.0, 2: 0.0, 3: 0.0}
        self._lock = threading.Lock()
        self._alert_counts = {1: 0, 2: 0, 3: 0}
        self._session_start = datetime.now()

        if not REQUESTS_AVAILABLE:
            print("[Telegram] Notificaciones desactivadas (falta 'requests')")
        elif not token or not chat_id:
            self.enabled = False
            print("[Telegram] Notificaciones desactivadas (falta token o chat_id)")
        else:
            # Verificar conexión al iniciar
            threading.Thread(target=self._verify_bot, daemon=True).start()

    def _verify_bot(self):
        """Verifica que el bot sea válido y envía mensaje de inicio."""
        try:
            url = TELEGRAM_API_URL.format(token=self.token, method="getMe")
            resp = requests.get(url, timeout=10)
            data = resp.json()
            if data.get("ok"):
                bot_name = data["result"].get("username", "desconocido")
                print(f"[Telegram] Bot conectado: @{bot_name}")
                self._send_message(
                    "🟢 *Detector de Microsueños iniciado*\n\n"
                    f"📅 {self._session_start.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    "Recibirás alertas si se detecta somnolencia."
                )
            else:
                print(f"[Telegram] Error al verificar bot: {data}")
                self.enabled = False
        except Exception as e:
            print(f"[Telegram] No se pudo conectar: {e}")
            self.enabled = False

    def _send_message(self, text, parse_mode="Markdown"):
        """Envía un mensaje de texto a través de la API de Telegram."""
        if not self.enabled:
            return False
        try:
            url = TELEGRAM_API_URL.format(
                token=self.token, method="sendMessage"
            )
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
            }
            resp = requests.post(url, json=payload, timeout=10)
            data = resp.json()
            if not data.get("ok"):
                print(f"[Telegram] Error enviando mensaje: {data.get('description', 'desconocido')}")
                return False
            return True
        except Exception as e:
            print(f"[Telegram] Error de red: {e}")
            return False

    def send_alert(self, level, reasons, ear=0.0, perclos=0.0,
                   mar=0.0, pitch=0.0):
        """
        Envía una alerta de somnolencia si no está en cooldown.

        Args:
            level: Nivel de alarma (1, 2 o 3)
            reasons: Lista de razones de la alerta
            ear: Valor EAR actual
            perclos: Valor PERCLOS actual
            mar: Valor MAR actual
            pitch: Ángulo pitch de la cabeza
        """
        if not self.enabled or level < 1 or level > 3:
            return

        now = time.monotonic()

        with self._lock:
            # Verificar cooldown
            if now < self._cooldown_until.get(level, 0):
                return
            # Actualizar cooldown
            self._cooldown_until[level] = now + TELEGRAM_COOLDOWN.get(level, 60)
            self._alert_counts[level] = self._alert_counts.get(level, 0) + 1

        # Construir mensaje
        emoji = NIVEL_EMOJI.get(level, "⚠️")
        titulo = NIVEL_TITULO.get(level, "ALERTA")
        hora = datetime.now().strftime("%H:%M:%S")

        reasons_text = "\n".join(f"  • {r}" for r in reasons)

        message = (
            f"{emoji} *NIVEL {level} - {titulo}*\n"
            f"🕐 {hora}\n\n"
            f"*Razones:*\n{reasons_text}\n\n"
            f"📊 *Métricas:*\n"
            f"  • EAR: `{ear:.3f}`\n"
            f"  • PERCLOS: `{perclos*100:.1f}%`\n"
        )

        if mar > 0.3:
            message += f"  • MAR (boca): `{mar:.2f}`\n"
        if abs(pitch) > 10:
            message += f"  • Inclinación: `{pitch:.1f}°`\n"

        # Agregar recomendación según nivel
        if level == 1:
            message += "\n💡 _Manténgase alerta. Considere descansar pronto._"
        elif level == 2:
            message += "\n⚡ _¡Tome acción! Abra ventanas, tome agua, pare pronto._"
        elif level == 3:
            message += "\n🛑 _¡DETENGA EL VEHÍCULO DE FORMA SEGURA AHORA!_"

        # Enviar en hilo separado para no bloquear el detector
        threading.Thread(
            target=self._send_message,
            args=(message,),
            daemon=True
        ).start()

    def send_session_summary(self, duration_min, total_yawns=0,
                             max_perclos=0.0, max_closed_duration=0.0):
        """
        Envía un resumen al finalizar la sesión de conducción.

        Args:
            duration_min: Duración de la sesión en minutos
            total_yawns: Total de bostezos detectados
            max_perclos: PERCLOS máximo registrado
            max_closed_duration: Mayor tiempo con ojos cerrados (s)
        """
        if not self.enabled:
            return

        hora_fin = datetime.now().strftime("%H:%M:%S")
        total_alerts = sum(self._alert_counts.values())

        # Determinar evaluación general
        if self._alert_counts[3] > 0:
            eval_emoji = "🔴"
            evaluacion = "SESIÓN CON RIESGO ALTO"
        elif self._alert_counts[2] > 0:
            eval_emoji = "🟠"
            evaluacion = "Sesión con alertas moderadas"
        elif self._alert_counts[1] > 0:
            eval_emoji = "🟡"
            evaluacion = "Sesión con señales leves"
        else:
            eval_emoji = "🟢"
            evaluacion = "Sesión sin incidentes"

        message = (
            f"🏁 *Sesión de conducción finalizada*\n\n"
            f"📅 {self._session_start.strftime('%Y-%m-%d')}\n"
            f"🕐 {self._session_start.strftime('%H:%M')} → {hora_fin}\n"
            f"⏱ Duración: `{duration_min:.1f} min`\n\n"
            f"{eval_emoji} *{evaluacion}*\n\n"
            f"📊 *Resumen de alertas:*\n"
            f"  ⚠️ Nivel 1 (Precaución): `{self._alert_counts[1]}`\n"
            f"  🚨 Nivel 2 (Alerta): `{self._alert_counts[2]}`\n"
            f"  🛑 Nivel 3 (Detener): `{self._alert_counts[3]}`\n"
            f"  📢 Total alertas: `{total_alerts}`\n\n"
            f"📈 *Métricas de la sesión:*\n"
            f"  • Bostezos detectados: `{total_yawns}`\n"
            f"  • PERCLOS máximo: `{max_perclos*100:.1f}%`\n"
            f"  • Mayor cierre de ojos: `{max_closed_duration:.1f}s`\n"
        )

        if total_alerts > 5:
            message += "\n💤 _Se recomienda descansar antes de volver a conducir._"
        elif total_alerts > 0:
            message += "\n💡 _Recuerde descansar cada 2 horas de conducción._"
        else:
            message += "\n✅ _¡Buen viaje! Conduzca siempre con precaución._"

        self._send_message(message)


# ─── Utilidad: obtener chat_id ───────────────────────────────────────────────

def get_chat_id(token):
    """
    Obtiene el chat_id del último mensaje recibido por el bot.
    El usuario debe haber enviado /start o cualquier mensaje al bot primero.
    """
    if not REQUESTS_AVAILABLE:
        print("Error: instala 'requests' con: pip install requests")
        return None

    url = TELEGRAM_API_URL.format(token=token, method="getUpdates")
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get("ok") and data.get("result"):
            # Tomar el mensaje más reciente
            last_update = data["result"][-1]
            message = last_update.get("message", {})
            chat = message.get("chat", {})
            chat_id = chat.get("id")
            first_name = chat.get("first_name", "")
            username = chat.get("username", "")
            print(f"\n  Chat encontrado:")
            print(f"  Nombre: {first_name}")
            print(f"  Username: @{username}")
            print(f"  Chat ID: {chat_id}\n")
            return chat_id
        else:
            print("\nNo se encontraron mensajes. "
                  "Envía /start al bot primero y vuelve a intentar.")
            return None
    except Exception as e:
        print(f"\nError: {e}")
        return None


if __name__ == "__main__":
    print("=" * 50)
    print("  Obtener Chat ID de Telegram")
    print("=" * 50)
    print("\n  1. Abre Telegram y busca tu bot")
    print("  2. Envíale el mensaje /start")
    print("  3. Presiona Enter aquí\n")
    input("  Presiona Enter cuando hayas enviado /start... ")

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        token = input("  Ingresa el token del bot: ").strip()

    chat_id = get_chat_id(token)
    if chat_id:
        print(f"  ✓ Tu chat_id es: {chat_id}")
        print(f"\n  Agrega esto a tu archivo .env:")
        print(f"  TELEGRAM_CHAT_ID={chat_id}")
    else:
        print("  ✗ No se pudo obtener el chat_id.")
