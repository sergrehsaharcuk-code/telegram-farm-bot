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


# Официальные названия стран из документации Tiger SMS
COUNTRY_NAMES = {
    "1": "Украина",
    "2": "Казахстан",
    "4": "Филиппины",
    "5": "Мьянма",
    "6": "Индонезия",
    "7": "Малайзия",
    "8": "Кения",
    "9": "Танзания",
    "10": "Вьетнам",
    "11": "Кыргызстан",
    "12": "США (виртуальные)",
    "13": "Израиль",
    "14": "Гонконг",
    "15": "Польша",
    "16": "Великобритания",
    "17": "Мадагаскар",
    "18": "Конго",
    "19": "Нигерия",
    "20": "Макао",
    "21": "Египет",
    "22": "Индия",
    "23": "Ирландия",
    "24": "Камбоджа",
    "25": "Лаос",
    "26": "Гаити",
    "27": "Кот-д'Ивуар",
    "28": "Гамбия",
    "29": "Сербия",
    "30": "Йемен",
    "31": "Южная Африка",
    "32": "Румыния",
    "33": "Колумбия",
    "34": "Эстония",
    "35": "Азербайджан",
    "36": "Канада",
    "37": "Марокко",
    "38": "Гана",
    "39": "Аргентина",
    "40": "Узбекистан",
    "41": "Камерун",
    "42": "Чад",
    "43": "Германия",
    "44": "Литва",
    "45": "Хорватия",
    "46": "Швеция",
    "47": "Ирак",
    "48": "Нидерланды",
    "49": "Латвия",
    "50": "Австрия",
    "51": "Беларусь",
    "52": "Таиланд",
    "53": "Саудовская Аравия",
    "54": "Мексика",
    "55": "Тайвань",
    "56": "Испания",
    "57": "Иран",
    "58": "Алжир",
    "59": "Словения",
    "60": "Бангладеш",
    "61": "Сенегал",
    "62": "Турция",
    "63": "Чехия",
    "64": "Шри-Ланка",
    "65": "Перу",
    "66": "Пакистан",
    "67": "Новая Зеландия",
    "68": "Гвинея",
    "69": "Мали",
    "70": "Венесуэла",
    "71": "Эфиопия",
    "72": "Монголия",
    "73": "Бразилия",
    "74": "Афганистан",
    "75": "Уганда",
    "76": "Ангола",
    "77": "Кипр",
    "78": "Франция",
    "79": "Папуа-Новая Гвинея",
    "80": "Мозамбик",
    "81": "Непал",
    "82": "Бельгия",
    "83": "Болгария",
    "84": "Венгрия",
    "85": "Молдова",
    "86": "Италия",
    "87": "Парагвай",
    "88": "Гондурас",
    "89": "Тунис",
    "90": "Никарагуа",
    "91": "Тимор-Лешти",
    "92": "Боливия",
    "93": "Коста-Рика",
    "94": "Гватемала",
    "95": "ОАЭ",
    "96": "Зимбабве",
    "97": "Пуэрто-Рико",
    "98": "Судан",
    "99": "Того",
    "100": "Кувей特",
    "101": "Сальвадор",
    "102": "Ливия",
    "103": "Ямайка",
    "104": "Тринидад и Тобаго",
    "105": "Эквадор",
    "106": "Свазиленд",
    "107": "Оман",
    "108": "Босния и Герцеговина",
    "109": "Доминиканская Республика",
    "110": "Сирия",
    "111": "Катар",
    "112": "Панама",
    "113": "Куба",
    "114": "Мавритания",
    "115": "Сьерра-Леоне",
    "116": "Иордания",
    "117": "Португалия",
    "118": "Барбадос",
    "119": "Бурунди",
    "120": "Бенин",
    "121": "Бруней",
    "122": "Багамы",
    "123": "Ботсвана",
    "124": "Белиз",
    "125": "ЦАР",
    "126": "Доминика",
    "127": "Гренада",
    "128": "Грузия",
    "129": "Греция",
    "130": "Гвинея-Бисау",
    "131": "Гайана",
    "132": "Исландия",
    "133": "Коморы",
    "134": "Сент-Китс и Невис",
    "135": "Либерия",
    "136": "Лесото",
    "137": "Малави",
    "138": "Намибия",
    "139": "Нигер",
    "140": "Руанда",
    "141": "Словакия",
    "142": "Суринам",
    "143": "Таджикистан",
    "144": "Монако",
    "145": "Бахрейн",
    "146": "Реюньон",
    "147": "Замбия",
    "148": "Армения",
    "149": "Сомали",
    "150": "Конго (ДР)",
    "151": "Чили",
    "152": "Буркина-Фасо",
    "153": "Ливан",
    "154": "Габон",
    "155": "Албания",
    "156": "Уругвай",
    "157": "Маврикий",
    "158": "Бутан",
    "159": "Мальдивы",
    "160": "Гваделупа",
    "161": "Туркменистан",
    "162": "Французская Гвиана",
    "163": "Финляндия",
    "164": "Сент-Люсия",
    "165": "Люксембург",
    "166": "Сент-Винсент",
    "167": "Экваториальная Гвинея",
    "168": "Джибути",
    "169": "Антигуа и Барбуда",
    "170": "Каймановы острова",
    "171": "Черногория",
    "172": "Дания",
    "173": "Швейцария",
    "174": "Норвегия",
    "175": "Австралия",
    "176": "Эритрея",
    "177": "Южный Судан",
    "178": "Сан-Томе и Принсипи",
    "179": "Аруба",
    "180": "Монтсеррат",
    "181": "Ангилья",
    "182": "Япония",
    "183": "Македония",
    "184": "Сейшелы",
    "185": "Новая Каледония",
    "186": "Кабо-Верде",
    "187": "США",
    "188": "Палестина",
    "189": "Фиджи",
    "190": "Южная Корея",
    "193": "Соломоновы Острова",
    "195": "Бермудские острова",
    "196": "Сингапур",
    "197": "Тонга",
    "198": "Самоа",
    "199": "Мальта",
    "201": "Гибралтар",
    "203": "Косово",
    "1001": "США VIP",
}


