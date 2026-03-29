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


class TigerSMSClient:
    """Клиент для работы с Tiger SMS API"""

    def __init__(self, api_key):
        self.api_key = api_key
        self.old_api_url = "https://api.tiger-sms.com/stubs/handler_api.php"
        self.new_api_url = "https://tiger-sms.com/api/v2/services/tg/prices"
        
        # Куки для авторизации на сайте (получены из браузера)
        self.cookies = {
            'tigersms_session': 'eyJpdiI6InNhVTFBbEswMXBEYlp5c0F0ZTJDYUE9PSIsInZhbHVlIjoiQTlNLy9IT3d3SXB4L2JReE1wVmJieTRjUnlYTU5xeXcxZkdtY09pWG5QdWN4bTdmZDkxYzV0MGkzKyt0SHprbHg1cjJBSjU0b2VrSVZYc3lCMXFxZVJNYVpzbllreVdUajk0amRRN3JUUDdIS3I3cnN5aXU4U1psVGpkRkNWeGkiLCJtYWMiOiIwMmEzMmVlMjA0Njc2MTgwNzgwYTUzNzkyZTQ4ZDc3YzZiNTM3MTQxNGQzMmM0ZGNmOTllMmViOGU0MWJhOWM4IiwidGFnIjoiIn0%3D',
            'XSRF-TOKEN': 'eyJpdiI6IndvL3FhL3JwMVhWVzVkMTBkRlVmK1E9PSIsInZhbHVlIjoiVGt2QkJzYUtpWFJWK0M1KzVUenpsMHhkSm1kcGpyeHo0UkVJOVRKWmRpSE96c0JST2ZOeDFyUUk5dGYwdEp0MXQzUVZ1eEhUbWcyY0JjeHVYRldMazVhai9JZjR0emNyNGFzaVVQYzZ0YjloYWYxWDYzYjRBSDFFT0lDalcyelAiLCJtYWMiOiJlNGVjYjZmM2FlYjBjMTg2NmRlYjRhNmZlZDA5NDhlNTY4M2Q2Y2NlYWYzMjg2ZGFjODY4YWI5NWEyMDE3YjNkIiwidGFnIjoiIn0%3D',
        }

    def _request_old(self, params):
        """Старый API для покупки номеров и баланса"""
        params['api_key'] = self.api_key
        try:
            response = requests.get(self.old_api_url, params=params, timeout=30)
            result = response.text.strip()
            print(f"Tiger SMS (old): {result[:200]}")
            return result
        except Exception as e:
            print(f"Tiger SMS ошибка: {e}")
            return None

    def get_balance(self):
        result = self._request_old({'action': 'getBalance'})
        if result and result.startswith('ACCESS_BALANCE'):
            try:
                return float(result.split(':')[1])
            except:
                return None
        return None

    def get_prices_from_site(self):
        """Получает цены напрямую с сайта Tiger SMS через API с авторизацией"""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': 'https://tiger-sms.com/ru',
        }
        
        try:
            response = requests.get(self.new_api_url, headers=headers, cookies=self.cookies, timeout=15)
            print(f"API ответ: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Получены цены с сайта: {len(data)} стран")
                return data
            else:
                print(f"Ошибка API: {response.text[:200]}")
                return None
        except Exception as e:
            print(f"Ошибка получения цен с сайта: {e}")
            return None

    def buy_number(self, country_id, operator=None):
        params = {
            'action': 'getNumber',
            'service': 'tg',
            'country': country_id
        }
        if operator:
            params['operator'] = operator

        result = self._request_old(params)
        if result and result.startswith('ACCESS_NUMBER'):
            parts = result.split(':')
            if len(parts) >= 3:
                return parts[1], parts[2]
        return None, None

    def get_code_status(self, number_id):
        return self._request_old({'action': 'getStatus', 'id': number_id})

    def cancel_number(self, number_id):
        self._request_old({'action': 'setStatus', 'id': number_id, 'status': 8})


