# 1_initial_data_loader.py

import requests
import sqlite3
import time
import os
from datetime import datetime
from typing import List, Dict, Any, Optional


# =========================================================================
# 1. YAPILANDIRMA (CONFIGURATION)
# =========================================================================
class Config:
    """Uygulama yapılandırmasını ve sabitleri barındırır."""
    # Güvenli Yöntem: API anahtarlarını ortam değişkenlerinden oku.
    # Eğer ortam değişkeni yoksa, koddaki güvensiz değeri kullanır.
    TWITCH_CLIENT_ID = "biy8wy461l3w5ed99cnto60apneme3"
    TWITCH_CLIENT_SECRET = "3ohwxlmcho7xpf4s9rsy3vxgf8dzkb"
    STEAM_API_KEY = "EF38F5976C52F832D267CA05535C61F1"

    DB_NAME: str = "all_game.db"
    TARGET_COUNTRY: str = "TR"
    GAME_FETCH_LIMIT: int = 3000
    GAMES_PER_PAGE: int = 100

    # API Uç Noktaları
    TWITCH_AUTH_URL: str = "https://id.twitch.tv/oauth2/token"
    IGDB_API_URL: str = "https://api.igdb.com/v4/"
    STEAM_APP_DETAILS_URL: str = "https://store.steampowered.com/api/appdetails"
    STEAM_PLAYERS_URL: str = "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"
    STEAM_REVIEWS_URL: str = "https://store.steampowered.com/appreviews/{appid}?json=1"


# =========================================================================
# 2. VERİTABANI YÖNETİCİSİ (DATABASE MANAGER)
# =========================================================================
class DatabaseManager:
    """SQLite veritabanı bağlantısını ve işlemlerini yönetir."""

    def __init__(self, db_name: str):
        self.db_name = db_name
        self.conn: Optional[sqlite3.Connection] = None

    def __enter__(self):
        self.conn = sqlite3.connect(self.db_name)
        self.conn.execute("PRAGMA foreign_keys = ON;")
        return self.conn.cursor()

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            if exc_type is None: self.conn.commit()
            self.conn.close()

    @staticmethod
    def setup_schema(cursor: sqlite3.Cursor) -> None:
        """Veritabanı şemasını oluşturur."""
        schema_queries = [
            "CREATE TABLE IF NOT EXISTS DimDevelopers (developer_id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);",
            "CREATE TABLE IF NOT EXISTS DimPublishers (publisher_id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);",
            "CREATE TABLE IF NOT EXISTS DimGenres (genre_id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);",
            "CREATE TABLE IF NOT EXISTS DimDate (date_id INTEGER PRIMARY KEY, full_date DATE NOT NULL, year INTEGER NOT NULL, month INTEGER NOT NULL, day INTEGER NOT NULL);",
            """CREATE TABLE IF NOT EXISTS DimGames
            (
                game_id
                INTEGER
                PRIMARY
                KEY,
                steam_app_id
                INTEGER
                UNIQUE,
                name
                TEXT
                NOT
                NULL,
                summary
                TEXT,
                cover_url
                TEXT,
                release_date_id
                INTEGER,
                developer_id
                INTEGER,
                publisher_id
                INTEGER,
                price_currency
                TEXT,
                price_initial
                INTEGER,
                price_final
                INTEGER,
                discount_percent
                INTEGER,
                FOREIGN
                KEY
               (
                release_date_id
               ) REFERENCES DimDate
               (
                   date_id
               ),
                FOREIGN KEY
               (
                   developer_id
               ) REFERENCES DimDevelopers
               (
                   developer_id
               ),
                FOREIGN KEY
               (
                   publisher_id
               ) REFERENCES DimPublishers
               (
                   publisher_id
               )
                );""",
            """CREATE TABLE IF NOT EXISTS GameGenres
            (
                game_id
                INTEGER,
                genre_id
                INTEGER,
                PRIMARY
                KEY
               (
                game_id,
                genre_id
               ),
                FOREIGN KEY
               (
                   game_id
               ) REFERENCES DimGames
               (
                   game_id
               ), FOREIGN KEY
               (
                   genre_id
               ) REFERENCES DimGenres
               (
                   genre_id
               )
                );""",
            """CREATE TABLE IF NOT EXISTS FactGameStats
            (
                stats_id
                INTEGER
                PRIMARY
                KEY,
                game_id
                INTEGER
                NOT
                NULL,
                date_id
                INTEGER
                NOT
                NULL,
                steam_player_count
                INTEGER,
                steam_positive_reviews
                INTEGER,
                steam_negative_reviews
                INTEGER,
                UNIQUE
               (
                game_id,
                date_id
               ),
                FOREIGN KEY
               (
                   game_id
               ) REFERENCES DimGames
               (
                   game_id
               ), FOREIGN KEY
               (
                   date_id
               ) REFERENCES DimDate
               (
                   date_id
               )
                );"""
        ]
        for query in schema_queries:
            cursor.execute(query)



