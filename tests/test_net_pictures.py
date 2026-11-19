"""app/net/pictures.py — пак картинок оборудования в хранилище: индекс при первом подключении, поиск, состояния.

Тесты доказывают, что

* пак в хранилище индексируется теми же правилами, что и папка на ПК инженера: механизм берётся из имени файла и
  из имени папки, состояние — из слова (off/on/alarm, работа/авария) или из цвета (зелёный/красный/серый);
* у механизма столько состояний, сколько картинок есть на самом деле (3, 4 — не фиксированные три);
* индекс пишется рядом с паком и второй раз не пересобирается;
* поиск идёт по смыслу: «нория авария» находит набор с аварией, а не просто файл с таким словом.
"""
import io
from urllib.parse import unquote_plus

from app.net import files, pictures

BOSS = {"role": "superuser", "username": "sysai"}


def _png(color=(200, 40, 40), size=(16, 16)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _pack(rights) -> None:
    """Нория с тремя состояниями и шнек с четырьмя — как в настоящем паке."""
    for name, color in (("нория off.png", (128, 128, 128)), ("нория работа.png", (40, 160, 40)),
                        ("нория авария.png", (200, 40, 40))):
        files.put(rights, f"{pictures.PACK}/Нория/{name}", data=_png(color))
    for name, color in (("shnekOff.png", (128, 128, 128)), ("shnekOn1.png", (40, 160, 40)),
                        ("shnekOn2.png", (40, 160, 40)), ("shnekAlarm.png", (200, 40, 40))):
        files.put(rights, f"{pictures.PACK}/Шнек/{name}", data=_png(color))


def test_the_pack_is_indexed_on_the_first_call_and_understood_by_equipment(client):
    rights = files.for_person(BOSS)
    _pack(rights)
    got = pictures.build(rights)
    stats = got["stats"]
    assert stats["pictures"] == 7 and stats["sets"] == 2 and stats["equipment"] == 2
    assert stats["saved"] is True
    kinds = {k["equipment"]: k for k in pictures.overview(rights)["kinds"]}
    assert kinds["нория"]["pictures"] == 3 and kinds["нория"]["states"] == ["alarm", "off", "on"]
    assert kinds["шнек"]["pictures"] == 4 and kinds["шнек"]["states"] == ["alarm", "off", "on"]


def test_a_mechanism_has_as_many_states_as_it_really_has(client):
    rights = files.for_person(BOSS)
    _pack(rights)
    found = pictures.find(rights, "шнек")
    assert found["found"] == 1
    one = found["sets"][0]
    assert one["equipment"] == "шнек"
    assert set(one["states"]) == {"off", "on", "alarm"}          # on1 и on2 — кадры одного состояния
    assert len(one["files"]) == 4


def test_the_search_goes_by_meaning_not_by_the_word_in_the_name(client):
    rights = files.for_person(BOSS)
    _pack(rights)
    found = pictures.find(rights, "нория авария")
    assert found["found"] == 1
    one = found["sets"][0]
    assert one["equipment"] == "нория" and "alarm" in one["states"]
    assert one["states"]["alarm"].endswith("нория авария.png")


def test_the_index_is_written_next_to_the_pack_and_not_rebuilt_every_time(client):
    rights = files.for_person(BOSS)
    _pack(rights)
    first = pictures.build(rights)["index"]
    again = pictures.load(rights)
    assert again["updated"] == first["updated"] and len(again["pictures"]) == 7
    assert files.info(rights, f"{pictures.PACK}/{pictures.INDEX_NAME}")["size"] > 0


def test_an_empty_pack_says_so_instead_of_failing(client):
    rights = files.for_person(BOSS)
    got = pictures.build(rights)
    assert got["stats"]["pictures"] == 0 and got["stats"]["sets"] == 0
    assert pictures.overview(rights)["kinds"] == []


def test_the_page_shows_the_pack_and_searches_by_meaning(client, net_on):
    rights = files.for_person(BOSS)
    _pack(rights)
    page = client.get("/pictures").text
    assert "Картинки оборудования" in page and "нория" in page and "шнек" in page
    found = client.get("/pictures", params={"q": "нория авария"}).text
    assert "нория" in found and "alarm" in found
    r = client.post("/pictures/index", follow_redirects=False)
    said = unquote_plus(r.headers["location"])
    assert "msg=" in said and "наборов 2" in said


def test_what_the_pack_lacks_is_named_so_the_agent_draws_only_that(client):
    rights = files.for_person(BOSS)
    _pack(rights)
    got = pictures.missing(rights, "нория", ["off", "on", "alarm", "warning"])
    assert got["have"] == ["alarm", "off", "on"]
    assert got["missing"] == ["warning"] and got["complete"] is False
    full = pictures.missing(rights, "нория", ["off", "on", "alarm"])
    assert full["missing"] == [] and full["complete"] is True
    assert pictures.missing(rights, "дробилка", ["on"])["missing"] == ["on"]
