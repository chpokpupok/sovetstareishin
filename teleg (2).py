import logging
import difflib
import sqlite3
from datetime import datetime
import re
import telebot
from telebot import types
from dotenv import load_dotenv
import os

load_dotenv()
# Получаем переменные окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = telebot.TeleBot(BOT_TOKEN)


# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('elders_council.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        role TEXT,
        agreement_accepted BOOLEAN DEFAULT FALSE,
        join_date TIMESTAMP
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS questions (
        question_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        question_text TEXT,
        is_approved BOOLEAN DEFAULT FALSE,
        is_answered BOOLEAN DEFAULT FALSE,
        timestamp TIMESTAMP,
        votes INTEGER DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS answers (
        answer_id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id INTEGER,
        user_id INTEGER,
        answer_text TEXT,
        timestamp TIMESTAMP,
        FOREIGN KEY (question_id) REFERENCES questions (question_id),
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS moderation_queue (
        question_id INTEGER PRIMARY KEY,
        FOREIGN KEY (question_id) REFERENCES questions (question_id)
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_votes (
        user_id INTEGER,
        question_id INTEGER,
        vote_type TEXT CHECK(vote_type IN ('up', 'down')),
        PRIMARY KEY (user_id, question_id),
        FOREIGN KEY (user_id) REFERENCES users (user_id),
        FOREIGN KEY (question_id) REFERENCES questions (question_id)
    )''')

    conn.commit()
    conn.close()


# Проверка пользовательского соглашения
def check_agreement(user_id):
    conn = sqlite3.connect('elders_council.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT agreement_accepted FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result and result[0]


# Проверка на запрещенные слова
def contains_bad_words(text: str) -> bool:
    f = open("true_list.txt", encoding="UTF-8")
    s = []
    for k in f.readlines():
        s.append(k.replace("\n", ""))

    pattern = re.compile(r'\b(' + '|'.join(map(re.escape, s)) + r')\b', re.IGNORECASE)
    return bool(pattern.search(text))


# Проверка на дубликаты вопросов
def is_duplicate_question(question_text: str) -> bool:
    conn = sqlite3.connect('elders_council.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT question_text FROM questions WHERE is_approved = TRUE')
    existing_questions = [row[0] for row in cursor.fetchall()]
    conn.close()

    for existing in existing_questions:
        similarity = difflib.SequenceMatcher(None, question_text.lower(), existing.lower()).ratio()
        if similarity > 0.8:
            return True
    return False


# Проверка, голосовал ли уже пользователь
def has_user_voted(user_id, question_id):
    conn = sqlite3.connect('elders_council.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT vote_type FROM user_votes WHERE user_id = ? AND question_id = ?', (user_id, question_id))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None


# Обработчики команд
@bot.message_handler(commands=['start'])
def start(message):
    user = message.from_user
    conn = sqlite3.connect('elders_council.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user.id,))
    if not cursor.fetchone():
        cursor.execute('''
        INSERT INTO users (user_id, username, first_name, last_name, role, join_date)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (user.id, user.username, user.first_name, user.last_name, 'user', datetime.now()))
        conn.commit()
    conn.close()

    if check_agreement(user.id):
        show_main_menu(message)
    else:
        show_agreement(message)


def show_agreement(message):
    agreement_text = """
    *Пользовательское соглашение*

    1. Бот предназначен для анонимного общения.
    2. Запрещено использовать оскорбительную лексику.
    3. Вопросы проходят модерацию.
    4. Администрация оставляет за собой право блокировать пользователей.

    Нажимая "Принимаю", вы соглашаетесь с условиями.
    """

    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("Принимаю", callback_data='accept_agreement'))
    keyboard.add(types.InlineKeyboardButton("Отказываюсь", callback_data='decline_agreement'))

    bot.send_message(
        chat_id=message.chat.id,
        text=agreement_text,
        parse_mode='Markdown',
        reply_markup=keyboard
    )


@bot.message_handler(commands=['upgrade_rights'])
def msg_upgrd(message):
    bot.send_message(message.chat.id, text=f'Введите пароль')
    bot.register_next_step_handler(message, check_pass)


def check_pass(message):
    if message.text == '123123':
        conn = sqlite3.connect('elders_council.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE users
            SET role = ?
            WHERE user_id = ?
            ''', ('moder', message.from_user.id))
        conn.commit()
        conn.close()
        bot.send_message(message.chat.id, text=f'Теперь вы модератор!')

    if message.text == '321321':
        conn = sqlite3.connect('elders_council.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
                    UPDATE users
                    SET role = ?
                    WHERE user_id = ?
                    ''', ('ekspert', message.from_user.id))
        conn.commit()
        conn.close()
        bot.send_message(message.chat.id, text=f'Теперь вы эксперт!')


@bot.callback_query_handler(func=lambda call: call.data == 'accept_agreement')
def accept_agreement(call):
    user_id = call.from_user.id

    conn = sqlite3.connect('elders_council.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET agreement_accepted = TRUE WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

    bot.answer_callback_query(call.id, "Спасибо! Теперь вы можете пользоваться ботом.")
    show_main_menu(call.message)


def show_main_menu(message):
    menu_text = "Главное меню:"
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("Задать вопрос", callback_data='ask_question'))
    keyboard.add(types.InlineKeyboardButton("Топ вопросов", callback_data='top_questions'))
    keyboard.add(types.InlineKeyboardButton("Просмотреть вопросы", callback_data='view_questions'))
    keyboard.add(types.InlineKeyboardButton("Правила", callback_data='show_rules'))

    bot.send_message(
        chat_id=message.chat.id,
        text=menu_text,
        reply_markup=keyboard
    )


@bot.callback_query_handler(func=lambda call: call.data == 'ask_question')
def ask_question(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(
        chat_id=call.message.chat.id,
        text="Напишите ваш вопрос:"
    )
    bot.register_next_step_handler(msg, process_question)


def process_question(message):
    question_text = message.text
    user_id = message.from_user.id
    fl = True

    if contains_bad_words(question_text):
        bot.send_message(
            chat_id=user_id,
            text="Ваш вопрос содержит недопустимые слова. Пожалуйста, переформулируйте."
        )
        fl = False
        bot.register_next_step_handler(message, process_question)

    if is_duplicate_question(question_text):
        bot.send_message(
            chat_id=user_id,
            text="Такой вопрос уже задавался ранее."
        )
        show_main_menu(message)
        fl = False
        bot.register_next_step_handler(message, process_question)

    if fl:
        conn = sqlite3.connect('elders_council.db', check_same_thread=False)
        cursor = conn.cursor()

        cursor.execute('''
        INSERT INTO questions (user_id, question_text, timestamp)
        VALUES (?, ?, ?)
        ''', (user_id, question_text, datetime.now()))

        question_id = cursor.lastrowid
        cursor.execute('INSERT INTO moderation_queue (question_id) VALUES (?)', (question_id,))

        conn.commit()
        conn.close()

        bot.send_message(
            chat_id=user_id,
            text="Ваш вопрос отправлен на модерацию. Вы получите уведомление, когда он будет опубликован."
        )
        notify_moderators(question_id, question_text)
        show_main_menu(message)


def notify_moderators(question_id: int, question_text: str):

    conn = sqlite3.connect('elders_council.db', check_same_thread=False)
    cursor = conn.cursor()

    cursor.execute('''SELECT user_id FROM users WHERE role = 'moder' ''')
    user_ids = [row[0] for row in cursor.fetchall()]

    cursor.close()
    conn.close()




    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("Одобрить", callback_data=f'approve_{question_id}'),
        types.InlineKeyboardButton("Отклонить", callback_data=f'reject_{question_id}')
    )

    for i in user_ids:  # Извлекаем user_id из кортежа
        bot.send_message(
                chat_id=i,
                text=f"Новый вопрос на модерацию:\n\n{question_text}",
                reply_markup=keyboard
            )





@bot.callback_query_handler(func=lambda call: call.data.startswith(('approve_', 'reject_')))
def handle_moderation(call):
    action, question_id = call.data.split('_')
    question_id = int(question_id)

    conn = sqlite3.connect('elders_council.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT user_id, question_text FROM questions WHERE question_id = ?', (question_id,))
        user_id, question_text = cursor.fetchone()

        if action == 'approve':
            cursor.execute('UPDATE questions SET is_approved = TRUE WHERE question_id = ?', (question_id,))
            cursor.execute('DELETE FROM moderation_queue WHERE question_id = ?', (question_id,))
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="✅ Вопрос одобрен"
            )

            bot.send_message(
                chat_id=user_id,
                text=f"Ваш вопрос одобрен:\n\n{question_text}"
            )
        else:
            cursor.execute('DELETE FROM questions WHERE question_id = ?', (question_id,))
            cursor.execute('DELETE FROM moderation_queue WHERE question_id = ?', (question_id,))
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="❌ Вопрос отклонен"
            )

            bot.send_message(
                chat_id=user_id,
                text=f"Ваш вопрос отклонен:\n\n{question_text}"
            )

        conn.commit()
    except Exception as e:
        logger.error(f"Ошибка модерации: {e}")
        conn.rollback()
    finally:
        conn.close()


