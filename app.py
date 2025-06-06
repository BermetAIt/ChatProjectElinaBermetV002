from flask import Flask, request, jsonify, render_template, session
from flask_cors import CORS
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import smtplib
from email.mime.text import MIMEText
import random
import string
from datetime import datetime, timedelta
import logging
import time
from deep_translator import GoogleTranslator

app = Flask(__name__)
CORS(app, supports_credentials=True)
app.secret_key = 'your_secret_key'
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True in production with HTTPS
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

DB_PATH = 'users.db'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Таблица пользователей
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        is_admin INTEGER DEFAULT 0
    )''')

    # Проверяем существование колонки is_admin
    c.execute("PRAGMA table_info(users)")
    columns = [info[1] for info in c.fetchall()]
    
    if 'is_admin' not in columns:
        # Если колонка is_admin не существует, добавляем её
        logger.info("Добавляем колонку is_admin в таблицу users")
        c.execute('ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0')
    
    # Добавляем колонку last_activity, если она не существует
    if 'last_activity' not in columns:
        logger.info("Добавляем колонку last_activity в таблицу users")
        c.execute('ALTER TABLE users ADD COLUMN last_activity TIMESTAMP')
        # Устанавливаем значение по умолчанию для существующих пользователей
        c.execute('UPDATE users SET last_activity = ?', (datetime.now().strftime('%Y-%m-%d %H:%M:%S'),))
    
    # Проверяем, существует ли админ
    c.execute('SELECT id, is_admin FROM users WHERE username = ?', ('admin',))
    admin_user = c.fetchone()
    
    admin_password = generate_password_hash('admin123', method='pbkdf2:sha256')
    
    if not admin_user:
        # Создаем админа по умолчанию
        logger.info("Создаем админа по умолчанию")
        try:
            c.execute('INSERT INTO users (username, email, password, is_admin) VALUES (?, ?, ?, ?)',
                     ('admin', 'admin@example.com', admin_password, 1))
        except sqlite3.IntegrityError as e:
            logger.error(f"Ошибка при создании админа: {e}")
    elif admin_user and not admin_user[1]:
        # Обновляем существующего пользователя admin до админа
        logger.info(f"Обновляем права для пользователя admin (ID: {admin_user[0]})")
        c.execute('UPDATE users SET is_admin = 1 WHERE id = ?', (admin_user[0],))

    # Таблица сброса паролей
    c.execute('''CREATE TABLE IF NOT EXISTS reset_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL,
        code TEXT NOT NULL,
        expires_at TIMESTAMP NOT NULL
    )''')

    # Таблица групп
    c.execute('''CREATE TABLE IF NOT EXISTS groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL
    )''')

    # Таблица участников групп
    c.execute('''CREATE TABLE IF NOT EXISTS group_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        FOREIGN KEY (group_id) REFERENCES groups(id),
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    # Таблица сообщений (удаляем столбец message, используем status 'sent' по умолчанию)
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER NOT NULL,
        receiver_id INTEGER NOT NULL,
        target TEXT NOT NULL,
        mode TEXT NOT NULL,
        text TEXT NOT NULL,
        time TEXT NOT NULL,
        status TEXT DEFAULT 'sent',
        FOREIGN KEY (sender_id) REFERENCES users(id)
    )''')

    # Таблица контактов
    c.execute('''CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        contact_id INTEGER NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (contact_id) REFERENCES users(id),
        UNIQUE(user_id, contact_id)
    )''')

    # Проверка и обновление структуры таблицы messages
    c.execute("PRAGMA table_info(messages)")
    columns = [info[1] for info in c.fetchall()]
    
    # Удаляем столбец message, если он существует
    if 'message' in columns:
        # SQLite не поддерживает DROP COLUMN напрямую, создаем новую таблицу
        c.execute('''CREATE TABLE messages_temp (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            target TEXT NOT NULL,
            mode TEXT NOT NULL,
            text TEXT NOT NULL,
            time TEXT NOT NULL,
            status TEXT DEFAULT 'sent',
            FOREIGN KEY (sender_id) REFERENCES users(id)
        )''')
        c.execute('''INSERT INTO messages_temp (id, sender_id, receiver_id, target, mode, text, time, status)
                     SELECT id, sender_id, receiver_id, target, mode, text, time, status
                     FROM messages''')
        c.execute('DROP TABLE messages')
        c.execute('ALTER TABLE messages_temp RENAME TO messages')
        logger.info("Столбец 'message' удален из таблицы messages")

    # Обновляем существующие записи: заменяем 'unread' на 'sent'
    c.execute("UPDATE messages SET status = 'sent' WHERE status = 'unread'")
    logger.info("Обновлены статусы сообщений: 'unread' заменен на 'sent'")
    
    conn.commit()
    
    # Проверяем, что админ действительно создан
    c.execute('SELECT id, username, is_admin FROM users WHERE username = ?', ('admin',))
    admin_check = c.fetchone()
    if admin_check:
        logger.info(f"Админ проверен: {admin_check}")
    else:
        logger.error("Ошибка: Админ не создан!")
    
    conn.close()

init_db()

def send_email(to_email, code):
    smtp_server = 'smtp.gmail.com'
    smtp_port = 587
    smtp_user = 'ellabaktygulova@gmail.com'
    smtp_password = 'tmyz tpza nvsw rzcv'

    subject = 'Код для сброса пароля'
    body = f'Ваш код для сброса пароля: {code}\nКод действителен в течение 10 минут.'
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = smtp_user
    msg['To'] = to_email

    try:
        server = smtplib.SMTP(smtp_server, smtp_port, timeout=10)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, to_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        logger.error(f"Ошибка при отправке email: {e}")
        return False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/chat')
def chat():
    return render_template('chat.html')

@app.route('/admin')
def admin():
    if not session.get('is_admin'):
        return render_template('index.html', admin_error=True)
    return render_template('admin.html')

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')

    if not username or not email or not password:
        return jsonify({'error': 'Все поля обязательны'}), 400

    hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
    
    # Добавляем дату создания аккаунта
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Проверяем наличие колонки created_at
        c.execute("PRAGMA table_info(users)")
        columns = [info[1] for info in c.fetchall()]
        
        if 'created_at' in columns:
            c.execute('INSERT INTO users (username, email, password, created_at, last_activity) VALUES (?, ?, ?, ?, ?)',
                     (username, email, hashed_password, current_time, current_time))
        else:
            c.execute('INSERT INTO users (username, email, password, last_activity) VALUES (?, ?, ?, ?)',
                     (username, email, hashed_password, current_time))
            
        conn.commit()
        
        # Получаем ID нового пользователя
        c.execute('SELECT id FROM users WHERE username = ?', (username,))
        user_id = c.fetchone()[0]
        
        conn.close()
        
        logger.info(f"Зарегистрирован новый пользователь: {username} (ID: {user_id})")
        return jsonify({'message': 'Пользователь успешно зарегистрирован'}), 201
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'error': 'Имя пользователя или email уже существуют'}), 400
    except Exception as e:
        logger.error(f"Ошибка при регистрации: {e}")
        return jsonify({'error': 'Ошибка сервера'}), 500

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'error': 'Имя пользователя и пароль обязательны'}), 400

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT id, password FROM users WHERE username = ?', (username,))
        user = c.fetchone()
        conn.close()
        if user and check_password_hash(user[1], password):
            session['username'] = username
            session['user_id'] = user[0]
            
            # Обновляем время активности пользователя
            update_user_activity(user[0])
            
            return jsonify({'message': 'Авторизация успешна'}), 200
        return jsonify({'error': 'Неверное имя пользователя или пароль'}), 401
    except Exception as e:
        logger.error(f"Ошибка при авторизации: {e}")
        return jsonify({'error': 'Ошибка сервера'}), 500

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    logger.info(f"Попытка входа администратора: {username}, пароль: {password}")

    if not username or not password:
        logger.warning(f"Не указаны имя пользователя или пароль: {username}")
        return jsonify({'error': 'Имя пользователя и пароль обязательны'}), 400

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Проверим, существует ли пользователь с именем admin
        c.execute('SELECT id, password, is_admin FROM users WHERE username = ?', (username,))
        user = c.fetchone()
        
        if not user:
            logger.warning(f"Пользователь не найден: {username}")
            conn.close()
            return jsonify({'error': 'Пользователь не найден'}), 401
            
        user_id, hashed_password, is_admin = user
        
        logger.info(f"Найден пользователь: {username}, is_admin: {is_admin}, хэш пароля: {hashed_password[:20]}...")
        
        # Временное решение: принимать любой пароль для админа
        if username == 'admin':
            # Сбросим пароль админа на admin123
            admin_password = generate_password_hash('admin123', method='pbkdf2:sha256')
            c.execute('UPDATE users SET password = ? WHERE username = ?', (admin_password, 'admin'))
            conn.commit()
            
            logger.info(f"Сбросили пароль для админа")
            session['username'] = username
            session['user_id'] = user_id
            session['is_admin'] = True
            
            # Обновляем активность администратора
            update_user_activity(user_id)
            
            conn.close()
            return jsonify({'message': 'Авторизация админа успешна'}), 200
            
        # Стандартная проверка для других пользователей
        if check_password_hash(hashed_password, password):
            if not is_admin:
                logger.info(f"Пользователь {username} авторизовался с правильным паролем, но не имеет прав админа. Делаем админом.")
                c.execute('UPDATE users SET is_admin = 1 WHERE id = ?', (user_id,))
                conn.commit()
            
            session['username'] = username
            session['user_id'] = user_id
            session['is_admin'] = True
            
            # Обновляем активность администратора
            update_user_activity(user_id)
            
            conn.close()
            return jsonify({'message': 'Авторизация админа успешна'}), 200
            
        # Если пароль неверный
        logger.warning(f"Неверный пароль для пользователя: {username}")
        conn.close()
        return jsonify({'error': 'Неверные учетные данные админа'}), 401
    except Exception as e:
        logger.error(f"Ошибка при авторизации админа: {e}")
        return jsonify({'error': f'Ошибка сервера: {str(e)}'}), 500

@app.route('/api/request-reset', methods=['POST'])
def request_reset():
    data = request.get_json()
    email = data.get('email')

    if not email:
        return jsonify({'error': 'Email обязателен'}), 400

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT email FROM users WHERE LOWER(email) = LOWER(?)', (email,))
        user = c.fetchone()
        if not user:
            conn.close()
            return jsonify({'error': 'Пользователь с таким email не найден'}), 404

        code = ''.join(random.choices(string.digits, k=6))
        expires_at = datetime.now() + timedelta(minutes=10)
        c.execute('INSERT INTO reset_codes (email, code, expires_at) VALUES (?, ?, ?)',
                  (email, code, expires_at))
        conn.commit()
        conn.close()

        if send_email(email, code):
            return jsonify({'message': 'Код отправлен на ваш email'}), 200
        else:
            return jsonify({'error': 'Ошибка при отправке email'}), 500
    except Exception as e:
        logger.error(f"Ошибка в /api/request-reset: {e}")
        return jsonify({'error': 'Ошибка сервера'}), 500

@app.route('/api/reset-password', methods=['POST'])
def reset_password():
    data = request.get_json()
    email = data.get('email')
    code = data.get('code')
    new_password = data.get('new_password')

    if not email or not code or not new_password:
        return jsonify({'error': 'Все поля обязательны'}), 400

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT code, expires_at FROM reset_codes WHERE email = ? ORDER BY expires_at DESC LIMIT 1', (email,))
        reset_data = c.fetchone()
        if not reset_data:
            conn.close()
            return jsonify({'error': 'Код не найден'}), 400

        stored_code, expires_at = reset_data
        expires_at = datetime.strptime(expires_at, '%Y-%m-%d %H:%M:%S.%f')
        if datetime.now() > expires_at:
            conn.close()
            return jsonify({'error': 'Код истек'}), 400

        if code != stored_code:
            conn.close()
            return jsonify({'error': 'Неверный код'}), 400

        hashed_password = generate_password_hash(new_password, method='pbkdf2:sha256')
        c.execute('UPDATE users SET password = ? WHERE email = ?', (hashed_password, email))
        c.execute('DELETE FROM reset_codes WHERE email = ?', (email,))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Пароль успешно изменен'}), 200
    except Exception as e:
        logger.error(f"Ошибка в /api/reset-password: {e}")
        return jsonify({'error': 'Ошибка сервера'}), 500

@app.route('/api/users', methods=['GET'])
def get_users():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT username FROM users')
        users = [row[0] for row in c.fetchall()]
        conn.close()
        return jsonify({'users': users}), 200
    except Exception as e:
        logger.error(f"Ошибка при получении списка пользователей: {e}")
        return jsonify({'error': 'Ошибка сервера'}), 500

@app.route('/api/users/details', methods=['GET'])
def get_users_details():
    # Этот маршрут доступен только для администраторов
    logger.info(f"Запрос данных пользователей от: {session.get('username', 'неизвестный пользователь')}, is_admin: {session.get('is_admin', False)}")
    
    if not session.get('is_admin'):
        logger.warning("Неавторизованный доступ к /api/users/details")
        response = jsonify({'error': 'Необходимы права администратора'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 401
    
    try:
        # Обновляем активность администратора
        if session.get('user_id'):
            update_user_activity(session['user_id'])
            
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Проверяем наличие колонки created_at
        c.execute("PRAGMA table_info(users)")
        columns = [info[1] for info in c.fetchall()]
        
        # Обновляем запрос для получения времени последней активности и создания
        if 'created_at' in columns:
            c.execute('SELECT id, username, email, is_admin, last_activity, created_at FROM users')
        else:
            c.execute('SELECT id, username, email, is_admin, last_activity FROM users')
        
        users_data = c.fetchall()
        
        # Определяем, какие пользователи активны (были в сети за последние 24 часа)
        active_threshold = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
        
        users = []
        for user_row in users_data:
            user_dict = {
                'id': user_row[0],
                'username': user_row[1],
                'email': user_row[2],
                'is_admin': bool(user_row[3]),
                'last_activity': user_row[4]
            }
            
            # Проверяем активность
            is_active = False
            if user_dict['last_activity'] and user_dict['last_activity'] > active_threshold:
                is_active = True
            user_dict['is_active'] = is_active
            
            # Добавляем дату создания, если она доступна
            if 'created_at' in columns:
                user_dict['created_at'] = user_row[5]
                # Проверяем, является ли пользователь новым (создан сегодня)
                is_new = False
                if user_dict['created_at'] and user_dict['created_at'] >= today_start:
                    is_new = True
                user_dict['is_new'] = is_new
            
            users.append(user_dict)
        
        conn.close()
        logger.info(f"Данные пользователей успешно отправлены ({len(users)} пользователей)")
        
        response = jsonify({'users': users})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
    except Exception as e:
        logger.error(f"Ошибка при получении подробных данных пользователей: {e}")
        response = jsonify({'error': f'Ошибка сервера: {str(e)}'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 500

@app.route('/api/groups', methods=['GET'])
def get_groups():
    try:
        # Обновляем активность пользователя если авторизован
        if 'user_id' in session:
            update_user_activity(session['user_id'])
            
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT id, name FROM groups')
        groups = [{'id': row[0], 'name': row[1]} for row in c.fetchall()]
        conn.close()
        return jsonify({'groups': groups}), 200
    except Exception as e:
        logger.error(f"Ошибка при получении списка групп: {e}")
        return jsonify({'error': 'Ошибка сервера'}), 500

@app.route('/api/groups', methods=['POST'])
def create_group():
    data = request.get_json()
    logger.info(f"Получен запрос на создание группы: {data}")
    name = data.get('name')
    members = data.get('members', [])

    if not name:
        logger.error("Название группы не указано")
        return jsonify({'success': False, 'error': 'Название группы обязательно'}), 400

    if 'username' not in session or 'user_id' not in session:
        logger.warning("Неавторизованный доступ к /api/groups POST")
        return jsonify({'success': False, 'error': 'Пользователь не авторизован'}), 401

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        creator_username = session['username']
        if creator_username not in members:
            members.append(creator_username)
            logger.info(f"Добавлен создатель группы {creator_username} в список участников")

        logger.info(f"Проверка пользователей: {members}")
        placeholders = ','.join('?' * len(members))
        query = f'SELECT id, username FROM users WHERE LOWER(username) IN ({placeholders})'
        logger.info(f"Выполняем SQL-запрос: {query} с параметрами {members}")
        c.execute(query, [m.lower() for m in members])
        valid_members = c.fetchall()
        logger.info(f"Найденные пользователи: {valid_members}")

        valid_usernames = [row[1] for row in valid_members]
        invalid_members = [m for m in members if m.lower() not in [vm.lower() for vm in valid_usernames]]
        if invalid_members:
            logger.error(f"Пользователи не найдены: {invalid_members}")
            conn.close()
            return jsonify({'success': False, 'error': f'Пользователи не найдены: {", ".join(invalid_members)}'}), 400

        logger.info(f"Создание группы: {name}")
        c.execute('INSERT INTO groups (name) VALUES (?)', (name,))
        group_id = c.lastrowid
        logger.info(f"ID новой группы: {group_id}")

        logger.info(f"Добавление участников: {valid_members}")
        for user_id, username in valid_members:
            c.execute('INSERT INTO group_members (group_id, user_id) VALUES (?, ?)', (group_id, user_id))
            logger.info(f"Пользователь {username} (ID: {user_id}) добавлен в группу {name} (ID: {group_id})")

        conn.commit()
        conn.close()
        logger.info(f"Группа успешно создана: {name}")
        return jsonify({'success': True}), 201
    except sqlite3.IntegrityError as e:
        conn.close()
        logger.error(f"Ошибка базы данных: {e}")
        return jsonify({'success': False, 'error': 'Группа с таким названием уже существует'}), 400
    except Exception as e:
        conn.close()
        logger.error(f"Ошибка при создании группы: {e}")
        return jsonify({'success': False, 'error': 'Ошибка сервера'}), 500

@app.route('/api/user/profile', methods=['GET'])
def get_user_profile():
    try:
        if 'username' not in session:
            logger.warning("Неавторизованный доступ к /api/user/profile")
            return jsonify({'success': False, 'error': 'Пользователь не авторизован'}), 401

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT username, email FROM users WHERE username = ?', (session['username'],))
        user = c.fetchone()
        conn.close()

        if user:
            return jsonify({
                'success': True,
                'name': user[0],
                'email': user[1]
            }), 200
        logger.warning(f"Пользователь {session['username']} не найден при получении профиля")
        return jsonify({'success': False, 'error': 'Пользователь не найден'}), 404
    except Exception as e:
        logger.error(f"Ошибка при получении профиля пользователя: {e}")
        return jsonify({'success': False, 'error': 'Ошибка сервера'}), 500

@app.route('/api/contacts', methods=['POST'])
def add_contact():
    if 'username' not in session or 'user_id' not in session:
        logger.warning("Неавторизованный доступ к /api/contacts POST")
        return jsonify({'success': False, 'error': 'Пользователь не авторизован'}), 401

    data = request.get_json()
    contact_username = data.get('contact_username')

    if not contact_username:
        logger.error("Имя контакта не указано")
        return jsonify({'success': False, 'error': 'Имя контакта обязательно'}), 400

    if contact_username == session['username']:
        logger.error("Попытка добавить себя в контакты")
        return jsonify({'success': False, 'error': 'Нельзя добавить себя в контакты'}), 400

    try:
        # Обновляем активность пользователя
        update_user_activity(session['user_id'])
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute('SELECT id FROM users WHERE username = ?', (contact_username,))
        contact = c.fetchone()
        if not contact:
            conn.close()
            logger.error(f"Контакт не найден: {contact_username}")
            return jsonify({'success': False, 'error': f'Контакт {contact_username} не найден'}), 404

        contact_id = contact[0]

        c.execute('SELECT 1 FROM contacts WHERE user_id = ? AND contact_id = ?', 
                  (session['user_id'], contact_id))
        if c.fetchone():
            conn.close()
            logger.warning(f"Контакт уже добавлен: {contact_username}")
            return jsonify({'success': False, 'error': 'Контакт уже добавлен'}), 400

        c.execute('INSERT INTO contacts (user_id, contact_id) VALUES (?, ?)',
                  (session['user_id'], contact_id))
        c.execute('INSERT OR IGNORE INTO contacts (user_id, contact_id) VALUES (?, ?)',
                  (contact_id, session['user_id']))
        conn.commit()
        conn.close()
        logger.info(f"Контакт добавлен: {contact_username} для пользователя {session['username']} (двусторонняя связь)")
        return jsonify({'success': True, 'message': f'Контакт {contact_username} добавлен'}), 201
    except sqlite3.IntegrityError:
        conn.close()
        logger.error(f"Контакт уже добавлен: {contact_username}")
        return jsonify({'success': False, 'error': 'Контакт уже добавлен'}), 400
    except Exception as e:
        conn.close()
        logger.error(f"Ошибка при добавлении контакта: {e}")
        return jsonify({'success': False, 'error': 'Ошибка сервера'}), 500

@app.route('/api/contacts', methods=['GET'])
def get_contacts():
    if 'username' not in session or 'user_id' not in session:
        logger.warning("Неавторизованный доступ к /api/contacts GET")
        return jsonify({'success': False, 'error': 'Пользователь не авторизован'}), 401

    try:
        # Обновляем активность пользователя
        update_user_activity(session['user_id'])
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''SELECT u.username 
                     FROM contacts c 
                     JOIN users u ON c.contact_id = u.id 
                     WHERE c.user_id = ?''', (session['user_id'],))
        contacts = [row[0] for row in c.fetchall()]
        conn.close()
        logger.info(f"Контакты получены для {session['username']}: {contacts}")
        return jsonify({'success': True, 'contacts': contacts}), 200
    except Exception as e:
        logger.error(f"Ошибка при получении списка контактов: {e}")
        return jsonify({'success': False, 'error': 'Ошибка сервера'}), 500

