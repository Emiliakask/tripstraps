# Trips-Traps-Trull

Tumedas minimalistlikus stiilis eestikeelne trips-traps-trull. Mängi samal seadmel sõbraga, arvuti vastu või teise mängijaga kahes eraldi telefonis.

**Avalik mäng:** [tripstraps.pplx.app](https://tripstraps.pplx.app)

## Võimalused

- **Kaks mängijat samal seadmel:** X ja O käivad kordamööda.
- **Arvutivastane:** sina oled X, arvuti O. Arvuti alustab juhusliku käiguga ning proovib hiljem võita ja sinu võiduliini blokeerida.
- **Kaks telefoni:** üks loob toa ja teine liitub kuuekohalise toakoodiga. Käigud, tulemused ja skoor sünkroonitakse serveri kaudu.
- **Võidud ja viigid:** selged teated, kolm rohelist võiduruutu ning vooru lõpus lukustuv mängulaud.
- **Ühine skoor ja uus voor:** võrgumängus kinnitavad uue vooru mõlemad mängijad; skoor säilib.
- **Telefonisõbralik kujundus:** ümarad ruudud, sujuvad hõljumisefektid, klaviatuuritugi ja vähendatud liikumise eelistuse arvestamine.

HTML, CSS ja JavaScript on koos ühes failis `public/index.html`. Võrgumäng kasutab lisaks Python/Flaski serverit ja SQLite-andmebaasi. See koodipakett on iseseisvalt käivitatav ega vaja Computeri ühendusi, salavõtmeid ega eelvaate URL-e.

## Kiire käivitamine

Vaja on Python 3.10 või uuemat versiooni.

```sh
git clone https://github.com/Emiliakask/tripstraps.git
cd tripstraps
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python server.py
```

Windowsis käivita virtuaalkeskkond käsuga `.venv\Scripts\activate`.

Ava brauseris [http://localhost:8787](http://localhost:8787). Nii kasutajaliides kui ka `/api` töötavad sama aadressi kaudu.

Kui avad ainult faili `public/index.html`, saad mängida samal seadmel ja arvuti vastu. **Kahe telefoni režiim vajab töötavat serverit.** Ainult HTML-i majutamine, näiteks GitHub Pagesis, ei paku mängutubade serverit.

## Kahe telefoniga mängimine

1. Ava mõlemas telefonis sama majutatud mängu veebiaadress.
2. Vali **Mängi kahe telefoniga**.
3. Esimeses telefonis vali **Loo mängutuba**. Looja saab sümboli X.
4. Teises telefonis sisesta toakood ja vali **Liitu toaga**. Liituja saab O.
5. X alustab. Mõlemad näevad sama mängulauda.
6. Uueks vooruks vajutab üks **Uus mäng** ja teine **Kinnita uus mäng**.

Avalikul veebilehel mängimiseks vajavad mõlemad telefonid internetti, mitte sama Wi-Fit ega Bluetoothi.

## Serveri majutamine

Linuxi tootmiskeskkonnas saab kasutada kaasasolevat Gunicorni:

```sh
GAME_DB=data.db python -m gunicorn \
  --bind 0.0.0.0:8787 \
  --workers 1 \
  --threads 4 \
  --timeout 60 \
  server:app
```

- Suuna oma HTTPS-aadressi liiklus selle serveri pordile 8787.
- Kasutajaliides ja API peavad olema **samal päritolul**. Eraldi CORS-teenust pole vaja.
- Kasuta selles versioonis ühte Gunicorni tööprotsessi: mälus olevad päringupiirangud on protsessipõhised.
- `GAME_DB` määrab andmebaasi faili asukoha; vaikimisi tekib `rooms.sqlite3` serveri kõrvale. Faili vanemkaust peab olema kirjutatav.
- Serverivaba või ainult staatilise majutuse korral tuleb mängutubade server ja ühiskasutatav andmebaas eraldi kohandada. Praegune SQLite-lahendus eeldab ühte töötavat serverit ja kirjutatavat failisüsteemi.

## Piirangud ja turvalisus

- Mängutuba aegub 24 tundi pärast loomist. See ei ole serveri tööaja garantii.
- Mängija ligipääsutunnus säilib ainult avatud brauserivaates. Lehe sulgemisel või uuesti laadimisel tuleb luua uus tuba. Ajutise võrguühenduse katkemisel proovib sama avatud vaade ühenduse taastada.
- Toast lahkumine sulgeb toa. Uue sõbraga mängimiseks loo uus tuba.
- Andmebaasis on ajutised mänguseisud, skoorid ja mängijatunnuste räsid. **Ära lisa andmebaasi GitHubi ega serveeri seda staatilise failina.**
- Kohalik andmebaas võib majutuse uuendamisel kaduda. Säilimise tagamiseks kasuta püsivat andmeketast ja varukoopiaid.
- Server kontrollib iga käiku, vooru numbrit ja mängija luba. Teise mängija käigujärjekorda ei saa kasutajaliidest muutes üle võtta.
- Loomise/liitumise ning mängijapäringute sagedus on piiratud. Andmebaasi ei kirjutata igal olekupäringul.
- Isikuandmeid, paroole, väliseid API-võtmeid, küpsistepõhist sisselogimist ega vestlust mäng ei kasuta.

## Testid

```sh
python -m unittest -v test_server.py
```

Testid kasutavad eraldi ajutist andmebaasi. Kontrollitakse mõlema mängija võiduliine, viiki, üheksanda käigu võitu, käigujärjekorda, hõivatud ruute, ligipääsukontrolli, tubade eraldatust, uue vooru kinnitamist ja toast lahkumist.

## Failid

```text
public/index.html           HTML, CSS ja JavaScript ühes failis
server.py                   Mängutubade API ja staatilise lehe server
requirements.txt            Fikseeritud Pythoni sõltuvused
test_server.py              Automaatsed serveritestid
docs/tripstraps-qr-kood.png  Avaliku mängu QR-kood
```

## QR-kood

Allolev QR-kood avab avaliku mängu aadressil [https://tripstraps.pplx.app](https://tripstraps.pplx.app).

![Trips-Traps-Trull mängu QR-kood](docs/tripstraps-qr-kood.png)