def get_country_name(country_id):
    """Возвращает русское название страны по ID из официальной документации"""
    return COUNTRY_NAMES.get(str(country_id), f"Страна {country_id}")


class TigerSMSClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.old_api_url = "https://api.tiger-sms.com/stubs/handler_api.php"

    def _request_old(self, params):
        params['api_key'] = self.api_key
        try:
            response = requests.get(self.old_api_url, params=params, timeout=30)
            result = response.text.strip()
            print(f"Tiger SMS: {result[:200]}")
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

    def get_prices(self):
        """Получает всех операторов с ценами для каждой страны"""
        result = self._request_old({'action': 'getPrices', 'service': 'tg'})
        
        if not result:
            print("❌ Пустой ответ от API")
            return None
        
        try:
            data = json.loads(result)
            all_offers = []
            
            for country_id, services in data.items():
                if 'tg' in services:
                    operators = services['tg']
                    
                    # operators может быть словарём или списком
                    if isinstance(operators, dict):
                        for op_name, op_data in operators.items():
                            if isinstance(op_data, dict):
                                price = float(op_data.get('cost', 0))
                            else:
                                price = float(op_data)
                            
                            all_offers.append({
                                'id': country_id,
                                'name': get_country_name(country_id),
                                'operator': op_name,
                                'price': price
                            })
                    elif isinstance(operators, list):
                        for op in operators:
                            if isinstance(op, dict):
                                price = float(op.get('cost', 0))
                                op_name = op.get('operator', 'Стандартный')
                            else:
                                price = float(op)
                                op_name = 'Стандартный'
                            
                            all_offers.append({
                                'id': country_id,
                                'name': get_country_name(country_id),
                                'operator': op_name,
                                'price': price
                            })
            
            # Сортируем по цене
            all_offers.sort(key=lambda x: x['price'])
            print(f"✅ Получены {len(all_offers)} предложений")
            return all_offers
        except Exception as e:
            print(f"❌ Ошибка парсинга: {e}")
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

    def get_all_offers(self):
        """Возвращает все предложения (страна + оператор + цена)"""
        return self.tiger_client.get_prices()

    def get_balance(self):
        return self.tiger_client.get_balance()

    async def buy_number_with_operator(self, user_id, country_id, operator):
        """Покупает номер у конкретного оператора"""
        print(f"📱 Покупаю номер: страна {country_id}, оператор {operator}")

        number_id, phone = self.tiger_client.buy_number(country_id, operator)
        if not phone:
            return False, f"Не удалось купить номер. Попробуй другой вариант.", None

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
