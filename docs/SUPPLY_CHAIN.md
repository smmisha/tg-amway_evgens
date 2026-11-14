# Supply chain: lock-файлы с хэшами (TG-F-08)

## Зачем

Раньше `requirements.txt` содержал только нижние границы (`pkg>=x.y`). Версии и
содержимое пакетов не фиксировались, а установка в CI не проверяла целостность:
скомпрометированный релиз зависимости или подмена артефакта прошли бы молча.
Теперь CI ставит зависимости из lock-файла, где каждый пакет закреплён `==` и
сопровождается SHA-256-хэшами (`pip install --require-hashes`).

## Файлы

| Файл | Роль |
|------|------|
| `requirements.in` | входной список прямых runtime-зависимостей; правится вручную |
| `requirements.lock` | сгенерированный lock (`==` + `--hash=sha256:`); ставится в `prepare.yml`, `publish.yml`, `datadome-probe.yml` |
| `requirements-responder.in` | входной список для лёгкого responder-джоба (`httpx`, `python-dotenv`) |
| `requirements-responder.lock` | lock для `responder.yml` (чтобы каждые 5 минут не ставить playwright/scrapling) |
| `requirements.txt` | человекочитаемая справка (нижние границы). CI **не** ставит из него |

## Генерация lock-файлов

Нужен Python 3.12 (как в CI) и `pip-tools` — это инструмент разработчика, он не
является runtime-зависимостью и в `requirements.in` не добавляется:

```bash
python -m pip install --upgrade "pip-tools>=7.4"

python -m piptools compile requirements.in \
    --generate-hashes --strip-extras --output-file requirements.lock

python -m piptools compile requirements-responder.in \
    --generate-hashes --strip-extras --output-file requirements-responder.lock
```

Почему так:

- `--generate-hashes` добавляет хэши **всех** артефактов каждой закреплённой
  версии (sdist + колёса всех платформ), поэтому lock, сгенерированный на одной
  ОС, проверяем и на Linux-раннере GitHub Actions;
- `--strip-extras` фиксирует современное поведение pip-tools и не меняет
  зависимости (extras всё равно разрешаются в конкретные пакеты);
- lock-файлы коммитятся в репозиторий; вручную их не редактируем. Любое
  изменение `requirements*.in` сопровождается перегенерацией и ревью diff.

## Установка

```bash
pip install --require-hashes -r requirements.lock
pip install --require-hashes -r requirements-responder.lock
```

`--require-hashes` заставляет pip проверять каждый артефакт по хэшу и падать при
любом несовпадении или отсутствии пиннинга/хэша.

## Проверка перед коммитом

Структурная проверка (все пакеты закреплены и имеют `--hash=sha256:`):

```bash
python - <<'PY'
import re, sys
for name in ("requirements.lock", "requirements-responder.lock"):
    text = open(name, encoding="utf-8").read()
    packages = re.findall(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+)", text, re.M)
    hashes = len(re.findall(r"--hash=sha256:", text))
    assert packages, f"{name}: нет пиннинга"
    assert hashes >= len(packages), f"{name}: не у каждого пакета есть хэш"
    print(f"{name}: {len(packages)} пакетов, {hashes} хэшей — OK")
PY
```

Проверка артефактов под Linux/Python 3.12 без установки (и без riscv-сюрпризов):

```bash
python -m pip download --no-deps --only-binary=:all: \
    --platform manylinux2014_x86_64 --platform manylinux_2_28_x86_64 \
    --python-version 3.12 --implementation cp --abi cp312 \
    --require-hashes -r requirements.lock -d /tmp/lock-check
```

## Обновление зависимостей

1. Изменить соответствующий `requirements*.in`.
2. Перегенерировать lock командами выше.
3. Проверить diff (новые версии/пакеты, отсутствие лишних зависимостей).
4. Прогнать проверки из предыдущего раздела и тесты; закоммитить `.in` и `.lock`
   одним изменением.

Периодически (или через Dependabot/Renovate) update-сессию стоит повторять:
пиннинг фиксирует версии, но не закрывает уязвимости в них.

## Ограничения

- Lock сгенерирован `pip-tools 7.6.2` на Python 3.12.10 — том же minor, что и в
  CI (`setup-python: 3.12`). При смене Python в CI lock нужно перегенерировать.
- `pip-tools` и `pytest` намеренно не входят в runtime-lock.
- Пиннинг по хэшам не отменяет необходимости обновлять зависимости: это защита от
  подмены артефактов, а не от уязвимостей в закреплённых версиях.