# =========================================================================
# 3. API İSTEMCİLERİ (API CLIENTS)
# =========================================================================
class IGDBClient:
    """IGDB API'si ile iletişimi yönetir."""

    def __init__(self, config: Config):
        self.config = config
        self.access_token = self._get_access_token()

    def _get_access_token(self) -> Optional[str]:
        if not self.config.TWITCH_CLIENT_ID or not self.config.TWITCH_CLIENT_SECRET:
            return None
        params = {'client_id': self.config.TWITCH_CLIENT_ID, 'client_secret': self.config.TWITCH_CLIENT_SECRET,
                  'grant_type': 'client_credentials'}
        try:
            response = requests.post(self.config.TWITCH_AUTH_URL, data=params)
            response.raise_for_status()
            return response.json().get('access_token')
        except requests.RequestException as e:
            return None

    def fetch_games(self) -> List[Dict[str, Any]]:
        """IGDB'den oyunları sayfalama yaparak çeker."""
        if not self.access_token: return []
        all_games, offset = [], 0
        headers = {'Client-ID': self.config.TWITCH_CLIENT_ID, 'Authorization': f'Bearer {self.access_token}'}

        while len(all_games) < self.config.GAME_FETCH_LIMIT:
            query = f"""
                fields name, summary, cover.url, first_release_date, genres.name, 
                       involved_companies.developer, involved_companies.publisher, involved_companies.company.name,
                       websites.url, websites.category;
                where platforms = (6, 167, 169, 48, 49) & category = 0;
                sort popularity desc; limit {self.config.GAMES_PER_PAGE}; offset {offset};
            """
            try:
                response = requests.post(f"{self.config.IGDB_API_URL}games", headers=headers, data=query)
                response.raise_for_status()
                batch = response.json()
                if not batch: break
                all_games.extend(batch)
                offset += self.config.GAMES_PER_PAGE
                time.sleep(0.5)
            except requests.RequestException as e:
                break
        return all_games[:self.config.GAME_FETCH_LIMIT]


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
        except requests.RequestException:
            return None

    def get_game_stats(self, app_id: int) -> Optional[Dict[str, int]]:
        """Bir oyunun oyuncu ve inceleme sayılarını çeker."""
        stats = {}
        try:
            player_res = requests.get(self.config.STEAM_PLAYERS_URL,
                                      params={'key': self.config.STEAM_API_KEY, 'appid': app_id}, timeout=10)
            if player_res.ok: stats['player_count'] = player_res.json().get('response', {}).get('player_count', 0)
            review_res = requests.get(self.config.STEAM_REVIEWS_URL.format(appid=app_id), params={'language': 'all'},
                                      timeout=10)
            if review_res.ok:
                summary = review_res.json().get('query_summary', {})
                stats['positive_reviews'], stats['negative_reviews'] = summary.get('total_positive', 0), summary.get(
                    'total_negative', 0)
            return stats
        except requests.RequestException:
            return None


