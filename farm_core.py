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

# Конфигурация Tiger SMS API
TIGER_API_KEY = "5lSQtpVENAT4WoIHx8LfVRyPCqKquAx5"
TIGER_API_URL = "https://api.tiger-sms.com/stubs/handler_api.php"


class TigerSMS:
    """Класс для работы с API Tiger SMS"""
    
    def __init__(self, api_key):
        self.api_key = api_key
        self.active_numbers = {}  # {phone: {'id': id, 'status': status}}
    
    def _request(self, params):
        """Отправляет запрос к API Tiger SMS"""
        params['api_key'] = self.api_key
        try:
            response = requests.get(TIGER_API_URL, params=params, timeout=30)
            return response.text.strip()
        except Exception as e:
            print(f"Ошибка запроса к Tiger SMS: {e}")
            return None
    
    def get_number(self, service="tg", country="ru"):
        """Покупает новый номер"""
        result = self._request({
            'action': 'getNumber',
            'service': service,
            'country': country
        })
        
        if result and result.startswith('ACCESS_NUMBER'):
            parts = result.split(':')
            if len(parts) >= 3:
                number_id = parts[1]
                phone = parts[2]
                self.active_numbers[phone] = {'id': number_id, 'status': 'waiting'}
                return phone, number_id
        return None, None
    
    def get_code(self, number_id, timeout=120):
        """Ждёт код SMS (максимум timeout секунд)"""
        import time
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            result = self._request({
                'action': 'getStatus',
                'id': number_id
            })
            
            if result and result.startswith('STATUS_OK'):
                code = result.split(':')[1]
                return code
            elif result and result.startswith('STATUS_WAIT_CODE'):
                time.sleep(5)
                continue
            else:
                time.sleep(5)
        
        return None
    
    def cancel_number(self, number_id):
        """Отменяет номер (если код не пришёл)"""
        self._request({
            'action': 'setStatus',
            'id': number_id,
            'status': 8  # 8 = cancel
        })


class ProxyManager:
    def __init__(self):
        self.proxies = []
        self.used_proxies = {}
        self.max_uses_per_day = 2
        self.current_index = 0

    def load_proxies(self):
        url = "https://advanced.name/freeproxy?protocol=socks5&type=all"
        
        try:
            response = requests.get(url, timeout=15)
            if response.status_code != 200:
                return 0

            import re
            pattern = r'<tr[^>]*>.*?<td[^>]*>(\d+\.\d+\.\d+\.\d+)<\/td>.*?<td[^>]*>(\d+)<\/td>'
            matches = re.findall(pattern, response.text, re.DOTALL)
            
            raw_proxies = []
            for ip, port in matches:
                raw_proxies.append(f"{ip}:{port}")
            
            unique_proxies = list(set(raw_proxies))
            
            self.proxies = []
            for p_str in unique_proxies[:50]:
                parsed = self._parse_proxy(p_str)
                if parsed and self._quick_check(parsed):
                    self.proxies.append(parsed)
                    print(f"✅ Прокси работает: {parsed[1]}:{parsed[2]}")
            
            self.current_index = 0
            return len(self.proxies)
        except Exception as e:
            print(f"Ошибка загрузки: {e}")
            return 0

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
        if proxy not in self.used_proxies:
            return True
        usage = self.used_proxies[proxy]
        if datetime.now() - usage['last_used'] > timedelta(days=1):
            del self.used_proxies[proxy]
            return True
        return usage['count'] < self.max_uses_per_day

    def mark_used(self, proxy):
        if proxy not in self.used_proxies:
            self.used_proxies[proxy] = {'count': 0, 'last_used': datetime.now()}
        self.used_proxies[proxy]['count'] += 1
        self.used_proxies[proxy]['last_used'] = datetime.now()

    def get_working_proxy(self):
        if not self.proxies:
            return None
        
        for _ in range(len(self.proxies)):
            proxy = self.proxies[self.current_index % len(self.proxies)]
            self.current_index += 1
            
            if self.can_use_proxy(proxy):
                return proxy
        
        return None


class TelegramFarm:
    def __init__(self, api_id, api_hash, accounts_dir, sessions_dir):
        self.api_id = api_id
        self.api_hash = api_hash
        self.accounts_dir = accounts_dir
        self.sessions_dir = sessions_dir
        self.pending_registrations = {}
        self.proxy_manager = ProxyManager()
        self.tiger_sms = TigerSMS(TIGER_API_KEY)
        
        os.makedirs(self.accounts_dir, exist_ok=True)
        os.makedirs(self.sessions_dir, exist_ok=True)

    def load_proxies(self):
        return self.proxy_manager.load_proxies()

    async def auto_register(self, user_id):
        """Автоматическая регистрация аккаунта через Tiger SMS"""
        
        # 1. Покупаем номер
        print("📱 Покупаю номер...")
        phone, number_id = self.tiger_sms.get_number()
        if not phone:
            return False, "Не удалось купить номер. Проверь баланс на Tiger SMS."
        
        print(f"✅ Номер куплен: {phone}")
        
        # 2. Отправляем запрос на регистрацию
        success, message = await self.start_registration(phone, user_id)
        if not success:
            self.tiger_sms.cancel_number(number_id)
            return False, f"Ошибка при отправке кода: {message}"
        
        # 3. Ждём код из SMS
        print("⏳ Жду код...")
        code = self.tiger_sms.get_code(number_id, timeout=120)
        
        if not code:
            self.tiger_sms.cancel_number(number_id)
            return False, "Код не пришёл за 2 минуты"
        
        print(f"📨 Получен код: {code}")
        
        # 4. Завершаем регистрацию
        success, message, account_data = await self.complete_registration(phone, code)
        
        if success:
            return True, message, account_data
        else:
            self.tiger_sms.cancel_number(number_id)
            return False, message, None

    async def start_registration(self, phone, user_id):
        proxy = self.proxy_manager.get_working_proxy()
        
        session_name = f"session_{phone.replace('+', '')}"
        session_path = os.path.join(self.sessions_dir, session_name)

        if not proxy:
            print("⚠️ Нет рабочих прокси!")
            return False, "Нет рабочих прокси. Попробуй позже."

        print(f"✅ Используем прокси: {proxy[1]}:{proxy[2]}")
        client = TelegramClient(session_path, self.api_id, self.api_hash, proxy=proxy)

        try:
            await asyncio.wait_for(client.connect(), timeout=15)
            
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

        except asyncio.TimeoutError:
            await client.disconnect()
            if proxy in self.proxy_manager.proxies:
                self.proxy_manager.proxies.remove(proxy)
                print(f"❌ Прокси {proxy[1]}:{proxy[2]} не работает, удалён из списка")
            return False, "Таймаут подключения. Прокси не работает."
        except FloodWaitError as e:
            return False, f"Нужно подождать {e.seconds} сек"
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
            
            if not session_string:
                return False, "❌ Не удалось получить session_string", None

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