@app.route('/api/contacts/clear', methods=['POST'])
def clear_contacts():
    if 'username' not in session or 'user_id' not in session:
        logger.warning("Неавторизованный доступ к /api/contacts/clear POST")
        return jsonify({'success': False, 'error': 'Пользователь не авторизован'}), 401

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('DELETE FROM contacts WHERE user_id = ?', (session['user_id'],))
        conn.commit()
        conn.close()
        logger.info(f"Список контактов очищен для пользователя {session['username']}")
        return jsonify({'success': True, 'message': 'Список контактов очищен'}), 200
    except Exception as e:
        logger.error(f"Ошибка при очистке списка контактов: {e}")
        return jsonify({'success': False, 'error': 'Ошибка сервера'}), 500

@app.route('/api/contacts/remove', methods=['POST'])
def remove_contact():
    if 'username' not in session or 'user_id' not in session:
        logger.warning("Неавторизованный доступ к /api/contacts/remove POST")
        return jsonify({'success': False, 'error': 'Пользователь не авторизован'}), 401

    data = request.get_json()
    contact_username = data.get('contact_username')

    if not contact_username:
        logger.error("Имя контакта не указано")
        return jsonify({'success': False, 'error': 'Имя контакта обязательно'}), 400

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute('SELECT id FROM users WHERE username = ?', (contact_username,))
        contact = c.fetchone()
        if not contact:
            conn.close()
            logger.error(f"Контакт не найден: {contact_username}")
            return jsonify({'success': False, 'error': f'Контакт {contact_username} не найден'}), 404

        contact_id = contact[0]

        c.execute('DELETE FROM contacts WHERE user_id = ? AND contact_id = ?', 
                  (session['user_id'], contact_id))
        c.execute('DELETE FROM contacts WHERE user_id = ? AND contact_id = ?', 
                  (contact_id, session['user_id']))
        conn.commit()
        conn.close()
        logger.info(f"Контакт удален: {contact_username} для пользователя {session['username']}")
        return jsonify({'success': True, 'message': f'Контакт {contact_username} удален'}), 200
    except Exception as e:
        if 'conn' in locals():
            conn.close()
        logger.error(f"Ошибка при удалении контакта: {e}")
        return jsonify({'success': False, 'error': 'Ошибка сервера'}), 500