# =========================================================================
# 4. VERİ İŞLEYİCİ (DATA PROCESSOR)
# =========================================================================
class DataProcessor:
    """Veritabanı ve API istemcilerini kullanarak oyun verilerini işler."""

    def __init__(self, db_manager: DatabaseManager, steam_client: SteamClient):
        self.db = db_manager
        self.steam = steam_client

    def process_and_save_game(self, game_data: Dict[str, Any]) -> None:
        """Tek bir oyunu alır, işler ve veritabanına kaydeder."""
        game_id = game_data.get('id')
        game_name = game_data.get('name', 'Bilinmeyen Oyun')

        with self.db as cursor:
            dev_id, pub_id = self._process_companies(cursor, game_data.get('involved_companies', []))
            release_date_id = self._handle_date(cursor, game_data.get('first_release_date'))
            steam_app_id = self._find_steam_app_id(game_data.get('websites', []))

            price_info, stats_info = None, None
            if steam_app_id:
                price_info = self.steam.get_price_info(steam_app_id)
                time.sleep(1)
                stats_info = self.steam.get_game_stats(steam_app_id)
            else:

            self._update_dim_games(cursor, game_data, steam_app_id, release_date_id, dev_id, pub_id, price_info)
            self._update_genres(cursor, game_id, game_data.get('genres', []))
            if steam_app_id and stats_info:
                self._update_fact_stats(cursor, game_id, stats_info)

    def _get_or_create_dimension(self, cursor: sqlite3.Cursor, table: str, name: str) -> Optional[int]:
        if not name: return None
        cursor.execute(f"SELECT {table}_id FROM Dim{table}s WHERE name = ?", (name,))
        result = cursor.fetchone()
        if result: return result[0]
        cursor.execute(f"INSERT INTO Dim{table}s (name) VALUES (?)", (name,))
        return cursor.lastrowid

    def _process_companies(self, cursor: sqlite3.Cursor, companies: List[Dict[str, Any]]) -> (Optional[int],
                                                                                              Optional[int]):
        dev_name, pub_name = None, None
        for company in companies:
            if company.get('developer'): dev_name = company.get('company', {}).get('name')
            if company.get('publisher'): pub_name = company.get('company', {}).get('name')
        return self._get_or_create_dimension(cursor, 'Developer', dev_name), self._get_or_create_dimension(cursor,
                                                                                                           'Publisher',
                                                                                                           pub_name)

    def _handle_date(self, cursor: sqlite3.Cursor, ts: Optional[int]) -> Optional[int]:
        if not ts: return None
        dt = datetime.fromtimestamp(ts)
        date_id = int(dt.strftime('%Y%m%d'))
        cursor.execute("INSERT OR IGNORE INTO DimDate (date_id, full_date, year, month, day) VALUES (?, ?, ?, ?, ?)",
                       (date_id, dt.date(), dt.year, dt.month, dt.day))
        return date_id

    def _find_steam_app_id(self, websites: List[Dict[str, Any]]) -> Optional[int]:
        for site in websites:
            if site.get('category') == 13 and 'store.steampowered.com/app/' in site.get('url', ''):
                try:
                    return int(site['url'].split('/app/')[1].split('/')[0])
                except (IndexError, ValueError):
                    continue
        return None

    def _update_dim_games(self, cursor, game_data, steam_id, release_id, dev_id, pub_id, price_info):
        """DimGames tablosuna bir oyunun verilerini ekler veya günceller."""
        game_details = {
            "game_id": game_data.get('id'), "steam_app_id": steam_id,
            "name": game_data.get('name', 'Bilinmeyen Oyun'), "summary": game_data.get('summary', 'Özet mevcut değil.'),
            "cover_url": game_data.get('cover', {}).get('url', '').replace('t_thumb', 't_cover_big'),
            "release_date_id": release_id, "developer_id": dev_id, "publisher_id": pub_id,
            "price_currency": price_info.get('currency') if price_info else None,
            "price_initial": price_info.get('initial') if price_info else None,
            "price_final": price_info.get('final') if price_info else None,
            "discount_percent": price_info.get('discount') if price_info else None,
        }
        sql_query = """
            INSERT OR REPLACE INTO DimGames (
                game_id, steam_app_id, name, summary, cover_url, release_date_id, developer_id, publisher_id,
                price_currency, price_initial, price_final, discount_percent
            ) VALUES (
                :game_id, :steam_app_id, :name, :summary, :cover_url, :release_date_id, :developer_id, :publisher_id,
                :price_currency, :price_initial, :price_final, :discount_percent
            )"""
        cursor.execute(sql_query, game_details)

    def _update_genres(self, cursor, game_id, genres):
        for genre in genres:
            genre_name = genre.get('name')
            if genre_name:
                genre_id = self._get_or_create_dimension(cursor, 'Genre', genre_name)
                if genre_id: cursor.execute("INSERT OR IGNORE INTO GameGenres (game_id, genre_id) VALUES (?, ?)",
                                            (game_id, genre_id))

    def _update_fact_stats(self, cursor, game_id, stats_info):
        """FactGameStats tablosuna günlük istatistikleri ekler."""
        today_id = self._handle_date(cursor, int(time.time()))
        cursor.execute("""
            INSERT OR REPLACE INTO FactGameStats 
                (game_id, date_id, steam_player_count, steam_positive_reviews, steam_negative_reviews)
            VALUES (?, ?, ?, ?, ?)""",
                       (game_id, today_id, stats_info.get('player_count'),
                        stats_info.get('positive_reviews'), stats_info.get('negative_reviews'))
                       )


# =========================================================================
# 5. ANA ÇALIŞTIRMA BLOĞU (MAIN EXECUTION)
# =========================================================================
def main():
    """Ana program akışını yönetir."""
    config = Config()

    if not all([config.TWITCH_CLIENT_ID, config.TWITCH_CLIENT_SECRET, config.STEAM_API_KEY]):
        return

    db_manager = DatabaseManager(config.DB_NAME)

    with db_manager as cursor:
        db_manager.setup_schema(cursor)

    igdb_client = IGDBClient(config)
    steam_client = SteamClient(config)
    processor = DataProcessor(db_manager, steam_client)

    games = igdb_client.fetch_games()

    if not games:
        return

    total_games = len(games)

    for i, game in enumerate(games):
        try:
            processor.process_and_save_game(game)
        except Exception as e:


if __name__ == "__main__":
    main()
