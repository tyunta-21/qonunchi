# Qonunchi — tekshiruvchi uchun qoʻllanma / Инструкция для проверяющего

**Sayt / Сайт:** http://3.27.43.72
**API kaliti / Ключ API:** talaba alohida yuboradi / студент пришлёт отдельно
**Kod / Код:** https://github.com/tyunta-21/qonunchi

Sayt bulutda (AWS) doimiy ishlaydi, talabaning kompyuteri kerak emas.
Сайт постоянно работает в облаке (AWS), компьютер студента для этого не нужен.

---

## 1. Saytni koʻrish / Посмотреть сайт (brauzerda / в браузере)

- **Bosh sahifa / Главная:** qidiruv, Konstitutsiya va kodekslar.
- **Hujjatlar / Документы:** filtrlar bilan katalog (turi, kuchda / kuchini yoʻqotgan, yil).
- **Qidiruv / Поиск:** barcha moddalar matni boʻyicha.
- **Hujjat sahifasi / Страница документа:** moddalar boʻyicha toʻliq matn, uz/ru almashtirish, lex.uz dagi aslga havola.
- **AI-yordamchi / ИИ-помощник:** har sahifadagi tugma. Faqat topilgan moddalar boʻyicha javob beradi va [1], [2] havolalarini qoʻyadi.

Masalan soʻrang / Например, спросите: *«Nikoh yoshi necha yosh?»*, *«Сколько дней длится ежегодный отпуск?»*

## 2. RAG API (/v1) — TZ boʻyicha / по ТЗ

Barcha soʻrovlarda sarlavha / Во всех запросах заголовок: `Authorization: Bearer <KALIT>`

| Soʻrov / Запрос | Nima qiladi / Что делает |
|---|---|
| `GET /v1/health` | holat / состояние (kalitsiz / без ключа) |
| `GET /v1/meta` | model, indeks, lex.uz sanasi |
| `POST /v1/rag/query` | bitta savol / один вопрос |
| `POST /v1/rag/batch` | 1–10 savol (11+ → 400) |
| `GET /v1/rag/batch/{batch_id}` | batch natijasi / результат batch |

Misol / Пример:
```
curl -X POST http://3.27.43.72/v1/rag/query \
  -H "Authorization: Bearer KALIT" -H "Content-Type: application/json" \
  -d '{"question": "Nikoh yoshi necha yosh?"}'
```

## 3. 100 savollik test / Тест на 100 вопросов (ixtiyoriy / по желанию)

Python 3.10+ kerak / Нужен Python 3.10+:
```
git clone https://github.com/tyunta-21/qonunchi && cd qonunchi
python3 eval/run_eval.py eval/testset_100.csv --url http://3.27.43.72 --key KALIT
python3 eval/report.py eval/testset_100.csv
```
O'zingizning savollaringiz bilan ham ishlaydi: CSV formati TZ (6-boʻlim) dagidek.
Можно подставить свой набор вопросов: формат CSV как в ТЗ (раздел 6).
Natija / Результат: Hit@5 (hujjat va modda), MRR, no-answer, toʻqib chiqarilgan va eskirgan havolalar, tezlik.

## Muhim / Важно

- Bu yuridik maslahat emas, maʼlumotnoma / Это справка, а не юридическая консультация.
- Himoya: bitta manzildan soatiga 30 ta savol (sayt), kalit boʻyicha sekundiga 5 ta soʻrov (API).
  Защита от расходов: 30 вопросов в час с одного адреса на сайте, 5 запросов в секунду на ключ в API.