@app.route('/api/messages', methods=['POST'])
def send_message():
    if 'username' not in session or 'user_id' not in session:
        logger.warning("Неавторизованный доступ к /api/messages POST")
        return jsonify({'success': False, 'error': 'Пользователь не авторизован'}), 401

    data = request.get_json()
    logger.info(f"Полученные данные: {data}")
    if not data:
        logger.error("Отсутствует тело запроса")
        return jsonify({'success': False, 'error': 'Тело запроса отсутствует'}), 400

    target = data.get('target')
    mode = data.get('mode')
    text = data.get('text')
    time = data.get('time')

    logger.info(f"Данные для отправки: target={target}, mode={mode}, text={text}, time={time}, user_id={session.get('user_id')}")

    if not all([target, mode, text, time]):
        logger.error(f"Недостаточно данных для отправки сообщения: {data}")
        return jsonify({'success': False, 'error': 'Все поля обязательны'}), 400

    if mode not in ['contacts', 'groups']:
        logger.error(f"Недопустимый режим: {mode}")
        return jsonify({'success': False, 'error': 'Недопустимый режим'}), 400

    if not isinstance(session.get('user_id'), int):
        logger.error(f"Некорректный user_id: {session.get('user_id')}")
        return jsonify({'success': False, 'error': 'Некорректный идентификатор пользователя'}), 400

    try:
        # Обновляем активность отправителя
        update_user_activity(session['user_id'])
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        if mode == 'contacts':
            c.execute('SELECT id FROM users WHERE username = ?', (target,))
            contact = c.fetchone()
            if not contact:
                conn.close()
                logger.error(f"Контакт не найден: {target}")
                return jsonify({'success': False, 'error': f'Контакт {target} не найден'}), 404
                
            contact_id = contact[0]
            
            c.execute('SELECT 1 FROM contacts WHERE user_id = ? AND contact_id = ?', 
                      (session['user_id'], contact_id))
            if not c.fetchone():
                c.execute('INSERT OR IGNORE INTO contacts (user_id, contact_id) VALUES (?, ?)',
                          (session['user_id'], contact_id))
                c.execute('INSERT OR IGNORE INTO contacts (user_id, contact_id) VALUES (?, ?)',
                          (contact_id, session['user_id']))
                logger.info(f"Контакт автоматически добавлен: {target} <-> {session['username']}")

            c.execute('SELECT username FROM users WHERE id = ?', (session['user_id'],))
            sender_username = c.fetchone()[0]
            
            logger.info(f"Попытка вставки сообщения: sender_id={session['user_id']}, receiver_id={contact_id}, target={target}")
            
            # Сохраняем сообщение для отправителя (status='sent')
            c.execute('''INSERT INTO messages (sender_id, receiver_id, target, mode, text, time, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?)''',
                        (session['user_id'], contact_id, target, mode, text, time, 'sent'))
            
            # Сохраняем сообщение для получателя (status='sent', будет обновлено до 'read' при просмотре)
            c.execute('''INSERT INTO messages (sender_id, receiver_id, target, mode, text, time, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?)''',
                        (session['user_id'], contact_id, sender_username, mode, text, time, 'sent'))
                        
            logger.info(f"Сообщение сохранено для обоих пользователей: отправитель={sender_username}, получатель={target}")
        
        else:  # mode == 'groups'
            c.execute('SELECT id FROM groups WHERE name = ?', (target,))
            group = c.fetchone()
            if not group:
                conn.close()
                logger.error(f"Группа не найдена: {target}")
                return jsonify({'success': False, 'error': f'Группа {target} не найдена'}), 404
                
            c.execute('SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?', 
                      (group[0], session['user_id']))
            if not c.fetchone():
                conn.close()
                logger.error(f"Пользователь не в группе: {target}")
                return jsonify({'success': False, 'error': f'Вы не являетесь членом группы {target}'}), 403
                
            logger.info(f"Попытка вставки группового сообщения: sender_id={session['user_id']}, target={target}")
            c.execute('''INSERT INTO messages (sender_id, receiver_id, target, mode, text, time, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?)''',
                        (session['user_id'], 0, target, mode, text, time, 'sent'))  # 0 означает групповое сообщение
        
        conn.commit()
        logger.info(f"Сообщение успешно сохранено в базе данных")
        conn.close()
        logger.info(f"Сообщение отправлено: {text} от {session['username']} к {target} ({mode})")
        return jsonify({'success': True}), 201
        
    except Exception as e:
        if 'conn' in locals():
            conn.close()
        logger.error(f"Ошибка при отправке сообщения: {e}")
        return jsonify({'success': False, 'error': f'Ошибка сервера: {str(e)}'}), 500

