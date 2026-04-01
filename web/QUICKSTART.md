# Quick Start Guide — cc-unpacker-web

## 🚀 Запуск за 30 секунд

```bash
cd /home/openclaw/repos/mini-apps/cc-unpacker-web
./start.sh
```

Открой в браузере: **http://localhost:8765**

## 📦 Использование

1. Введи npm пакет (например: `@types/react`)
2. Опционально укажи версию (по умолчанию `latest`)
3. Нажми **Unpack**
4. Дождись завершения (прогресс бар)
5. Выбери файл из дерева слева
6. Скачай ZIP со всеми файлами (кнопка справа вверху)

## 🧪 Тестовые пакеты

**Пакеты с source maps (работают):**
- `@types/node` — TypeScript definitions с embedded sources
- `vue` — некоторые билды содержат maps
- `@babel/core` — может содержать source maps

**Пакеты БЕЗ source maps (не работают):**
- `react` — production builds без maps
- `left-pad` — маленький пакет без maps
- Большинство production пакетов

> **Примечание:** Не все npm пакеты публикуются с source maps. Это нормально — инструмент показывает корректную ошибку.

## 🛠️ Управление

**Остановить сервер:**
```bash
# Нажми Ctrl+C в терминале где запущен start.sh
# Или
pkill -f "python3 main.py"
```

**Очистить базу данных:**
```bash
rm jobs.db
```

**Посмотреть логи:**
```bash
# Если запущен через start.sh — логи в терминале
# Или
tail -f server.log  # если запущен в фоне
```

## 🔧 Troubleshooting

### Порт 8765 уже занят
```bash
# Измени порт в main.py, последняя строка:
# uvicorn.run("main:app", host="0.0.0.0", port=8888, reload=True)
```

### ModuleNotFoundError
```bash
# Установи зависимости:
pip install --break-system-packages fastapi 'uvicorn[standard]'
```

### Пакет не распаковывается
- Проверь, что пакет существует в npm registry
- Убедись, что у пакета есть source maps (большинство production пакетов их не имеют)
- Проверь логи сервера для деталей ошибки

## 📊 Системные требования

- **Python:** 3.11+
- **RAM:** минимум 512MB (для пакетов до 50MB)
- **Disk:** ~100MB для зависимостей
- **Browser:** Любой современный (Chrome, Firefox, Safari)

## 🎯 Архитектура

```
Browser (index.html)
    ↓ HTTP/JSON
FastAPI Server (main.py)
    ↓ Jobs
SQLite DB (jobs.db) + Threading
    ↓ Unpacking
cc-unpacker logic (unpacker.py)
    ↓ npm registry
httpx → npm registry → tarball download
    ↓ extraction
Source map parser → Reconstructed sources
```

## 🔗 Полезные ссылки

- **Репозиторий:** `/home/openclaw/repos/mini-apps/cc-unpacker-web/`
- **Документация:** `README.md`
- **Итоговый отчёт:** `SUMMARY.md`
- **Исходный CLI инструмент:** `/home/openclaw/repos/mini-apps/cc-unpacker/`

---

**Готово. Работает. Наслаждайся! 🦾**
