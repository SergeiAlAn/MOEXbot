# Сертификаты НУЦ Минцифры

MOEX перевёл публичные сервисы (в т.ч. `iss.moex.com`) на TLS-сертификаты
Национального удостоверяющего центра. В стандартном CA-бандле Python (`certifi`)
их нет — без этих файлов aiohttp получает `CERTIFICATE_VERIFY_FAILED`.

Источник: https://gu-st.ru/content/Other/doc/  
Инструкция Биржи: https://www.moex.com/kak-sohranit-dostup-k-servisam-birzhi

- `russian_trusted_root_ca.cer` — корневой
- `russian_trusted_sub_ca.cer` — выпускающий (промежуточный)
