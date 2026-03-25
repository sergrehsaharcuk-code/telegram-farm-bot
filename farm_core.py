import os
import json
import zipfile
import shutil
import requests
import socks as socks
from datetime import datetime
from telethon import TelegramClient
from telethon.errors import PhoneCodeInvalidError, FloodWaitError

from config import API_ID, API_HASH, ACCOUNTS_DIR, SESSIONS_DIR


class TelegramFarm:
    def __init__(self, api_id, api_hash, accounts_dir, sessions_dir):
        self.api_id = api_id
        self.api_hash = api_hash
        self.accounts_dir = accounts_dir
        self.sessions_dir = sessions_dir
        self.pending_registrations = {}
        self.proxies = []
        self.proxy_index = 0
        
        os.makedirs(self.accounts_dir, exist_ok=True)
        os.makedirs(self.sessions_dir, exist_ok=True)

    def load_proxies(self):
        """Загружает бесплатные прокси"""
        urls = [
            "https://raw.githubusercontent.com/proxygenerator1/ProxyGenerator/main/MostStable/socks5.txt",
            "https://raw.githubusercontent.com/proxygenerator1/ProxyGenerator/main/Stable/socks5.txt",
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

    def get_next_proxy(self):
        """Возвращает следующий прокси"""
        if not self.proxies:
            return None
        proxy = self.proxies[self.proxy_index % len(self.proxies)]
        self.proxy_index += 1
        return proxy

    async def start_registration(self, phone, user_id):
        proxy = self.get_next_proxy()
        
        phone_clean = phone.replace('+', '').replace(' ', '')
        session_path = os.path.join(self.sessions_dir, f"temp_{phone_clean}")

        if proxy:
            client = TelegramClient(
                session_path, 
                self.api_id, 
                self.api_hash, 
                proxy=proxy,
                device_model="iPhone 15 Pro",
                system_version="17.4.1"
            )
        else:
            client = TelegramClient(session_path, self.api_id, self.api_hash)

        try:
            await client.connect()
            
            if await client.is_user_authorized():
                await client.disconnect()
                return False, "Аккаунт уже авторизован"

            sent_code = await client.send_code_request(phone)
            
            self.pending_registrations[phone] = {
                'client': client,
                'phone_hash': sent_code.phone_code_hash,
                'session_path': session_path,
                'user_id': user_id
            }
            return True, f"Код отправлен на {phone}"

        except FloodWaitError as e:
            return False, f"Ошибка: нужно подождать {e.seconds} сек"
        except Exception as e:
            await client.disconnect()
            return False, f"Ошибка: {str(e)}"

    async def complete_registration(self, phone, code):
        if phone not in self.pending_registrations:
            return False, "Регистрация не найдена", None

        reg_data = self.pending_registrations[phone]
        client = reg_data['client']
        phone_clean = phone.replace('+', '').replace(' ', '')

        try:
            await client.sign_in(phone, code, phone_code_hash=reg_data['phone_hash'])
            
            me = await client.get_me()
            session_string = client.session.save()
            
            await client.disconnect()

            account_folder = os.path.join(self.accounts_dir, phone_clean)
            os.makedirs(account_folder, exist_ok=True)

            with open(os.path.join(account_folder, "auth_key.txt"), "w") as f:
                f.write(session_string)

            info = {
                "phone": me.phone,
                "id": me.id,
                "first_name": me.first_name,
                "username": me.username,
                "session_string": session_string,
                "date_added": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            with open(os.path.join(account_folder, "info.json"), "w", encoding="utf-8") as f:
                json.dump(info, f, ensure_ascii=False, indent=4)

            temp_session_file = reg_data['session_path'] + ".session"
            final_session_file = os.path.join(account_folder, f"{phone_clean}.session")
            if os.path.exists(temp_session_file):
                shutil.move(temp_session_file, final_session_file)

            archive_path = os.path.join(self.accounts_dir, f"{phone_clean}.zip")
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
