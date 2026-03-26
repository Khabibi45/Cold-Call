"""
Service ADB — Controle du telephone Android via USB pour passer des appels gratuits.
Utilise le forfait mobile de l'utilisateur (appels illimites).

Prerequis :
- ADB installe sur la machine (android-platform-tools)
- Telephone branche en USB avec debogage USB active
- Permission ADB acceptee sur le telephone
"""

import asyncio
import shutil
import re

from app.core.logging import get_logger

logger = get_logger("adb_service")


class ADBService:
    """Controle un telephone Android via ADB pour passer des appels."""

    def __init__(self):
        self._adb_path = shutil.which("adb")
        self._current_call_number: str | None = None
        self._call_active = False

    # --- Proprietes ---

    @property
    def is_adb_installed(self) -> bool:
        """Verifie si ADB est installe sur la machine."""
        return self._adb_path is not None

    async def is_device_connected(self) -> bool:
        """Verifie si un telephone Android est connecte en USB."""
        if not self.is_adb_installed:
            return False
        try:
            result = await self._run_adb("devices")
            # Parse la sortie : "List of devices attached\nXXXXX\tdevice\n"
            lines = [l.strip() for l in result.strip().split("\n") if l.strip()]
            # Filtrer la ligne "List of devices attached" et les lignes vides
            devices = [l for l in lines if "\tdevice" in l]
            return len(devices) > 0
        except Exception as e:
            logger.error("adb_device_check_error", error=str(e))
            return False

    async def get_device_info(self) -> dict:
        """Recupere les infos du telephone connecte."""
        if not await self.is_device_connected():
            return {"connected": False}
        try:
            model = (await self._run_adb("shell", "getprop", "ro.product.model")).strip()
            brand = (await self._run_adb("shell", "getprop", "ro.product.brand")).strip()
            battery_raw = await self._run_adb("shell", "dumpsys", "battery")
            # Extraire le niveau de batterie
            battery_match = re.search(r"level:\s*(\d+)", battery_raw)
            battery = int(battery_match.group(1)) if battery_match else -1
            return {
                "connected": True,
                "model": model,
                "brand": brand,
                "battery": battery,
            }
        except Exception as e:
            logger.error("adb_device_info_error", error=str(e))
            return {"connected": False, "error": str(e)}

    # --- Appels ---

    async def make_call(self, phone_number: str) -> bool:
        """
        Lance un appel vers le numero donne via le telephone Android.
        Utilise le forfait mobile de l'utilisateur.
        """
        if not await self.is_device_connected():
            logger.error("adb_make_call_no_device")
            return False

        # Nettoyer le numero (garder uniquement chiffres et +)
        clean_number = re.sub(r"[^\d+]", "", phone_number)
        if not clean_number:
            logger.error("adb_make_call_invalid_number", number=phone_number)
            return False

        try:
            # Deverrouiller l'ecran si necessaire
            await self._run_adb("shell", "input", "keyevent", "KEYCODE_WAKEUP")
            await asyncio.sleep(0.3)

            # Lancer l'appel via intent Android
            await self._run_adb(
                "shell", "am", "start",
                "-a", "android.intent.action.CALL",
                "-d", f"tel:{clean_number}"
            )

            self._current_call_number = clean_number
            self._call_active = True
            logger.info("adb_call_started", number=clean_number)

            # Activer le haut-parleur apres un delai (le temps que l'appel demarre)
            await asyncio.sleep(2)
            await self._enable_speaker()

            return True
        except Exception as e:
            logger.error("adb_make_call_error", number=clean_number, error=str(e))
            return False

    async def hangup(self) -> bool:
        """Raccroche l'appel en cours."""
        try:
            await self._run_adb("shell", "input", "keyevent", "KEYCODE_ENDCALL")
            self._call_active = False
            self._current_call_number = None
            logger.info("adb_call_ended")
            return True
        except Exception as e:
            logger.error("adb_hangup_error", error=str(e))
            return False

    async def is_call_active(self) -> bool:
        """Detecte si un appel est en cours sur le telephone."""
        try:
            # Verifier l'etat du telephone via dumpsys
            result = await self._run_adb("shell", "dumpsys", "telephony.registry")
            # Chercher mCallState=1 (ringing) ou mCallState=2 (offhook/en appel)
            if "mCallState=2" in result or "mCallState=1" in result:
                return True
            # Alternative : chercher dans l'etat audio
            audio = await self._run_adb("shell", "dumpsys", "audio")
            if "MODE_IN_CALL" in audio or "MODE_IN_COMMUNICATION" in audio:
                return True
            return False
        except Exception:
            return self._call_active

    async def get_call_state(self) -> str:
        """Retourne l'etat de l'appel : idle, ringing, in_call."""
        try:
            result = await self._run_adb("shell", "dumpsys", "telephony.registry")
            if "mCallState=2" in result:
                return "in_call"
            elif "mCallState=1" in result:
                return "ringing"
            return "idle"
        except Exception:
            return "unknown"

    # --- Utilitaires ---

    async def _enable_speaker(self):
        """Active le haut-parleur pendant l'appel."""
        try:
            # Simuler l'appui sur le bouton haut-parleur via input tap
            # Methode alternative : utiliser media commands
            await self._run_adb("shell", "input", "keyevent", "KEYCODE_VOLUME_UP")
        except Exception:
            pass  # Non critique

    async def _run_adb(self, *args: str) -> str:
        """Execute une commande ADB et retourne la sortie."""
        cmd = [self._adb_path or "adb"] + list(args)
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)

        if process.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace").strip()
            if error_msg:
                raise RuntimeError(f"ADB error: {error_msg}")

        return stdout.decode("utf-8", errors="replace")

    @property
    def status(self) -> dict:
        """Statut actuel du service ADB."""
        return {
            "adb_installed": self.is_adb_installed,
            "call_active": self._call_active,
            "current_number": self._current_call_number,
        }


# --- Singleton ---
_adb_service: ADBService | None = None


def get_adb_service() -> ADBService:
    """Retourne l'instance singleton du service ADB."""
    global _adb_service
    if _adb_service is None:
        _adb_service = ADBService()
    return _adb_service
