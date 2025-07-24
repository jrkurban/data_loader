# 2_daily_price_tracker.py
# BU BETİK, İLK VERİ YÜKLENDİKTEN SONRA HER GÜN ÇALIŞTIRILMALIDIR.

import requests
import sqlite3
import time
import os
from datetime import datetime
from typing import Optional, Dict, Any, List

# =========================================================================
# 1. YAPILANDIRMA (CONFIGURATION)
# =========================================================================
class Config:
    """Günlük fiyat takip betiğinin yapılandırmasını barındırır."""
    # GÜVENLİ YÖNTEM: API anahtarını ortam değişkenlerinden oku.
    STEAM_API_KEY = "EF38F5976C52F832D267CA05535C61F1"
    DB_NAME: str = "all_game.db"
    TARGET_COUNTRY: str = "TR"
    STEAM_APP_DETAILS_URL: str = "https://store.steampowered.com/api/appdetails"


# =========================================================================
# 2. YARDIMCI SINIFLAR VE FONKSİYONLAR
# =========================================================================
class DatabaseManager:
    """SQLite veritabanı bağlantısını ve işlemlerini yönetir."""
    def __init__(self, db_name: str):
        self.db_name = db_name
        self.conn: Optional[sqlite3.Connection] = None

    def __enter__(self):
        self.conn = sqlite3.connect(self.db_name)
        # Yabancı anahtar desteğini etkinleştir
        self.conn.execute("PRAGMA foreign_keys = ON;")
        return self.conn.cursor()

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            if exc_type is None:  # Hata yoksa değişiklikleri kaydet
                self.conn.commit()
            self.conn.close()

    @staticmethod
    def setup_price_history_table(cursor: sqlite3.Cursor) -> None:
        """FactPriceHistory ve DimDate tablolarının var olduğundan emin olur."""
        print("Fiyat geçmişi tabloları kontrol ediliyor...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS FactPriceHistory (
                price_history_id INTEGER PRIMARY KEY,
                game_id INTEGER NOT NULL,
                date_id INTEGER NOT NULL,
                price_currency TEXT,
                price_initial INTEGER,
                price_final INTEGER,
                discount_percent INTEGER,
                UNIQUE(game_id, date_id),
                FOREIGN KEY (game_id) REFERENCES DimGames (game_id),
                FOREIGN KEY (date_id) REFERENCES DimDate (date_id)
            );""")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS DimDate (
                date_id INTEGER PRIMARY KEY,
                full_date DATE NOT NULL,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                day INTEGER NOT NULL
            );""")
        print("Fiyat geçmişi tabloları hazır.")


class SteamClient:
    """Steam API'leri ile iletişimi yönetir."""
    def __init__(self, config: Config):
        self.config = config

    def get_price_info(self, app_id: int) -> Optional[Dict[str, Any]]:
        """Bir oyunun fiyat bilgisini çeker."""
        params = {'appids': app_id, 'cc': self.config.TARGET_COUNTRY}
        try:
            response = requests.get(self.config.STEAM_APP_DETAILS_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json().get(str(app_id))
            if not data or not data.get('success'): return None

            if data['data'].get('is_free') or 'price_overview' not in data['data']:
                return {'currency': 'N/A', 'initial': 0, 'final': 0, 'discount': 0}

            price = data['data']['price_overview']
            return {'currency': price.get('currency'), 'initial': price.get('initial'), 'final': price.get('final'),
                    'discount': price.get('discount_percent')}
        except requests.RequestException as e:
            print(f"HATA: Steam fiyat bilgisi çekilemedi (AppID: {app_id}): {e}")
            return None


def handle_date_dimension(cursor: sqlite3.Cursor, ts: int) -> int:
    """Tarih bilgisini DimDate'e ekler veya mevcutsa ID'sini döner."""
    dt = datetime.fromtimestamp(ts)
    date_id = int(dt.strftime('%Y%m%d'))
    cursor.execute("INSERT OR IGNORE INTO DimDate (date_id, full_date, year, month, day) VALUES (?, ?, ?, ?, ?)",
                   (date_id, dt.date(), dt.year, dt.month, dt.day))
    return date_id


# =========================================================================
# 3. ANA İŞ MANTIĞI
# =========================================================================
def track_daily_prices(config: Config):
    """Veritabanındaki oyunların günlük fiyatlarını çeker ve kaydeder."""
    db_manager = DatabaseManager(config.DB_NAME)
    steam_client = SteamClient(config)

    # Önce gerekli tabloların var olduğundan emin ol
    with db_manager as cursor:
        DatabaseManager.setup_price_history_table(cursor)

    # Takip edilecek oyunları al (Sadece Steam'de olanları)
    games_to_track: List[tuple] = []
    with db_manager as cursor:
        cursor.execute("SELECT game_id, steam_app_id, name FROM DimGames WHERE steam_app_id IS NOT NULL")
        games_to_track = cursor.fetchall()

    if not games_to_track:
        print("Veritabanında takip edilecek Steam oyunu bulunamadı. Lütfen önce `1_initial_data_loader.py` betiğini çalıştırın.")
        return

    total_games = len(games_to_track)
    print(f"Toplam {total_games} oyun için günlük fiyatlar takip edilecek...")

    for i, (game_id, steam_app_id, name) in enumerate(games_to_track):
        print(f"\n[{i + 1}/{total_games}] Fiyat çekiliyor: {name} (App ID: {steam_app_id})")
        price_info = steam_client.get_price_info(steam_app_id)

        if price_info:
            with db_manager as cursor:
                today_id = handle_date_dimension(cursor, int(time.time()))
                cursor.execute("""
                    INSERT OR REPLACE INTO FactPriceHistory (
                        game_id, date_id, price_currency, price_initial, price_final, discount_percent
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (game_id, today_id, price_info.get('currency'), price_info.get('initial'),
                      price_info.get('final'), price_info.get('discount')))

                final_price = price_info.get('final', 0) / 100
                print(f"Fiyat kaydedildi: {final_price:.2f} {price_info.get('currency')}")
        else:
            print("Fiyat bilgisi alınamadı, bu oyun atlanıyor.")

        # API'ye çok sık istek atmamak için bekle
        time.sleep(1.5)


# =========================================================================
# 4. PROGRAM GİRİŞ NOKTASI
# =========================================================================
def main():
    """Ana program akışını yönetir."""
    print("--- Günlük Fiyat Takip Betiği Başlatıldı ---")
    config = Config()

    # Ortam değişkeni kontrolü
    if not config.STEAM_API_KEY:
        print("KRİTİK HATA: Lütfen ortam değişkeni olarak STEAM_API_KEY'i ayarlayın. Program çalıştırılamadı.")
        return

    try:
        track_daily_prices(config)
    except Exception as e:
        print(f"Program çalışırken beklenmedik bir hata oluştu: {e}")

    print("\n--- Fiyat Takip İşlemi Tamamlandı ---")


if __name__ == "__main__":
    main()