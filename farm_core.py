import os
import json
import zipfile
import shutil
import requests
import socks
import asyncio
from datetime import datetime, timedelta
from telethon import TelegramClient
from telethon.errors import PhoneCodeInvalidError, FloodWaitError

from config import API_ID, API_HASH, ACCOUNTS_DIR, SESSIONS_DIR, TIGER_API_KEY


class TigerSMS:
    # ... (оставляем как было)


class ProxyManager:
    def __init__(self):
        self.proxies = []
        self.used_proxies = {}  # {proxy: {'count': int, 'last_used': datetime}}
        self.max_uses_per_day = 2  # 2 аккаунта на прокси в день
        self.current_index = 0

    def load_proxies(self):
        """Загружает прокси из источников"""
        urls = [
            "https://advanced.name/freeproxy?protocol=socks5&type=all",
            "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt",
        ]
        
        all_raw = []
        for url in urls:
            try:
                response = requests.get(url, timeout=15)
                if response.status_code == 200:
                    lines = response.text.strip().split('\n')
                    for line in lines:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            # Очищаем от лишнего
                            if ':' in line:
                                all_raw.append(line)
            except Exception as e:
                print(f"Ошибка загрузки {url}: {e}")
        
        unique_proxies = list(set(all_raw))
        
        self.proxies = []
        for p_str in unique_proxies[:50]:  # 50 прокси максимум
            parsed = self._parse_proxy(p_str)
            if parsed and self._quick_check(parsed):
                self.proxies.append(parsed)
                print(f"✅ Прокси работает: {parsed[1]}:{parsed[2]}")
        
        self.current_index = 0
        return len(self.proxies)

    def _parse_proxy(self, proxy_str):
        clean_str = proxy_str.replace("socks5://", "").replace("http://", "")
        parts = clean_str.split(':')
        try:
            host = parts[0]
            port = int(parts[1])
            return (socks.SOCKS5, host, port, True, None, None)
        except Exception:
            return None

    def _quick_check(self, proxy):
        try:
            import socket
            sock = socks.socksocket()
            sock.set_proxy(socks.SOCKS5, proxy[1], proxy[2])
            sock.settimeout(3)
            sock.connect(("1.1.1.1", 80))
            sock.close()
            return True
        except Exception:
            return False

    def can_use_proxy(self, proxy):
        """Проверяет, не превышен ли лимит использования прокси за день"""
        if proxy not in self.used_proxies:
            return True
        
        usage = self.used_proxies[proxy]
        # Если прошло больше суток — сбрасываем счётчик
        if datetime.now() - usage['last_used'] > timedelta(days=1):
            del self.used_proxies[proxy]
            return True
        
        return usage['count'] < self.max_uses_per_day

    def mark_used(self, proxy):
        """Отмечает, что прокси использован"""
        if proxy not in self.used_proxies:
            self.used_proxies[proxy] = {'count': 0, 'last_used': datetime.now()}
        self.used_proxies[proxy]['count'] += 1
        self.used_proxies[proxy]['last_used'] = datetime.now()

    def reset_daily_limits(self):
        """Сбрасывает все лимиты (вызывать раз в сутки)"""
        self.used_proxies = {}
        print("🔄 Лимиты прокси сброшены")

    def get_working_proxy(self):
        """Возвращает следующий доступный прокси"""
        if not self.proxies:
            return None
        
        for _ in range(len(self.proxies)):
            proxy = self.proxies[self.current_index % len(self.proxies)]
            self.current_index += 1
            
            if self.can_use_proxy(proxy):
                return proxy
        
        return None


class TelegramFarm:
    # ... (оставляем как было, но добавим reset в __init__)