@bot.callback_query_handler(func=lambda call: call.data == 'top_questions')
def show_top_questions(call):
    bot.answer_callback_query(call.id)

    conn = sqlite3.connect('elders_council.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        cursor.execute('''
        SELECT question_id, question_text, votes 
        FROM questions 
        WHERE is_approved = TRUE
        ORDER BY votes DESC 
        LIMIT 10
        ''')

        top_questions = cursor.fetchall()

        if not top_questions:
            text = "⭐ Пока нет вопросов с высоким рейтингом."
            bot.send_message(call.message.chat.id, text=text)
        else:
            text = "🏆 Топ-10 вопросов:\n\n"
            keyboard = types.InlineKeyboardMarkup()

            for idx, (q_id, q_text, votes) in enumerate(top_questions, 1):
                text += f"{idx}. {q_text} (👍 {votes})\n"
                keyboard.add(types.InlineKeyboardButton(
                    f"{idx}. {q_text[:30]}... (👍 {votes})",
                    callback_data=f'view_question_{q_id}'
                ))

            bot.send_message(
                chat_id=call.message.chat.id,
                text="Выберите вопрос для просмотра:",
                reply_markup=keyboard
            )

    except sqlite3.Error as e:
        logger.error(f"Database error in top questions: {e}")
        bot.send_message(
            chat_id=call.message.chat.id,
            text="⚠ Ошибка при получении вопросов."
        )
    finally:
        conn.close()


@bot.callback_query_handler(func=lambda call: call.data.startswith('view_question_'))
def view_question(call):
    question_id = int(call.data.split('_')[2])
    user_id = call.from_user.id

    conn = sqlite3.connect('elders_council.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        # Получаем информацию о вопросе
        cursor.execute('''
        SELECT question_text, votes, is_answered 
        FROM questions 
        WHERE question_id = ? AND is_approved = TRUE
        ''', (question_id,))
        question = cursor.fetchone()

        if not question:
            bot.answer_callback_query(call.id, "Вопрос не найден или не одобрен")
            return

        question_text, votes, is_answered = question
        text = f"❓ Вопрос:\n{question_text}\n\n👍 Голосов: {votes}\n"

        # Получаем ответы на вопрос
        cursor.execute('''
        SELECT a.answer_text, u.first_name, u.role 
        FROM answers a
        JOIN users u ON a.user_id = u.user_id
        WHERE a.question_id = ?
        ORDER BY a.timestamp
        ''', (question_id,))
        answers = cursor.fetchall()

        if answers:
            text += "\n📝 Ответы:\n"
            for idx, (answer_text, first_name, role) in enumerate(answers, 1):
                text += f"\n{idx}. {answer_text}\n   — {first_name} ({role})\n"
        elif is_answered:
            text += "\nℹ На вопрос пока нет ответов, но он помечен как отвеченный."
        else:
            text += "\nℹ На вопрос пока нет ответов."

        # Создаем клавиатуру с кнопками голосования
        keyboard = types.InlineKeyboardMarkup()

        # Проверяем, голосовал ли уже пользователь
        user_vote = has_user_voted(user_id, question_id)

        if user_vote != 'up':
            keyboard.add(types.InlineKeyboardButton("👍 Поддержать", callback_data=f'vote_up_{question_id}'))
        if user_vote != 'down':
            keyboard.add(types.InlineKeyboardButton("👎 Против", callback_data=f'vote_down_{question_id}'))

        # Добавляем кнопку для ответа (только для экспертов и модераторов)
        cursor.execute('SELECT role FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        user_role = result[0] if result else 'user'

        if user_role in ['ekspert', 'moder']:
            keyboard.add(types.InlineKeyboardButton("✏ Ответить", callback_data=f'answer_{question_id}'))

        keyboard.add(types.InlineKeyboardButton("🔙 Назад к вопросам", callback_data='view_questions'))

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=text,
            reply_markup=keyboard
        )

    except Exception as e:
        logger.error(f"Error viewing question: {e}")
        bot.answer_callback_query(call.id, "Ошибка при загрузке вопроса")
    finally:
        conn.close()


@bot.callback_query_handler(func=lambda call: call.data.startswith(('vote_up_', 'vote_down_')))
def handle_vote(call):
    try:
        # Разбираем callback data более надёжно
        if call.data.startswith('vote_up_'):
            vote_type = 'up'
            question_id = int(call.data.replace('vote_up_', ''))
        elif call.data.startswith('vote_down_'):
            vote_type = 'down'
            question_id = int(call.data.replace('vote_down_', ''))
        else:
            logger.error(f"Invalid vote callback: {call.data}")
            return

        user_id = call.from_user.id
        logger.info(f"Processing vote: user={user_id}, type={vote_type}, question={question_id}")

        conn = sqlite3.connect('elders_council.db', check_same_thread=False)
        cursor = conn.cursor()

        # Проверяем текущий голос
        cursor.execute('SELECT vote_type FROM user_votes WHERE user_id=? AND question_id=?',
                      (user_id, question_id))
        existing = cursor.fetchone()

        # Получаем текущие голоса
        cursor.execute('SELECT votes FROM questions WHERE question_id=?', (question_id,))
        current_votes = cursor.fetchone()[0]

        if existing:
            existing_type = existing[0]
            if existing_type == vote_type:
                # Отмена голоса
                cursor.execute('DELETE FROM user_votes WHERE user_id=? AND question_id=?',
                             (user_id, question_id))
                new_votes = current_votes - 1 if vote_type == 'up' else current_votes + 1
            else:
                # Смена голоса
                cursor.execute('UPDATE user_votes SET vote_type=? WHERE user_id=? AND question_id=?',
                             (vote_type, user_id, question_id))
                new_votes = current_votes + 1 if vote_type == 'up' else current_votes - 1
        else:
            # Новый голос
            cursor.execute('INSERT INTO user_votes (user_id, question_id, vote_type) VALUES (?,?,?)',
                         (user_id, question_id, vote_type))
            new_votes = current_votes + 1 if vote_type == 'up' else current_votes - 1

        # Обновляем счётчик
        cursor.execute('UPDATE questions SET votes=? WHERE question_id=?',
                      (new_votes, question_id))
        conn.commit()

        bot.answer_callback_query(call.id, "Голос учтён!")
        view_question(call)  # Обновляем сообщение

    except Exception as e:
        logger.error(f"Vote error: {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Ошибка голосования")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

@bot.callback_query_handler(func=lambda call: call.data.startswith('answer_'))
def answer_question(call):
    question_id = int(call.data.split('_')[1])
    user_id = call.from_user.id

    # Проверяем, является ли пользователь экспертом или модератором
    conn = sqlite3.connect('elders_council.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT role FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    user_role = result[0] if result else 'user'

    if user_role not in ['ekspert', 'moder']:
        bot.answer_callback_query(call.id, "Только эксперты могут отвечать на вопросы")
        return

    msg = bot.send_message(
        chat_id=call.message.chat.id,
        text="Напишите ваш ответ на вопрос:"
    )
    bot.register_next_step_handler(msg, process_answer, question_id)


def process_answer(message, question_id):
    answer_text = message.text
    user_id = message.from_user.id

    # Регистрируем адаптер для datetime (решение проблемы с DeprecationWarning)
    sqlite3.register_adapter(datetime, lambda dt: dt.isoformat())

    conn = sqlite3.connect('elders_council.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        # Добавляем ответ в базу данных
        cursor.execute('''
        INSERT INTO answers (question_id, user_id, answer_text, timestamp)
        VALUES (?, ?, ?, ?)
        ''', (question_id, user_id, answer_text, datetime.now()))

        # Помечаем вопрос как отвеченный
        cursor.execute('''
        UPDATE questions 
        SET is_answered = TRUE 
        WHERE question_id = ?
        ''', (question_id,))

        conn.commit()

        # Получаем текст вопроса для уведомления
        cursor.execute('SELECT question_text FROM questions WHERE question_id = ?', (question_id,))
        question_text = cursor.fetchone()[0]

        # Отправляем подтверждение
        bot.send_message(
            chat_id=message.chat.id,
            text=f"✅ Ваш ответ на вопрос «{question_text[:50]}...» успешно добавлен."
        )



    except Exception as e:
        logger.error(f"Error saving answer: {e}")
        bot.send_message(
            chat_id=message.chat.id,
            text="⚠ Произошла ошибка при сохранении ответа. Пожалуйста, попробуйте позже."
        )
    finally:
        conn.close()


@bot.callback_query_handler(func=lambda call: call.data == 'view_questions')
def view_questions(call, page=1):
    QUESTIONS_PER_PAGE = 5
    bot.answer_callback_query(call.id)

    conn = sqlite3.connect('elders_council.db', check_same_thread=False)
    cursor = conn.cursor()

    try:
        # Получаем общее количество одобренных вопросов
        cursor.execute('SELECT COUNT(*) FROM questions WHERE is_approved = TRUE')
        total_questions = cursor.fetchone()[0]
        total_pages = max(1, (total_questions + QUESTIONS_PER_PAGE - 1) // QUESTIONS_PER_PAGE)

        # Определяем текущую страницу
        if hasattr(call, 'data') and call.data.startswith('view_questions_page_'):
            try:
                page = int(call.data.split('_')[-1])
            except Exception:
                page = 1

        offset = (page - 1) * QUESTIONS_PER_PAGE

        # Получаем вопросы для текущей страницы
        cursor.execute('''
        SELECT question_id, question_text, votes, is_answered 
        FROM questions 
        WHERE is_approved = TRUE
        ORDER BY timestamp DESC
        LIMIT ? OFFSET ?
        ''', (QUESTIONS_PER_PAGE, offset))
        questions = cursor.fetchall()

        if not questions:
            bot.send_message(
                chat_id=call.message.chat.id,
                text="ℹ Пока нет одобренных вопросов."
            )
            return

        keyboard = types.InlineKeyboardMarkup()

        for q_id, q_text, votes, is_answered in questions:
            status = "✅" if is_answered else "❓"
            keyboard.add(types.InlineKeyboardButton(
                f"{status} {q_text[:30]}... (👍 {votes})",
                callback_data=f'view_question_{q_id}'
            ))

        # Кнопки пагинации
        pagination_buttons = []
        if page > 1:
            pagination_buttons.append(types.InlineKeyboardButton(
                "⬅️ Назад", callback_data=f'view_questions_page_{page-1}'
            ))
        if page < total_pages:
            pagination_buttons.append(types.InlineKeyboardButton(
                "Вперёд ➡️", callback_data=f'view_questions_page_{page+1}'
            ))
        if pagination_buttons:
            keyboard.row(*pagination_buttons)

        keyboard.add(types.InlineKeyboardButton("🔙 Назад", callback_data='back_to_main'))

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"Выберите вопрос для просмотра:\nСтраница {page} из {total_pages}",
            reply_markup=keyboard
        )

    except Exception as e:
        logger.error(f"Error viewing questions: {e}")
        bot.answer_callback_query(call.id, "Ошибка при загрузке вопросов")
    finally:
        conn.close()

# Обработчик callback для пагинации
@bot.callback_query_handler(func=lambda call: call.data.startswith('view_questions_page_'))
def handle_questions_pagination(call):
    try:
        page = int(call.data.split('_')[-1])
    except Exception:
        page = 1
    view_questions(call, page)


@bot.callback_query_handler(func=lambda call: call.data == 'back_to_main')
def back_to_main(call):
    show_main_menu(call.message)


@bot.callback_query_handler(func=lambda call: call.data == 'show_rules')
def show_rules(call):
    bot.answer_callback_query(call.id)

    rules_text = """
    Правила чат-бота
Целью чат-бота является расширение коммуникаций между ветеранами УГНТУ и молодежью.
Телеграмм-бот «Совет старейшин» предназначен для задания вопросов студентами, молодыми
преподавателями и получения ответов от ветеранов, позволяющий получить управляемый инструмент
коммуникации поддержании динамики информационного обмена в сообществе «Семья УГНТУ».
Обсуждаемые вопросы в телеграмм-боте касаются деятельности УГНТУ: учебная, научная и профессиональная.
Работа чат-бота регламентируется пользовательским соглашением.
    """

    bot.send_message(
        chat_id=call.message.chat.id,
        text=rules_text,
        parse_mode='Markdown'
    )
    show_main_menu(call.message)


if __name__ == '__main__':
    init_db()
    bot.polling(none_stop=True)