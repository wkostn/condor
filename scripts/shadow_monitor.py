import asyncio
import logging
import os
import time
from dataclasses import dataclass

import aiohttp


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
log = logging.getLogger("shadow_monitor")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _parse_targets() -> list[tuple[str, str]]:
    # Format: "name=url,name2=url2"
    raw = os.getenv("SHADOW_MONITOR_TARGETS", "").strip()
    if not raw:
        hb_api = os.getenv("HB_API_URL", "http://127.0.0.1:8000").rstrip("/")
        targets = [("hummingbot_api", f"{hb_api}/docs")]
        token = os.getenv("TELEGRAM_TOKEN", "").strip()
        if token:
            targets.append(("telegram_api", f"https://api.telegram.org/bot{token}/getMe"))
        include_web = os.getenv("SHADOW_MONITOR_INCLUDE_CONDOR_WEB", "").strip().lower()
        if include_web in {"1", "true", "yes", "on"}:
            web_port = _env_int("WEB_PORT", 8088)
            targets.append(("condor_web", f"http://127.0.0.1:{web_port}/docs"))
        return targets

    targets: list[tuple[str, str]] = []
    for part in raw.split(","):
        piece = part.strip()
        if not piece or "=" not in piece:
            continue
        name, url = piece.split("=", 1)
        targets.append((name.strip(), url.strip()))
    return targets


@dataclass
class MonitorState:
    failures: int = 0
    down_since: float | None = None
    is_down: bool = False


class ShadowMonitor:
    def __init__(self):
        self.interval_sec = _env_int("SHADOW_MONITOR_INTERVAL_SEC", 60)
        self.timeout_sec = _env_int("SHADOW_MONITOR_TIMEOUT_SEC", 8)
        self.fail_threshold = _env_int("SHADOW_MONITOR_FAIL_THRESHOLD", 3)
        self.targets = _parse_targets()
        self.token = os.getenv("TELEGRAM_TOKEN", "").strip()
        self.admin_user_id = os.getenv("ADMIN_USER_ID", "").strip()
        self.states = {name: MonitorState() for name, _ in self.targets}

        log.info(
            "Shadow Monitor started: interval=%ss timeout=%ss threshold=%s targets=%s",
            self.interval_sec,
            self.timeout_sec,
            self.fail_threshold,
            [n for n, _ in self.targets],
        )

    async def _notify(self, message: str) -> None:
        if not self.token or not self.admin_user_id:
            log.warning("Alert skipped (missing TELEGRAM_TOKEN or ADMIN_USER_ID): %s", message)
            return

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.admin_user_id,
            "text": message,
            "disable_web_page_preview": True,
        }
        timeout = aiohttp.ClientTimeout(total=10)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status >= 400:
                        body = await resp.text()
                        log.warning("Telegram alert failed: %s %s", resp.status, body)
        except Exception as e:
            log.warning("Telegram alert exception: %s", e)

    async def _check_target(self, session: aiohttp.ClientSession, name: str, url: str) -> None:
        state = self.states[name]
        now = time.time()

        ok = False
        error_msg = ""
        try:
            async with session.get(url) as resp:
                ok = 200 <= resp.status < 400
                if not ok:
                    error_msg = f"HTTP {resp.status}"
        except Exception as e:
            error_msg = str(e)

        if ok:
            if state.is_down:
                duration = int(now - (state.down_since or now))
                msg = f"✅ Shadow Monitor recovery: {name} is UP again (down for {duration}s)."
                log.info(msg)
                await self._notify(msg)
            state.failures = 0
            state.down_since = None
            state.is_down = False
            return

        state.failures += 1
        if state.down_since is None:
            state.down_since = now

        log.warning("Health check failed: %s (%s) [%s/%s]", name, error_msg, state.failures, self.fail_threshold)

        if not state.is_down and state.failures >= self.fail_threshold:
            state.is_down = True
            msg = (
                f"🚨 Shadow Monitor alert: {name} appears DOWN. "
                f"failures={state.failures}, error={error_msg}"
            )
            log.error(msg)
            await self._notify(msg)

    async def run_forever(self) -> None:
        if not self.targets:
            log.error("No targets configured. Set SHADOW_MONITOR_TARGETS or WEB_PORT/HB_API_URL.")
            return

        timeout = aiohttp.ClientTimeout(total=self.timeout_sec)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                await asyncio.gather(
                    *(self._check_target(session, name, url) for name, url in self.targets)
                )
                await asyncio.sleep(self.interval_sec)


async def main() -> None:
    monitor = ShadowMonitor()
    await monitor.run_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shadow Monitor stopped")