@app.route('/api/messages', methods=['GET'])
def get_messages():
    if 'username' not in session or 'user_id' not in session:
        logger.warning("Неавторизованный доступ к /api/messages GET")
        return jsonify({'success': False, 'error': 'Пользователь не авторизован'}), 401

    mode = request.args.get('mode')
    target = request.args.get('target')
    since = request.args.get('since')

    if not mode or not target:
        logger.error(f"Недостаточно параметров: mode={mode}, target={target}")
        return jsonify({'success': False, 'error': 'Режим и цель обязательны'}), 400

    if mode not in ['contacts', 'groups']:
        logger.error(f"Недопустимый режим: {mode}")
        return jsonify({'success': False, 'error': 'Недопустимый режим'}), 400

    try:
        # Обновляем активность пользователя при получении сообщений
        update_user_activity(session['user_id'])
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        if mode == 'contacts':
            c.execute('SELECT id FROM users WHERE username = ?', (target,))
            contact = c.fetchone()
            if not contact:
                conn.close()
                logger.error(f"Контакт не найден: {target}")
                return jsonify({'success': False, 'error': f'Контакт {target} не найден'}), 404

            contact_id = contact[0]
            logger.info(f"Получение сообщений для контакта: {target} (id={contact_id})")

        elif mode == 'groups':
            c.execute('SELECT id FROM groups WHERE name = ?', (target,))
            group = c.fetchone()
            if not group:
                conn.close()
                logger.error(f"Группа не найдена: {target}")
                return jsonify({'success': False, 'error': f'Группа {target} не найдена'}), 404
            c.execute('SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?', 
                      (group[0], session['user_id']))
            if not c.fetchone():
                conn.close()
                logger.error(f"Пользователь не в группе: {target}")
                return jsonify({'success': False, 'error': f'Вы не являетесь членом группы {target}'}), 403

        query = '''SELECT m.id, m.text, m.time, m.status, m.sender_id, u.username
                   FROM messages m
                   JOIN users u ON m.sender_id = u.id
                   WHERE m.mode = ?'''
        params = [mode]
        
        if mode == 'contacts':
            query += ''' AND (
                        (m.sender_id = ? AND m.receiver_id = ? AND m.target = ?) OR 
                        (m.sender_id = ? AND m.receiver_id = ? AND m.target = ?)
                      )'''
            params.extend([
                session['user_id'], contact_id, target,  # Я -> Контакт
                contact_id, session['user_id'], session['username']  # Контакт -> Я
            ])
            logger.info(f"SQL запрос для личных сообщений: {query} с параметрами {params}")
        else:
            query += ' AND m.target = ?'
            params.append(target)
            
        if since:
            query += ' AND m.time > ?'
            params.append(since)
            
        query += ' ORDER BY m.time ASC'

        c.execute(query, params)
        
        seen_messages = set()
        messages = []
        
        for row in c.fetchall():
            msg_id, text, time, status, sender_id, sender_name = row
            msg_key = f"{sender_id}:{text}:{time}"
            
            if msg_key not in seen_messages:
                seen_messages.add(msg_key)
                messages.append({
                    'text': text,
                    'time': time,
                    'status': status,
                    'isSent': sender_id == session['user_id'],
                    'sender': sender_name
                })

        # Обновляем статус на 'read' только для входящих сообщений
        if mode == 'contacts':
            c.execute('''UPDATE messages 
                        SET status = 'read'
                        WHERE mode = ? 
                        AND target = ? 
                        AND sender_id = ? 
                        AND receiver_id = ? 
                        AND status = 'sent' ''',
                     (mode, session['username'], contact_id, session['user_id']))
        else:  # mode == 'groups'
            c.execute('''UPDATE messages 
                        SET status = 'read'
                        WHERE mode = ? 
                        AND target = ? 
                        AND sender_id != ? 
                        AND status = 'sent' ''',
                     (mode, target, session['user_id']))
        
        conn.commit()
        conn.close()

        logger.info(f"Сообщения получены для {mode}/{target}: {len(messages)} сообщений")
        return jsonify({'success': True, 'messages': messages}), 200
    except Exception as e:
        if 'conn' in locals():
            conn.close()
        logger.error(f"Ошибка при получении сообщений: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True, 'message': 'Выход выполнен успешно'}), 200

@app.route('/api/groups/clear', methods=['POST'])
def clear_groups():
    if 'username' not in session or 'user_id' not in session:
        logger.warning("Неавторизованный доступ к /api/groups/clear POST")
        return jsonify({'success': False, 'error': 'Пользователь не авторизован'}), 401

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        c.execute('''SELECT group_id FROM group_members 
                     WHERE user_id = ?''', (session['user_id'],))
        group_ids = [row[0] for row in c.fetchall()]
        
        c.execute('DELETE FROM group_members WHERE user_id = ?', (session['user_id'],))
        
        for group_id in group_ids:
            c.execute('SELECT COUNT(*) FROM group_members WHERE group_id = ?', (group_id,))
            count = c.fetchone()[0]
            if count == 0:
                c.execute('DELETE FROM groups WHERE id = ?', (group_id,))
                logger.info(f"Группа {group_id} удалена, так как в ней не осталось участников")
        
        conn.commit()
        conn.close()
        logger.info(f"Пользователь {session['username']} покинул все группы")
        return jsonify({'success': True, 'message': 'Вы покинули все группы'}), 200
    except Exception as e:
        logger.error(f"Ошибка при очистке списка групп: {e}")
        return jsonify({'success': False, 'error': 'Ошибка сервера'}), 500

@app.route('/api/groups/members', methods=['GET'])
def get_group_members():
    if 'username' not in session or 'user_id' not in session:
        logger.warning("Неавторизованный доступ к /api/groups/members GET")
        return jsonify({'success': False, 'error': 'Пользователь не авторизован'}), 401

    group_name = request.args.get('group')
    if not group_name:
        logger.error("Имя группы не указано")
        return jsonify({'success': False, 'error': 'Имя группы обязательно'}), 400

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        c.execute('SELECT id FROM groups WHERE name = ?', (group_name,))
        group = c.fetchone()
        if not group:
            conn.close()
            logger.error(f"Группа не найдена: {group_name}")
            return jsonify({'success': False, 'error': f'Группа {group_name} не найдена'}), 404
            
        group_id = group[0]
        
        c.execute('SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?', 
                  (group_id, session['user_id']))
        if not c.fetchone():
            conn.close()
            logger.error(f"Пользователь не в группе: {group_name}")
            return jsonify({'success': False, 'error': f'Вы не являетесь членом группы {group_name}'}), 403
            
        c.execute('''SELECT u.username 
                     FROM group_members gm 
                     JOIN users u ON gm.user_id = u.id 
                     WHERE gm.group_id = ?''', (group_id,))
        members = [row[0] for row in c.fetchall()]
        
        conn.close()
        logger.info(f"Получен список участников группы {group_name}: {members}")
        return jsonify({'success': True, 'members': members}), 200
    except Exception as e:
        if 'conn' in locals():
            conn.close()
        logger.error(f"Ошибка при получении участников группы: {e}")
        return jsonify({'success': False, 'error': 'Ошибка сервера'}), 500

@app.route('/api/groups/rename', methods=['POST'])
def rename_group():
    if 'username' not in session or 'user_id' not in session:
        logger.warning("Неавторизованный доступ к /api/groups/rename POST")
        return jsonify({'success': False, 'error': 'Пользователь не авторизован'}), 401

    data = request.get_json()
    old_name = data.get('oldName')
    new_name = data.get('newName')

    if not old_name or not new_name:
        logger.error("Не указаны старое или новое имя группы")
        return jsonify({'success': False, 'error': 'Оба имени группы обязательны'}), 400

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        c.execute('SELECT id FROM groups WHERE name = ?', (old_name,))
        group = c.fetchone()
        if not group:
            conn.close()
            logger.error(f"Группа не найдена: {old_name}")
            return jsonify({'success': False, 'error': f'Группа {old_name} не найдена'}), 404
            
        group_id = group[0]
        
        c.execute('SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?', 
                  (group_id, session['user_id']))
        if not c.fetchone():
            conn.close()
            logger.error(f"Пользователь не в группе: {old_name}")
            return jsonify({'success': False, 'error': f'Вы не являетесь членом группы {old_name}'}), 403
        
        c.execute('SELECT 1 FROM groups WHERE name = ? AND id != ?', (new_name, group_id))
        if c.fetchone():
            conn.close()
            logger.error(f"Группа с именем {new_name} уже существует")
            return jsonify({'success': False, 'error': f'Группа с именем {new_name} уже существует'}), 400
            
        c.execute('UPDATE groups SET name = ? WHERE id = ?', (new_name, group_id))
        c.execute('UPDATE messages SET target = ? WHERE target = ? AND mode = "groups"', 
                  (new_name, old_name))
        
        conn.commit()
        conn.close()
        logger.info(f"Группа {old_name} переименована в {new_name}")
        return jsonify({'success': True}), 200
    except Exception as e:
        if 'conn' in locals():
            conn.close()
        logger.error(f"Ошибка при переименовании группы: {e}")
        return jsonify({'success': False, 'error': 'Ошибка сервера'}), 500

@app.route('/api/groups/delete', methods=['POST'])
def delete_group():
    if 'username' not in session or 'user_id' not in session:
        logger.warning("Неавторизованный доступ к /api/groups/delete POST")
        return jsonify({'success': False, 'error': 'Пользователь не авторизован'}), 401

    data = request.get_json()
    group_name = data.get('name')

    if not group_name:
        logger.error("Имя группы не указано")
        return jsonify({'success': False, 'error': 'Имя группы обязательно'}), 400

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        c.execute('SELECT id FROM groups WHERE name = ?', (group_name,))
        group = c.fetchone()
        if not group:
            conn.close()
            logger.error(f"Группа не найдена: {group_name}")
            return jsonify({'success': False, 'error': f'Группа {group_name} не найдена'}), 404
            
        group_id = group[0]
        
        c.execute('SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?', 
                  (group_id, session['user_id']))
        if not c.fetchone():
            conn.close()
            logger.error(f"Пользователь не в группе: {group_name}")
            return jsonify({'success': False, 'error': f'Вы не являетесь членом группы {group_name}'}), 403
            
        c.execute('DELETE FROM group_members WHERE group_id = ?', (group_id,))
        c.execute('DELETE FROM groups WHERE id = ?', (group_id,))
        c.execute('DELETE FROM messages WHERE target = ? AND mode = "groups"', (group_name,))
        
        conn.commit()
        conn.close()
        logger.info(f"Группа {group_name} удалена")
        return jsonify({'success': True}), 200
    except Exception as e:
        if 'conn' in locals():
            conn.close()
        logger.error(f"Ошибка при удалении группы: {e}")
        return jsonify({'success': False, 'error': 'Ошибка сервера'}), 500

@app.route('/api/groups/members/add', methods=['POST'])
def add_members_to_group():
    if 'username' not in session or 'user_id' not in session:
        logger.warning("Неавторизованный доступ к /api/groups/members/add POST")
        return jsonify({'success': False, 'error': 'Пользователь не авторизован'}), 401

    data = request.get_json()
    group_name = data.get('group')
    new_members = data.get('members', [])

    if not group_name:
        logger.error("Имя группы не указано")
        return jsonify({'success': False, 'error': 'Имя группы обязательно'}), 400
    
    if not new_members:
        logger.error("Не указаны новые участники")
        return jsonify({'success': False, 'error': 'Должен быть хотя бы один новый участник'}), 400

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        c.execute('SELECT id FROM groups WHERE name = ?', (group_name,))
        group = c.fetchone()
        if not group:
            conn.close()
            logger.error(f"Группа не найдена: {group_name}")
            return jsonify({'success': False, 'error': f'Группа {group_name} не найдена'}), 404
            
        group_id = group[0]
        
        c.execute('SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?', 
                  (group_id, session['user_id']))
        if not c.fetchone():
            conn.close()
            logger.error(f"Пользователь не в группе: {group_name}")
            return jsonify({'success': False, 'error': f'Вы не являетесь членом группы {group_name}'}), 403
        
        placeholders = ','.join('?' * len(new_members))
        query = f'SELECT id, username FROM users WHERE LOWER(username) IN ({placeholders})'
        c.execute(query, [m.lower() for m in new_members])
        valid_members = c.fetchall()
        
        valid_usernames = [row[1] for row in valid_members]
        invalid_members = [m for m in new_members if m.lower() not in [vm.lower() for vm in valid_usernames]]
        if invalid_members:
            logger.error(f"Пользователи не найдены: {invalid_members}")
            conn.close()
            return jsonify({'success': False, 'error': f'Пользователи не найдены: {", ".join(invalid_members)}'}), 400
        
        added_count = 0
        for user_id, username in valid_members:
            c.execute('SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?', 
                      (group_id, user_id))
            if not c.fetchone():
                c.execute('INSERT INTO group_members (group_id, user_id) VALUES (?, ?)', 
                          (group_id, user_id))
                added_count += 1
                logger.info(f"Пользователь {username} добавлен в группу {group_name}")
        
        conn.commit()
        conn.close()
        
        if added_count > 0:
            logger.info(f"Добавлено {added_count} новых участников в группу {group_name}")
            return jsonify({'success': True, 'added_count': added_count}), 200
        else:
            logger.info(f"Новые участники не были добавлены в группу {group_name} (уже являются участниками)")
            return jsonify({'success': True, 'added_count': 0, 'message': 'Все указанные пользователи уже являются участниками группы'}), 200
    except Exception as e:
        if 'conn' in locals():
            conn.close()
        logger.error(f"Ошибка при добавлении участников в группу: {e}")
        return jsonify({'success': False, 'error': 'Ошибка сервера'}), 500

@app.route('/api/messages/deleteForAll', methods=['POST'])
def delete_message_for_all():
    if 'username' not in session or 'user_id' not in session:
        logger.warning("Неавторизованный доступ к /api/messages/deleteForAll POST")
        return jsonify({'success': False, 'error': 'Не авторизован'}), 401

    data = request.get_json()
    if not data or 'mode' not in data or 'target' not in data or 'time' not in data or 'text' not in data:
        logger.error("Неверные параметры запроса")
        return jsonify({'success': False, 'error': 'Неверные параметры запроса'}), 400

    mode = data['mode']
    target = data['target']
    time = data['time']
    text = data['text']
    
    sender_id = session['user_id']
    
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        if mode == 'contacts':
            # Находим ID получателя
            c.execute('SELECT id FROM users WHERE username = ?', (target,))
            receiver = c.fetchone()
            if not receiver:
                conn.close()
                logger.error(f"Контакт не найден: {target}")
                return jsonify({'success': False, 'error': 'Контакт не найден'}), 404
            
            receiver_id = receiver[0]

            # Удаляем сообщение для обоих пользователей
            c.execute('''DELETE FROM messages 
                        WHERE mode = ? 
                        AND sender_id = ? 
                        AND (receiver_id = ? OR receiver_id = ?)
                        AND time = ? 
                        AND text = ?''',
                      (mode, sender_id, receiver_id, 0, time, text))
            
            conn.commit()
            conn.close()
            logger.info(f"Сообщение удалено для всех в чате {mode}/{target}")
            return jsonify({'success': True, 'message': 'Сообщение удалено у всех'}), 200
        
        elif mode == 'groups':
            c.execute('SELECT id FROM groups WHERE name = ?', (target,))
            group = c.fetchone()
            if not group:
                conn.close()
                logger.error(f"Группа не найдена: {target}")
                return jsonify({'success': False, 'error': 'Группа не найдена'}), 404
            
            c.execute('''DELETE FROM messages 
                        WHERE mode = ? 
                        AND target = ? 
                        AND sender_id = ? 
                        AND time = ? 
                        AND text = ?''',
                      (mode, target, sender_id, time, text))
            
            conn.commit()
            conn.close()
            logger.info(f"Сообщение удалено для всех в группе {target}")
            return jsonify({'success': True, 'message': 'Сообщение удалено из группы'}), 200
        
        else:
            conn.close()
            logger.error(f"Недопустимый режим: {mode}")
            return jsonify({'success': False, 'error': 'Недопустимый режим'}), 400
            
    except Exception as e:
        if 'conn' in locals():
            conn.close()
        logger.error(f"Ошибка при удалении сообщения: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/translate', methods=['POST'])
def translate_text():
    if 'username' not in session or 'user_id' not in session:
        logger.warning("Неавторизованный доступ к /api/translate")
        return jsonify({'success': False, 'error': 'Пользователь не авторизован'}), 401
    
    data = request.get_json()
    text = data.get('text')
    source_lang = data.get('source_lang')  # auto, ru, en
    
    if not text:
        return jsonify({'success': False, 'error': 'Текст для перевода обязателен'}), 400
    
    try:
        # Улучшенное определение языка текста, если не указан
        if source_lang == 'auto' or not source_lang:
            ru_chars = 0
            en_chars = 0
            for char in text.lower():
                if 'а' <= char <= 'я' or char == 'ё':
                    ru_chars += 1
                elif 'a' <= char <= 'z':
                    en_chars += 1
            
            source_lang = 'ru' if ru_chars > en_chars else 'en'
            logger.info(f"Определен язык: {source_lang} (ru_chars: {ru_chars}, en_chars: {en_chars})")
        
        # Целевой язык
        target_lang = 'en' if source_lang == 'ru' else 'ru'
        
        # Попытка использовать Google Translate API через deep-translator
        try:
            # Создаем экземпляр переводчика
            translator = GoogleTranslator(source=source_lang, target=target_lang)
            
            # Используем Google Translate
            translated_text = translator.translate(text)
            
            logger.info(f"Google Translate: {text} ({source_lang}) -> {translated_text} ({target_lang})")
            return jsonify({
                'success': True, 
                'text': text,
                'translated_text': translated_text,
                'source_lang': source_lang,
                'target_lang': target_lang
            }), 200
            
        except Exception as e:
            # В случае ошибки с Google Translate используем резервный метод
            logger.warning(f"Ошибка Google Translate: {e}. Используем резервный метод.")
            
            # Простая транслитерация как резервный метод
            if source_lang == 'ru':
                # Русский -> Английский: просто указываем, что это перевод
                translated_text = f"Translation of: {text}"
            else:
                # Английский -> Русский: просто указываем, что это перевод
                translated_text = f"Перевод: {text}"
            
            logger.info(f"Резервный перевод: {text} ({source_lang}) -> {translated_text} ({target_lang})")
            return jsonify({
                'success': True, 
                'text': text,
                'translated_text': translated_text,
                'source_lang': source_lang,
                'target_lang': target_lang,
                'fallback': True # Флаг, что использован резервный метод
            }), 200
        
    except Exception as e:
        logger.error(f"Ошибка при переводе текста: {e}")
        return jsonify({'success': False, 'error': f'Ошибка сервера: {str(e)}'}), 500

@app.route('/api/messages/stats', methods=['GET'])
def get_messages_stats():
    """Endpoint для получения статистики сообщений для админ-панели"""
    if not session.get('is_admin'):
        logger.warning("Неавторизованный доступ к /api/messages/stats")
        return jsonify({'error': 'Необходимы права администратора'}), 401
    
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Получаем общее количество сообщений (считаем уникальные)
        c.execute('''
            SELECT COUNT(*) FROM (
                SELECT DISTINCT sender_id, receiver_id, text, time 
                FROM messages
            )
        ''')
        total_messages = c.fetchone()[0]
        
        # Получаем количество сообщений за последний день
        yesterday = datetime.now() - timedelta(days=1)
        yesterday_str = yesterday.strftime('%Y-%m-%d %H:%M:%S')
        
        c.execute('''
            SELECT COUNT(*) FROM (
                SELECT DISTINCT sender_id, receiver_id, text, time 
                FROM messages
                WHERE time > ?
            )
        ''', (yesterday_str,))
        recent_messages = c.fetchone()[0]
        
        # Текущая дата и время для расчетов
        now = datetime.now()
        
        # Получаем количество активных пользователей за последние 24 часа
        active_since = (now - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
        c.execute('''
            SELECT COUNT(*) FROM users 
            WHERE last_activity > ? AND is_admin = 0
        ''', (active_since,))
        active_users = c.fetchone()[0]
        
        # Получаем количество новых пользователей за сегодня
        # Для этого нам нужно получить пользователей, созданных сегодня
        # В качестве приближения мы используем id пользователей (предполагая, что id увеличивается последовательно)
        
        # Сначала получим минимальный ID для пользователей, зарегистрированных сегодня
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
        
        # Проверим наличие колонки created_at в таблице пользователей
        c.execute("PRAGMA table_info(users)")
        columns = [info[1] for info in c.fetchall()]
        
        if 'created_at' not in columns:
            # Если колонки нет, добавим её и установим текущее время для существующих пользователей
            c.execute('ALTER TABLE users ADD COLUMN created_at TIMESTAMP')
            c.execute('UPDATE users SET created_at = last_activity WHERE last_activity IS NOT NULL')
            c.execute('UPDATE users SET created_at = ? WHERE created_at IS NULL', (now.strftime('%Y-%m-%d %H:%M:%S'),))
            conn.commit()
            logger.info("Добавлена колонка created_at в таблицу users")
        
        # Теперь подсчитаем новых пользователей, созданных сегодня
        c.execute('''
            SELECT COUNT(*) FROM users 
            WHERE created_at >= ? AND is_admin = 0
        ''', (today_start,))
        new_users = c.fetchone()[0]
        
        # Общее количество пользователей
        c.execute('SELECT COUNT(*) FROM users WHERE is_admin = 0')
        total_regular_users = c.fetchone()[0]
        
        # Статистика по пользователям
        c.execute('''
            SELECT sender_id, COUNT(*) FROM (
                SELECT DISTINCT sender_id, text, time 
                FROM messages
            ) GROUP BY sender_id ORDER BY COUNT(*) DESC LIMIT 5
        ''')
        top_senders_data = c.fetchall()
        
        top_senders = []
        for sender_id, count in top_senders_data:
            c.execute('SELECT username FROM users WHERE id = ?', (sender_id,))
            username = c.fetchone()
            if username:
                top_senders.append({
                    'username': username[0],
                    'count': count
                })
        
        conn.close()
        
        logger.info(f"Статистика: всего сообщений {total_messages}, за последний день {recent_messages}, активных пользователей: {active_users}, новых пользователей: {new_users}")
        
        response = jsonify({
            'total_messages': total_messages,
            'recent_messages': recent_messages,
            'active_users': active_users,
            'new_users': new_users,
            'total_regular_users': total_regular_users,
            'top_senders': top_senders
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
        
    except Exception as e:
        logger.error(f"Ошибка при получении статистики сообщений: {e}")
        response = jsonify({'error': f'Ошибка сервера: {str(e)}'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 500

# Функция для обновления времени последней активности пользователя
def update_user_activity(user_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('UPDATE users SET last_activity = ? WHERE id = ?', 
                 (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), user_id))
        conn.commit()
        conn.close()
        logger.debug(f"Обновлено время активности для пользователя {user_id}")
    except Exception as e:
        logger.error(f"Ошибка при обновлении времени активности: {e}")

if __name__ == '__main__':
    app.run(debug=True, port=5000)