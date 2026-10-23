# emasz-data

Az áramszolgáltató (MVM Hálózat / ÉMÁSZ) negyedórás fogyasztási adatait tölti be a Home Assistant **Energia** irányítópultjába.

A működés:

1. Az MVM Partnerportál minden nap emailben elküldi az előző napi adatokat egy CSV melléklettel (a levél tárgya: „Napi riport").
2. A script IMAP-on keresztül megnézi a postafiókot, és kiolvassa az olvasatlan „Napi riport" leveleket.
3. A CSV-ből órás összesítést készít, és a Home Assistant WebSocket API-ján keresztül külső statisztikaként feltölti.
4. A feldolgozott leveleket olvasottnak jelöli. Ez csak sikeres feltöltés után történik meg.

A script két adatsort hoz létre (kWh):

| Statisztika azonosító | Név |
|---|---|
| `energia:halozati_vetel` | Hálózatból vételezett |
| `energia:halozatba_betaplalt` | Hálózatba betáplált |

## A CSV formátuma

A CSV ilyen formában érkezik a szolgáltatótól, negyedórás felbontásban:

```csv
Gyáriszám;Azonosító;Dátum;Idő;Hálózatból vételezett;Mértékegység;Státusz;Státusz megnevezés;Hálózatba betáplált;Mértékegység;Státusz;Státusz megnevezés;Szaldó;Mértékegység;Státusz;Státusz megnevezés
1234;1234-1234;2026.10.22;0:00:00;5,200,000,000,000;kWh;IU012;Érték érvényes;0;kWh;;;0;kWh;;
1234;1234-1234;2026.10.22;0:15:00;4,800,000,000,000;kWh;IU012;Érték érvényes;0;kWh;;;0;kWh;;
```

## Előkészületek

### 1. Külön Gmail cím létrehozása

Érdemes **új, külön Gmail címet** létrehozni erre a célra. Így a postafiókban csak az áramszolgáltató levelei lesznek. Ez azért jó, mert:

- a script nem fér hozzá a személyes leveleidhez,
- az IMAP jelszót nem a fő fiókodhoz kell megadni,
- az „olvasatlan" jelzés nem keveredik a saját leveleiddel.

### 2. IMAP beállítása a Gmailben

1. Jelentkezz be az új Gmail fiókba.
2. Kapcsold be a kétlépcsős azonosítást (Google Fiók → Biztonság → Kétlépcsős azonosítás). Az alkalmazásjelszóhoz ez kötelező.
3. Hozz létre **alkalmazásjelszót**: <https://myaccount.google.com/apppasswords>. Adj neki tetszőleges nevet (pl. `emasz-data`). A kapott 16 karakteres jelszót használd `IMAP_PASSWORD` értékként, szóközök nélkül. A normál Google jelszó nem működik.
4. Ellenőrizd, hogy az IMAP engedélyezve van-e: Gmail → Beállítások (fogaskerék) → *Az összes beállítás megtekintése* → *Továbbítás és POP/IMAP* → *IMAP-hozzáférés: IMAP engedélyezése*. Az újabb Gmail fiókoknál ez a beállítás már nem biztos, hogy megjelenik, mert az IMAP alapból be van kapcsolva.
5. Az IMAP szerver: `imap.gmail.com` (SSL, 993-as port). A script ezt automatikusan használja.

### 3. Regisztráció az MVM Partnerportálon

1. Regisztrálj itt: <https://partnerportal.mvmhalozat.hu/aram/login>
2. A beállításoknál kapcsold be az **„Előző napi adatok email küldése"** opciót. Add meg az **új Gmail címet** email címként.
3. Ezután minden nap kapsz egy „Napi riport" tárgyú emailt a CSV melléklettel.

A régebbi adatokat a portálról manuálisan is letöltheted CSV-ben. Ezeket a `--csv` kapcsolóval töltheted be egyszer (lásd lentebb).

### 4. Home Assistant hosszú élettartamú hozzáférési token

1. Home Assistant → bal alsó sarokban a **profilod** neve → **Biztonság** fül.
2. Görgess le a **Hosszú élettartamú hozzáférési tokenek** részhez, és kattints a **Token létrehozása** gombra.
3. Adj neki nevet (pl. `emasz-data`), majd másold ki a tokent. **Később már nem lehet újra megnézni.**
4. Ez lesz a `HA_TOKEN` értéke.

A `HA_URL` a Home Assistant WebSocket címe:

- HTTP esetén: `ws://homeassistant.local:8123/api/websocket`
- HTTPS esetén: `wss://ha.pelda.hu/api/websocket`

## Beállítás

Másold le a mintát, és töltsd ki a saját adataiddal:

```sh
cp .env.example .env
```

| Változó | Leírás |
|---|---|
| `HA_URL` | A Home Assistant WebSocket címe |
| `HA_TOKEN` | Hosszú élettartamú hozzáférési token |
| `IMAP_HOST` | `imap.gmail.com` |
| `IMAP_USER` | Az új Gmail cím |
| `IMAP_PASSWORD` | A Gmail **alkalmazásjelszó** |
| `IMAP_FOLDER` | Postafiók mappa (alapértelmezés: `INBOX`) |
| `STORE` | A negyedórás adatok helyi tárolója (alapértelmezés: `hourly_store.json`) |
| `CHECK_INTERVAL` | Levélellenőrzés gyakorisága másodpercben (alapértelmezés: `600`) |


## Futtatás

### Docker (ajánlott)

```sh
docker build -t emasz-data .
docker run -d --name emasz-data --restart unless-stopped \
  --env-file .env \
  -e STORE=/data/hourly_store.json \
  -v emasz-data:/data \
  emasz-data
```

A konténer `--daemon` módban fut: 10 percenként új „Napi riport" levelet keres. Ha feldolgozott egyet, 23 órát vár a következő ellenőrzésig.

A `-v emasz-data:/data` volume fontos, mert enélkül a tároló a konténer újralétrehozásakor elvész. Ilyenkor a script csak az újabb leveleket látná, és az összegzés (`sum`) hibás lenne.

Log megtekintése:

```sh
docker logs -f emasz-data
```

### Közvetlenül Pythonnal

```sh
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 ha_import.py --daemon
```

### Egyéb használat

```sh
# egyszeri betöltés a postafiók összes leveléből (múltbeli adatok)
python3 ha_import.py --mail

# csak az utolsó 7 nap levelei
python3 ha_import.py --mail --days 7

# manuálisan letöltött CSV fájlok betöltése
python3 ha_import.py --csv a.csv b.csv

# ellenőrzés feltöltés nélkül
python3 ha_import.py --csv a.csv --dry-run
```

## Megjelenítés a Home Assistantban

A feltöltés után az adatok külső statisztikaként jelennek meg:

1. **Beállítások → Irányítópultok → Energia**
2. A **Hálózati fogyasztás** résznél válaszd a `Hálózatból vételezett` statisztikát.
3. Ha van napelemed, a **Visszatáplálás a hálózatba** résznél válaszd a `Hálózatba betáplált` statisztikát.

A statisztikák nem érzékelők (entity), ezért az Energia irányítópulton és a statisztika-grafikon kártyán érhetők el.

## Hibaelhárítás

| Üzenet | Teendő |
|---|---|
| `HA authentikacio sikertelen (token?)` | Ellenőrizd a `HA_TOKEN` értékét, és hogy a `HA_URL` jó címre mutat-e. |
| `imaplib.IMAP4.error: ... AUTHENTICATIONFAILED` | Alkalmazásjelszót használj, ne a normál jelszót. A kétlépcsős azonosításnak be kell lennie kapcsolva. |
| `nincs uj level` | Nincs olvasatlan „Napi riport" levél. Nézd meg, hogy a portálon be van-e kapcsolva az email küldés. |
| `nincs CSV melleklet, kihagyva` | A levélben nincs `.csv` fájl, ezért a script kihagyta. |
| `FIGYELEM: ... oraban nem 4 negyedora van` | Hiányos adat. Letölthető a portálról, és betölthető a `--csv` kapcsolóval. |

## Adatvédelem

- A `.env`, a `hourly_store.json` és a CSV fájlok személyes adatokat tartalmaznak, ezeket ne commitold. A `.gitignore` kizárja őket.
- A tokent és a jelszót csak a `.env` fájlban vagy környezeti változóban tárold.