class ProxyManager:
    def __init__(self):
        self.proxies = []
        self.used_proxies = {}
        self.max_uses_per_day = 2
        self.current_index = 0

    def load_proxies(self):
        url = "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt"

        try:
            print("🌐 Загрузка прокси...")
            response = requests.get(url, timeout=15)
            if response.status_code != 200:
                print("Ошибка загрузки прокси")
                return 0

            lines = response.text.strip().split('\n')
            self.proxies = []

            for line in lines[:50]:
                line = line.strip()
                if line and ':' in line:
                    parsed = self._parse_proxy(line)
                    if parsed:
                        self.proxies.append(parsed)
                        print(f"✅ Прокси: {parsed[1]}:{parsed[2]}")

            print(f"✅ Загружено прокси: {len(self.proxies)}")
            self.current_index = 0
            return len(self.proxies)
        except Exception as e:
            print(f"Ошибка: {e}")
            return 0

    def _parse_proxy(self, proxy_str):
        clean_str = proxy_str.replace("socks5://", "").replace("http://", "")
        parts = clean_str.split(':')
        try:
            return (socks.SOCKS5, parts[0], int(parts[1]), True, None, None)
        except:
            return None

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
        self.tiger_client = TigerSMSClient(TIGER_API_KEY)

        os.makedirs(self.accounts_dir, exist_ok=True)
        os.makedirs(self.sessions_dir, exist_ok=True)

    def load_proxies(self):
        return self.proxy_manager.load_proxies()

    def get_countries_with_prices(self):
        """Возвращает список стран с ценами для бота"""
        raw_data = self.tiger_client.get_prices_from_site()
        if not raw_data:
            return None

        result = []
        for item in raw_data:
            # Пытаемся получить ID и цену из разных форматов
            country_id = item.get('country_id') or item.get('id')
            country_name = item.get('name') or item.get('country')
            price = item.get('price') or item.get('cost', 0)
            
            if country_id is not None and country_name:
                result.append({
                    'id': str(country_id),
                    'name': country_name,
                    'price': float(price)
                })
            elif country_id is not None:
                # Если нет названия, используем ID
                result.append({
                    'id': str(country_id),
                    'name': f"Страна {country_id}",
                    'price': float(price)
                })

        # Сортируем по цене
        result.sort(key=lambda x: x['price'])
        return result

    def get_balance(self):
        return self.tiger_client.get_balance()

    async def buy_number_by_country_id(self, user_id, country_id):
        print(f"📱 Покупаю номер в стране {country_id}...")

        number_id, phone = self.tiger_client.buy_number(country_id)
        if not phone:
            return False, f"Не удалось купить номер. Попробуй другую страну.", None

        print(f"✅ Номер куплен: {phone}")

        success, msg = await self.start_registration(phone, user_id)
        if not success:
            self.tiger_client.cancel_number(number_id)
            return False, msg, None

        print("⏳ Жду код...")
        code = await self.wait_for_code(number_id)
        if not code:
            self.tiger_client.cancel_number(number_id)
            return False, "Код не пришёл за 2 минуты", None

        print(f"📨 Код: {code}")

        success, msg, data = await self.complete_registration(phone, code)
        if success:
            return True, msg, data
        else:
            self.tiger_client.cancel_number(number_id)
            return False, msg, None

    async def wait_for_code(self, number_id, timeout=120):
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < timeout:
            result = self.tiger_client.get_code_status(number_id)
            if result and result.startswith('STATUS_OK'):
                return result.split(':')[1]
            elif result and result.startswith('STATUS_WAIT_CODE'):
                await asyncio.sleep(5)
            else:
                await asyncio.sleep(5)
        return None

    async def start_registration(self, phone, user_id):
        proxy = self.proxy_manager.get_working_proxy()

        session_name = f"session_{phone.replace('+', '')}"
        session_path = os.path.join(self.sessions_dir, session_name)

        if not proxy:
            return False, "Нет рабочих прокси. Попробуй позже."

        print(f"🔌 Используем прокси: {proxy[1]}:{proxy[2]}")
        client = TelegramClient(session_path, self.api_id, self.api_hash, proxy=proxy)

        try:
            await asyncio.wait_for(client.connect(), timeout=15)
            if await client.is_user_authorized():
                await client.disconnect()
                return False, "Аккаунт уже авторизован"
            await client.send_code_request(phone)
            self.pending_registrations[phone] = {'client': client, 'proxy': proxy}
            return True, f"Код отправлен на {phone}"
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
                return False, "Не удалось получить session_string", None
            if proxy:
                self.proxy_manager.mark_used(proxy)
            await client.disconnect()
            del self.pending_registrations[phone]

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
                        zipf.write(os.path.join(root, file), os.path.relpath(os.path.join(root, file), self.accounts_dir))

            return True, f"✅ Аккаунт {phone} готов!", info
        except PhoneCodeInvalidError:
            return False, "Неверный код", None
        except Exception as e:
            return False, f"Ошибка: {str(e)}", None

    def get_accounts_list(self):
        accounts = []
        if os.path.exists(self.accounts_dir):
            for item in os.listdir(self.accounts_dir):
                if item.endswith('.zip'):
                    accounts.append(item)
        return sorted(accounts, reverse=True)
