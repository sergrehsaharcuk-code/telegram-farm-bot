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

from config import API_ID, API_HASH, ACCOUNTS_DIR, SESSIONS_DIR


class ProxyManager:
    """Управление прокси с проверкой и лимитами"""
    
    def __init__(self):
        self.proxies = []  # список прокси в формате кортежа
        self.used_proxies = {}  # {proxy_tuple: {'count': int, 'last_used': datetime}}
        self.max_uses_per_day = 2  # максимум 2 аккаунта на один прокси в день
    
    def load_proxies(self):
        """Загружает и подготавливает прокси"""
        urls = [
            "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt",
            "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
        ]
        
        raw_list = []
        for url in urls:
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    raw_list.extend(response.text.strip().split('\n'))
            except Exception:
                pass
        
        unique_proxies = list(set([p.strip() for p in raw_list if p.strip()]))
        
        self.proxies = []
        for p_str in unique_proxies:
            parsed = self._parse_proxy(p_str)
            if parsed:
                self.proxies.append(parsed)
        
        return len(self.proxies)
    
    def _parse_proxy(self, proxy_str):
        """Преобразует строку в кортеж для Telethon"""
        clean_str = proxy_str.replace("socks5://", "").replace("http://", "")
        parts = clean_str.split(':')
        
        try:
            host = parts[0]
            port = int(parts[1])
            user = parts[2] if len(parts) > 2 else None
            password = parts[3] if len(parts) > 3 else None
            return (socks.SOCKS5, host, port, True, user, password)
        except Exception:
            return None
    
    async def check_proxy(self, proxy):
        """Проверяет, работает ли прокси"""
        if not proxy:
            return False
        
        try:
            # Создаём клиента с прокси
            client = TelegramClient('check_session', API_ID, API_HASH, proxy=proxy)
            await client.connect()
            
            # Проверяем, что подключились
            is_connected = client.is_connected()
            await client.disconnect()
            
            return is_connected
        except Exception:
            return False
    
    def can_use_proxy(self, proxy):
        """Проверяет, не превышен ли лимит использования прокси"""
        if proxy not in self.used_proxies:
            return True
        
        usage = self.used_proxies[proxy]
        
        # Сбрасываем счётчик, если прошёл день
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
    
    async def get_working_proxy(self):
        """Возвращает рабочий прокси с учётом лимитов"""
        # Перемешиваем список
        import random
        random.shuffle(self.proxies)
        
        for proxy in self.proxies:
            # Проверяем лимиты
            if not self.can_use_proxy(proxy):
                continue
            
            # Проверяем, работает ли прокси
            if await self.check_proxy(proxy):
                return proxy
        
        return None  # Нет рабочих прокси


class TelegramFarm:
    def __init__(self, api_id, api_hash, accounts_dir, sessions_dir):
        self.api_id = api_id
        self.api_hash = api_hash
        self.accounts_dir = accounts_dir
        self.sessions_dir = sessions_dir
        self.pending_registrations = {}
        self.proxy_manager = ProxyManager()

    async def start_registration(self, phone, user_id):
        # Получаем рабочий прокси
        proxy = await self.proxy_manager.get_working_proxy()
        
        session_name = f"session_{phone.replace('+', '')}"
        session_path = os.path.join(self.sessions_dir, session_name)

        if proxy:
            client = TelegramClient(session_path, self.api_id, self.api_hash, proxy=proxy)
        else:
            client = TelegramClient(session_path, self.api_id, self.api_hash)

        try:
            await client.connect()

            if await client.is_user_authorized():
                await client.disconnect()
                return False, "Аккаунт уже авторизован"

            await client.send_code_request(phone)

            self.pending_registrations[phone] = {
                'client': client,
                'session_path': session_path,
                'user_id': user_id,
                'proxy': proxy
            }
            return True, f"Код отправлен на {phone}"

        except FloodWaitError as e:
            return False, f"Ошибка: нужно подождать {e.seconds} сек"
        except Exception as e:
            await client.disconnect()
            return False, f"Ошибка: {str(e)}"

    async def complete_registration(self, phone, code):
        if phone not in self.pending_registrations:
            return False, "Нет ожидающей регистрации", None

        data = self.pending_registrations[phone]
        client = data['client']
        proxy = data.get('proxy')

        try:
            await client.sign_in(phone, code)

            me = await client.get_me()
            session_string = client.session.save()
            
            # Если использовали прокси — отмечаем
            if proxy:
                self.proxy_manager.mark_used(proxy)

            await client.disconnect()

            folder_name = phone.replace('+', '')
            account_folder = os.path.join(self.accounts_dir, folder_name)
            os.makedirs(account_folder, exist_ok=True)

            with open(os.path.join(account_folder, "auth_key.txt"), "w") as f:
                f.write(session_string)

            info = {
                "phone": me.phone,
                "id": me.id,
                "first_name": me.first_name,
                "session_string": session_string,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            with open(os.path.join(account_folder, "info.json"), "w", encoding="utf-8") as f:
                json.dump(info, f, ensure_ascii=False, indent=4)

            session_file = f"{client.session.filename}.session"
            if os.path.exists(session_file):
                shutil.copy(session_file, os.path.join(account_folder, f"{folder_name}.session"))

            archive_path = os.path.join(self.accounts_dir, f"{folder_name}.zip")
            with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(account_folder):
                    for file in files:
                        full_path = os.path.join(root, file)
                        zipf.write(full_path, os.path.relpath(full_path, self.accounts_dir))

            del self.pending_registrations[phone]

            return True, f"✅ Аккаунт {phone} сохранен!", info

        except PhoneCodeInvalidError:
            return False, "❌ Неверный код", None
        except Exception as e:
            return False, f"❌ Ошибка: {str(e)}", None
        finally:
            if client.is_connected():
                await client.disconnect()

    def get_accounts_list(self):
        accounts = []
        if os.path.exists(self.accounts_dir):
            for item in os.listdir(self.accounts_dir):
                if item.endswith('.zip'):
                    accounts.append(item)
        return sorted(accounts, reverse=True)

    async def cleanup(self):
        for phone, data in self.pending_registrations.items():
            try:
                await data['client'].disconnect()
            except:
                pass
        self.pending_registrations.clear()
