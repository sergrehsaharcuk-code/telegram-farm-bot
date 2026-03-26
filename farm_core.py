import os
import json
import zipfile
import shutil
import requests
import socks
import asyncio
import pycountry
from datetime import datetime, timedelta
from telethon import TelegramClient
from telethon.errors import PhoneCodeInvalidError, FloodWaitError

from config import API_ID, API_HASH, ACCOUNTS_DIR, SESSIONS_DIR, TIGER_API_KEY


class TigerSMS:
    def __init__(self, api_key):
        self.api_key = api_key
        self.api_url = "https://api.tiger-sms.com/stubs/handler_api.php"
        self.active_numbers = {}
    
    def _request(self, params):
        params['api_key'] = self.api_key
        try:
            response = requests.get(self.api_url, params=params, timeout=30)
            result = response.text.strip()
            print(f"Tiger SMS: {result[:200]}")
            return result
        except Exception as e:
            print(f"Tiger SMS ошибка: {e}")
            return None
    
    def get_balance(self):
        result = self._request({'action': 'getBalance'})
        if result and result.startswith('ACCESS_BALANCE'):
            try:
                return float(result.split(':')[1])
            except:
                return None
        return None
    
    def get_prices(self):
        """Получает цены с автоматическим определением названий стран"""
        # Получаем цены
        result = self._request({'action': 'getPrices', 'service': 'tg'})
        if not result:
            return None
        
        try:
            data = json.loads(result)
            prices = []
            
            for country_id, services in data.items():
                if 'tg' in services:
                    tg_info = services['tg']
                    
                    # Извлекаем цену
                    if isinstance(tg_info, list) and len(tg_info) > 0:
                        cost = tg_info[0].get('cost', 0)
                    else:
                        cost = tg_info.get('cost', 0)
                    
                    # Получаем название страны через pycountry
                    name = self._get_country_name(country_id)
                    
                    prices.append({
                        'id': country_id,
                        'name': name,
                        'price': float(cost)
                    })
            
            prices.sort(key=lambda x: x['price'])
            print(f"✅ Получены цены для {len(prices)} стран")
            return prices
                
        except Exception as e:
            print(f"❌ Ошибка обработки цен: {e}")
            return None
    
    def _get_country_name(self, country_id):
        """Автоматически определяет название страны по ID"""
        try:
            # Пробуем как цифровой код ISO 3166-1 numeric (с 3 цифрами)
            country_id_padded = str(country_id).zfill(3)
            country = pycountry.countries.get(numeric=country_id_padded)
            if country:
                return country.name
        except:
            pass
        
        try:
            # Пробуем как двухбуквенный код ISO 3166-1 alpha-2
            country = pycountry.countries.get(alpha_2=str(country_id))
            if country:
                return country.name
        except:
            pass
        
        try:
            # Пробуем как трехбуквенный код ISO 3166-1 alpha-3
            country = pycountry.countries.get(alpha_3=str(country_id))
            if country:
                return country.name
        except:
            pass
        
        return f"Страна {country_id}"
    
    def get_number(self, service="tg", country="any", operator=None):
        params = {
            'action': 'getNumber',
            'service': service,
            'country': country
        }
        if operator:
            params['operator'] = operator
        
        result = self._request(params)
        if result and result.startswith('ACCESS_NUMBER'):
            parts = result.split(':')
            if len(parts) >= 3:
                return parts[1], parts[2]
        return None, None
    
    async def get_code(self, number_id, timeout=120):
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < timeout:
            result = self._request({'action': 'getStatus', 'id': number_id})
            if result and result.startswith('STATUS_OK'):
                return result.split(':')[1]
            elif result and result.startswith('STATUS_WAIT_CODE'):
                await asyncio.sleep(5)
            else:
                await asyncio.sleep(5)
        return None
    
    def cancel_number(self, number_id):
        self._request({'action': 'setStatus', 'id': number_id, 'status': 8})


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
        self.tiger_sms = TigerSMS(TIGER_API_KEY)
        
        os.makedirs(self.accounts_dir, exist_ok=True)
        os.makedirs(self.sessions_dir, exist_ok=True)

    def load_proxies(self):
        return self.proxy_manager.load_proxies()

    async def buy_number_by_country_id(self, user_id, country_id):
        print(f"📱 Покупаю номер в стране {country_id}...")
        
        number_id, phone = self.tiger_sms.get_number(service="tg", country=country_id)
        if not phone:
            return False, f"Не удалось купить номер. Попробуй другую страну.", None
        
        print(f"✅ Номер куплен: {phone}")
        
        success, msg = await self.start_registration(phone, user_id)
        if not success:
            self.tiger_sms.cancel_number(number_id)
            return False, msg, None
        
        print("⏳ Жду код...")
        code = await self.tiger_sms.get_code(number_id)
        if not code:
            self.tiger_sms.cancel_number(number_id)
            return False, "Код не пришёл за 2 минуты", None
        
        print(f"📨 Код: {code}")
        
        success, msg, data = await self.complete_registration(phone, code)
        if success:
            return True, msg, data
        else:
            self.tiger_sms.cancel_number(number_id)
            return False, msg, None

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
